"""Client for Neuravision on Kilby (https://kilby.neuramorphic.ai/docs/neuravision).

Two calls, authenticated with a workspace key (``kai_...``):

- ``POST {base}/neuravision/analyze``: multipart with 1-6 ``images`` (9 MB in all), ``store_id``, ``gondola_id`` and,
  when the workspace has several catalogs, ``catalog``. Answers a job (202), or the finished job (200) when ``wait``
  seconds were enough.
- ``GET {base}/neuravision/jobs/{id}``: the job; ``result`` when it is ``done``.

Kilby meters and bills every analyzed photo of the workspace: this client sends no usage telemetry of its own.

Guarantees:
- The key never appears in logs, exceptions or ``repr``.
- A request is retried only when a retry cannot create a second billed job: responses Kilby documents as "not
  counted" (429 rate_limit, 502/503/504) and network errors that happen before the request reached Kilby. When the
  connection breaks after the photos were sent, ``AmbiguousSubmitError`` is raised instead of resending them.
- ``Retry-After`` is respected (capped), otherwise exponential backoff with jitter.

Dataset API (catalogs, products, labels, trainings, versions): see the methods after ``check``. It depends on Kilby's
Neuravision dataset API (contract of 2026-11-18, not deployed yet) and on a key with the "Manage catalogs and
trainings" permission, which only a Kilby workspace admin can create.

Dependencies: httpx only. Python 3.9+.
"""
from __future__ import annotations

import email.utils
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union
from urllib.parse import quote

import httpx

log = logging.getLogger("kilby_neuravision")

DEFAULT_BASE_URL = "https://ai.kilby.neuramorphic.ai/v1"
MAX_PHOTOS = 6
MAX_TOTAL_BYTES = 9 * 1024 * 1024  # all the photos of one analysis
MAX_WAIT_S = 25
FINAL_STATUSES = ("done", "failed", "expired")

