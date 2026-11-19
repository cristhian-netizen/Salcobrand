'use client';
// Anonymous capture page: field people WITHOUT any account send shelf photos through a link.
// - Deliberately unbranded and generic: no name, no logo, neutral palette, system font. The page
//   reveals nothing about whose system it is, so a forwarded link exposes nothing.
// - The token lives in location.hash (never sent in the path, so never in access logs) and goes
//   out as a Bearer header to the two public endpoints; the link fixes category/PDV/limits.
// - The native camera File goes straight into FormData — no canvas, no resize, no re-encode —
//   exactly like DatasetImages.jsx, so the server stores the phone's original bytes verbatim.
import {useEffect, useRef, useState} from 'react';
import {parseToken, stateOf, messageFor, counterText, progressText, remainingText,
        freshSession, afterUpload, retryQueue} from './captura.mjs';

// A plain gray dot: the runtime replacement for the portal favicon (the exported HTML carries the
// site-wide icons; removing them here keeps the branded one from ever showing on this page).
const NEUTRAL_ICON = 'data:image/svg+xml,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="#9ca3af"/></svg>');

async function call(path, token, {method = 'GET', form} = {}) {
  let response;
  try {
    response = await fetch(path, {method, body: form, cache: 'no-store',
                                  headers: {Accept: 'application/json', Authorization: `Bearer ${token}`}});
  } catch {
    const offline = new Error('Sin conexión. Revisa tu señal e inténtalo de nuevo.');
    offline.status = 0;
    throw offline;
  }
  let body = null;
  try { body = await response.json(); } catch {}
  if (!response.ok) {
    const error = new Error(typeof body?.detail === 'string' ? body.detail : 'No se pudo completar el envío.');
    error.status = response.status;
    throw error;
  }
  return body;
}

export default function CapturePage() {
  const [token, setToken] = useState(undefined); // undefined until the hash is read in the browser
  const [link, setLink] = useState(null);        // {category, photos_left}
  const [errorStatus, setErrorStatus] = useState(null);
  const [errorText, setErrorText] = useState('');
  const [session, setSession] = useState(freshSession(0));
  const [progress, setProgress] = useState(null); // {done, total} while files go up one by one
  const cameraInput = useRef(null);
  const galleryInput = useRef(null);

  useEffect(() => {
    // The portal's exported <head> links its branded icons on every route: strip them and pin the dot.
    document.querySelectorAll('link[rel*="icon"]').forEach(node => node.remove());
    const icon = document.createElement('link');
    icon.rel = 'icon';
    icon.href = NEUTRAL_ICON;
    document.head.appendChild(icon);
    setToken(parseToken(window.location.hash));
  }, []);

  async function load(current) {
    setErrorStatus(null); setErrorText('');
    try {
      const info = await call('/api/public/dataset/link', current);
      setLink(info);
      setSession(s => ({...s, photosLeft: info.photos_left}));
    } catch (e) {
      setErrorStatus(e.status ?? 500); setErrorText(e.message);
    }
  }

  useEffect(() => { if (token) load(token); }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  async function send(files) {
    if (!files.length || progress) return;
    let current = session;
    for (let index = 0; index < files.length; index++) {
      setProgress({done: index + 1, total: files.length});
      const form = new FormData();
      // The File object as-is: appended untouched, streamed untouched, stored byte-identical.
      form.append('files', files[index], files[index].name || 'foto');
      try {
        const result = await call('/api/public/dataset/images', token, {method: 'POST', form});
        current = afterUpload(current, {ok: true, photosLeft: result.photos_left});
      } catch (e) {
        if (e.status === 401 || e.status === 410) { setErrorStatus(410); current = afterUpload(current, {ok: false, status: 410}); break; }
        current = afterUpload(current, {ok: false, status: e.status, file: files[index], message: e.message});
        if (e.status === 409) break; // the link filled up: what landed stays counted
      }
      setSession(current);
    }
    setSession(current);
    setProgress(null);
  }

  function pick(input) {
    const files = [...(input.files || [])];
    input.value = ''; // the same photo can be chosen again later
    send(files);
  }

  function retry() {
    const {files, state} = retryQueue(session);
    setSession(state);
    send(files);
  }

  const state = token === undefined ? 'loading'
    : stateOf({token, loading: !link && !errorStatus, errorStatus, photosLeft: session.photosLeft});
  const closed = messageFor(state, session.sent);

  return <main className="cap-page">
    {state === 'loading' && <p className="cap-note" role="status">Cargando…</p>}
    {state === 'error' && <div className="cap-center">
      <p className="cap-note" role="alert">{errorText || 'No se pudo cargar.'}</p>
      <button type="button" className="cap-secondary" onClick={() => load(token)}>Reintentar</button>
    </div>}
    {closed && <div className="cap-center">
      {session.sent > 0 && <p className="cap-counter">{counterText(session.sent)}</p>}
      <p className="cap-note">{closed}</p>
    </div>}
    {!closed && state === 'ready' && <div className="cap-body">
      <header className="cap-head">
        <h1>{link.category}</h1>
        <p>{remainingText(session.photosLeft)}</p>
      </header>
      <button type="button" className="cap-main" disabled={!!progress} onClick={() => cameraInput.current?.click()}>
        Tomar fotos
      </button>
      <button type="button" className="cap-secondary" disabled={!!progress} onClick={() => galleryInput.current?.click()}>
        Elegir de la galería
      </button>
      {progress && <p className="cap-progress" role="status"><span className="cap-spin" aria-hidden="true"/>{progressText(progress.done, progress.total)}</p>}
      {session.sent > 0 && !progress && <p className="cap-counter" role="status">{counterText(session.sent)}</p>}
      {session.failed.length > 0 && !progress && <div className="cap-fail" role="alert">
        <p>{session.failMessage} {session.failed.length === 1 ? 'Falta 1 foto.' : `Faltan ${session.failed.length} fotos.`}</p>
        <button type="button" className="cap-secondary" onClick={retry}>Reintentar</button>
      </div>}
      <p className="cap-hint">Las fotos se envían tal cual, una por una. Mantén la pantalla abierta hasta ver el ✓.</p>
    </div>}
    <input ref={cameraInput} type="file" accept="image/*" capture="environment" multiple hidden onChange={e => pick(e.target)}/>
    <input ref={galleryInput} type="file" accept="image/*" multiple hidden onChange={e => pick(e.target)}/>
  </main>;
}
