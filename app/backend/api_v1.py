"""NeuraVision API v1 para Salcobrand (apis-portal/SPEC.md §3–5 y §8): sub-aplicación FastAPI montada en /v1.

- Autenticación: header X-API-Key (o Authorization: Bearer). Detrás de Amazon API Gateway, el gateway manda
  X-NV-Gateway (secreto compartido, env APIS_GATEWAY_SECRET) + X-NV-Key-Id (apiKeyId) y la llave es opcional.
- Errores: JSON {"error": "<código>", "detail": "<texto>", "request_id": "..."}; header X-Request-Id en toda respuesta.
- Telemetría: un evento por llamada (middleware) → api_telemetry (DynamoDB evt#/agg#, log [api-evt], CloudWatch).
- Cuotas: llamadas/min en la dependencia de autenticación; fotos/día antes de encolar el análisis (429 + Retry-After).
- Análisis: jobs en SQLite (api_jobs) procesados por un hilo trabajador; `wait` espera hasta 50 s (25 s vía gateway).
- Alcance: cada cliente ve solo los puntos/lecturas creados con su llave; planogramas propios + los cargados en la app.
"""
import asyncio
import hmac
import os
import re
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

import api_jobs
import api_telemetry
import apis_store
import core
import db

API_VERSION = "1.0"
WAIT_MAX_DIRECT = 50          # s: ruta directa salcobrand.neuramorphic.ai/v1 (ALB corta a los 60 s)
WAIT_MAX_APIGW = 25           # s: vía API Gateway (timeout de integración 29 s)
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_REQUEST_BYTES = 100 * 1024 * 1024
JOB_POLL_S = 0.5
# planogramas cargados en la app (sin dueño) visibles para los clientes de la API (APIS_PLANOGRAMS_SHARED=0 para ocultarlos)
SHARE_UI_PLANOGRAMS = os.environ.get("APIS_PLANOGRAMS_SHARED", "1") != "0"

DESCRIPTION = """API de lectura de góndolas con el motor NeuraVision (sin servicios de IA externos).

Autenticación con el header `X-API-Key` (o `Authorization: Bearer <llave>`). El análisis de fotos se encola como
*job*: `POST /analyze` responde 202 con `job_id`; consulta `GET /jobs/{job_id}` o usa `?wait=<segundos>` para esperar
el resultado en la misma llamada. Guía completa: `docs/API_SALCOBRAND.md`.
"""

# Documentación generada: en producción se apaga (APIS_DOCS_ENABLED=0) y la referencia pública curada vive en
# https://developers.neuramorphic.ai; en local queda disponible en /v1/docs.
_DOCS_ON = os.environ.get("APIS_DOCS_ENABLED", "1") != "0"
app = FastAPI(title="NeuraVision API · Salcobrand", version=API_VERSION, description=DESCRIPTION,
              docs_url="/docs" if _DOCS_ON else None, openapi_url="/openapi.json" if _DOCS_ON else None, redoc_url=None)


# ---------------------------------------------------------------------------
# errores con forma fija
# ---------------------------------------------------------------------------

ERROR_CODES = {400: "bad_request", 401: "invalid_api_key", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
               409: "conflict", 413: "payload_too_large", 415: "unsupported_media_type", 422: "validation_error",
               429: "quota_exceeded", 500: "internal_error", 503: "service_unavailable"}


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str = None, detail: str = "", headers: Dict[str, str] = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code or ERROR_CODES.get(status_code, "error")


def _state(request: Request) -> dict:
    return request.scope.setdefault("state", {})


