"""Session-authenticated capture jobs with persisted idempotency and scoped recovery."""
import hashlib
import json
import logging
import math
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
import api_jobs
import catalog_service
import core
import db
import infrastructure
import profiles
import capture_selection

logger = logging.getLogger(__name__)


def authorized_job(job_id, user, authorize_point):
    job = db.get_job(job_id)
    if not job or job["client_id"] != api_jobs.APP_CLIENT:
        raise HTTPException(404, "Solicitud de análisis no encontrada.")
    if job["payload"].get("user") != user["username"] and not profiles.can(user, "manage"):
        raise HTTPException(404, "Solicitud de análisis no encontrada.")
    authorize_point(job["point_id"], user)
    return job


def public_job(job):
    result = {key: job.get(key) for key in ("job_id", "point_id", "status", "created_at", "started_at", "finished_at", "engine_ms")}
    result["can_recover"] = bool(job["status"] == "failed" and job["payload"].get("remote_submitted") and not job["payload"].get("remote_final_failed"))
    if job["status"] == "done":
        result["reading"] = db.get_reading(job["reading_id"]) if job.get("reading_id") else None
    if job["status"] == "failed":
        error = job.get("error") or "No se pudo analizar la captura."
        result["detail"] = error.split(": ", 2)[-1] if error.startswith("engine_error:") else error
    return result


def existing_request(key, fingerprint):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM management_capture_requests WHERE request_key = ?", (key,)).fetchone()
    if row and row["fingerprint"] != fingerprint:
        raise HTTPException(409, "Esta solicitud ya se utilizó con otras fotos o con otra góndola.")
    job = db.get_job(row["job_id"]) if row else None
    if row and not job:
        raise HTTPException(410, "Esta solicitud caducó. Consulta el historial antes de iniciar otra captura.")
    return job


