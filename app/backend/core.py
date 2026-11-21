"""Piezas compartidas entre la app (sesión por cookie, main.py) y la API v1 (llave, api_v1.py):
imágenes subidas, motor NeuraVision, recortes, revisión humana e importación de planogramas.

Sin FastAPI: los errores son excepciones propias (ValueError, LookupError, AnalysisRejected, ...) que cada capa
traduce a su formato HTTP. Así la lógica de análisis existe una sola vez.
"""
import io
import os
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

import db
import level_alignment
import storage
from vision import MAX_IMAGES, analyze_shelf  # noqa: F401  (vision.py agrega la raíz del proyecto al sys.path)

def analysis_backend():
    """embedded (engine in this process), remote (NeuraVision engine with user/password) or kilby (Neuravision on Kilby)."""
    value = os.environ.get("NEURAVISION_ANALYSIS_BACKEND", "embedded").strip().lower()
    return value if value in ("embedded", "remote", "kilby") else "embedded"


def remote_enabled():
    """True when the engine runs outside this process: the old remote engine or Neuravision on Kilby."""
    return analysis_backend() != "embedded"


def remote_adapter():
    """The module that analyzes outside this process; both expose analyze() and health() with the same contract."""
    if analysis_backend() == "kilby":
        import kilby_model
        return kilby_model
    import remote_model
    return remote_model


def shared_components():
    from neuravision.engine import shared_components as components
    return components()


def shared_memory():
    if remote_enabled():
        return None
    from neuravision.engine import shared_memory as memory
    return memory()

UPLOADS_DIR = db.DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
}
EXTENSION_TO_CONTENT_TYPE = {v: k for k, v in EXTENSION_BY_CONTENT_TYPE.items()}
# px: las fotos se guardan (y se analizan) con este lado mayor. 3000 desde E1 (recortes a resolución completa): el detector
# sigue trabajando a 1600 px, pero el OCR y el catálogo leen recortes 2-3× más grandes. Antes 2000. La foto guardada es la
# misma que analiza el motor, así que las cajas de la lectura están en sus píxeles (overlays y recortes de revisión).
STORED_MAX_SIDE = int(os.environ.get("NEURAVISION_STORED_MAX_SIDE", "3000"))
STORED_JPEG_QUALITY = 85
STORED_MAX_BYTES = 2_500_000   # por sobre esto (PNG grandes de la API) se vuelve a codificar como JPEG aunque quepa en píxeles


class AnalysisRejected(Exception):
    """El motor no encontró una góndola/productos en las fotos (no es un error del servicio)."""


class ImageTooLarge(ValueError):
    """Una foto (o el conjunto) supera el tamaño máximo aceptado."""


class PlanogramExists(Exception):
    """Ya existe un planograma con ese id (y no se pidió o no se puede reemplazar)."""


# ---------------------------------------------------------------------------
# Fotos subidas
# ---------------------------------------------------------------------------

def shrink_for_storage(image_bytes: bytes, content_type: str, max_side: int = None):
    """Fotos de celular (12 MP, HEIC) se guardan como JPEG de hasta STORED_MAX_SIDE px (3000; q 85): la app ya manda
    JPEG ≤ 3000 px y ≤ 1,4 MB, que se guarda tal cual. Es la imagen que analiza el motor y la que ven los overlays."""
    max_side = max_side or STORED_MAX_SIDE
    try:
        from PIL import Image, ImageOps
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except Exception:
            pass
        original = Image.open(io.BytesIO(image_bytes))
        orientation = original.getexif().get(274, 1)
        img = ImageOps.exif_transpose(original).convert("RGB")
        if orientation == 1 and max(img.size) <= max_side and content_type in ("image/jpeg", "image/png", "image/webp") and len(image_bytes) <= STORED_MAX_BYTES:
            return image_bytes, content_type
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=STORED_JPEG_QUALITY)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, content_type


def save_upload(point_id: str, image_bytes: bytes, content_type: str) -> str:
    """Guarda la foto (S3 si PHOTOS_BUCKET, si no DATA_DIR/uploads) y devuelve la ruta relativa `<punto>/<archivo>`."""
    ext = EXTENSION_BY_CONTENT_TYPE.get(content_type, "jpg")
    rel = f"{point_id}/{uuid.uuid4().hex}.{ext}"
    storage.put(rel, image_bytes, content_type)
    return rel


def delete_uploads(rel_paths: List[str]) -> None:
    storage.delete(rel_paths or [])


def is_image_upload(content_type: Optional[str]) -> bool:
    return bool(content_type) and (content_type.startswith("image/") or content_type == "application/octet-stream")