def error_response(request: Request, status: int, code: str, detail: Any, headers: Dict[str, str] = None) -> JSONResponse:
    st = _state(request)
    if status >= 400:
        st["error"] = f"{code}: {detail}"[:300]
    return JSONResponse({"error": code, "detail": detail, "request_id": st.get("request_id")}, status_code=status, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def _http_exception(request: Request, exc: StarletteHTTPException):
    code = getattr(exc, "code", None) or ERROR_CODES.get(exc.status_code, "error")
    return error_response(request, exc.status_code, code, exc.detail, getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def _validation_exception(request: Request, exc: RequestValidationError):
    parts = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", []) if x != "body")
        parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
    return error_response(request, 422, "validation_error", "; ".join(parts) or "Solicitud inválida")


# ---------------------------------------------------------------------------
# middleware de telemetría (ASGI puro): request_id, latencia, evento por llamada
# ---------------------------------------------------------------------------

def _via_from_headers(headers: Headers) -> str:
    secret = os.environ.get("APIS_GATEWAY_SECRET", "")
    given = headers.get("x-nv-gateway", "")
    return "apigw" if secret and given and hmac.compare_digest(given, secret) else "direct"


# URLs que devuelve la API (poll, crop_url): por API Gateway el cliente no ve el prefijo interno /v1 (la etapa lo aporta),
# así que se devuelven absolutas sobre la URL pública; en la ruta directa quedan relativas a /v1.
PUBLIC_BASE_URL = os.environ.get("APIS_PUBLIC_BASE_URL", "https://salcobrand-api.neuramorphic.ai").rstrip("/")


def _url_prefix(request: Request) -> str:
    st = _state(request)
    via = st.get("via") or _via_from_headers(request.headers)
    st["via"] = via
    return PUBLIC_BASE_URL if via == "apigw" else "/v1"


def _route_label(scope: dict) -> str:
    """`POST /v1/analyze` con los parámetros de ruta colapsados (`/v1/readings/{reading_id}`)."""
    method = scope.get("method", "GET")
    partial = None
    for route in app.router.routes:
        try:
            match, _ = route.matches(scope)
        except Exception:
            continue
        fmt = getattr(route, "path_format", None) or getattr(route, "path", "")
        if match == Match.FULL:
            return f"{method} /v1{fmt}"
        if match == Match.PARTIAL and partial is None:
            partial = fmt
    if partial is not None:
        return f"{method} /v1{partial}"
    path = scope.get("path", "")
    root = scope.get("root_path", "")
    if root and path.startswith(root):
        path = path[len(root):]
    return f"{method} /v1{path}"


def _client_ip(scope: dict, headers: Headers) -> str:
    xff = headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    client = scope.get("client") or ("", 0)
    return client[0] or ""


class TelemetryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        st = scope.setdefault("state", {})
        rid = uuid.uuid4().hex
        st.update({"request_id": rid, "t0": time.perf_counter(), "ts": apis_store.now_iso(), "via": _via_from_headers(headers)})
        status = {"code": None, "started": False}

        async def _send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                status["started"] = True
                MutableHeaders(scope=message).append("X-Request-Id", rid)
            await send(message)

        exc_text = None
        try:
            await self.app(scope, receive, _send)
        except Exception as exc:
            exc_text = f"{type(exc).__name__}: {exc}"[:300]
            print(f"[api-v1] error no controlado ({rid}):", flush=True)
            traceback.print_exc()
            if not status["started"]:
                status["code"] = 500
                resp = JSONResponse({"error": "internal_error", "detail": "Error interno; reintenta o reporta el request_id",
                                     "request_id": rid}, status_code=500, headers={"X-Request-Id": rid})
                await resp(scope, receive, send)
        finally:
            self._record(scope, headers, status["code"] or 500, exc_text)

    @staticmethod
    def _record(scope, headers: Headers, status_code: int, exc_text: Optional[str]):
        try:
            st = scope.get("state", {})
            latency = int((time.perf_counter() - st.get("t0", time.perf_counter())) * 1000)
            cid = st.get("client_id")
            try:
                bytes_in = int(headers.get("content-length") or 0) or None
            except ValueError:
                bytes_in = None
            evt = {
                "pk": f"evt#{cid}" if cid else None, "sk": f"{st.get('ts')}#{st.get('request_id')}",
                "client_id": cid, "key_id": st.get("key_id"), "request_id": st.get("request_id"), "ts": st.get("ts"),
                "endpoint": _route_label(scope), "status": status_code, "latency_ms": latency,
                "ip": _client_ip(scope, headers), "user_agent": (headers.get("user-agent") or "")[:200],
                "via": st.get("via", "direct"),
                "apigw_request_id": headers.get("x-amzn-requestid") or headers.get("x-amzn-apigateway-api-id"),
                "photos": st.get("photos"), "bytes_in": bytes_in, "planogram_id": st.get("planogram_id"),
                "point_id": st.get("point_id"), "reading_id": st.get("reading_id"), "job_id": st.get("job_id"),
                "facings": st.get("facings"), "products": st.get("products"), "needs_review": st.get("needs_review"),
                "levels": st.get("levels"), "engine_ms": st.get("engine_ms"),
                "error": exc_text or st.get("error"),
            }
            api_telemetry.emit_event(evt)
        except Exception:
            traceback.print_exc()


app.add_middleware(TelemetryMiddleware)


# ---------------------------------------------------------------------------
# autenticación por llave (directa) o por identidad del gateway
# ---------------------------------------------------------------------------

def _raw_key_from_headers(headers: Headers) -> Optional[str]:
    raw = headers.get("x-api-key")  # Starlette compara sin distinguir mayúsculas: sirve X-API-Key y x-api-key
    if not raw:
        authz = headers.get("authorization") or ""
        if authz.lower().startswith("bearer "):
            raw = authz[7:]
    raw = (raw or "").strip()
    return raw or None


def _resolve_identity(request: Request) -> Optional[dict]:
    """{client, key} según X-NV-Gateway + X-NV-Key-Id (gateway) o X-API-Key / Bearer (ruta directa). Puede lanzar."""
    st = _state(request)
    store = apis_store.get_store()
    via = st.get("via") or _via_from_headers(request.headers)
    st["via"] = via
    ctx = None
    if via == "apigw":
        ctx = store.resolve_apigw_key_id(request.headers.get("x-nv-key-id"))
    if ctx is None:
        raw = _raw_key_from_headers(request.headers)
        if raw:
            ctx = store.resolve_key(raw)
    return ctx


# APIS_REQUIRE_GATEWAY=1: en producción solo se acepta tráfico que venga de Amazon API Gateway (cabecera de puerta válida);
# la ruta directa queda cerrada a llaves de cliente para que límites de tasa, cuotas y access logs del gateway apliquen siempre.
_REQUIRE_GATEWAY = os.environ.get("APIS_REQUIRE_GATEWAY", "0") == "1"


def require_api_key(request: Request) -> dict:
    st = _state(request)
    store = apis_store.get_store()
    if _REQUIRE_GATEWAY and (st.get("via") or _via_from_headers(request.headers)) != "apigw":
        raise ApiError(403, "direct_route_disabled", "Usa la URL pública de la API (Amazon API Gateway); la ruta directa está cerrada")
    try:
        ctx = _resolve_identity(request)
    except Exception as exc:
        print(f"[api-auth] no se pudo resolver la llave: {type(exc).__name__}: {exc}", flush=True)
        raise ApiError(401, "invalid_api_key", "No se pudo validar la llave de API; reintenta en unos segundos")
    if ctx is None:
        if st.get("via") != "apigw" and not _raw_key_from_headers(request.headers):
            raise ApiError(401, "invalid_api_key", "Falta la llave: envía el header X-API-Key (o Authorization: Bearer <llave>)")
        raise ApiError(401, "invalid_api_key", "Llave de API inválida, revocada o vencida")
    client, key = ctx["client"], ctx["key"]
    client_id = client["client_id"]
    st["client_id"] = client_id
    st["key_id"] = key.get("key_id")
    if (client.get("status") or "active") != "active":
        raise ApiError(403, "client_suspended", "El cliente está suspendido; contacta a Neuramorphic")
    ok, retry_after = store.check_and_count_quota(client_id, photos=0, calls=1, client=client)
    if not ok:
        calls_min, _ = store.quotas_for(client)
        raise ApiError(429, "quota_exceeded", f"Límite de {calls_min} llamadas por minuto alcanzado",
                       headers={"Retry-After": str(retry_after)})
    store.touch_key_last_used(client_id, key.get("key_id"))
    return ctx


def optional_api_key(request: Request) -> Optional[dict]:
    """Para /health: atribuye la llamada si trae llave válida, sin exigirla ni contar cuota."""
    try:
        ctx = _resolve_identity(request)
    except Exception:
        return None
    if ctx:
        _state(request)["client_id"] = ctx["client"]["client_id"]
        _state(request)["key_id"] = ctx["key"].get("key_id")
    return ctx


# ---------------------------------------------------------------------------
# modelos
# ---------------------------------------------------------------------------

class PlanogramItemIn(BaseModel):
    title: str
    band: int = 1
    expected_facings: int = 1
    position_in_section: Optional[int] = None
    order_seq: Optional[int] = None
    section_label: Optional[str] = None
    module: int = 1
    segment: int = 0
    internal_code: Optional[str] = None
    barcode: Optional[str] = None
    tag: Optional[str] = None


class PlanogramIn(BaseModel):
    id: Optional[str] = None
    name: str
    module_cm: Optional[float] = None
    bands: Optional[int] = None
    items: List[PlanogramItemIn]


class PointIn(BaseModel):
    point_id: Optional[str] = None
    name: Optional[str] = None
    planogram_id: Optional[str] = None
    store_id: Optional[str] = None
    gondola_id: Optional[str] = None


class ConfirmIn(BaseModel):
    image_index: int
    item_index: int
    title: Optional[str] = None      # título del planograma confirmado; None/"" = fuera de planograma
    facings: Optional[int] = None


# ---------------------------------------------------------------------------
# ayudas de alcance y de forma pública
# ---------------------------------------------------------------------------

_ID_BAD = re.compile(r"[^A-Za-z0-9_-]+")


def _clean_id(raw: Optional[str], maxlen: int = 40) -> str:
    return _ID_BAD.sub("-", (raw or "").strip()).strip("-")[:maxlen]


def _visible_planogram(client_id: str, planogram_id: str) -> dict:
    pg = db.get_planogram(planogram_id) if planogram_id else None
    owner = (pg or {}).get("owner_client")
    if not pg or not (owner == client_id or (owner is None and SHARE_UI_PLANOGRAMS)):
        raise ApiError(404, "not_found", f"Planograma '{planogram_id}' no encontrado")
    return pg


def _own_point(client_id: str, point_id: str) -> dict:
    meta = db.get_point_meta(point_id) if point_id else None
    if not meta or meta.get("owner_client") != client_id:
        raise ApiError(404, "not_found", f"Punto '{point_id}' no encontrado")
    return meta


def _own_reading(client_id: str, reading_id: int) -> dict:
    r = db.get_reading(reading_id)
    if r:
        meta = db.get_point_meta(r["point_id"])
        if meta and meta.get("owner_client") == client_id:
            return r
    raise ApiError(404, "not_found", f"Lectura {reading_id} no encontrada")


def _planogram_public(pg: dict) -> dict:
    out = {k: v for k, v in pg.items() if k != "owner_client"}
    out["shared"] = pg.get("owner_client") is None
    return out


def _point_public(meta: dict) -> dict:
    return {k: v for k, v in meta.items() if k != "owner_client"}


def _public_reading(r: dict, debug: bool = False, prefix: str = "/v1") -> dict:
    """La lectura que guarda la app, sin rutas internas; `engine.images[]` (depuración) solo con ?debug=1."""
    out = {k: v for k, v in r.items() if k != "image_paths"}
    products = []
    for p in r.get("products") or []:
        q = dict(p)
        if q.get("item_index") is not None and q.get("image_index") is not None:
            q["crop_url"] = f"{prefix}/readings/{r['id']}/crops/{q['image_index']}/{q['item_index']}.jpg"
        products.append(q)
    out["products"] = products
    out["count_uncertain"] = sum(1 for p in products if p.get("count_uncertain"))
    eng = r.get("engine")
    if isinstance(eng, dict) and not debug:
        out["engine"] = {k: v for k, v in eng.items() if k != "images"}
    return out


def _note_reading(request: Request, r: dict) -> None:
    _state(request).update({"reading_id": r.get("id"), "facings": r.get("total_facings"),
                            "products": len(r.get("products") or []), "needs_review": r.get("needs_review"),
                            "levels": r.get("shelf_levels_detected"), "point_id": r.get("point_id"),
                            "planogram_id": r.get("planogram_id")})


def _job_public(job: dict, debug: bool = False, prefix: str = "/v1") -> dict:
    out = {"job_id": job["job_id"], "status": job["status"], "point_id": job["point_id"], "created_at": job["created_at"],
           "started_at": job.get("started_at"), "finished_at": job.get("finished_at"), "poll": f"{prefix}/jobs/{job['job_id']}"}
    if job["status"] == "done":
        out["reading_id"] = job.get("reading_id")
        out["engine_ms"] = job.get("engine_ms")
        r = db.get_reading(job["reading_id"]) if job.get("reading_id") else None
        out["reading"] = _public_reading(r, debug, prefix) if r else None
    elif job["status"] == "failed":
        err = job.get("error") or "Análisis fallido"
        out["error"] = err
        out["error_code"] = "analysis_error" if err.startswith("engine_error:") else "analysis_rejected"
    return out


# ---------------------------------------------------------------------------
# salud y cuenta
# ---------------------------------------------------------------------------

@app.get("/health", summary="Estado del motor y de la cola (no exige llave ni cuenta cuota)")
def health(request: Request, _ctx: Optional[dict] = Depends(optional_api_key)):
    eh = core.engine_health()
    try:
        counts = db.job_counts()
    except Exception:
        counts = {}
    # sin detalles internos (rutas, nombres de módulos, almacén): el cliente solo necesita saber si el motor está listo
    return {"status": "ok" if eh["engine_ready"] and api_jobs.worker_alive() else "degraded", "api_version": API_VERSION,
            "engine": eh["engine"], "engine_ready": eh["engine_ready"], "engine_error": bool(eh["engine_error"]),
            "max_images": core.MAX_IMAGES,
            "jobs": {"queued": counts.get("queued", 0), "running": counts.get("running", 0)},
            "time": apis_store.now_iso()}


@app.get("/me", summary="Cliente, llave, plan, cuotas y uso de hoy")
def me(request: Request, ctx: dict = Depends(require_api_key)):
    client, key = ctx["client"], ctx["key"]
    store = apis_store.get_store()
    calls_min, photos_day = store.quotas_for(client)
    try:
        snapshot = store.quota_snapshot(client["client_id"])
    except Exception as exc:
        snapshot = {"error": f"{type(exc).__name__}: {exc}"[:120]}
    via = _state(request).get("via", "direct")
    return {"client": {"client_id": client["client_id"], "name": client.get("name"), "plan": client.get("plan"),
                       "status": client.get("status")},
            "key": {"key_id": key.get("key_id"), "key_prefix": key.get("key_prefix"), "label": key.get("label"),
                    "expires_at": key.get("expires_at"), "last_used_at": key.get("last_used_at")},
            "quotas": {"calls_per_minute": calls_min, "photos_per_day": photos_day},
            "usage_now": snapshot, "via": via,
            "limits": {"max_images": core.MAX_IMAGES, "stored_max_px": core.STORED_MAX_SIDE,
                       "wait_max_s": WAIT_MAX_APIGW if via == "apigw" else WAIT_MAX_DIRECT,
                       "max_image_mb": MAX_IMAGE_BYTES // (1024 * 1024)}}


# ---------------------------------------------------------------------------
# planogramas
# ---------------------------------------------------------------------------

@app.get("/planograms", summary="Planogramas disponibles")
def list_planograms(ctx: dict = Depends(require_api_key)):
    cid = ctx["client"]["client_id"]
    return [_planogram_public(p) for p in db.list_planograms(owner_client=cid, include_shared=SHARE_UI_PLANOGRAMS)]


@app.get("/planograms/{planogram_id}", summary="Un planograma con sus posiciones")
def get_planogram(planogram_id: str, request: Request, ctx: dict = Depends(require_api_key)):
    _state(request)["planogram_id"] = planogram_id
    return _planogram_public(_visible_planogram(ctx["client"]["client_id"], planogram_id))


@app.post("/planograms", status_code=201, summary="Crear un planograma (JSON)")
def create_planogram(payload: PlanogramIn, request: Request, ctx: dict = Depends(require_api_key)):
    cid = ctx["client"]["client_id"]
    if not payload.items:
        raise ApiError(422, "validation_error", "items: debe tener al menos una posición")
    pid = core.slugify_id(payload.id or payload.name)
    exists, _owner = db.planogram_owner(pid)
    if exists:
        raise ApiError(409, "planogram_exists", f"Ya existe un planograma con id '{pid}'")
    items, pos_in_band = [], {}
    for i, it in enumerate(payload.items, start=1):
        title = it.title.strip()
        if not title:
            raise ApiError(422, "validation_error", f"items[{i - 1}].title: vacío")
        band = int(it.band or 1)
        pos_in_band[band] = pos_in_band.get(band, 0) + 1
        items.append({"order_seq": it.order_seq or i, "section_label": it.section_label or f"1/{band}", "module": it.module or 1,
                      "band": band, "segment": it.segment or 0, "position_in_section": it.position_in_section or pos_in_band[band],
                      "title": title, "internal_code": it.internal_code, "barcode": it.barcode,
                      "expected_facings": max(0, int(it.expected_facings or 1)), "tag": it.tag})
    db.create_planogram({"id": pid, "name": payload.name.strip() or pid, "module_cm": payload.module_cm,
                         "bands": payload.bands or max(it["band"] for it in items), "source_filename": None,
                         "owner_client": cid, "items": items})
    _state(request)["planogram_id"] = pid
    return _planogram_public(db.get_planogram(pid))


@app.post("/planograms/import-pdf", status_code=201, summary="Crear un planograma desde el PDF de Salcobrand")
async def import_planogram_pdf(
    request: Request,
    file: UploadFile = File(..., description="PDF del planograma (texto, no escaneado)"),
    planogram_id: Optional[str] = Form(default=None),
    name: Optional[str] = Form(default=None),
    replace: bool = Form(default=False),
    ctx: dict = Depends(require_api_key),
):
    cid = ctx["client"]["client_id"]
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise ApiError(413, "payload_too_large", "PDF demasiado grande")
    try:
        result = await run_in_threadpool(core.import_planogram_pdf, data, file.filename, planogram_id, name, replace, cid)
    except core.PlanogramExists as exc:
        raise ApiError(409, "planogram_exists", str(exc))
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc))
    _state(request)["planogram_id"] = result["id"]
    return result


# ---------------------------------------------------------------------------
# puntos (local / góndola)
# ---------------------------------------------------------------------------

def _create_point(cid: str, point_id: Optional[str], name: Optional[str], planogram_id: Optional[str],
                  store_id: Optional[str], gondola_id: Optional[str]) -> dict:
    store_id = (store_id or "").strip() or None
    gondola_id = (gondola_id or "").strip() or None
    if point_id:
        pid = _clean_id(point_id)
        if not pid or pid != point_id.strip():
            raise ApiError(422, "validation_error", "point_id: solo letras, números, guion y guion bajo (máx. 40)")
    elif store_id and gondola_id:
        pid = f"{_clean_id(store_id, 20)}-{_clean_id(gondola_id, 19)}"
        if db.find_point_by_store_gondola(cid, store_id, gondola_id):
            raise ApiError(409, "point_exists", f"Ya existe un punto para {store_id}/{gondola_id}")
    else:
        pid = db.next_point_id()
    if db.point_exists(pid):
        raise ApiError(409, "point_exists", f"El punto '{pid}' ya existe")
    planogram_id = (planogram_id or "").strip() or None
    if planogram_id:
        _visible_planogram(cid, planogram_id)
    name = (name or "").strip() or (f"{store_id} / {gondola_id}" if store_id and gondola_id else pid)
    db.create_point(pid, name, planogram_id, owner_client=cid, store_id=store_id, gondola_id=gondola_id)
    return db.get_point_meta(pid)


@app.post("/points", status_code=201, summary="Crear un punto (local + góndola)")
def create_point(payload: PointIn, request: Request, ctx: dict = Depends(require_api_key)):
    meta = _create_point(ctx["client"]["client_id"], payload.point_id, payload.name, payload.planogram_id,
                         payload.store_id, payload.gondola_id)
    _state(request)["point_id"] = meta["id"]
    return _point_public(meta)


@app.get("/points", summary="Puntos creados con esta llave")
def list_points(ctx: dict = Depends(require_api_key)):
    return [_point_public(m) for m in db.list_points_for_client(ctx["client"]["client_id"])]


@app.get("/points/{point_id}", summary="Un punto")
def get_point(point_id: str, request: Request, ctx: dict = Depends(require_api_key)):
    _state(request)["point_id"] = point_id
    return _point_public(_own_point(ctx["client"]["client_id"], point_id))


@app.get("/points/{point_id}/readings", summary="Historial de lecturas de un punto")
def point_readings(point_id: str, request: Request, limit: int = Query(10, ge=1, le=100), debug: bool = False,
                   ctx: dict = Depends(require_api_key)):
    _own_point(ctx["client"]["client_id"], point_id)
    _state(request)["point_id"] = point_id
    readings = [_public_reading(r, debug, _url_prefix(request)) for r in db.readings_for_point(point_id, limit)]
    return {"point_id": point_id, "count": len(readings), "readings": readings}


# ---------------------------------------------------------------------------
# análisis (jobs)
# ---------------------------------------------------------------------------

async def _wait_for_job(job_id: str, seconds: float) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        job = await run_in_threadpool(db.get_job, job_id)
        if job is None or job["status"] in ("done", "failed") or time.monotonic() >= deadline:
            return job
        await asyncio.sleep(min(JOB_POLL_S, max(0.05, deadline - time.monotonic())))


def _finished_job_response(request: Request, job: dict, debug: bool) -> JSONResponse:
    out = _job_public(job, debug, _url_prefix(request))
    if job["status"] == "done":
        if out.get("reading"):
            _note_reading(request, out["reading"])
        _state(request)["engine_ms"] = job.get("engine_ms")
        return JSONResponse(out, status_code=200)
    _state(request)["engine_ms"] = job.get("engine_ms")
    if out.get("error_code") == "analysis_error":
        raise ApiError(500, "analysis_error", f"{out['error']} (job {job['job_id']})")
    raise ApiError(422, "analysis_rejected", f"{out['error']} (job {job['job_id']})")


@app.post("/analyze", status_code=202, summary="Analizar fotos de una góndola (encola un job)")
async def analyze(
    request: Request,
    images: List[UploadFile] = File(..., description=f"1 a {core.MAX_IMAGES} fotos, de izquierda a derecha (JPG/PNG/WebP/HEIC)"),
    point_id: Optional[str] = Form(default=None),
    store_id: Optional[str] = Form(default=None),
    gondola_id: Optional[str] = Form(default=None),
    name: Optional[str] = Form(default=None, description="Nombre del punto si se crea con store_id + gondola_id"),
    planogram_id: Optional[str] = Form(default=None),
    linear_meters: Optional[float] = Form(default=None),
    wait: int = Query(0, ge=0, le=WAIT_MAX_DIRECT, description="Segundos a esperar el resultado (máx. 50; 25 vía gateway)"),
    debug: bool = Query(False, description="Incluir engine.images[] (cajas, OCR por recorte) en la lectura"),
    ctx: dict = Depends(require_api_key),
):
    st = _state(request)
    client = ctx["client"]
    cid = client["client_id"]
    store = apis_store.get_store()

    # punto: existente (propio) o creado al vuelo por local + góndola
    point_id = (point_id or "").strip() or None
    if point_id:
        point = _own_point(cid, point_id)
    elif (store_id or "").strip() and (gondola_id or "").strip():
        point = db.find_point_by_store_gondola(cid, store_id.strip(), gondola_id.strip()) or \
            _create_point(cid, None, name, planogram_id, store_id, gondola_id)
    else:
        raise ApiError(422, "validation_error", "Indica point_id, o store_id + gondola_id")
    st["point_id"] = point["id"]

    import infrastructure
    try:
        capture_context = infrastructure.capture_context(point["id"])
    except infrastructure.ManagementError as exc:
        raise ApiError(exc.status, "inactive_infrastructure", str(exc)) from exc

    pg_id = (planogram_id or "").strip() or point.get("planogram_id")
    if (planogram_id or "").strip():
        _visible_planogram(cid, pg_id)
        if not point.get("planogram_id"):
            db.set_point_planogram(point["id"], pg_id)
    st["planogram_id"] = pg_id

    try:
        loaded = await core.read_image_uploads(images, max_bytes_each=MAX_IMAGE_BYTES, max_bytes_total=MAX_REQUEST_BYTES)
    except core.ImageTooLarge as exc:
        raise ApiError(413, "payload_too_large", str(exc))
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc))
    st["photos"] = len(loaded)

    ok, retry_after = store.check_and_count_quota(cid, photos=len(loaded), calls=0, client=client)
    if not ok:
        _calls, photos_day = store.quotas_for(client)
        raise ApiError(429, "quota_exceeded", f"Cuota diaria de fotos alcanzada ({photos_day} fotos/día)",
                       headers={"Retry-After": str(retry_after)})

    image_paths = [core.save_upload(point["id"], b, ct) for b, ct in loaded]
    payload = {"image_paths": image_paths, "linear_meters": linear_meters, "planogram_id": pg_id,
               "key_id": ctx["key"].get("key_id"), "request_id": st["request_id"], "evt_sk": f"{st['ts']}#{st['request_id']}",
               "day": str(st["ts"])[:10], "via": st.get("via", "direct"), "debug": bool(debug), "infrastructure": capture_context}
    job = api_jobs.enqueue(cid, point["id"], payload)
    st["job_id"] = job["job_id"]

    max_wait = WAIT_MAX_APIGW if st.get("via") == "apigw" else WAIT_MAX_DIRECT
    wait = min(int(wait or 0), max_wait)
    if wait > 0:
        job = await _wait_for_job(job["job_id"], wait) or job
        if job["status"] in ("done", "failed"):
            return _finished_job_response(request, job, debug)
    out = _job_public(job, debug, _url_prefix(request))
    out["queued_ahead"] = max(0, api_jobs.queue_depth() - 1)
    return JSONResponse(out, status_code=202)