KEY_PATTERN = re.compile(r"^kai_[A-Za-z0-9_-]{16,196}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
CATALOG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
SKU_MAX = 64
PRODUCT_PHOTOS_MAX = 5
PRODUCT_PHOTO_BYTES = 10 * 1024 * 1024

# Codes Kilby documents as retriable without billing (the request was refused before any photo was counted).
RETRIABLE_CODES = {"rate_limit", "busy", "capacity", "unavailable", "engine_unavailable", "timeout"}

# Spanish text for each documented error code (gateway errors and job errors), for the people using the app.
MESSAGES_ES: Dict[str, str] = {
    "missing_key": "Falta la clave de Neuravision. Un administrador la ingresa en Administración → APIs.",
    "invalid_key": "La clave de Neuravision no es válida o fue revocada. Un administrador debe ingresar una nueva en Administración → APIs.",
    "expired_key": "La clave de Neuravision venció. Un administrador debe crear una nueva en Kilby e ingresarla en Administración → APIs.",
    "product_not_allowed": "Esta clave de Kilby no permite usar Neuravision. Crea la clave desde la página Neuravision del panel de Kilby.",
    "vision_not_enabled": "Neuravision no está activo en el espacio de Kilby (no hay un plan activo o fue suspendido). Un administrador debe activarlo en el panel de Kilby.",
    "invalid_request": "La solicitud de análisis no es válida. Revisa las fotos y la góndola e inténtalo nuevamente.",
    "catalog_not_found": "El catálogo configurado no existe en Kilby. Revisa el catálogo en Administración → APIs.",
    "catalog_not_ready": "El catálogo aún no tiene una versión publicada en Kilby. Entrénalo y publícalo en el panel de Kilby.",
    "photo_too_large": "Una foto es demasiado grande. Usa fotos de hasta 3.000 píxeles por lado.",
    "request_too_large": "Las fotos superan 9 MB en total. Envía menos fotos o fotos más livianas.",
    "unsupported_photo": "Formato de foto no admitido. Usa JPEG, PNG, WebP o HEIC.",
    "rejected_by_engine": "El motor no aceptó estas fotos o esta góndola. No se cobró. Revisa las fotos e inténtalo nuevamente.",
    "rate_limit": "Se alcanzó el límite de solicitudes por minuto de la clave. Reintenta en unos segundos.",
    "key_daily_photos": "La clave alcanzó su límite de fotos de hoy.",
    "key_monthly_photos": "La clave alcanzó su límite de fotos del mes.",
    "workspace_monthly_photos": "El espacio de Kilby alcanzó su tope mensual de fotos. Un administrador puede subirlo en la página Neuravision de Kilby.",
    "engine_unavailable": "El motor de análisis no está disponible en este momento. No se cobró. Inténtalo nuevamente.",
    "busy": "Neuravision está recibiendo muchas fotos en este momento. No se cobró. Reintenta en unos segundos.",
    "capacity": "Neuravision no está aceptando más fotos por ahora. No se cobró. Inténtalo más tarde.",
    "timeout": "El motor tardó demasiado en recibir las fotos. No se cobró. Inténtalo nuevamente.",
    "unavailable": "Kilby no pudo atender la solicitud en este momento. Inténtalo nuevamente.",
    "not_found": "Kilby no tiene ese análisis en este espacio.",
    # Dataset API (catalogs, products, labels, trainings)
    "dataset_not_allowed": "La clave no tiene el permiso «Manage catalogs and trainings». Un administrador del espacio de Kilby debe crear una clave con ese permiso e ingresarla en Administración → APIs.",
    "training_quota": "El plan de Kilby no tiene entrenamientos disponibles por ahora (Starter: 1 al mes; Growth: 1 por semana y catálogo).",
    "no_products": "El catálogo de Kilby no tiene productos. Sincroniza los productos antes de entrenar.",
    "too_few_images": "Menos de 2 productos tienen una foto utilizable. Agrega fotos a los productos y sincroniza.",
    "bad_manifest": "Kilby envió algo que el motor rechazó. Reintenta; si vuelve a fallar, escribe a Neuramorphic.",
    "internal": "El motor falló al entrenar. Inténtalo más tarde.",
    # Job errors (status failed / expired)
    "analysis_rejected": "No se reconoció una góndola con productos del catálogo en estas fotos (lejos, borrosas o no es una góndola). No se cobró.",
    "analysis_error": "El motor falló con estas fotos. No se cobró. Inténtalo nuevamente.",
    "engine_lost_job": "El motor ya no tiene este análisis. No se cobró. Vuelve a enviar las fotos.",
    "no_answer": "El motor no terminó este análisis a tiempo. No se cobró. Vuelve a enviar las fotos.",
    # Client-side
    "network": "No fue posible conectar con Kilby. Revisa la conexión del servidor e inténtalo nuevamente.",
    "ambiguous_submit": "Se cortó la conexión después de enviar las fotos; no se sabe si Kilby las recibió. Recupera la solicitud antes de reenviar.",
    "job_timeout": "El análisis sigue en proceso en Kilby. Recupera la solicitud en unos minutos.",
}


def message_es(code: Optional[str], default: str = "Neuravision no pudo completar la solicitud.") -> str:
    return MESSAGES_ES.get(code or "", default)


# ---------------------------------------------------------------------------- errors

class NeuravisionError(Exception):
    """Base error. ``code`` is Kilby's ``error.code``; ``detail`` its English message; ``message_es`` for the UI."""

    def __init__(self, message: str, *, status: Optional[int] = None, code: Optional[str] = None,
                 retry_after: Optional[float] = None, request_id: Optional[str] = None, param: Optional[str] = None):
        super().__init__(message)
        self.status, self.code, self.retry_after = status, code, retry_after
        self.request_id, self.param, self.detail = request_id, param, message

    @property
    def message_es(self) -> str:
        return message_es(self.code)

    def __str__(self) -> str:
        bits = [self.detail]
        if self.status:
            bits.append(f"(HTTP {self.status}{' ' + self.code if self.code else ''})")
        return " ".join(bits)


class AuthError(NeuravisionError):
    """401 missing_key / invalid_key / expired_key, 403 product_not_allowed."""


class NotEnabledError(NeuravisionError):
    """403 vision_not_enabled: the workspace has no active plan."""


class InvalidRequestError(NeuravisionError):
    """400, 404 catalog_not_found / not_found, 409 catalog_not_ready, 413, 415, 422 rejected_by_engine."""


class RateLimitError(NeuravisionError):
    """429: rate_limit (retriable) or a photo cap (not retriable until the period ends)."""


class UnavailableError(NeuravisionError):
    """502/503/504 or a network error. Not counted by Kilby."""


class AmbiguousSubmitError(UnavailableError):
    """The connection broke after the photos were sent: Kilby may have created (and will bill) the job."""


class JobTimeoutError(NeuravisionError):
    """The job is still queued or running after the deadline. ``job`` is the last state seen."""

    def __init__(self, message: str, job: "Job"):
        super().__init__(message, code="job_timeout")
        self.job = job


_ERROR_CLASSES = {401: AuthError, 413: InvalidRequestError, 415: InvalidRequestError, 422: InvalidRequestError,
                  400: InvalidRequestError, 404: InvalidRequestError, 409: InvalidRequestError, 429: RateLimitError}


def _error_from_response(response: httpx.Response) -> NeuravisionError:
    code = message = param = body_retry = None
    try:
        body = response.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            code, message, param = err.get("code"), err.get("message"), err.get("param")
            body_retry = err.get("retry_after")
    except ValueError:
        pass
    status = response.status_code
    if status == 403:
        cls = NotEnabledError if code == "vision_not_enabled" else AuthError
    elif status >= 500:
        cls = UnavailableError
    else:
        cls = _ERROR_CLASSES.get(status, NeuravisionError)
    retry_after = _retry_after(response)
    if retry_after is None and isinstance(body_retry, (int, float)) and not isinstance(body_retry, bool):
        retry_after = max(0.0, float(body_retry))
    return cls(str(message or f"Kilby answered HTTP {status}")[:300], status=status, code=code,
               retry_after=retry_after, request_id=response.headers.get("X-Kilby-Request-Id"), param=param)


def _retry_after(response: httpx.Response) -> Optional[float]:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------- data

@dataclass(frozen=True)
class Photo:
    data: bytes
    content_type: str = "image/jpeg"
    filename: str = "photo.jpg"

    def __repr__(self) -> str:  # never dump the bytes
        return f"Photo({self.filename!r}, {self.content_type}, {len(self.data)} bytes)"


@dataclass
class Job:
    id: str
    status: str
    photos: int = 0
    catalog: Optional[str] = None
    created_at: Optional[str] = None
    finished_at: Optional[str] = None
    engine_ms: Optional[int] = None
    billed: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    result_available: Optional[bool] = None
    result: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def final(self) -> bool:
        return self.status in FINAL_STATUSES

    @property
    def error_es(self) -> Optional[str]:
        return message_es(self.error_code) if self.error_code else None

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "Job":
        if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not isinstance(data.get("status"), str):
            raise NeuravisionError("Kilby returned a job without id or status")
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        return cls(id=data["id"], status=data["status"], photos=int(data.get("photos") or 0), catalog=data.get("catalog"),
                   created_at=data.get("created_at"), finished_at=data.get("finished_at"), engine_ms=data.get("engine_ms"),
                   billed=bool(data.get("billed")), error_code=err.get("code"), error_message=err.get("message"),
                   result_available=data.get("result_available"),
                   result=data.get("result") if isinstance(data.get("result"), dict) else None, raw=data)


@dataclass
class ConnectionCheck:
    ok: bool
    key_valid: bool
    plan_active: Optional[bool]
    code: Optional[str]
    message_es: str


# ---------------------------------------------------------------------------- client

_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.WriteError, httpx.WriteTimeout)
# WriteError/WriteTimeout: Kilby reads the whole form before it reserves a job, so a body that was not fully written
# cannot have created one.