async def read_image_uploads(images, max_bytes_each: int = None, max_bytes_total: int = None) -> List[Tuple[bytes, str]]:
    """Lee y valida las fotos subidas (1..MAX_IMAGES) y las reduce a ≤ STORED_MAX_SIDE px (3000).
    ValueError (mensaje para el usuario) o ImageTooLarge si supera los límites dados."""
    if not images:
        raise ValueError("Debes subir al menos una foto")
    if len(images) > MAX_IMAGES:
        raise ValueError(f"Máximo {MAX_IMAGES} fotos por lectura")
    loaded = []
    total = 0
    for image in images:
        if not is_image_upload(image.content_type):
            raise ValueError("Todos los archivos deben ser imágenes (JPG, PNG, WebP o HEIC)")
        raw = await image.read(max_bytes_each + 1) if max_bytes_each else await image.read()
        total += len(raw)
        if max_bytes_each and len(raw) > max_bytes_each:
            raise ImageTooLarge(f"Una foto supera el máximo de {max_bytes_each // (1024 * 1024)} MB")
        if max_bytes_total and total > max_bytes_total:
            raise ImageTooLarge(f"El conjunto de fotos supera el máximo de {max_bytes_total // (1024 * 1024)} MB")
        image_bytes, content_type = shrink_for_storage(raw, image.content_type)
        if not image_bytes:
            raise ValueError("Una de las imágenes está vacía")
        from PIL import Image
        try:
            with Image.open(io.BytesIO(image_bytes)) as verified:
                verified.verify()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ValueError("No se pudo abrir una de las fotos. Usa JPG, PNG, WebP o HEIC válidos.") from exc
        loaded.append((image_bytes, content_type))
    return loaded


def load_images_from_disk(image_paths: List[str]) -> List[Tuple[bytes, str]]:
    loaded = []
    for rel_path in image_paths:
        data = storage.get(rel_path)
        if data is None:
            raise FileNotFoundError(f"No se encontró la foto {rel_path}")
        ext = rel_path.rsplit(".", 1)[-1].lower()
        loaded.append((data, EXTENSION_TO_CONTENT_TYPE.get(ext, "image/jpeg")))
    return loaded


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------

ENGINE_STATE = {"ready": False, "error": None, "components": None}


def warm_up_engine():
    """Carga detector/OCR/memoria visual al arrancar (en segundo plano) para que la primera foto no espere."""
    if remote_enabled():
        return
    try:
        d, o, m = shared_components()
        ENGINE_STATE.update({"ready": True, "components": {"detector": getattr(d, "name", "?"), "ocr": getattr(o, "name", "?"),
                                                           "visual_memory": len(m) if m is not None else None}})
        # inferencia de calentamiento: la primera foto real no paga la inicialización perezosa de torch/easyocr
        try:
            from PIL import Image as _Image, ImageDraw as _Draw

            img = _Image.new("RGB", (640, 480), "white")
            dr = _Draw.Draw(img)
            dr.rectangle([60, 60, 300, 420], outline="black", width=4)
            dr.text((80, 100), "PRODUCTO DE PRUEBA 100ml", fill="black")
            buf = io.BytesIO()
            img.save(buf, "JPEG")
            t0 = time.perf_counter()
            analyze_shelf([(buf.getvalue(), "image/jpeg")], None)
            ENGINE_STATE["warmup_s"] = round(time.perf_counter() - t0, 1)
            print(f"[neuravision] calentamiento listo en {ENGINE_STATE['warmup_s']} s", flush=True)
        except Exception as exc:
            print(f"[neuravision] calentamiento falló (no crítico): {exc}", flush=True)
    except Exception as exc:  # el servicio sigue arriba; /health lo informa
        ENGINE_STATE.update({"ready": False, "error": str(exc)[:300]})


def engine_health() -> dict:
    if remote_enabled():
        return remote_adapter().health()
    if os.environ.get("ROLE") == "api" and os.environ.get("JOBS_QUEUE_URL"):
        # la API no carga el motor: lo corren los workers, que escalan desde 0 según la cola
        return {"engine": "neuravision", "engine_ready": True, "engine_error": None,
                "components": {"mode": "workers (cola SQS, 0..N)"}, "warmup_s": None,
                "detector": os.environ.get("NEURAVISION_DETECTOR", "auto"), "ocr": os.environ.get("NEURAVISION_OCR", "auto")}
    return {"engine": "neuravision", "engine_ready": ENGINE_STATE["ready"], "engine_error": ENGINE_STATE["error"],
            "components": ENGINE_STATE["components"], "warmup_s": ENGINE_STATE.get("warmup_s"),
            "detector": os.environ.get("NEURAVISION_DETECTOR", "auto"), "ocr": os.environ.get("NEURAVISION_OCR", "auto")}


