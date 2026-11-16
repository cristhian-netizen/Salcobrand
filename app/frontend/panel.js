/* Panel de supervisión NeuraVision (Salcobrand). Vanilla JS, sin build.
   Rutas por hash: #/resumen · #/gondola/<punto>?r=<lectura> · #/tendencias/<punto> · #/catalogo/<planograma>?point=<punto> · #/revision
   Datos: /api/summary, /api/points/{id}, /api/points/{id}/trends, /api/catalog/{planograma}, /api/review/pending,
          /api/readings/{id}/review, POST /api/readings/{id}/confirm, POST /api/points/{id}/stock-actions. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const enc = encodeURIComponent;
  const view = $("#view");
  const THEME_KEY = "nv-panel-theme";

  const state = { user: null, summary: null, summaryDays: null, planograms: null, renderToken: 0, reviewCount: null };

  // ───────────────────────────────────────────────────────────────── API
  class ApiError extends Error {
    constructor(status, detail) { super(detail); this.status = status; }
  }

  async function api(path, opts = {}) {
    const init = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
    if (opts.json !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.json); }
    if (opts.body) init.body = opts.body;
    const res = await fetch(path, init);
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (res.status === 401) { showLogin(); throw new ApiError(401, "Sesión no iniciada o expirada"); }
    if (!res.ok) throw new ApiError(res.status, (data && data.detail) || `Error ${res.status}`);
    return data;
  }

  async function getSummary(days = 7, force = false) {
    if (!force && state.summary && state.summaryDays === days) return state.summary;
    state.summary = await api(`/api/summary?days=${days}`);
    state.summaryDays = days;
    return state.summary;
  }

  async function getPlanograms(force = false) {
    if (!force && state.planograms) return state.planograms;
    state.planograms = await api("/api/planograms");
    return state.planograms;
  }

  // ───────────────────────────────────────────────────────────────── formato
  const nf0 = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat("es-CL", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const fmtInt = (v) => (v == null || Number.isNaN(Number(v)) ? "—" : nf0.format(Number(v)));
  const fmtPct = (v) => (v == null || Number.isNaN(Number(v)) ? "—" : `${nf1.format(Number(v))} %`);
  const fmtCLP = (v) => (v == null || Number.isNaN(Number(v)) ? "—" : `$ ${nf0.format(Math.round(Number(v)))}`);
  const fmtDate = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("es-CL", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  };
  const fmtDay = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("es-CL", { day: "numeric", month: "short" });
  };
  const fmtAgo = (iso) => {
    if (!iso) return "sin lectura";
    const ms = Date.now() - new Date(iso).getTime();
    if (Number.isNaN(ms)) return "";
    const min = Math.round(ms / 60000);
    if (min < 1) return "ahora";
    if (min < 60) return `hace ${min} min`;
    const h = Math.round(min / 60);
    if (h < 24) return `hace ${h} h`;
    const d = Math.round(h / 24);
    if (d === 1) return "ayer";
    if (d < 30) return `hace ${d} días`;
    const m = Math.round(d / 30);
    return `hace ${m} ${m === 1 ? "mes" : "meses"}`;
  };
  const pctKind = (v) => (v == null ? "none" : v >= 90 ? "good" : v >= 70 ? "warn" : "bad");
  const STATUS = {
    ok: ["completo", "good"], low: ["caras bajas", "warn"], missing: ["quiebre", "bad"], foreign: ["ajeno", "neutral"],
  };
  const statusTag = (st, extra = "") => {
    const [label, kind] = STATUS[st] || [st || "—", "neutral"];
    return `<span class="tag tag-${kind} ${extra}">${esc(label)}</span>`;
  };
  const FLAG_KIND = { quiebre: "bad", baja: "warn", bajo: "warn", sube: "info", estable: "good", none: "neutral" };
  const FLAG_ORDER = { quiebre: 0, baja: 1, bajo: 2, sube: 3, estable: 4, none: 5 };
  const flagTag = (s) => `<span class="tag tag-${FLAG_KIND[s.flag_kind] || "neutral"}">${esc(s.flag)}</span>`;
  const tagTop = (tag) => (tag ? ` <span class="tagtop">${esc(tag)}</span>` : "");

  function meter(pct, { wide = false, label = null } = {}) {
    const kind = pctKind(pct);
    const w = pct == null ? 0 : Math.max(0, Math.min(100, pct));
    return `<span class="meter ${kind} ${wide ? "wide" : ""}"><span class="bar"><i style="width:${w}%"></i></span><span class="v">${label ?? fmtPct(pct)}</span></span>`;
  }

  /* Minigráfico de una serie (null = sin dato: la línea se corta). Último punto en el acento; `current` marca una lectura. */
  function sparkline(values, { w = 120, h = 32, max = null, min = 0, current = -1, labels = null, unit = "" } = {}) {
    const known = values.map((v, i) => [i, v]).filter(([, v]) => v != null && !Number.isNaN(Number(v)));
    if (!known.length) return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true"></svg>`;
    const vmax = Math.max(max ?? -Infinity, ...known.map((p) => Number(p[1])), min + 1);
    const n = values.length;
    const padX = 4, padY = 4;
    const x = (i) => (n > 1 ? padX + (i * (w - 2 * padX)) / (n - 1) : w / 2);
    const y = (v) => h - padY - ((Number(v) - min) / (vmax - min)) * (h - 2 * padY);
    const segs = [];
    let cur = [];
    values.forEach((v, i) => {
      if (v == null) { if (cur.length) segs.push(cur); cur = []; return; }
      cur.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    });
    if (cur.length) segs.push(cur);
    const paths = segs.map((s) => `<polyline class="ln" points="${s.join(" ")}"/>`).join("");
    const lastIdx = known[known.length - 1][0];
    const pts = known.map(([i, v]) => {
      const cls = i === current ? "pt cur" : i === lastIdx ? "pt last" : "pt";
      const r = i === current || i === lastIdx ? 3.5 : 2.5;
      const title = `${labels && labels[i] ? labels[i] + ": " : ""}${Number.isInteger(Number(v)) ? fmtInt(v) : nf1.format(Number(v))}${unit}`;
      return `<circle class="${cls}" cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="${r}"><title>${esc(title)}</title></circle>`;
    }).join("");
    const grid = max != null ? `<line class="gl" x1="${padX}" x2="${w - padX}" y1="${y(max).toFixed(1)}" y2="${y(max).toFixed(1)}"/>` : "";
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" role="img" aria-label="Serie de ${known.length} valores">${grid}${paths}${pts}</svg>`;
  }

  function kpi({ label, value, sub = "", kind = "", href = null, scrollTo = null, spark = "" }) {
    const inner = `<div class="kpi-l">${esc(label)}</div><div class="kpi-v ${kind}">${value}</div>${sub ? `<div class="kpi-s">${sub}</div>` : ""}${spark}`;
    if (href) return `<a class="kpi" href="${esc(href)}">${inner}</a>`;
    if (scrollTo) return `<button type="button" class="kpi kpi-btn" data-action="scroll-to" data-target="${esc(scrollTo)}">${inner}</button>`;
    return `<div class="kpi">${inner}</div>`;
  }

  const loading = (msg = "Cargando…") => `<div class="loading">${esc(msg)}</div>`;
  const errorBox = (err) => `<div class="notice notice-bad mt1">${esc(err && err.message ? err.message : String(err))}</div>`;

  function toast(msg, kind = "") {
    const box = $("#toasts");
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = msg;
    box.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function downloadText(filename, text, mime = "text/csv;charset=utf-8") {
    const blob = new Blob(["﻿" + text], { type: mime });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }

  const csvCell = (v) => {
    const s = v == null ? "" : String(v);
    return /[;"\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };

  // ───────────────────────────────────────────────────────────────── tema, sesión, navegación
  function applyTheme(theme) {
    if (theme === "dark") document.documentElement.setAttribute("data-theme", "dark");
    else document.documentElement.removeAttribute("data-theme");
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* sin almacenamiento */ }
  }
  function toggleTheme() {
    applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  }

  function showLogin() {
    $("#app").hidden = true;
    $("#login").hidden = false;
    document.body.classList.remove("nav-open");
    const u = $("#loginForm [name=username]");
    if (u && !u.value) u.focus();
  }

  const ROLE_LABEL = { tienda: "usuario de tienda", supervisor: "supervisor", admin: "administrador" };

  async function initApp(me) {
    state.user = me;
    state.summary = null;
    $("#login").hidden = true;
    $("#app").hidden = false;
    $("#userName").textContent = me.username;
    $("#userName2").textContent = me.username;
    $("#userRole").textContent = `${ROLE_LABEL[me.role] || me.role}${me.store_id ? ` · ${me.store_name || me.store_id} (${me.store_id})` : ""}`;
    $("#avatar").textContent = me.username.slice(0, 2);
    $$("[data-admin-only]").forEach((el) => { el.hidden = me.role !== "admin"; });
    refreshReviewCount();
    route();
  }

  async function refreshReviewCount() {
    try {
      const data = await api("/api/review/pending");
      const n = data.reduce((acc, rd) => acc + rd.items.length, 0);
      state.reviewCount = n;
      const el = $("#navReviewCount");
      el.textContent = String(n);
      el.hidden = n === 0;
    } catch { /* la cuenta es informativa */ }
  }

  function parseHash() {
    const raw = location.hash.replace(/^#\/?/, "");
    const [pathPart, q = ""] = raw.split("?");
    const segs = pathPart.split("/").filter(Boolean);
    return { route: segs[0] || "resumen", param: segs[1] ? decodeURIComponent(segs[1]) : null, query: new URLSearchParams(q) };
  }

  function go(route, param = null, params = null) {
    const qs = params ? new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== "")).toString() : "";
    location.hash = `#/${route}${param ? "/" + enc(param) : ""}${qs ? "?" + qs : ""}`;
  }

  const VIEWS = { resumen: renderResumen, gondola: renderGondola, tendencias: renderTendencias, catalogo: renderCatalogo, revision: renderRevision, usuarios: renderUsuarios };

  async function route() {
    if (!state.user) return;
    const ctx = parseHash();
    document.body.classList.remove("nav-open");
    $("#menuBtn").setAttribute("aria-expanded", "false");
    $$("#nav .link[data-route]").forEach((a) => a.classList.toggle("is-active", a.dataset.route === ctx.route));
    const fn = VIEWS[ctx.route] || renderResumen;
    const token = ++state.renderToken;
    view.innerHTML = loading();
    try {
      await fn(ctx, token);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      if (token === state.renderToken) view.innerHTML = `<div class="ph"><h1 class="h1">No se pudo cargar</h1></div>${errorBox(err)}`;
      console.error(err);
    }
  }

  /* Vuelve a dibujar la vista actual conservando el scroll (tras confirmar un recorte, por ejemplo). */
  async function rerender() {
    const y = window.scrollY;
    await route();
    window.scrollTo(0, y);
  }

  // ───────────────────────────────────────────────────────────────── vistas
  // Resumen ─────────────────────────────────────────────────────────
  const byWorst = (a, b) => {
    const av = a.last && a.last.compliance_pct != null ? a.last.compliance_pct : null;
    const bv = b.last && b.last.compliance_pct != null ? b.last.compliance_pct : null;
    if (av == null && bv == null) return (a.last ? 0 : 1) - (b.last ? 0 : 1) || a.id.localeCompare(b.id);
    if (av == null) return 1;
    if (bv == null) return -1;
    return av - bv || a.id.localeCompare(b.id);
  };

  async function renderResumen(ctx, token) {
    const days = [7, 14, 30, 90].includes(Number(ctx.query.get("days"))) ? Number(ctx.query.get("days")) : 7;
    const s = await getSummary(days);
    if (token !== state.renderToken) return;
    const store = ctx.query.get("local") || "";
    const q = (ctx.query.get("q") || "").trim().toLowerCase();
    const rows = s.points
      .filter((p) => (!store || p.store_key === store) && (!q || `${p.name} ${p.id} ${p.planogram_name || ""}`.toLowerCase().includes(q)))
      .sort(byWorst);
    const t = s.totals;
    const stores = s.stores || [];
    const storeRows = stores.map((g) => `<tr class="row-link ${g.key === store ? "is-current" : ""}" data-href="#/resumen?local=${enc(g.key)}${q ? "&q=" + enc(q) : ""}&days=${days}">
        <td class="wrap"><div class="pri">${esc(g.label)}</div><div class="sec">${g.store_id ? esc(g.store_id) : "puntos sin local asignado"}</div></td>
        <td class="num">${fmtInt(g.points)}</td>
        <td class="num">${fmtInt(g.points_measured_in_period)} <span class="muted">de ${fmtInt(g.points)}</span></td>
        <td>${g.avg_compliance_pct != null ? meter(g.avg_compliance_pct) : '<span class="muted">—</span>'}</td>
        <td class="num">${g.total_missing ? `<span class="tag tag-bad">${fmtInt(g.total_missing)}</span>` : fmtInt(0)}</td>
        <td class="num">${g.total_needs_review ? `<span class="tag tag-warn">${fmtInt(g.total_needs_review)}</span>` : fmtInt(0)}</td>
        <td>${g.last_reading_at ? esc(fmtAgo(g.last_reading_at)) : '<span class="tag tag-neutral tag-plain">sin lectura</span>'}</td>
      </tr>`).join("");
    const storesCard = stores.length > 1 || state.user.role !== "tienda" ? `<section class="card mb-s">
        <div class="card-h"><div><div class="card-t">Por local</div><div class="card-s">Cada góndola pertenece a un local. Toca un local para filtrar la tabla de góndolas.</div></div>
          ${store ? `<a class="pill pill-sm" href="#/resumen?days=${days}${q ? "&q=" + enc(q) : ""}">Quitar filtro</a>` : ""}</div>
        <div class="card-b">${storeRows ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Local</th><th class="num">Góndolas</th><th class="num">Medidas · ${days} d</th><th>Cumpl. promedio</th><th class="num">Quiebres</th><th class="num">Por revisar</th><th>Última lectura</th></tr></thead><tbody>${storeRows}</tbody></table></div>` : '<div class="empty">Sin locales.</div>'}</div>
      </section>` : "";

    const tiles = [
      kpi({ label: "Cumplimiento promedio", value: fmtPct(t.avg_compliance_pct), kind: pctKind(t.avg_compliance_pct),
            sub: `última lectura de ${fmtInt(t.points_with_planogram)} góndola${t.points_with_planogram === 1 ? "" : "s"} con planograma` }),
      kpi({ label: `Góndolas medidas · ${days} días`, value: `${fmtInt(t.points_measured_in_period)} <span class="muted">de ${fmtInt(t.points)}</span>`,
            sub: `${fmtInt(t.readings_in_period)} lectura${t.readings_in_period === 1 ? "" : "s"} en el período` }),
      kpi({ label: "Quiebres abiertos", value: fmtInt(t.total_missing), kind: t.total_missing ? "bad" : "good",
            sub: `posiciones sin producto en la última lectura${t.total_low ? ` · ${fmtInt(t.total_low)} con caras bajas` : ""}` }),
      kpi({ label: "Por revisar", value: fmtInt(t.total_needs_review), kind: t.total_needs_review ? "warn" : "good",
            sub: "recortes dudosos en las últimas lecturas · abrir revisión", href: "#/revision" }),
    ].join("");

    const tableRows = rows.map((p) => {
      const l = p.last;
      const pct = l ? l.compliance_pct : null;
      return `<tr class="row-link" data-href="#/gondola/${enc(p.id)}">
        <td class="wrap"><div class="pri">${esc(p.gondola || p.name)}</div><div class="sec">${esc(p.id)}</div></td>
        <td>${esc(p.store || "—")}</td>
        <td class="wrap">${p.planogram_name ? esc(p.planogram_name) : '<span class="tag tag-neutral tag-plain">sin planograma</span>'}</td>
        <td>${l ? `<div>${esc(fmtAgo(l.created_at))}</div><div class="sec">${esc(fmtDate(l.created_at))} · ${fmtInt(p.readings_count)} lectura${p.readings_count === 1 ? "" : "s"}</div>` : '<span class="tag tag-neutral tag-plain">sin lectura</span>'}</td>
        <td>${l && p.planogram_id ? meter(pct) : '<span class="muted">—</span>'}</td>
        <td class="num">${l ? (l.missing ? `<span class="tag tag-bad">${fmtInt(l.missing)}</span>` : fmtInt(0)) : "—"}</td>
        <td class="num">${l ? (l.low ? `<span class="tag tag-warn">${fmtInt(l.low)}</span>` : fmtInt(0)) : "—"}</td>
        <td class="num">${l ? (l.needs_review ? `<span class="tag tag-warn">${fmtInt(l.needs_review)}</span>` : fmtInt(0)) : "—"}</td>
        <td class="num">${l ? fmtInt(l.total_facings) : "—"}</td>
      </tr>`;
    }).join("");

    view.innerHTML = `
      <div class="ph">
        <div><h1 class="h1">Resumen</h1>
          <p class="ph-sub">Última lectura de cada góndola y actividad de los últimos ${days} días. ${fmtInt(t.points)} góndola${t.points === 1 ? "" : "s"} registrada${t.points === 1 ? "" : "s"}. Actualizado ${esc(fmtDate(s.generated_at))}</p></div>
        <div class="ph-actions">
          <a class="pill" href="#/revision">Revisar recortes</a>
          <a class="pill pill-lime" href="/">Nueva lectura</a>
        </div>
      </div>
      <section class="kpis">${tiles}</section>
      ${storesCard}
      <section class="card">
        <div class="card-h">
          <div><div class="card-t">Góndolas por cumplimiento</div><div class="card-s">De menor a mayor cumplimiento de la última lectura. Toca una fila para ver el detalle.</div></div>
          <form class="filters" id="sumFilters" data-form="summary">
            <label class="fld w-l"><span>Buscar</span><input class="in in-sm" name="q" value="${esc(ctx.query.get("q") || "")}" placeholder="Góndola, local o planograma"></label>
            <label class="fld"><span>Local</span><select class="in in-sm" name="local"><option value="">Todos los locales</option>${stores.map((g) => `<option value="${esc(g.key)}" ${g.key === store ? "selected" : ""}>${esc(g.label)}${g.store_id ? ` (${esc(g.store_id)})` : ""}</option>`).join("")}</select></label>
            <label class="fld w-s"><span>Período</span><select class="in in-sm" name="days">${[7, 14, 30, 90].map((d) => `<option value="${d}" ${d === days ? "selected" : ""}>${d} días</option>`).join("")}</select></label>
          </form>
        </div>
        <div class="card-b">
          ${rows.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr>
            <th>Góndola</th><th>Local</th><th>Planograma</th><th>Última lectura</th><th>Cumplimiento</th><th class="num">Quiebres</th><th class="num">Bajas</th><th class="num">Por revisar</th><th class="num">Caras</th>
          </tr></thead><tbody>${tableRows}</tbody></table></div>`
          : `<div class="empty">${s.points.length ? "Ninguna góndola coincide con el filtro." : "Todavía no hay góndolas. Créalas en la app de captura."}</div>`}
        </div>
      </section>`;
  }

  // Góndola ─────────────────────────────────────────────────────────
  async function renderGondola(ctx, token) {
    if (!ctx.param) {
      const s = await getSummary(7);
      if (token !== state.renderToken) return;
      const cards = [...s.points].sort(byWorst).map((p) => `<a class="point" href="#/gondola/${enc(p.id)}">
        <div class="t">${esc(p.gondola || p.name)}</div>
        <div class="s">${esc(p.store || "")}${p.store ? " · " : ""}${esc(p.id)}${p.planogram_name ? " · " + esc(p.planogram_name) : ""}</div>
        <div class="row">${p.last && p.planogram_id ? meter(p.last.compliance_pct) : '<span class="tag tag-neutral tag-plain">sin cumplimiento</span>'}<span class="muted small">${esc(fmtAgo(p.last && p.last.created_at))}</span></div>
      </a>`).join("");
      view.innerHTML = `<div class="ph"><div><h1 class="h1">Góndola</h1><p class="ph-sub">Elige una góndola para ver su última foto, el cumplimiento por banda, qué reponer y los recortes por revisar.</p></div></div>
        ${cards ? `<div class="points">${cards}</div>` : '<div class="empty">Todavía no hay góndolas.</div>'}`;
      return;
    }
    const pid = ctx.param;
    const [point, trends, actions] = await Promise.all([
      api(`/api/points/${enc(pid)}`),
      api(`/api/points/${enc(pid)}/trends?limit=12`),
      api(`/api/points/${enc(pid)}/stock-actions`).catch(() => []),
      getSummary(7).catch(() => null),
    ]);
    if (token !== state.renderToken) return;
    const readings = point.readings || [];
    const ridParam = Number(ctx.query.get("r"));
    const reading = readings.find((r) => r.id === ridParam) || readings[0] || null;
    const imgIdx = Math.max(0, Math.min(Number(ctx.query.get("img") || 0), reading ? reading.image_urls.length - 1 : 0));
    const showBoxes = ctx.query.get("boxes") !== "0";
    const summaryPoint = (state.summary && state.summary.points.find((p) => p.id === pid)) || null;
    const storeLabel = summaryPoint ? summaryPoint.store : point.name;

    const header = `
      <div class="ph">
        <div><h1 class="h1">${esc(point.name)}</h1>
          <p class="ph-sub">${esc(pid)}${summaryPoint && summaryPoint.store ? " · " + esc(storeLabel) : ""} · ${point.planogram_name ? `planograma <b>${esc(point.planogram_name)}</b>` : '<span class="tag tag-neutral tag-plain">sin planograma</span>'} · ${fmtInt(readings.length)} lectura${readings.length === 1 ? "" : "s"}</p></div>
        <div class="ph-actions">
          ${readings.length > 1 ? `<label class="fld w-s"><span class="sr">Lectura</span><select class="in in-sm" data-select="reading">${readings.map((r) => `<option value="${r.id}" ${reading && r.id === reading.id ? "selected" : ""}>Lectura #${r.id} · ${esc(fmtDate(r.created_at))}</option>`).join("")}</select></label>` : ""}
          <a class="pill" href="#/tendencias/${enc(pid)}">Tendencias</a>
          ${point.planogram_id ? `<a class="pill" href="#/catalogo/${enc(point.planogram_id)}?point=${enc(pid)}">Catálogo</a>` : ""}
          <a class="pill pill-lime" href="/">Nueva lectura</a>
        </div>
      </div>`;

    if (!reading) {
      view.innerHTML = `${header}<div class="card"><div class="empty">Esta góndola todavía no tiene lecturas. Toma la primera foto desde la app de captura.</div></div>`;
      return;
    }

    const c = reading.compliance || null;
    const eng = reading.engine || null;
    const expected = c ? c.total_expected_facings : null;
    const missing = c ? c.items.filter((it) => it.status === "missing").length : null;
    const low = c ? c.items.filter((it) => it.status === "low").length : null;

    const tiles = [
      kpi({ label: "Cumplimiento", value: fmtPct(c ? c.compliance_pct : null), kind: pctKind(c ? c.compliance_pct : null),
            sub: c ? `${fmtInt(c.total_filled_facings)} de ${fmtInt(expected)} caras esperadas` : "sin planograma asignado en esta lectura" }),
      kpi({ label: "Caras detectadas", value: fmtInt(reading.total_facings), sub: `${fmtInt(reading.shelf_levels_detected)} niveles · ${fmtPct(reading.empty_space_pct)} de espacio vacío` }),
      kpi({ label: "Quiebres", value: fmtInt(missing), kind: missing ? "bad" : c ? "good" : "", sub: c ? `${fmtInt(low)} posiciones con caras bajas` : "—" }),
      kpi({ label: "Por revisar", value: fmtInt(reading.needs_review), kind: reading.needs_review ? "warn" : "good", sub: "recortes dudosos en esta lectura · ver abajo", scrollTo: "rev" }),
      kpi({ label: "Impacto estimado", value: c && c.impact_clp ? fmtCLP(c.impact_clp) : "—", sub: c ? (c.items_missing_price ? `${fmtInt(c.items_missing_price)} posiciones en falta sin precio cargado` : "unidades faltantes × precio") : "—" }),
    ].join("");

    // foto con cajas
    const engImg = eng && eng.images ? eng.images[imgIdx] : null;
    const [iw, ih] = (engImg && engImg.size) || [4, 3];
    const rects = showBoxes && engImg && engImg.items ? engImg.items.map((it) => {
      const [x1, y1, x2, y2] = it.box;
      const kind = it.status === "signage" ? "signage" : it.needs_review ? "review" : it.status === "match" ? "match" : "unmatched";
      const label = it.status === "signage" ? "Letrero (no es producto)"
        : `${it.title || (it.ocr ? `sin calce · OCR "${it.ocr}"` : "sin identificar")} · confianza ${it.confidence != null ? nf1.format(it.confidence * 100) + " %" : "—"}${it.needs_review ? " · por revisar" : ""}${it.stack_units > 1 ? ` · pila ×${it.stack_units}` : ""}`;
      return `<rect class="bx bx-${kind}" x="${x1}" y="${y1}" width="${Math.max(1, x2 - x1)}" height="${Math.max(1, y2 - y1)}"><title>${esc(label)}</title></rect>`;
    }).join("") : "";
    const nBoxes = engImg && engImg.items ? engImg.items.length : 0;
    const photo = `
      <div class="photo" style="aspect-ratio:${iw}/${ih}">
        <img src="${esc(reading.image_urls[imgIdx])}" alt="Foto de la góndola ${esc(point.name)}">
        <svg viewBox="0 0 ${iw} ${ih}" preserveAspectRatio="none" aria-hidden="true">${rects}</svg>
      </div>
      <div class="photo-tools">
        <div class="legend"><span class="l-match"><i></i>identificado</span><span class="l-review"><i></i>por revisar</span><span class="l-unmatched"><i></i>sin calce</span><span class="l-signage"><i></i>letrero</span></div>
        <div class="row">
          ${reading.image_urls.length > 1 ? `<div class="img-tabs">${reading.image_urls.map((_, i) => `<button type="button" class="${i === imgIdx ? "on" : ""}" data-action="img" data-img="${i}">Foto ${i + 1}</button>`).join("")}</div>` : ""}
          <label class="chk"><input type="checkbox" data-toggle="boxes" ${showBoxes ? "checked" : ""}> cajas (${fmtInt(nBoxes)})</label>
        </div>
      </div>
      <div class="muted xs mt-xs">${esc(reading.notes || "")}</div>`;

    // cumplimiento por banda
    let bands = '<div class="empty">Sin planograma asignado: no hay cumplimiento por banda.</div>';
    if (c) {
      const perBand = {};
      c.items.forEach((it) => { const b = perBand[it.band] || (perBand[it.band] = { missing: 0, low: 0, n: 0 }); b.n++; if (it.status === "missing") b.missing++; if (it.status === "low") b.low++; });
      bands = `<div class="bands">${c.band_summary.map((b) => {
        const x = perBand[b.band] || { missing: 0, low: 0, n: 0 };
        return `<div class="band"><span class="lbl">Banda ${esc(b.band)}</span>${meter(b.compliance_pct, { wide: true })}<span class="extra">${x.missing ? `${x.missing} quiebre${x.missing === 1 ? "" : "s"}` : "sin quiebres"}${x.low ? ` · ${x.low} baja${x.low === 1 ? "" : "s"}` : ""}</span></div>`;
      }).join("")}</div>
      ${c.price_tag_evaluated ? `<div class="muted xs mt-s">Rótulos de precio visibles: ${fmtPct(c.price_tag_compliance_pct)} de ${fmtInt(c.price_tag_evaluated)} evaluados (meta ${fmtInt(c.price_tag_target_pct)} %).</div>` : ""}`;
    }

    // historial
    const series = trends.readings || [];
    const curIdx = series.findIndex((r) => r.id === reading.id);
    const history = series.length ? `
      <div class="chart">${sparkline(series.map((r) => r.compliance_pct), { w: 320, h: 90, max: 100, current: curIdx, labels: series.map((r) => fmtDay(r.created_at)), unit: " %" })}
        <div class="chart-x"><span>${esc(fmtDay(series[0].created_at))}</span><span>cumplimiento por lectura (últimas ${series.length})</span><span>${esc(fmtDay(series[series.length - 1].created_at))}</span></div></div>
      <div class="tbl-wrap mt-s"><table class="tbl"><thead><tr><th>Lectura</th><th class="num">Cumpl.</th><th class="num">Caras</th><th class="num">Quiebres</th><th class="num">Revisar</th></tr></thead><tbody>
        ${[...series].reverse().map((r) => `<tr class="row-link ${r.id === reading.id ? "is-current" : ""}" data-href="#/gondola/${enc(pid)}?r=${r.id}">
          <td><div class="pri">#${r.id}</div><div class="sec">${esc(fmtDate(r.created_at))}</div></td>
          <td class="num">${fmtPct(r.compliance_pct)}</td><td class="num">${fmtInt(r.total_facings)}</td><td class="num">${fmtInt(r.missing)}</td><td class="num">${fmtInt(r.needs_review)}</td></tr>`).join("")}
      </tbody></table></div>` : '<div class="empty">Sin historial.</div>';

    // reponer
    const openActions = (actions || []).filter((a) => !a.resolved_at);
    const requested = new Map(openActions.map((a) => [a.planogram_item_id, a]));
    const repl = c ? c.replenishment : [];
    const replHtml = repl.length ? `<div class="list">${repl.map((it) => {
      const req = requested.get(it.planogram_item_id);
      return `<div class="li" id="repl-${it.planogram_item_id}">
        <div><div class="t">${esc(it.title)}${tagTop(it.tag)}</div><div class="s">Banda ${esc(it.band)} · posición ${esc(it.position_in_section)} · faltan <b>${fmtInt(it.deficit)}</b> de ${fmtInt(it.expected_facings)} caras${it.uncertain ? " · conteo por confirmar" : ""}${it.price_clp != null && it.deficit_value_clp ? ` · ${fmtCLP(it.deficit_value_clp)}` : ""}</div></div>
        <div class="r">${statusTag(it.status)}${req ? `<span class="tag tag-info tag-plain">solicitado ${esc(fmtAgo(req.created_at))}</span>` : `<button type="button" class="pill pill-xs" data-action="request" data-item="${it.planogram_item_id}" data-title="${esc(it.title)}" data-qty="${it.deficit}">Solicitar</button>`}</div>
      </div>`;
    }).join("")}</div>` : `<div class="empty">${c ? "Todas las posiciones del planograma están completas en esta lectura." : "Sin planograma asignado."}</div>`;

    const foreign = c && c.foreign_products.length ? `<div class="card"><div class="card-h"><div><div class="card-t">Fuera de planograma</div><div class="card-s">Productos detectados que no calzan con ninguna posición (mal ubicados o ajenos a esta góndola).</div></div></div>
      <div class="card-b"><div class="list">${c.foreign_products.map((p) => `<div class="li"><div><div class="t">${esc(p.product || "sin identificar")}</div><div class="s">Nivel ${esc(p.shelf_level)} · ${fmtInt(p.facings)} cara${p.facings === 1 ? "" : "s"}</div></div><div class="r"><span class="tag tag-neutral tag-plain">confianza ${esc(p.confidence_fuera_de_planograma)}</span></div></div>`).join("")}</div></div></div>` : "";
    const misplaced = c && c.misplaced_items.length ? `<div class="card"><div class="card-h"><div><div class="card-t">Orden incorrecto</div><div class="card-s">Presentes, pero fuera de la secuencia izquierda→derecha que manda el planograma.</div></div></div>
      <div class="card-b"><div class="list">${c.misplaced_items.map((m) => `<div class="li"><div><div class="t">${esc(m.title)}${tagTop(m.tag)}</div><div class="s">Banda ${esc(m.band)} · posición esperada ${esc(m.position_in_section)}</div></div></div>`).join("")}</div></div></div>` : "";

    view.innerHTML = `${header}
      <section class="kpis k5">${tiles}</section>
      <div class="g-photo">
        <section class="card"><div class="card-h"><div><div class="card-t">Lectura #${reading.id}</div><div class="card-s">${esc(fmtDate(reading.created_at))} · ${esc(fmtAgo(reading.created_at))}${eng ? ` · ${esc(eng.detector || "")}` : ""}</div></div></div>
          <div class="card-b">${photo}</div></section>
        <div class="stack">
          <section class="card"><div class="card-h"><div><div class="card-t">Cumplimiento por banda</div><div class="card-s">Caras cubiertas sobre caras esperadas en cada banda.</div></div></div><div class="card-b">${bands}</div></section>
          <section class="card"><div class="card-h"><div><div class="card-t">Historial</div><div class="card-s">Últimas lecturas de esta góndola.</div></div></div><div class="card-b">${history}</div></section>
        </div>
      </div>
      <div class="stack mt1">
        <section class="card"><div class="card-h"><div><div class="card-t">Reponer</div><div class="card-s">Posiciones con quiebre o caras bajas en esta lectura, TOP y lanzamientos primero.</div></div>${repl.length ? `<span class="tag tag-neutral tag-plain">${fmtInt(repl.length)} posiciones</span>` : ""}</div><div class="card-b">${replHtml}</div></section>
        <section class="card" id="rev"><div class="card-h"><div><div class="card-t">Por revisar en esta lectura</div><div class="card-s">Confirma cada recorte dudoso una vez: corrige la lectura y enseña a la memoria visual.</div></div></div>
          <div class="card-b" id="gondolaReview">${reading.needs_review ? loading("Cargando recortes…") : '<div class="empty">Nada por revisar en esta lectura.</div>'}</div></section>
        ${foreign}${misplaced}
      </div>`;

    if (reading.needs_review) {
      try {
        const rv = await api(`/api/readings/${reading.id}/review`);
        if (token !== state.renderToken) return;
        const box = $("#gondolaReview");
        if (box) box.innerHTML = rv.items.length ? rv.items.map((it) => reviewItemHtml(rv, it)).join("") : '<div class="empty">Nada por revisar en esta lectura.</div>';
      } catch (err) {
        const box = $("#gondolaReview");
        if (box) box.innerHTML = errorBox(err);
      }
    }
  }

  // Tendencias (Módulo 1) ───────────────────────────────────────────
  async function renderTendencias(ctx, token) {
    const s = await getSummary(7);
    if (token !== state.renderToken) return;
    const candidates = s.points.filter((p) => p.planogram_id);
    const pid = ctx.param || (candidates[0] && candidates[0].id) || null;
    const limit = [6, 12, 24, 52].includes(Number(ctx.query.get("n"))) ? Number(ctx.query.get("n")) : 12;
    const selector = `<label class="fld"><span class="sr">Góndola</span><select class="in in-sm" data-select="trend-point">${s.points.map((p) => `<option value="${esc(p.id)}" ${p.id === pid ? "selected" : ""} ${!p.planogram_id ? "disabled" : ""}>${esc(p.name)}${!p.planogram_id ? " (sin planograma)" : ""}</option>`).join("")}</select></label>
      <label class="fld w-s"><span class="sr">Lecturas</span><select class="in in-sm" data-select="trend-limit">${[6, 12, 24, 52].map((n) => `<option value="${n}" ${n === limit ? "selected" : ""}>últimas ${n}</option>`).join("")}</select></label>`;
    if (!pid) {
      view.innerHTML = `<div class="ph"><div><h1 class="h1">Tendencias por SKU</h1><p class="ph-sub">Caras detectadas de cada posición del planograma, lectura a lectura.</p></div></div><div class="empty">No hay góndolas con planograma asignado.</div>`;
      return;
    }
    const t = await api(`/api/points/${enc(pid)}/trends?limit=${limit}`);
    if (token !== state.renderToken) return;
    const kindFilter = ctx.query.get("flag") || "";
    const q = (ctx.query.get("q") || "").trim().toLowerCase();
    const readings = t.readings || [];
    const labels = readings.map((r) => fmtDay(r.created_at));
    const skus = (t.skus || [])
      .filter((x) => (!kindFilter || x.flag_kind === kindFilter) && (!q || x.title.toLowerCase().includes(q)))
      .sort((a, b) => (FLAG_ORDER[a.flag_kind] ?? 9) - (FLAG_ORDER[b.flag_kind] ?? 9) || a.band - b.band || a.position_in_section - b.position_in_section);
    const fc = t.flag_counts || {};
    const first = readings[0], last = readings[readings.length - 1];
    const delta = first && last && first.compliance_pct != null && last.compliance_pct != null ? last.compliance_pct - first.compliance_pct : null;

    const tiles = [
      kpi({ label: "Lecturas en la serie", value: fmtInt(readings.length), sub: readings.length ? `${esc(fmtDay(first.created_at))} → ${esc(fmtDay(last.created_at))}` : "sin lecturas" }),
      kpi({ label: "Cumplimiento última", value: fmtPct(last ? last.compliance_pct : null), kind: pctKind(last ? last.compliance_pct : null),
            sub: delta == null ? "—" : `${delta >= 0 ? "+" : ""}${nf1.format(delta)} puntos vs. la primera de la serie` }),
      kpi({ label: "En quiebre", value: fmtInt(fc.quiebre || 0), kind: fc.quiebre ? "bad" : "good", sub: "SKU sin caras en la última lectura" }),
      kpi({ label: "A la baja", value: fmtInt((fc.baja || 0) + (fc.bajo || 0)), kind: (fc.baja || 0) + (fc.bajo || 0) ? "warn" : "good", sub: `${fmtInt(fc.baja || 0)} cayendo · ${fmtInt(fc.bajo || 0)} bajo lo esperado` }),
      kpi({ label: "Estables o subiendo", value: fmtInt((fc.estable || 0) + (fc.sube || 0)), kind: "good", sub: `${fmtInt(fc.estable || 0)} estables · ${fmtInt(fc.sube || 0)} suben` }),
    ].join("");

    const maxFac = Math.max(1, ...(t.skus || []).flatMap((x) => x.series.filter((v) => v != null)), ...(t.skus || []).map((x) => x.expected_facings || 0));
    const rows = skus.map((x) => `<tr>
      <td class="wrap"><div class="pri">${esc(x.title)}${tagTop(x.tag)}</div><div class="sec">Banda ${esc(x.band)} · posición ${esc(x.position_in_section)}${x.price_clp != null ? " · " + fmtCLP(x.price_clp) : ""}</div></td>
      <td class="num">${fmtInt(x.expected_facings)}</td>
      <td class="spark-cell">${sparkline(x.series, { w: 136, h: 30, max: Math.max(x.expected_facings || 0, ...x.series.filter((v) => v != null)), labels })}</td>
      <td class="sec mono">${x.series.map((v) => (v == null ? "·" : v)).join(" ")}</td>
      <td class="num"><b>${fmtInt(x.last)}</b></td>
      <td class="num">${x.delta == null ? "—" : (x.delta > 0 ? "+" : "") + fmtInt(x.delta)}</td>
      <td>${flagTag(x)}</td>
    </tr>`).join("");

    view.innerHTML = `
      <div class="ph">
        <div><h1 class="h1">Tendencias por SKU</h1><p class="ph-sub"><b>${esc(t.point_name)}</b> · ${esc(t.planogram_name || "sin planograma")}. Caras detectadas en cada lectura por posición del planograma; "baja N" cuenta caídas consecutivas al final de la serie.</p></div>
        <div class="ph-actions"><form class="filters" data-form="trend-head">${selector}</form><button type="button" class="pill" data-action="export-csv">Exportar CSV</button><a class="pill pill-ghost" href="#/gondola/${enc(pid)}">Ver góndola</a></div>
      </div>
      <section class="kpis k5">${tiles}</section>
      <section class="card"><div class="card-h"><div><div class="card-t">Cumplimiento por lectura</div><div class="card-s">Caras cubiertas sobre esperadas, lectura a lectura (máximo 100 %).</div></div></div>
        <div class="card-b">${readings.length ? `<div class="chart">${sparkline(readings.map((r) => r.compliance_pct), { w: 640, h: 110, max: 100, labels, unit: " %" })}<div class="chart-x"><span>${esc(labels[0])}</span><span>${readings.length} lecturas</span><span>${esc(labels[labels.length - 1])}</span></div></div>` : '<div class="empty">Sin lecturas.</div>'}</div></section>
      <section class="card mt1">
        <div class="card-h"><div><div class="card-t">Serie por SKU</div><div class="card-s">${fmtInt(skus.length)} de ${fmtInt((t.skus || []).length)} posiciones. Orden: quiebres, bajas, bajo lo esperado, luego el resto.</div></div>
          <form class="filters" data-form="trend-filters">
            <label class="fld w-l"><span>Buscar SKU</span><input class="in in-sm" name="q" value="${esc(ctx.query.get("q") || "")}" placeholder="Título del planograma"></label>
            <label class="fld"><span>Tendencia</span><select class="in in-sm" name="flag"><option value="">Todas</option>${[["quiebre", "quiebre"], ["baja", "baja"], ["bajo", "bajo esperado"], ["estable", "estable"], ["sube", "sube"], ["none", "sin datos"]].map(([k, l]) => `<option value="${k}" ${k === kindFilter ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          </form></div>
        <div class="card-b">${rows ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>SKU</th><th class="num">Esperado</th><th>Serie</th><th>Caras por lectura</th><th class="num">Última</th><th class="num">Δ</th><th>Tendencia</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<div class="empty">Ninguna posición coincide con el filtro.</div>'}</div>
      </section>`;
    state.trendData = t;
  }

  function exportTrendsCsv() {
    const t = state.trendData;
    if (!t) return;
    const dates = t.readings.map((r) => r.created_at.slice(0, 10));
    const head = ["punto", "nombre", "planograma", "sku", "banda", "posicion", "etiqueta", "esperado", ...dates.map((d, i) => `lectura_${i + 1}_${d}`), "ultima", "delta", "tendencia"];
    const lines = [head.join(";")];
    t.skus.forEach((x) => {
      lines.push([t.point_id, t.point_name, t.planogram_name, x.title, x.band, x.position_in_section, x.tag || "", x.expected_facings,
        ...x.series.map((v) => (v == null ? "" : v)), x.last ?? "", x.delta ?? "", x.flag].map(csvCell).join(";"));
    });
    downloadText(`tendencias-${t.point_id}-${new Date().toISOString().slice(0, 10)}.csv`, lines.join("\r\n"));
    toast("CSV exportado (separador ;)", "good");
  }

  // Catálogo ────────────────────────────────────────────────────────
  async function renderCatalogo(ctx, token) {
    const [s, pgs] = await Promise.all([getSummary(7), getPlanograms()]);
    if (token !== state.renderToken) return;
    const withPg = s.points.filter((p) => p.planogram_id);
    const planId = ctx.param || (withPg[0] && withPg[0].planogram_id) || (pgs[0] && pgs[0].id) || null;
    const pointsOfPlan = s.points.filter((p) => p.planogram_id === planId);
    const rawPoint = ctx.query.get("point");
    const pointParam = rawPoint == null ? (pointsOfPlan[0] ? pointsOfPlan[0].id : "") : (rawPoint === "-" ? "" : rawPoint);
    const head = (sub) => `<div class="ph"><div><h1 class="h1">Catálogo</h1><p class="ph-sub">${sub}</p></div>
      <div class="ph-actions"><form class="filters" data-form="catalog-head">
        <label class="fld"><span class="sr">Planograma</span><select class="in in-sm" data-select="catalog-plan">${pgs.map((pg) => `<option value="${esc(pg.id)}" ${pg.id === planId ? "selected" : ""}>${esc(pg.name)} (${fmtInt(pg.item_count)})</option>`).join("")}</select></label>
        <label class="fld"><span class="sr">Góndola</span><select class="in in-sm" data-select="catalog-point"><option value="">Sin lectura (solo catálogo)</option>${pointsOfPlan.map((p) => `<option value="${esc(p.id)}" ${p.id === pointParam ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>
      </form></div></div>`;
    if (!planId) {
      view.innerHTML = head("Imagen oficial, marca y precio de cada SKU del planograma frente a lo que vio la cámara.") + '<div class="empty">No hay planogramas cargados. <a href="/planogramas">Importar uno</a>.</div>';
      return;
    }
    const c = await api(`/api/catalog/${enc(planId)}${pointParam ? `?point_id=${enc(pointParam)}` : ""}`);
    if (token !== state.renderToken) return;
    const band = ctx.query.get("band") || "";
    const st = ctx.query.get("st") || "";
    const q = (ctx.query.get("q") || "").trim().toLowerCase();
    const bandsAvail = [...new Set(c.items.map((it) => it.band))].sort((a, b) => a - b);
    const items = c.items.filter((it) => (!band || String(it.band) === band)
      && (!st || (st === "none" ? !it.observed : it.observed && it.observed.status === st))
      && (!q || `${it.title} ${(it.catalog && (it.catalog.title_web + " " + it.catalog.brand)) || ""} ${it.internal_code || ""}`.toLowerCase().includes(q)));
    const cov = c.coverage;
    const obsInfo = c.point && c.point.reading_id
      ? (c.point.planogram_id === planId ? `Última lectura de <b>${esc(c.point.name)}</b>: #${c.point.reading_id}, ${esc(fmtAgo(c.point.created_at))}.` : `La última lectura de ${esc(c.point.name)} usó otro planograma: sin observación.`)
      : c.point ? `${esc(c.point.name)} no tiene lecturas todavía.` : "Sin góndola seleccionada: solo la ficha oficial.";

    const cards = items.map((it) => {
      const cat = it.catalog;
      const obs = it.observed;
      const crop = obs && obs.crops.length ? obs.crops[0] : null;
      const official = cat && cat.image ? `<figure><img src="${esc(cat.image)}" alt="Imagen oficial de ${esc(it.title)}" loading="lazy"><figcaption>Imagen oficial</figcaption></figure>`
        : `<figure><div class="ph-empty">Sin ficha en el catálogo</div><figcaption>Imagen oficial</figcaption></figure>`;
      const seen = crop ? `<figure><img src="${esc(crop.crop_url)}" alt="Recorte de la cámara para ${esc(it.title)}" loading="lazy"><figcaption>Lo que vio la cámara</figcaption></figure>`
        : `<figure><div class="ph-empty">${obs ? (obs.status === "missing" ? "No se vio en la última lectura" : "Sin recorte asociado") : "Sin lectura"}</div><figcaption>Lo que vio la cámara</figcaption></figure>`;
      const obsLine = obs ? `${statusTag(obs.status, "tag-sm")} <span><b>${fmtInt(obs.detected_facings)}</b> de ${fmtInt(it.expected_facings)} caras${obs.uncertain ? " · por confirmar" : ""}${obs.orden_incorrecto ? " · orden incorrecto" : ""}</span>${crop && crop.confidence != null ? `<span class="muted">conf. ${nf1.format(crop.confidence * 100)} %</span>` : ""}`
        : `<span class="muted">sin observación</span>`;
      return `<article class="sku">
        <div class="sku-imgs">${official}${seen}</div>
        <div class="sku-b">
          <div class="sku-t">${esc(it.title)}${tagTop(it.tag)}</div>
          <div class="sku-s">${cat ? `${esc(cat.title_web || "")}${cat.brand ? " · " + esc(cat.brand) : ""}` : `código ${esc(it.internal_code || "—")}`}${cat && cat.url ? ` · <a href="${esc(cat.url)}" target="_blank" rel="noopener">ficha</a>` : ""}</div>
          <div class="sku-meta"><span>Banda <b>${esc(it.band)}</b> · pos. <b>${esc(it.position_in_section)}</b></span><span>esperado <b>${fmtInt(it.expected_facings)}</b></span><span>${it.price_clp != null ? `<b>${fmtCLP(it.price_clp)}</b>${it.price_source ? ` <span class="muted">(${esc(it.price_source)})</span>` : ""}` : '<span class="muted">sin precio</span>'}</span></div>
          <div class="sku-obs">${obsLine}</div>
        </div>
      </article>`;
    }).join("");

    view.innerHTML = head(`<b>${esc(c.planogram.name)}</b> · ${fmtInt(cov.with_catalog)} de ${fmtInt(cov.items)} posiciones con ficha oficial${c.catalog_categories.length ? ` (${esc(c.catalog_categories.join(", "))})` : ""}. ${obsInfo}`) + `
      <section class="card"><div class="card-h"><div><div class="card-t">SKU del planograma</div><div class="card-s">${fmtInt(items.length)} de ${fmtInt(c.items.length)} posiciones.</div></div>
        <form class="filters" data-form="catalog-filters">
          <label class="fld w-l"><span>Buscar</span><input class="in in-sm" name="q" value="${esc(ctx.query.get("q") || "")}" placeholder="Título, marca o código"></label>
          <label class="fld w-s"><span>Banda</span><select class="in in-sm" name="band"><option value="">Todas</option>${bandsAvail.map((b) => `<option value="${b}" ${String(b) === band ? "selected" : ""}>Banda ${b}</option>`).join("")}</select></label>
          <label class="fld"><span>Observado</span><select class="in in-sm" name="st"><option value="">Todos</option><option value="ok" ${st === "ok" ? "selected" : ""}>completo</option><option value="low" ${st === "low" ? "selected" : ""}>caras bajas</option><option value="missing" ${st === "missing" ? "selected" : ""}>quiebre</option><option value="none" ${st === "none" ? "selected" : ""}>sin observación</option></select></label>
        </form></div>
        <div class="card-b">${cards ? `<div class="skus">${cards}</div>` : '<div class="empty">Ninguna posición coincide con el filtro.</div>'}</div></section>`;
  }

  // Revisión ────────────────────────────────────────────────────────
  function candidatesOf(it) {
    const out = [];
    const push = (title, kind, score) => { if (title && !out.some((o) => o.t === title)) out.push({ t: title, k: kind, s: score }); };
    if (it.status === "match" && it.product) push(it.product, "motor", it.confidence);
    (it.visual_top3 || []).forEach((v) => push(v.title, "visual", v.sim));
    (it.text_top3 || []).forEach((v) => push(v.title, "texto", v.score));
    return out.slice(0, 4);
  }

  function reviewItemHtml(rd, it) {
    const key = `${rd.reading_id}-${it.image_index}-${it.item_index}`;
    const cands = candidatesOf(it);
    const stKind = it.status === "match" ? (it.ambiguous ? "warn" : "info") : "bad";
    const stLabel = it.status === "match" ? (it.ambiguous ? "ambiguo" : "identificado con poca confianza") : it.status === "unmatched" ? "sin calce" : it.status === "unreadable" ? "ilegible" : it.status;
    return `<div class="rv" id="rv-${key}" data-rid="${rd.reading_id}" data-img="${it.image_index}" data-item="${it.item_index}">
      <img class="rv-crop" src="${esc(it.crop_url)}" alt="Recorte nivel ${esc(it.level)} posición ${esc(it.position)}" loading="lazy">
      <div class="rv-b">
        <div class="rv-h"><span class="tag tag-${stKind}">${esc(stLabel)}</span><span>Nivel ${esc(it.level)} · posición ${esc(it.position)}</span><span class="muted">confianza ${it.confidence != null ? nf1.format(it.confidence * 100) + " %" : "—"} · ${fmtInt(it.facings)} cara${it.facings === 1 ? "" : "s"}</span></div>
        ${it.ocr ? `<div class="muted xs">Texto leído: ${esc(it.ocr)}</div>` : ""}
        <div class="rv-cands">${cands.length ? cands.map((cnd) => `<button type="button" class="cand" data-action="confirm" data-title="${esc(cnd.t)}"><b>${esc(cnd.t)}</b><span>${esc(cnd.k)} ${cnd.s != null ? nf1.format(Number(cnd.s) * 100) + " %" : ""}</span></button>`).join("") : '<span class="muted xs">Sin sugerencias: elige el SKU en la lista.</span>'}</div>
        <div class="rv-form">
          <select class="in in-xs" data-field="title"><option value="">— SKU del planograma —</option>${rd.titles.map((tt) => `<option>${esc(tt)}</option>`).join("")}</select>
          <input class="in in-xs" type="number" min="0" data-field="facings" value="${it.facings ?? 1}" aria-label="Caras">
          <button type="button" class="pill pill-xs pill-lime" data-action="confirm-select">Confirmar</button>
          <button type="button" class="pill pill-xs" data-action="confirm" data-title="">Fuera de planograma</button>
          <button type="button" class="pill pill-xs pill-ghost" data-action="skip">Omitir</button>
        </div>
      </div>
    </div>`;
  }

  async function renderRevision(ctx, token) {
    const [data] = await Promise.all([api("/api/review/pending"), getSummary(7).catch(() => null)]);
    if (token !== state.renderToken) return;
    const n = data.reduce((acc, rd) => acc + rd.items.length, 0);
    state.reviewCount = n;
    const el = $("#navReviewCount"); el.textContent = String(n); el.hidden = n === 0;
    const pointName = (id) => (state.summary && (state.summary.points.find((p) => p.id === id) || {}).name) || id;
    view.innerHTML = `
      <div class="ph"><div><h1 class="h1">Revisión</h1><p class="ph-sub">Cada recorte dudoso se confirma una vez. La confirmación corrige la lectura y queda en la memoria visual: la próxima vez ese producto se reconoce por apariencia.</p></div>
        <div class="ph-actions"><span class="tag tag-${n ? "warn" : "good"}" id="revCount">${n ? `${fmtInt(n)} recortes en ${fmtInt(data.length)} lectura${data.length === 1 ? "" : "s"}` : "Sin pendientes"}</span></div></div>
      ${data.length ? data.map((rd) => `<section class="card mb-s"><div class="card-h"><div><div class="card-t">Lectura #${rd.reading_id} · ${esc(pointName(rd.point_id))}</div><div class="card-s">${esc(fmtDate(rd.created_at))} · ${esc(fmtAgo(rd.created_at))} · ${fmtInt(rd.items.length)} recorte${rd.items.length === 1 ? "" : "s"}</div></div><a class="pill pill-sm" href="#/gondola/${enc(rd.point_id)}?r=${rd.reading_id}">Ver góndola</a></div>
        <div class="card-b">${rd.items.map((it) => reviewItemHtml(rd, it)).join("")}</div></section>`).join("")
      : '<section class="card"><div class="empty">No hay recortes pendientes de revisión.</div></section>'}`;
  }

  // Usuarios (solo administradores) ──────────────────────────────
  const roleTag = (role) => `<span class="tag ${role === "admin" ? "tag-info" : role === "supervisor" ? "tag-good" : "tag-neutral"} tag-plain">${esc(ROLE_LABEL[role] || role)}</span>`;

  function userEditForm(u) {
    return `<form class="edit-form" data-form="user-edit" data-username="${esc(u.username)}">
      <label class="fld"><span>Rol</span><select class="in in-sm" name="role">${["tienda", "supervisor", "admin"].map((r) => `<option value="${r}" ${u.role === r ? "selected" : ""}>${ROLE_LABEL[r]}</option>`).join("")}</select></label>
      <label class="fld"><span>Id del local</span><input class="in in-sm" name="store_id" value="${esc(u.store_id || "")}" placeholder="L001" autocapitalize="characters"></label>
      <label class="fld"><span>Nombre del local</span><input class="in in-sm" name="store_name" value="${esc(u.store_name || "")}" placeholder="Providencia 1234"></label>
      <label class="fld"><span>Nueva contraseña</span><input class="in in-sm" name="password" type="password" autocomplete="new-password" placeholder="(sin cambio)" minlength="6"></label>
      <div class="acts"><button class="pill pill-sm pill-lime" type="submit">Guardar</button><button class="pill pill-sm" type="button" data-action="edit-cancel">Cancelar</button>
        ${u.username !== state.user.username ? `<button class="pill pill-sm pill-danger" type="button" data-action="user-delete" data-username="${esc(u.username)}">Eliminar usuario</button>` : ""}</div>
    </form>`;
  }

  async function renderUsuarios(ctx, token) {
    if (!state.user || state.user.role !== "admin") {
      view.innerHTML = `<div class="ph"><div><h1 class="h1">Usuarios</h1></div></div><div class="notice notice-info">Solo los administradores gestionan usuarios y locales.</div>`;
      return;
    }
    const users = await api("/api/admin/users");
    if (token !== state.renderToken) return;
    const editing = ctx.query.get("edit") || "";
    const nStores = new Set(users.filter((u) => u.store_id).map((u) => u.store_id)).size;
    const rows = users.map((u) => `<tr>
        <td><div class="pri">${esc(u.username)}</div><div class="sec">desde ${esc(fmtDay(u.created_at))}</div></td>
        <td>${roleTag(u.role)}</td>
        <td class="wrap">${u.store_id ? `<div class="pri">${esc(u.store_name || u.store_id)}</div><div class="sec">${esc(u.store_id)}</div>` : '<span class="muted">todos los locales</span>'}</td>
        <td class="acts"><button type="button" class="link-btn" data-action="edit-user" data-username="${esc(u.username)}">${editing === u.username ? "Cerrar" : "Editar"}</button></td>
      </tr>${editing === u.username ? `<tr class="edit-row"><td colspan="4">${userEditForm(u)}</td></tr>` : ""}`).join("");
    view.innerHTML = `
      <div class="ph"><div><h1 class="h1">Usuarios</h1><p class="ph-sub">${fmtInt(users.length)} usuarios · ${fmtInt(nStores)} locales con usuario de tienda. Un usuario de tienda solo ve y crea las góndolas de su local; supervisores y administradores ven todos.</p></div></div>
      <div class="g-photo">
        <section class="card"><div class="card-h"><div><div class="card-t">Usuarios</div><div class="card-s">Rol y local de cada cuenta.</div></div></div>
          <div class="card-b"><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Usuario</th><th>Rol</th><th>Local</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div></section>
        <section class="card"><div class="card-h"><div><div class="card-t">Crear usuario</div><div class="card-s">Para un local: rol "usuario de tienda" con el id (p. ej. L001) y el nombre del local. No necesita código de invitación.</div></div></div>
          <div class="card-b"><form class="stack" data-form="user-create" autocomplete="off">
            <label class="fld"><span>Usuario</span><input class="in" name="username" required minlength="3" autocapitalize="none" placeholder="l001-caja"></label>
            <label class="fld"><span>Contraseña</span><input class="in" name="password" type="password" required minlength="6" autocomplete="new-password"></label>
            <label class="fld"><span>Rol</span><select class="in" name="role"><option value="tienda">usuario de tienda</option><option value="supervisor">supervisor</option><option value="admin">administrador</option></select></label>
            <div class="g2"><label class="fld"><span>Id del local</span><input class="in" name="store_id" placeholder="L001" autocapitalize="characters"></label>
              <label class="fld"><span>Nombre del local</span><input class="in" name="store_name" placeholder="Providencia 1234"></label></div>
            <div class="form-err" data-err></div>
            <div><button class="pill pill-lime" type="submit">Crear usuario</button></div>
          </form></div></section>
      </div>`;
  }

  async function submitUserForm(form) {
    const data = Object.fromEntries(new FormData(form).entries());
    const err = form.querySelector("[data-err]");
    const btn = form.querySelector("button[type=submit]");
    if (err) err.textContent = "";
    btn.disabled = true;
    try {
      if (form.dataset.form === "user-create") {
        const u = await api("/api/admin/users", { method: "POST", json: data });
        toast(`Usuario ${u.username} creado (${ROLE_LABEL[u.role]})`, "good");
        go("usuarios");
        await rerender();
      } else {
        const username = form.dataset.username;
        const body = { role: data.role, store_id: data.store_id, store_name: data.store_name };
        if (data.password) body.password = data.password;
        const u = await api(`/api/admin/users/${enc(username)}`, { method: "PATCH", json: body });
        toast(`Guardado: ${u.username} · ${ROLE_LABEL[u.role]}${u.store_id ? " · " + u.store_id : ""}${data.password ? " · contraseña cambiada" : ""}`, "good");
        if (u.username === state.user.username) state.user = { ...state.user, role: u.role, store_id: u.store_id, store_name: u.store_name };
        go("usuarios");
        await rerender();
      }
    } catch (e) {
      if (err) err.textContent = e.message; else toast(e.message, "bad");
    } finally {
      btn.disabled = false;
    }
  }

  async function deleteUser(username) {
    if (!window.confirm(`¿Eliminar el usuario ${username}? Esta acción no se puede deshacer.`)) return;
    try {
      await api(`/api/admin/users/${enc(username)}`, { method: "DELETE" });
      toast(`Usuario ${username} eliminado`);
      go("usuarios");
      await rerender();
    } catch (e) {
      toast(e.message, "bad");
    }
  }

  async function confirmItem(node, title) {
    const rid = Number(node.dataset.rid), img = Number(node.dataset.img), item = Number(node.dataset.item);
    const facInput = node.querySelector("[data-field=facings]");
    const facings = facInput && facInput.value !== "" ? Number(facInput.value) : null;
    node.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      const d = await api(`/api/readings/${rid}/confirm`, { method: "POST", json: { image_index: img, item_index: item, title: title || null, facings } });
      node.className = "rv done";
      node.innerHTML = `Confirmado${title ? `: <b>${esc(title)}</b>` : " como fuera de planograma"}${facings != null ? ` · ${fmtInt(facings)} cara${facings === 1 ? "" : "s"}` : ""} · memoria visual: ${d.memory_size != null ? fmtInt(d.memory_size) + " ejemplos" : "sin cambio"} · quedan ${fmtInt(d.needs_review)} en esta lectura`;
      if (state.reviewCount != null) { state.reviewCount = Math.max(0, state.reviewCount - 1); const el = $("#navReviewCount"); el.textContent = String(state.reviewCount); el.hidden = state.reviewCount === 0; }
      const rc = $("#revCount");
      if (rc && state.reviewCount != null) rc.textContent = state.reviewCount ? `${fmtInt(state.reviewCount)} recortes pendientes` : "Sin pendientes";
      state.summary = null;
      if (parseHash().route === "gondola") rerender();
    } catch (err) {
      node.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      toast(err.message || "No se pudo confirmar", "bad");
    }
  }

  async function requestReplenishment(btn) {
    const pid = parseHash().param;
    const qty = Math.max(1, Number(btn.dataset.qty) || 1);
    btn.disabled = true;
    try {
      const a = await api(`/api/points/${enc(pid)}/stock-actions`, { method: "POST", json: { planogram_item_id: Number(btn.dataset.item), product_title: btn.dataset.title, action_type: "solicitud", quantity: qty, note: "desde el panel de supervisión" } });
      btn.outerHTML = `<span class="tag tag-info tag-plain">solicitado ${esc(fmtAgo(a.created_at))}</span>`;
      toast(`Solicitud de reposición: ${qty} × ${btn.dataset.title}`, "good");
    } catch (err) {
      btn.disabled = false;
      toast(err.message || "No se pudo registrar la solicitud", "bad");
    }
  }

  // ───────────────────────────────────────────────────────────────── eventos
  function updateQuery(patch) {
    const ctx = parseHash();
    Object.entries(patch).forEach(([k, v]) => { if (v == null || v === "") ctx.query.delete(k); else ctx.query.set(k, v); });
    go(ctx.route, ctx.param, Object.fromEntries(ctx.query.entries()));
  }

  view.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-action]");
    if (btn) {
      const action = btn.dataset.action;
      const node = btn.closest(".rv");
      if (action === "confirm" && node) return confirmItem(node, btn.dataset.title || "");
      if (action === "confirm-select" && node) {
        const sel = node.querySelector("[data-field=title]");
        if (!sel.value) { toast("Elige un SKU del planograma", "bad"); sel.focus(); return; }
        return confirmItem(node, sel.value);
      }
      if (action === "skip" && node) { node.remove(); return; }
      if (action === "request") return requestReplenishment(btn);
      if (action === "export-csv") return exportTrendsCsv();
      if (action === "img") return updateQuery({ img: btn.dataset.img });
      if (action === "scroll-to") { const t = document.getElementById(btn.dataset.target); if (t) t.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
      if (action === "edit-user") return updateQuery({ edit: parseHash().query.get("edit") === btn.dataset.username ? null : btn.dataset.username });
      if (action === "edit-cancel") return updateQuery({ edit: null });
      if (action === "user-delete") return deleteUser(btn.dataset.username);
      return;
    }
    const row = ev.target.closest("tr.row-link[data-href]");
    if (row && !ev.target.closest("a, button, input, select")) location.hash = row.dataset.href;
  });

  let debounce = null;
  view.addEventListener("input", (ev) => {
    const form = ev.target.closest("form[data-form]");
    if (!form || form.dataset.form.startsWith("user-") || ev.target.tagName !== "INPUT" || ev.target.type === "checkbox") return;
    clearTimeout(debounce);
    debounce = setTimeout(() => updateQuery({ [ev.target.name]: ev.target.value.trim() }), 300);
  });

  view.addEventListener("change", (ev) => {
    const el = ev.target;
    if (el.dataset.toggle === "boxes") return updateQuery({ boxes: el.checked ? null : "0" });
    if (el.dataset.select === "reading") return updateQuery({ r: el.value, img: null });
    if (el.dataset.select === "trend-point") return go("tendencias", el.value, Object.fromEntries(parseHash().query.entries()));
    if (el.dataset.select === "trend-limit") return updateQuery({ n: el.value });
    if (el.dataset.select === "catalog-plan") return go("catalogo", el.value, {});
    if (el.dataset.select === "catalog-point") return updateQuery({ point: el.value || "-" });
    const f = el.closest("form[data-form]");
    if (el.tagName === "SELECT" && f && !f.dataset.form.startsWith("user-")) return updateQuery({ [el.name]: el.value });
  });

  view.addEventListener("submit", (ev) => {
    const form = ev.target.closest("form[data-form]");
    if (!form) return;
    ev.preventDefault();
    if (form.dataset.form.startsWith("user-")) submitUserForm(form);
  });

  document.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-action=theme]")) { toggleTheme(); return; }
    const userBtn = ev.target.closest("#userBtn");
    const menu = $("#userMenu");
    if (userBtn) { menu.hidden = !menu.hidden; userBtn.setAttribute("aria-expanded", String(!menu.hidden)); return; }
    if (!ev.target.closest("#userMenu")) { menu.hidden = true; $("#userBtn").setAttribute("aria-expanded", "false"); }
    if (ev.target.closest("#menuBtn")) {
      const open = document.body.classList.toggle("nav-open");
      $("#menuBtn").setAttribute("aria-expanded", String(open));
      return;
    }
    if (ev.target.closest("#nav .link")) { document.body.classList.remove("nav-open"); }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") { $("#userMenu").hidden = true; document.body.classList.remove("nav-open"); }
  });

  $("#logoutBtn").addEventListener("click", async () => {
    try { await fetch("/api/auth/logout", { method: "POST" }); } catch { /* igual se cierra */ }
    state.user = null; state.summary = null;
    $("#userMenu").hidden = true;
    showLogin();
  });

  $("#loginForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const err = $("#loginErr");
    err.textContent = "";
    $("#loginBtn").disabled = true;
    try {
      const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: form.username.value.trim(), password: form.password.value }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "No se pudo iniciar sesión");
      form.password.value = "";
      await initApp(data);
    } catch (e) {
      err.textContent = e.message;
    } finally {
      $("#loginBtn").disabled = false;
    }
  });

  window.addEventListener("hashchange", route);

  (async () => {
    try {
      const res = await fetch("/api/auth/me");
      if (res.ok) { const me = await res.json(); await initApp(me); return; }
    } catch { /* sin red: mostrar acceso */ }
    showLogin();
  })();
})();
