"""Enlaces de captura del dataset (local-neura): a public URL so field people WITHOUT any account
photograph store shelves straight into the dataset sweep (management_dataset_images), verbatim.

- The link fixes everything (category, optional PDV, expiry, photo cap): the public page asks for
  nothing, so a leaked link can only add photos to that one category, never read or choose.
- The token (>=32 url-safe chars from secrets.token_urlsafe) is stored as a sha256 hash — the same
  rule as the Kilby API keys in apis_store — so the database never holds a usable URL. It is shown
  ONCE, on creation, as the full /captura#<token> URL (the fragment keeps it out of server logs).
- Uploads reuse dataset_api's rules by calling it (sniff by magic bytes, 40 MB each, 507 on low
  disk, atomic tmp+replace, NO analysis): the two entry points cannot drift apart. Rows carry
  created_by = "link:<id-prefix>" so every sweep remains attributable to its link.
- The public routes never call Kilby (the category was frozen at creation) and never list
  anything: GET returns only this link's own label and remaining count.
- Validation/revocation mirror capture_links (expires_at/active) with revoked_at kept one-way:
  a revoked token cannot come back because nobody can tell who still holds the old URL.
"""
import hashlib
import os
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import db
import dataset_api
from infrastructure import _audit

DEFAULT_DAYS, MAX_DAYS = 14, 60
DEFAULT_MAX_PHOTOS, MAX_MAX_PHOTOS = 500, 5000
RATE_PER_MINUTE = 30
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,100}$")
INACTIVE_ES = "Este enlace ya no está activo."
_hits = defaultdict(deque)
_hits_lock = threading.Lock()


