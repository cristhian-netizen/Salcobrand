import os
import csv
import functools
import io
import re
import sqlite3
import shutil
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import api_jobs
import api_v1
import auth
import image_cache
import captures
import vivo
import core
import db
import shadow
import storage
import profiles
import infrastructure
import management_api
import catalog_api
import catalog_service
import capture_api
import report_api
import analysis_usage_api
import settings_api
import reading_details_api
import dashboard_api
import alerts_api
import store_excel_api

load_dotenv()
db.init_db()
infrastructure.bootstrap_legacy_stores()

app = FastAPI(title="Salcobrand - Control de Inventario de Farmacia")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthPayload(BaseModel):
    username: str
    password: str
    code: Optional[str] = None   # código de invitación (registro)


class PlanogramAssignPayload(BaseModel):
    planogram_id: Optional[str] = None


class PlanogramPricesPayload(BaseModel):
    prices: dict


class PlanogramItemPayload(BaseModel):
    order_seq: int
    section_label: str
    module: int
    band: int
    segment: int
    position_in_section: int
    title: str
    internal_code: Optional[str] = None
    barcode: Optional[str] = None
    expected_facings: int
    tag: Optional[str] = None


class PlanogramCreatePayload(BaseModel):
    id: str
    name: str
    module_cm: Optional[int] = None
    bands: Optional[int] = None
    source_filename: Optional[str] = None
    items: List[PlanogramItemPayload]


class ConfirmPayload(BaseModel):
    image_index: int
    item_index: int
    title: Optional[str] = None      # título del planograma confirmado; None/"" = fuera de planograma
    facings: Optional[int] = None
    verdict: Optional[str] = None    # 'no_identificable' = detectado pero el envase no se distingue
    reason: Optional[str] = None     # con ese verdict: al_reves | tapado | borroso | no_producto | otro


class StockActionPayload(BaseModel):
    planogram_item_id: Optional[int] = None
    product_title: str
    action_type: str  # "solicitud" | "ajuste_robo"
    quantity: int
    note: Optional[str] = None


class SupplierStockoutPayload(BaseModel):
    planogram_item_id: int
    product_title: str
    note: Optional[str] = None


def _session_cookie_name(request: Request) -> str:
    selector = request.headers.get('x-portal-session')
    if selector is None:
        selector = request.query_params.get('portal_session')
    if selector is None:
        return auth.SESSION_COOKIE  # Existing pilot/legacy clients.
    if not re.fullmatch(r'[a-f0-9]{32}', selector):
        raise HTTPException(400, 'Identificador de sesión de pestaña inválido.')
    return auth.SESSION_COOKIE + '_' + selector


def require_auth(request: Request) -> str:
    # An explicit tab selector must never fall back to another tab/legacy cookie.
    token = request.cookies.get(_session_cookie_name(request))
    username = auth.verify_session_token(token) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    return username


def require_account(request: Request) -> dict:
    """Usuario de la sesión con su rol y local: {username, role, store_id, store_name}."""
    return _account_state(require_auth(request), request)


def _account_state(username: str, request: Request) -> dict:
    u = db.get_user(username)
    if not u:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    import people_service
    status = people_service.account_status(u['username'])
    if status == 'De baja':
        raise HTTPException(status_code=403, detail='La cuenta está de baja.')
    if status == 'Suspendido' and request.method not in ('GET','HEAD','OPTIONS'):
        raise HTTPException(status_code=403, detail='Tu cuenta está suspendida y permite solo consultas.')
    profile = profiles.profile_of(u)
    if profile in profiles.INTERNAL_PROFILES and not u.get('is_internal'):
        raise HTTPException(403, 'El perfil de proveedor requiere una cuenta interna.')
    if profile is None:
        raise HTTPException(status_code=403, detail="El perfil de la cuenta no está habilitado")
    return {"username": u["username"], "role": u["role"], "profile": profile, 'read_only':status == 'Suspendido', 'status':status,
            'internal':bool(u.get('is_internal')), 'portal_access':bool(u.get('portal_access',1)),
            "store_id": u.get("store_id"), "store_name": u.get("store_name"), "store_ids": u.get("store_ids", []),
            "permissions": [action for action in profiles.PERMISSIONS if profiles.can({**u, 'read_only':status == 'Suspendido'}, action)],
            "environment": os.environ.get("NEURAVISION_ENVIRONMENT")}


def require_user(request: Request) -> dict:
    return _portal_user(require_account(request))


def _portal_user(user: dict) -> dict:
    if not user['portal_access']:
        raise HTTPException(status_code=403,detail='Esta cuenta tiene acceso a la consola interna.')
    import client_identity
    if not client_identity.public_identity()['active']:
        raise HTTPException(status_code=403,detail='El cliente está inactivo.')
    return user


_TAB_COOKIE = re.compile(re.escape(auth.SESSION_COOKIE) + r'_[a-f0-9]{32}$')


def _image_cookie_names(request: Request) -> list:
    return [auth.SESSION_COOKIE, *sorted(name for name in request.cookies if _TAB_COOKIE.fullmatch(name))]


def _has_image_session(request: Request) -> bool:
    if request.headers.get('x-portal-session') is not None or request.query_params.get('portal_session') is not None:
        return bool(request.cookies.get(_session_cookie_name(request)))
    return any(request.cookies.get(name) for name in _image_cookie_names(request))


def require_image_user(request: Request) -> dict:
    """Images authenticate with the HttpOnly session cookie alone. An explicit tab selector (header or query
    parameter) keeps its strict per-tab meaning, for the capture links and older clients that still send it; an
    image URL without one accepts any valid session cookie of the browser (legacy cookie first, then the per-tab
    cookies in stable order). Without the per-tab query parameter the URL is identical in every tab, so the
    browser cache finally works for photos and crops."""
    if request.headers.get('x-portal-session') is not None or request.query_params.get('portal_session') is not None:
        return require_user(request)
    for name in _image_cookie_names(request):
        username = auth.verify_session_token(request.cookies.get(name) or '')
        if username:
            return _portal_user(_account_state(username, request))
    raise HTTPException(status_code=401, detail="Sesión inválida o expirada")


