"""Capture classification and manual-width locations, independent of shelf masters."""
import hashlib
import json
import db
import catalog_service
import profiles
import settings_service
from infrastructure import ManagementError, _row

MANUAL_PREFIX = 'SB-MANUAL-'


def selection(category='', subcategory='', subcategories=None):
    from product_classification import selection as classify
    return classify(category, subcategory, subcategories)


def validate_selection(values, conn=None):
    from product_classification import validate
    validate(values, conn)


def has_shelves(conn, code):
    return bool(conn.execute('SELECT 1 FROM management_assignments WHERE store_code=? AND quantity>0', (code,)).fetchone())


def manual_store(conn, code):
    store = _row(conn, 'management_stores', 'code', code)
    if store['deleted'] or store['status'] != 'Activo':
        raise ManagementError('El PDV estÃ¡ inactivo.', 409)
    if has_shelves(conn, code):
        raise ManagementError('Este PDV tiene gÃ³ndolas asignadas. Selecciona su tipo y gÃ³ndola.', 409)
    return store


def options(user):
    scope = profiles.store_scope(user)
    with db.get_conn() as conn:
        stores = conn.execute("SELECT code FROM management_stores WHERE deleted=0 AND status='Activo'").fetchall()
        manual = [store['code'] for store in stores if (scope is None or store['code'] in scope) and not has_shelves(conn, store['code'])]
    return {'categories': settings_service.read()['state']['catalog']['categories'], 'manual_stores': manual}


def manual_point(code, user, values):
    identity = json.dumps([code, user['username'], values], sort_keys=True, ensure_ascii=False)
    point_id = MANUAL_PREFIX + hashlib.sha256(identity.encode()).hexdigest()[:32]
    with db.get_conn() as conn:
        catalog_service.lock_catalog(conn)
        existing = conn.execute('SELECT store_id FROM points WHERE id=?', (point_id,)).fetchone()
        if existing:
            if existing['store_id'] != code:
                raise ManagementError('El punto de captura no corresponde al PDV.', 409)
            return point_id
        store = manual_store(conn, code)
        validate_selection(values, conn)
        db.create_point(point_id, store['name'] + ' Â· Captura con ancho manual', store_id=code, gondola_id='Captura manual', conn=conn)
    return point_id