def analyze_and_store(point_id: str, loaded: List[Tuple[bytes, str]], linear_meters: float = None,
                      planogram_id: str = None, image_paths: List[str] = None, captured_by: str = None, capture_context: dict = None, plan_snapshot: dict = None, job_id: str = None) -> Tuple[dict, int]:
    """Corre el motor y guarda la lectura. Devuelve (lectura, ms del motor).
    image_paths: rutas ya guardadas (jobs de la API); si es None, guarda las fotos aquí (flujo de la app).
    AnalysisRejected si el motor no reconoce una góndola. Se ejecuta en un hilo (CPU-bound)."""
    planogram_context = db.planogram_context_for_vision(planogram_id, planogram=plan_snapshot) if planogram_id else None
    t0 = time.perf_counter()
    if remote_enabled():
        analysis = remote_adapter().analyze(point_id, loaded, linear_meters, job_id, plan_snapshot)
    else:
        analysis = analyze_shelf(loaded, planogram_context)
    engine_ms = int((time.perf_counter() - t0) * 1000)
    if not analysis.get("is_pharmacy_shelf", True):
        raise AnalysisRejected(analysis.get("rejection_reason") or "La imagen no parece ser una góndola/estante de farmacia.")
    # Un cartel sobre la góndola o la base vacía no son niveles: se alinean los niveles con las bandas del planograma.
    planogram = plan_snapshot if plan_snapshot is not None else db.get_planogram(planogram_id) if planogram_id else None
    try:
        analysis = level_alignment.align(analysis, planogram)
    except Exception as exc:  # el análisis ya se cobró: se guarda sin alinear antes que perderlo
        print(f"[niveles] no se pudo alinear con el planograma: {exc!r}", flush=True)
    if image_paths is None:
        image_paths = [save_upload(point_id, image_bytes, content_type) for image_bytes, content_type in loaded]
    reading = db.add_reading(point_id, analysis, image_paths, linear_meters, planogram_id, captured_by=captured_by, capture_context=capture_context, plan_snapshot=plan_snapshot)
    return reading, engine_ms


# ---------------------------------------------------------------------------
# Recortes y revisión humana (memoria visual)
# ---------------------------------------------------------------------------

def crop_for(reading: dict, image_index: int, item_index: int, margin: float = 0.0):
    """Recorte PIL del ítem detectado (caja en píxeles de la foto guardada, que es la que analizó el motor).
    `margin`: fracción del lado mayor que se agrega por lado (el mismo margen con que el motor recorta para la memoria
    visual). LookupError si no existe el ítem o la foto original."""
    from PIL import Image, ImageOps

    try:
        item = reading["engine"]["images"][image_index]["items"][item_index]
        rel = reading["image_paths"][image_index]
    except (KeyError, IndexError, TypeError):
        raise LookupError("Recorte no encontrado")
    data = storage.get(rel)
    if data is None:
        raise LookupError("Imagen original no disponible")
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    if remote_enabled():
        x1, y1, x2, y2 = map(float, item["box"])
        padding = max(x2 - x1, y2 - y1) * margin
        bounds = (max(0, int(x1-padding)), max(0, int(y1-padding)), min(img.width, int(x2+padding)), min(img.height, int(y2+padding)))
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            raise LookupError("El recorte no tiene coordenadas válidas")
        return img.crop(bounds)
    from neuravision.engine import crop_box
    return crop_box(img, tuple(item["box"]), 1.0, margin)[0]


def crop_jpeg(reading: dict, image_index: int, item_index: int, max_side: int = 480) -> bytes:
    import kilby_model
    if kilby_model.reading_kilby_job(reading):
        # Reading analyzed on Kilby: there are no local boxes; Kilby serves the crop and it is cached on disk.
        return kilby_model.crop_jpeg(reading, image_index, item_index)
    crop = crop_for(reading, image_index, item_index)
    crop.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def planogram_titles(planogram_id: Optional[str], snapshot: dict = None) -> list:
    titles = []
    if planogram_id:
        ctx = db.planogram_context_for_vision(planogram_id, planogram=snapshot)
        if ctx:
            for band, ts in sorted(ctx["titles_by_band"].items(), key=lambda kv: int(kv[0])):
                titles += [t for t in ts if t not in titles]
    return titles


