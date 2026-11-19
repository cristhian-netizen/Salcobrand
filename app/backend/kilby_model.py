"""Neuravision on Kilby as the analysis backend (NEURAVISION_ANALYSIS_BACKEND=kilby).

Same interface as remote_model, so core.analyze_and_store and api_jobs do not change:
- analyze(local_point_id, images, linear_meters, job_id, plan_snapshot) returns the engine-neutral analysis that
  db.add_reading stores (products, categories, total_facings, shelf_levels_detected, empty_space_pct, engine).
- health() feeds /health and /api/capture/status. It never calls Kilby: Kilby probes /health every few seconds.

Rules:
- The key comes from Administración → APIs (encrypted in the database) or NEURAVISION_API_KEY. Without a key the
  analysis does not run. There is no automatic fallback to another engine: that would analyze without billing.
- Kilby meters and bills each analyzed photo. This module sends no usage of its own.
- The Kilby job id is saved in api_jobs.payload as soon as Kilby accepts the photos. A restart or "Recuperar" polls
  that job instead of sending (and paying for) the photos again. The flags remote_submitted / remote_final_failed keep
  the meaning they have for remote_model, so capture_api's recovery works unchanged.
- Planograms are not sent: Kilby reads the photos against the workspace's published catalog. Compliance keeps being
  computed here from the reading's planogram snapshot (db.add_reading), as before.
"""
import hashlib
import io
import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone

import db
import integrations_service
import kilby_neuravision as kn

log = logging.getLogger("kilby_model")

INTEGRATION = "neuravision"
PHOTO_BUDGET = kn.MAX_TOTAL_BYTES - 64 * 1024  # room for the multipart envelope
_HEALTH = {"generation": None, "at": 0.0, "value": None}
HEALTH_TTL_S = 30


def base_url():
    return os.environ.get("KILBY_NEURAVISION_URL", kn.DEFAULT_BASE_URL).strip() or kn.DEFAULT_BASE_URL


def api_key():
    return integrations_service.secret(INTEGRATION, "api_key")


def catalog():
    return integrations_service.value(INTEGRATION, "catalog")


def client(key=None):
    return kn.KilbyNeuravision(key or api_key(), base_url())


def health():
    now = time.monotonic()
    if _HEALTH["generation"] == integrations_service.GENERATION["value"] and now - _HEALTH["at"] < HEALTH_TTL_S:
        return _HEALTH["value"]
    fields = {f["name"]: f for f in integrations_service.field_states(INTEGRATION)}
    key = fields["api_key"]
    if key["configured"]:
        error = None
    elif key["unreadable"]:
        error = "La clave de Neuravision guardada no se puede leer (cambió la clave de cifrado del servidor). Un administrador debe ingresarla de nuevo en Administración → APIs."
    else:
        error = kn.message_es("missing_key")
    value = {"engine": "neuravision", "engine_ready": error is None, "engine_error": error,
             "components": {"mode": "kilby", "catalog": fields["catalog"].get("value") or "único del espacio"},
             "warmup_s": None, "detector": "Neuravision en Kilby", "ocr": "Neuravision en Kilby"}
    _HEALTH.update(generation=integrations_service.GENERATION["value"], at=now, value=value)
    return value


def check_connection(key):
    with client(key) as kilby:
        result = kilby.check()
    return {"ok": result.ok, "code": result.code, "message": result.message_es,
            "key_valid": result.key_valid, "plan_active": result.plan_active}


# ---------------------------------------------------------------------------- helpers

def kilby_id(value):
    """Kilby's store_id / gondola_id: 1-40 letters, digits, dots, dashes or underscores. Longer or other values keep
    a readable prefix plus a hash, so the same local value always maps to the same Kilby value."""
    value = str(value or "").strip()
    if kn.ID_PATTERN.match(value):
        return value
    prefix = re.sub(r"[^A-Za-z0-9._-]", "-", value).strip("-._")[:29] or "id"
    return prefix + "-" + hashlib.sha256(value.encode()).hexdigest()[:10]


