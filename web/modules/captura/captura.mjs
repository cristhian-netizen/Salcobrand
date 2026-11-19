// Pure helpers for the anonymous capture page (/captura#<token>), tested with node:test.
// The token travels in the URL FRAGMENT so it never reaches server access logs; the page reads
// it from location.hash and sends it as a Bearer header on every call.

// 32-100 url-safe chars (secrets.token_urlsafe shape); anything else is treated as no link at all.
export function parseToken(hash) {
  const token = String(hash || '').replace(/^#/, '');
  return /^[A-Za-z0-9_-]{32,100}$/.test(token) ? token : null;
}

// What the screen shows. The link decides; the page only reflects it:
// 'inactive' (no/expired/revoked token), 'error' (server/network), 'loading', 'full', 'ready'.
export function stateOf({token, loading, errorStatus, photosLeft}) {
  if (!token || errorStatus === 401 || errorStatus === 410) return 'inactive';
  if (errorStatus != null) return 'error'; // 0 means network failure: retryable, NOT "inactive"
  if (loading) return 'loading';
  if (photosLeft <= 0) return 'full';
  return 'ready';
}

// A dead link reads the same whether it expired, was revoked or arrived already full: one polite
// line, nothing to probe. Only a session that DID send photos earns the thank-you variant.
export function messageFor(state, sent = 0) {
  if (state === 'inactive') return 'Este enlace ya no está activo.';
  if (state === 'full') {
    return sent > 0 ? 'Se envió todo: este enlace alcanzó su máximo de fotos. ¡Gracias!'
      : 'Este enlace ya no está activo.';
  }
  return null;
}

export const counterText = sent => (sent === 1 ? '1 foto enviada ✓' : `${sent} fotos enviadas ✓`);
export const progressText = (done, total) => `Subiendo ${done}/${total}…`;
export const remainingText = left => (left === 1 ? 'Queda 1 foto disponible' : `Quedan ${left} fotos disponibles`);

// Sequential upload bookkeeping: one plain object in, one out, so retry cannot drift.
// state = {sent, photosLeft, failed: [File], failMessage}
export const freshSession = photosLeft => ({sent: 0, photosLeft, failed: [], failMessage: ''});

export function afterUpload(state, outcome) {
  if (outcome.ok) {
    return {...state, sent: state.sent + 1,
            photosLeft: typeof outcome.photosLeft === 'number' ? outcome.photosLeft : state.photosLeft - 1};
  }
  // 410: the link died mid-session; 409: it filled up. Both stop the queue, keep what was sent.
  if (outcome.status === 401 || outcome.status === 410) return {...state, photosLeft: 0, failed: [], failMessage: ''};
  if (outcome.status === 409) return {...state, photosLeft: 0, failed: [], failMessage: ''};
  return {...state, failed: [...state.failed, outcome.file], failMessage: outcome.message || 'No se pudo enviar la foto.'};
}

// The retry queue is exactly the files that failed, oldest first, and taking them clears the slate.
export const retryQueue = state => ({files: state.failed, state: {...state, failed: [], failMessage: ''}});
