"""Captura de fotos por enlace (8-nov-2026): una URL sin usuario ni clave para que el personal de un local tome fotos de
la góndola desde el teléfono. Solo guarda fotos (S3 + tabla `captures`): no analiza ni muestra datos del sistema.

- El enlace lleva un código difícil de adivinar: /captura/<local>-<aleatorio>. Se crea y se desactiva desde la
  administración (/api/admin/capture-links); puede vencer.
- Enlace POR LOCAL (store_id fijo) o UNIVERSAL (store_id "*" y `locales_json` = [{store_id, label}]): en el universal la
  persona elige su local al abrir y cada foto lleva el local elegido, que debe estar en la lista del enlace o ser un
  "Otro local" escrito a mano (LOCAL-<número>): así un solo enlace sirve para pedir fotos a cualquier local.
- Tipo de foto: "gondola" (franja 1..8 o "completa", guiado) o "producto" (alta del local: una foto por percha con el
  producto de frente y su etiqueta de precio; franja opcional).
- La página (frontend/captura.html + static/captura.js/css) guarda cada foto en IndexedDB y la borra del teléfono SOLO
  cuando el servidor responde 200; `cliente_id` (uuid por foto) evita duplicados si una respuesta se pierde.
- Límites: solo imágenes, ≤ 25 MB por foto (se guarda como JPEG ≤ 3000 px), máximo por día por enlace (600 por defecto)
  y por IP (40 por minuto).
- Las fotos quedan en storage `capturas/<local>/<fecha>/<uuid>.jpg` y en la tabla `captures`.
"""
import json
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

import core
import db
import storage

router = APIRouter()
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
PAGE = FRONTEND / "captura.html"
SW = FRONTEND / "captura-sw.js"
VERSION = "2026.11.19-sb3"          # cambiar junto con VERSION de captura-sw.js al publicar CSS/JS nuevos
MAX_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_PER_DAY = 600
IP_PER_MINUTE = 40
UNIVERSAL = "*"
FRANJAS = {"", "completa", "1", "2", "3", "4", "5", "6", "7", "8"}
TIPOS = {"gondola", "producto"}
_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{3,80}$")
OTRO_LOCAL = re.compile(r"^LOCAL-([1-9][0-9]{0,3})$")  # universal: "Otro local" escrito a mano (número de local, 1-9999)
_ip_hits = defaultdict(deque)
_ip_lock = threading.Lock()

# Las tablas capture_links y captures están en db.SCHEMA (SQLite) y pgcompat.SCHEMA (Postgres).


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _day_start() -> str:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:24] or "local"


# ---------------------------------------------------------------- enlaces
def _link_dict(row) -> dict:
    d = dict(row)
    raw = d.pop("locales_json", None)
    try:
        locales = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        locales = None
    d["universal"] = d.get("store_id") == UNIVERSAL
    d["locales"] = locales if d["universal"] else [{"store_id": d["store_id"], "label": d.get("label") or d["store_id"]}]
    return d


def _limpiar_locales(locales) -> list:
    out, vistos = [], set()
    for l in locales or []:
        sid = str((l or {}).get("store_id") or "").strip()
        if not sid or sid == UNIVERSAL or sid in vistos:
            continue
        vistos.add(sid)
        out.append({"store_id": sid, "label": str(l.get("label") or sid).strip()[:60] or sid})
    return out


