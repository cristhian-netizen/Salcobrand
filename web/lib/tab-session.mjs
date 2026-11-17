// Only a cookie selector lives in sessionStorage. Credentials remain HttpOnly.
const KEY = 'neuravision.tab-session';
export const SESSION_HEADER = 'X-Portal-Session';
let memoryId;

export const createTabSession = () => globalThis.crypto.randomUUID().replaceAll('-', '');

export function setTabSession(id) {
  memoryId = id;
  try { window.sessionStorage.setItem(KEY, id); } catch {}
}

export function getTabSession() {
  if (typeof window === 'undefined') return null;
  let id;
  try { id = window.sessionStorage.getItem(KEY); } catch {}
  if (/^[a-f0-9]{32}$/.test(id || '')) return id;
  if (!memoryId) memoryId = createTabSession();
  setTabSession(memoryId);
  return memoryId;
}

export function sessionHeaders() {
  const id = getTabSession();
  return id ? {[SESSION_HEADER]: id} : {};
}

// Images and direct downloads cannot send a custom header. The selector alone
// grants no access: the matching HttpOnly session cookie is still required.
export function sessionUrl(value) {
  if (!value || typeof window === 'undefined') return value;
  const url = new URL(value, window.location.origin);
  if (url.origin !== window.location.origin || !/^\/(api|uploads|catalog-images|static)(\/|$)/.test(url.pathname)) return value;
  url.searchParams.set('portal_session', getTabSession());
  return url.pathname + url.search + url.hash;
}
