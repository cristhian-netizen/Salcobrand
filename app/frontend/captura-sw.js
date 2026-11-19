/* Service worker de la captura de fotos por enlace (/captura/<código>), servido en /captura/sw.js con alcance /captura/.
   - Precarga los archivos de la página (CSS, JS, ícono) y guarda la página de cada enlace abierto: el enlace abre sin
     señal y las fotos guardadas en el teléfono se siguen enviando después.
   - /captura/<código>/estado, /foto y demás llamadas nunca pasan por el caché (van directo a la red).
   - Navegación: red primero (4 s); sin señal, la página guardada de ese enlace (o la de otro enlace: es la misma).
   Al publicar una versión: cambiar VERSION aquí y en captures.VERSION (app/backend/captures.py). */
const VERSION = "2026.11.19-sb3";
const CACHE = "sb-captura-" + VERSION;
const SHELL = [
  "/static/captura.css?v=" + VERSION,
  "/static/captura.js?v=" + VERSION,
  "/static/assets/pwa/icon-192.png",
];
const PAGINA = /^\/captura\/[a-z0-9][a-z0-9-]{3,80}$/;

async function guardarPaginasAbiertas(cache) {
  const ventanas = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  await Promise.all(ventanas.map((c) => {
    const u = new URL(c.url);
    return PAGINA.test(u.pathname) ? cache.add(new Request(u.pathname, { cache: "reload", credentials: "same-origin" })).catch(() => {}) : null;
  }));
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL.map((u) => new Request(u, { cache: "reload", credentials: "same-origin" }))).catch(() => {});
    await guardarPaginasAbiertas(cache);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("sb-captura-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  const d = event.data || {};
  if (d.tipo === "guardar" && typeof d.url === "string" && PAGINA.test(d.url)) {
    event.waitUntil(caches.open(CACHE).then((c) => c.add(new Request(d.url, { cache: "reload", credentials: "same-origin" }))).catch(() => {}));
  }
});

function withTimeout(p, ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("timeout")), ms);
    p.then((v) => { clearTimeout(t); resolve(v); }, (e) => { clearTimeout(t); reject(e); });
  });
}

async function paginaGuardada(cache, path) {
  const hit = await cache.match(path);
  if (hit) return hit;
  for (const req of await cache.keys()) {
    if (PAGINA.test(new URL(req.url).pathname)) return cache.match(req);
  }
  return null;
}

async function navegar(request, path) {
  const cache = await caches.open(CACHE);
  try {
    const res = await withTimeout(fetch(request), 4000);
    if (res && res.ok) cache.put(path, res.clone()).catch(() => {});
    return res;
  } catch (e) {
    const hit = await paginaGuardada(cache, path);
    if (hit) return hit;
    throw e;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res && res.ok) cache.put(request, res.clone()).catch(() => {});
  return res;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.mode === "navigate") {
    if (PAGINA.test(url.pathname)) event.respondWith(navegar(req, url.pathname));
    return;
  }
  const key = url.pathname + url.search;
  if (SHELL.includes(key)) event.respondWith(cacheFirst(req));
  // todo lo demás (estado, foto, manifiesto, /uploads, /static sin versión): red directa, sin pasar por aquí
});
