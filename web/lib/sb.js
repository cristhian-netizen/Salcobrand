// Same-origin client with an independent HttpOnly session cookie per tab.
import {createTabSession, setTabSession, sessionHeaders, SESSION_HEADER} from './tab-session.mjs';
export {sessionUrl} from './tab-session.mjs';
import {normalizeUser} from './profiles.mjs';
export {ROLE_NAMES} from './profiles.mjs';
const listeners = new Set();
let pending = 0;

export function subscribeSession(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export const hasPendingMutation = () => pending > 0;

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

function detailOf(body, status) {
  const d = body?.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map(x => x?.msg || String(x)).join(' ');
  if (status === 401) return 'Tu sesión expiró. Inicia sesión nuevamente.';
  if (status === 403) return 'Tu perfil no tiene permiso para esta acción.';
  if (status >= 500) return 'El servidor no pudo completar la operación. Intenta nuevamente.';
  return 'No se pudo completar la solicitud.';
}

export async function api(path, { method = 'GET', body, form, timeout = 30000, raw = false, silent401 = false, headers: extraHeaders = {} } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const mutating = method !== 'GET';
  if (mutating) pending++;
  try {
    const headers = { Accept: 'application/json', ...sessionHeaders(), ...extraHeaders };
    let payload;
    if (form) payload = form;
    else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
    const response = await fetch(path, { method, headers, body: payload, credentials: 'same-origin', cache: 'no-store', signal: controller.signal });
    if (!response.ok) {
      let parsed = null;
      try { parsed = await response.json(); } catch {}
      if (response.status === 401 && !silent401) listeners.forEach(fn => fn());
      throw new ApiError(detailOf(parsed, response.status), response.status);
    }
    if (raw) return response;
    if (response.status === 204) return null;
    const type = response.headers.get('content-type') || '';
    return type.includes('application/json') ? response.json() : response.text();
  } catch (error) {
    if (error.name === 'AbortError') throw new ApiError('El servidor tardó demasiado en responder.', 0);
    if (error instanceof TypeError) throw new ApiError('No se pudo conectar con el servidor. Revisa tu conexión.', 0);
    throw error;
  } finally {
    clearTimeout(timer);
    if (mutating) pending--;
  }
}

export const auth = {
  login: async (username, password) => {
    const id = createTabSession();
    const result = await api('/api/auth/login', { method: 'POST', body: { username, password }, silent401: true, headers: {[SESSION_HEADER]: id} });
    setTabSession(id);
    return result;
  },
  me: async () => normalizeUser(await api('/api/auth/me', { silent401: true })),
  logout: () => api('/api/auth/logout', { method: 'POST', silent401: true }),
  changePassword: (current_password, new_password) => api('/api/auth/change-password', { method: 'POST', body: { current_password, new_password } }),
};

export async function download(path, filename) {
  const response = await api(path, { raw: true, timeout: 120000 });
  saveBlob(await response.blob(), filename);
}

export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export const fmt = {
  date: v => { const d = new Date(v); return Number.isNaN(d.valueOf()) ? '—' : d.toLocaleDateString('es-CL', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'America/Santiago' }); },
  dateTime: v => { const d = new Date(v); return Number.isNaN(d.valueOf()) ? '—' : d.toLocaleString('es-CL', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'America/Santiago' }); },
  ago: v => {
    const d = new Date(v); if (Number.isNaN(d.valueOf())) return '—';
    const s = Math.round((Date.now() - d.valueOf()) / 1000);
    if (s < 60) return 'hace un momento'; if (s < 3600) return `hace ${Math.round(s / 60)} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`; const days = Math.round(s / 86400); return days === 1 ? 'ayer' : `hace ${days} días`;
  },
  pct: v => (typeof v === 'number' && Number.isFinite(v)) ? `${v.toLocaleString('es-CL', { maximumFractionDigits: 1 })} %` : '—',
  num: v => (typeof v === 'number' && Number.isFinite(v)) ? v.toLocaleString('es-CL') : '—',
};