def locales_por_defecto() -> list:
    """Locales de los enlaces por local activos (para crear el universal sin escribir la lista)."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT store_id, label FROM capture_links WHERE active = 1 AND store_id != ? ORDER BY label",
                            (UNIVERSAL,)).fetchall()
    return _limpiar_locales([{"store_id": r["store_id"], "label": r["label"]} for r in rows])


def create_link(store_id: str, label: str = None, days: Optional[int] = None, max_per_day: Optional[int] = None,
                created_by: str = None, locales: Optional[list] = None) -> dict:
    """`locales` (lista de {store_id, label}) crea un enlace UNIVERSAL: la persona elige el local al abrir."""
    universal = locales is not None
    if universal:
        locales = _limpiar_locales(locales)
        if not locales:
            raise ValueError("El enlace universal necesita al menos un local")
        store_id = UNIVERSAL
    base = label or ("salcobrand" if universal else store_id)
    token = f"{_slug(base)}-{secrets.token_urlsafe(8).replace('_', 'x').replace('-', 'y').lower()}"
    expires = (datetime.now(timezone.utc) + timedelta(days=int(days))).isoformat() if days else None
    with db.get_conn() as conn:
        conn.execute("INSERT INTO capture_links (token, store_id, label, created_at, created_by, expires_at, active, max_per_day, locales_json) "
                     "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                     (token, store_id, label or ("Salcobrand" if universal else store_id), now_iso(), created_by, expires,
                      int(max_per_day or DEFAULT_MAX_PER_DAY), json.dumps(locales, ensure_ascii=False) if universal else None))
    return get_link(token)


def get_link(token: str) -> Optional[dict]:
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM capture_links WHERE token = ?", (token,)).fetchone()
    return _link_dict(row) if row else None


def list_links() -> list:
    with db.get_conn() as conn:
        rows = conn.execute("SELECT l.*, (SELECT COUNT(*) FROM captures c WHERE c.token = l.token) AS fotos, "
                            "(SELECT MAX(created_at) FROM captures c WHERE c.token = l.token) AS ultima "
                            "FROM capture_links l ORDER BY l.created_at DESC").fetchall()
    return [_link_dict(r) for r in rows]


def set_active(token: str, active: bool) -> Optional[dict]:
    with db.get_conn() as conn:
        conn.execute("UPDATE capture_links SET active = ? WHERE token = ?", (1 if active else 0, token))
    return get_link(token)


def set_local(token: str, store_id: str, label: str = None) -> Optional[dict]:
    """Corrige el local de un enlace por local y mueve sus fotos (captures.store_id) a ese local. Las fotos no se mueven
    en storage: la ruta queda donde se guardó (capturas/<local anterior>/…) y la fila apunta a ella."""
    link = get_link(token)
    if not link:
        return None
    if link["universal"]:
        raise ValueError("El enlace universal no tiene un local fijo")
    store_id = (store_id or "").strip()
    if not store_id or store_id == UNIVERSAL:
        raise ValueError("Falta el local")
    with db.get_conn() as conn:
        conn.execute("UPDATE capture_links SET store_id = ?, label = ? WHERE token = ?", (store_id, (label or store_id).strip(), token))
        cur = conn.execute("UPDATE captures SET store_id = ? WHERE token = ?", (store_id, token))
        moved = cur.rowcount
    return {**get_link(token), "fotos_movidas": moved}


def _valid(link: Optional[dict]) -> bool:
    if not link or not int(link.get("active") or 0):
        return False
    exp = link.get("expires_at")
    return not exp or exp > now_iso()


def list_captures(store_id: str = None, token: str = None, limit: int = 500) -> list:
    q, args = "SELECT * FROM captures", []
    conds = []
    if store_id:
        conds.append("store_id = ?"); args.append(store_id)
    if token:
        conds.append("token = ?"); args.append(token)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY id DESC LIMIT ?"; args.append(int(limit))
    with db.get_conn() as conn:
        rows = conn.execute(q, tuple(args)).fetchall()
    return [{**dict(r), "url": f"/uploads/{r['rel_path']}"} for r in rows]


def _count(token: str, since_iso: str = None) -> int:
    with db.get_conn() as conn:
        if since_iso:
            return conn.execute("SELECT COUNT(*) AS n FROM captures WHERE token = ? AND created_at >= ?", (token, since_iso)).fetchone()["n"]
        return conn.execute("SELECT COUNT(*) AS n FROM captures WHERE token = ?", (token,)).fetchone()["n"]


def _hoy_por_local(token: str) -> dict:
    """{store_id: {"gondola": n, "producto": n}} de hoy (UTC) para este enlace."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT store_id, COALESCE(tipo, 'gondola') AS tipo, COUNT(*) AS n FROM captures "
                            "WHERE token = ? AND created_at >= ? GROUP BY store_id, COALESCE(tipo, 'gondola')",
                            (token, _day_start())).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["store_id"], {"gondola": 0, "producto": 0})[r["tipo"] if r["tipo"] in TIPOS else "gondola"] = r["n"]
    return out


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")) or "?"


def _ip_ok(ip: str) -> bool:
    now = time.time()
    with _ip_lock:
        q = _ip_hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= IP_PER_MINUTE:
            return False
        q.append(now)
        return True


# ---------------------------------------------------------------- páginas y subida públicas
@router.get("/captura/sw.js", include_in_schema=False)
def capture_sw():
    """Service worker de la página de captura (alcance /captura/): abre sin señal y guarda la página de cada enlace."""
    return Response(SW.read_text(encoding="utf-8"), media_type="text/javascript", headers={"Cache-Control": "no-cache"})


def _inactive_html() -> str:
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            "<body style='font-family:Arial;padding:24px'><h2>Enlace no válido</h2>"
            "<p>Este enlace para tomar fotos no existe o ya no está activo.</p></body>")


@router.get("/captura/{token}", response_class=HTMLResponse, include_in_schema=False)
def capture_page(token: str):
    link = get_link(token) if _TOKEN_RE.match(token or "") else None
    if not link:
        return HTMLResponse(_inactive_html(), status_code=404)
    html = PAGE.read_text(encoding="utf-8").replace("__VERSION__", VERSION)
    # enlace desactivado o vencido: misma página (muestra "ya no está activo" y las fotos que el teléfono tenga guardadas)
    return HTMLResponse(html, status_code=200 if _valid(link) else 404, headers={"Cache-Control": "no-cache", "X-Robots-Tag": "noindex"})


