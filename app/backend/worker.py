"""Servicio worker del motor NeuraVision (ECS, escala de 0 a N según la cola SQS de lecturas).

Arranque: (1) baja de S3 la versión de detector configurada (models_fetch), (2) espera a que la API deje la base lista,
(3) calienta el motor, (4) consume la cola: una lectura a la vez por worker. Mientras procesa, protege la tarea para que
el autoescalado no la apague a mitad. SIGTERM: termina la lectura en curso y sale. Un mensaje que falla 3 veces va a la
cola de errores (DLQ) por la política de la cola.

Uso (contenedor): python worker.py
"""
import json
import os
import signal
import sys
import time
import traceback
import urllib.request

os.environ.setdefault("ROLE", "worker")

import models_fetch  # noqa: E402  (antes de cargar el motor: fija NEURAVISION_RTDETR_PATH)

MODELS = models_fetch.prepare()

import api_jobs  # noqa: E402
import core  # noqa: E402
import db  # noqa: E402
import shadow  # noqa: E402

STOP = {"flag": False}
VISIBILITY_S = int(os.environ.get("WORKER_VISIBILITY_S", "900"))
POST_JOB_PROTECT_MIN = int(os.environ.get("WORKER_POST_JOB_PROTECT_MIN", "10"))  # 0 = liberar al terminar (comportamiento anterior)


def _on_term(*_):
    STOP["flag"] = True
    print("[worker] SIGTERM: termino la lectura en curso y salgo", flush=True)


def _protect(enabled: bool, minutes: int = 20) -> None:
    """Protección de tarea ECS (scale-in): mientras haya una lectura en curso el autoescalado no apaga esta tarea.
    También al arrancar (10 min): un worker encendido para una foto no se apaga antes de alcanzar a tomarla, aunque la
    alarma de cola vacía todavía no vea la foto (las métricas de SQS llegan con minutos de retraso)."""
    uri = os.environ.get("ECS_AGENT_URI")
    if not uri:
        return
    body = {"ProtectionEnabled": enabled}
    if enabled:
        body["ExpiresInMinutes"] = minutes
    try:
        req = urllib.request.Request(f"{uri}/task-protection/v1/state", data=json.dumps(body).encode(), method="PUT",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as exc:
        print(f"[worker] protección de tarea ({enabled}) falló: {exc}", flush=True)


def _wait_db_ready(timeout_s: int = 900) -> None:
    db.init_db("worker")
    if not db.USE_PG:
        return
    import pgcompat

    t0 = time.time()
    while not pgcompat.meta_get("ready"):
        if time.time() - t0 > timeout_s:
            raise RuntimeError("la base no quedó lista (la API no marcó meta.ready)")
        print("[worker] esperando a que la API deje la base lista…", flush=True)
        time.sleep(5)


def _handle(sqs, msg) -> None:
    try:
        job_id = json.loads(msg["Body"])["job_id"]
    except Exception:
        print(f"[worker] mensaje inválido, se descarta: {msg.get('Body')!r}", flush=True)
        sqs.delete_message(QueueUrl=api_jobs.QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
        return
    _protect(True)
    try:
        models_fetch.ensure_catalog()  # versión activa del catálogo (S3); cambia sin reiniciar el worker
        try:
            mem = core.shared_memory()
            if mem is not None and mem.maybe_reload():
                print(f"[worker] memoria visual recargada: {len(mem)} recortes", flush=True)
        except Exception as exc:
            print(f"[worker] no pude recargar la memoria visual: {exc}", flush=True)
        t0 = time.perf_counter()
        final = api_jobs.process_job(job_id)
        if final is None:
            print(f"[worker] {job_id}: ya no estaba en cola (duplicado o terminado)", flush=True)
        else:
            print(f"[worker] {job_id}: {final['status']} en {time.perf_counter() - t0:.1f} s"
                  + (f" · lectura {final.get('reading_id')}" if final.get("reading_id") else f" · {final.get('error')}"),
                  flush=True)
        sqs.delete_message(QueueUrl=api_jobs.QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
        if final is not None and final.get("reading_id"):
            shadow.run(final, final["reading_id"])
    finally:
        # Tras cada lectura la protección queda POST_JOB_PROTECT_MIN minutos más (no se libera al tiro): las métricas de
        # SQS llegan con minutos de retraso, y liberar enseguida hacía que la alarma de cola vacía apagara el worker
        # recién usado y que, un minuto después, la alarma de cola con lecturas (con el dato atrasado) encendiera otro
        # sin trabajo por 15 min (8-nov 15:18-15:34). Así además un local que sube franjas de a una no espera un arranque
        # nuevo entre foto y foto. La protección vence sola y el autoescalado apaga el worker como siempre.
        if POST_JOB_PROTECT_MIN > 0:
            _protect(True, minutes=POST_JOB_PROTECT_MIN)
        else:
            _protect(False)


def main() -> int:
    if not api_jobs.using_sqs():
        print("[worker] falta JOBS_QUEUE_URL", flush=True)
        return 2
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    _protect(True, minutes=10)  # arranque: se libera al terminar la primera lectura o a los 10 min
    _wait_db_ready()
    t0 = time.perf_counter()
    core.warm_up_engine()
    print(f"[worker] motor listo en {time.perf_counter() - t0:.0f} s · modelos {MODELS or 'de la imagen'} · "
          f"sombra {'sí' if shadow.enabled() else 'no'}", flush=True)
    if not core.ENGINE_STATE.get("ready"):
        print(f"[worker] el motor no cargó: {core.ENGINE_STATE.get('error')}", flush=True)
        return 1
    sqs = api_jobs._sqs()
    while not STOP["flag"]:
        try:
            res = sqs.receive_message(QueueUrl=api_jobs.QUEUE_URL, MaxNumberOfMessages=1, WaitTimeSeconds=20,
                                      VisibilityTimeout=VISIBILITY_S)
        except Exception as exc:
            print(f"[worker] error leyendo la cola: {exc}", flush=True)
            time.sleep(5)
            continue
        for msg in res.get("Messages", []):
            try:
                _handle(sqs, msg)
            except Exception:
                print("[worker] error inesperado (el mensaje vuelve a la cola):", flush=True)
                traceback.print_exc()
    print("[worker] fin", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
