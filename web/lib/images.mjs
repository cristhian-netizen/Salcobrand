// Image URLs authenticate with the HttpOnly session cookie alone: no per-tab query parameter, so the browser
// cache holds across tabs, reloads and screens. `w` asks the server for its cached thumbnail variant (grids use
// 256; the full image is fetched only on click/zoom). Data URIs and foreign URLs pass through untouched.
export function imageUrl(src, w) {
  if (!src || typeof src !== 'string' || !src.startsWith('/')) return src;
  if (!w) return src;
  return src + (src.includes('?') ? '&' : '?') + 'w=' + w;
}