@app.get("/jobs/{job_id}", summary="Estado de un job (y la lectura cuando termina)")
def get_job(job_id: str, request: Request, debug: bool = False, ctx: dict = Depends(require_api_key)):
    job = db.get_job(job_id)
    if not job or job["client_id"] != ctx["client"]["client_id"]:
        raise ApiError(404, "not_found", f"Job '{job_id}' no encontrado")
    _state(request)["job_id"] = job_id
    _state(request)["point_id"] = job["point_id"]
    out = _job_public(job, debug, _url_prefix(request))
    if out.get("reading"):
        _note_reading(request, out["reading"])
    return out


# ---------------------------------------------------------------------------
# lecturas
# ---------------------------------------------------------------------------

@app.get("/readings/{reading_id}", summary="Una lectura")
def get_reading(reading_id: int, request: Request, debug: bool = False, ctx: dict = Depends(require_api_key)):
    r = _own_reading(ctx["client"]["client_id"], reading_id)
    _note_reading(request, r)
    return _public_reading(r, debug, _url_prefix(request))


@app.get("/readings/{reading_id}/crops/{image_index}/{item_index}.jpg", summary="Recorte JPEG de un ítem detectado")
def reading_crop(reading_id: int, image_index: int, item_index: int, request: Request, ctx: dict = Depends(require_api_key)):
    r = _own_reading(ctx["client"]["client_id"], reading_id)
    _state(request)["reading_id"] = reading_id
    try:
        data = core.crop_jpeg(r, image_index, item_index)
    except LookupError as exc:
        raise ApiError(404, "not_found", str(exc))
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/readings/{reading_id}/review", include_in_schema=False, summary="Ítems por revisar de la lectura (índices, recorte, candidatos)")
def reading_review(reading_id: int, request: Request, ctx: dict = Depends(require_api_key)):
    raise HTTPException(403, 'La verificación de productos es interna. Utiliza el perfil local-neura del proveedor.')


