/* App de tienda (PWA) para farmacias: login por cookie, góndolas, captura guiada con verificación de nitidez y
   exposición, compresión en el teléfono, cola de envío sin conexión (IndexedDB) y resultado con confirmaciones.
   Sin dependencias. Rutas por hash: #/login #/puntos #/punto/:id #/captura/:id #/lectura/:id #/cola #/ajustes */
(() => {
  "use strict";

  const VERSION = (document.querySelector('meta[name="tienda-version"]') || {}).content || "dev";
  const MAX_PHOTOS = 6;
  const SHARP_MIN = 60;            // varianza del laplaciano (0-255, copia de 256 px). Calibrado: foto nítida de góndola 800-4000, desenfoque σ=8 px ≈ 100, σ=14 px ≈ 18
  const LUM_MIN = 45, LUM_MAX = 215;   // luminancia media aceptada
  const MAX_ATTEMPTS = 5;
  const BACKOFF_MS = [3000, 6000, 12000, 24000, 48000];
  // Compresión en el teléfono (E1, recortes a resolución completa): lado mayor 3000 px, JPEG 0,80, hasta ~1,4 MB por foto
  // (antes 1600 px / 0,82 / 500 KB). El servidor guarda la foto tal cual (core.STORED_MAX_SIDE = 3000) y el motor detecta a
  // 1600 px pero lee OCR/catálogo sobre recortes 2-3× más grandes. Modo datos bajos: 2000 px / 0,75 / ~700 KB.
  const QUALITY = { normal: { maxSide: 3000, quality: 0.80, target: 1.4 * 1024 * 1024 }, low: { maxSide: 2000, quality: 0.75, target: 700 * 1024 } };

  // ─── utilidades ──────────────────────────────────────────────────────────
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (id) => `<svg aria-hidden="true"><use href="#i-${id}"/></svg>`;
  const nf = (n, d) => Number(n).toLocaleString("es-CL", { maximumFractionDigits: d == null ? 0 : d, minimumFractionDigits: d == null ? 0 : d });
  const fmtBytes = (n) => (n < 1024 * 1024 ? nf(n / 1024) + " KB" : nf(n / 1048576, 1) + " MB");
  const fmtPct = (v) => (v == null ? "–" : nf(v) + " %");
  const pctClass = (v) => (v == null ? "" : v >= 90 ? "good" : v >= 70 ? "warn" : "bad");
  const pctTag = (v) => (v == null ? "tag-neutral" : v >= 90 ? "tag-good" : v >= 70 ? "tag-warn" : "tag-bad");
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  function fmtDate(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const hh = String(d.getHours()).padStart(2, "0"), mm = String(d.getMinutes()).padStart(2, "0");
    return `${d.getDate()} ${MESES[d.getMonth()]}, ${hh}:${mm}`;
  }
  function fmtRel(iso) {
    if (!iso) return "sin lecturas";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const s = (Date.now() - d.getTime()) / 1000;
    if (s < 60) return "hace un momento";
    if (s < 3600) return `hace ${Math.round(s / 60)} min`;
    if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
    if (s < 172800) return "ayer";
    if (s < 7 * 86400) return `hace ${Math.round(s / 86400)} días`;
    return fmtDate(iso);
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const plural = (n, s, p) => `${nf(n)} ${n === 1 ? s : p}`;

  const Settings = {
    get(k, d) { try { const v = localStorage.getItem("tienda." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("tienda." + k, JSON.stringify(v)); } catch (e) { /* sin almacenamiento */ } },
    del(k) { try { localStorage.removeItem("tienda." + k); } catch (e) { /* nada */ } },
  };

  const Theme = {
    current() {
      const t = document.documentElement.getAttribute("data-theme");
      if (t === "dark" || t === "light") return t;
      return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    },
    set(t) {
      document.documentElement.setAttribute("data-theme", t);
      try { localStorage.setItem("tienda.theme", t); } catch (e) { /* nada */ }
      const btn = $("#themeBtn");
      if (btn) btn.innerHTML = icon(t === "dark" ? "sun" : "moon");
      $$('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", t === "dark" ? "#0a0a0a" : "#f6f6f3"));
    },
    toggle() { this.set(this.current() === "dark" ? "light" : "dark"); },
  };

  // ─── IndexedDB (cola de envío y caché) con respaldo en memoria ───────────
  const Mem = { jobs: new Map(), kv: new Map(), seq: 1 };
  const DB = {
    _p: null, broken: false,
    open() {
      if (this._p) return this._p;
      this._p = new Promise((resolve, reject) => {
        if (!window.indexedDB) return reject(new Error("sin IndexedDB"));
        const req = indexedDB.open("tienda", 1);
        req.onupgradeneeded = () => {
          const db = req.result;
          if (!db.objectStoreNames.contains("jobs")) db.createObjectStore("jobs", { keyPath: "id", autoIncrement: true });
          if (!db.objectStoreNames.contains("kv")) db.createObjectStore("kv");
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error || new Error("IndexedDB"));
        req.onblocked = () => reject(new Error("IndexedDB bloqueada"));
      }).catch((e) => { this.broken = true; throw e; });
      return this._p;
    },
    async tx(store, mode, fn) {
      const db = await this.open();
      return new Promise((resolve, reject) => {
        const t = db.transaction(store, mode);
        const req = fn(t.objectStore(store));
        t.oncomplete = () => resolve(req && req.result);
        t.onerror = () => reject(t.error);
        t.onabort = () => reject(t.error || new Error("abort"));
      });
    },
    async getAll(store) { try { return await this.tx(store, "readonly", (s) => s.getAll()); } catch (e) { return Array.from(Mem[store].values()); } },
    async get(store, key) { try { return await this.tx(store, "readonly", (s) => s.get(key)); } catch (e) { return Mem[store].get(key); } },
    async put(store, val, key) {
      try { return await this.tx(store, "readwrite", (s) => (key === undefined ? s.put(val) : s.put(val, key))); }
      catch (e) { const k = key === undefined ? val.id : key; Mem[store].set(k, val); return k; }
    },
    async add(store, val) {
      try { return await this.tx(store, "readwrite", (s) => s.add(val)); }
      catch (e) { val.id = Mem.seq++; Mem[store].set(val.id, val); return val.id; }
    },
    async del(store, key) { try { return await this.tx(store, "readwrite", (s) => s.delete(key)); } catch (e) { Mem[store].delete(key); } },
  };
  const Cache = {
    async get(k) { try { return await DB.get("kv", k); } catch (e) { return undefined; } },
    async set(k, v) { try { await DB.put("kv", v, k); } catch (e) { /* sin caché */ } },
  };

  // ─── estado y API ────────────────────────────────────────────────────────
  // me: {username, role: tienda|supervisor|admin, store_id, store_name} según GET /api/auth/me (role/store pueden faltar en backends antiguos)
  const State = { user: null, me: null, offlineAuth: false, points: null, pointsAt: 0, planograms: null, route: { name: "", id: null }, drafts: {}, returnTo: null, renderSeq: 0 };
  const isStoreUser = () => Boolean(State.me && State.me.role === "tienda");
  const myStore = () => (State.me && (State.me.store_name || State.me.store_id)) || null;
  const pointsKey = () => "points:" + (State.user || "");

  class ApiError extends Error { constructor(msg, status) { super(msg); this.status = status; } }
  function detailText(data, fallback) {
    if (!data) return fallback;
    const d = data.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
    return fallback;
  }
  async function api(path, opts = {}) {
    const init = { method: opts.method || "GET", credentials: "same-origin", headers: {} };
    if (opts.json) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.json); }
    else if (opts.form) init.body = opts.form;
    const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    let timer = null;
    if (ctrl) { init.signal = ctrl.signal; timer = setTimeout(() => ctrl.abort(), opts.timeout || 20000); }
    let res;
    try { res = await fetch(path, init); }
    catch (e) { throw new ApiError(navigator.onLine ? "No se pudo conectar con el servidor" : "Sin conexión", 0); }
    finally { if (timer) clearTimeout(timer); }
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
    if (res.status === 401) {
      if (!opts.noAuthRedirect) onUnauthorized();
      throw new ApiError("Sesión expirada", 401);
    }
    if (!res.ok) throw new ApiError(detailText(data, `Error ${res.status}`), res.status);
    return data;
  }
  function onUnauthorized() {
    if (!State.user) return;
    State.user = null; State.me = null;
    State.returnTo = location.hash && !/#\/login/.test(location.hash) ? location.hash : null;
    toast("La sesión expiró. Vuelve a entrar.", true);
    go("#/login");
  }
  function go(hash) { if (location.hash === hash) render(); else location.hash = hash; }

  // ─── avisos ──────────────────────────────────────────────────────────────
  function toast(html, bad, ms) {
    const host = $("#toasts");
    const t = document.createElement("div");
    t.className = "toast" + (bad ? " bad" : "");
    t.innerHTML = html;
    host.appendChild(t);
    setTimeout(() => { t.style.transition = "opacity .3s"; t.style.opacity = "0"; setTimeout(() => t.remove(), 320); }, ms || (bad ? 5000 : 3200));
    return t;
  }
  function sheet(html) {
    const host = $("#sheetHost");
    host.innerHTML = `<div class="scrim" role="dialog" aria-modal="true"><div class="sheet">${html}</div></div>`;
    const scrim = host.firstElementChild;
    scrim.addEventListener("click", (e) => { if (e.target === scrim) closeSheet(); });
    const first = scrim.querySelector("input, select, button");
    if (first) setTimeout(() => first.focus(), 30);
    return scrim;
  }
  function closeSheet() { $("#sheetHost").innerHTML = ""; }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeSheet(); if (!$("#cam").hidden) Cam.close(); } });

  // ─── puntos (góndolas) ───────────────────────────────────────────────────
  function splitName(p) {
    const name = String(p.name || p.id);
    const i = name.indexOf("/");
    const prefix = i > 0 ? name.slice(0, i).trim() : null;
    const gondola = i > 0 ? name.slice(i + 1).trim() || name : name;
    const store = p.store_name || p.store_id || prefix || null;
    return { store: store ? String(store) : null, gondola };
  }
  function trimPoint(p) {
    const l = p.latest;
    return {
      id: p.id, name: p.name, store_id: p.store_id || null, store_name: p.store_name || null, gondola_id: p.gondola_id || null,
      planogram_id: p.planogram_id, planogram_name: p.planogram_name, readings_count: p.readings_count,
      latest: l ? { id: l.id, created_at: l.created_at, compliance_pct: l.compliance ? l.compliance.compliance_pct : null, needs_review: l.needs_review || 0,
        total_facings: l.total_facings, shelf_levels: l.shelf_levels_detected } : null,
    };
  }
  async function loadPoints(force) {
    if (!force && State.points && Date.now() - State.pointsAt < 60000) return State.points;
    if (!State.points) {
      const cached = await Cache.get(pointsKey());   // la caché es por usuario: cada tienda ve solo lo suyo
      if (cached && cached.list) { State.points = cached.list; State.pointsAt = 0; State.pointsCachedAt = cached.at; }
    }
    if (!navigator.onLine || !State.user || State.offlineAuth) return State.points || [];
    try {
      const list = await api("/api/points", { timeout: 60000 });
      State.points = list.map(trimPoint);
      State.pointsAt = Date.now();
      State.pointsCachedAt = new Date().toISOString();
      Cache.set(pointsKey(), { list: State.points, at: State.pointsCachedAt });
    } catch (e) {
      if (!State.points) throw e;
      toast(esc(e.message), true);
    }
    return State.points;
  }
  async function loadPlanograms() {
    if (State.planograms) return State.planograms;
    State.planograms = await api("/api/planograms");
    return State.planograms;
  }
  function pointById(id) { return (State.points || []).find((p) => p.id === id) || null; }

  // ─── imágenes: decodificar, medir (nitidez / luz) y comprimir ────────────
  function decodeImage(blob) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => resolve({ source: img, width: img.naturalWidth, height: img.naturalHeight, close: () => URL.revokeObjectURL(url) });
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("No se pudo leer la imagen")); };
      img.src = url;
    });
  }
  /* Nitidez = varianza del laplaciano; luz = luminancia media. Sobre una copia de 256 px de ancho. */
  function measure(source, sw, sh) {
    const W = 256, H = Math.max(8, Math.round((sh * W) / sw));
    const c = $("#probeCanvas");
    c.width = W; c.height = H;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(source, 0, 0, W, H);
    const d = ctx.getImageData(0, 0, W, H).data;
    const g = new Float32Array(W * H);
    let sum = 0;
    for (let i = 0, j = 0; i < d.length; i += 4, j++) { const y = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]; g[j] = y; sum += y; }
    const mean = sum / (W * H);
    let ls = 0, ls2 = 0, n = 0;
    for (let y = 1; y < H - 1; y++) {
      for (let x = 1; x < W - 1; x++) {
        const i = y * W + x;
        const v = 4 * g[i] - g[i - 1] - g[i + 1] - g[i - W] - g[i + W];
        ls += v; ls2 += v * v; n++;
      }
    }
    const lm = ls / n;
    return { sharpness: ls2 / n - lm * lm, luminance: mean };
  }
  function qualityVerdict(m) {
    if (m.luminance < LUM_MIN) return "Foto muy oscura, repite";
    if (m.luminance > LUM_MAX) return "Foto muy clara o con reflejos, repite";
    if (m.sharpness < SHARP_MIN) return "Foto borrosa, repite";
    return null;
  }
  function toBlob(canvas, type, q) {
    return new Promise((resolve, reject) => {
      try { canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("No se pudo codificar la foto"))), type, q); }
      catch (e) { reject(e); }
    });
  }
  async function compressImage(src, opts) {
    // src: {source, width, height}; devuelve {blob, width, height, quality}
    let scale = Math.min(1, opts.maxSide / Math.max(src.width, src.height));
    let q = opts.quality;
    let out = null, w = 0, h = 0;
    for (let round = 0; round < 7; round++) {
      w = Math.max(1, Math.round(src.width * scale)); h = Math.max(1, Math.round(src.height * scale));
      const c = document.createElement("canvas");
      c.width = w; c.height = h;
      const ctx = c.getContext("2d");
      ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
      ctx.drawImage(src.source, 0, 0, w, h);
      out = await toBlob(c, "image/jpeg", q);
      if (out.size <= opts.target) break;
      if (q > 0.62) q = Math.round((q - 0.1) * 100) / 100;
      else { scale *= 0.85; q = Math.min(opts.quality, 0.72); }
    }
    return { blob: out, width: w, height: h, quality: q };
  }
  function qualityOpts() { return Settings.get("lowData", false) ? QUALITY.low : QUALITY.normal; }
  async function improveResolution(track) {
    // Some phones open a small video mode (1280x720 / 1600x1200) even when more was asked for; the engine needs
    // ~3000 px to read labels, so ask again before falling back to that stream.
    if (!track || !track.getSettings || !track.applyConstraints) return;
    const before = track.getSettings(), area = (s) => (s.width || 0) * (s.height || 0);
    if (Math.max(before.width || 0, before.height || 0) >= 2560) return;
    try { await track.applyConstraints({ width: { ideal: 3264 }, height: { ideal: 2448 } }); } catch (e) { return; }
    if (area(track.getSettings()) < area(before)) { try { await track.applyConstraints({ width: { ideal: before.width }, height: { ideal: before.height } }); } catch (e) { /* keep whatever the camera gives */ } }
  }

  // ─── cola de envío (IndexedDB) ───────────────────────────────────────────
  const Queue = {
    jobs: [], sending: null, timer: null, progress: null, listeners: [],
    on(fn) { this.listeners.push(fn); },
    emit(kind) { this.listeners.forEach((fn) => { try { fn(kind); } catch (e) { /* nada */ } }); },
    async load() {
      this.jobs = (await DB.getAll("jobs")).sort((a, b) => a.id - b.id);
      const cutoff = Date.now() - 2 * 86400000;
      for (const j of this.jobs.slice()) {
        if (j.status === "sending") { j.status = "queued"; await DB.put("jobs", j); }  // se cortó a mitad de envío: se reanuda
        if (j.status === "done" && new Date(j.finished_at || j.created_at).getTime() < cutoff) { await DB.del("jobs", j.id); this.jobs.splice(this.jobs.indexOf(j), 1); }
      }
      this.emit("load");
      this.kick();
    },
    pending() { return this.jobs.filter((j) => j.status === "queued" || j.status === "sending" || (j.status === "error" && !j.final)); },
    forPoint(id) { return this.jobs.filter((j) => j.point_id === id && j.status !== "done"); },
    async enqueue(point, photos) {
      const job = {
        point_id: point.id, point_name: point.name, created_at: new Date().toISOString(), status: "queued", attempts: 0, next_at: 0,
        last_error: null, final: false, reading_id: null, bytes: photos.reduce((s, p) => s + p.blob.size, 0), n_photos: photos.length,
        photos: photos.map((p, i) => ({ blob: p.blob, size: p.blob.size, w: p.width, h: p.height, name: p.name || `foto-${i + 1}.jpg` })),
      };
      job.id = await DB.add("jobs", job);
      this.jobs.push(job);
      this.emit("change");
      this.kick();
      return job;
    },
    async retry(id) {
      const j = this.jobs.find((x) => x.id === id);
      if (!j) return;
      j.status = "queued"; j.attempts = 0; j.next_at = 0; j.final = false; j.last_error = null;
      await DB.put("jobs", j);
      this.emit("change");
      this.kick();
    },
    async remove(id) {
      const j = this.jobs.find((x) => x.id === id);
      if (!j || j.status === "sending") return;
      await DB.del("jobs", j.id);
      this.jobs.splice(this.jobs.indexOf(j), 1);
      this.emit("change");
    },
    kick() {
      if (this.sending) return;
      clearTimeout(this.timer);
      const now = Date.now();
      const ready = this.jobs.filter((j) => j.status === "queued" || (j.status === "error" && !j.final && j.next_at <= now));
      if (!ready.length) {
        const waiting = this.jobs.filter((j) => j.status === "error" && !j.final).map((j) => j.next_at);
        if (waiting.length) this.timer = setTimeout(() => this.kick(), Math.max(500, Math.min(...waiting) - now));
        return;
      }
      if (!navigator.onLine || !State.user || State.offlineAuth) return;
      this.send(ready[0]);
    },
    async send(job) {
      this.sending = job;
      job.status = "sending";
      this.progress = { loaded: 0, total: job.bytes, phase: "upload" };
      await DB.put("jobs", job);
      this.emit("change");
      try {
        const reading = await uploadJob(job, (p) => { this.progress = p; this.emit("progress"); });
        job.status = "done"; job.reading_id = reading.id; job.finished_at = new Date().toISOString(); job.last_error = null;
        job.photos = [];  // libera el espacio de las fotos
        await DB.put("jobs", job);
        await Cache.set("reading:" + reading.id, reading);
        const pt = pointById(job.point_id);
        if (pt) {
          pt.latest = { id: reading.id, created_at: reading.created_at, compliance_pct: reading.compliance ? reading.compliance.compliance_pct : null,
            needs_review: reading.needs_review || 0, total_facings: reading.total_facings, shelf_levels: reading.shelf_levels_detected };
          pt.readings_count = (pt.readings_count || 0) + 1;
          State.pointsAt = 0;
          Cache.set(pointsKey(), { list: State.points, at: State.pointsCachedAt });
        }
        const pct = reading.compliance ? reading.compliance.compliance_pct : null;
        toast(`Lectura lista${pct != null ? " · " + fmtPct(pct) : ""} <a href="#/lectura/${reading.id}">Ver</a>`, false, 6000);
      } catch (e) {
        if (e.auth) { job.status = "queued"; await DB.put("jobs", job); this.sending = null; this.progress = null; this.emit("change"); onUnauthorized(); return; }
        job.attempts += 1;
        job.last_error = e.message || "Error";
        job.status = "error";
        if (e.retry && job.attempts < MAX_ATTEMPTS) { job.final = false; job.next_at = Date.now() + BACKOFF_MS[Math.min(job.attempts - 1, BACKOFF_MS.length - 1)]; }
        else { job.final = true; job.next_at = 0; if (!e.retry) job.last_error = e.message; }
        await DB.put("jobs", job);
        if (job.final) toast(`No se pudo analizar: ${esc(job.last_error)}`, true);
      }
      this.sending = null;
      this.progress = null;
      this.emit("change");
      this.kick();
    },
  };
  function uploadJob(job, onProgress) {
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      job.photos.forEach((p, i) => fd.append("images", p.blob, p.name || `foto-${i + 1}.jpg`));
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/points/${encodeURIComponent(job.point_id)}/analyze`);
      xhr.responseType = "text";
      xhr.withCredentials = true;
      let watchdog = null;
      const arm = () => { clearTimeout(watchdog); watchdog = setTimeout(() => xhr.abort(), 180000); };  // 180 s sin bytes ⇒ reintento
      const fail = (msg, extra) => { clearTimeout(watchdog); reject(Object.assign(new Error(msg), extra || {})); };
      xhr.upload.onprogress = (e) => { arm(); if (e.lengthComputable) onProgress({ phase: "upload", loaded: e.loaded, total: e.total }); };
      xhr.upload.onload = () => onProgress({ phase: "analyze", loaded: job.bytes, total: job.bytes });
      xhr.onprogress = () => arm();   // los espacios de keep-alive del servidor llegan aquí
      xhr.onerror = () => fail("Sin conexión con el servidor", { retry: true });
      xhr.onabort = () => fail("Tiempo de espera agotado", { retry: true });
      xhr.onload = () => {
        clearTimeout(watchdog);
        const text = (xhr.responseText || "").replace(/^\s+/, "");
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (xhr.status === 401) return fail("Sesión expirada", { auth: true });
        if (xhr.status === 0 || xhr.status >= 500) return fail(detailText(data, `Error ${xhr.status || "de red"}`), { retry: true });
        if (xhr.status >= 400) return fail(detailText(data, `Error ${xhr.status}`), { retry: false });
        if (!data) return fail("Respuesta incompleta del servidor", { retry: true });
        if (data.error || data.id == null) return fail(detailText(data, "El motor no pudo leer la góndola"), { retry: false });
        resolve(data);
      };
      arm();
      xhr.send(fd);
    });
  }

  // ─── barra de estado y pestañas ──────────────────────────────────────────
  function renderStatus() {
    const btn = $("#statusBtn"), txt = $("#statusText");
    if (!btn) return;
    const pending = Queue.pending();
    btn.classList.remove("off", "busy");
    if (!navigator.onLine) { btn.classList.add("off"); txt.textContent = "Sin conexión" + (pending.length ? ` · ${pending.length} en cola` : ""); }
    else if (Queue.sending) {
      btn.classList.add("busy");
      const idx = pending.indexOf(Queue.sending) + 1;
      txt.textContent = `Enviando ${idx} de ${pending.length} · ${fmtBytes(Queue.sending.bytes)}`;   // el % subido y la fase van en la tarjeta de la cola
    } else if (State.offlineAuth) { btn.classList.add("off"); txt.textContent = "Sin sesión verificada"; }
    else txt.textContent = pending.length ? `En línea · ${pending.length} en cola` : "En línea";
    const n = $("#tabQueueN");
    if (n) { n.hidden = !pending.length; n.textContent = pending.length; }
  }
  function setChrome({ top, tabs, title, sub }) {
    $("#top").hidden = !top;
    $("#tabs").hidden = !tabs;
    $("#view").classList.toggle("no-tabs", !tabs);
    if (title != null) $("#topTitle").textContent = title;
    const s = $("#topSub");
    s.hidden = !sub; s.textContent = sub || "";
    $$("#tabs .tab").forEach((t) => t.classList.toggle("is-active", t.dataset.tab === State.route.name || (t.dataset.tab === "puntos" && ["punto", "captura", "lectura"].includes(State.route.name))));
  }

  // ─── vistas ──────────────────────────────────────────────────────────────
  const view = () => $("#view");

  function viewLogin() {
    setChrome({ top: false, tabs: false });
    const remembered = Settings.get("user", "");
    view().innerHTML = `
      <div class="login"><form class="login-card" id="loginForm" novalidate>
        <div class="brand"><img src="/static/assets/pwa/icon-192.png" alt="" width="34" height="34"/><div><b>Góndolas</b><span>Farmacias Salcobrand</span></div></div>
        <div class="fld"><label for="u">Usuario</label><input class="in" id="u" name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" value="${esc(remembered)}" required></div>
        <div class="fld"><label for="p">Contraseña</label><input class="in" id="p" name="password" type="password" autocomplete="current-password" required></div>
        <label class="chk"><input type="checkbox" id="remember" ${Settings.get("remember", true) ? "checked" : ""}> Recordar en este dispositivo</label>
        <div class="form-err" id="loginErr" role="alert"></div>
        <button class="btn btn-lime btn-xl block" type="submit" id="loginBtn">Entrar</button>
        <div class="login-foot"><span>v${esc(VERSION)}</span><span id="loginNet">${navigator.onLine ? "" : "Sin conexión: no se puede iniciar sesión"}</span></div>
      </form></div>`;
    const form = $("#loginForm");
    (remembered ? $("#p") : $("#u")).focus();
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const u = $("#u").value.trim(), p = $("#p").value;
      const err = $("#loginErr"), btn = $("#loginBtn");
      if (!u || !p) { err.textContent = "Escribe usuario y contraseña."; return; }
      btn.disabled = true; err.textContent = "";
      try {
        const data = await api("/api/auth/login", { method: "POST", json: { username: u, password: p }, noAuthRedirect: true });
        const remember = $("#remember").checked;
        Settings.set("remember", remember);
        if (remember) Settings.set("user", data.username); else { Settings.del("user"); Settings.del("me"); }
        State.points = null; State.pointsQuery = ""; State.planograms = null;   // otro usuario puede haber entrado en este teléfono
        await verifySession(data.username);   // trae role/local desde /api/auth/me
        const to = State.returnTo; State.returnTo = null;
        Queue.kick();
        go(to && !/#\/login/.test(to) ? to : "#/puntos");
      } catch (ex) {
        err.textContent = ex.status === 401 ? "Usuario o contraseña incorrectos" : ex.message;
      } finally { btn.disabled = false; }
    });
  }

  const NO_STORE_MSG = "Tu usuario no tiene local asignado: pide al supervisor que lo asigne.";
  function headerSub() { return [myStore(), State.user].filter(Boolean).join(" · "); }
  async function viewPoints() {
    setChrome({ top: true, tabs: true, title: "Mis góndolas", sub: headerSub() });
    if (isStoreUser() && !State.me.store_id) {   // usuario de tienda sin local: no hay nada que listar ni crear
      view().innerHTML = `<div class="stack"><div class="notice notice-warn">${icon("warn")}<span>${NO_STORE_MSG}</span></div></div>`;
      return;
    }
    const q = State.pointsQuery || "";
    view().innerHTML = `
      <div class="stack">
        <div class="search">${icon("search")}<input class="in" id="q" type="search" placeholder="${isStoreUser() ? "Buscar góndola" : "Buscar góndola o local"}" value="${esc(q)}" autocomplete="off" aria-label="Buscar"></div>
        <button class="btn btn-lime block" type="button" data-act="new-point">${icon("plus")}Nueva góndola</button>
        <div id="pointsList"><div class="empty"><span class="spin" style="display:inline-block"></span></div></div>
      </div>`;
    const input = $("#q");
    input.addEventListener("input", () => { State.pointsQuery = input.value; renderPointsList(); });
    try { await loadPoints(); } catch (e) { $("#pointsList").innerHTML = `<div class="notice notice-bad">${icon("warn")}<span>${esc(e.message)}</span></div>`; return; }
    renderPointsList();
  }
  function renderPointsList() {
    const host = $("#pointsList");
    if (!host) return;
    const q = (State.pointsQuery || "").trim().toLowerCase();
    let list = State.points || [];
    if (q) list = list.filter((p) => (p.name + " " + (p.planogram_name || "") + " " + p.id).toLowerCase().includes(q));
    if (!list.length) {
      host.innerHTML = `<div class="empty">${State.points && State.points.length ? "Ninguna góndola coincide." : "Todavía no hay góndolas. Crea la primera con «Nueva góndola»."}</div>`;
      return;
    }
    // usuario de tienda: lista plana de su local; supervisor/admin: agrupado por local solo si la lista abarca varios
    const groups = new Map();
    for (const p of list) { const key = isStoreUser() ? "" : splitName(p).store || ""; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(p); }
    const grouped = !isStoreUser() && groups.size > 1;
    const parts = [];
    if (State.pointsAt === 0 && State.pointsCachedAt) parts.push(`<div class="notice notice-info">${icon("warn")}<span>Lista guardada ${fmtRel(State.pointsCachedAt)}${navigator.onLine ? "" : " · sin conexión"}.</span></div>`);
    for (const [store, pts] of groups) {
      if (grouped) parts.push(`<div class="group-h"><h2>${esc(store || "Sin local")}</h2><span class="small muted">${plural(pts.length, "góndola", "góndolas")}</span></div>`);
      for (const p of pts) {
        const { gondola } = splitName(p);
        const l = p.latest, jobs = Queue.forPoint(p.id);
        const tags = [];
        if (l && l.needs_review) tags.push(`<span class="tag tag-warn">${plural(l.needs_review, "por confirmar", "por confirmar")}</span>`);
        if (jobs.some((j) => j.status === "sending")) tags.push(`<span class="tag tag-info">Enviando</span>`);
        else if (jobs.some((j) => j.status === "queued" || (j.status === "error" && !j.final))) tags.push(`<span class="tag tag-info">En cola</span>`);
        if (jobs.some((j) => j.status === "error" && j.final)) tags.push(`<span class="tag tag-bad">Error de envío</span>`);
        parts.push(`<a class="row" href="#/punto/${encodeURIComponent(p.id)}" style="margin-bottom:8px">
          <div class="row-main">
            <div class="row-t">${esc(gondola)}</div>
            <div class="row-s">${esc(p.planogram_name || "Sin planograma")} · ${l ? "lectura " + fmtRel(l.created_at) : "sin lecturas"}</div>
            <div class="row-tags">${tags.join("")}</div>
          </div>
          ${l ? `<div class="pct ${pctClass(l.compliance_pct)}">${l.compliance_pct != null ? nf(l.compliance_pct) + "%" : "–"}<small>${l.compliance_pct != null ? "planograma" : "sin planograma"}</small></div>` : ""}
          <svg class="chev"><use href="#i-chev"/></svg></a>`);
      }
    }
    host.innerHTML = parts.join("");
  }
  async function newPointSheet() {
    if (isStoreUser() && !State.me.store_id) {
      const s0 = sheet(`<h2>Nueva góndola</h2><div class="notice notice-warn">${icon("warn")}<span>${NO_STORE_MSG}</span></div><button class="btn" type="button" data-close>Cerrar</button>`);
      s0.querySelector("[data-close]").addEventListener("click", closeSheet);
      return;
    }
    let pgs = [];
    try { pgs = await loadPlanograms(); } catch (e) { /* sin planogramas (fuera de línea) */ }
    // tienda: solo nombre de la góndola (el servidor la asigna a su local); supervisor/admin: «Local / Góndola»
    const nameField = isStoreUser()
      ? `<dl class="kv"><dt>Local</dt><dd><b>${esc(myStore())}</b></dd></dl>
         <div class="fld"><label for="npName">Nombre de la góndola</label><input class="in" id="npName" placeholder="Ej.: Cuidado bucal" autocomplete="off"><div class="hint">Quedará en ${esc(myStore())}.</div></div>`
      : `<div class="fld"><label for="npName">Nombre</label><input class="in" id="npName" placeholder="Local / Góndola" autocomplete="off"><div class="hint">Ej.: «Providencia 1234 / Cuidado bucal». La parte antes de «/» agrupa por local.</div></div>`;
    const s = sheet(`
      <h2>Nueva góndola</h2>
      ${nameField}
      <div class="fld"><label for="npPg">Planograma</label><select class="in" id="npPg" ${pgs.length ? "" : "disabled"}><option value="">Sin planograma</option>${pgs.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("")}</select>${pgs.length ? "" : `<div class="hint">${navigator.onLine ? "No hay planogramas cargados." : "Sin conexión: no se pueden listar los planogramas."}</div>`}</div>
      <div class="form-err" id="npErr" role="alert"></div>
      <div class="btn-row"><button class="btn" type="button" data-close>Cancelar</button><button class="btn btn-lime" type="button" id="npSave">Crear</button></div>`);
    s.querySelector("[data-close]").addEventListener("click", closeSheet);
    s.querySelector("#npSave").addEventListener("click", async () => {
      const name = s.querySelector("#npName").value.trim();
      const err = s.querySelector("#npErr");
      if (!name) { err.textContent = "Escribe un nombre."; return; }
      if (!navigator.onLine) { err.textContent = "Sin conexión: crea la góndola cuando vuelva la red."; return; }
      const fd = new FormData();
      fd.append("name", name);
      const pg = s.querySelector("#npPg").value;
      if (pg) fd.append("planogram_id", pg);
      try {
        const p = await api("/api/points", { method: "POST", form: fd });
        closeSheet();
        await loadPoints(true);
        go("#/punto/" + encodeURIComponent(p.id));
      } catch (ex) { err.textContent = ex.message; }
    });
  }

  async function viewPoint(id) {
    await loadPoints();
    let p = pointById(id);
    if (!p && navigator.onLine) { try { await loadPoints(true); p = pointById(id); } catch (e) { /* nada */ } }
    if (!p) { setChrome({ top: true, tabs: true, title: "Góndola" }); view().innerHTML = `<div class="empty">Góndola no encontrada.</div>`; return; }
    const { store, gondola } = splitName(p);
    setChrome({ top: true, tabs: true, title: gondola, sub: [store, p.planogram_name].filter(Boolean).join(" · ") });
    const l = p.latest;
    view().innerHTML = `
      <div class="stack">
        <div class="ph"><a class="back" href="#/puntos">${icon("back")}Góndolas</a></div>
        <a class="btn btn-lime btn-xl block" href="#/captura/${encodeURIComponent(p.id)}">${icon("camera")}Tomar fotos</a>
        <div id="pointJobs"></div>
        <div class="card">
          <div class="card-h"><h2>Última lectura</h2>${l ? `<span class="small muted">${fmtRel(l.created_at)}</span>` : ""}</div>
          <div class="card-b">${l ? `
            <div class="hero"><div class="big ${pctClass(l.compliance_pct)}">${l.compliance_pct != null ? nf(l.compliance_pct) + "<small>%</small>" : "–"}</div>
              <div class="l"><b>${l.compliance_pct != null ? "Cumplimiento del planograma" : (p.planogram_name ? "Sin cumplimiento calculado" : "Sin planograma asignado")}</b>
              <span>${plural(l.total_facings || 0, "cara", "caras")} · ${plural(l.shelf_levels || 0, "nivel", "niveles")} · ${l.needs_review ? `<span class="warn">${plural(l.needs_review, "por confirmar", "por confirmar")}</span>` : "nada por confirmar"}</span></div></div>
            <div style="margin-top:12px"><a class="btn block" href="#/lectura/${l.id}">Ver resultado${icon("chev")}</a></div>`
          : `<div class="empty" style="padding:8px 0">Sin lecturas todavía. Toma las fotos de la góndola para obtener la primera.</div>`}</div>
        </div>
        <div class="card"><div class="card-h"><h2>Historial</h2><span class="small muted" id="histSub"></span></div><div class="card-b" id="hist"><button class="btn btn-sm" type="button" data-act="load-hist">Ver últimas lecturas</button></div></div>
      </div>`;
    renderPointJobs(p.id);
    if (navigator.onLine && (p.readings_count || 0) > 0 && !State.offlineAuth) loadHistory(p);
  }
  function renderPointJobs(pointId) {
    const host = $("#pointJobs");
    if (!host) return;
    const jobs = Queue.forPoint(pointId);
    host.innerHTML = jobs.map(jobCard).join("");
  }
  async function loadHistory(p) {
    const host = $("#hist"), sub = $("#histSub");
    if (!host) return;
    host.innerHTML = `<div class="empty" style="padding:8px"><span class="spin" style="display:inline-block"></span></div>`;
    let rows = null;
    try {
      const full = await api(`/api/points/${encodeURIComponent(p.id)}`, { timeout: 60000 });
      rows = (full.readings || []).slice(0, 10).map((r) => ({ id: r.id, created_at: r.created_at, pct: r.compliance ? r.compliance.compliance_pct : null, facings: r.total_facings, review: r.needs_review || 0 }));
      Cache.set("hist:" + p.id, rows);
    } catch (e) {
      rows = await Cache.get("hist:" + p.id);
      if (!rows) { host.innerHTML = `<div class="notice notice-warn">${icon("warn")}<span>${esc(e.message)}</span></div>`; return; }
    }
    if (!rows.length) { host.innerHTML = `<div class="empty" style="padding:8px 0">Sin lecturas.</div>`; return; }
    const hasPct = rows.some((r) => r.pct != null);
    const series = rows.slice().reverse().map((r) => (hasPct ? r.pct : r.facings));
    sub.textContent = hasPct ? "cumplimiento, últimas " + rows.length : "caras detectadas, últimas " + rows.length;
    host.innerHTML = `${sparkline(series, hasPct ? [0, 100] : null, hasPct ? "Cumplimiento por lectura" : "Caras por lectura")}
      <div class="list" style="margin-top:8px">${rows.map((r) => `<a class="hist-row" href="#/lectura/${r.id}"><span class="d">${fmtDate(r.created_at)}</span>${r.review ? `<span class="tag tag-warn tag-plain">${r.review} por confirmar</span>` : ""}<span class="p ${hasPct ? pctClass(r.pct) : ""}">${hasPct ? fmtPct(r.pct) : nf(r.facings || 0)}</span><svg class="chev" style="width:16px;height:16px;color:var(--ink3)"><use href="#i-chev"/></svg></a>`).join("")}</div>`;
  }
  function sparkline(values, domain, label) {
    const W = 300, H = 44, px = 6, py = 6;
    const vals = values.map((v) => (v == null ? null : Number(v)));
    const nums = vals.filter((v) => v != null);
    if (nums.length < 2) return `<svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}: ${nums.length ? nf(nums[0]) : "sin datos"}"><line class="grid" x1="0" y1="${H - py}" x2="${W}" y2="${H - py}"/>${nums.length ? `<circle class="pt" cx="${W - px}" cy="${H / 2}" r="4"/>` : ""}</svg>`;
    let lo = domain ? domain[0] : Math.min(...nums), hi = domain ? domain[1] : Math.max(...nums);
    if (hi === lo) { hi += 1; lo -= 1; }
    const n = vals.length;
    const x = (i) => px + (i * (W - 2 * px)) / (n - 1);
    const y = (v) => H - py - ((v - lo) * (H - 2 * py)) / (hi - lo);
    const pts = vals.map((v, i) => (v == null ? null : [x(i), y(v)])).filter(Boolean);
    const line = pts.map((p) => p.join(",")).join(" ");
    const area = `${pts[0][0]},${H - py} ${line} ${pts[pts.length - 1][0]},${H - py}`;
    const last = pts[pts.length - 1];
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(label)}: ${vals.map((v) => (v == null ? "–" : nf(v))).join(", ")}">
      <line class="grid" x1="0" y1="${H - py}" x2="${W}" y2="${H - py}"/><polygon class="area" points="${area}"/><polyline class="line" points="${line}"/><circle class="pt" cx="${last[0]}" cy="${last[1]}" r="4"/></svg>`;
  }

  // ─── captura ─────────────────────────────────────────────────────────────
  function draft(pointId) { if (!State.drafts[pointId]) State.drafts[pointId] = []; return State.drafts[pointId]; }
  async function viewCapture(id) {
    await loadPoints();
    const p = pointById(id);
    if (!p) { go("#/puntos"); return; }
    const { gondola } = splitName(p);
    setChrome({ top: true, tabs: false, title: "Fotos · " + gondola, sub: p.planogram_name || "" });
    view().innerHTML = `
      <div class="stack">
        <div class="ph"><a class="back" href="#/punto/${encodeURIComponent(p.id)}">${icon("back")}Góndola</a></div>
        <div class="notice notice-info">${icon("camera")}<span>Hasta ${MAX_PHOTOS} fotos, de izquierda a derecha, un módulo completo por foto. Se comprimen en el teléfono antes de enviar.</span></div>
        <div class="photos" id="photoList"></div>
        <div class="btn-row">
          <button class="btn" type="button" id="openCameraBtn">${icon("camera")}Cámara</button>
          <button class="btn" type="button" data-act="gallery">${icon("image")}Galería</button>
        </div>
        <button class="btn btn-lime btn-xl block" type="button" id="sendBtn" disabled>Enviar a análisis</button>
        <p class="small muted" style="text-align:center">Si no hay señal, la lectura queda en cola y se envía sola.</p>
      </div>`;
    renderPhotoList(p);
    $("#openCameraBtn").addEventListener("click", () => Cam.open(p));
    $("#sendBtn").addEventListener("click", () => sendDraft(p));
    if (!draft(p.id).length) Cam.open(p);   // sin fotos aún: la cámara se abre sola; si falla, muestra el respaldo
  }
  function renderPhotoList(p) {
    const host = $("#photoList"), photos = draft(p.id);
    if (!host) return;
    if (!photos.length) { host.innerHTML = `<div class="empty">Sin fotos todavía.</div>`; }
    else {
      host.innerHTML = photos.map((ph, i) => `<div class="photo">
        <img src="${ph.url}" alt="Foto ${i + 1}">
        <div class="m"><b>Foto ${i + 1}${i === 0 ? " · izquierda" : i === photos.length - 1 && photos.length > 1 ? " · derecha" : ""}</b><span>${ph.width}×${ph.height} · ${fmtBytes(ph.blob.size)}${ph.original ? " · sin comprimir" : ""}</span></div>
        <div class="acts"><button type="button" data-act="ph-up" data-i="${i}" aria-label="Mover a la izquierda" ${i === 0 ? "disabled" : ""}>←</button><button type="button" data-act="ph-down" data-i="${i}" aria-label="Mover a la derecha" ${i === photos.length - 1 ? "disabled" : ""}>→</button><button type="button" class="del" data-act="ph-del" data-i="${i}" aria-label="Eliminar foto">✕</button></div>
      </div>`).join("");
    }
    const send = $("#sendBtn");
    if (send) { send.disabled = !photos.length; send.textContent = photos.length ? `Enviar ${plural(photos.length, "foto", "fotos")} · ${fmtBytes(photos.reduce((s, x) => s + x.blob.size, 0))}` : "Enviar a análisis"; }
  }
  async function sendDraft(p) {
    const photos = draft(p.id);
    if (!photos.length) return;
    $("#sendBtn").disabled = true;
    try {
      await Queue.enqueue(p, photos);
      photos.forEach((ph) => URL.revokeObjectURL(ph.url));
      State.drafts[p.id] = [];
      toast(navigator.onLine ? "Enviando a análisis…" : "En cola: se enviará cuando haya conexión");
      go("#/punto/" + encodeURIComponent(p.id));
    } catch (e) { toast("No se pudo guardar la lectura: " + esc(e.message), true); $("#sendBtn").disabled = false; }
  }
  /* Acepta una imagen (de la cámara o de archivo): mide, rechaza si está borrosa/oscura, comprime y agrega al borrador. */
  async function acceptImage(p, src, blobOriginal, name, force) {
    const photos = draft(p.id);
    if (photos.length >= MAX_PHOTOS) throw new Error(`Máximo ${MAX_PHOTOS} fotos`);
    const m = measure(src.source, src.width, src.height);
    const verdict = force ? null : qualityVerdict(m);
    if (verdict) { const err = new Error(verdict); err.quality = true; err.metrics = m; throw err; }
    const out = await compressImage(src, qualityOpts());
    const ph = { blob: out.blob, width: out.width, height: out.height, quality: out.quality, name: name || `foto-${Date.now()}.jpg`, sharp: m.sharpness, lum: m.luminance, url: URL.createObjectURL(out.blob) };
    photos.push(ph);
    return ph;
  }
  async function addFiles(p, files) {
    const list = Array.from(files || []);
    let lastErr = null;
    for (const f of list) {
      if (draft(p.id).length >= MAX_PHOTOS) { toast(`Máximo ${MAX_PHOTOS} fotos`, true); break; }
      let src = null;
      try { src = await decodeImage(f); }
      catch (e) {
        // HEIC u otro formato que el navegador no decodifica: se envía tal cual (el servidor lo acepta)
        draft(p.id).push({ blob: f, width: 0, height: 0, name: f.name, original: true, url: URL.createObjectURL(f) });
        continue;
      }
      try { await acceptImage(p, src, f, f.name.replace(/\.[^.]+$/, "") + ".jpg"); }
      catch (e) {
        lastErr = e;
        if (e.quality) {
          const ok = await askForce(e.message);
          if (ok) await acceptImage(p, src, f, f.name, true);
        } else toast(esc(e.message), true);
      } finally { src.close(); }
    }
    renderPhotoList(p);
    Cam.renderThumbs();
    return lastErr;
  }
  function askForce(msg) {
    return new Promise((resolve) => {
      const s = sheet(`<h2>${esc(msg)}</h2><p class="t2">La foto no pasa la verificación. Puedes usarla igual, pero el análisis será menos confiable.</p>
        <div class="btn-row"><button class="btn btn-lime" type="button" data-no>Repetir</button><button class="btn" type="button" data-yes>Usar igual</button></div>`);
      s.querySelector("[data-no]").addEventListener("click", () => { closeSheet(); resolve(false); });
      s.querySelector("[data-yes]").addEventListener("click", () => { closeSheet(); resolve(true); });
    });
  }

  const Cam = {
    stream: null, point: null, liveTimer: null, busy: false, ic: null, photoOpts: null,
    el() { return $("#cam"); },
    async open(point) {
      this.point = point;
      const cam = this.el();
      cam.hidden = false;
      $("#cameraError").hidden = true;
      $("#camTitle").textContent = splitName(point).gondola;
      this.msg(null);
      this.renderThumbs();
      document.body.style.overflow = "hidden";
      const video = $("#cameraVideo");
      if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) || !window.isSecureContext) { this.showError("Este navegador no permite usar la cámara desde la app."); return; }
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 3264 }, height: { ideal: 2448 } }, audio: false });
        video.srcObject = this.stream;
        await video.play().catch(() => {});
        clearInterval(this.liveTimer);
        this.liveTimer = setInterval(() => this.probe(), 700);
        const track = this.stream.getVideoTracks()[0];
        await improveResolution(track);
        // Full-resolution photos (ImageCapture) when the device offers them: the live video stream is often much
        // smaller (e.g. 1600x1200) than what the sensor can give, and shoot() falls back to that stream otherwise.
        this.ic = null; this.photoOpts = null;
        if ("ImageCapture" in window) {
          try {
            this.ic = new ImageCapture(track);
            const pc = await Promise.race([this.ic.getPhotoCapabilities(), new Promise((r) => setTimeout(() => r(null), 2500))]);
            if (pc && pc.imageWidth && pc.imageWidth.max && pc.imageHeight && pc.imageHeight.max) this.photoOpts = { imageWidth: pc.imageWidth.max, imageHeight: pc.imageHeight.max };
          } catch (e) { this.ic = null; }
        }
      } catch (e) {
        this.showError(e && e.name === "NotAllowedError" ? "Permiso de cámara denegado. Puedes usar la cámara del teléfono." : "No se pudo abrir la cámara (" + (e && (e.message || e.name) || "error") + ").");
      }
    },
    showError(text) {
      $("#cameraErrorText").textContent = text;
      $("#cameraError").hidden = false;
    },
    close() {
      clearInterval(this.liveTimer); this.liveTimer = null;
      if (this.stream) { this.stream.getTracks().forEach((t) => t.stop()); this.stream = null; }
      this.ic = null; this.photoOpts = null;
      $("#cameraVideo").srcObject = null;
      this.el().hidden = true;
      document.body.style.overflow = "";
      if (this.point && State.route.name === "captura") renderPhotoList(this.point);
    },
    msg(text, ok, extraHtml) {
      const m = $("#camMsg");
      clearTimeout(this._msgT);
      if (!text) { m.hidden = true; m.innerHTML = ""; return; }
      m.hidden = false; m.className = "cam-msg" + (ok ? " ok" : "");
      m.innerHTML = `<span>${esc(text)}</span>${extraHtml || ""}`;
      if (!extraHtml) this._msgT = setTimeout(() => this.msg(null), ok ? 1600 : 2600);
    },
    probe() {
      const v = $("#cameraVideo");
      if (!v.videoWidth || this.busy) return;
      try {
        const m = measure(v, v.videoWidth, v.videoHeight);
        const s = $("#liveSharp"), l = $("#liveLight");
        s.className = "live-pill " + (m.sharpness >= SHARP_MIN ? "ok" : "ko");
        s.textContent = m.sharpness >= SHARP_MIN ? "Nitidez ok" : "Enfoca / quieto";
        l.className = "live-pill " + (m.luminance >= LUM_MIN && m.luminance <= LUM_MAX ? "ok" : "ko");
        l.textContent = m.luminance < LUM_MIN ? "Poca luz" : m.luminance > LUM_MAX ? "Mucha luz" : "Luz ok";
      } catch (e) { /* nada */ }
    },
    renderThumbs() {
      const host = $("#camThumbs");
      if (!host || !this.point) return;
      const photos = draft(this.point.id);
      host.innerHTML = photos.map((ph, i) => `<figure><img src="${ph.url}" alt="Foto ${i + 1}"><figcaption>${fmtBytes(ph.blob.size)}</figcaption></figure>`).join("");
      host.scrollLeft = host.scrollWidth;
      $("#camCount").textContent = `${photos.length}/${MAX_PHOTOS}`;
      $("#camDone").textContent = photos.length ? `Listo (${photos.length})` : "Listo";
      $("#shutterBtn").disabled = photos.length >= MAX_PHOTOS;
    },
    async photoBlob() {
      // ImageCapture.takePhoto gives the sensor's photo resolution; null (after a short wait) falls back to the
      // video frame so the shutter never hangs on devices with a broken takePhoto.
      if (!this.ic) return null;
      const limit = () => new Promise((r) => setTimeout(() => r(null), 4000));
      try { return await Promise.race([this.ic.takePhoto(this.photoOpts || undefined), limit()]); }
      catch (e) {
        try { return await Promise.race([this.ic.takePhoto(), limit()]); }
        catch (e2) { this.ic = null; return null; }
      }
    },
    async shoot() {
      const v = $("#cameraVideo");
      if (this.busy) return;
      if (!v.videoWidth) { this.msg("La cámara todavía está cargando"); return; }
      if (draft(this.point.id).length >= MAX_PHOTOS) { this.msg(`Máximo ${MAX_PHOTOS} fotos`); return; }
      this.busy = true;
      const flash = $("#camFlash"); flash.classList.remove("on"); void flash.offsetWidth; flash.classList.add("on");
      let src = null;
      const blob = await this.photoBlob();
      if (blob && blob.size) { try { src = await decodeImage(blob); } catch (e) { src = null; } }
      if (!src) {
        const c = document.createElement("canvas");
        c.width = v.videoWidth; c.height = v.videoHeight;
        c.getContext("2d").drawImage(v, 0, 0);
        src = { source: c, width: c.width, height: c.height, close() {} };
      }
      try {
        const ph = await acceptImage(this.point, src, null, `foto-${Date.now()}.jpg`);
        src.close();
        this.renderThumbs();
        this.msg(`Foto ${draft(this.point.id).length}/${MAX_PHOTOS} · ${fmtBytes(ph.blob.size)}`, true);
        if (draft(this.point.id).length >= MAX_PHOTOS) setTimeout(() => this.close(), 900);
      } catch (e) {
        if (e.quality) {
          this.msg(e.message, false, `<button type="button" id="camForce">Usar igual</button>`);
          $("#camForce").addEventListener("click", async () => {
            this.msg(null);
            try { const ph = await acceptImage(this.point, src, null, `foto-${Date.now()}.jpg`, true); this.renderThumbs(); this.msg(`Foto agregada · ${fmtBytes(ph.blob.size)}`, true); }
            catch (ex) { this.msg(ex.message); }
            finally { src.close(); }
          });
        } else { src.close(); this.msg(e.message || "No se pudo capturar la foto"); }
      } finally { this.busy = false; }
    },
  };
  function bindCamera() {
    $("#camClose").addEventListener("click", () => Cam.close());
    $("#camErrorClose").addEventListener("click", () => Cam.close());
    $("#camDone").addEventListener("click", () => Cam.close());
    $("#shutterBtn").addEventListener("click", () => Cam.shoot());
    $("#camGallery").addEventListener("click", () => $("#fileGal").click());
    $("#camFallbackBtn").addEventListener("click", () => $("#fileCam").click());
    $("#camFallbackGallery").addEventListener("click", () => $("#fileGal").click());
    const onFiles = (input) => async () => {
      const p = Cam.point || pointById(State.route.id);
      if (!p || !input.files.length) return;
      const err = await addFiles(p, input.files);
      input.value = "";
      if (!$("#cam").hidden) {
        if (!err) Cam.msg(`Foto ${draft(p.id).length}/${MAX_PHOTOS} agregada`, true);
        if (draft(p.id).length >= MAX_PHOTOS) Cam.close();
      }
    };
    $("#fileCam").addEventListener("change", onFiles($("#fileCam")));
    $("#fileGal").addEventListener("change", onFiles($("#fileGal")));
  }

  // ─── cola (vista) ────────────────────────────────────────────────────────
  function jobCard(j) {
    const p = Queue.progress;
    let state = "", bar = "";
    if (j.status === "queued") state = navigator.onLine ? "En cola" : "En cola · sin conexión";
    else if (j.status === "sending") {
      const pct = p && p.phase === "upload" && p.total ? Math.round((p.loaded / p.total) * 100) : null;
      state = p && p.phase === "analyze" ? "Analizando en el servidor…" : `Subiendo${pct != null ? " " + pct + " %" : ""}`;
      bar = `<div class="bar ${p && p.phase === "analyze" ? "indet" : ""}"><i style="width:${pct || 0}%"></i></div>`;
    } else if (j.status === "done") state = "Lista";
    else if (j.status === "error") state = j.final ? "Error" : `Reintento ${j.attempts} de ${MAX_ATTEMPTS} en ${Math.max(1, Math.round((j.next_at - Date.now()) / 1000))} s`;
    const tag = j.status === "done" ? "tag-good" : j.status === "error" && j.final ? "tag-bad" : j.status === "sending" ? "tag-info" : "tag-neutral";
    return `<div class="job" data-job="${j.id}">
      <div class="job-h"><b>${esc(splitName({ name: j.point_name, id: j.point_id }).gondola)}</b><span class="tag ${tag}">${esc(state)}</span></div>
      <div class="s">${plural(j.n_photos || (j.photos && j.photos.length) || 0, "foto", "fotos")} · ${fmtBytes(j.bytes)} · ${fmtDate(j.created_at)}</div>
      ${bar}${j.last_error && j.status === "error" ? `<div class="err">${esc(j.last_error)}</div>` : ""}
      <div class="acts">${j.status === "done" ? `<a class="btn btn-sm" href="#/lectura/${j.reading_id}">Ver resultado</a>` : ""}${j.status === "error" ? `<button class="btn btn-sm" type="button" data-act="job-retry" data-id="${j.id}">Reintentar ahora</button>` : ""}${j.status !== "sending" ? `<button class="btn btn-sm btn-ghost" type="button" data-act="job-del" data-id="${j.id}">Eliminar</button>` : ""}</div>
    </div>`;
  }
  function viewQueue() {
    setChrome({ top: true, tabs: true, title: "Cola de envío", sub: navigator.onLine ? "Se envía una lectura a la vez" : "Sin conexión: se enviará al volver la red" });
    const jobs = Queue.jobs.slice().reverse();
    view().innerHTML = `<div class="stack">${jobs.length ? jobs.map(jobCard).join("") : `<div class="empty">No hay lecturas en cola.</div>`}</div>`;
  }

  // ─── resultado de una lectura ────────────────────────────────────────────
  const Reading = { data: null, done: new Set(), titles: null };
  async function getReading(id, refresh) {
    const key = "reading:" + id;
    if (!refresh) { const c = await Cache.get(key); if (c && (!navigator.onLine || State.offlineAuth)) return c; }
    if (navigator.onLine && !State.offlineAuth) {
      try { const r = await api(`/api/readings/${id}`, { timeout: 60000 }); Cache.set(key, r); return r; }
      catch (e) { const c = await Cache.get(key); if (c) return c; throw e; }
    }
    const c = await Cache.get(key);
    if (c) return c;
    throw new ApiError("Sin conexión y la lectura no está guardada en el teléfono", 0);
  }
  function engineItem(r, p) {
    try {
      const items = r.engine.images[p.image_index].items;
      return items.find((it) => it.index === p.item_index) || items[p.item_index] || null;
    } catch (e) { return null; }
  }
  function reviewItems(r) {
    const out = [];
    (r.products || []).forEach((p, idx) => {
      if (p.item_index == null || p.image_index == null) return;
      const key = `${p.image_index}:${p.item_index}`;
      if (Reading.done.has(key)) return;
      const it = engineItem(r, p);
      const ambiguous = Boolean(p.ambiguous || (it && it.ambiguous));
      if (!(p.needs_review || p.count_uncertain || ambiguous)) return;
      const cands = [];
      const push = (t) => { if (t && !cands.includes(t) && cands.length < 4) cands.push(t); };
      if (it && Array.isArray(it.candidates)) it.candidates.forEach(push);
      if (it && Array.isArray(it.catalog_top3)) it.catalog_top3.forEach((c) => push(c.title));
      if (it && Array.isArray(it.text_top3)) it.text_top3.forEach((c) => push(c.title));
      if (it && Array.isArray(it.visual_top3)) it.visual_top3.forEach((c) => push(c.title));
      const identified = p.match_status === "match" || p.match_status === "confirmed";
      out.push({ key, idx, p, it, ambiguous, candidates: cands, kind: p.needs_review || ambiguous || !identified ? "identify" : "count" });
    });
    return out;
  }
  async function viewReading(id) {
    setChrome({ top: true, tabs: true, title: "Resultado", sub: "" });
    view().innerHTML = `<div class="empty"><span class="spin" style="display:inline-block"></span></div>`;
    let r;
    try { r = await getReading(Number(id)); }
    catch (e) { view().innerHTML = `<div class="stack"><div class="ph"><a class="back" href="#/puntos">${icon("back")}Góndolas</a></div><div class="notice notice-bad">${icon("warn")}<span>${esc(e.message)}</span></div></div>`; return; }
    Reading.data = r;
    Reading.done = new Set((await Cache.get("confirmed:" + r.id)) || []);
    Reading.titles = null;
    await loadPoints().catch(() => {});
    const p = pointById(r.point_id) || { id: r.point_id, name: r.point_id };
    const { gondola, store } = splitName(p);
    setChrome({ top: true, tabs: true, title: gondola, sub: [store, fmtDate(r.created_at)].filter(Boolean).join(" · ") });
    renderReading();
  }
  function renderReading() {
    const r = Reading.data, c = r.compliance;
    const pct = c ? c.compliance_pct : null;
    const review = reviewItems(r);
    const pt = pointById(r.point_id);
    const rep = c && c.replenishment ? c.replenishment : (r.products || []).filter((p) => p.out_of_stock).map((p) => ({ title: p.product && p.product !== "espacio vacío" ? p.product : "Espacio vacío (producto no identificado)", band: p.shelf_level, deficit: null, status: "missing", tag: null }));
    view().innerHTML = `
      <div class="stack">
        <div class="ph"><a class="back" href="#/punto/${encodeURIComponent(r.point_id)}">${icon("back")}Góndola</a></div>
        <div class="card"><div class="card-b">
          <div class="hero"><div class="big ${pctClass(pct)}">${pct != null ? nf(pct) + "<small>%</small>" : "–"}</div>
            <div class="l"><b>${pct != null ? (pct >= 90 ? "Cumple el planograma" : pct >= 70 ? "Cumplimiento parcial" : "Cumplimiento bajo") : (r.planogram_id ? "Sin cumplimiento calculado" : "Sin planograma asignado")}</b>
            <span>${c ? esc(c.planogram_name) + " · " : ""}${nf(c ? c.total_filled_facings : r.total_facings || 0)}${c ? " de " + nf(c.total_expected_facings) : ""} caras${pt && pt.latest && pt.latest.id !== r.id ? " · lectura anterior" : ""}</span></div></div>
          <div class="kpis" style="margin-top:14px">
            <div class="kpi"><div class="v">${nf(r.total_facings || 0)}</div><div class="l">Caras</div></div>
            <div class="kpi"><div class="v">${nf(r.shelf_levels_detected || 0)}</div><div class="l">Niveles</div></div>
            <div class="kpi"><div class="v ${review.length ? "warn" : ""}">${nf(review.length)}</div><div class="l">Por revisar</div></div>
          </div>
        </div></div>

        <div class="card"><div class="card-h"><h2>Reponer ahora</h2><span class="small muted">${rep.length ? plural(rep.length, "producto", "productos") : ""}</span></div>
          <div class="card-b">${rep.length ? `<div class="list">${rep.map((x) => `<div class="item"><div class="m"><div class="t">${esc(x.title)}${x.tag ? ` <span class="tag tag-info tag-plain" style="vertical-align:2px">${esc(x.tag)}</span>` : ""}</div><div class="s">${x.band != null ? "Banda " + esc(x.band) : ""}${x.uncertain ? " · conteo por confirmar" : ""}</div></div><div class="r ${x.status === "missing" ? "bad" : "warn"}">${x.deficit != null ? "faltan " + nf(x.deficit) : "falta"}<small>${x.status === "missing" ? "sin stock" : `${nf(x.detected_facings)} de ${nf(x.expected_facings)}`}</small></div></div>`).join("")}</div>` : `<div class="empty" style="padding:8px 0">${c ? "Nada que reponer según el planograma." : "Sin huecos detectados."}</div>`}</div>
        </div>

        <div class="card"><div class="card-h"><h2>Por confirmar <span class="small muted" style="font-weight:400">(opcional)</span></h2><span class="small muted">${review.length ? "1 de " + nf(review.length) : ""}</span></div>
          <div class="card-b review" id="review">${review.length ? `<p class="small muted" style="margin:0 0 8px">La lectura ya quedó registrada. Si tienes un momento, confirma estos recortes: el sistema aprende y la próxima foto sale mejor.</p>` + reviewCard(review[0], review.length) : `<div class="empty" style="padding:8px 0">${Reading.done.size ? "Todo confirmado. Gracias." : "Nada por confirmar."}</div>`}</div>
        </div>

        <div class="card"><div class="card-h"><h2>Ver góndola</h2><span class="small muted">${plural((r.image_urls || []).length, "foto", "fotos")}</span></div>
          <div class="card-b" id="shelf"><button class="btn btn-sm" type="button" data-act="show-shelf">Mostrar fotos con detecciones</button><p class="small muted" style="margin-top:6px">Descarga las fotos originales (pesan más).</p></div>
        </div>
      </div>`;
  }
  function reviewCard(item, total) {
    const { p, it, candidates, kind } = item;
    const crop = `/api/readings/${Reading.data.id}/crops/${p.image_index}/${p.item_index}.jpg`;
    const facings = Math.max(0, Number(p.facings) || 0);
    const where = `Nivel ${esc(p.shelf_level)} · posición ${esc(p.position_index)}`;
    const title = p.product && p.product !== "producto no identificado" ? p.product : null;
    const done = Reading.done.size, remaining = total;
    const dots = `<div class="progress-dots" aria-hidden="true">${Array.from({ length: Math.min(12, done + remaining) }, (_, i) => `<i class="${i < done ? "on" : ""}"></i>`).join("")}</div>`;
    let question, opts;
    if (kind === "count") {
      question = `<b>${esc(title)}</b><span>${where} · ¿cuántas caras hay? El motor contó ${nf(facings)}.</span>`;
      opts = `<div class="rc-count"><div class="stepper"><button type="button" data-act="st-dec" aria-label="Menos">−</button><output id="stVal">${nf(facings)}</output><button type="button" data-act="st-inc" aria-label="Más">+</button></div>
        <button class="opt primary" style="width:auto" type="button" data-act="confirm" data-title="${esc(title)}" data-use-count="1">Confirmar</button></div>`;
    } else {
      const heading = candidates.length > 1 || !title ? "¿Qué producto es?" : `¿Es ${esc(title)}?`;
      question = `<b>${heading}</b><span>${where}${it && it.ocr ? " · texto leído: «" + esc(String(it.ocr).slice(0, 60)) + "»" : ""}</span>`;
      const list = [];
      if (title && candidates.length <= 1) list.push(`<button class="opt primary" type="button" data-act="confirm" data-title="${esc(title)}">Sí, es ${esc(title)}</button>`);
      candidates.filter((t) => !(title && candidates.length <= 1 && t === title)).forEach((t, i) => list.push(`<button class="opt ${i === 0 && !title ? "primary" : ""}" type="button" data-act="confirm" data-title="${esc(t)}">${esc(t)}</button>`));
      list.push(`<button class="opt quiet" type="button" data-act="other">Otro producto…</button>`);
      list.push(`<button class="opt quiet" type="button" data-act="confirm" data-title="">No está en el planograma</button>`);
      opts = `<div class="opts">${list.join("")}</div>
        <div class="rc-count"><span class="small t2">Caras</span><div class="stepper"><button type="button" data-act="st-dec" aria-label="Menos">−</button><output id="stVal">${nf(facings)}</output><button type="button" data-act="st-inc" aria-label="Más">+</button></div></div>`;
    }
    return `<div class="rc" data-key="${item.key}" data-ii="${p.image_index}" data-ki="${p.item_index}" data-facings="${facings}">
      ${dots}
      <div class="rc-top"><img class="crop" src="${crop}" alt="Recorte del producto" loading="lazy"><div class="rc-q">${question}</div></div>
      ${opts}
    </div>`;
  }
  async function confirmItem(card, title, useCount) {
    const ii = Number(card.dataset.ii), ki = Number(card.dataset.ki);
    const orig = Number(card.dataset.facings), cur = Number(($("#stVal", card) || {}).value || ($("#stVal", card) || {}).textContent || orig);
    const body = { image_index: ii, item_index: ki, title: title || null };
    if (title && (useCount || cur !== orig)) body.facings = cur;
    $$("button", card).forEach((b) => (b.disabled = true));
    try {
      const resp = await api(`/api/readings/${Reading.data.id}/confirm`, { method: "POST", json: body, timeout: 30000 });
      const key = `${ii}:${ki}`;
      Reading.done.add(key);
      Cache.set("confirmed:" + Reading.data.id, Array.from(Reading.done));
      if (resp && resp.reading) { Reading.data = resp.reading; Cache.set("reading:" + Reading.data.id, Reading.data); }
      const pt = pointById(Reading.data.point_id);
      if (pt && pt.latest && pt.latest.id === Reading.data.id) { pt.latest.needs_review = reviewItems(Reading.data).length; Cache.set(pointsKey(), { list: State.points, at: State.pointsCachedAt }); }
      card.classList.add("leaving");
      await sleep(190);
      renderReading();
    } catch (e) {
      $$("button", card).forEach((b) => (b.disabled = false));
      toast(esc(e.message), true);
    }
  }
  async function otherProductSheet(card) {
    const r = Reading.data;
    let titles = Reading.titles;
    if (!titles) {
      titles = [];
      if (r.compliance && r.compliance.items) titles = r.compliance.items.map((i) => i.title);
      else if (r.planogram_id) { try { const pg = await api(`/api/planograms/${encodeURIComponent(r.planogram_id)}`); titles = (pg.items || []).map((i) => i.title); } catch (e) { /* sin lista */ } }
      titles = Array.from(new Set(titles));
      Reading.titles = titles;
    }
    const s = sheet(`<h2>¿Qué producto es?</h2>
      <div class="search">${icon("search")}<input class="in" id="opQ" placeholder="Buscar en el planograma o escribir el nombre" autocomplete="off"></div>
      <div class="opts" id="opList"></div>
      <button class="btn" type="button" data-close>Cancelar</button>`);
    const list = s.querySelector("#opList"), q = s.querySelector("#opQ");
    const draw = () => {
      const v = q.value.trim().toLowerCase();
      const hits = titles.filter((t) => !v || t.toLowerCase().includes(v)).slice(0, 40);
      list.innerHTML = hits.map((t) => `<button class="opt" type="button" data-title="${esc(t)}">${esc(t)}</button>`).join("") + (v && !hits.some((t) => t.toLowerCase() === v) ? `<button class="opt quiet" type="button" data-title="${esc(q.value.trim())}">Usar «${esc(q.value.trim())}»</button>` : "") + (!hits.length && !v ? `<div class="empty">Sin planograma: escribe el nombre.</div>` : "");
    };
    q.addEventListener("input", draw);
    draw();
    list.addEventListener("click", (e) => { const b = e.target.closest("[data-title]"); if (!b) return; closeSheet(); confirmItem(card, b.dataset.title, false); });
    s.querySelector("[data-close]").addEventListener("click", closeSheet);
  }
  function renderShelf() {
    const r = Reading.data, host = $("#shelf");
    const imgs = (r.engine && r.engine.images) || [];
    const byItem = new Map();
    (r.products || []).forEach((p) => { if (p.item_index != null) byItem.set(`${p.image_index}:${p.item_index}`, p); });
    host.innerHTML = `<div class="legend"><span><i style="border-color:var(--good)"></i>identificado</span><span><i style="border-color:var(--warn)"></i>por confirmar</span><span><i style="border-color:var(--bad)"></i>sin identificar</span><span><i style="border-color:var(--ink3);border-style:dashed"></i>letrero</span></div>
      <div class="stack" style="margin-top:10px">${(r.image_urls || []).map((u, i) => {
        const info = imgs[i], size = info && info.size;
        const rects = info && size ? info.items.map((it) => {
          const p = byItem.get(`${i}:${it.index}`);
          let cls = "bad";
          if (it.status === "signage") cls = "sig";
          else if (p && p.match_status === "confirmed") cls = "ok";
          else if (p && (p.needs_review || p.count_uncertain)) cls = "rev";
          else if ((p && p.match_status === "match") || it.status === "match") cls = "ok";
          const [x1, y1, x2, y2] = it.box;
          return `<rect class="${cls}" x="${x1}" y="${y1}" width="${Math.max(1, x2 - x1)}" height="${Math.max(1, y2 - y1)}" rx="4"><title>${esc(p ? p.product : it.title || it.status)}</title></rect>`;
        }).join("") : "";
        return `<div class="shelf"><img src="${u}" alt="Foto ${i + 1} de la góndola" loading="lazy">${size ? `<svg viewBox="0 0 ${size[0]} ${size[1]}" preserveAspectRatio="none" aria-hidden="true">${rects}</svg>` : ""}</div>`;
      }).join("")}</div>`;
  }

  // ─── ajustes ─────────────────────────────────────────────────────────────
  function viewSettings() {
    setChrome({ top: true, tabs: true, title: "Ajustes", sub: headerSub() });
    const dark = Theme.current() === "dark", low = Settings.get("lowData", false);
    const sw = navigator.serviceWorker && navigator.serviceWorker.controller ? "activo" : "no registrado";
    const roleLabel = { tienda: "tienda", supervisor: "supervisor", admin: "administrador" }[State.me && State.me.role] || "";
    const storeRow = State.me && (State.me.role === "tienda" || myStore()) ? `<dt>Local</dt><dd>${myStore() ? esc(myStore()) : `<span class="warn">sin asignar</span>`}</dd>` : "";
    view().innerHTML = `
      <div class="stack">
        <div class="card"><div class="card-b">
          <div class="switch"><div class="l"><b>Tema oscuro</b><span>Claro por defecto</span></div><button class="toggle" type="button" role="switch" aria-checked="${dark}" aria-label="Tema oscuro" data-act="toggle-theme"></button></div>
          <div class="switch"><div class="l"><b>Modo datos bajos</b><span>Fotos a 2000 px y calidad 0,75 (≈ 700 KB cada una, en vez de 3000 px y ≈ 1,4 MB)</span></div><button class="toggle" type="button" role="switch" aria-checked="${low}" aria-label="Modo datos bajos" data-act="toggle-low"></button></div>
        </div></div>
        <div class="card"><div class="card-b">
          <dl class="kv"><dt>Usuario</dt><dd>${esc(State.user || "–")}${roleLabel ? ` <span class="muted">· ${roleLabel}</span>` : ""}</dd>${storeRow}<dt>Versión</dt><dd class="mono">${esc(VERSION)}</dd><dt>Sin conexión</dt><dd>${sw === "activo" ? "lista para abrir sin red" : "caché " + sw}</dd><dt>Cola</dt><dd>${plural(Queue.pending().length, "lectura pendiente", "lecturas pendientes")}</dd></dl>
        </div></div>
        <div class="card"><div class="card-b">
          <button class="btn block" type="button" data-act="refresh">Actualizar lista de góndolas</button>
          <div style="height:8px"></div>
          <button class="btn btn-danger block" type="button" data-act="logout">Cerrar sesión</button>
          <p class="small muted" style="margin-top:8px">Las lecturas en cola se conservan en el teléfono y se envían al volver a entrar.</p>
        </div></div>
      </div>`;
  }

  // ─── acciones delegadas ──────────────────────────────────────────────────
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act]");
    if (!b || b.disabled) return;
    const act = b.dataset.act;
    const p = State.route.id ? pointById(State.route.id) : null;
    switch (act) {
      case "new-point": newPointSheet(); break;
      case "gallery": $("#fileGal").click(); break;
      case "ph-up": case "ph-down": case "ph-del": {
        if (!p) return;
        const photos = draft(p.id), i = Number(b.dataset.i);
        if (act === "ph-del") { URL.revokeObjectURL(photos[i].url); photos.splice(i, 1); }
        else { const j = act === "ph-up" ? i - 1 : i + 1; if (j < 0 || j >= photos.length) return; [photos[i], photos[j]] = [photos[j], photos[i]]; }
        renderPhotoList(p); Cam.renderThumbs();
        break;
      }
      case "load-hist": if (p) loadHistory(p); break;
      case "job-retry": Queue.retry(Number(b.dataset.id)); break;
      case "job-del": if (confirm("¿Eliminar esta lectura de la cola? Las fotos se perderán.")) Queue.remove(Number(b.dataset.id)); break;
      case "show-shelf": renderShelf(); break;
      case "st-dec": case "st-inc": {
        const out = $("#stVal", b.closest(".rc"));
        const v = Math.max(0, Math.min(99, Number(out.textContent) + (act === "st-inc" ? 1 : -1)));
        out.textContent = nf(v); out.value = String(v);
        break;
      }
      case "confirm": confirmItem(b.closest(".rc"), b.dataset.title, Boolean(b.dataset.useCount)); break;
      case "other": otherProductSheet(b.closest(".rc")); break;
      case "toggle-theme": Theme.toggle(); b.setAttribute("aria-checked", String(Theme.current() === "dark")); break;
      case "toggle-low": { const v = !Settings.get("lowData", false); Settings.set("lowData", v); b.setAttribute("aria-checked", String(v)); break; }
      case "refresh": b.disabled = true; try { await loadPoints(true); toast("Lista actualizada"); } catch (ex) { toast(esc(ex.message), true); } b.disabled = false; break;
      case "logout": {
        if (Queue.pending().length && !confirm(`Hay ${Queue.pending().length} lectura(s) en cola. Se enviarán cuando vuelvas a entrar. ¿Cerrar sesión?`)) return;
        try { await api("/api/auth/logout", { method: "POST" }); } catch (ex) { /* sin red */ }
        State.user = null; State.me = null; State.offlineAuth = false; State.points = null; State.planograms = null;
        Settings.del("me");
        go("#/login");
        break;
      }
      default: break;
    }
  });

  // ─── router ──────────────────────────────────────────────────────────────
  function parseRoute() {
    const h = location.hash.replace(/^#\/?/, "");
    const parts = h.split("/").filter(Boolean);
    return { name: parts[0] || "puntos", id: parts[1] ? decodeURIComponent(parts[1]) : null };
  }
  async function render() {
    const r = parseRoute();
    const seq = ++State.renderSeq;
    if (!$("#cam").hidden && r.name !== "captura") Cam.close();
    closeSheet();
    if (!State.user && r.name !== "login") { State.returnTo = location.hash; location.hash = "#/login"; return; }
    if (State.user && r.name === "login") { location.hash = "#/puntos"; return; }
    State.route = r;
    window.scrollTo(0, 0);
    try {
      if (r.name === "login") viewLogin();
      else if (r.name === "puntos") await viewPoints();
      else if (r.name === "punto" && r.id) await viewPoint(r.id);
      else if (r.name === "captura" && r.id) await viewCapture(r.id);
      else if (r.name === "lectura" && r.id) await viewReading(r.id);
      else if (r.name === "cola") viewQueue();
      else if (r.name === "ajustes") viewSettings();
      else location.hash = "#/puntos";
    } catch (e) {
      if (seq !== State.renderSeq) return;
      view().innerHTML = `<div class="notice notice-bad">${icon("warn")}<span>${esc(e.message || e)}</span></div>`;
    }
    renderStatus();
  }

  // ─── arranque ────────────────────────────────────────────────────────────
  async function boot() {
    Theme.set(Theme.current());
    $("#themeBtn").addEventListener("click", () => Theme.toggle());
    $("#statusBtn").addEventListener("click", () => go("#/cola"));
    bindCamera();
    Queue.on((kind) => {
      renderStatus();
      if (kind === "progress") { $$("[data-job]").forEach((el) => { const j = Queue.jobs.find((x) => x.id === Number(el.dataset.job)); if (j) el.outerHTML = jobCard(j); }); return; }
      if (State.route.name === "cola") viewQueue();
      else if (State.route.name === "punto") { renderPointJobs(State.route.id); const p = pointById(State.route.id); if (kind === "change" && p && !Queue.sending) viewPoint(p.id); }
      else if (State.route.name === "puntos") renderPointsList();
    });
    window.addEventListener("online", () => { renderStatus(); Queue.kick(); if (State.offlineAuth) verifySession(); });
    window.addEventListener("offline", renderStatus);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) Queue.kick(); });
    window.addEventListener("hashchange", render);
    await Queue.load();
    await verifySession();
    if (!location.hash) location.hash = State.user ? "#/puntos" : "#/login";
    render();
    registerSW();
  }
  function applyMe(me) {
    State.user = me.username; State.offlineAuth = false;
    State.me = { username: me.username, role: me.role || null, store_id: me.store_id || null, store_name: me.store_name || null };
    if (Settings.get("remember", true)) { Settings.set("user", me.username); Settings.set("me", State.me); }
  }
  async function verifySession(justLoggedIn) {
    const remembered = Settings.get("user", "");
    try {
      applyMe(await api("/api/auth/me", { noAuthRedirect: true, timeout: 8000 }));
      Queue.kick();
    } catch (e) {
      if (e.status === 401) { State.user = null; State.me = null; State.offlineAuth = false; }
      else if (justLoggedIn) { State.user = justLoggedIn; State.me = { username: justLoggedIn, role: null, store_id: null, store_name: null }; State.offlineAuth = false; }
      else if (remembered && !State.user) {   // sin red: se entra con lo guardado (usuario y local de la última sesión)
        State.user = remembered; State.offlineAuth = true;
        const saved = Settings.get("me", null);
        State.me = saved && saved.username === remembered ? saved : { username: remembered, role: null, store_id: null, store_name: null };
      }
    }
    renderStatus();
  }
  function registerSW() {
    if (!("serviceWorker" in navigator) || location.pathname !== "/tienda") return;   // en pruebas locales (/static/…) no hay SW
    navigator.serviceWorker.register("/sw.js", { scope: "/tienda" }).then((reg) => {
      reg.addEventListener("updatefound", () => {
        const nw = reg.installing;
        if (!nw) return;
        nw.addEventListener("statechange", () => {
          // el SW nuevo ya hizo skipWaiting(): basta recargar para tomar la versión nueva (nunca se recarga sola)
          if (nw.state === "installed" && navigator.serviceWorker.controller) toast(`Nueva versión disponible <button type="button" id="swUpd">Actualizar</button>`, false, 15000)
            .querySelector("#swUpd").addEventListener("click", () => { nw.postMessage({ type: "SKIP_WAITING" }); setTimeout(() => location.reload(), 150); });
        });
      });
    }).catch(() => { /* sin SW: la app funciona igual, solo no arranca sin red */ });
  }
  boot();
})();
