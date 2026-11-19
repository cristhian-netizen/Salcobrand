"""Nationwide dataset sweep (local-neura): original phone photos stored VERBATIM, zero analysis.

- The camera file is written byte-for-byte to DATA_DIR/dataset/<category>/<uuid>.<ext> (atomic
  write, extension by content sniff, never by filename): sha256(stored) == sha256(uploaded) always.
  No shrink_for_storage, no EXIF transpose, no re-encode; PIL is only asked for the dimensions and
  a failed HEIC size read stores NULL instead of rejecting the photo.
- Categories are the workspace's Kilby catalogs (kilby_catalog.workspace_catalogs, 60 s cache).
  When Kilby is unreachable the configured catalog is offered as fallback with a Spanish warning,
  so the sweep continues while Kilby is down.
- The dataset/ folder is deliberately NOT in maintenance.WIPE_DIRS and the table is in
  maintenance.KEEP_TABLES: sweeps are valuable raw data and must survive operational wipes.
- Grid thumbnails (`?w=`) and HTTP caching reuse image_cache like every other authenticated image;
  the /file endpoint always serves the original bytes when `w` is absent.
"""
import io
import os
import re
import shutil
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

import db
import image_cache
from infrastructure import _audit

try:  # HEIC dimensions and grid thumbnails; the stored bytes are never re-encoded
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    pass

MAX_FILES = 12
MAX_BYTES_EACH = 40 * 1024 * 1024
MIN_FREE_BYTES = 500 * 1024 * 1024
SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
# ISO-BMFF brands of the HEIC/HEIF family (iPhone writes heic/heix; mif1/msf1 are generic HEIF).
HEIC_BRANDS = {b"heic": "image/heic", b"heix": "image/heic", b"hevc": "image/heic", b"hevx": "image/heic",
               b"heim": "image/heic", b"heis": "image/heic", b"hevm": "image/heic", b"hevs": "image/heic",
               b"mif1": "image/heif", b"msf1": "image/heif"}
EXTENSION = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic", "image/heif": "heif"}


def dataset_dir():
    return db.DATA_DIR / "dataset"


def sniff(data: bytes) -> Optional[str]:
    """Media type by magic bytes (JPEG/PNG/WebP/HEIC-HEIF) or None. The client's declared
    content type and filename are never trusted."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return HEIC_BRANDS.get(data[8:12])
    return None


def dimensions(data: bytes):
    """(width, height) read without re-encoding anything; (None, None) when PIL cannot open the
    bytes (e.g. an HEIC variant pillow-heif does not decode) — the photo is stored anyway."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception:
        return None, None


def active_categories():
    """([{slug, name}], warning) — the workspace's Kilby catalogs (60 s cache in kilby_catalog).
    Unreachable Kilby or missing key: the configured catalog as fallback plus a Spanish warning."""
    import kilby_catalog
    import kilby_neuravision as kn

    try:
        with kilby_catalog.client() as kilby:
            catalogs = kilby_catalog.workspace_catalogs(kilby)
        return [{"slug": c.get("slug"), "name": c.get("name") or c.get("slug")} for c in catalogs if c.get("slug")], None
    except (kn.NeuravisionError, ValueError, LookupError) as exc:
        import integrations_service

        configured = integrations_service.value(kilby_catalog.INTEGRATION, "catalog")
        warning = ("No se pudo consultar los catálogos de Kilby (" + (getattr(exc, "message_es", None) or str(exc)) +
                   ") Se usa el catálogo configurado mientras tanto." if configured else
                   "No se pudo consultar los catálogos de Kilby y no hay un catálogo configurado en Administración → APIs. " +
                   "Inténtalo nuevamente en unos minutos.")
        return ([{"slug": configured, "name": configured}] if configured else []), warning


def _counts(conn):
    """{category: {count, bytes}} of everything stored."""
    rows = conn.execute("SELECT category, COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS total "
                        "FROM management_dataset_images GROUP BY category").fetchall()
    # int(): under Postgres SUM() comes back as Decimal, which json rejects (SQLite returns int).
    return {row["category"]: {"count": int(row["n"]), "bytes": int(row["total"])} for row in rows}


def _serialize(row) -> dict:
    return {"id": row["id"], "category": row["category"], "store_id": row["store_id"], "bytes": row["bytes"],
            "mime": row["mime"], "width": row["width"], "height": row["height"], "created_by": row["created_by"],
            "created_at": row["created_at"], "url": f"/api/admin/dataset/images/{row['id']}/file"}


def _require_free_disk():
    """507 before writing anything when the service disk is close to full (the sweep must never
    be the thing that fills the volume and takes the whole app down)."""
    if shutil.disk_usage(db.DATA_DIR).free < MIN_FREE_BYTES:
        raise HTTPException(507, "Espacio insuficiente en el disco del servicio; amplíalo en Kilby")


