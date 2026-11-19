"""Server-side Salcobrand API adapter. Credentials and cookies stay in this process."""
import hashlib
import json
import os
import re
import time
from urllib.parse import quote, urlsplit

import httpx
import db

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def base_url():
    value = os.environ.get("NEURAVISION_REMOTE_URL", "").rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ValueError("Configura una URL HTTPS válida para la API de análisis.")
    return value


def authenticate(client):
    import client_identity
    config = client_identity.model_config()
    if config['remoteOrgId']:
        key = os.environ.get(config['credentialEnv'],'')
        if not key:
            raise ValueError('Falta configurar la variable de integración del modelo en el servidor.')
        client.headers['X-API-Key'] = key
        response = client.get('/api/auth/me')
        try:
            authorized = response.status_code == 200 and response.json().get('org_id') == config['remoteOrgId']
        except (ValueError,AttributeError):
            authorized = False
        if not authorized:
            raise ValueError('La integración del modelo no corresponde a la organización configurada.')
        return
    username = os.environ.get('NEURAVISION_REMOTE_USERNAME','')
    password = os.environ.get('NEURAVISION_REMOTE_PASSWORD','')
    if not username or not password:
        raise ValueError('Falta configurar el acceso de servidor a la API de análisis.')
    response = client.post('/api/auth/login',json={'username':username,'password':password})
    if response.status_code != 200:
        raise ValueError('La API de análisis no autorizó el acceso configurado en el servidor.')


_HEALTH = {"at": 0.0, "value": None}
HEALTH_TTL_S = int(os.environ.get("NEURAVISION_REMOTE_HEALTH_TTL_S", "30"))


def health():
    """Cached: Kilby probes /health every few seconds, and each call used to poll the engine (≈25,000 calls a day)."""
    if _HEALTH["value"] is not None and time.monotonic() - _HEALTH["at"] < HEALTH_TTL_S:
        return _HEALTH["value"]
    _HEALTH.update(at=time.monotonic(), value=_health())
    return _HEALTH["value"]


def _health():
    ready = False
    try:
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = client.get(base_url() + "/v1/health")
            ready = response.status_code == 200 and response.json().get("engine_ready") is True
        import client_identity
        config = client_identity.model_config()
        configured = bool(os.environ.get(config['credentialEnv'])) if config['remoteOrgId'] else bool(os.environ.get("NEURAVISION_REMOTE_USERNAME") and os.environ.get("NEURAVISION_REMOTE_PASSWORD"))
        ready = ready and configured
    except (ValueError, httpx.HTTPError):
        pass
    return {"engine": "neuravision", "engine_ready": ready,
            "engine_error": None if ready else "La API de análisis no está disponible o falta configurar el acceso.",
            "components": {"mode": "remote-api"}, "warmup_s": None, "detector": "remoto", "ocr": "remoto"}


def json_response(response):
    content = bytearray()
    for chunk in response.iter_bytes():
        content.extend(chunk)
        if len(content) > MAX_RESPONSE_BYTES:
            raise ValueError("La respuesta de la API de análisis supera el tamaño permitido.")
    data = json.loads(content)
    if not isinstance(data, (dict, list)):
        raise ValueError("La API de análisis devolvió un resultado no válido.")
    return data