def submit(point_id, images, meters, user, request_id, selection=None, manual_store=None, manual_override=False, geometry=None, by_type=False, manual_reference=False):
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", request_id or ""):
        raise HTTPException(400, "La captura necesita un identificador de solicitud válido.")
    key = hashlib.sha256((user["username"] + ":" + request_id).encode()).hexdigest()
    values = {"point": point_id, "meters": meters,
              "images": [(mime, hashlib.sha256(content).hexdigest()) for content, mime in images]}
    if geometry:
        values['geometry'] = geometry
    if manual_override:
        values['manual_override'] = True
    if by_type:
        values['by_type'] = True
    if selection:
        values['selection'] = selection
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    prior = existing_request(key, fingerprint)
    if prior:
        return public_job(prior)
    context = {} if manual_store else (infrastructure.capture_context(point_id) or {})
    context.update(selection or {})
    if manual_store:
        context.update(captureMode='manual', manualWidthCm=meters * 100 if meters is not None else None)
        context.update(geometry or {})
        if geometry:
            context['width_cm'] = meters * 100 if meters is not None else None
    paths = []
    created = False
    try:
        for content, mime in images:
            paths.append(core.save_upload(point_id, content, mime))
        with db.get_conn() as conn:
            catalog_service.lock_catalog(conn)
            duplicate = conn.execute("SELECT * FROM management_capture_requests WHERE request_key = ?", (key,)).fetchone()
            if duplicate:
                if duplicate["fingerprint"] != fingerprint:
                    raise HTTPException(409, "El identificador de captura ya se utilizó con otras fotos.")
                job_id = duplicate["job_id"]
            else:
                capture_selection.validate_selection(selection or {}, conn)
                if manual_store:
                    capture_selection.manual_store(conn, manual_store, manual_override)
                    if manual_reference:
                        reference = infrastructure.capture_context(point_id)
                        point = db.get_point(point_id)
                        if not reference or point.get('store_id') != manual_store:
                            raise HTTPException(409, 'La referencia ya no está disponible en este PDV.')
                if core.remote_enabled():
                    pending = conn.execute("SELECT status, payload_json FROM api_jobs WHERE point_id = ? AND status IN ('queued', 'running', 'failed')", (point_id,)).fetchall()
                    for row in pending:
                        payload = json.loads(row["payload_json"] or "{}")
                        recovering = payload.get("remote_submitted") and not payload.get("remote_final_failed")
                        if row["status"] != "failed" or recovering:
                            raise HTTPException(409, "Esta góndola tiene una captura pendiente. Espera su resultado o recupera la solicitud anterior antes de enviar otra.")
                if by_type:
                    context = infrastructure.capture_context(point_id) or {}
                    if not context.get('type_id'):
                        raise HTTPException(409, 'Selecciona un tipo precargado del PDV.')
                    context.update(selection or {})
                    context['captureMode'] = 'type'
                    meters = context['width_cm'] / 100
                point = db.get_point(point_id)
                import client_identity
                plan_id = point.get('planogram_id') if client_identity.public_identity(conn)['tenant']['modules']['planograms'] else None
                plan_snapshot = db.get_planogram(plan_id) if plan_id else None
                if plan_snapshot and plan_snapshot.get('category'):
                    context.pop('subcategory', None)
                    context.update(category=plan_snapshot['category'], subcategories=plan_snapshot.get('subcategories', []))
                payload = {"image_paths": paths, "linear_meters": meters, "planogram_id": plan_id,
                           "plan_snapshot": plan_snapshot,
                           "infrastructure": context, "user": user["username"], "via": "app"}
                job_id = api_jobs.new_job_id()
                db.insert_job(conn, job_id, api_jobs.APP_CLIENT, point_id, payload)
                conn.execute("INSERT INTO management_capture_requests (request_key, submitted_by, point_id, fingerprint, job_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                             (key, user["username"], point_id, fingerprint, job_id, db.now_iso()))
                created = True
    except Exception:
        core.delete_uploads(paths)
        raise
    if created:
        try:
            api_jobs._dispatch(job_id)
        except Exception:
            logger.exception("No se pudo enviar a la cola el job persistido %s", job_id)
    else:
        core.delete_uploads(paths)
    return public_job(db.get_job(job_id))


def router(require_user, require_scan, authorize_point):
    api = APIRouter(prefix="/api", tags=["Captura y mediciones"])

    @api.get('/capture/planograms')
    def planograms(store: str, category: str = '', subcategories: Optional[List[str]] = Query(None), user=Depends(require_scan)):
        return JSONResponse(capture_selection.reference_plans(user, store, category, subcategories or []), headers={'Cache-Control':'no-store'})

    @api.get('/capture/planograms/{plan_id}')
    def planogram_reference(plan_id: str, store: str, user=Depends(require_scan)):
        return JSONResponse(capture_selection.reference_plans(user, store, plan_id=plan_id), headers={'Cache-Control':'no-store'})

    @api.get('/capture/options')
    def options(user=Depends(require_scan)):
        return capture_selection.options(user)

    @api.post('/stores/{store_code}/analysis-jobs', status_code=202)
    async def manual(store_code: str, images: List[UploadFile] = File(...), linear_meters: Optional[float] = Form(None),
                     manual_override: bool = Form(False), reference_point_id: str = Form(''), levels: Optional[int] = Form(None), depths: Optional[List[float]] = Form(None),
                     category: str = Form(''), subcategory: str = Form(''), subcategories: Optional[List[str]] = Form(None),
                     request_id: str = Header(alias='Idempotency-Key'), user=Depends(require_scan)):
        scope = profiles.store_scope(user)
        if scope is not None and store_code not in scope:
            raise HTTPException(403, 'El PDV está fuera de tu ámbito.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', request_id or ''):
            raise HTTPException(400, 'La captura necesita un identificador de solicitud válido.')
        if linear_meters is not None and (not math.isfinite(linear_meters) or not 0 < linear_meters <= 30):
            raise HTTPException(400, 'El ancho debe ser mayor a cero y hasta 30 metros.')
        values = capture_selection.selection(category, subcategory, subcategories)
        dimensions = capture_selection.geometry(levels, depths)
        try:
            loaded = await core.read_image_uploads(images, max_bytes_each=25*1024*1024, max_bytes_total=100*1024*1024)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if reference_point_id:
            if not manual_override:
                raise HTTPException(400, 'Activa las medidas manuales para conservar una referencia precargada.')
            authorize_point(reference_point_id, user)
            reference = await run_in_threadpool(infrastructure.capture_context, reference_point_id)
            point = db.get_point(reference_point_id)
            if not reference or point.get('store_id') != store_code:
                raise HTTPException(403, 'La referencia no pertenece al PDV seleccionado.')
            point_id = reference_point_id
        else:
            point_id = await run_in_threadpool(capture_selection.manual_point, store_code, user, values, manual_override)
        return await run_in_threadpool(submit, point_id, loaded, linear_meters, user, request_id, values, store_code, manual_override, dimensions, False, bool(reference_point_id))

    @api.get("/capture/status")
    def status(user=Depends(require_user)):
        health = core.engine_health()
        return {"available": health["engine_ready"], "mode": health.get("components", {}).get("mode") if health.get("components") else "embedded",
                "detail": health.get("engine_error"), "max_photos": core.MAX_IMAGES}

    @api.post("/points/{point_id}/analysis-jobs", status_code=202)
    async def create(point_id: str, images: List[UploadFile] = File(...), linear_meters: Optional[float] = Form(None), by_type: bool = Form(False),
                     category: str = Form(''), subcategory: str = Form(''), subcategories: Optional[List[str]] = Form(None),
                     request_id: str = Header(alias="Idempotency-Key"), user=Depends(require_scan)):
        authorize_point(point_id, user)
        if point_id.startswith(capture_selection.MANUAL_PREFIX):
            raise HTTPException(400, 'Usa la captura con ancho manual desde el PDV.')
        if linear_meters is not None and (not math.isfinite(linear_meters) or not 0 < linear_meters <= 30):
            raise HTTPException(400, "El ancho debe ser mayor a cero y hasta 30 metros.")
        try:
            loaded = await core.read_image_uploads(images, max_bytes_each=25*1024*1024, max_bytes_total=100*1024*1024)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return await run_in_threadpool(submit, point_id, loaded, linear_meters, user, request_id, capture_selection.selection(category, subcategory, subcategories), None, False, None, by_type)

    @api.get("/analysis-jobs")
    def active(user=Depends(require_user)):
        with db.get_conn() as conn:
            rows = conn.execute("SELECT j.job_id FROM api_jobs j JOIN management_capture_requests c ON c.job_id = j.job_id WHERE c.submitted_by = ? AND j.status IN ('queued', 'running') ORDER BY j.created_at DESC LIMIT 10", (user["username"],)).fetchall()
        result = []
        for row in rows:
            try:
                result.append(public_job(authorized_job(row["job_id"], user, authorize_point)))
            except HTTPException:
                continue
        return result

    @api.get("/analysis-jobs/{job_id}")
    def get(job_id: str, user=Depends(require_user)):
        return public_job(authorized_job(job_id, user, authorize_point))

    @api.get("/analysis-requests/{request_id}")
    def request_status(request_id: str, user=Depends(require_user)):
        key = hashlib.sha256((user["username"] + ":" + request_id).encode()).hexdigest()
        with db.get_conn() as conn:
            row = conn.execute("SELECT job_id FROM management_capture_requests WHERE request_key = ?", (key,)).fetchone()
        if not row:
            raise HTTPException(404, "La carga todavía no tiene una solicitud confirmada.")
        return public_job(authorized_job(row["job_id"], user, authorize_point))

    @api.post("/analysis-jobs/{job_id}/resume", status_code=202)
    def resume(job_id: str, user=Depends(require_scan)):
        job = authorized_job(job_id, user, authorize_point)
        if not public_job(job)["can_recover"]:
            raise HTTPException(409, "Esta solicitud no requiere recuperación.")
        with db.get_conn() as conn:
            changed = conn.execute("UPDATE api_jobs SET status = 'queued', error = NULL, started_at = NULL, finished_at = NULL WHERE job_id = ? AND status = 'failed'", (job_id,)).rowcount
        if changed:
            api_jobs._dispatch(job_id)
        return public_job(db.get_job(job_id))

    return api
