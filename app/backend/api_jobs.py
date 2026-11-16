"""Cola de análisis (API v1 y app de tienda): tabla `api_jobs` + quien procese.

- Producción (JOBS_QUEUE_URL): el job se guarda en la base y su id va a una cola SQS; lo procesa el servicio worker
  (worker.py), que escala de 0 a N según la cola. La API no corre el motor.
- Desarrollo / sin cola: UN hilo trabajador dentro del proceso, como antes.
El motor es CPU-bound (una foto a la vez por worker). Los jobs viven 7 días. client_id "app" = lecturas de la app.
"""
import json
import os
import queue
import secrets
import threading
import time
import traceback
from typing import Optional

import api_telemetry
import core
import db

JOB_TTL_DAYS = 7
PURGE_EVERY_S = 3600

_queue = queue.Queue()
_lock = threading.Lock()
_thread = None  # type: Optional[threading.Thread]
STATE = {"started": False, "current": None, "done": 0, "failed": 0}


def new_job_id() -> str:
    """SPEC §7: `j_` + 16 hex."""
    return "j_" + secrets.token_hex(8)


QUEUE_URL = os.environ.get("JOBS_QUEUE_URL", "").strip()
APP_CLIENT = "app"
_sqs_client = None


def using_sqs() -> bool:
    return bool(QUEUE_URL)


def _sqs():
    global _sqs_client
    if _sqs_client is None:
        import boto3

        _sqs_client = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _sqs_client


WORKER_SERVICE = os.environ.get("WORKER_SERVICE", "").strip()
ECS_CLUSTER = os.environ.get("ECS_CLUSTER", "neuramorphic")
_wake = {"last": 0.0}


def wake_worker() -> None:
    """Si no hay ningún worker encendido, enciende uno ya (sin esperar a que la alarma de la cola lo note: las métricas
    de SQS llegan con minutos de retraso). El autoescalado lo vuelve a apagar cuando la cola queda vacía."""
    if not WORKER_SERVICE or time.time() - _wake["last"] < 20:
        return
    _wake["last"] = time.time()
    try:
        import boto3

        ecs = boto3.client("ecs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        svc = ecs.describe_services(cluster=ECS_CLUSTER, services=[WORKER_SERVICE])["services"][0]
        if svc.get("desiredCount", 0) == 0:
            ecs.update_service(cluster=ECS_CLUSTER, service=WORKER_SERVICE, desiredCount=1)
            print("[api-jobs] worker apagado: se enciende uno", flush=True)
    except Exception as exc:  # la alarma de la cola igual lo enciende
        print(f"[api-jobs] no pude encender el worker: {exc}", flush=True)


def _dispatch(job_id: str) -> None:
    if using_sqs():
        _sqs().send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps({"job_id": job_id}))
        wake_worker()
    else:
        _queue.put(job_id)


def enqueue(client_id: str, point_id: str, payload: dict) -> dict:
    """payload: image_paths (ya guardadas), linear_meters, planogram_id, key_id, request_id, evt_sk, day, via."""
    import catalog_service
    payload = {**payload, "plan_snapshot": catalog_service.job_snapshot(payload.get("planogram_id"))}
    job = db.create_job(new_job_id(), client_id, point_id, payload)
    _dispatch(job["job_id"])
    return job


def queue_depth() -> int:
    if using_sqs():
        try:
            a = _sqs().get_queue_attributes(QueueUrl=QUEUE_URL, AttributeNames=["ApproximateNumberOfMessages"])["Attributes"]
            return int(a.get("ApproximateNumberOfMessages", 0))
        except Exception:
            return -1
    return _queue.qsize()


def worker_alive() -> bool:
    if using_sqs():
        return True  # el worker es otro servicio (escala desde 0); la API solo encola
    return bool(_thread and _thread.is_alive())


def resend_pending(older_than_s: int = 120) -> int:
    """API con SQS, al arrancar: jobs 'queued' que no alcanzaron a ir a la cola (p. ej. creados justo en la migración)
    se vuelven a enviar. Un duplicado no hace daño: set_job_running lo descarta."""
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_s)).isoformat()
    n = 0
    for job_id in db.queued_job_ids():
        job = db.get_job(job_id)
        if job and job["created_at"] < cutoff:
            _dispatch(job_id)
            n += 1
    return n