def catalog_slug(value):
    """Kilby catalog slug for a planogram category: lowercase, accents stripped, separators to dashes
    ("Salud Sexual" → "salud-sexual", "Desodorantes" → "desodorantes"). None when nothing usable remains."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40].rstrip("-")
    return text if kn.CATALOG_PATTERN.match(text) else None


def _catalog_choice(plan_snapshot, prior):
    """Catalog for one analysis: the planogram's subcategory when it is unambiguous (finer than the category:
    "Cuidado personal" > "Desodorantes" must pick desodorantes), else its category (or the one selected at
    capture), when it maps to a slug other than the configured catalog; else the configured catalog.
    Returns (slug or None, Spanish note)."""
    configured = catalog() or None
    plan = plan_snapshot or {}
    subs = [s for s in (plan.get("subcategories") or []) if s]
    candidates = []
    if plan.get("subcategory"):
        candidates.append(plan.get("subcategory"))
    if len(subs) == 1:
        candidates.append(subs[0])
    candidates.append(plan.get("category"))
    candidates.append((prior.get("infrastructure") or {}).get("category"))
    for candidate in candidates:
        derived = catalog_slug(candidate)
        if derived:
            if derived != configured:
                return derived, f"Análisis con el catálogo «{derived}» de Kilby, según «{candidate}»."
            break
    return configured, ""


def checkpoint(job_id, **values):
    if job_id:
        with db.get_conn() as conn:
            row = conn.execute("SELECT payload_json FROM api_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row:
                payload = json.loads(row["payload_json"] or "{}")
                payload.update(values)
                conn.execute("UPDATE api_jobs SET payload_json = ? WHERE job_id = ?", (json.dumps(payload), job_id))


def _point(local_point_id):
    with db.get_conn() as conn:
        row = conn.execute("SELECT id, name, store_id FROM points WHERE id = ?", (local_point_id,)).fetchone()
    return dict(row) if row else {"id": local_point_id, "name": None, "store_id": None}


def fit_budget(images):
    """Kilby takes 9 MB of photos per analysis. Stored photos are JPEG <= 3000 px (core.shrink_for_storage), usually
    well under the budget; when six of them are not, they are re-encoded with lower JPEG quality at the same pixel
    size, so item positions keep matching the stored photos."""
    photos = [kn.Photo(content, mime or "image/jpeg", f"capture-{index + 1}.{'png' if mime == 'image/png' else 'jpg'}")
              for index, (content, mime) in enumerate(images)]
    if sum(len(p.data) for p in photos) <= PHOTO_BUDGET:
        return photos
    from PIL import Image, ImageOps

    for quality in (80, 70, 60):
        smaller = []
        for index, photo in enumerate(photos):
            with Image.open(io.BytesIO(photo.data)) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                buffer = io.BytesIO()
                image.save(buffer, "JPEG", quality=quality)
            smaller.append(kn.Photo(buffer.getvalue(), "image/jpeg", f"capture-{index + 1}.jpg"))
        if sum(len(p.data) for p in smaller) <= PHOTO_BUDGET:
            return smaller
    raise ValueError("Las fotos superan 9 MB en total incluso comprimidas. Envía menos fotos por góndola.")


def _parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _recover_submitted(kilby, prior, job_id):
    """The connection broke after the photos were sent: find the job Kilby created, without sending them again.
    This app analyzes one capture at a time (ROLE=all, one worker thread), so the first job created after the
    submission with the same number of photos is ours."""
    started = prior.get("kilby_submitted_at") or 0
    candidates = [j for j in kilby.jobs(limit=20)
                  if (_parse_time(j.created_at) or 0) >= started - 5 and j.photos == prior.get("kilby_photos")]
    if not candidates:
        checkpoint(job_id, remote_final_failed=True)  # Kilby never got it: nothing billed, the user can send it again
        raise ValueError("Kilby no registró el envío anterior (no se cobró). Vuelve a cargar las fotos.")
    found = min(candidates, key=lambda j: _parse_time(j.created_at) or 0)
    checkpoint(job_id, kilby_job_id=found.id)
    return kilby.job(found.id)  # the list carries no result


def normalized(job):
    reading = job.result or {}
    products = [dict(p) for p in reading.get("products") or [] if isinstance(p, dict)]
    return {"products": products, "categories": reading.get("categories") or [], "total_facings": reading.get("total_facings"),
            "shelf_levels_detected": reading.get("shelf_levels_detected"), "empty_space_pct": reading.get("empty_space_pct"),
            "notes": "", "is_pharmacy_shelf": True,
            # Kilby does not return item boxes: no overlays for these readings; the review crops are downloaded
            # from Kilby's crops endpoint and cached on disk (crop_jpeg below).
            "engine": {"images": [], "kilby": {"job_id": job.id, "catalog": job.catalog, "engine_ms": job.engine_ms,
                                                "billed": job.billed, "photos": job.photos,
                                                "possible_missing": reading.get("possible_missing") or []}}}


# ---------------------------------------------------------------------------- review crops

def reading_kilby_job(reading):
    """Kilby job id of a reading analyzed on Kilby (no local item boxes), else None."""
    engine = reading.get("engine") if isinstance(reading, dict) else None
    if not isinstance(engine, dict) or engine.get("images"):
        return None
    info = engine.get("kilby") if isinstance(engine.get("kilby"), dict) else {}
    job_id = info.get("job_id")
    return job_id if isinstance(job_id, str) and job_id else None


def crop_jpeg(reading, image_index, item_index):
    """JPEG crop of one detected item, served by Kilby and cached on disk (DATA_DIR/kilby-crops): the crops of a
    finished job never change, so each one is downloaded once and later requests read the file. LookupError (with
    the Spanish reason) when Kilby does not have that crop or cannot be reached."""
    job_id = reading_kilby_job(reading)
    if not job_id or type(image_index) is not int or type(item_index) is not int or image_index < 0 or item_index < 0:
        raise LookupError("Recorte no encontrado")
    path = db.DATA_DIR / "kilby-crops" / re.sub(r"[^A-Za-z0-9._-]", "-", job_id)[:80] / f"{image_index}-{item_index}.jpg"
    try:
        return path.read_bytes()
    except OSError:
        pass
    key = api_key()
    if not key:
        raise LookupError(kn.message_es("missing_key"))
    with client(key) as kilby:
        try:
            data = kilby.crop(job_id, image_index, item_index)
        except kn.NeuravisionError as exc:
            raise LookupError(exc.message_es) from None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + f".{os.getpid()}.tmp")
        temp.write_bytes(data)
        temp.replace(path)  # atomic: a concurrent request never reads a half-written file
    except OSError:
        log.warning("neuravision: el recorte %s no se pudo guardar en disco", path)
    return data


# ---------------------------------------------------------------------------- analysis

def analyze(local_point_id, images, linear_meters=None, job_id=None, plan_snapshot=None):
    key = api_key()
    if not key:
        checkpoint(job_id, remote_final_failed=True)
        raise ValueError(kn.message_es("missing_key"))
    prior = db.get_job(job_id)["payload"] if job_id else {}
    note = prior.get("kilby_catalog_note") or ""
    timeout = int(os.environ.get("KILBY_NEURAVISION_TIMEOUT_S", "600"))
    with client(key) as kilby:
        try:
            if prior.get("kilby_job_id"):
                job = kilby.job(prior["kilby_job_id"])
            elif prior.get("remote_submitted") and not prior.get("remote_final_failed"):
                job = _recover_submitted(kilby, prior, job_id)
            else:
                point = _point(local_point_id)
                photos = fit_budget(images)
                chosen, note = _catalog_choice(plan_snapshot, prior)
                checkpoint(job_id, remote_submitted=True, kilby_submitted_at=time.time(), kilby_photos=len(photos),
                           kilby_catalog_note=note)

                def submit(slug):
                    return kilby.analyze(photos, kilby_id(point.get("store_id") or "PDV-001"), kilby_id(local_point_id),
                                         catalog=slug, name=point.get("name"), linear_meters=linear_meters,
                                         wait=kn.MAX_WAIT_S)
                try:
                    try:
                        job = submit(chosen)
                    except kn.InvalidRequestError as exc:
                        configured = catalog() or None
                        if exc.code != "catalog_not_found" or not chosen or chosen == configured:
                            raise
                        # The category's catalog does not exist (yet) in Kilby: one retry with the configured one.
                        # Kilby answers 404 before counting any photo, so the retry cannot bill twice.
                        note = (f"El catálogo «{chosen}» no existe en Kilby; se usó el catálogo configurado "
                                + (f"«{configured}»." if configured else "(el único del espacio)."))
                        log.warning("neuravision: el catálogo %s no existe en Kilby; se reintenta con %s",
                                    chosen, configured or "el catálogo único del espacio")
                        checkpoint(job_id, kilby_catalog_note=note)
                        job = submit(configured)
                except kn.AmbiguousSubmitError:
                    raise  # remote_submitted stays: "Recuperar" finds the job instead of sending again
                except kn.NeuravisionError:
                    checkpoint(job_id, remote_final_failed=True)  # refused before analysis: not counted
                    raise
                checkpoint(job_id, kilby_job_id=job.id)
            job = kilby.wait_for(job, timeout=timeout)
        except kn.JobTimeoutError:
            raise ValueError(kn.message_es("job_timeout")) from None
        except kn.AmbiguousSubmitError as exc:
            raise ValueError(exc.message_es) from None
        except kn.InvalidRequestError as exc:
            if exc.code == "not_found":
                checkpoint(job_id, remote_final_failed=True)
            raise ValueError(exc.message_es) from None
        except kn.NeuravisionError as exc:
            raise ValueError(exc.message_es) from None
    if job.status == "done" and job.result:
        result = normalized(job)
        if note:
            result["notes"] = note
        return result
    checkpoint(job_id, remote_final_failed=True)
    if job.status == "done":
        raise ValueError("Kilby ya no tiene el resultado de este análisis (se guarda 7 días). Vuelve a cargar las fotos.")
    if job.error_code == "analysis_rejected":
        return {"is_pharmacy_shelf": False, "rejection_reason": job.error_es}
    raise ValueError(job.error_es or kn.message_es("analysis_error"))