def require_internal(user: dict = Depends(require_account)):
    if not user['internal'] or profiles.profile_of(user) in profiles.INTERNAL_PROFILES:
        raise HTTPException(status_code=403,detail='Consola exclusiva del equipo interno de Neuramorphic.')
    return user


def permission(action):
    def check(user: dict = Depends(require_user)):
        if not profiles.can(user, action):
            raise HTTPException(status_code=403, detail="Tu perfil no permite esta acción")
        return user
    return check


require_scan = permission("scan")
require_review = permission("review")
require_training = permission("train")
require_report = permission("report")
require_dashboard = permission("dashboard")
require_resolve = permission("resolve")


def require_training_image(request: Request) -> dict:
    """Dataset photo URLs authenticate like other images (HttpOnly cookie, any tab) but stay provider-only.
    The browser holds one session per profile tab, and an <img> sends them all without choosing: the first
    cookie is not the verdict. Any of the browser's valid sessions that may train lets the photo load; with
    sessions but none that trains it is the profile refusal, and with no session at all it is 401."""
    if request.headers.get('x-portal-session') is not None or request.query_params.get('portal_session') is not None:
        user = require_user(request)
        if not profiles.can(user, "train"):
            raise HTTPException(status_code=403, detail="Tu perfil no permite esta acción")
        return user
    any_session = False
    for name in _image_cookie_names(request):
        username = auth.verify_session_token(request.cookies.get(name) or '')
        if username:
            any_session = True
            user = _portal_user(_account_state(username, request))
            if profiles.can(user, "train"):
                return user
    if any_session:
        raise HTTPException(status_code=403, detail="Tu perfil no permite esta acción")
    raise HTTPException(status_code=401, detail="Sesión inválida o expirada")


def require_staff(user: dict = Depends(require_user)) -> dict:
    """Configuration and capture links belong to Administrador only."""
    if not profiles.can(user, "manage"):
        raise HTTPException(status_code=403, detail="Solo el administrador gestiona esta configuración")
    return user


def require_admin(user: dict = Depends(require_user)) -> dict:
    if not profiles.can(user, "manage"):
        raise HTTPException(status_code=403, detail="Solo administradores")
    return user


def store_scope(user: dict):
    """None = unrestricted; tuple = assigned PDV; empty tuple = no PDV."""
    return profiles.store_scope(user)


@app.exception_handler(infrastructure.ManagementError)
async def management_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


app.include_router(management_api.router(require_user, require_admin))
import people_api
app.include_router(people_api.router(require_admin))
import client_console_api
app.include_router(client_console_api.router(require_internal))
import training_api
app.include_router(training_api.router(require_training, require_internal))
import dataset_api
app.include_router(dataset_api.router(require_training, require_training_image))
import dataset_links
app.include_router(dataset_links.admin_router(require_training))
app.include_router(dataset_links.public_router())  # token-only: fotos de terreno sin cuenta
app.include_router(catalog_api.router(require_admin))


