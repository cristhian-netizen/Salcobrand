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


def manual_store(conn, code, allow_assigned=False):
    store = _row(conn, 'management_stores', 'code', code)
    if store['deleted'] or store['status'] != 'Activo':
        raise ManagementError('El PDV está inactivo.', 409)
    if not allow_assigned and has_shelves(conn, code):
        raise ManagementError('Activa las medidas manuales para este PDV con góndolas asignadas.', 409)
    return store


def geometry(levels=None, depths=None):
    import math
    if levels is None and not depths:
        return {}
    if type(levels) is not int or not 1 <= levels <= 100 or not depths or len(depths) != levels:
        raise ManagementError('Indica de 1 a 100 niveles y una profundidad por nivel.')
    if any(not math.isfinite(depth) or not 0 < depth <= 1000 for depth in depths):
        raise ManagementError('Las profundidades deben ser mayores a cero y hasta 1.000 cm.')
    return {'levels':levels, 'depths':depths}


def geography(user):
    import infrastructure
    if profiles.profile_of(user) != 'replenisher':
        return infrastructure.REGIONS
    scope = profiles.store_scope(user)
    stores = [s for s in infrastructure.list_stores() if s['code'] in scope and s['status']=='Activo']
    selected = {}
    for store in stores:
        try:
            region, commune = infrastructure._location(store['region'], store['commune'])
        except ManagementError:
            continue
        selected.setdefault(region,set()).add(commune)
    return [{**region,'communes':[c for c in region['communes'] if c['name'] in selected[region['name']]]}
            for region in infrastructure.REGIONS if region['name'] in selected]


def options(user):
    import plan_assignments
    plan_assignments.prepare()
    import infrastructure
    scope = profiles.store_scope(user)
    types = []
    with db.get_conn() as conn:
        stores = conn.execute("SELECT code FROM management_stores WHERE deleted=0 AND status='Activo'").fetchall()
        manual = [s['code'] for s in stores if (scope is None or s['code'] in scope) and not has_shelves(conn, s['code'])]
        rows = conn.execute("SELECT a.store_code,t.* FROM management_assignments a JOIN management_shelf_types t ON t.id=a.type_id JOIN management_stores s ON s.code=a.store_code WHERE a.quantity>0 AND t.deleted=0 AND t.status='Activo' AND s.deleted=0 AND s.status='Activo'").fetchall()
        for row in rows:
            if scope is None or row['store_code'] in scope:
                types.append(infrastructure._type_public(row))
    return {'categories': settings_service.read()['state']['catalog']['categories'], 'manual_stores':manual, 'types':types,'shared_plan_assignments':True}


def manual_point(code, user, values, allow_assigned=False):
    identity = json.dumps([code, user['username'], values], sort_keys=True, ensure_ascii=False)
    point_id = MANUAL_PREFIX + hashlib.sha256(identity.encode()).hexdigest()[:32]
    with db.get_conn() as conn:
        catalog_service.lock_catalog(conn)
        existing = conn.execute('SELECT store_id FROM points WHERE id=?', (point_id,)).fetchone()
        if existing:
            if existing['store_id'] != code:
                raise ManagementError('El punto de captura no corresponde al PDV.', 409)
            return point_id
        store = manual_store(conn, code, allow_assigned)
        validate_selection(values, conn)
        db.create_point(point_id, store['name'] + ' · Captura con ancho manual', store_id=code, gondola_id='Captura manual', conn=conn)
    return point_id


def reference_plans(user, store, category='', subcategories=(), plan_id=None, type_id=None):
    import plan_assignments
    scope=profiles.store_scope(user)
    if scope is not None and store not in scope:raise ManagementError('El PDV está fuera de tu ámbito.',403)
    plan_assignments.prepare()
    with db.get_conn() as conn:
        manual_store(conn,store,allow_assigned=True)
        if not plan_id:
            if not category or not subcategories:return []
            validate_selection(selection(category,subcategories=list(subcategories)),conn)
        allowed={r['plan_id'] for r in plan_assignments.available(conn,store,category,subcategories,type_id)}
        result=[]
        for row in conn.execute('SELECT p.id,p.name,m.data_json FROM planograms p JOIN management_planograms m ON m.id=p.id').fetchall():
            meta=json.loads(row['data_json'])
            if meta.get('status','Activo')!='Activo':continue
            if row['id'] not in allowed:
                continue
            if plan_id and row['id']!=plan_id:continue
            position_count=conn.execute('SELECT COUNT(*) AS n FROM planogram_items WHERE planogram_id=?',(row['id'],)).fetchone()['n']
            if plan_id:return {key:meta.get(key,'') for key in ('photo','document','document_name')} | {'id':row['id'],'name':row['name'],'document_pages':meta.get('document_pages',0),'category':meta.get('category',''),'subcategories':meta.get('subcategories',[]),'position_count':position_count}
            result.append({'id':row['id'],'name':row['name'],'subcategories':meta.get('subcategories',[]),'has_reference':bool(meta.get('photo') or meta.get('document')),'position_count':position_count})
        if plan_id:raise ManagementError('El planograma no está disponible en este PDV y tipo de góndola.',404)
        return sorted(result,key=lambda r:r['name'].casefold())
