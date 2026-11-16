"""Internal identity directory, bound to this deployment's operational client."""
import base64
import binascii
import copy
import io
import json
import os
import re
import uuid
from PIL import Image
import db
from catalog_service import lock_catalog
from infrastructure import ManagementError, _audit, _text

FONTS = ['Arial','Verdana','Tahoma','Trebuchet MS','Georgia','Times New Roman','system-ui']
DEFAULT_MODEL = {'remoteOrgId':'','credentialEnv':'INTEGRATION_NEURAVISION_KEY'}
DEFAULT_IDENTITY = {'schema':1,'id':'salcobrand','name':'Salcobrand','logo':'','theme':'default',
                    'primaryColor':'#183247','sidebarColor':'#0f1b2d',
                    'modules':{'vision':True,'planograms':True,'sales':False},'typography':{}}
IDENTITY_FIELDS = tuple(DEFAULT_IDENTITY)


def current_slug():
    slug = os.environ.get('NEURAVISION_TENANT_ID','salcobrand')
    if not re.fullmatch(r'[a-z][a-z0-9-]{2,49}',slug):
        raise ManagementError('El cliente de este despliegue no está configurado correctamente.',503)
    return slug


def ensure_current(conn):
    slug = current_slug()
    existing = conn.execute('SELECT * FROM management_clients WHERE slug=?',(slug,)).fetchone()
    if existing:
        return existing
    tenant = {**copy.deepcopy(DEFAULT_IDENTITY),'id':slug,'name':os.environ.get('NEURAVISION_TENANT_NAME','Salcobrand')}
    client_id = str(uuid.uuid5(uuid.NAMESPACE_URL,'neuravision-client:' + slug))
    conn.execute('INSERT INTO management_clients (id,slug,name,tenant_json,model_json,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                 (client_id,slug,tenant['name'],json.dumps(tenant),json.dumps(DEFAULT_MODEL),db.now_iso()))
    return conn.execute('SELECT * FROM management_clients WHERE slug=?',(slug,)).fetchone()


def public_identity(conn=None):
    if conn is None:
        with db.get_conn() as connection:
            return public_identity(connection)
    row = ensure_current(conn)
    tenant = json.loads(row['tenant_json'])
    return {'tenant':{key:tenant[key] for key in IDENTITY_FIELDS if key in tenant},'version':row['version'],
            'client_id':row['id'],'active':bool(row['active'])}


def model_config():
    with db.get_conn() as conn:
        return validate_model(json.loads(ensure_current(conn)['model_json']))


def directory():
    with db.get_conn() as conn:
        current = ensure_current(conn)
        rows = conn.execute('SELECT * FROM management_clients ORDER BY name,id').fetchall()
    return {'clients':[{'id':row['id'],'slug':row['slug'],'name':json.loads(row['tenant_json']).get('name',row['name']),
                        'active':bool(row['active'])} for row in rows],
            'deployment_client_id':current['id'],'fonts':FONTS,'defaults':copy.deepcopy(DEFAULT_IDENTITY)}


def detail(client_id,conn=None):
    if conn is None:
        with db.get_conn() as connection:
            ensure_current(connection)
            return detail(client_id,connection)
    row = conn.execute('SELECT * FROM management_clients WHERE id=?',(client_id,)).fetchone()
    if row is None:
        raise ManagementError('El cliente no está registrado.',404)
    return {'tenant':json.loads(row['tenant_json']),'model':json.loads(row['model_json']),'version':row['version'],
            'organization':{'id':row['id'],'slug':row['slug'],'name':row['name']},'active':bool(row['active'])}


def color(value):
    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):
        raise ManagementError('Usa colores hexadecimales de seis caracteres.')
    return value