async def integrity_conflict(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail": "El registro entra en conflicto con otro existente. Actualiza la pantalla antes de guardar."})


app.add_exception_handler(sqlite3.IntegrityError, integrity_conflict)
if db.USE_PG:
    app.add_exception_handler(db.pgcompat.psycopg2.IntegrityError, integrity_conflict)


def authorize_point(point_id: str, user: dict) -> None:
    """404 si el punto no existe; 403 si el usuario es de tienda y el punto pertenece a otro local."""
    exists, point_store = db.point_store_id(point_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Punto no encontrado")
    scope = store_scope(user)
    if scope is not None and point_store not in scope:
        raise HTTPException(status_code=403, detail="Esta góndola pertenece a otro local")


def authorize_reading(reading_id: int, user: dict) -> None:
    point_id = db.reading_point_id(reading_id)
    if point_id is None:
        raise HTTPException(status_code=404, detail="Lectura no encontrada")
    authorize_point(point_id, user)
    if profiles.profile_of(user) == "replenisher":
        reading = db.get_reading(reading_id)
        if not reading or reading.get("captured_by") != user["username"]:
            raise HTTPException(status_code=403, detail="Solo puedes consultar tus propias mediciones")


app.include_router(capture_api.router(require_user, require_scan, authorize_point))
app.include_router(report_api.router(require_report, require_review, authorize_reading, store_scope, require_user))
app.include_router(analysis_usage_api.router(require_user))
app.include_router(settings_api.router(require_admin, require_user))
import integrations_api
app.include_router(integrations_api.router(require_admin, require_user))
app.include_router(reading_details_api.router(require_user, require_review, authorize_reading))
app.include_router(dashboard_api.router(require_dashboard, require_report, store_scope))
app.include_router(alerts_api.router(require_user, require_resolve, authorize_reading))
app.include_router(store_excel_api.router(require_admin))


def _set_session_cookie(response: Response, username: str, request: Request) -> None:
    token = auth.create_session_token(username)
    response.set_cookie(
        _session_cookie_name(request),
        token,
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
UPLOADS_DIR = core.UPLOADS_DIR   # fotos (shrink, guardado, recortes, motor) viven en core.py: compartidos con la API v1
ENGINE_STATE = core.ENGINE_STATE

ROLE = os.environ.get("ROLE", "all")   # "api": sin motor (lo corre el servicio worker por la cola) · "all": todo en un proceso

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/uploads/{rel_path:path}")
def uploaded_photo(rel_path: str, request: Request, w: Optional[int] = None):
    """Authorize original photos, including direct URLs, before retrieving bytes. `?w=` serves the cached
    thumbnail for grids; the answer is browser-cacheable (ETag + private max-age, immutable for reading photos,
    which never change under their path)."""
    if rel_path.startswith('_training/'):
        raise HTTPException(404, 'Fotografía no disponible.')
    reading_id = db.reading_for_photo(rel_path)
    if _has_image_session(request):
        user = require_image_user(request)
        if reading_id is not None:
            authorize_reading(reading_id, user)
        elif not profiles.can(user, "manage"):
            raise HTTPException(status_code=403, detail="Tu perfil no permite consultar esta fotografía")
    elif request.headers.get("x-api-key") or request.headers.get("authorization"):
        ctx = api_v1.require_api_key(request)
        reading = db.get_reading(reading_id) if reading_id is not None else None
        point = db.get_point_meta(reading["point_id"]) if reading else None
        if not point or point.get("owner_client") != ctx["client"]["client_id"]:
            raise HTTPException(status_code=403, detail="La fotografía no pertenece al cliente de la API")
    else:
        raise HTTPException(status_code=401, detail="Inicia sesión para consultar la fotografía")
    try:
        data = storage.get(rel_path)
    except ValueError:
        data = None
    if data is None:
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    data, thumb_type = image_cache.thumbnail("uploads", rel_path, data, w)
    return image_cache.response(request, data, thumb_type or storage.content_type_for(rel_path),
                                immutable=reading_id is not None)
# Imágenes oficiales del catálogo real (data/catalogo/<categoria>/images), solo lectura y solo carpetas existentes
for _category, _images_dir in db.catalog_image_dirs():
    app.mount(f"/catalog-images/{_category}", StaticFiles(directory=_images_dir), name=f"catalog-images-{_category}")
# API v1 para el cliente (llave X-API-Key): sub-aplicación con su propia documentación en /v1/docs
app.mount("/v1", api_v1.app, name="api_v1")


@app.on_event("startup")
def _startup_engine():
    import threading

    try:
        print(f"[registro] código de invitación: {_registration_code()}", flush=True)
    except Exception as exc:
        print(f"[registro] sin código: {exc}", flush=True)

    if ROLE != "api" and os.environ.get("NEURAVISION_WARMUP", "1") != "0":
        threading.Thread(target=core.warm_up_engine, daemon=True).start()
    # cola de lecturas: con SQS la API solo encola (el motor está en el servicio worker); sin SQS, hilo local
    api_jobs.start_worker()
    import kilby_catalog
    kilby_catalog.start()  # NEURAVISION_ANALYSIS_BACKEND=kilby only: sends pending product changes to Kilby
    if storage.using_s3():  # fotos antiguas de EFS → S3, en segundo plano (idempotente)
        threading.Thread(target=storage.migrate_local_to_s3, daemon=True).start()


@app.get("/health")
def health():
    """Health check liviano para el ALB (no descarga la SPA)."""
    eh = core.engine_health()
    return {"status": "ok", "role": ROLE, "engine": "neuravision", "engine_ready": eh["engine_ready"],
            "engine_error": eh["engine_error"], "components": eh["components"],
            "detector": os.environ.get("NEURAVISION_DETECTOR", "auto"), "db": "postgres" if db.USE_PG else "sqlite",
            "photos": "s3" if storage.using_s3() else "disco", "queue": "sqs" if api_jobs.using_sqs() else "local"}


@app.get("/")
def index():
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


def _frontend_file(filename: str, media_type: str = "text/html"):
    """Archivo del frontend servido sin sesión (como '/'); 404 claro si todavía no existe."""
    path = FRONTEND_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{filename} no está disponible")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/panel")
def panel_page():
    """Panel de supervisión (supervisores de cadena y operadores). La página pide la sesión por /api/auth/me."""
    return _frontend_file("panel.html")


@app.get("/tienda")
def tienda_page():
    """App de tienda (PWA de captura)."""
    return _frontend_file("tienda.html")


@app.get("/sw.js")
def service_worker():
    return _frontend_file("sw.js", media_type="application/javascript")


@app.get("/manifest.webmanifest")
def web_manifest():
    return _frontend_file("manifest.webmanifest", media_type="application/manifest+json")


def _registration_code() -> str:
    """Código requerido para registrarse en producción. Si no viene por entorno, se genera una vez y se
    guarda en DATA_DIR/registration_code (EFS) y se imprime en el log al arrancar."""
    code = os.environ.get("REGISTRATION_CODE")
    if code is not None:
        return code.strip()
    path = db.DATA_DIR / "registration_code"
    if not path.exists():
        import secrets
        path.write_text(secrets.token_urlsafe(12))
    return path.read_text().strip()


@app.post("/api/auth/register")
def api_register(payload: AuthPayload, request: Request, response: Response):
    username = payload.username.strip().lower()
    expected = _registration_code()
    if expected and (payload.code or "").strip() != expected:
        raise HTTPException(status_code=403, detail="El registro requiere un código de invitación")
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="El usuario debe tener al menos 3 caracteres")
    auth.validate_password(payload.password)
    if db.user_exists(username):
        raise HTTPException(status_code=409, detail="Ese usuario ya existe")

    password_hash, salt = auth.hash_password(payload.password)
    role = "admin" if db.count_users() == 0 else "viewer"
    db.create_user(username, password_hash, salt, role=role)
    _set_session_cookie(response, username, request)
    return {"username": username, "role": role, "store_id": None, "store_name": None}


@app.post("/api/auth/login")
def api_login(payload: AuthPayload, request: Request, response: Response):
    user = auth.login_user(payload.username)
    # los teclados de teléfono agregan un espacio al final al autocompletar: se tolera en la contraseña
    password = payload.password.strip() if payload.password.strip() else payload.password
    if not user or not (auth.verify_password(password, user["password_hash"], user["salt"])
                        or auth.verify_password(payload.password, user["password_hash"], user["salt"])):
        raise HTTPException(status_code=401, detail="Usuario, email o contraseña incorrectos")

    username = user["username"]

    import people_service
    if people_service.account_status(username) == 'De baja':
        raise HTTPException(status_code=403, detail='La cuenta está de baja. Contacta al administrador.')
    _set_session_cookie(response, username, request)
    return {"username": username, "role": user["role"], "store_id": user.get("store_id"), "store_name": user.get("store_name")}


class PasswordChangePayload(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/auth/change-password")
def api_change_password(payload: PasswordChangePayload, request: Request, response: Response, user: dict = Depends(require_account)):
    row = db.get_user(user["username"])
    if not row or not auth.verify_password(payload.current_password, row["password_hash"], row["salt"]):
        raise HTTPException(status_code=403, detail="Contraseña actual incorrecta")
    auth.validate_password(payload.new_password)
    password_hash, salt = auth.hash_password(payload.new_password)
    db.update_user_password(user["username"], password_hash, salt)
    _set_session_cookie(response, user['username'], request)
    return {"ok": True}


@app.post("/api/auth/logout")
def api_logout(request: Request, response: Response):
    response.delete_cookie(_session_cookie_name(request))
    return {"ok": True}


@app.get("/api/auth/me")
def api_me(user: dict = Depends(require_account)):
    import client_identity
    identity = client_identity.public_identity() if user['portal_access'] else None
    return {**user, 'tenant':identity['tenant'] if identity else None,
            'tenant_version':identity['version'] if identity else None,
            'permissions':user['permissions'] if user['portal_access'] else ['console']}



class UserCreatePayload(BaseModel):
    username: str
    password: str
    role: str = "replenisher"
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    store_ids: Optional[List[str]] = None


class UserUpdatePayload(BaseModel):
    role: Optional[str] = None
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    password: Optional[str] = None
    store_ids: Optional[List[str]] = None


def _clean_assignments(role, store_id, store_name, store_ids):
    profile = profiles.profile_of(role)
    values = list(dict.fromkeys(str(value).strip().upper() for value in (store_ids if store_ids is not None else ([store_id] if store_id else []))))
    if len(values) > 100 or any(not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,19}", value) for value in values):
        raise HTTPException(status_code=400, detail="Indica códigos de PDV válidos (máximo 100)")
    if profile not in ("analyst", "replenisher"):
        return None, None, []
    if profile == "replenisher" and not values:
        raise HTTPException(status_code=400, detail="Asigna al menos un PDV al reponedor")
    return (values[0] if len(values) == 1 else None), (store_name or "").strip() or None, values


@app.get("/api/admin/users")
def api_list_users(_admin: dict = Depends(require_admin)):
    """[{username, role, store_id, store_name, created_at}] (solo admin)."""
    return db.list_users()


@app.post("/api/admin/users", status_code=201)
def api_create_user(payload: UserCreatePayload, _admin: dict = Depends(require_admin)):
    """Crea un usuario con rol y local (sin código de invitación: lo crea un admin)."""
    username = payload.username.strip().lower()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="El usuario debe tener al menos 3 caracteres")
    auth.validate_password(payload.password)
    if payload.role not in profiles.PROFILES:
        raise HTTPException(status_code=400, detail="Selecciona Administrador, Analista, Reponedor o Superusuario")
    if db.user_exists(username):
        raise HTTPException(status_code=409, detail="Ese usuario ya existe")
    store_id, store_name, store_ids = _clean_assignments(payload.role, payload.store_id, payload.store_name, payload.store_ids)
    password_hash, salt = auth.hash_password(payload.password)
    db.create_user(username, password_hash, salt, role=payload.role, store_id=store_id, store_name=store_name, store_ids=store_ids)
    return db.update_user(username)


@app.patch("/api/admin/users/{username}")
def api_update_user(username: str, payload: UserUpdatePayload, admin: dict = Depends(require_admin)):
    """Cambia rol, local (store_id/store_name; vacío = sin local) y/o contraseña de un usuario."""
    current = db.get_user(username)
    if not current:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if current.get('is_internal') or not current.get('portal_access',1):
        raise HTTPException(status_code=403,detail='Esta cuenta pertenece al equipo interno.')
    data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    role = data.get("role")
    if role is not None and role not in profiles.PROFILES:
        raise HTTPException(status_code=400, detail="Selecciona Administrador, Analista, Reponedor o Superusuario")
    if username == admin["username"] and role is not None and role != "admin":
        raise HTTPException(status_code=400, detail="No puedes quitarte tu propio rol de administrador")
    set_store = any(key in data for key in ("store_id", "store_name", "store_ids"))
    effective_role = role or current["role"]
    assigned = data.get("store_ids", None if "store_id" in data else current.get("store_ids"))
    store_id, store_name, store_ids = _clean_assignments(effective_role,
        data.get("store_id", current.get("store_id")), data.get("store_name", current.get("store_name")), assigned)
    kwargs = {"role": role, "set_store": set_store or role is not None, "store_id": store_id, "store_name": store_name, "store_ids": store_ids}
    if data.get("password") is not None:
        auth.validate_password(data["password"])
        kwargs["password_hash"], kwargs["salt"] = auth.hash_password(data["password"])
    return db.update_user(username, **kwargs)


@app.delete("/api/admin/users/{username}")
def api_delete_user(username: str, admin: dict = Depends(require_admin)):
    if not db.user_exists(username):
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    current = db.get_user(username)
    if current.get('is_internal') or not current.get('portal_access',1):
        raise HTTPException(status_code=403,detail='Esta cuenta pertenece al equipo interno.')
    if username == admin["username"]:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario")
    db.delete_user(username)
    return {"deleted": username}


def _rows_to_csv(rows: list) -> str:
    fieldnames = [
        "point_id", "point_name", "reading_id", "created_at",
        "product", "laboratorio", "category", "facings", "shelf_level", "position_index",
        "out_of_stock", "estimated_depth", "units_estimate",
        "reading_total_facings", "reading_empty_space_pct", "reading_shelf_levels", "reading_linear_meters",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


@app.get("/api/export.csv")
def api_export_all_csv(user: dict = Depends(require_report)):
    csv_text = _rows_to_csv(db.export_rows(store_id=store_scope(user)))
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=salcobrand-export.csv"},
    )


@app.get("/api/points")
def api_list_points(user: dict = Depends(require_user)):
    """Rol tienda: solo los puntos con points.store_id == store_id del usuario. Supervisor/admin: todos."""
    return infrastructure.annotate_points(db.list_points_with_latest(store_scope(user), captured_by=profiles.reading_author(user)))


@app.post("/api/points")
def api_create_point(
    point_id: Optional[str] = Form(default=None),
    name: str = Form(...),
    planogram_id: Optional[str] = Form(default=None),
    store_id: Optional[str] = Form(default=None),
    gondola_id: Optional[str] = Form(default=None),
    user: dict = Depends(require_admin),
):
    """Rol tienda: store_id se fuerza al local del usuario (se ignora el enviado) y el nombre lleva el prefijo del
    local ('<nombre o id del local> · <nombre>'); gondola_id se conserva. Supervisor/admin: store_id opcional."""
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre del punto es obligatorio")

    pid = (point_id or "").strip() or db.next_point_id()
    if db.point_exists(pid):
        raise HTTPException(status_code=409, detail=f"El punto {pid} ya existe")

    planogram_id = (planogram_id or "").strip() or None
    if planogram_id and not db.get_planogram(planogram_id):
        raise HTTPException(status_code=404, detail="Planograma no encontrado")
    gondola_id = (gondola_id or "").strip() or None
    store_id = (store_id or "").strip().upper() or None
    if store_id:
        known = next((s for s in infrastructure.list_stores() if s["code"] == store_id), None)
        if not known or known["status"] != "Activo":
            raise HTTPException(400, "Selecciona un PDV activo del módulo PDV.")
    if planogram_id:
        catalog_service.validate_assignment(planogram_id, store_id)
    db.create_point(pid, name, planogram_id, store_id=store_id, gondola_id=gondola_id)
    return db.get_point(pid)


@app.put("/api/points/{point_id}/planogram")
def api_set_point_planogram(point_id: str, payload: PlanogramAssignPayload, user: dict = Depends(require_admin)):
    authorize_point(point_id, user)
    if payload.planogram_id and not db.get_planogram(payload.planogram_id):
        raise HTTPException(status_code=404, detail="Planograma no encontrado")
    if payload.planogram_id:
        catalog_service.validate_assignment(payload.planogram_id, db.point_store_id(point_id)[1], point_id)
    db.set_point_planogram(point_id, payload.planogram_id)
    return db.get_point(point_id)


@app.get("/api/planograms")
def api_list_planograms(user: dict = Depends(require_user)):
    return catalog_service.plan_options()


@app.get("/api/planograms/{planogram_id}")
def api_get_planogram(planogram_id: str, user: dict = Depends(require_user)):
    pg = db.get_planogram(planogram_id)
    if not pg:
        raise HTTPException(status_code=404, detail="Planograma no encontrado")
    return pg


@app.post("/api/admin/planograms")
def api_create_planogram(payload: PlanogramCreatePayload, user: dict = Depends(require_staff)):
    if db.get_planogram(payload.id):
        raise HTTPException(status_code=409, detail="Ya existe un planograma con ese id")
    db.create_planogram(payload.dict())
    return db.get_planogram(payload.id)


@app.post("/api/admin/planograms/import-pdf")
async def api_import_planogram_pdf(
    pdf: UploadFile = File(...),
    planogram_id: Optional[str] = Form(default=None),
    name: Optional[str] = Form(default=None),
    replace: bool = Form(default=False),
    user: dict = Depends(require_staff),
):
    """Crea un planograma a partir del PDF que entrega Salcobrand (texto, no escaneado)."""
    data = await pdf.read()
    try:
        return await run_in_threadpool(core.import_planogram_pdf, data, pdf.filename, planogram_id, name, replace, None)
    except core.PlanogramExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/planograms/import-json")
async def api_import_planogram_json(
    file: UploadFile = File(...),
    planogram_id: Optional[str] = Form(default=None),
    name: Optional[str] = Form(default=None),
    replace: bool = Form(default=False),
    user: dict = Depends(require_staff),
):
    """Crea un planograma desde un JSON {name, module_cm, bands, items:[{band, position_in_section, title, expected_facings, ...}]}."""
    import json as _json
    import re as _re
    import unicodedata as _ud

    try:
        data = _json.loads((await file.read()).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"JSON inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "El JSON debe ser un objeto con una lista de posiciones.")
    raw_items = data.get("items") or []
    if not raw_items:
        raise HTTPException(status_code=400, detail="El JSON no tiene 'items'")
    raw_name = planogram_id or data.get("name") or (file.filename or "").rsplit(".", 1)[0] or "planograma"
    raw_name = "".join(c for c in _ud.normalize("NFKD", raw_name) if not _ud.combining(c))
    base = _re.sub(r"[^a-z0-9]+", "-", raw_name.lower()).strip("-")[:60] or "planograma"
    if db.get_planogram(base):
        if not replace:
            raise HTTPException(status_code=409, detail=f"Ya existe el planograma '{base}' (marca 'reemplazar' para actualizarlo)")
    items = catalog_service.legacy_items(raw_items)
    payload = {"id": base, "name": name or data.get("name") or base, "module_cm": data.get("module_cm"), "bands": data.get("bands") or max((it["band"] for it in items), default=0),
               "source_filename": file.filename, "items": items}
    if not items:
        raise HTTPException(400, "El archivo no contiene posiciones válidas.")
    try:
        if db.get_planogram(base):
            db.replace_planogram(payload)
        else:
            db.create_planogram(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": base, "name": payload["name"], "bands": payload["bands"], "module_cm": payload["module_cm"], "n_items": len(items),
            "items_preview": [it["title"] for it in items[:8]]}


@app.get("/planogramas")
def planogramas_page(user: dict = Depends(require_user)):
    return FileResponse(FRONTEND_DIR / "planogramas.html", media_type="text/html")


@app.delete("/api/admin/planograms/{planogram_id}")
def api_delete_planogram(planogram_id: str, user: dict = Depends(require_staff)):
    if not db.get_planogram(planogram_id):
        raise HTTPException(status_code=404, detail="Planograma no encontrado")
    db.delete_planogram(planogram_id)
    return {"deleted": planogram_id}


@app.put("/api/planograms/{planogram_id}/prices")
def api_update_planogram_prices(planogram_id: str, payload: PlanogramPricesPayload, user: dict = Depends(require_staff)):
    if not db.get_planogram(planogram_id):
        raise HTTPException(status_code=404, detail="Planograma no encontrado")
    updated = db.update_planogram_prices(planogram_id, payload.prices)
    return {"updated": updated, "planogram": db.get_planogram(planogram_id)}


@app.get("/api/points/{point_id}")
def api_get_point(point_id: str, user: dict = Depends(require_user)):
    authorize_point(point_id, user)
    point = db.get_point(point_id, captured_by=profiles.reading_author(user))
    return infrastructure.annotate_points([point])[0]


@app.get("/api/points/{point_id}/export.csv")
def api_export_point_csv(point_id: str, user: dict = Depends(require_report)):
    authorize_point(point_id, user)
    csv_text = _rows_to_csv(db.export_rows(point_id))
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=salcobrand-{point_id}-export.csv"},
    )


@app.get("/api/points/{point_id}/daily-metrics")
def api_daily_metrics(point_id: str, user: dict = Depends(require_dashboard)):
    authorize_point(point_id, user)
    return db.daily_metrics(point_id)


@app.get("/api/points/{point_id}/replenishment")
def api_replenishment(point_id: str, user: dict = Depends(require_dashboard)):
    authorize_point(point_id, user)
    return db.replenishment_signals(point_id)


@app.delete("/api/points/{point_id}")
def api_delete_point(point_id: str, user: dict = Depends(require_admin)):
    authorize_point(point_id, user)
    with db.get_conn() as conn:
        linked = conn.execute("SELECT id FROM management_instances WHERE point_id = ?", (point_id,)).fetchone()
        history = conn.execute("SELECT id FROM readings WHERE point_id = ? LIMIT 1", (point_id,)).fetchone()
    if linked or history:
        raise HTTPException(409, "Esta góndola tiene infraestructura o lecturas. Conserva su historial y desactívala desde Infraestructura.")
    db.delete_point(point_id)
    storage.delete_prefix(point_id)
    return {"deleted": point_id}


@app.post("/api/points/{point_id}/analyze")
async def api_analyze(
    point_id: str,
    images: List[UploadFile] = File(...),
    linear_meters: Optional[float] = Form(default=None),
    user: dict = Depends(require_scan),
):
    authorize_point(point_id, user)
    point = db.get_point(point_id)

    capture_context = infrastructure.capture_context(point_id)

    try:
        loaded = await core.read_image_uploads(images)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    planogram_id = point.get("planogram_id")
    image_paths = await run_in_threadpool(lambda: [core.save_upload(point_id, b, ct) for b, ct in loaded])
    job = api_jobs.enqueue(api_jobs.APP_CLIENT, point_id, {"image_paths": image_paths, "linear_meters": linear_meters,
                                                          "planogram_id": planogram_id, "user": user.get("username"),
                                                          "via": "app", "infrastructure": capture_context})

    async def _stream():
        """La lectura la hace el motor (worker) a partir de la cola; aquí se espera el resultado. Mantiene viva la
        conexión (el ALB corta a los 60 s sin bytes) emitiendo espacios cada 15 s; JSON.parse ignora los espacios
        iniciales, así que el frontend no cambia. Si no hay worker encendido, el primero tarda 1-3 min en arrancar."""
        import asyncio
        import json as _json
        import time as _time

        t0, last_byte = _time.monotonic(), _time.monotonic()
        while True:
            j = await run_in_threadpool(db.get_job, job["job_id"])
            if j and j["status"] == "done" and j.get("reading_id"):
                reading = await run_in_threadpool(db.get_reading, j["reading_id"])
                yield _json.dumps(reading, ensure_ascii=False)
                return
            if j and j["status"] == "failed":
                err = j.get("error") or "Error al analizar la imagen"
                detail = err if not err.startswith("engine_error") else f"Error al analizar la imagen: {err}"
                yield _json.dumps({"id": None, "error": True, "detail": detail})
                return
            if _time.monotonic() - t0 > ANALYZE_TIMEOUT_S:
                yield _json.dumps({"id": None, "error": True, "job_id": job["job_id"],
                                   "detail": "El análisis está tardando más de lo normal. La lectura aparecerá en el panel "
                                             "cuando termine."})
                return
            if _time.monotonic() - last_byte > 15:
                last_byte = _time.monotonic()
                yield " "
            await asyncio.sleep(1.0)

    from fastapi.responses import StreamingResponse

    return StreamingResponse(_stream(), media_type="application/json")


ANALYZE_TIMEOUT_S = int(os.environ.get("ANALYZE_TIMEOUT_S", "600"))

# ---------------------------------------------------------------------------
# Captura de fotos por enlace (sin usuario): /captura/<código> (captures.py). Aquí, la administración.
# ---------------------------------------------------------------------------
app.include_router(captures.router)
app.include_router(vivo.router)   # cámara en vivo (prototipo): /vivo/<código>


class CaptureLocal(BaseModel):
    store_id: str
    label: Optional[str] = None


class CaptureLinkPayload(BaseModel):
    store_id: Optional[str] = None
    label: Optional[str] = None
    days: Optional[int] = None         # vence en N días (vacío = no vence)
    max_per_day: Optional[int] = None  # fotos por día (por defecto 600)
    universal: bool = False            # enlace único: la persona elige su local al abrir
    locales: Optional[List[CaptureLocal]] = None  # locales del universal (vacío = los de los enlaces por local activos)


@app.post("/api/admin/capture-links", status_code=201)
def api_create_capture_link(payload: CaptureLinkPayload, request: Request, user: dict = Depends(require_staff)):
    label = (payload.label or "").strip() or None
    try:
        if payload.universal:
            locales = ([l.model_dump() if hasattr(l, "model_dump") else l.dict() for l in payload.locales]
                       if payload.locales else captures.locales_por_defecto())
            link = captures.create_link(captures.UNIVERSAL, label, payload.days, payload.max_per_day,
                                        created_by=user.get("username"), locales=locales)
        else:
            store_id = (payload.store_id or "").strip()
            if not store_id or store_id == captures.UNIVERSAL:
                raise HTTPException(status_code=400, detail="Falta el local")
            link = captures.create_link(store_id, label, payload.days, payload.max_per_day, created_by=user.get("username"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "salcobrand.neuramorphic.ai"
    return {**link, "url": f"https://{host}/captura/{link['token']}"}


@app.post("/api/admin/capture-links/{token}/local")
def api_capture_link_local(token: str, payload: CaptureLocal, user: dict = Depends(require_staff)):
    """Corrige el local de un enlace por local y mueve sus fotos a ese local (p. ej. el 129 que en realidad es el 128)."""
    try:
        link = captures.set_local(token, payload.store_id, payload.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not link:
        raise HTTPException(status_code=404, detail="Enlace no encontrado")
    return link


@app.get("/api/admin/capture-links")
def api_list_capture_links(user: dict = Depends(require_staff)):
    return captures.list_links()


@app.post("/api/admin/capture-links/{token}/desactivar")
def api_disable_capture_link(token: str, user: dict = Depends(require_staff)):
    link = captures.set_active(token, False)
    if not link:
        raise HTTPException(status_code=404, detail="Enlace no encontrado")
    return link


@app.post("/api/admin/capture-links/{token}/activar")
def api_enable_capture_link(token: str, user: dict = Depends(require_staff)):
    link = captures.set_active(token, True)
    if not link:
        raise HTTPException(status_code=404, detail="Enlace no encontrado")
    return link


@app.get("/api/admin/captures")
def api_list_captures(store_id: Optional[str] = None, token: Optional[str] = None, limit: int = 500,
                      user: dict = Depends(require_staff)):
    return captures.list_captures(store_id, token, min(max(limit, 1), 5000))


@app.get("/api/admin/shadow")
def api_shadow_summary(user: dict = Depends(require_staff)):
    """Modo sombra: comparación del detector candidato con el de producción sobre lecturas reales."""
    return shadow.summary()


@app.post("/api/admin/reanalyze")
def api_reanalyze_all(user: dict = Depends(require_review)):
    """Vuelve a analizar todas las fotos ya subidas con el prompt/algoritmo actual,
    actualizando cada lectura existente en el lugar (sin crear lecturas nuevas)."""
    if ROLE == "api":
        raise HTTPException(status_code=409, detail="El motor corre en el servicio worker; el reanálisis masivo se hace "
                                                    "desde un worker (no desde la API).")
    if getattr(core, "analysis_backend", lambda: "embedded")() == "kilby":
        raise HTTPException(status_code=409, detail="Con Neuravision en Kilby cada foto reanalizada se cobra: el reanálisis "
                                                    "masivo no está disponible. Vuelve a capturar las góndolas que lo necesiten.")
    results = {"updated": [], "unchanged_rejected": [], "errors": []}
    for r in db.all_readings_with_images():
        try:
            authorize_point(r["point_id"], user)
        except HTTPException:
            continue
        image_paths = r["image_paths"]
        if not image_paths:
            continue
        try:
            loaded = core.load_images_from_disk(image_paths)
            planogram_context = (
                db.planogram_context_for_vision(r["planogram_id"], planogram=db.reading_planogram_snapshot(r["id"])) if r["planogram_id"] else None
            )
            if getattr(core, "remote_enabled", lambda: False)():
                import remote_model
                analysis = remote_model.analyze(r["point_id"], loaded, r.get("linear_meters"), plan_snapshot=db.reading_planogram_snapshot(r["id"]))
            else:
                analysis = core.analyze_shelf(loaded, planogram_context)

            if not analysis.get("is_pharmacy_shelf", True):
                results["unchanged_rejected"].append({
                    "reading_id": r["id"],
                    "point_id": r["point_id"],
                    "reason": analysis.get("rejection_reason"),
                })
                continue

            db.update_reading_analysis(r["id"], analysis)
            results["updated"].append({
                "reading_id": r["id"],
                "point_id": r["point_id"],
                "total_facings": analysis.get("total_facings"),
                "products": len(analysis.get("products", [])),
            })
        except Exception as exc:
            results["errors"].append({"reading_id": r["id"], "point_id": r["point_id"], "error": str(exc)})
    return results


# ---------------------------------------------------------------------------
# Revisión humana: recortes dudosos → confirmación → memoria visual (NeuraVision)
# ---------------------------------------------------------------------------
@app.get("/revision")
def revision_page(user: dict = Depends(require_training)):
    return FileResponse(FRONTEND_DIR / "revision.html", media_type="text/html")


@app.get("/api/readings/{reading_id}")
def api_get_reading(reading_id: int, user: dict = Depends(require_user)):
    authorize_reading(reading_id, user)
    r = db.get_reading(reading_id)
    if not r:
        raise HTTPException(status_code=404, detail="Lectura no encontrada")
    return r


@app.delete("/api/readings/{reading_id}")
def api_delete_reading(reading_id: int, user: dict = Depends(require_admin)):
    authorize_reading(reading_id, user)
    if not db.delete_reading(reading_id):
        raise HTTPException(status_code=404, detail="Lectura no encontrada")
    return {"deleted": reading_id}


@app.get("/api/review/pending")
def api_review_pending(user: dict = Depends(require_training)):
    return training_api.pending()


@functools.lru_cache(maxsize=1024)
def _crop_cached(reading_id: int, image_index: int, item_index: int) -> bytes:
    """Recorte JPEG por (lectura, foto, ítem). Las cajas y la foto de una lectura no cambian (los ids no se reutilizan),
    así que se cachea en memoria: el panel pide decenas de recortes por lectura."""
    r = db.get_reading(reading_id)
    if not r:
        raise LookupError("Lectura no encontrada")
    return core.crop_jpeg(r, image_index, item_index)


@app.get("/api/readings/{reading_id}/crops/{image_index}/{item_index}.jpg")
def api_reading_crop(reading_id: int, image_index: int, item_index: int, request: Request, w: Optional[int] = None,
                     user: dict = Depends(require_image_user)):
    authorize_reading(reading_id, user)
    try:
        data = _crop_cached(reading_id, image_index, item_index)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    data, thumb_type = image_cache.thumbnail("crops", f"{reading_id}/{image_index}/{item_index}", data, w)
    return image_cache.response(request, data, thumb_type or "image/jpeg", immutable=True)


@app.post("/api/readings/{reading_id}/confirm")
def api_reading_confirm(reading_id: int, payload: ConfirmPayload, user: dict = Depends(require_training)):
    """Guarda una etiqueta interna de entrenamiento sin modificar la medición del cliente."""
    authorize_reading(reading_id, user)
    r = db.get_reading(reading_id)
    if not r:
        raise HTTPException(status_code=404, detail="Lectura no encontrada")
    try:
        if payload.verdict not in (None, '', 'no_identificable'):
            raise HTTPException(status_code=400, detail="verdict debe ser 'no_identificable' o nulo")
        if payload.verdict == 'no_identificable' and payload.reason not in ('al_reves', 'tapado', 'borroso', 'no_producto', 'otro'):
            raise HTTPException(status_code=400, detail="reason debe ser al_reves, tapado, borroso, no_producto u otro")
        return training_api.save_label(r, payload.image_index, payload.item_index, payload.title, payload.facings, user['username'],
                                       verdict=payload.verdict or None, reason=payload.reason if payload.verdict else None)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/points/{point_id}/stock-actions")
def api_create_stock_action(point_id: str, payload: StockActionPayload, user: dict = Depends(require_resolve)):
    authorize_point(point_id, user)
    if payload.action_type not in ("solicitud", "ajuste_robo"):
        raise HTTPException(status_code=400, detail="action_type debe ser 'solicitud' o 'ajuste_robo'")
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="La cantidad debe ser mayor a 0")
    return db.create_stock_action(
        point_id, payload.planogram_item_id, payload.product_title,
        payload.action_type, payload.quantity, payload.note, user["username"],
    )


@app.get("/api/points/{point_id}/stock-actions")
def api_list_stock_actions(point_id: str, include_resolved: bool = False, user: dict = Depends(require_dashboard)):
    authorize_point(point_id, user)
    return db.list_stock_actions(point_id, include_resolved)


@app.post("/api/stock-actions/{action_id}/resolve")
def api_resolve_stock_action(action_id: int, user: dict = Depends(require_resolve)):
    pid = db.stock_action_point(action_id)
    if pid is None:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    authorize_point(pid, user)
    db.resolve_stock_action(action_id)
    return {"resolved": action_id}


@app.delete("/api/stock-actions/{action_id}")
def api_delete_stock_action(action_id: int, user: dict = Depends(require_resolve)):
    pid = db.stock_action_point(action_id)
    if pid is None:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    authorize_point(pid, user)
    db.delete_stock_action(action_id)
    return {"deleted": action_id}


@app.post("/api/points/{point_id}/supplier-stockouts")
def api_create_supplier_stockout(point_id: str, payload: SupplierStockoutPayload, user: dict = Depends(require_resolve)):
    authorize_point(point_id, user)
    return db.create_supplier_stockout(point_id, payload.planogram_item_id, payload.product_title, payload.note, user["username"])


@app.get("/api/points/{point_id}/supplier-stockouts")
def api_list_point_supplier_stockouts(point_id: str, include_resolved: bool = False, user: dict = Depends(require_dashboard)):
    authorize_point(point_id, user)
    return db.list_supplier_stockouts(point_id, include_resolved)


@app.get("/api/supplier-stockouts")
def api_list_all_supplier_stockouts(user: dict = Depends(require_user)):
    if profiles.profile_of(user) == "replenisher":
        return []  # Supplier actions are shared; replenisher alerts come from own readings.
    return db.list_supplier_stockouts(None, False, store_id=store_scope(user))


@app.post("/api/supplier-stockouts/{stockout_id}/resolve")
def api_resolve_supplier_stockout(stockout_id: int, user: dict = Depends(require_resolve)):
    pid = db.supplier_stockout_point(stockout_id)
    if pid is None:
        raise HTTPException(status_code=404, detail="Quiebre no encontrado")
    authorize_point(pid, user)
    db.resolve_supplier_stockout(stockout_id)
    return {"resolved": stockout_id}


# ---------------------------------------------------------------------------
# Panel de supervisión (/panel): resumen, tendencias por SKU, catálogo oficial y revisión por lectura
# ---------------------------------------------------------------------------
@app.get("/api/home")
def api_home(user: dict = Depends(require_user)):
    import home_service
    return home_service.summary(user)


@app.get("/api/summary")
def api_summary(days: int = 7, user: dict = Depends(require_user)):
    """Por punto: local/góndola, planograma y última lectura (cumplimiento, caras, por revisar, quiebres); totales del
    período y agrupación por local (`stores`). Rol tienda: solo su local."""
    summary = db.panel_summary(days, store_id=store_scope(user), captured_by=profiles.reading_author(user))
    summary["points"] = infrastructure.annotate_points(summary["points"])
    return summary


@app.get("/api/points/{point_id}/trends")
def api_point_trends(point_id: str, limit: int = 12, user: dict = Depends(require_dashboard)):
    """Serie de las últimas lecturas del punto y caras por SKU del planograma con bandera de tendencia (Módulo 1)."""
    authorize_point(point_id, user)
    data = db.point_trends(point_id, limit)
    if data is None:
        raise HTTPException(status_code=404, detail="Punto no encontrado")
    return data


@app.get("/api/catalog/{planogram_id}")
def api_catalog(planogram_id: str, point_id: Optional[str] = None, user: dict = Depends(require_dashboard)):
    """Posiciones del planograma + ficha del catálogo real (imagen oficial, marca, precio) y lo último observado en el punto."""
    if point_id:
        authorize_point(point_id, user)
    data = db.catalog_for_planogram(planogram_id, point_id or None)
    if data is None:
        raise HTTPException(status_code=404, detail="Planograma no encontrado")
    return data


@app.get("/api/readings/{reading_id}/review")
def api_reading_review(reading_id: int, user: dict = Depends(require_training)):
    """Ítems por revisar de una lectura (índices, recorte, candidatos), igual que /v1/readings/{id}/review."""
    authorize_reading(reading_id, user)
    r = db.get_reading(reading_id)
    if not r:
        raise HTTPException(status_code=404, detail="Lectura no encontrada")
    return training_api.review_payload(r)