@router.get("/captura/{token}/manifest.webmanifest", include_in_schema=False)
def capture_manifest(token: str):
    link = get_link(token)
    if not _valid(link):
        raise HTTPException(status_code=404, detail="Enlace no válido")
    nombre = "Fotos Salcobrand" if link["universal"] else f"Fotos {link.get('label') or link['store_id']}"
    return JSONResponse({"name": nombre, "short_name": "Fotos SB", "start_url": f"/captura/{token}", "scope": "/captura/",
                         "display": "standalone", "background_color": "#ffffff", "theme_color": "#0074c8",
                         "icons": [{"src": "/static/assets/pwa/icon-192.png", "sizes": "192x192", "type": "image/png"},
                                   {"src": "/static/assets/pwa/icon-512.png", "sizes": "512x512", "type": "image/png"}]},
                        media_type="application/manifest+json")


@router.get("/captura/{token}/estado", include_in_schema=False)
def capture_state(token: str):
    link = get_link(token)
    if not _valid(link):
        raise HTTPException(status_code=404, detail="Enlace no válido")
    por_local = _hoy_por_local(token)
    return {"label": link["label"], "universal": link["universal"], "locales": link["locales"], "otro_local": link["universal"],
            "local": None if link["universal"] else link["store_id"],
            "hoy": _count(token, _day_start()), "total": _count(token), "hoy_por_local": por_local,
            "franjas": sorted(FRANJAS - {""}, key=lambda f: (f == "completa", f)), "version": VERSION}


@router.post("/captura/{token}/foto", include_in_schema=False)
async def capture_upload(token: str, request: Request, foto: UploadFile = File(...), franja: str = Form(default=""),
                         tipo: str = Form(default=""), local: str = Form(default=""), cliente_id: str = Form(default=""),
                         tomada_en: str = Form(default=""), origen: str = Form(default="")):
    link = get_link(token)
    if not _valid(link):
        raise HTTPException(status_code=404, detail="Enlace no válido")
    if not _ip_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Demasiadas fotos seguidas. Espera un minuto.", headers={"Retry-After": "30"})
    # local: el del enlace, o el elegido en el enlace universal (debe estar en su lista)
    if link["universal"]:
        local = (local or "").strip()
        if local not in {l["store_id"] for l in link["locales"]}:
            m = OTRO_LOCAL.match(local.upper())
            if not m:
                raise HTTPException(status_code=400, detail="Elige tu local en la lista o escribe su número antes de tomar fotos.")
            local = f"LOCAL-{m.group(1)}"
        store_id = local
    else:
        store_id = link["store_id"]
    cliente_id = re.sub(r"[^A-Za-z0-9_-]", "", cliente_id or "")[:64]
    if cliente_id:                                   # reintento de una foto que ya llegó (se perdió la respuesta)
        with db.get_conn() as conn:
            prev = conn.execute("SELECT id FROM captures WHERE token = ? AND cliente_id = ?", (token, cliente_id)).fetchone()
        if prev:
            return JSONResponse({"ok": True, "id": prev["id"], "duplicada": True, "hoy": _count(token, _day_start())})
    if _count(token, _day_start()) >= int(link.get("max_per_day") or DEFAULT_MAX_PER_DAY):
        raise HTTPException(status_code=429, detail="Se alcanzó el máximo de fotos de hoy para este enlace.", headers={"Retry-After": "3600"})
    if not core.is_image_upload(foto.content_type):
        raise HTTPException(status_code=400, detail="El archivo no es una imagen")
    raw = await foto.read()
    if not raw:
        raise HTTPException(status_code=400, detail="La foto llegó vacía")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="La foto supera 25 MB")
    data, ctype = core.shrink_for_storage(raw, foto.content_type or "image/jpeg")
    width = height = None
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
    except Exception:
        raise HTTPException(status_code=400, detail="No se pudo leer la imagen")
    franja = (franja or "").strip().lower()
    if franja not in FRANJAS:
        franja = ""
    tipo = (tipo or "").strip().lower()
    if tipo not in TIPOS:
        tipo = "gondola"
    ext = core.EXTENSION_BY_CONTENT_TYPE.get(ctype, "jpg")
    rel = f"capturas/{_slug(store_id)}/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}/{uuid.uuid4().hex}.{ext}"
    storage.put(rel, data, ctype)
    with db.get_conn() as conn:
        cur = conn.execute("INSERT INTO captures (token, store_id, created_at, rel_path, bytes, width, height, franja, device, "
                           "tipo, cliente_id, tomada_en, origen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (token, store_id, now_iso(), rel, len(data), width, height, franja or None,
                            (request.headers.get("user-agent") or "")[:200], tipo, cliente_id or None,
                            (tomada_en or "")[:40] or None, (origen or "")[:24] or None))
        cid = cur.lastrowid
    return JSONResponse({"ok": True, "id": cid, "hoy": _count(token, _day_start()), "ancho": width, "alto": height,
                         "local": store_id, "tipo": tipo})
