/* Captura de fotos por enlace (/captura/<código>) — piloto Salcobrand. Sin dependencias ni build.
   Misma experiencia que la recolección de PF (PF/app/frontend/recoleccion.js), adaptada al piloto Salcobrand:
   - Enlace por local (entra con el local ya elegido) o UNIVERSAL (la persona elige su local de la lista al abrir).
   - Al entrar se elige QUÉ se fotografía: "Góndola" (guiado franja por franja y al final la completa) o "Producto"
     (alta del local: una foto por percha con el producto de frente y su etiqueta de precio).
   - Cámara en la página (getUserMedia, la mayor resolución; ImageCapture.takePhoto si existe). Sin cámara o sin permiso:
     la cámara del teléfono (input capture) y la galería.
   - Cola sin conexión: cada foto se guarda en IndexedDB y se borra SOLO cuando el servidor responde 200. Si el teléfono
     recarga la página al volver de la cámara, la foto ya está guardada y se envía sola. `cliente_id` evita duplicados.
   - Aviso suave si la foto salió oscura, con reflejo o movida (no bloquea).
   Vistas: inicio (local y tipo de foto) · cámara · inactivo. */
(() => {
  "use strict";

  const VERSION = (document.querySelector('meta[name="captura-version"]') || {}).content || "dev";
  const TOKEN = (/^\/captura\/([a-z0-9][a-z0-9-]{3,80})\/?$/.exec(location.pathname) || [])[1] || "";
  const API = "/captura/" + TOKEN;
  const SHARP_MIN = 60, LUM_MIN = 45, LUM_MAX = 225;
  const MAX_BYTES = 25 * 1024 * 1024;
  const MAX_LADO = 4096, LADO_REDUCIR = 4700, PESO_REDUCIR = 9 * 1024 * 1024, JPEG_Q = 0.92;
  const PARALELO = 2, TIRA_MAX = 24;
  const FRANJAS = ["1", "2", "3", "4", "5", "6", "completa"];
  const TIPOS = {
    gondola: { nombre: "Góndola", largo: "Fotos de la góndola", icono: "shelf" },
    producto: { nombre: "Producto", largo: "Fotos de producto", icono: "tag" },
  };
  const espera = (n) => Math.round(Math.min(120000, 2000 * Math.pow(2, Math.max(0, n - 1))) * (0.85 + Math.random() * 0.3));

  // ─── utilidades ──────────────────────────────────────────────────────────
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (id) => `<svg class="i" aria-hidden="true"><use href="#i-${id}"/></svg>`;
  const nf = (n, d) => Number(n).toLocaleString("es-CL", { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 });
  const plural = (n, s, p) => `${nf(n)} ${n === 1 ? s : p}`;
  const fmtBytes = (n) => (n < 1048576 ? nf(n / 1024) + " KB" : nf(n / 1048576, 1) + " MB");
  const hoy = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const nombreFranja = (f) => (f === "completa" ? "Completa" : f ? `Franja ${f}` : "Sin franja");
  const Store = {
    get(k, d) { try { const v = localStorage.getItem("sbcap." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("sbcap." + k, JSON.stringify(v)); } catch (e) { /* sin almacenamiento */ } },
  };
  const SK = (k) => `${TOKEN}.${k}`;                 // claves de ESTE enlace
  function toast(html, bad, ms) {
    const el = document.createElement("div");
    el.className = "toast" + (bad ? " bad" : "");
    el.innerHTML = html;
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), ms || 3200);
  }
  const Theme = {
    current() {
      const t = document.documentElement.getAttribute("data-theme");
      if (t === "dark" || t === "light") return t;
      return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    },
    paint() {
      const dark = this.current() === "dark";
      const b = $("#themeBtn");
      if (b) { b.innerHTML = icon(dark ? "sun" : "moon"); b.setAttribute("aria-label", dark ? "Cambiar a tema claro" : "Cambiar a tema oscuro"); }
      const color = S.vista === "camara" ? "#000000" : dark ? "#0f1726" : "#ffffff";
      $$('meta[name="theme-color"]').forEach((m) => { m.setAttribute("content", color); m.removeAttribute("media"); });
    },
    toggle() { const t = this.current() === "dark" ? "light" : "dark"; document.documentElement.setAttribute("data-theme", t); try { localStorage.setItem("sbcap.theme", t); } catch (e) { /* nada */ } this.paint(); },
  };
  function nuevoId() {
    if (window.crypto && crypto.randomUUID) { try { return crypto.randomUUID().replace(/-/g, ""); } catch (e) { /* contexto no seguro */ } }
    const b = new Uint8Array(16); (window.crypto || {}).getRandomValues ? crypto.getRandomValues(b) : b.forEach((_, i) => { b[i] = Math.floor(Math.random() * 256); });
    return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  }
  const Enviadas = {
    get() { const e = Store.get(SK("enviadas"), null); return e && e.fecha === hoy() ? e.n : 0; },
    sumar() { Store.set(SK("enviadas"), { fecha: hoy(), n: this.get() + 1 }); },
  };
  // navegador dentro de una app (WhatsApp, Instagram, Facebook): la cámara suele fallar o recargar la página
  const EN_APP = /WhatsApp|FBAN|FBAV|Instagram|Line\/|; wv\)/i.test(navigator.userAgent || "");

  // ─── IndexedDB: "cola" (metadatos + miniatura) y "blobs" (el archivo), con respaldo en memoria ──
  const Mem = { cola: new Map(), blobs: new Map(), seq: 1 };
  const enMem = (id) => typeof id === "string" && id.charAt(0) === "m";
  const pedido = (rq) => new Promise((res, rej) => { rq.onsuccess = () => res(rq.result); rq.onerror = () => rej(rq.error); });
  const fin = (t) => new Promise((res, rej) => { t.oncomplete = () => res(); t.onerror = () => rej(t.error); t.onabort = () => rej(t.error || new Error("abort")); });
  const DB = {
    _p: null, ok: true,
    open() {
      if (this._p) return this._p;
      this._p = new Promise((resolve, reject) => {
        if (!window.indexedDB) return reject(new Error("sin IndexedDB"));
        const rq = indexedDB.open("sb-captura", 1);
        rq.onupgradeneeded = () => {
          const d = rq.result;
          if (!d.objectStoreNames.contains("cola")) d.createObjectStore("cola", { keyPath: "id", autoIncrement: true });
          if (!d.objectStoreNames.contains("blobs")) d.createObjectStore("blobs", { keyPath: "id" });
        };
        rq.onsuccess = () => resolve(rq.result);
        rq.onerror = () => reject(rq.error || new Error("IndexedDB"));
        rq.onblocked = () => reject(new Error("IndexedDB bloqueada"));
      });
      return this._p;
    },
    limpio(m) { const r = Object.assign({}, m); delete r.enviando; return r; },
    async agregar(meta, blob) {
      try {
        const d = await this.open();
        const t = d.transaction(["cola", "blobs"], "readwrite");
        let id = null;
        const rq = t.objectStore("cola").add(this.limpio(meta));
        rq.onsuccess = () => { id = rq.result; t.objectStore("blobs").put({ id, blob }); };
        await fin(t);
        return id;
      } catch (e) {
        if (this.ok) toast(e && e.name === "QuotaExceededError" ? "El teléfono no tiene espacio para guardar más fotos sin enviar. No cierres esta página hasta que se envíen."
          : "Este navegador no guarda las fotos sin señal. No cierres esta página hasta que se envíen.", true, 6000);
        this.ok = false;
        const id = "m" + Mem.seq++;
        Mem.cola.set(id, Object.assign({}, meta, { id })); Mem.blobs.set(id, blob);
        return id;
      }
    },
    async blob(id) {
      if (enMem(id)) return Mem.blobs.get(id) || null;
      const d = await this.open();
      const r = await pedido(d.transaction("blobs").objectStore("blobs").get(id));
      return r ? r.blob : null;
    },
    async quitar(id) {
      if (enMem(id)) { Mem.cola.delete(id); Mem.blobs.delete(id); return; }
      const d = await this.open();
      const t = d.transaction(["cola", "blobs"], "readwrite");
      t.objectStore("cola").delete(id); t.objectStore("blobs").delete(id);
      await fin(t);
    },
    async actualizar(meta) {
      if (enMem(meta.id)) { Mem.cola.set(meta.id, meta); return; }
      try { const d = await this.open(); const t = d.transaction("cola", "readwrite"); t.objectStore("cola").put(this.limpio(meta)); await fin(t); } catch (e) { /* queda como estaba */ }
    },
    async todas() {
      let out = [];
      try { const d = await this.open(); out = await pedido(d.transaction("cola").objectStore("cola").getAll()); } catch (e) { this.ok = false; }
      return out.concat(Array.from(Mem.cola.values())).filter((f) => !f.token || f.token === TOKEN);
    },
  };

  // ─── sesiones: una por local y tipo, desde que se abre la cámara hasta "Terminar" ──
  const Sesiones = {
    leer() { const d = Store.get(SK("sesiones"), null); return d && Array.isArray(d.lista) ? d : { actual: null, lista: [] }; },
    guardar(d) { d.lista = d.lista.filter((x) => x.dia === hoy() || x.id === d.actual).slice(-40); Store.set(SK("sesiones"), d); },
    actual() { const d = this.leer(); return d.lista.find((x) => x.id === d.actual) || null; },
    actualId() { return this.leer().actual; },
    iniciar(local, tipo) {
      const d = this.leer();
      const cur = d.lista.find((x) => x.id === d.actual);
      if (cur && !cur.fin && cur.local && cur.local.store_id === local.store_id && cur.tipo === tipo && cur.dia === hoy()) return cur;
      if (cur && !cur.fin) cur.fin = new Date().toISOString();
      const n = { id: "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), dia: hoy(), local: { store_id: local.store_id, label: local.label },
        tipo, inicio: new Date().toISOString(), fin: null, tomadas: 0, enviadas: 0, rechazadas: 0, franjas: {} };
      d.lista.push(n); d.actual = n.id; this.guardar(d);
      return n;
    },
    sumar(id, campo, franja) {
      if (!id) return;
      const d = this.leer(); const x = d.lista.find((y) => y.id === id);
      if (!x) return;
      x[campo] = (x[campo] || 0) + 1;
      if (campo === "tomadas" && franja) { x.franjas = x.franjas || {}; x.franjas[franja] = (x.franjas[franja] || 0) + 1; }
      this.guardar(d);
    },
    terminar() {
      const d = this.leer(); const x = d.lista.find((y) => y.id === d.actual);
      if (x && !x.fin) x.fin = new Date().toISOString();
      d.actual = null; this.guardar(d);
      return x;
    },
    hoy() { return this.leer().lista.filter((x) => x.dia === hoy() && x.tomadas > 0); },
    pendientes(id) { return S.cola.filter((f) => f.sesion === id && f.estado !== "rechazada").length; },
  };

  // ─── estado ──────────────────────────────────────────────────────────────
  const S = {
    info: Store.get(SK("estado"), null),       // {label, universal, locales: [{store_id, label}], local, hoy_por_local}
    local: Store.get(SK("local"), null),       // {store_id, label}
    tipo: Store.get(SK("tipo"), null),         // "gondola" | "producto"
    franja: Store.get(SK("franja"), "1"),      // franja actual (góndola) o elegida (producto, "" = sin indicar)
    vista: null, cola: [], activos: 0, sinSenal: false, inactivo: !TOKEN, timer: null,
    sesion: 0, sesionId: null, tira: [], procesando: 0, avisoT: 0,
    cam: { stream: null, track: null, ic: null, ocupado: false, foto: null, caps: {}, torch: false, zoom: null, error: null, iniciando: false, lock: null },
  };
  const locales = () => (S.info && S.info.locales) || [];
  const universal = () => !!(S.info && S.info.universal);
  const OTRO = /^LOCAL-[1-9][0-9]{0,3}$/;                                        // "Otro local" escrito a mano (universal)
  function ajustarLocal() {
    const ls = locales();
    if (!S.info) return;
    if (!universal()) S.local = ls[0] || null;                                   // enlace por local: el suyo, siempre
    else if (S.local && !ls.some((l) => l.store_id === S.local.store_id)) { if (!OTRO.test(S.local.store_id)) S.local = null; }   // ya no está en la lista
    else if (S.local) S.local = ls.find((l) => l.store_id === S.local.store_id);
    Store.set(SK("local"), S.local);
  }
  async function cargarEstado() {
    if (!TOKEN) return;
    try {
      const r = await fetch(API + "/estado", { credentials: "omit", cache: "no-store" });
      if (r.status === 404) { S.inactivo = true; return; }
      if (!r.ok) throw new Error("HTTP " + r.status);
      S.info = await r.json();
      Store.set(SK("estado"), S.info);
      ajustarLocal();
    } catch (e) { /* sin señal: sirve el estado guardado en el teléfono */ }
  }
  const hoyDe = (store_id, tipo) => {
    const x = S.info && S.info.hoy_por_local && S.info.hoy_por_local[store_id];
    return x ? (tipo ? x[tipo] || 0 : (x.gondola || 0) + (x.producto || 0)) : 0;
  };

  // ─── vistas ──────────────────────────────────────────────────────────────
  const LOCKUP = `<span class="lockup" aria-label="Salcobrand · Fotos de góndola"><span class="client"><b>Salcobrand</b></span><span class="sep"></span>
      <span class="client"><span class="para">Fotos de góndola</span></span></span>`;
  const top = () => `<header class="r-top">${LOCKUP}<button class="btn btn-ghost btn-icon" type="button" data-act="ayuda" aria-label="¿Para qué es esto?">${icon("help")}</button>
      <button class="btn btn-ghost btn-icon" id="themeBtn" type="button" data-act="tema"></button></header>`;

  function render() {
    closeSheet();
    if (S.inactivo) viewInactivo();
    else if (S.vista === "camara" && S.local && S.tipo) viewCamara();
    else viewInicio();
    Theme.paint();
  }

  function estadoLinea() {
    const n = S.cola.length;
    if (!n) return "";
    const off = !navigator.onLine || S.sinSenal;
    return `<div class="r-status-line${off ? " off" : ""}" id="rEstado">${icon(off ? "cloud-off" : "upload")}<span>${plural(n, "foto guardada", "fotos guardadas")} en este teléfono · ${off ? "se envían solas cuando vuelva la señal" : "enviándose"}</span>
      <button class="btn btn-sm" type="button" data-act="cola">Ver</button></div>`;
  }
  function avisoApp() {
    if (!EN_APP) return "";
    return `<div class="r-inapp">${icon("alert")}<div><b>Ábrelo en Safari o Chrome</b>Dentro de WhatsApp la cámara puede cerrarse y perder la foto. Toca los tres puntos (o el botón compartir) y elige «Abrir en el navegador».
      <button class="btn btn-sm" type="button" data-act="copiar">${icon("link")}Copiar el enlace</button></div></div>`;
  }

  function viewInicio() {
    salirCamara();
    S.vista = "inicio";
    const ls = locales(), l = S.local;
    const cur = Sesiones.actual();
    let cuerpo;
    if (!S.info) {
      cuerpo = `<div class="r-hello"><span class="kicker">${icon("camera")}Piloto Salcobrand</span><h1>Cargando…</h1></div>
        <div class="r-empty" style="padding:18px;text-align:center">${navigator.onLine ? '<span class="spinner"></span>' : "Sin señal: abre el enlace con internet la primera vez."}</div>`;
    } else if (universal() && !l) {
      cuerpo = `<div class="r-hello"><span class="kicker">${icon("store")}Paso 1 de 2</span><h1>¿En qué local estás?</h1>
          <p>Elige tu local. Queda guardado en este teléfono.</p></div>
        <div class="r-list">${ls.map((x) => `<button class="r-opt" type="button" data-local="${esc(x.store_id)}"><span class="ic">${icon("store")}</span>
          <span class="g"><b>${esc(x.label)}</b><span>${hoyDe(x.store_id) ? `${plural(hoyDe(x.store_id), "foto", "fotos")} hoy` : "Sin fotos hoy"}</span></span>${icon("right")}</button>`).join("")}</div>
        ${S.info.otro_local !== false ? `<form class="r-otro" id="otroLocal" novalidate><label for="otroNum">¿Tu local no está en la lista? Escribe su número</label>
          <div class="row"><input id="otroNum" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="4" placeholder="Ej.: 212" autocomplete="off" enterkeyhint="go">
          <button class="btn btn-primary" type="submit">Seguir</button></div></form>` : ""}`;
    } else {
      const seguir = cur && !cur.fin && cur.dia === hoy() && l && cur.local && cur.local.store_id === l.store_id;
      cuerpo = `<div class="r-hello"><span class="kicker">${icon("camera")}${universal() ? "Paso 2 de 2" : "Fotos para el piloto"}</span><h1>¿Qué vas a fotografiar?</h1>
          <span class="loc">${icon("store")}${esc(l ? l.label : "")}${universal() ? `<button class="btn btn-link" type="button" data-act="cambiar-local">Cambiar</button>` : ""}</span></div>
        ${seguir ? `<button class="r-resume" type="button" data-tipo="${esc(cur.tipo)}"><span class="ic">${icon(TIPOS[cur.tipo].icono)}</span>
          <span class="g"><small>Seguir donde quedaste</small><b>${esc(TIPOS[cur.tipo].largo)}</b><span>${plural(cur.tomadas, "foto", "fotos")} en esta toma</span></span>${icon("right")}</button>` : ""}
        <div class="r-modes">
          <button class="r-mode" type="button" data-tipo="gondola"><span class="h"><span class="ic">${icon("shelf")}</span>
            <span><b>Góndola</b><small>Una foto por franja y la góndola completa</small></span>${icon("right")}</span>
            <ul><li>${icon("check")}De arriba hacia abajo: franja 1, 2, 3… y al final la góndola completa.</li>
              <li>${icon("check")}De frente, a un metro, sin flash.</li></ul>
            ${l && hoyDe(l.store_id, "gondola") ? `<span class="tag tag-good cnt">${icon("check")}${plural(hoyDe(l.store_id, "gondola"), "foto", "fotos")} hoy</span>` : ""}</button>
          <button class="r-mode prod" type="button" data-tipo="producto"><span class="h"><span class="ic">${icon("tag")}</span>
            <span><b>Producto</b><small>Alta del local: una foto por percha</small></span>${icon("right")}</span>
            <ul><li>${icon("check")}El producto de frente y su etiqueta de precio completa en la misma foto.</li>
              <li>${icon("check")}A unos 30 cm. Una foto por percha, todas las perchas.</li></ul>
            ${l && hoyDe(l.store_id, "producto") ? `<span class="tag tag-good cnt">${icon("check")}${plural(hoyDe(l.store_id, "producto"), "foto", "fotos")} hoy</span>` : ""}</button>
        </div>`;
    }
    $("#app").innerHTML = top() + `<main class="r-main">${avisoApp()}${cuerpo}
      <div style="height:14px"></div>${estadoLinea()}
      <div id="rHoy">${resumenHoyHtml()}</div>
      <footer class="r-foot">
        <div class="row"><button class="btn btn-link" type="button" data-act="ayuda">${icon("help")}¿Cómo tomar las fotos?</button>${Enviadas.get() ? `<span>${plural(Enviadas.get(), "foto enviada", "fotos enviadas")} hoy desde este teléfono</span>` : ""}</div>
        <div class="r-priv">${icon("shield")}<span>No pedimos tu nombre ni tu correo. Las fotos son solo para el piloto de reconocimiento de productos de Salcobrand.</span></div>
        <span>Versión ${esc(VERSION)}</span></footer></main>`;
  }

  function viewInactivo() {
    salirCamara();
    S.vista = "inactivo";
    const n = S.cola.length;
    $("#app").innerHTML = top() + `<main class="r-main"><div class="r-off"><span class="r-off-ic">${icon("alert")}</span>
      <h1>Este enlace ya no está activo</h1><p>Pide un enlace nuevo a tu supervisor.</p>
      ${n ? `<p class="muted">Tienes ${plural(n, "foto guardada", "fotos guardadas")} en este teléfono que no alcanzaron a enviarse.</p>` : ""}</div></main>`;
  }

  // ─── navegación: "atrás" del teléfono vuelve de la cámara al inicio ──
  function ir(v) {
    const actual = history.state && history.state.v;
    if (v === "inicio") {
      if (actual === "camara") { history.back(); return; }
      S.vista = "inicio"; render(); return;
    }
    if (v === "camara" && (!S.local || !S.tipo)) { ir("inicio"); return; }
    if (actual !== v) history.pushState({ v }, "");
    S.vista = v;
    render();
    window.scrollTo(0, 0);
  }
  window.addEventListener("popstate", () => {
    const v = (history.state && history.state.v) || "inicio";
    S.vista = v === "camara" && (!S.local || !S.tipo) ? "inicio" : v;
    render();
  });
  function elegirLocal(store_id) {
    const l = locales().find((x) => x.store_id === store_id);
    if (!l) return;
    S.local = l; Store.set(SK("local"), l);
    render(); window.scrollTo(0, 0);
  }
  function otroLocal() {
    const n = parseInt((($("#otroNum") || {}).value || "").replace(/\D/g, ""), 10);
    if (!n || n > 9999) { toast("Escribe el número de tu local, solo números.", true); return; }
    const id = "LOCAL-" + n;
    S.local = locales().find((x) => x.store_id === id) || { store_id: id, label: "Local " + n };
    Store.set(SK("local"), S.local);
    render(); window.scrollTo(0, 0);
  }
  function elegirTipo(tipo) {
    if (!TIPOS[tipo] || !S.local) return;
    if (S.tipo !== tipo) { S.franja = tipo === "gondola" ? "1" : ""; Store.set(SK("franja"), S.franja); }
    const cur = Sesiones.actual();
    if (tipo === "gondola" && (!cur || cur.tipo !== "gondola" || cur.fin || cur.dia !== hoy())) { S.franja = "1"; Store.set(SK("franja"), "1"); }
    S.tipo = tipo; Store.set(SK("tipo"), tipo);
    ir("camara");
  }

  // ─── hojas ───────────────────────────────────────────────────────────────
  const Sheet = { kind: null };
  function sheet(html, kind, sinFoco) {
    const refresco = sinFoco && Sheet.kind === kind && $("#sheetHost .sheet");
    Sheet.kind = kind;
    if (refresco) { refresco.innerHTML = html; return; }
    $("#sheetHost").innerHTML = `<div class="sheet-bg" id="sheetBg"><div class="sheet" role="dialog" aria-modal="true">${html}</div></div>`;
    const b = $("#sheetHost .sheet .btn-primary") || $("#sheetHost .sheet button");
    if (b) b.focus({ preventScroll: true });
  }
  function closeSheet() { $("#sheetHost").innerHTML = ""; Sheet.kind = null; }

  function bienvenida() {
    sheet(`<div class="r-welcome"><div class="hero"><span class="ic">${icon("scan")}</span><h2>Fotos para enseñarle al sistema a reconocer los productos</h2></div>
      <p class="lead">Con tus fotos entrenamos y medimos el reconocimiento de productos de la góndola de <b>Bienestar Sexual</b>.</p>
      <ul class="r-points">
        <li>${icon("shelf")}<span><b>Góndola:</b> una foto por franja, de arriba hacia abajo, y al final la góndola completa. De frente, a un metro y sin flash.</span></li>
        <li>${icon("tag")}<span><b>Producto (alta del local):</b> una foto por percha, a unos 30 cm, con el producto de frente y su <b>etiqueta de precio completa</b> en la misma foto.</span></li>
        <li>${icon("cloud-off")}<span><b>Funciona sin señal:</b> las fotos se guardan en el teléfono y se envían solas cuando vuelve internet. Puedes cerrar la página.</span></li>
        <li>${icon("shield")}<span><b>Sin datos personales:</b> no pedimos tu nombre ni tu correo.</span></li>
      </ul>
      <div class="opts"><button class="btn btn-primary btn-lg btn-block" type="button" data-act="entendido">Entendido</button></div></div>`, "ayuda");
  }

  function colaSheet(refresco) {
    const items = S.cola.slice().sort((a, b) => String(a.creado).localeCompare(String(b.creado)));
    const malas = items.filter((f) => f.estado === "rechazada");
    const off = !navigator.onLine || S.sinSenal;
    const bytes = items.reduce((s, f) => s + (f.bytes || 0), 0);
    const ahora = Date.now();
    const est = (f) => {
      if (f.estado === "rechazada") return `<span class="bad">No se pudo enviar: ${esc(f.error || "archivo no válido")}</span>`;
      if (f.enviando) return "Enviando…";
      if (off) return "Guardada · esperando señal";
      if ((f.next_at || 0) > ahora) return `Reintenta en ${nf(Math.ceil((f.next_at - ahora) / 1000))} s`;
      return "En cola";
    };
    sheet(`<h2>Fotos en este teléfono</h2>
      <div class="r-qsum"><span class="tag tag-good">${icon("check")}${plural(Enviadas.get(), "enviada", "enviadas")} hoy</span>
        <span class="tag${items.length - malas.length ? " tag-warn" : ""}">${icon("clock")}${nf(items.length - malas.length)} en cola</span>
        ${malas.length ? `<span class="tag tag-bad">${icon("alert")}${nf(malas.length)} con problema</span>` : ""}${bytes ? `<span class="tag">${fmtBytes(bytes)}</span>` : ""}</div>
      <p>${!items.length ? "No queda nada por enviar." : off ? "Sin señal: quedan guardadas en el teléfono y se envían solas cuando vuelva. Puedes seguir tomando fotos."
        : "Se envían solas, de a dos. Puedes seguir tomando fotos o cerrar la página: lo que falte se envía la próxima vez que la abras."}</p>
      ${items.length ? `<div class="r-qlist">${items.slice(0, 80).map((f) => `<div class="r-qitem">${f.thumb ? `<img class="th" src="${f.thumb}" alt="">` : `<span class="th"></span>`}
        <span class="g"><b>${esc((f.local && f.local.label) || "")} · ${esc(TIPOS[f.tipo] ? TIPOS[f.tipo].nombre : "")}${f.franja ? ` · ${esc(nombreFranja(f.franja))}` : ""}</b>${est(f)}</span>
        ${f.estado === "rechazada" ? `<button class="btn btn-ghost btn-icon btn-danger" type="button" data-borrar="${esc(String(f.id))}" aria-label="Borrar esta foto del teléfono">${icon("trash")}</button>` : ""}</div>`).join("")}</div>` : ""}
      <div class="opts">${items.length ? `<button class="btn btn-primary btn-lg" type="button" data-act="reintentar">${icon("refresh")}Reintentar ahora</button>` : ""}
        <button class="btn btn-lg" type="button" data-act="cerrar">Cerrar</button></div>`, "cola", refresco);
  }
  function refrescarHoja() { if (Sheet.kind === "cola") colaSheet(true); else if (Sheet.kind === "fin") finSheet(true); }

  const duracion = (a, b) => {
    const m = Math.max(0, Math.round((new Date(b || Date.now()) - new Date(a)) / 60000));
    return m < 1 ? "menos de 1 min" : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
  };
  const horaCorta = (iso) => { try { return new Date(iso).toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit", hour12: false }); } catch (e) { return ""; } };

  function finSheet(refresco) {
    const x = Sesiones.actual();
    if (!x) { ir("inicio"); return; }
    const pend = Sesiones.pendientes(x.id), malas = x.rechazadas || 0;
    const off = !navigator.onLine || S.sinSenal;
    const todo = x.tomadas > 0 && pend === 0 && !malas;
    const fr = x.franjas || {};
    sheet(`<div class="r-fin">
      <div class="r-fin-hero${todo ? " ok" : ""}"><span class="ic">${icon(todo ? "check" : pend ? (off ? "cloud-off" : "upload") : "camera")}</span>
        <div><h2>${x.tomadas ? (todo ? "¡Listo! Todas tus fotos se enviaron" : "Resumen de la toma") : "No tomaste fotos en esta toma"}</h2>
        <p>${esc(x.local.label)} · ${esc(TIPOS[x.tipo].largo)}</p></div></div>
      <div class="r-fin-stats">
        <div><b>${nf(x.tomadas)}</b><span>tomadas</span></div>
        <div class="g"><b>${nf(x.enviadas)}</b><span>enviadas</span></div>
        <div class="${pend ? "w" : ""}"><b>${nf(pend)}</b><span>en cola</span></div>
        ${malas ? `<div class="b"><b>${nf(malas)}</b><span>con problema</span></div>` : ""}
      </div>
      ${x.tipo === "gondola" ? `<div class="r-fin-franjas">${FRANJAS.map((f) => `<span class="${fr[f] ? "ok" : ""}">${fr[f] ? icon("check") : ""}${esc(nombreFranja(f))}${fr[f] > 1 ? ` ×${nf(fr[f])}` : ""}</span>`).join("")}</div>
        ${x.tomadas && fr.completa === undefined ? `<p class="r-fin-note">${icon("alert")}<span>Falta la foto de la <b>góndola completa</b>. Tómala antes de terminar.</span></p>` : ""}` : ""}
      <p class="muted" style="font-size:13.5px">${icon("clock")} ${duracion(x.inicio)} · desde las ${horaCorta(x.inicio)}</p>
      ${pend ? `<p class="r-fin-note">${icon(off ? "cloud-off" : "upload")}<span>${off ? "Sin señal: " : ""}${plural(pend, "foto queda", "fotos quedan")} guardada${pend > 1 ? "s" : ""} en este teléfono y se envía${pend > 1 ? "n" : ""} sola${pend > 1 ? "s" : ""}. <b>No borres los datos del navegador</b> hasta que llegue a 0.</span></p>` : ""}
      ${malas ? `<p class="r-fin-note bad">${icon("alert")}<span>${plural(malas, "foto no se pudo enviar", "fotos no se pudieron enviar")}. Puedes verlas en «Fotos en este teléfono».</span></p>` : ""}
      <div class="opts"><button class="btn btn-primary btn-lg btn-block" type="button" data-act="terminar-ok">${icon("check")}Terminar</button>
        <button class="btn btn-lg btn-block" type="button" data-act="cerrar">Seguir tomando fotos</button></div></div>`, "fin", refresco);
  }
  function terminarSesion() {
    const x = Sesiones.terminar();
    S.sesionId = null; S.sesion = 0; S.tira = [];
    closeSheet();
    ir("inicio");
    if (x && x.tomadas) {
      const pend = Sesiones.pendientes(x.id);
      toast(pend ? `Toma terminada: ${plural(x.tomadas, "foto", "fotos")}, ${nf(pend)} todavía en cola.` : `Toma terminada: ${plural(x.tomadas, "foto enviada", "fotos enviadas")}. ¡Gracias!`, false, 4500);
    }
  }

  function resumenHoyHtml() {
    const ses = Sesiones.hoy().slice().reverse();
    if (!ses.length) return "";
    const t = ses.reduce((a, x) => { a.t += x.tomadas; a.e += x.enviadas; a.p += Sesiones.pendientes(x.id); a.m += x.rechazadas || 0; return a; }, { t: 0, e: 0, p: 0, m: 0 });
    return `<section class="r-hoy" aria-label="Resumen de hoy"><div class="r-hoy-h"><h2>${icon("check")}Tus fotos de hoy</h2>
        <span>${plural(t.t, "foto", "fotos")} · ${nf(t.e)} enviadas${t.p ? ` · <b class="w">${nf(t.p)} en cola</b>` : ""}${t.m ? ` · <b class="b">${nf(t.m)} con problema</b>` : ""}</span></div>
      <ul>${ses.map((x) => { const p = Sesiones.pendientes(x.id); const ok = !p && !(x.rechazadas || 0);
        return `<li><span class="st ${ok ? "ok" : p ? "w" : "b"}">${icon(ok ? "check" : p ? "clock" : "alert")}</span>
          <span class="g"><b>${esc(x.local.label)} · ${esc(TIPOS[x.tipo] ? TIPOS[x.tipo].nombre : "")}</b><small>${horaCorta(x.inicio)}${x.fin ? `–${horaCorta(x.fin)}` : " · en curso"}</small></span>
          <span class="n"><b>${nf(x.tomadas)}</b><small>${ok ? "enviadas" : p ? `${nf(p)} en cola` : `${nf(x.rechazadas)} con problema`}</small></span></li>`; }).join("")}</ul></section>`;
  }
  function pintarResumenHoy() {
    if (S.vista !== "inicio") return;
    const host = $("#rHoy");
    if (host) host.innerHTML = resumenHoyHtml();
  }

  // ─── cámara ──────────────────────────────────────────────────────────────
  function viewCamara() {
    S.vista = "camara";
    const ses = Sesiones.iniciar(S.local, S.tipo);
    if (S.sesionId !== ses.id) { S.sesionId = ses.id; S.sesion = ses.tomadas || 0; S.tira = []; }
    document.body.classList.add("en-camara");
    const prod = S.tipo === "producto";
    $("#app").innerHTML = `<section class="cam" id="cam" aria-label="Cámara">
      <video id="vid" playsinline muted autoplay></video>
      <div class="cam-starting" id="camStart"><div><span class="spinner"></span>Abriendo la cámara…</div></div>
      <div class="cam-fallback" id="camFb" hidden></div>
      ${prod ? `<div class="cam-frame" aria-hidden="true"><i></i><span>Producto + etiqueta de precio</span></div>` : ""}
      <div class="cam-flash" id="flash"></div>
      <div class="cam-top">
        <div class="cam-row">
          <button class="cam-where" type="button" data-act="volver" aria-label="${esc(S.local.label)}, ${esc(TIPOS[S.tipo].largo)}. Volver al inicio"><small>${esc(S.local.label)}</small><b>${esc(TIPOS[S.tipo].largo)}</b></button>
          <button class="cam-pill" type="button" data-act="volver">${icon("left")}Volver</button>
          <button class="cam-pill cam-fin" type="button" data-act="terminar" aria-label="Terminar y ver el resumen">${icon("check")}Terminar</button>
        </div>
        <div class="cam-guide" id="camGuide"></div>
        <button class="cam-status" id="camStatus" type="button" data-act="cola" aria-live="polite"></button>
      </div>
      <div class="cam-msg" id="camMsg" role="status"></div>
      <div class="cam-bottom">
        <div class="cam-zoom" id="camZoom" role="group" aria-label="Zoom"></div>
        <div class="strip" id="tira" aria-label="Fotos de esta toma"></div>
        <div class="cam-ctrl">
          <div class="l"><button class="cam-ic lg" type="button" data-act="galeria" aria-label="Subir fotos desde la galería">${icon("image")}</button></div>
          <button class="shutter${prod ? " prod" : ""}" id="shutter" type="button" aria-label="Tomar foto"><span class="n" id="cuenta"></span></button>
          <div class="r"><button class="cam-ic lg" type="button" id="torchBtn" data-act="linterna" aria-label="Linterna" aria-pressed="false" hidden>${icon("bolt")}</button>
            <button class="cam-ic lg" type="button" data-act="ayuda" aria-label="¿Cómo tomar las fotos?">${icon("help")}</button></div>
        </div>
        <div class="cam-hint" id="camHint" aria-live="polite"></div>
      </div></section>`;
    $("#shutter").addEventListener("click", disparar);
    pintarGuia(); pintarTira(); pintarEstado(); pintarCuenta(); pintarCamEstado();
    abrirCamara();
  }
  function pintarGuia() {
    const g = $("#camGuide");
    if (!g) return;
    const ses = Sesiones.actual(), fr = (ses && ses.franjas) || {};
    if (S.tipo === "gondola") {
      const f = S.franja || "1";
      const titulo = f === "completa" ? "Góndola completa" : `Franja ${f}`;
      const tip = f === "completa" ? "Toda la góndola en una foto, de frente" : f === "1" ? "Empieza por la de arriba · de frente, a 1 metro, sin flash" : "De frente, a 1 metro, sin flash";
      g.innerHTML = `<div class="t"><b>${esc(titulo)}</b><span>${esc(tip)}</span></div>
        <div class="cam-chips" role="group" aria-label="Franja">${FRANJAS.map((x) => `<button type="button" data-franja="${x}" aria-pressed="${x === f}" class="${fr[x] ? "hecha" : ""}">${fr[x] ? icon("check") : ""}${x === "completa" ? "Completa" : x}</button>`).join("")}</div>`;
    } else {
      const f = S.franja || "";
      g.innerHTML = `<div class="t"><b>Producto ${nf((S.sesion || 0) + 1)}</b><span>Una foto por percha · a 30 cm · etiqueta completa</span></div>
        <div class="cam-chips" role="group" aria-label="Franja del producto (opcional)"><span class="lbl">Franja:</span>${["", "1", "2", "3", "4", "5", "6"].map((x) => `<button type="button" data-franja="${x}" aria-pressed="${x === f}">${x || "—"}</button>`).join("")}</div>`;
    }
    const sel = g.querySelector('[aria-pressed="true"]');
    if (sel && sel.scrollIntoView) { try { sel.scrollIntoView({ block: "nearest", inline: "center" }); } catch (e) { /* nada */ } }
  }
  function elegirFranja(f) {
    S.franja = f; Store.set(SK("franja"), f);
    pintarGuia();
  }
  function avanzarFranja() {
    if (S.tipo !== "gondola") { pintarGuia(); return; }       // producto: solo sube el número del producto
    const i = FRANJAS.indexOf(S.franja || "1");
    if (i >= 0 && i < FRANJAS.length - 1) {
      const sig = FRANJAS[i + 1];
      S.franja = sig; Store.set(SK("franja"), sig);
      mensaje(`${nombreFranja(FRANJAS[i])} lista · sigue con ${sig === "completa" ? "la góndola completa" : `la franja ${sig}`}`, true);
    } else mensaje("Góndola completa lista. Toca «Terminar» cuando acabes.", true);
    pintarGuia();
  }
  function salirCamara() {
    if (!document.body.classList.contains("en-camara")) return;
    document.body.classList.remove("en-camara");
    pararCamara();
  }

  async function abrirCamara() {
    const C = S.cam;
    pararCamara();
    C.error = null; C.iniciando = true; C.torch = false; C.zoom = null;
    pintarCamEstado();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { C.error = "sin_api"; C.iniciando = false; pintarCamEstado(); return; }
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: "environment" }, width: { ideal: 4096 }, height: { ideal: 3072 } } });
    } catch (e) {
      if (e && (e.name === "NotAllowedError" || e.name === "SecurityError")) C.error = "permiso";
      else {
        try { stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: "environment" } }); }
        catch (e2) { C.error = e2 && e2.name === "NotAllowedError" ? "permiso" : "error"; }
      }
    }
    if (S.vista !== "camara") { if (stream) stream.getTracks().forEach((t) => t.stop()); return; }
    if (!stream) { C.iniciando = false; pintarCamEstado(); return; }
    C.stream = stream;
    C.track = stream.getVideoTracks()[0];
    await mejorarResolucion(C.track);
    const v = $("#vid");
    if (v) { v.srcObject = stream; try { await v.play(); } catch (e) { /* autoplay: el video está silenciado */ } }
    C.caps = (C.track.getCapabilities && C.track.getCapabilities()) || {};
    C.ic = null; C.foto = null;
    if ("ImageCapture" in window) {
      try {
        C.ic = new ImageCapture(C.track);
        const pc = await Promise.race([C.ic.getPhotoCapabilities(), sleep(2500).then(() => null)]);
        if (pc && pc.imageWidth && pc.imageWidth.max && pc.imageHeight && pc.imageHeight.max) {
          C.foto = { imageWidth: pc.imageWidth.max, imageHeight: pc.imageHeight.max };
          if ((pc.fillLightMode || []).indexOf("off") >= 0) C.foto.fillLightMode = "off";
        }
      } catch (e) { C.ic = null; }
    }
    C.iniciando = false;
    pintarCamEstado(); pintarZoom(); pedirWakeLock();
  }
  async function mejorarResolucion(t) {
    if (!t || !t.getSettings || !t.applyConstraints) return;
    const a = t.getSettings(), area = (s) => (s.width || 0) * (s.height || 0);
    if (Math.max(a.width || 0, a.height || 0) >= 2560) return;
    try { await t.applyConstraints({ width: { ideal: 3840 }, height: { ideal: 2160 } }); } catch (e) { return; }
    if (area(t.getSettings()) < area(a)) { try { await t.applyConstraints({ width: { ideal: a.width }, height: { ideal: a.height } }); } catch (e) { /* queda como esté */ } }
  }
  function pararCamara() {
    const C = S.cam;
    if (C.stream) C.stream.getTracks().forEach((t) => t.stop());
    C.stream = null; C.track = null; C.ic = null;
    if (C.lock) { try { C.lock.release(); } catch (e) { /* nada */ } C.lock = null; }
    const v = $("#vid");
    if (v) v.srcObject = null;
  }
  async function pedirWakeLock() {
    try { if ("wakeLock" in navigator && !S.cam.lock) S.cam.lock = await navigator.wakeLock.request("screen"); } catch (e) { /* sin bloqueo de pantalla */ }
  }
  function pintarCamEstado() {
    const C = S.cam, st = $("#camStart"), fb = $("#camFb");
    if (!st || !fb) return;
    st.hidden = !C.iniciando;
    if (C.error) {
      const txt = { permiso: "El navegador no tiene permiso para usar la cámara. Puedes dárselo en el candado de la barra de direcciones, o usar la cámara del teléfono:",
        sin_api: EN_APP ? "Dentro de WhatsApp la cámara no funciona en la página. Ábrelo en Safari o Chrome, o usa la cámara del teléfono:" : "Este navegador no deja usar la cámara dentro de la página. Usa la cámara del teléfono:",
        error: "La cámara no respondió (puede que otra app la esté usando). Usa la cámara del teléfono:" }[C.error];
      fb.hidden = false;
      fb.innerHTML = `<div class="fb-card"><span class="ic">${icon("camera-off")}</span><h2>No pudimos abrir la cámara aquí</h2><p>${txt}</p>
        <button class="btn btn-primary btn-lg" type="button" data-act="camara-telefono">${icon("camera")}Abrir cámara del teléfono</button>
        <button class="btn btn-lg" type="button" data-act="galeria">${icon("image")}Subir desde la galería</button>
        <button class="btn btn-link" type="button" data-act="reintentar-camara">${icon("refresh")}Intentar otra vez con la cámara aquí</button></div>`;
    } else { fb.hidden = true; fb.innerHTML = ""; }
    const sh = $("#shutter");
    if (sh) sh.setAttribute("aria-label", C.error ? "Abrir la cámara del teléfono" : "Tomar foto");
    const tb = $("#torchBtn");
    if (tb) { tb.hidden = !(C.caps && C.caps.torch) || !!C.error; tb.setAttribute("aria-pressed", String(!!C.torch)); }
    pintarHint();
  }
  function pintarZoom() {
    const host = $("#camZoom");
    if (!host) return;
    const z = S.cam.caps && S.cam.caps.zoom;
    if (!z || !(z.max > z.min) || S.cam.error) { host.innerHTML = ""; return; }
    let vals = [1, 2, 3].filter((x) => x >= z.min - 1e-6 && x <= z.max + 1e-6);
    if (z.min < 1) vals.unshift(Math.round(z.min * 10) / 10);
    if (vals.length < 2) { host.innerHTML = ""; return; }
    const cur = S.cam.zoom || (S.cam.track && S.cam.track.getSettings && S.cam.track.getSettings().zoom) || vals[0];
    host.innerHTML = vals.map((x) => `<button type="button" data-act="zoom" data-z="${x}" aria-pressed="${Math.abs(x - cur) < 0.05}">${nf(x, x % 1 ? 1 : 0)}×</button>`).join("");
  }
  async function aplicarZoom(x) {
    const t = S.cam.track;
    if (!t) return;
    try { await t.applyConstraints({ advanced: [{ zoom: x }] }); S.cam.zoom = x; } catch (e) { /* sin zoom */ }
    pintarZoom();
  }
  async function aplicarLinterna(on) {
    const t = S.cam.track;
    if (!t) return;
    try { await t.applyConstraints({ advanced: [{ torch: !!on }] }); S.cam.torch = !!on; } catch (e) { S.cam.torch = false; }
    const tb = $("#torchBtn");
    if (tb) tb.setAttribute("aria-pressed", String(S.cam.torch));
  }
  function pintarCuenta() {
    const n = $("#cuenta");
    if (n) { n.textContent = S.sesion ? nf(S.sesion) : ""; n.setAttribute("data-n", String(S.sesion)); }
    pintarHint();
  }
  function pintarHint() {
    const h = $("#camHint");
    if (!h) return;
    if (S.cam.error) { h.textContent = "El botón grande abre la cámara del teléfono."; return; }
    const g = S.procesando ? ` · guardando ${nf(S.procesando)}…` : "";
    h.innerHTML = S.sesion ? `<b>${plural(S.sesion, "foto", "fotos")}</b> en esta toma${g}` : S.tipo === "producto" ? "Encuadra el producto y su etiqueta dentro del marco." : "Toca el botón para tomar la foto de la franja.";
  }
  function destello() {
    const f = $("#flash");
    if (f) { f.classList.remove("on"); void f.offsetWidth; f.classList.add("on"); }
    const s = $("#shutter");
    if (s) { s.classList.add("tap"); setTimeout(() => s.classList.remove("tap"), 120); }
    try { if (navigator.vibrate) navigator.vibrate(25); } catch (e) { /* sin vibración */ }
  }
  function mensaje(t, bueno) {
    const el = $("#camMsg");
    if (!el) { toast(esc(t)); return; }
    el.className = "cam-msg on" + (bueno ? " good" : "");
    el.innerHTML = `${icon(bueno ? "check" : "alert")}<span>${esc(t)}</span>`;
    clearTimeout(mensaje.t); mensaje.t = setTimeout(() => el.classList.remove("on"), 2600);
  }
  function aviso(m) {
    if (!m || Date.now() - S.avisoT < 3000) return;
    let t = null;
    if (m.lum < LUM_MIN) t = "Salió oscura: busca más luz" + (S.cam.caps && S.cam.caps.torch && !S.cam.torch ? " o enciende la linterna" : "");
    else if (m.lum > LUM_MAX) t = "Salió con mucho reflejo: cambia un poco el ángulo";
    else if (m.sharp < SHARP_MIN) t = "Salió movida: afirma el teléfono un segundo y repítela";
    if (!t) return;
    S.avisoT = Date.now();
    mensaje(t, false);
  }

  // ─── imágenes ────────────────────────────────────────────────────────────
  function lienzo(w, h) { const c = document.createElement("canvas"); c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h)); return c; }
  function liberar(c) { if (c) { c.width = 0; c.height = 0; } }
  function cuadro(v, lado) {
    const w = v.videoWidth, h = v.videoHeight;
    const k = Math.min(1, (lado || MAX_LADO) / Math.max(w, h));
    const c = lienzo(w * k, h * k);
    c.getContext("2d", { alpha: false }).drawImage(v, 0, 0, c.width, c.height);
    return c;
  }
  const aBlob = (c, q) => new Promise((res, rej) => { try { c.toBlob((b) => (b ? res(b) : rej(new Error("No se pudo comprimir la foto"))), "image/jpeg", q); } catch (e) { rej(e); } });
  function cargarImg(url) { return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("no se pudo leer")); i.src = url; }); }
  async function copiaChica(blob, lado) {
    let src = null, w = 0, h = 0;
    if (window.createImageBitmap) {
      try { src = await createImageBitmap(blob, { resizeWidth: lado, resizeQuality: "medium" }); } catch (e) { src = null; }
      if (!src) { try { src = await createImageBitmap(blob); } catch (e) { src = null; } }
    }
    let url = null;
    if (!src) { url = URL.createObjectURL(blob); try { src = await cargarImg(url); } catch (e) { URL.revokeObjectURL(url); return null; } }
    w = src.width || src.naturalWidth; h = src.height || src.naturalHeight;
    const k = Math.min(1, lado / Math.max(w, h, 1));
    const c = lienzo(w * k, h * k);
    c.getContext("2d", { alpha: false }).drawImage(src, 0, 0, c.width, c.height);
    if (src.close) src.close();
    if (url) URL.revokeObjectURL(url);
    return c;
  }
  async function decodificar(blob) {
    if (window.createImageBitmap) { try { return await createImageBitmap(blob); } catch (e) { /* abajo */ } }
    const url = URL.createObjectURL(blob);
    try { return await cargarImg(url); } finally { setTimeout(() => URL.revokeObjectURL(url), 0); }
  }
  function dibujar(src, giro, lado) {
    const w = src.width || src.naturalWidth, h = src.height || src.naturalHeight;
    const k = Math.min(1, lado / Math.max(w, h));
    const dw = Math.round(w * k), dh = Math.round(h * k);
    const c = giro ? lienzo(dh, dw) : lienzo(dw, dh);
    const x = c.getContext("2d", { alpha: false });
    x.imageSmoothingEnabled = true; x.imageSmoothingQuality = "high";
    if (giro) { x.translate(c.width / 2, c.height / 2); x.rotate((giro * Math.PI) / 180); x.drawImage(src, -dw / 2, -dh / 2, dw, dh); }
    else x.drawImage(src, 0, 0, dw, dh);
    return c;
  }
  function huella(c, n) {
    const t = lienzo(n, n), x = t.getContext("2d", { willReadFrequently: true });
    x.drawImage(c, 0, 0, n, n);
    const d = x.getImageData(0, 0, n, n).data, out = new Float32Array(n * n);
    for (let i = 0, j = 0; i < d.length; i += 4, j++) out[j] = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    return out;
  }
  function giroNecesario(peq, ref) {
    if (!ref || Math.abs(peq.width - peq.height) < 4 || (peq.height > peq.width) === (ref.height > ref.width)) return 0;
    const r = huella(ref, 24);
    const dif = (g) => { const c = dibujar(peq, g, 64), hh = huella(c, 24); liberar(c); let s = 0; for (let i = 0; i < r.length; i++) s += Math.abs(r[i] - hh[i]); return s; };
    return dif(90) <= dif(-90) ? 90 : -90;
  }
  function medir(c) {
    const W = 256, H = Math.max(8, Math.round((c.height * W) / c.width));
    const t = lienzo(W, H), x = t.getContext("2d", { willReadFrequently: true });
    x.drawImage(c, 0, 0, W, H);
    const d = x.getImageData(0, 0, W, H).data, g = new Float32Array(W * H);
    let sum = 0;
    for (let i = 0, j = 0; i < d.length; i += 4, j++) { const y = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]; g[j] = y; sum += y; }
    let ls = 0, ls2 = 0, n = 0;
    for (let y = 1; y < H - 1; y++) for (let xx = 1; xx < W - 1; xx++) {
      const i = y * W + xx, v = 4 * g[i] - g[i - 1] - g[i + 1] - g[i - W] - g[i + W];
      ls += v; ls2 += v * v; n++;
    }
    liberar(t);
    const lm = ls / n;
    return { sharp: ls2 / n - lm * lm, lum: sum / (W * H) };
  }
  function miniatura(c) {
    if (!c) return null;
    const k = Math.min(1, 160 / Math.max(c.width, c.height));
    const t = lienzo(c.width * k, c.height * k);
    t.getContext("2d", { alpha: false }).drawImage(c, 0, 0, t.width, t.height);
    const url = t.toDataURL("image/jpeg", 0.7);
    liberar(t);
    return url;
  }
  async function preparar(blob, ref) {
    const peq = await copiaChica(blob, 256);
    if (!peq) return { blob, w: 0, h: 0, peq: null };
    const giro = giroNecesario(peq, ref);
    if (!giro && blob.size <= PESO_REDUCIR) return { blob, w: 0, h: 0, peq };
    const full = await decodificar(blob);
    const w = full.width || full.naturalWidth, h = full.height || full.naturalHeight;
    if (!giro && Math.max(w, h) <= LADO_REDUCIR && blob.size <= MAX_BYTES) { if (full.close) full.close(); return { blob, w, h, peq }; }
    const c = dibujar(full, giro, MAX_LADO);
    if (full.close) full.close();
    const out = await aBlob(c, JPEG_Q);
    const r = { blob: out, w: c.width, h: c.height, peq: giro ? dibujar(peq, giro, 256) : peq };
    liberar(c);
    if (giro) liberar(peq);
    return r;
  }

  // ─── disparo y archivos: todo en segundo plano, en orden ─────────────────
  const Proc = { p: Promise.resolve() };
  function enSegundoPlano(fn) {
    S.procesando++; pintarHint();
    Proc.p = Proc.p.then(fn).catch((e) => toast(`No se pudo guardar una foto: ${esc(e && e.message ? e.message : "error")}`, true))
      .then(() => { S.procesando--; pintarHint(); });
  }
  async function tomarFoto() {
    const C = S.cam;
    C.ocupado = true;
    try {
      let b = null;
      try { b = await C.ic.takePhoto(C.foto || undefined); }
      catch (e) { if (!C.foto) throw e; C.foto = null; b = await C.ic.takePhoto(); }
      return b && b.size ? b : null;
    } catch (e) {
      C.ic = null;
      return null;
    } finally {
      C.ocupado = false;
      if (C.torch) aplicarLinterna(true);
    }
  }
  function contexto() {
    return { local: Object.assign({}, S.local), tipo: S.tipo, franja: S.tipo === "gondola" ? S.franja || "1" : S.franja || "", sesion: Sesiones.actualId() };
  }
  function disparar() {
    const C = S.cam, v = $("#vid");
    if (C.error || !C.track || C.track.readyState !== "live") { if (C.error) abrirArchivo("cam"); return; }
    if (!v || !v.videoWidth) return;
    destello();
    const ctx = contexto(), tomada = new Date().toISOString();
    S.sesion++; Sesiones.sumar(ctx.sesion, "tomadas", ctx.franja); pintarCuenta();
    const ref = cuadro(v, 192);
    const item = agregarATira(miniatura(ref), ctx.franja);
    const conFoto = !!(C.ic && !C.ocupado);
    const captura = conFoto ? tomarFoto() : null;
    let completo = conFoto ? null : cuadro(v, 0);
    avanzarFranja();
    enSegundoPlano(async () => {
      let r = null, origen = "foto";
      if (captura) { const b = await captura; if (b) r = await preparar(b, ref); }
      if (!r) {
        if (!completo) { const vv = $("#vid"); completo = vv && vv.videoWidth ? cuadro(vv, 0) : null; }
        if (!completo) throw new Error("la cámara se cerró");
        origen = "video";
        r = { blob: await aBlob(completo, JPEG_Q), w: completo.width, h: completo.height, peq: ref };
        liberar(completo);
      }
      aviso(medir(r.peq || ref));
      await encolar(r, Object.assign(ctx, { tomada, origen, thumb: item.src, item }));
      if (r.peq && r.peq !== ref) liberar(r.peq);
      liberar(ref);
    });
  }
  function abrirArchivo(via) {
    const inp = via === "gal" ? $("#galInput") : $("#camInput");
    inp.value = "";
    inp.click();
  }
  const esFoto = (f) => /^image\//.test(f.type || "") || /\.(jpe?g|png|webp|heic|heif)$/i.test(f.name || "");
  function recibirArchivos(files, via) {
    const lista = Array.from(files || []);
    if (!lista.length || !S.local || !S.tipo) return;
    lista.forEach((file) => {
      if (!esFoto(file)) { toast(`«${esc(file.name)}» no es una foto.`, true); return; }
      const ctx = contexto();
      S.sesion++; Sesiones.sumar(ctx.sesion, "tomadas", ctx.franja); pintarCuenta();
      const tomada = new Date(file.lastModified || Date.now()).toISOString();
      if (lista.length === 1 && via === "cam") avanzarFranja(); else if (S.tipo === "producto") pintarGuia();
      enSegundoPlano(async () => {
        let r;
        try { r = await preparar(file, null); } catch (e) { r = { blob: file, w: 0, h: 0, peq: null }; }
        if (r.blob.size > MAX_BYTES) { toast(`«${esc(file.name)}» pesa más de 25 MB y no se pudo reducir en este teléfono.`, true, 5000); return; }
        const thumb = miniatura(r.peq);
        const item = agregarATira(thumb, ctx.franja);
        if (r.peq) aviso(medir(r.peq));
        await encolar(r, Object.assign(ctx, { tomada, origen: via === "gal" ? "galeria" : "camara_telefono", thumb, item }));
        liberar(r.peq);
      });
    });
    if (lista.length > 1) toast(`${plural(lista.length, "foto agregada", "fotos agregadas")} a la cola${S.tipo === "gondola" ? ` como ${nombreFranja(S.franja)}` : ""}.`);
  }
  async function encolar(r, o) {
    const meta = { token: TOKEN, local: o.local, tipo: o.tipo, franja: o.franja, cid: nuevoId(), tomada_en: o.tomada, w: r.w || 0, h: r.h || 0,
      bytes: r.blob.size, mime: r.blob.type || "", origen: o.origen, estado: "cola", intentos: 0, next_at: 0, error: null,
      thumb: o.thumb || null, creado: new Date().toISOString(), sesion: o.sesion || null };
    meta.id = await DB.agregar(meta, r.blob);
    S.cola.push(meta);
    if (o.item) { o.item.id = meta.id; pintarTira(); }
    pedirPersistencia();
    Envio.kick();
  }
  let persistenciaPedida = false;
  function pedirPersistencia() {
    if (persistenciaPedida) return;
    persistenciaPedida = true;
    try { if (navigator.storage && navigator.storage.persist) navigator.storage.persist(); } catch (e) { /* el navegador decide */ }
  }

  let tiraSeq = 0;
  function agregarATira(src, franja) {
    const item = { key: ++tiraSeq, src, id: null, estado: "cola", nuevo: true, franja: S.tipo === "gondola" ? franja : "" };
    S.tira.unshift(item);
    if (S.tira.length > TIRA_MAX) S.tira.length = TIRA_MAX;
    pintarTira();
    return item;
  }
  function marcarTira(id, estado) { const it = S.tira.find((x) => x.id === id); if (it) { it.estado = estado; pintarTira(); } }
  function pintarTira() {
    const host = $("#tira");
    if (!host) return;
    if (!S.tira.length) { host.innerHTML = `<span class="strip-empty">${S.cola.length ? `${plural(S.cola.length, "foto guardada", "fotos guardadas")} en el teléfono` : "Tus fotos aparecen aquí"}</span>`; return; }
    host.innerHTML = S.tira.map((t) => `<span class="th${t.estado === "ok" ? " ok" : t.estado === "bad" ? " bad" : ""}${t.nuevo ? " new" : ""}">${t.src ? `<img src="${t.src}" alt="">` : ""}
      ${t.franja ? `<span class="f">${t.franja === "completa" ? "C" : esc(t.franja)}</span>` : ""}<span class="d">${icon(t.estado === "ok" ? "check" : t.estado === "bad" ? "x" : "clock")}</span></span>`).join("");
    S.tira.forEach((t) => { t.nuevo = false; });
  }

  // ─── envío: de a PARALELO, con reintentos; se borra del teléfono solo con 200 ──
  const Envio = {
    kick() {
      clearTimeout(S.timer);
      if (S.inactivo || !TOKEN) { pintarEstado(); return; }
      const ahora = Date.now();
      if (navigator.onLine) {
        const listas = S.cola.filter((f) => f.estado === "cola" && !f.enviando && (f.next_at || 0) <= ahora);
        while (S.activos < PARALELO && listas.length) this.enviar(listas.shift());
      }
      const esperas = S.cola.filter((f) => f.estado === "cola" && !f.enviando && (f.next_at || 0) > ahora).map((f) => f.next_at);
      if (esperas.length) S.timer = setTimeout(() => Envio.kick(), Math.max(500, Math.min.apply(null, esperas) - ahora));
      pintarEstado();
    },
    async enviar(f) {
      f.enviando = true; S.activos++;
      pintarEstado();
      let res = null, data = null;
      try {
        const blob = await DB.blob(f.id);
        if (!blob) {
          f.enviando = false; S.activos--;
          await DB.quitar(f.id); S.cola = S.cola.filter((x) => x !== f);
          this.kick();
          return;
        }
        const fd = new FormData();
        fd.append("foto", blob, `foto-${f.cid || f.id}.${/png/.test(blob.type) ? "png" : /webp/.test(blob.type) ? "webp" : /hei[cf]/.test(blob.type) ? "heic" : "jpg"}`);
        fd.append("franja", f.franja || "");
        fd.append("tipo", f.tipo || "gondola");
        fd.append("local", (f.local && f.local.store_id) || "");
        fd.append("cliente_id", f.cid || "");
        fd.append("tomada_en", f.tomada_en || "");
        fd.append("origen", f.origen || "");
        const ctl = window.AbortController ? new AbortController() : null;
        const t = ctl ? setTimeout(() => ctl.abort(), 240000) : null;
        try { res = await fetch(API + "/foto", { method: "POST", body: fd, credentials: "omit", signal: ctl ? ctl.signal : undefined }); }
        finally { if (t) clearTimeout(t); }
        try { data = await res.json(); } catch (e) { data = null; }
      } catch (e) { res = null; }
      f.enviando = false; S.activos--;
      const st = res ? res.status : 0;
      if (st === 200 || st === 201) {
        try { await DB.quitar(f.id); } catch (e) { /* el próximo envío vuelve como duplicada y se borra */ }
        S.cola = S.cola.filter((x) => x !== f);
        f.thumb = null;
        S.sinSenal = false;
        Enviadas.sumar();
        Sesiones.sumar(f.sesion, "enviadas");
        marcarTira(f.id, "ok");
        if (data && S.info && f.local) {                  // contador de hoy en la portada, sin volver a pedir el estado
          const h = (S.info.hoy_por_local = S.info.hoy_por_local || {});
          const x = (h[f.local.store_id] = h[f.local.store_id] || { gondola: 0, producto: 0 });
          if (!data.duplicada) x[f.tipo || "gondola"] = (x[f.tipo || "gondola"] || 0) + 1;
          Store.set(SK("estado"), S.info);
        }
      } else if (st === 404) {
        S.inactivo = true;
        render();
        return;
      } else if (st === 400 || st === 413 || st === 415) {
        f.estado = "rechazada";
        Sesiones.sumar(f.sesion, "rechazadas");
        f.error = (data && typeof data.detail === "string" && data.detail) || `Error ${st}`;
        await DB.actualizar(f);
        marcarTira(f.id, "bad");
        toast(`Una foto no se pudo enviar: ${esc(f.error)}`, true, 5000);
      } else {
        f.intentos = (f.intentos || 0) + 1;
        const ra = res && parseInt(res.headers.get("Retry-After") || "", 10);
        f.next_at = Date.now() + (ra > 0 ? Math.min(ra, 600) * 1000 : espera(f.intentos));
        f.error = (data && typeof data.detail === "string" && data.detail) || (st ? `Error ${st}` : "Sin conexión");
        if (!st) S.sinSenal = true;
        if (st === 429 && f.intentos === 1) toast(esc(f.error), true, 5000);
        await DB.actualizar(f);
      }
      refrescarHoja();
      pintarResumenHoy();
      this.kick();
    },
    reintentar() {
      S.cola.forEach((f) => { if (f.estado === "rechazada") { f.estado = "cola"; f.error = null; } f.next_at = 0; DB.actualizar(f); });
      S.sinSenal = false;
      this.kick();
    },
  };

  function pintarEstado() {
    const enCola = S.cola.filter((f) => f.estado !== "rechazada").length, malas = S.cola.length - enCola;
    const off = !navigator.onLine || S.sinSenal;
    const b = $("#camStatus");
    if (b) {
      b.className = "cam-status" + (malas ? " bad" : off ? " off" : "");
      const ic = off ? icon("cloud-off") : malas ? icon("alert") : S.activos ? '<span class="spinner"></span>' : '<span class="dot"></span>';
      b.innerHTML = `${ic}<span>Enviadas ${nf(Enviadas.get())}</span><span class="sep">·</span><span>En cola ${nf(enCola)}</span>`
        + (off ? `<span class="sep">·</span><span>Sin señal</span>` : "") + (malas ? `<span class="sep">·</span><span>${nf(malas)} con problema</span>` : "");
      b.setAttribute("aria-label", `Enviadas ${Enviadas.get()}, en cola ${enCola}${off ? ", sin señal" : ""}${malas ? `, ${malas} con problema` : ""}. Ver fotos en el teléfono`);
    }
    if (S.vista === "inicio") {
      const host = $("#rEstado"), html = estadoLinea();
      if (host) { if (html) host.outerHTML = html; else host.remove(); }
      else if (html) { const h = $("#rHoy"); if (h) h.insertAdjacentHTML("beforebegin", html); }
    }
    if (S.vista === "camara" && !S.tira.length) pintarTira();
  }

  // ─── eventos ─────────────────────────────────────────────────────────────
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.id === "sheetBg") { closeSheet(); return; }
    const loc = t.closest("[data-local]");
    if (loc) { elegirLocal(loc.getAttribute("data-local")); return; }
    const tip = t.closest("[data-tipo]");
    if (tip) { elegirTipo(tip.getAttribute("data-tipo")); return; }
    const fr = t.closest("[data-franja]");
    if (fr) { elegirFranja(fr.getAttribute("data-franja")); return; }
    const del = t.closest("[data-borrar]");
    if (del) {
      const f = S.cola.find((x) => String(x.id) === del.getAttribute("data-borrar"));
      if (f && confirm("¿Borrar esta foto del teléfono? No se va a enviar.")) { await DB.quitar(f.id); S.cola = S.cola.filter((x) => x !== f); marcarTira(f.id, "bad"); colaSheet(); pintarEstado(); }
      return;
    }
    const a = t.closest("[data-act]");
    if (!a) return;
    const act = a.getAttribute("data-act");
    if (act === "ayuda") bienvenida();
    else if (act === "entendido") { Store.set("bienvenida", 1); closeSheet(); }
    else if (act === "cerrar") closeSheet();
    else if (act === "tema") Theme.toggle();
    else if (act === "volver") ir("inicio");
    else if (act === "cambiar-local") { S.local = null; Store.set(SK("local"), null); render(); }
    else if (act === "terminar") finSheet();
    else if (act === "terminar-ok") terminarSesion();
    else if (act === "cola") colaSheet();
    else if (act === "reintentar") { closeSheet(); Envio.reintentar(); }
    else if (act === "galeria") abrirArchivo("gal");
    else if (act === "camara-telefono") abrirArchivo("cam");
    else if (act === "reintentar-camara") abrirCamara();
    else if (act === "linterna") aplicarLinterna(!S.cam.torch);
    else if (act === "zoom") aplicarZoom(parseFloat(a.getAttribute("data-z")));
    else if (act === "copiar") {
      try { await navigator.clipboard.writeText(location.href); toast("Enlace copiado. Pégalo en Safari o Chrome."); }
      catch (err) { prompt("Copia este enlace y ábrelo en Safari o Chrome:", location.href); }
    }
  });
  document.addEventListener("submit", (e) => {
    if (e.target && e.target.id === "otroLocal") { e.preventDefault(); otroLocal(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && Sheet.kind) { if (Sheet.kind === "ayuda") Store.set("bienvenida", 1); closeSheet(); }
    else if ((e.key === " " || e.key === "Enter") && S.vista === "camara" && !Sheet.kind && e.target === document.body) { e.preventDefault(); disparar(); }
  });
  $("#camInput").addEventListener("change", (e) => { recibirArchivos(e.target.files, "cam"); if (e.target.files && e.target.files.length) toast("Foto guardada. Toca de nuevo para la siguiente."); });
  $("#galInput").addEventListener("change", (e) => recibirArchivos(e.target.files, "gal"));
  window.addEventListener("online", () => { S.sinSenal = false; S.cola.forEach((f) => { f.next_at = 0; }); Envio.kick(); });
  window.addEventListener("offline", () => { pintarEstado(); });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { if (S.vista === "camara") pararCamara(); return; }
    if (S.vista === "camara" && !S.cam.stream) abrirCamara();
    Envio.kick();
  });

  function registrarSW() {
    if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
    navigator.serviceWorker.register("/captura/sw.js", { scope: "/captura/" })
      .then(() => navigator.serviceWorker.ready)
      .then((reg) => { if (reg.active) reg.active.postMessage({ tipo: "guardar", url: location.pathname }); })
      .catch(() => { /* sin modo sin conexión */ });
  }

  async function boot() {
    try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => Theme.paint()); } catch (e) { /* navegador antiguo */ }
    S.cola = (await DB.todas()).map((f) => Object.assign(f, { enviando: false })).sort((a, b) => String(a.creado).localeCompare(String(b.creado)));
    ajustarLocal();
    // toma en curso hoy (p. ej. la página se recargó al volver de la cámara): directo a la cámara
    const cur = Sesiones.actual();
    const seguir = cur && !cur.fin && cur.dia === hoy() && S.local && cur.local && cur.local.store_id === S.local.store_id && S.tipo === cur.tipo;
    S.vista = seguir ? "camara" : "inicio";
    history.replaceState({ v: "inicio" }, "");
    if (S.vista === "camara") history.pushState({ v: "camara" }, "");
    render();
    await cargarEstado();
    if (S.inactivo || S.vista === "inicio") render();
    if (!Store.get("bienvenida") && !S.inactivo && S.vista === "inicio") bienvenida();   // después del último render (render cierra hojas)
    registrarSW();
    Envio.kick();
    setInterval(() => { if (S.cola.length && !S.activos) Envio.kick(); }, 30000);
  }
  boot();
})();
