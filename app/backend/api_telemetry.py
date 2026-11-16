"""Telemetría de la API v1 (SPEC §4): un evento por llamada → DynamoDB (evt# + agg#), línea de log `[api-evt] {json}`
y métricas CloudWatch (namespace NeuraVision/API, dimensiones Client + Endpoint).

Nada de aquí lanza hacia el request: los errores se registran y se sigue. En producción las escrituras van por un
hilo aparte (no suman latencia a la respuesta); con APIS_STORE=memory son síncronas (pruebas deterministas).
"""
import json
import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import apis_store

METRICS_NAMESPACE = "NeuraVision/API"
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="api-telemetry")
_cw = {"client": None}
_cw_lock = threading.Lock()


def _sync() -> bool:
    flag = os.environ.get("APIS_TELEMETRY_SYNC")
    if flag is not None:
        return flag.strip() not in ("0", "", "false", "no")
    return apis_store.store_kind() == "memory"


def _guarded(fn, *args):
    try:
        fn(*args)
    except Exception:
        print("[api-telemetry] error:", flush=True)
        traceback.print_exc()


def submit(fn, *args) -> None:
    if _sync():
        _guarded(fn, *args)
    else:
        _pool.submit(_guarded, fn, *args)


def _log_json(tag: str, payload: dict) -> None:
    print(f"[{tag}] " + json.dumps(payload, ensure_ascii=False, default=str), flush=True)


# ---------------------------------------------------------------------------
# evento de una llamada
# ---------------------------------------------------------------------------

def emit_event(evt: dict) -> None:
    """Línea de log siempre; DynamoDB + agregados + CloudWatch solo si la llamada se atribuyó a un cliente."""
    _log_json("api-evt", evt)
    if not evt.get("client_id"):
        return
    submit(_persist_event, evt)


def _persist_event(evt: dict) -> None:
    store = apis_store.get_store()
    store.record_event(evt)
    # caras/por revisar las suma el job al terminar (así no se cuentan dos veces en la ruta con `wait`)
    agg = {k: v for k, v in evt.items() if k not in ("facings", "needs_review")}
    store.add_aggregates(evt["client_id"], str(evt["ts"])[:10], agg, call=True)
    put_metrics(evt["client_id"], evt.get("endpoint") or "?", int(evt.get("status") or 0),
                int(evt.get("latency_ms") or 0), int(evt.get("photos") or 0))


# ---------------------------------------------------------------------------
# cierre de un job (enriquece el evento de POST /v1/analyze y suma caras al día)
# ---------------------------------------------------------------------------

def job_finished(client_id: str, evt_sk: Optional[str], day: str, job_id: str, fields: dict, failed: bool) -> None:
    _log_json("api-job", {"client_id": client_id, "job_id": job_id, "failed": failed, **fields})
    submit(_persist_job, client_id, evt_sk, day, fields, failed)


def _persist_job(client_id: str, evt_sk: Optional[str], day: str, fields: dict, failed: bool) -> None:
    store = apis_store.get_store()
    store.update_event(client_id, evt_sk, fields)
    store.add_aggregates(client_id, day, {"facings": fields.get("facings"), "needs_review": fields.get("needs_review"),
                                          "job_failed": failed}, call=False)


# ---------------------------------------------------------------------------
# CloudWatch
# ---------------------------------------------------------------------------

def put_metrics(client_id: str, endpoint: str, status: int, latency_ms: int, photos: int) -> None:
    """Calls / Errors / LatencyMs / Photos por Client + Endpoint. Se omite con APIS_STORE=memory; nunca lanza."""
    if apis_store.store_kind() == "memory" or os.environ.get("APIS_METRICS", "1") == "0":
        return
    try:
        if _cw["client"] is None:
            with _cw_lock:
                if _cw["client"] is None:
                    import boto3

                    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
                    _cw["client"] = boto3.client("cloudwatch", region_name=region)
        dims = [{"Name": "Client", "Value": client_id}, {"Name": "Endpoint", "Value": endpoint}]
        data = [
            {"MetricName": "Calls", "Dimensions": dims, "Value": 1, "Unit": "Count"},
            {"MetricName": "Errors", "Dimensions": dims, "Value": 1 if status >= 400 else 0, "Unit": "Count"},
            {"MetricName": "LatencyMs", "Dimensions": dims, "Value": float(latency_ms), "Unit": "Milliseconds"},
        ]
        if photos:
            data.append({"MetricName": "Photos", "Dimensions": dims, "Value": photos, "Unit": "Count"})
        _cw["client"].put_metric_data(Namespace=METRICS_NAMESPACE, MetricData=data)
    except Exception as exc:
        print(f"[api-telemetry] CloudWatch falló: {type(exc).__name__}: {exc}", flush=True)
