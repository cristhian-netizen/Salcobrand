"""Gemini pre-labeling for the training review (Revisión para entrenamiento).

For each pending review item of a reading, Gemini sees the crop (downscaled to <= 768 px) and the item's candidate
list, and answers strict JSON: {"eleccion": "<sku or exact title from the list or NINGUNO>", "confianza": 0.0-1.0,
"texto_leido": "<text read on the package>"}. The suggestion only pre-selects a candidate on the screen: the label
that is stored is always the human's confirmation, through the same endpoint as before.

Rules:
- The key comes from Administración → APIs (encrypted at rest) or GEMINI_API_KEY. It never appears in logs,
  errors or responses.
- Suggestions are stored once per (reading, image, item): asking again returns the stored rows without calling
  Gemini, so the button is safe to press twice.
- Crops are the same bytes the review screen serves (core.crop_jpeg): Kilby crops come from the disk cache and are
  never re-cropped here.
- At most 4 concurrent calls, ~20 s per call. A 429 from Google respects Retry-After once. Errors are Spanish.

Dependencies: httpx only (PIL just to downscale, with a fallback to the original bytes).
"""
import base64
import io
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

import db
import integrations_service

log = logging.getLogger("gemini_prelabel")

INTEGRATION = "gemini"
MODEL = "gemini-flash-latest"
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
KEY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{20,200}$")
MAX_WORKERS = 4
MAX_CANDIDATES = 12
PROMPT_MAX_SIDE = 768
RETRY_AFTER_CAP_S = 15

MESSAGES_ES = {
    "missing_key": "Falta la clave de Gemini. Un administrador la ingresa en Administración → APIs.",
    "invalid_key": "La clave de Gemini no es válida o fue revocada. Un administrador debe ingresar una nueva en Administración → APIs.",
    "rate_limit": "Se alcanzó el límite de Gemini. Reintenta en unos minutos.",
    "blocked": "Gemini no aceptó esta imagen (filtro de contenido). El recorte queda sin sugerencia.",
    "bad_answer": "Gemini respondió algo que no se pudo interpretar. Reintenta.",
    "unavailable": "Gemini no está disponible en este momento. Reintenta más tarde.",
    "timeout": "Gemini tardó demasiado en responder. Reintenta.",
    "network": "No fue posible conectar con Gemini. Revisa la conexión del servidor.",
}


def message_es(code, default="Gemini no pudo completar la solicitud."):
    return MESSAGES_ES.get(code or "", default)


class GeminiError(Exception):
    """code identifies the Spanish message; the exception text never carries the key."""

    def __init__(self, code, status=None, retry_after=None):
        super().__init__(message_es(code))
        self.code, self.status, self.retry_after = code, status, retry_after

    @property
    def message_es(self):
        return message_es(self.code)


def base_url():
    return (os.environ.get("GEMINI_API_URL", "").strip() or DEFAULT_BASE_URL).rstrip("/")


def api_key():
    return integrations_service.secret(INTEGRATION, "api_key")


def configured():
    fields = {f["name"]: f for f in integrations_service.field_states(INTEGRATION)}
    return bool(fields["api_key"]["configured"])


# ---------------------------------------------------------------------------- transport

def _error_code(response):
    status = response.status_code
    try:
        detail = (response.json().get("error") or {})
    except ValueError:
        detail = {}
    reason = str(detail.get("status") or "")
    if status in (401, 403) or reason == "PERMISSION_DENIED" or "API key" in str(detail.get("message") or ""):
        return "invalid_key"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "unavailable"
    return "bad_answer"


def _retry_after(response):
    value = response.headers.get("Retry-After")
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None


def generate(key, parts, sleep=time.sleep):
    """One generateContent call with temperature 0. Returns the model's text. GeminiError with a Spanish code."""
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    url = f"{base_url()}/models/{MODEL}:generateContent"
    timeout = httpx.Timeout(connect=10, read=20, write=20, pool=10)
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        for attempt in (0, 1):
            try:
                response = client.post(url, json=body, headers={"X-goog-api-key": key})
            except httpx.TimeoutException:
                raise GeminiError("timeout") from None
            except httpx.TransportError:
                raise GeminiError("network") from None
            if response.status_code == 429 and attempt == 0:
                sleep(min(_retry_after(response) or 2.0, RETRY_AFTER_CAP_S))
                continue
            break
    if response.status_code >= 400:
        raise GeminiError(_error_code(response), status=response.status_code)
    try:
        answer = response.json()
        candidates = answer.get("candidates") or []
        if not candidates and (answer.get("promptFeedback") or {}).get("blockReason"):
            raise GeminiError("blocked")
        text = "".join(part.get("text", "") for part in (candidates[0].get("content") or {}).get("parts") or [])
    except (ValueError, IndexError, AttributeError, TypeError):
        raise GeminiError("bad_answer") from None
    if not text.strip():
        raise GeminiError("bad_answer")
    return text