def review_items_for_reading(reading: dict, crop_prefix: str = "/api") -> dict:
    """Ítems dudosos de una lectura (índices, recorte, candidatos) + títulos del planograma para elegir."""
    r = reading
    items = []
    for p in r["products"]:
        if p.get("needs_review") and p.get("item_index") is not None:
            it = None
            try:
                it = r["engine"]["images"][p["image_index"]]["items"][p["item_index"]]
            except (KeyError, IndexError, TypeError):
                pass
            items.append({"image_index": p["image_index"], "item_index": p["item_index"], "level": p["shelf_level"],
                          "position": p["position_index"], "product": p["product"], "status": p["match_status"],
                          "confidence": p.get("confidence"), "ocr": p.get("ocr_text"), "facings": p.get("facings"),
                          "ambiguous": bool(p.get("ambiguous")) if "ambiguous" in p else bool((it or {}).get("ambiguous")),
                          "text_top3": (it or {}).get("text_top3", []), "visual_top3": (it or {}).get("visual_top3", []),
                          "crop_url": f"{crop_prefix}/readings/{r['id']}/crops/{p['image_index']}/{p['item_index']}.jpg"})
    return {"reading_id": r["id"], "point_id": r["point_id"], "created_at": r["created_at"],
            "planogram_id": r["planogram_id"], "titles": planogram_titles(r["planogram_id"], db.reading_planogram_snapshot(r["id"])), "items": items,
            "image_urls": r["image_urls"], "notes": r["notes"]}


def confirm_reading_item(reading: dict, image_index: int, item_index: int, title: Optional[str],
                         facings: Optional[int], source: str) -> dict:
    """Una persona confirma qué SKU es un recorte (o que es ajeno al planograma: título vacío).
    Actualiza la lectura y alimenta la memoria visual. LookupError si el ítem no está en la lectura."""
    r = reading
    title = (title or "").strip()
    products = r["products"]
    target = next((p for p in products if p.get("image_index") == image_index and p.get("item_index") == item_index), None)
    if target is None:
        raise LookupError("Producto no encontrado en la lectura")
    if title:
        target.update({"product": title, "brand": title.replace(".", " ").split()[0] if title else "", "match_status": "confirmed",
                       "confidence": 1.0, "source": "humano", "needs_review": False, "out_of_stock": False})
    else:
        target.update({"match_status": "foreign", "confidence": 1.0, "source": "humano", "needs_review": False})
    if facings is not None and facings >= 0:
        target["facings"] = facings
    for p in products:  # limpiar campos derivados que recalcula _reading_dict
        for field in db.DERIVED_PRODUCT_FIELDS:
            p.pop(field, None)
    memory_size = None
    if title:
        try:
            memory = shared_memory()  # solo la memoria visual: la API no carga detector ni OCR
            if memory is not None:
                from neuravision.engine import crop_margin

                memory.add(crop_for(r, image_index, item_index, margin=crop_margin()), title, r["planogram_id"], source=source)
                memory_size = len(memory)
        except Exception as exc:
            print(f"[revision] no se pudo guardar en memoria visual: {exc}", flush=True)
    updated = db.update_reading_products(r["id"], products)
    return {"ok": True, "memory_size": memory_size, "needs_review": updated["needs_review"], "reading": updated}


# ---------------------------------------------------------------------------
# Planogramas
# ---------------------------------------------------------------------------

def slugify_id(raw: Optional[str], fallback: str = "planograma", maxlen: int = 60) -> str:
    raw = raw or ""
    raw = "".join(c for c in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:maxlen] or fallback


def import_planogram_pdf(data: bytes, filename: Optional[str], planogram_id: Optional[str] = None,
                         name: Optional[str] = None, replace: bool = False, owner_client: Optional[str] = None) -> dict:
    """Crea un planograma a partir del PDF que entrega Salcobrand (texto, no escaneado). Síncrono (correr en hilo).
    ValueError: PDF ilegible/vacío. PlanogramExists: id ya usado (o pertenece a otro origen y no se puede reemplazar)."""
    from neuravision.planogram_pdf import parse_pdf_bytes, to_app_payload

    if not data:
        raise ValueError("PDF vacío")
    try:
        parsed = parse_pdf_bytes(data)
    except Exception as exc:
        raise ValueError(f"No se pudo leer el PDF: {exc}") from exc
    if not parsed["items"]:
        raise ValueError("No se encontraron productos en el PDF (¿es un PDF escaneado?)")
    stem = (filename or "").rsplit(".", 1)[0]
    base = slugify_id(planogram_id or stem or parsed["name"])
    exists, existing_owner = db.planogram_owner(base)
    if exists:
        if not replace:
            raise PlanogramExists(f"Ya existe el planograma '{base}' (marca 'reemplazar' para actualizarlo)")
        if owner_client is not None and existing_owner != owner_client:
            raise PlanogramExists(f"El planograma '{base}' no fue creado con esta llave; usa otro id")
    default_name = stem.replace("_", " ").strip() or parsed["name"]
    payload = to_app_payload(parsed, base, name or default_name, filename)
    payload["owner_client"] = owner_client
    if exists:
        db.replace_planogram(payload)
    else:
        db.create_planogram(payload)
    return {"id": base, "name": payload["name"], "bands": payload["bands"], "module_cm": payload["module_cm"],
            "n_items": len(payload["items"]), "items_preview": [it["title"] for it in payload["items"][:8]]}