def token_hash(token: str) -> str:
    """sha256 hex, like apis_store does for API keys: only the hash ever touches the database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def marker(link_id: str) -> str:
    """created_by of every photo swept through a link: short enough to read in the grid,
    long enough (8 hex chars) that two links never collide in practice."""
    return "link:" + link_id[:8]


def _rate_ok(key: str) -> bool:
    """30 requests/min per presented token (even an invalid one, so unknown tokens cannot be
    probed faster than known ones). Same deque-per-key shape as captures._ip_ok."""
    now = time.time()
    with _hits_lock:
        q = _hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_PER_MINUTE:
            return False
        q.append(now)
        return True


def _photos_of(conn, link_id: str) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM management_dataset_images WHERE created_by = ?",
                        (marker(link_id),)).fetchone()["n"]


def _serialize(row, photos: int) -> dict:
    """The admin listing: everything EXCEPT the token (only its hash exists, and even that stays
    on the server so a listing can never be replayed as a URL)."""
    return {"id": row["id"], "category": row["category"], "category_name": row["category_name"] or row["category"],
            "store_id": row["store_id"], "max_photos": row["max_photos"], "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"], "created_by": row["created_by"], "created_at": row["created_at"],
            "photos": int(photos)}


def _find_by_token(token: str):
    with db.get_conn() as conn:
        return conn.execute("SELECT * FROM management_dataset_links WHERE token_hash = ?",
                            (token_hash(token),)).fetchone()


def _public_link(authorization: Optional[str]):
    """Authenticate a public request by its Bearer token: 429 before any lookup, 401 for a
    missing/unknown token (one message, no oracle), 410 once revoked or expired."""
    token = (authorization or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not _rate_ok(token_hash(token)):
        raise HTTPException(429, "Demasiadas solicitudes seguidas. Espera un minuto.", headers={"Retry-After": "30"})
    if not TOKEN_RE.fullmatch(token):
        raise HTTPException(401, "Enlace no válido.")
    row = _find_by_token(token)
    if row is None:
        raise HTTPException(401, "Enlace no válido.")
    if row["revoked_at"] or row["expires_at"] <= db.now_iso():
        raise HTTPException(410, INACTIVE_ES)
    return row


class DatasetLinkPayload(BaseModel):
    category: str
    store_id: Optional[str] = None
    days: Optional[int] = None        # vence en N días (por defecto 14, máximo 60: un enlace nunca es eterno)
    max_photos: Optional[int] = None  # fotos totales del enlace (por defecto 500)


def admin_router(require_training):
    api = APIRouter(prefix="/api/admin/dataset/links", tags=["Enlaces de captura del dataset"])

    @api.post("", status_code=201)
    def create(payload: DatasetLinkPayload, request: Request, user=Depends(require_training)):
        """Creates the link and returns the full URL ONCE: the token is hashed on the spot and
        can never be shown again."""
        category = (payload.category or "").strip()
        active, _warning = dataset_api.active_categories()
        names = {c["slug"]: c["name"] for c in active}
        if category not in names:
            raise HTTPException(400, "La categoría no está activa en Kilby. Actualiza la página y elige una de la lista.")
        if not dataset_api.SLUG.fullmatch(category):
            raise HTTPException(400, "La categoría tiene un identificador inválido.")
        days = DEFAULT_DAYS if payload.days is None else payload.days
        if not 1 <= days <= MAX_DAYS:
            raise HTTPException(400, f"El vencimiento debe ser entre 1 y {MAX_DAYS} días.")
        max_photos = DEFAULT_MAX_PHOTOS if payload.max_photos is None else payload.max_photos
        if not 1 <= max_photos <= MAX_MAX_PHOTOS:
            raise HTTPException(400, f"El máximo de fotos debe ser entre 1 y {MAX_MAX_PHOTOS}.")
        store_id = (payload.store_id or "").strip() or None
        token = secrets.token_urlsafe(32)
        link_id = uuid.uuid4().hex
        now = db.now_iso()
        expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        with db.get_conn() as conn:
            if store_id is not None and conn.execute(
                    "SELECT 1 FROM management_stores WHERE LOWER(code) = LOWER(?) AND deleted = 0", (store_id,)).fetchone() is None:
                raise HTTPException(400, "El PDV indicado no existe. Elige uno de la lista o déjalo en blanco.")
            conn.execute("INSERT INTO management_dataset_links (id, token_hash, category, category_name, store_id, "
                         "max_photos, expires_at, revoked_at, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                         (link_id, token_hash(token), category, names[category], store_id, max_photos, expires,
                          user["username"], now))
            _audit(conn, user["username"], "dataset.link_create", link_id, None,
                   {"category": category, "store_id": store_id, "days": days, "max_photos": max_photos})
            row = conn.execute("SELECT * FROM management_dataset_links WHERE id = ?", (link_id,)).fetchone()
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "salcobrand.neuramorphic.ai"
        # The token travels in the FRAGMENT: browsers never send it in the path, so it stays out of access logs.
        return {**_serialize(row, 0), "url": f"https://{host}/captura#{token}"}

    @api.get("")
    def listing(user=Depends(require_training)):
        with db.get_conn() as conn:
            rows = conn.execute("SELECT l.*, (SELECT COUNT(*) FROM management_dataset_images i "
                                "WHERE i.created_by = 'link:' || SUBSTR(l.id, 1, 8)) AS photos "
                                "FROM management_dataset_links l ORDER BY l.created_at DESC").fetchall()
        return JSONResponse({"links": [_serialize(row, row["photos"]) for row in rows]},
                            headers={"Cache-Control": "no-store"})

    @api.post("/{link_id}/revocar")
    def revoke(link_id: str, user=Depends(require_training)):
        with db.get_conn() as conn:
            row = conn.execute("SELECT * FROM management_dataset_links WHERE id = ?", (link_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Enlace no encontrado.")
            if not row["revoked_at"]:  # revoking twice stays a no-op: the first timestamp is the truth
                conn.execute("UPDATE management_dataset_links SET revoked_at = ? WHERE id = ?", (db.now_iso(), link_id))
                _audit(conn, user["username"], "dataset.link_revoke", link_id,
                       {"category": row["category"], "store_id": row["store_id"]}, None)
            row = conn.execute("SELECT * FROM management_dataset_links WHERE id = ?", (link_id,)).fetchone()
            photos = _photos_of(conn, link_id)
        return _serialize(row, photos)

    return api


def public_router():
    api = APIRouter(prefix="/api/public/dataset", tags=["Captura pública del dataset"])

    @api.get("/link")
    def link_info(authorization: Optional[str] = Header(None)):
        """Only this link's own label and remaining count: the public surface never lists
        categories, photos or anything else worth probing."""
        row = _public_link(authorization)
        with db.get_conn() as conn:
            photos = _photos_of(conn, row["id"])
        return JSONResponse({"category": row["category_name"] or row["category"],
                             "photos_left": max(0, row["max_photos"] - photos)},
                            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})

    @api.post("/images", status_code=201)
    async def upload(files: List[UploadFile] = File(...), authorization: Optional[str] = Header(None)):
        """1–12 original photos, byte-identical, under the link's frozen category. Kilby is never
        consulted here: a sweep in the field must not depend on it, and the category was already
        validated as active when the link was created."""
        link = _public_link(authorization)
        if not 1 <= len(files) <= dataset_api.MAX_FILES:
            raise HTTPException(400, f"Sube entre 1 y {dataset_api.MAX_FILES} fotos por solicitud.")
        loaded = []
        for file in files:
            raw = await file.read(dataset_api.MAX_BYTES_EACH + 1)
            if len(raw) > dataset_api.MAX_BYTES_EACH:
                raise HTTPException(413, f"Una foto supera el máximo de {dataset_api.MAX_BYTES_EACH // (1024 * 1024)} MB.")
            mime = dataset_api.sniff(raw)
            if mime is None:
                raise HTTPException(400, "Solo se aceptan fotos JPEG, PNG, WebP o HEIC (el archivo original del teléfono).")
            loaded.append((raw, mime))
        dataset_api._require_free_disk()
        folder = dataset_api.dataset_dir() / link["category"]
        folder.mkdir(parents=True, exist_ok=True)
        created_by = marker(link["id"])
        written = []
        try:
            with db.get_conn() as conn:
                # Counted inside the transaction so parallel batches cannot stack far past the cap.
                photos = _photos_of(conn, link["id"])
                if photos + len(loaded) > link["max_photos"]:
                    left = max(0, link["max_photos"] - photos)
                    raise HTTPException(409, "Este enlace ya alcanzó el máximo de fotos." if left == 0 else
                                        f"Este enlace solo admite {left} foto(s) más.")
                total = 0
                for raw, mime in loaded:
                    image_id = uuid.uuid4().hex
                    path = folder / f"{image_id}.{dataset_api.EXTENSION[mime]}"
                    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
                    temp.write_bytes(raw)  # atomic: a crash never leaves a half-written original
                    temp.replace(path)
                    written.append(path)
                    width, height = dataset_api.dimensions(raw)
                    conn.execute("INSERT INTO management_dataset_images (id, category, store_id, path, bytes, mime, "
                                 "width, height, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                 (image_id, link["category"], link["store_id"], str(path.relative_to(db.DATA_DIR)),
                                  len(raw), mime, width, height, created_by, db.now_iso()))
                    total += len(raw)
                # ONE event per batch: a 500-photo sweep must not drown the activity log.
                _audit(conn, created_by, "dataset.link_upload", link["id"], None,
                       {"category": link["category"], "store_id": link["store_id"],
                        "count": len(loaded), "bytes": total})
        except Exception:
            for path in written:  # the transaction rolled back: no orphan files on disk
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
        return {"ok": True, "created": len(loaded), "photos_left": max(0, link["max_photos"] - photos - len(loaded))}

    return api