def check_connection(key):
    """Probar conexión: one tiny text-only call ("responde OK"); no image, no crop."""
    if not key:
        return {"ok": False, "code": "missing_key", "message": message_es("missing_key")}
    try:
        generate(key, [{"text": "responde OK"}])
    except GeminiError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message_es}
    return {"ok": True, "code": None, "message": f"Gemini respondió con el modelo {MODEL}."}


# ---------------------------------------------------------------------------- prompt pieces

def _prompt_jpeg(data, max_side=PROMPT_MAX_SIDE):
    """Crop bytes for the prompt: downscaled to <= max_side px JPEG. The stored crop is never modified."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as opened:
            image = opened.convert("RGB")
        if max(image.size) <= max_side and data[:3] == b"\xff\xd8\xff":
            return data
        image.thumbnail((max_side, max_side))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=85)
        return buffer.getvalue()
    except Exception:
        return data  # not decodable here (QA bytes): Gemini judges the original


def _similarity(wanted, candidate):
    wanted, candidate = set(wanted.split()), set(candidate.split())
    return len(wanted & candidate) / len(wanted | candidate) if wanted and candidate else 0.0


def candidates_for(item, titles):
    """The item's own candidates (text_top3 + visual_top3, in order); without any, the top catalog/planogram
    titles closest to what the engine read (match score by normalized token overlap)."""
    from product_matching import norm

    seen, result = set(), []
    for entry in [*(item.get("text_top3") or []), *(item.get("visual_top3") or [])]:
        title = str(entry.get("title") or "").strip() if isinstance(entry, dict) else str(entry or "").strip()
        sku = str(entry.get("sku") or "").strip() if isinstance(entry, dict) else ""
        if title and title.casefold() not in seen:
            seen.add(title.casefold())
            result.append({"title": title, "sku": sku})
    if result:
        return result[:MAX_CANDIDATES]
    observed = norm(str(item.get("product") or "") + " " + str(item.get("ocr") or ""))
    scored = sorted(((_similarity(observed, norm(title)), index, title) for index, title in enumerate(titles or [])),
                    key=lambda row: (-row[0], row[1]))
    return [{"title": title, "sku": ""} for _, _, title in scored[:8] if title]


def build_prompt(candidates):
    lines = [f"{index + 1}. {c['title']}" + (f" (SKU {c['sku']})" if c["sku"] else "")
             for index, c in enumerate(candidates)]
    return ("Eres un verificador de productos de farmacia. La imagen es el recorte de un producto en una góndola.\n"
            "Elige de esta lista el producto que aparece en la imagen:\n" + "\n".join(lines) + "\n\n"
            'Responde SOLO este JSON, sin texto adicional:\n'
            '{"eleccion": "<sku o título exacto de la lista o NINGUNO>", "confianza": 0.0-1.0, '
            '"texto_leido": "<lo que lees en el envase>"}\n'
            'Si el producto no está en la lista o no se distingue, "eleccion" es "NINGUNO".')


def parse_answer(text, candidates):
    """Strict JSON, tolerant of fenced code blocks. Returns (title or None, sku, confidence, texto_leido).
    An eleccion outside the list counts as NINGUNO: the suggestion must be choosable on the screen."""
    cleaned = re.sub(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$", "", str(text or "").strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise GeminiError("bad_answer")
    try:
        data = json.loads(cleaned[start:end + 1])
    except ValueError:
        raise GeminiError("bad_answer") from None
    if not isinstance(data, dict):
        raise GeminiError("bad_answer")
    choice = str(data.get("eleccion") or "").strip()
    confidence = data.get("confianza")
    confidence = max(0.0, min(1.0, float(confidence))) if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None
    read_text = str(data.get("texto_leido") or "").strip()[:300]
    if not choice or choice.casefold() in ("ninguno", "ninguna"):
        return None, "", confidence, read_text
    for candidate in candidates:
        if choice.casefold() in (candidate["title"].casefold(), candidate["sku"].casefold() if candidate["sku"] else ""):
            return candidate["title"], candidate["sku"], confidence, read_text
    return None, "", confidence, read_text


# ---------------------------------------------------------------------------- storage

def stored_for(reading_id):
    """Stored suggestions of a reading, keyed by (image_index, item_index)."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM management_training_suggestions WHERE reading_id = ?", (reading_id,)).fetchall()
    return {(row["image_index"], row["item_index"]): public(row) for row in rows}