class KilbyNeuravision:
    """Synchronous client. Thread-safe as long as the underlying httpx.Client is (it is)."""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, *, timeout: Optional[httpx.Timeout] = None,
                 max_retries: int = 3, client: Optional[httpx.Client] = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 user_agent: str = "salcobrand-neuravision/1"):
        if not isinstance(api_key, str) or not KEY_PATTERN.match(api_key.strip()):
            raise AuthError("This is not a Kilby key (they start with kai_)", code="invalid_key")
        base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        parsed = httpx.URL(base)
        if parsed.scheme != "https" and parsed.host not in ("127.0.0.1", "localhost"):
            raise ValueError("Kilby's URL must be https")
        if parsed.userinfo or parsed.query or parsed.fragment:
            raise ValueError("Kilby's URL must not carry credentials, a query or a fragment")
        self._key = api_key.strip()
        self.base_url = base
        self.max_retries = max(0, int(max_retries))
        self._sleep, self._clock = sleep, clock
        self._owns_client = client is None
        self._http = client or httpx.Client(timeout=timeout or httpx.Timeout(connect=10, read=60, write=60, pool=10),
                                            follow_redirects=False, trust_env=False)
        self._headers = {"Authorization": "Bearer " + self._key, "Accept": "application/json", "User-Agent": user_agent}

    def __repr__(self) -> str:
        return f"KilbyNeuravision(base_url={self.base_url!r}, key=kai_…{self._key[-4:]})"

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "KilbyNeuravision":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ transport
    def _backoff(self, attempt: int, retry_after: Optional[float]) -> float:
        if retry_after is not None:
            return min(retry_after, 30.0)
        return min(8.0, 2 ** attempt) * (0.5 + random.random() / 2)

    def _send(self, method: str, path: str, *, idempotent: bool, **kwargs) -> httpx.Response:
        url = self.base_url + path
        headers = {**self._headers, **kwargs.pop("headers", {})}
        attempt = 0
        while True:
            try:
                response = self._http.request(method, url, headers=headers, **kwargs)
            except _NOT_SENT as exc:
                error: NeuravisionError = UnavailableError(f"cannot reach Kilby: {type(exc).__name__}", code="network")
            except httpx.TransportError as exc:  # read timeout, connection reset after sending
                if not idempotent:
                    raise AmbiguousSubmitError(f"connection to Kilby broke after sending: {type(exc).__name__}",
                                               code="ambiguous_submit") from None
                error = UnavailableError(f"connection to Kilby broke: {type(exc).__name__}", code="network")
            else:
                if response.status_code < 400:
                    return response
                error = _error_from_response(response)
                retriable = error.code in RETRIABLE_CODES or (error.code is None and response.status_code in (502, 503, 504))
                if not retriable:
                    raise error
            if attempt >= self.max_retries:
                raise error
            delay = self._backoff(attempt, error.retry_after)
            log.info("neuravision %s %s: %s, retry %d in %.1f s", method, path.split("?")[0], error.code or error.status,
                     attempt + 1, delay)
            self._sleep(delay)
            attempt += 1

    @staticmethod
    def _json(response: httpx.Response) -> Dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            raise NeuravisionError("Kilby returned something that is not JSON", status=response.status_code) from None
        if not isinstance(data, dict):
            raise NeuravisionError("Kilby returned an unexpected answer", status=response.status_code)
        return data

    # ------------------------------------------------------------------ API
    def analyze(self, photos: Sequence[Union[Photo, bytes]], store_id: str, gondola_id: str, *,
                catalog: Optional[str] = None, name: Optional[str] = None, linear_meters: Optional[float] = None,
                wait: int = 0) -> Job:
        """Send the photos of one shelf (left to right). Returns the job (finished if ``wait`` was enough)."""
        items = [p if isinstance(p, Photo) else Photo(bytes(p)) for p in photos]
        if not 1 <= len(items) <= MAX_PHOTOS:
            raise InvalidRequestError(f"send 1 to {MAX_PHOTOS} photos", code="invalid_request", param="images")
        total = sum(len(p.data) for p in items)
        if total > MAX_TOTAL_BYTES:
            raise InvalidRequestError(f"the photos weigh {total} bytes; at most {MAX_TOTAL_BYTES}", code="request_too_large")
        for label, value in (("store_id", store_id), ("gondola_id", gondola_id)):
            if not isinstance(value, str) or not ID_PATTERN.match(value):
                raise InvalidRequestError(f"{label}: 1 to 40 letters, digits, dots, dashes or underscores",
                                          code="invalid_request", param=label)
        if catalog is not None and not CATALOG_PATTERN.match(catalog):
            raise InvalidRequestError("catalog: lowercase letters, digits and dashes", code="invalid_request", param="catalog")
        wait = max(0, min(int(wait or 0), MAX_WAIT_S))
        data: Dict[str, str] = {"store_id": store_id, "gondola_id": gondola_id}
        if catalog:
            data["catalog"] = catalog
        if name:
            data["name"] = " ".join(str(name).split())[:100]
        if linear_meters is not None and 0 < float(linear_meters) <= 100:
            data["linear_meters"] = f"{float(linear_meters):g}"
        if wait:
            data["wait"] = str(wait)
        files = [("images", (p.filename, p.data, p.content_type)) for p in items]
        base = self._http.timeout  # with wait, Kilby holds the answer up to that many seconds
        timeout = httpx.Timeout(connect=base.connect, read=(base.read or 60) + wait, write=base.write, pool=base.pool)
        response = self._send("POST", "/neuravision/analyze", idempotent=False, data=data, files=files, timeout=timeout)
        job = Job.from_json(self._json(response))
        log.info("neuravision job %s %s: %d photos, %d bytes", job.id, job.status, len(items), total)
        return job

    def job(self, job_id: str) -> Job:
        if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", job_id):
            raise InvalidRequestError("not a job id", code="invalid_request")
        return Job.from_json(self._json(self._send("GET", "/neuravision/jobs/" + job_id, idempotent=True)))

    def jobs(self, limit: int = 20) -> List[Job]:
        data = self._json(self._send("GET", "/neuravision/jobs", idempotent=True, params={"limit": max(1, min(int(limit), 100))}))
        return [Job.from_json(item) for item in data.get("data") or []]

    def wait_for(self, job: Union[Job, str], *, timeout: float = 600, interval: float = 1.5, max_interval: float = 5.0) -> Job:
        """Poll until the job ends. ``JobTimeoutError`` (with the last state) when it is still running at ``timeout``.
        Interval: 1.5 s, growing 1.3x up to 5 s (a cold engine takes 1-3 minutes to answer the first photo)."""
        current = job if isinstance(job, Job) else self.job(job)
        deadline = self._clock() + timeout
        step = interval
        while not current.final:
            left = deadline - self._clock()
            if left <= 0:
                raise JobTimeoutError(f"job {current.id} still {current.status}", current)
            self._sleep(min(step, left))
            step = min(step * 1.3, max_interval)
            current = self.job(current.id)
        return current

    def analyze_and_wait(self, photos: Sequence[Union[Photo, bytes]], store_id: str, gondola_id: str, *,
                         timeout: float = 600, **kwargs) -> Job:
        kwargs.setdefault("wait", MAX_WAIT_S)
        return self.wait_for(self.analyze(photos, store_id, gondola_id, **kwargs), timeout=timeout)

    def check(self) -> ConnectionCheck:
        """Checks the key without sending any photo (nothing is analyzed or billed).

        1. ``GET /neuravision/jobs?limit=1``: the key is valid and may call Neuravision.
        2. ``POST /neuravision/analyze`` with no photo: Kilby checks the workspace's plan before it reads the form, so
           an active plan answers 400 ``invalid_request`` on ``images`` and an inactive one 403 ``vision_not_enabled``.
           No job can be created without photos. (Order of checks verified in Kilby's gateway, 2026-11-18.)
        The catalog is only checked by a real analysis (409 ``catalog_not_ready`` / 404 ``catalog_not_found``)."""
        try:
            self.jobs(limit=1)
        except AuthError as exc:
            return ConnectionCheck(False, False, None, exc.code, exc.message_es)
        except NeuravisionError as exc:
            return ConnectionCheck(False, False, None, exc.code or "network", message_es(exc.code or "network"))
        boundary = "kilby-connection-check"
        form = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\nconnection-check\r\n'
                       for name in ("store_id", "gondola_id")) + f"--{boundary}--\r\n"
        try:
            self._send("POST", "/neuravision/analyze", idempotent=True, content=form.encode(),
                       headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
        except NotEnabledError as exc:
            return ConnectionCheck(False, True, False, exc.code, exc.message_es)
        except InvalidRequestError as exc:
            if exc.status == 400:
                return ConnectionCheck(True, True, True, None, "Conexión correcta: la clave es válida y Neuravision está activo en Kilby.")
            return ConnectionCheck(False, True, None, exc.code, exc.message_es)
        except NeuravisionError as exc:
            return ConnectionCheck(False, True, None, exc.code, exc.message_es)
        return ConnectionCheck(False, True, None, "unexpected", "Kilby respondió algo inesperado a la prueba de conexión.")

    # ------------------------------------------------------------------ dataset API
    # Depends on Kilby's Neuravision dataset API (contract 2026-11-18, NOT deployed yet). The key needs the
    # "Manage catalogs and trainings" permission (403 dataset_not_allowed otherwise). Kilby never calls this app:
    # the app pushes its product master and its confirmed crops, then launches trainings.

    @staticmethod
    def _slug(slug: str) -> str:
        if not isinstance(slug, str) or not CATALOG_PATTERN.match(slug):
            raise InvalidRequestError("catalog: lowercase letters, digits and dashes", code="invalid_request", param="catalog")
        return slug

    @staticmethod
    def _sku(sku: str) -> str:
        if not isinstance(sku, str) or not sku.strip() or len(sku) > SKU_MAX or any(ord(c) < 32 for c in sku):
            raise InvalidRequestError(f"sku: 1 to {SKU_MAX} characters", code="invalid_request", param="sku")
        return quote(sku, safe="")

    @staticmethod
    def _payload(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            raise NeuravisionError("Kilby returned something that is not JSON", status=response.status_code) from None

    def _list(self, data: Any) -> List[Dict[str, Any]]:
        items = data.get("data") if isinstance(data, dict) else data
        return [item for item in items or [] if isinstance(item, dict)]

    def catalogs(self) -> List[Dict[str, Any]]:
        """slug, name, products, photos, published_version {version, top1, top3, products, seeded}, trainings_left."""
        return self._list(self._payload(self._send("GET", "/neuravision/catalogs", idempotent=True)))

    def create_catalog(self, slug: str, name: str) -> Dict[str, Any]:
        body = {"slug": self._slug(slug), "name": " ".join(str(name).split())[:100] or slug}
        return self._json(self._send("POST", "/neuravision/catalogs", idempotent=True, json=body))

    def products_page(self, slug: str, cursor: Optional[str] = None, limit: int = 100) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        params: Dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
        if cursor:
            params["cursor"] = cursor
        data = self._payload(self._send("GET", f"/neuravision/catalogs/{self._slug(slug)}/products", idempotent=True, params=params))
        following = data.get("next_cursor") or data.get("cursor") if isinstance(data, dict) else None
        return self._list(data), following or None

    def iter_products(self, slug: str, limit: int = 100) -> Iterator[Dict[str, Any]]:
        cursor: Optional[str] = None
        for _ in range(10_000):
            items, cursor = self.products_page(slug, cursor, limit)
            yield from items
            if not cursor or not items:
                return

    def put_product(self, slug: str, sku: str, name: str, *, brand: Optional[str] = None, category: Optional[str] = None,
                    photos: Optional[Sequence[Photo]] = None) -> Dict[str, Any]:
        """Upsert (idempotent). Without photos the product keeps the ones Kilby has; with 1-5 photos they replace them."""
        path = f"/neuravision/catalogs/{self._slug(slug)}/products/{self._sku(sku)}"
        fields = {"name": " ".join(str(name).split())[:180]}
        if brand:
            fields["brand"] = str(brand)[:100]
        if category:
            fields["category"] = str(category)[:100]
        if not photos:
            return self._json(self._send("PUT", path, idempotent=True, json=fields))
        if len(photos) > PRODUCT_PHOTOS_MAX or any(len(p.data) > PRODUCT_PHOTO_BYTES for p in photos):
            raise InvalidRequestError(f"1 to {PRODUCT_PHOTOS_MAX} product photos of up to 10 MB", code="invalid_request", param="photos")
        files = [("photos", (p.filename, p.data, p.content_type)) for p in photos]
        return self._json(self._send("PUT", path, idempotent=True, data=fields, files=files))

    def delete_product(self, slug: str, sku: str) -> bool:
        """True when Kilby deleted it, False when it was already absent."""
        try:
            self._send("DELETE", f"/neuravision/catalogs/{self._slug(slug)}/products/{self._sku(sku)}", idempotent=True)
        except InvalidRequestError as exc:
            if exc.status == 404:
                return False
            raise
        return True

    def upload_labels(self, slug: str, labels: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """Replaces the catalog's confirmed crops. Each label: {job_id: vjob_..., image_index, item_index, sku}."""
        lines = []
        for label in labels:
            lines.append(json.dumps({"job_id": label["job_id"], "image_index": int(label["image_index"]),
                                     "item_index": int(label["item_index"]), "sku": str(label["sku"])}, ensure_ascii=False))
        body = ("\n".join(lines) + ("\n" if lines else "")).encode()
        return self._json(self._send("POST", f"/neuravision/catalogs/{self._slug(slug)}/labels", idempotent=True,
                                     content=body, headers={"Content-Type": "application/x-ndjson"}))

    def start_training(self, slug: str) -> Dict[str, Any]:
        """202 {id, status}. Never retried: each accepted training counts against the plan's quota."""
        return self._json(self._send("POST", f"/neuravision/catalogs/{self._slug(slug)}/trainings", idempotent=False))

    def training(self, slug: str, training_id: str) -> Dict[str, Any]:
        """{id, status queued/running/done/failed, metrics {top1, top3, skus}, baseline {top1, top3}, version, published, error}."""
        if not isinstance(training_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", training_id):
            raise InvalidRequestError("not a training id", code="invalid_request")
        return self._json(self._send("GET", f"/neuravision/catalogs/{self._slug(slug)}/trainings/{training_id}", idempotent=True))

    def versions(self, slug: str) -> List[Dict[str, Any]]:
        return self._list(self._payload(self._send("GET", f"/neuravision/catalogs/{self._slug(slug)}/versions", idempotent=True)))

    def publish(self, slug: str, version: str) -> Dict[str, Any]:
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", version):
            raise InvalidRequestError("not a version", code="invalid_request")
        response = self._send("POST", f"/neuravision/catalogs/{self._slug(slug)}/versions/{version}/publish", idempotent=True)
        return self._json(response) if response.content else {}