def validate_identity(tenant):
    if not isinstance(tenant,dict) or type(tenant.get('schema')) is not int or tenant['schema'] != 1:
        raise ManagementError('Versión de identidad no válida.')
    slug = tenant.get('id')
    if not isinstance(slug,str) or not re.fullmatch(r'[a-z][a-z0-9-]{2,49}',slug):
        raise ManagementError('Identificador: usa de 3 a 50 letras minúsculas, números y guiones.')
    name = _text(tenant.get('name'),'Nombre del cliente',100,True)
    logo = tenant.get('logo','')
    if not isinstance(logo,str) or len(logo)>800000:
        raise ManagementError('Logo no válido o demasiado grande.')
    if logo:
        match = re.fullmatch(r'data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)',logo)
        if not match:
            raise ManagementError('Usa un logo PNG, JPG o WebP válido.')
        try:
            with Image.open(io.BytesIO(base64.b64decode(match[2],validate=True))) as image:
                if image.format != {'jpeg':'JPEG','png':'PNG','webp':'WEBP'}[match[1]]:
                    raise ValueError()
                image.verify()
        except (ValueError,OSError,binascii.Error,Image.DecompressionBombError):
            raise ManagementError('No se pudo validar la imagen del logo.') from None
    modules = tenant.get('modules')
    if not isinstance(modules,dict) or any(type(modules.get(key)) is not bool for key in ('vision','planograms','sales')):
        raise ManagementError('Completa los módulos de la identidad con valores válidos.')
    typography = tenant.get('typography',{})
    if not isinstance(typography,dict) or set(typography)-{'sidebar','content'}:
        raise ManagementError('Tipografía no válida.')
    for area,values in typography.items():
        allowed = {'fontFamily','color','fontSize'} if area == 'sidebar' else {'fontFamily','color'}
        if not isinstance(values,dict) or set(values)-allowed:
            raise ManagementError('El tamaño de letra se configura en la barra lateral.')
        if 'fontFamily' in values and values['fontFamily'] not in FONTS:
            raise ManagementError('Tipo de letra no válido.')
        if 'color' in values:
            color(values['color'])
        if 'fontSize' in values and (type(values['fontSize']) is not int or not 10 <= values['fontSize'] <= 24):
            raise ManagementError('El tamaño de la barra lateral debe estar entre 10 y 24 px.')
    return {'schema':1,'id':slug,'name':name,'logo':logo,'theme':_text(tenant.get('theme','default'),'Tema',50),
            'primaryColor':color(tenant.get('primaryColor')),'sidebarColor':color(tenant.get('sidebarColor','#0f1b2d')),
            'modules':{key:modules[key] for key in ('vision','planograms','sales')},'typography':copy.deepcopy(typography)}


def validate_model(model):
    if not isinstance(model,dict) or set(model)-{'remoteOrgId','credentialEnv'}:
        raise ManagementError('Configuración del modelo no válida.')
    org = model.get('remoteOrgId','')
    env = model.get('credentialEnv',DEFAULT_MODEL['credentialEnv'])
    if not isinstance(org,str) or (org and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',org)):
        raise ManagementError('ID de organización del modelo no válido.')
    if not isinstance(env,str) or not re.fullmatch(r'INTEGRATION_[A-Z0-9_]{1,88}',env):
        raise ManagementError('Indica el nombre de una variable INTEGRATION_ del servidor.')
    return {'remoteOrgId':org,'credentialEnv':env}


def save(client_id,tenant,version,actor,model=None):
    identity = validate_identity(tenant)
    model = validate_model(model) if model is not None else None
    with db.get_conn() as conn:
        lock_catalog(conn)
        current = ensure_current(conn)
        before = detail(client_id,conn)
        if type(version) is not int or version != before['version']:
            raise ManagementError('La identidad cambió en otra sesión. Recarga el cliente antes de aplicar.',409)
        if identity['id'] != before['organization']['slug']:
            raise ManagementError('El identificador pertenece a otro cliente. Abre el cliente correcto.')
        if model is not None and model != before['model'] and client_id == current['id']:
            jobs = conn.execute("SELECT status,payload_json FROM api_jobs WHERE status IN ('queued','running','failed')").fetchall()
            pending = any(job['status'] != 'failed' or (json.loads(job['payload_json']).get('remote_submitted') and not json.loads(job['payload_json']).get('remote_final_failed')) for job in jobs)
            if pending:
                raise ManagementError('Hay capturas en proceso. Espera a que terminen antes de cambiar la conexión del modelo.',409)
        after_tenant = {**before['tenant'],**identity}
        conn.execute('UPDATE management_clients SET tenant_json=?,model_json=?,version=version+1,updated_by=?,updated_at=? WHERE id=?',
                     (json.dumps(after_tenant,ensure_ascii=False),json.dumps(model if model is not None else before['model']),actor,db.now_iso(),client_id))
        # Identity changes never write customer classifications or operational tables.
        audit_before = {**before['tenant'],'logo':bool(before['tenant'].get('logo'))}
        audit_after = {**identity,'logo':bool(identity['logo'])}
        _audit(conn,actor,'tenant.identity.update',client_id,audit_before,audit_after)
        if model is not None and model != before['model']:
            _audit(conn,actor,'tenant.model.link',client_id,before['model'],model)
    return {'version':version+1}


def seed_local_operator():
    """Called only by explicit local preview runners, outside application startup."""
    import auth
    username = 'local-internal'
    with db.get_conn() as conn:
        lock_catalog(conn)
        existing = conn.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        if existing:
            if not existing['is_internal'] or existing['portal_access']:
                raise ValueError('local-internal ya existe con permisos diferentes. Revisa la cuenta local antes de continuar.')
            return
        hashed,salt = auth.hash_password('Isolated-local-password-2026!')
        db.create_user(username,hashed,salt,role='admin',conn=conn)
        conn.execute('UPDATE users SET is_internal=1,portal_access=0,auth_version=auth_version+1 WHERE username=?',(username,))