def public(row):
    return {"image_index": row["image_index"], "item_index": row["item_index"], "title": row["title"],
            "sku": row["sku"] or "", "confidence": row["confidence"], "ocr_text": row["ocr_text"] or "",
            "model": row["model"], "created_at": row["created_at"]}


def _store(reading_id, image_index, item_index, title, sku, confidence, read_text, actor):
    """First suggestion wins: a concurrent second call never overwrites what the screen already shows."""
    with db.get_conn() as conn:
        conn.execute("INSERT INTO management_training_suggestions (reading_id, image_index, item_index, title, sku, "
                     "confidence, ocr_text, model, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
                     "ON CONFLICT (reading_id, image_index, item_index) DO NOTHING",
                     (reading_id, image_index, item_index, title, sku, confidence, read_text, MODEL, actor, db.now_iso()))


# ---------------------------------------------------------------------------- suggestions for a reading

def suggest(reading, items, titles, actor, limit=None):
    """Suggestions for the reading's pending review items. Stored ones are returned without calling Gemini.
    `limit` caps how many NEW crops go to Gemini in this call (long readings are processed in batches: one
    HTTP request per batch keeps each call seconds long instead of minutes); `restantes` in the answer says
    how many pending crops still have no suggestion after this batch. GeminiError("missing_key") without a
    key; per-item failures are counted and reported in Spanish."""
    import core

    key = api_key()
    if not key:
        raise GeminiError("missing_key")
    counts = {"sugeridos": 0, "sin_sugerencia": 0, "en_cache": 0, "errores": 0}
    stored = stored_for(reading["id"])
    results, errors, work = [], [], []
    skipped_by_limit = 0
    for item in items:
        pair = (item["image_index"], item["item_index"])
        if pair in stored:
            counts["en_cache"] += 1
            results.append({**stored[pair], "cached": True})
            continue
        candidates = candidates_for(item, titles)
        if not candidates:
            counts["sin_sugerencia"] += 1
            continue
        if limit is not None and len(work) >= limit:
            skipped_by_limit += 1
            continue
        try:
            crop = core.crop_jpeg(reading, item["image_index"], item["item_index"])
        except LookupError as exc:
            counts["errores"] += 1
            errors.append(str(exc))
            continue
        work.append((pair, candidates, _prompt_jpeg(crop)))

    def ask(entry):
        pair, candidates, jpeg = entry
        parts = [{"text": build_prompt(candidates)},
                 {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(jpeg).decode()}}]
        return pair, candidates, generate(key, parts)

    if work:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(work))) as pool:
            answers = list(pool.map(lambda entry: _safely(ask, entry), work))
        for outcome in answers:
            if isinstance(outcome, GeminiError):
                counts["errores"] += 1
                errors.append(outcome.message_es)
                continue
            pair, candidates, text = outcome
            try:
                title, sku, confidence, read_text = parse_answer(text, candidates)
            except GeminiError as exc:
                counts["errores"] += 1
                errors.append(exc.message_es)
                continue
            _store(reading["id"], pair[0], pair[1], title, sku, confidence, read_text, actor)
            counts["sugeridos" if title else "sin_sugerencia"] += 1
    fresh = stored_for(reading["id"])
    results += [{**fresh[pair], "cached": False} for pair, _, _ in work if pair in fresh]
    if errors:
        log.warning("gemini: %d de %d recortes fallaron en la lectura %s", counts["errores"], len(items), reading["id"])
    return {"reading_id": reading["id"], **counts, "restantes": skipped_by_limit,
            "error": errors[0] if errors else None, "suggestions": results}


def _safely(fn, entry):
    try:
        return fn(entry)
    except GeminiError as exc:
        return exc