@app.post("/readings/{reading_id}/confirm", include_in_schema=False, summary="Confirmación humana de un recorte (alimenta la memoria visual)")
def reading_confirm(reading_id: int, payload: ConfirmIn, request: Request, ctx: dict = Depends(require_api_key)):
    raise HTTPException(403, 'La verificación de productos es interna. Utiliza el perfil local-neura del proveedor.')


# ---------------------------------------------------------------------------
# uso propio
# ---------------------------------------------------------------------------

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_day(value: Optional[str], name: str) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if not _DAY_RE.match(value):
        raise ApiError(422, "validation_error", f"{name}: usa el formato YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ApiError(422, "validation_error", f"{name}: fecha inválida")


@app.get("/usage", summary="Uso propio por día (llamadas, fotos, errores, latencia, por endpoint y por llave)")
def usage(request: Request, from_day: Optional[str] = Query(None, alias="from"), to_day: Optional[str] = Query(None, alias="to"),
          ctx: dict = Depends(require_api_key)):
    cid = ctx["client"]["client_id"]
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    to_dt = _parse_day(to_day, "to") or today
    from_dt = _parse_day(from_day, "from") or (to_dt - timedelta(days=6))
    if from_dt > to_dt:
        raise ApiError(422, "validation_error", "from debe ser anterior o igual a to")
    if (to_dt - from_dt).days > 92:
        raise ApiError(422, "validation_error", "Rango máximo: 92 días")
    f, t = from_dt.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d")
    try:
        days = apis_store.get_store().usage(cid, f, t)
    except Exception as exc:
        print(f"[api-v1] usage falló: {type(exc).__name__}: {exc}", flush=True)
        raise ApiError(503, "service_unavailable", "Telemetría no disponible en este momento")
    totals = {k: sum(int(d.get(k) or 0) for d in days) for k in ("calls", "errors", "photos", "facings", "needs_review", "jobs_failed")}
    return {"client_id": cid, "from": f, "to": t, "days": days, "totals": totals}


# ---------------------------------------------------------------------------
# OpenAPI: esquema de seguridad para "Authorize" en /v1/docs
# ---------------------------------------------------------------------------

def _openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes,
                         servers=app.servers)
    schema.setdefault("components", {})["securitySchemes"] = {
        "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
        "BearerAuth": {"type": "http", "scheme": "bearer"},
    }
    schema["security"] = [{"ApiKeyAuth": []}, {"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = _openapi