def checkpoint(job_id, **values):
    if job_id:
        with db.get_conn() as conn:
            row = conn.execute("SELECT payload_json FROM api_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row:
                payload = json.loads(row["payload_json"] or "{}")
                payload.update(values)
                conn.execute("UPDATE api_jobs SET payload_json = ? WHERE job_id = ?", (json.dumps(payload), job_id))


def get_point(client, point_id):
    with client.stream("GET", "/api/points/" + quote(point_id, safe="")) as response:
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return json_response(response)


def remote_point_id(local_point_id):
    configured = os.environ.get("NEURAVISION_REMOTE_POINT_MAP", "{}")
    mapping = json.loads(configured)
    prefix = os.environ.get("NEURAVISION_REMOTE_POINT_PREFIX", "MIGLOCAL-")
    point_id = mapping.get(local_point_id, prefix + local_point_id.upper())
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", point_id):
        raise ValueError("La vinculación de la góndola con la API no es válida.")
    return point_id


def ensure_point(client, local_point_id, point_id):
    existing = get_point(client, point_id)
    if existing is not None:
        return existing
    local = db.get_point(local_point_id)
    body = {"point_id": point_id, "name": "Migración local · " + local_point_id,
            "store_id": local.get("store_id") or "PDV-001", "gondola_id": point_id}
    response = client.post("/api/points", data=body)
    if response.status_code == 409:
        return get_point(client, point_id)
    response.raise_for_status()
    return response.json()


def normalized(reading, point_id, origin):
    if not isinstance(reading, dict) or reading.get("id") is None or not isinstance(reading.get("products"), list):
        raise ValueError("La API no devolvió una medición completa.")
    if reading.get("point_id") != point_id:
        raise ValueError("La medición recibida pertenece a otra góndola.")
    # db.add_reading consumes this engine-neutral analysis representation.
    result = {key: reading.get(key) for key in ("products", "categories", "total_facings", "shelf_levels_detected", "empty_space_pct", "notes")}
    result["categories"] = reading.get("categories") or []
    result["notes"] = reading.get("notes") or ""
    result["engine"] = {**(reading.get("engine") or {}),
                        "remote": {"base_url": origin, "point_id": point_id, "reading_id": reading["id"]}}
    result["is_pharmacy_shelf"] = True
    return result


def recover(client, point_id, baseline, deadline):
    while time.monotonic() < deadline:
        try:
            point = get_point(client, point_id)
        except httpx.HTTPError:
            time.sleep(3)
            continue
        readings = point.get("readings", []) if point else []
        newer = [r for r in readings if isinstance(r.get("id"), int) and r["id"] > baseline]
        if newer:
            return min(newer, key=lambda row: row["id"])
        time.sleep(3)
    raise ValueError("La API continúa procesando o no confirmó el resultado. Recupera esta solicitud antes de volver a cargar las fotos.")


def sync_plan(client, point, point_id, snapshot):
    plan_id = None
    if snapshot:
        fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()[:24]
        plan_id = "MIGLOCAL-PG-" + fingerprint
        response = client.get("/api/planograms/" + plan_id)
        if response.status_code == 404:
            fields = ("order_seq", "section_label", "module", "band", "segment", "position_in_section", "title", "internal_code", "barcode", "expected_facings", "tag")
            payload = {"id": plan_id, "name": snapshot["name"], "bands": snapshot.get("bands"),
                       "module_cm": snapshot.get("module_cm"), "source_filename": snapshot.get("source_filename"),
                       "items": [{key: item.get(key) for key in fields} for item in snapshot["items"]]}
            created = client.post("/api/admin/planograms", json=payload)
            if created.status_code != 409:
                created.raise_for_status()
        else:
            response.raise_for_status()
    if point.get("planogram_id") != plan_id:
        assigned = client.put("/api/points/" + quote(point_id, safe="") + "/planogram", json={"planogram_id": plan_id})
        assigned.raise_for_status()


def analyze(local_point_id, images, linear_meters=None, job_id=None, plan_snapshot=None):
    origin = base_url()
    timeout = httpx.Timeout(connect=15, read=90, write=90, pool=15)
    with httpx.Client(base_url=origin, timeout=timeout, follow_redirects=False, trust_env=False) as client:
        authenticate(client)
        prior = db.get_job(job_id)["payload"] if job_id else {}
        point_id = prior.get("remote_point_id") or remote_point_id(local_point_id)
        point = ensure_point(client, local_point_id, point_id)
        baseline = prior.get("remote_baseline_id", max((r["id"] for r in point.get("readings", [])), default=0))
        deadline = time.monotonic() + int(os.environ.get("NEURAVISION_REMOTE_TIMEOUT_S", "900"))
        if prior.get("remote_submitted"):
            reading = recover(client, point_id, baseline, deadline)
            return normalized(reading, point_id, origin)
        sync_plan(client, point, point_id, plan_snapshot)
        checkpoint(job_id, remote_point_id=point_id, remote_baseline_id=baseline, remote_submitted=True)
        files = [("images", (f"capture-{index+1}.jpg", content, mime)) for index, (content, mime) in enumerate(images)]
        fields = {"linear_meters": str(linear_meters)} if linear_meters is not None else {}
        try:
            with client.stream("POST", "/api/points/" + quote(point_id, safe="") + "/analyze", files=files, data=fields) as response:
                if 400 <= response.status_code < 500:
                    checkpoint(job_id, remote_final_failed=True)
                    raise ValueError("La API rechazó la captura. Revisa el formato de las fotos y el acceso configurado.")
                response.raise_for_status()
                result = json_response(response)
            if result.get("id") is None:
                if result.get("job_id"):
                    result = recover(client, point_id, baseline, deadline)
                else:
                    checkpoint(job_id, remote_final_failed=True)
                    detail = result.get("detail")
                    raise ValueError(detail[:300] if isinstance(detail, str) else "El motor no pudo analizar estas fotos.")
        except httpx.HTTPError:
            # An interrupted response may already have created a measurement.
            result = recover(client, point_id, baseline, deadline)
        return normalized(result, point_id, origin)