def start_worker() -> None:
    """Idempotente: arranca el hilo (daemon) y recupera lo pendiente en la base. Con SQS no arranca hilo: reenvía lo
    pendiente a la cola y deja el motor al servicio worker."""
    global _thread
    if using_sqs():
        try:
            purged = db.purge_old_jobs(JOB_TTL_DAYS)
            resent = resend_pending()
            print(f"[api-jobs] modo SQS: la API solo encola; {resent} pendientes reenviados, {purged} purgados", flush=True)
        except Exception as exc:
            print(f"[api-jobs] no se pudo revisar la cola: {exc}", flush=True)
        STATE["started"] = True
        return
    with _lock:
        if _thread and _thread.is_alive():
            return
        purged = requeued = 0
        pending = []
        try:
            purged = db.purge_old_jobs(JOB_TTL_DAYS)
            requeued = db.requeue_running_jobs()
            pending = db.queued_job_ids()
        except Exception as exc:
            print(f"[api-jobs] no se pudo recuperar la cola: {exc}", flush=True)
        for job_id in pending:
            _queue.put(job_id)
        _thread = threading.Thread(target=_loop, name="api-jobs-worker", daemon=True)
        _thread.start()
        STATE["started"] = True
        print(f"[api-jobs] trabajador iniciado: {len(pending)} en cola ({requeued} reencolados), {purged} purgados", flush=True)


def _loop() -> None:
    last_purge = time.time()
    while True:
        job_id = _queue.get()
        try:
            process_job(job_id)
        except Exception:
            print(f"[api-jobs] error inesperado en {job_id}:", flush=True)
            traceback.print_exc()
        finally:
            _queue.task_done()
        if time.time() - last_purge > PURGE_EVERY_S:
            last_purge = time.time()
            try:
                db.purge_old_jobs(JOB_TTL_DAYS)
            except Exception as exc:
                print(f"[api-jobs] purga falló: {exc}", flush=True)


def process_job(job_id: str) -> Optional[dict]:
    """Corre un job (en el hilo trabajador). Devuelve el job final o None si ya no estaba en cola."""
    if not db.set_job_running(job_id):
        return None
    job = db.get_job(job_id)
    p = job["payload"]
    STATE["current"] = job_id
    t0 = time.perf_counter()
    reading, error, engine_ms = None, None, None
    try:
        loaded = core.load_images_from_disk(p.get("image_paths") or [])
        reading, engine_ms = core.analyze_and_store(job["point_id"], loaded, p.get("linear_meters"), p.get("planogram_id"),
                                                    image_paths=p.get("image_paths") or [], captured_by=p.get("user"), capture_context=p.get("infrastructure"), plan_snapshot=p.get("plan_snapshot"), job_id=job_id)
    except core.AnalysisRejected as exc:
        error = str(exc)[:300]
    except Exception as exc:
        error = f"engine_error: {type(exc).__name__}: {exc}"[:300]
        traceback.print_exc()
    if engine_ms is None:
        engine_ms = int((time.perf_counter() - t0) * 1000)
    if reading is not None:
        db.finish_job(job_id, "done", reading_id=reading["id"], engine_ms=engine_ms)
        STATE["done"] += 1
    else:
        db.finish_job(job_id, "failed", error=error, engine_ms=engine_ms)
        STATE["failed"] += 1
        latest = db.get_job(job_id)["payload"]
        if not latest.get("remote_submitted") or latest.get("remote_final_failed"):
            core.delete_uploads(p.get("image_paths") or [])
    STATE["current"] = None

    fields = {"job_id": job_id, "job_status": "done" if reading is not None else "failed", "engine_ms": engine_ms, "error": error}
    if reading is not None:
        fields.update({"reading_id": reading["id"], "facings": reading.get("total_facings"),
                       "products": len(reading.get("products") or []), "needs_review": reading.get("needs_review"),
                       "levels": reading.get("shelf_levels_detected")})
    if job["client_id"] != APP_CLIENT:
        api_telemetry.job_finished(job["client_id"], p.get("evt_sk"), p.get("day") or job["created_at"][:10], job_id, fields,
                                   failed=reading is None)
    return db.get_job(job_id)
