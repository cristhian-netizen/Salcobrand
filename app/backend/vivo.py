"""Cámara en vivo (prototipo, 8-nov-2026): /vivo/<código> abre la cámara, el DETECTOR corre en el teléfono (onnxruntime-web)
y dibuja un recuadro sobre cada producto mientras se apunta; avisa si la foto sale movida, oscura o torcida y puede
disparar sola. Al tomar la foto la sube como una captura más (captures.py) y pide al motor completo, en el servidor, los
nombres: la foto vuelve con una etiqueta sobre cada producto.

- Usa el MISMO código de enlace que /captura/<código> (mismos límites); no cambia esa página.
- Los recursos pesados (modelo ONNX ~80 MB, onnxruntime-web 1.20.1) viven en storage `vivo/…` (S3 uploads/vivo/…), se
  sirven desde este dominio con caché inmutable y la página va con COOP/COEP para que el WASM use varios hilos.
- El análisis de una foto en vivo va a un punto aparte por local (VIVO-<local>, sin planograma = modo catálogo) para no
  mezclar pruebas con las lecturas reales, y trabaja sobre una COPIA de la captura (el motor borra las fotos de los
  análisis fallidos; la captura original nunca se toca).
- /vivo/<código>/medicion guarda las mediciones del teléfono (cuadros por segundo, motor usado, tiempos) en
  storage `vivo/mediciones/<fecha>/` para decidir con números.
"""
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

import api_jobs
import captures
import core
import db
import storage

router = APIRouter()
PAGE = Path(__file__).resolve().parent.parent / "frontend" / "vivo.html"
MODEL_VERSION = os.environ.get("NEURAVISION_WEB_DETECTOR", "v5-20261107")
ORT_VERSION = "1.20.1"
LEER_MAX_DIA = int(os.environ.get("VIVO_LEER_MAX_DIA", "150"))   # análisis por local y día
ISOLATION = {"Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Embedder-Policy": "require-corp"}
_ASSET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_ORT_FILES = {"ort.webgpu.min.js", "ort.wasm.min.js", "ort-wasm-simd-threaded.jsep.mjs", "ort-wasm-simd-threaded.jsep.wasm",
              "ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.wasm"}
_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm", ".onnx": "application/octet-stream",
          ".json": "application/json"}
_cache: dict = {}
_cache_lock = threading.Lock()
_CACHE_MAX_BYTES = 400 * 1024 * 1024


def _link_or_404(token: str) -> dict:
    link = captures.get_link(token)
    if not captures._valid(link):
        raise HTTPException(status_code=404, detail="Enlace no válido")
    return link


def _asset(rel: str) -> bytes:
    """Lee un recurso de storage con caché en memoria (los archivos son inmutables por versión)."""
    with _cache_lock:
        if rel in _cache:
            return _cache[rel]
    try:
        data = storage.get(rel)
    except ValueError:
        data = None
    if data is None:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")
    with _cache_lock:
        if sum(len(v) for v in _cache.values()) + len(data) <= _CACHE_MAX_BYTES:
            _cache[rel] = data
    return data


def _asset_response(rel: str) -> Response:
    data = _asset(rel)
    ext = "." + rel.rsplit(".", 1)[-1].lower()
    return Response(content=data, media_type=_TYPES.get(ext, "application/octet-stream"),
                    headers={"Cache-Control": "public, max-age=31536000, immutable", "Cross-Origin-Resource-Policy": "same-origin",
                             **ISOLATION})          # los hilos del WASM son workers: su script también debe venir aislado


# ---------------------------------------------------------------- página y recursos
@router.get("/vivo/{token}", response_class=HTMLResponse, include_in_schema=False)
def vivo_page(token: str):
    if not captures._valid(captures.get_link(token)):
        return HTMLResponse("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                            "<body style='font-family:Arial;padding:24px'><h2>Enlace no válido</h2>"
                            "<p>Este enlace no existe o ya no está activo.</p></body>", status_code=404)
    html = PAGE.read_text(encoding="utf-8").replace("__MODELO__", MODEL_VERSION).replace("__ORT__", ORT_VERSION)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache", "X-Robots-Tag": "noindex", **ISOLATION})


@router.get("/vivo-recursos/ort/{version}/{name}", include_in_schema=False)
def vivo_ort(version: str, name: str):
    if version != ORT_VERSION or name not in _ORT_FILES:
        raise HTTPException(status_code=404, detail="Recurso no encontrado")
    return _asset_response(f"vivo/ort/{version}/{name}")


@router.get("/vivo-recursos/modelo/{version}/{name}", include_in_schema=False)
def vivo_modelo(version: str, name: str):
    if not _ASSET_RE.match(version) or not re.match(r"^detector_\d{3,4}(_[a-z0-9]+)?\.onnx$", name):
        raise HTTPException(status_code=404, detail="Recurso no encontrado")
    return _asset_response(f"vivo/modelos/{version}/{name}")


