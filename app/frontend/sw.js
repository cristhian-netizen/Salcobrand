/* Service worker de la app de tienda (/tienda).
   - Precarga el cascarón (HTML, CSS, JS, manifest, íconos) para arrancar sin conexión.
   - /api, /v1 y /uploads nunca se cachean (van directo a la red).
   - Navegaciones: red primero (4 s), si falla el /tienda cacheado.
   - CSS/JS versionados por ?v=: caché primero (una versión nueva cambia la URL y este archivo).
   Al publicar una versión nueva: cambiar VERSION aquí y en <meta name="tienda-version"> de tienda.html. */
const VERSION = "2026.11.05-3";
const CACHE = "tienda-" + VERSION;
const SHELL = [
  "/tienda",
  "/static/tienda.css?v=" + VERSION,
  "/static/tienda.js?v=" + VERSION,
  "/manifest.webmanifest",
  "/static/assets/pwa/icon-192.png",
  "/static/assets/pwa/icon-512.png",
];
const NETWORK_ONLY = /^\/(api|v1|uploads)(\/|$)/;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL.map((u) => new Request(u, { cache: "reload", credentials: "same-origin" }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("tienda-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("timeout")), ms);
    promise.then((v) => { clearTimeout(t); resolve(v); }, (e) => { clearTimeout(t); reject(e); });
  });
}

async function networkFirst(request, fallbackKey, ms) {
  const cache = await caches.open(CACHE);
  try {
    const res = await withTimeout(fetch(request), ms);
    if (res && res.ok) cache.put(fallbackKey, res.clone()).catch(() => {});
    return res;
  } catch (e) {
    const cached = await cache.match(fallbackKey);
    if (cached) return cached;
    throw e;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const res = await fetch(request);
  if (res && res.ok) cache.put(request, res.clone()).catch(() => {});
  return res;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (NETWORK_ONLY.test(url.pathname)) return;          // la API y las fotos nunca pasan por el caché
  if (req.mode === "navigate") {
    event.respondWith(networkFirst(req, "/tienda", 4000));
    return;
  }
  const key = url.pathname + url.search;
  if (SHELL.includes(key)) {
    event.respondWith(cacheFirst(req));
    return;
  }
  // otros estáticos (p. ej. apple-touch-icon): red, y si no hay red lo que haya en caché
  event.respondWith(fetch(req).catch(() => caches.match(req).then((c) => c || Response.error())));
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});