def router(require_training, require_training_image):
    api = APIRouter(prefix="/api/admin/dataset", tags=["Dataset de fotos para entrenamiento"])

    @api.get("/categories")
    def categories(user=Depends(require_training)):
        """Active Kilby catalogs plus stored-but-inactive categories, each with {count, bytes}."""
        active, warning = active_categories()
        with db.get_conn() as conn:
            stored = _counts(conn)
        result = [{**c, "active": True, **stored.get(c["slug"], {"count": 0, "bytes": 0})} for c in active]
        known = {c["slug"] for c in active}
        # A catalog removed from Kilby later must never hide the photos already swept for it.
        result += [{"slug": slug, "name": slug, "active": False, **stored[slug]}
                   for slug in sorted(stored) if slug not in known]
        return JSONResponse({"categories": result, "warning": warning}, headers={"Cache-Control": "no-store"})

    @api.post("/images", status_code=201)
    async def upload(category: str = Form(...), store_id: Optional[str] = Form(None),
                     files: List[UploadFile] = File(...), user=Depends(require_training)):
        """1–12 original photos for one category, stored verbatim; no analysis is ever queued."""
        category = (category or "").strip()
        active, _warning = active_categories()
        if category not in {c["slug"] for c in active}:
            raise HTTPException(400, "La categoría no está activa en Kilby. Actualiza la página y elige una de la lista.")
        if not SLUG.fullmatch(category):
            raise HTTPException(400, "La categoría tiene un identificador inválido.")
        if not 1 <= len(files) <= MAX_FILES:
            raise HTTPException(400, f"Sube entre 1 y {MAX_FILES} fotos por solicitud.")
        store_id = (store_id or "").strip() or None
        loaded = []
        for file in files:
            raw = await file.read(MAX_BYTES_EACH + 1)
            if len(raw) > MAX_BYTES_EACH:
                raise HTTPException(413, f"Una foto supera el máximo de {MAX_BYTES_EACH // (1024 * 1024)} MB.")
            mime = sniff(raw)
            if mime is None:
                raise HTTPException(400, "Solo se aceptan fotos JPEG, PNG, WebP o HEIC (el archivo original del teléfono).")
            loaded.append((raw, mime))
        _require_free_disk()
        folder = dataset_dir() / category
        folder.mkdir(parents=True, exist_ok=True)
        created, written = [], []
        try:
            with db.get_conn() as conn:
                if store_id is not None and conn.execute(
                        "SELECT 1 FROM management_stores WHERE LOWER(code) = LOWER(?) AND deleted = 0", (store_id,)).fetchone() is None:
                    raise HTTPException(400, "El PDV indicado no existe. Elige uno de la lista o déjalo en blanco.")
                for raw, mime in loaded:
                    image_id = uuid.uuid4().hex
                    path = folder / f"{image_id}.{EXTENSION[mime]}"
                    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
                    temp.write_bytes(raw)  # atomic: a crash never leaves a half-written original
                    temp.replace(path)
                    written.append(path)
                    width, height = dimensions(raw)
                    rel = str(path.relative_to(db.DATA_DIR))
                    now = db.now_iso()
                    conn.execute("INSERT INTO management_dataset_images (id, category, store_id, path, bytes, mime, "
                                 "width, height, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                 (image_id, category, store_id, rel, len(raw), mime, width, height,
                                  user["username"], now))
                    _audit(conn, user["username"], "dataset.upload", image_id, None,
                           {"category": category, "store_id": store_id, "bytes": len(raw), "mime": mime})
                    created.append({"id": image_id, "category": category, "store_id": store_id, "bytes": len(raw),
                                    "mime": mime, "width": width, "height": height, "created_by": user["username"],
                                    "created_at": now, "url": f"/api/admin/dataset/images/{image_id}/file"})
        except Exception:
            for path in written:  # the transaction rolled back: no orphan files on disk
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
        return {"created": created}

    @api.get("/images")
    def listing(category: str, user=Depends(require_training)):
        with db.get_conn() as conn:
            rows = conn.execute("SELECT * FROM management_dataset_images WHERE category = ? "
                                "ORDER BY created_at DESC, id", (category,)).fetchall()
        return JSONResponse({"images": [_serialize(row) for row in rows]}, headers={"Cache-Control": "no-store"})

    @api.get("/images/{image_id}/file")
    def file(image_id: str, request: Request, w: Optional[int] = None, user=Depends(require_training_image)):
        """The ORIGINAL bytes, exactly as uploaded (ETag + Cache-Control private, immutable: the
        file under an id never changes). `?w=` serves the cached grid thumbnail only."""
        with db.get_conn() as conn:
            row = conn.execute("SELECT path, mime FROM management_dataset_images WHERE id = ?", (image_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Fotografía no encontrada.")
        target = (db.DATA_DIR / row["path"]).resolve()
        if dataset_dir().resolve() not in target.parents:
            raise HTTPException(404, "Fotografía no disponible.")
        try:
            data = target.read_bytes()
        except OSError:
            raise HTTPException(404, "El archivo ya no está en el disco del servicio.")
        data, thumb_type = image_cache.thumbnail("dataset", image_id, data, w)
        return image_cache.response(request, data, thumb_type or row["mime"], immutable=True)

    @api.delete("/images/{image_id}")
    def delete(image_id: str, user=Depends(require_training)):
        with db.get_conn() as conn:
            row = conn.execute("SELECT path, category FROM management_dataset_images WHERE id = ?", (image_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Fotografía no encontrada.")
            conn.execute("DELETE FROM management_dataset_images WHERE id = ?", (image_id,))
            _audit(conn, user["username"], "dataset.delete", image_id, {"category": row["category"], "path": row["path"]}, None)
        target = (db.DATA_DIR / row["path"]).resolve()
        if dataset_dir().resolve() in target.parents:
            try:
                target.unlink()
            except OSError:
                pass
        return {"deleted": image_id}

    return api