# ---------------------------------------------------------------- mediciones del teléfono
@router.post("/vivo/{token}/medicion", include_in_schema=False)
async def vivo_medicion(token: str, request: Request):
    link = _link_or_404(token)
    if not captures._ip_ok(captures._client_ip(request)):
        raise HTTPException(status_code=429, detail="Demasiadas solicitudes")
    raw = await request.body()
    if len(raw) > 16 * 1024:
        raise HTTPException(status_code=413, detail="Medición demasiado grande")
    try:
        data = json.loads(raw or b"{}")
        assert isinstance(data, dict)
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")
    now = datetime.now(timezone.utc)
    data.update({"local": link["store_id"], "recibido": now.isoformat(), "ua_servidor": (request.headers.get("user-agent") or "")[:300]})
    storage.put(f"vivo/mediciones/{now:%Y-%m-%d}/{now:%H%M%S}-{uuid.uuid4().hex[:8]}.json",
                json.dumps(data, ensure_ascii=False).encode(), "application/json")
    return {"ok": True}


# ---------------------------------------------------------------- nombres del motor completo para una foto tomada en vivo
class LeerPayload(BaseModel):
    capture_id: int


def demo_point_for(store_id: str, label: str) -> str:
    """Punto aparte por local para las fotos en vivo (sin planograma: el motor usa el modo catálogo). Sin store_id para
    que no aparezca en la app de la tienda; se ve en el panel de supervisión."""
    pid = "VIVO-" + captures._slug(store_id).upper()
    if not db.get_point(pid):
        try:
            db.create_point(pid, f"Cámara en vivo (prueba) · {label or store_id}")
        except Exception:
            if not db.get_point(pid):   # otra solicitud lo creó al mismo tiempo
                raise
    return pid


def _leidas_hoy(point_id: str) -> int:
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with db.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM api_jobs WHERE point_id = ? AND created_at >= ?", (point_id, day)).fetchone()["n"]


@router.post("/captura/{token}/leer", include_in_schema=False)
def vivo_leer(token: str, body: LeerPayload, request: Request):
    link = _link_or_404(token)
    if not captures._ip_ok(captures._client_ip(request)):
        raise HTTPException(status_code=429, detail="Demasiadas solicitudes seguidas. Espera un minuto.")
    with db.get_conn() as conn:
        cap = conn.execute("SELECT * FROM captures WHERE id = ? AND token = ?", (int(body.capture_id), token)).fetchone()
    if not cap:
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    pid = demo_point_for(link["store_id"], link.get("label"))
    if _leidas_hoy(pid) >= LEER_MAX_DIA:
        raise HTTPException(status_code=429, detail="Se alcanzó el máximo de análisis de hoy para este local.")
    data = storage.get(cap["rel_path"])
    if data is None:
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    copia = core.save_upload(pid, data, storage.content_type_for(cap["rel_path"]))
    job = api_jobs.enqueue(api_jobs.APP_CLIENT, pid, {"image_paths": [copia], "linear_meters": None, "planogram_id": None,
                                                      "user": f"enlace:{token}", "via": "vivo", "token": token,
                                                      "capture_id": int(body.capture_id)})
    return {"job_id": job["job_id"], "estado": job["status"]}


def resultado(reading: dict) -> dict:
    """Recuadros con nombre para dibujar sobre la foto: seguro = el motor lo nombra sin pedir revisión."""
    eng = reading.get("engine") or {}
    imgs = eng.get("images") or []
    if not imgs:
        return {"ancho": None, "alto": None, "items": []}
    im = imgs[0]
    items = []
    for it in im.get("items") or []:
        st = it.get("status")
        items.append({"box": it.get("box"), "nombre": it.get("title") if st == "match" else None,
                      "seguro": st == "match" and not it.get("needs_review"), "estado": st,
                      "confianza": round(float(it.get("confidence") or 0), 2)})
    W, H = (im.get("size") or [None, None])[:2]
    return {"ancho": W, "alto": H, "items": items}


@router.get("/captura/{token}/leer/{job_id}", include_in_schema=False)
def vivo_leer_estado(token: str, job_id: str):
    _link_or_404(token)
    j = db.get_job(job_id)
    if not j or (j.get("payload") or {}).get("token") != token:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")
    if j["status"] in ("queued", "running"):
        return {"estado": j["status"]}
    if j["status"] == "failed":
        return {"estado": "fallido", "detalle": (j.get("error") or "No se pudo analizar la foto")[:200]}
    reading = db.get_reading(j["reading_id"]) if j.get("reading_id") else None
    if not reading:
        return {"estado": "fallido", "detalle": "La lectura no está disponible"}
    return {"estado": "listo", "lectura": reading["id"], "ms": j.get("engine_ms"), **resultado(reading)}
