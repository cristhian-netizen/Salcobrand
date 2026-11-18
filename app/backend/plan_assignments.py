"""Versioned, scoped assignments of shared planograms. Historical readings are never rewritten."""
import json
import db
import catalog_service as catalog
import infrastructure
from infrastructure import ManagementError, _audit, _row


def initialize(conn):
    """Caller holds the catalog lock. Preserve legacy point/store assignments once."""
    rows=conn.execute('SELECT m.* FROM management_planograms m LEFT JOIN management_plan_scope_state s ON s.plan_id=m.id WHERE s.plan_id IS NULL').fetchall()
    changed=False
    for row in rows:
        meta=json.loads(row['data_json']);category=meta.get('category');subs=meta.get('subcategories') or []
        if not category or not subs:
            continue
        points=conn.execute('SELECT p.store_id,i.type_id FROM points p LEFT JOIN management_instances i ON i.point_id=p.id WHERE p.planogram_id=?',(row['id'],)).fetchall()
        targets={(p['store_id'],p['type_id'] or '') for p in points if p['store_id']}
        if meta.get('store_code') and not any(code==meta['store_code'] for code,_ in targets):
            targets.add((meta['store_code'],''))
        for store,type_id in targets:
            conn.execute('INSERT INTO management_stores(code,name,created_at,updated_at) VALUES (?,?,?,?) ON CONFLICT DO NOTHING',(store,store,db.now_iso(),db.now_iso()))
            for sub in subs:
                insert(conn,row['id'],store,category,sub,type_id,'migration')
        conn.execute('INSERT INTO management_plan_scope_state(plan_id,initialized_at) VALUES (?,?) ON CONFLICT DO NOTHING',(row['id'],db.now_iso()))
        changed=True
    if changed:
        catalog.changed(conn)


def prepare():
    infrastructure.bootstrap_legacy_stores()
    with db.get_conn() as conn:
        catalog.lock_catalog(conn)
        initialize(conn)


def insert(conn,plan,store,category,sub,type_id,actor):
    conn.execute('INSERT INTO management_plan_scopes(plan_id,store_code,category,subcategory,type_id,assigned_by,assigned_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                 (plan,store,category,sub,type_id,actor,db.now_iso()))


def rows(conn):
    result=[]
    for row in conn.execute('SELECT s.*,p.name,m.data_json FROM management_plan_scopes s JOIN planograms p ON p.id=s.plan_id JOIN management_planograms m ON m.id=s.plan_id').fetchall():
        item=dict(row);meta=json.loads(item.pop('data_json'))
        item['status']=meta.get('status','Activo');result.append(item)
    return result


def summary(plan_id):
    with db.get_conn() as conn:
        catalog.lock_catalog(conn);initialize(conn)
        assigned=[dict(r) for r in conn.execute('SELECT store_code,type_id,category,subcategory FROM management_plan_scopes WHERE plan_id=?',(plan_id,)).fetchall()]
        initialized=bool(conn.execute('SELECT 1 FROM management_plan_scope_state WHERE plan_id=?',(plan_id,)).fetchone())
        codes={r['store_code'] for r in assigned}
        if not initialized:
            record=conn.execute('SELECT data_json FROM management_planograms WHERE id=?',(plan_id,)).fetchone()
            meta=json.loads(record['data_json']) if record else {}
            codes.update(r['store_id'] for r in conn.execute('SELECT DISTINCT store_id FROM points WHERE planogram_id=?',(plan_id,)).fetchall() if r['store_id'])
            if meta.get('store_code'):codes.add(meta['store_code'])
    return {'assigned_store_codes':sorted(codes),'assigned_count':len(codes),'assignments':assigned,'shared_assignments':initialized}


def details(plan_id):
    infrastructure.bootstrap_legacy_stores()
    stores=infrastructure.list_stores(include_deleted=True)
    types=infrastructure.list_types()
    with db.get_conn() as conn:
        catalog.lock_catalog(conn);initialize(conn)
        _row(conn,'planograms','id',plan_id)
        meta=_row(conn,'management_planograms','id',plan_id)
        bindings=rows(conn)
        quantities=[dict(r) for r in conn.execute('SELECT store_code,type_id FROM management_assignments WHERE quantity>0').fetchall()]
        for store in stores:
            store['type_ids']=[r['type_id'] for r in quantities if r['store_code']==store['code']]
            store['references']=[r for r in bindings if r['store_code']==store['code'] and r['status']=='Activo']
        version=catalog.lock_catalog(conn)
    return {'stores':stores,'types':types,'assignments':[r for r in bindings if r['plan_id']==plan_id],
            'version':version,'plan_version':meta['version']}


def preview(conn,plan_id,stores,type_id=None,replace_conflicts=False):
    meta=json.loads(_row(conn,'management_planograms','id',plan_id)['data_json'])
    subs=meta.get('subcategories') or []
    if not meta.get('category') or len(subs)!=1:
        raise ManagementError('Selecciona y guarda una única subcategoría del planograma antes de asignarlo.',409)
    if len(stores)>10000 or len(stores)!=len(set(stores)):
        raise ManagementError('Selecciona hasta 10.000 PDV sin duplicados.')
    if stores and meta.get('status')!='Activo':raise ManagementError('Activa el planograma antes de asignarlo; también puedes quitar todas sus asignaciones.',409)
    if type_id and stores:
        shelf=_row(conn,'management_shelf_types','id',type_id)
        if shelf['deleted'] or shelf['status']!='Activo':raise ManagementError('El tipo de góndola no está activo.',409)
    category,sub=meta['category'],subs[0]
    bindings=rows(conn)
    current_bindings=[r for r in bindings if r['plan_id']==plan_id and (type_id is None or r['type_id']==type_id)]
    current={r['store_code'] for r in current_bindings}
    selected=set(stores)
    for code in selected:
        store=_row(conn,'management_stores','code',code)
        if code not in current:
            if store['deleted'] or store['status']!='Activo' or meta.get('status')!='Activo':
                raise ManagementError('Solo puedes añadir PDV y planogramas activos.',409)
            if type_id and not conn.execute('SELECT 1 FROM management_assignments WHERE store_code=? AND type_id=? AND quantity>0',(code,type_id)).fetchone():
                raise ManagementError('El tipo de góndola seleccionado no está asignado al PDV '+code+'.',409)
    targets={(code,t) for code in selected for t in ({r['type_id'] for r in current_bindings if r['store_code']==code} or {''})} if type_id is None else {(code,type_id) for code in selected}
    conflicts=[r for r in bindings if (r['store_code'],r['type_id']) in targets and r['plan_id']!=plan_id and r['category']==category and r['subcategory']==sub and r['status']=='Activo']
    return {'selected':len(selected),'added':sorted(selected-current),'removed':sorted(current-selected),
            'conflicts':conflicts,'category':category,'subcategory':sub,'type_id':type_id}


def change(plan_id,payload,actor,commit=False):
    with db.get_conn() as conn:
        catalog.lock_catalog(conn);initialize(conn)
        catalog.lock_catalog(conn,payload['version'])
        result=preview(conn,plan_id,payload['stores'],payload.get('type_id'))
        if not commit:return {**result,'version':payload['version']}
        if result['conflicts'] and not payload.get('replace_conflicts'):
            raise ManagementError('Hay PDV con otra referencia activa. Revisa la vista previa y confirma el reemplazo.',409)
        for conflict in result['conflicts']:
            conn.execute('DELETE FROM management_plan_scopes WHERE plan_id=? AND store_code=? AND category=? AND subcategory=? AND type_id=?',
                         tuple(conflict[k] for k in ('plan_id','store_code','category','subcategory','type_id')))
        if result['type_id'] is None:
            previous=[r for r in rows(conn) if r['plan_id']==plan_id]
            selected=set(payload['stores'])
            targets={(store,t) for store in selected for t in ({r['type_id'] for r in previous if r['store_code']==store} or {''})}
            for store in {r['store_code'] for r in previous}-selected:
                conn.execute('DELETE FROM management_plan_scopes WHERE plan_id=? AND store_code=?',(plan_id,store))
        else:
            conn.execute('DELETE FROM management_plan_scopes WHERE plan_id=? AND type_id=?',(plan_id,result['type_id']))
            targets={(store,result['type_id']) for store in payload['stores']}
        for store,type_id in targets:
            # Replace inactive references as well; they must not resurface on reactivation.
            conn.execute('DELETE FROM management_plan_scopes WHERE plan_id<>? AND store_code=? AND category=? AND subcategory=? AND type_id=?',
                         (plan_id,store,result['category'],result['subcategory'],type_id))
            insert(conn,plan_id,store,result['category'],result['subcategory'],type_id,actor)
        conn.execute('INSERT INTO management_plan_scope_state(plan_id,initialized_at) VALUES (?,?) ON CONFLICT DO NOTHING',(plan_id,db.now_iso()))
        catalog.changed(conn)
        _audit(conn,actor,'planogram.assignments',plan_id,None,{k:v for k,v in result.items() if k!='conflicts'})
        return {**result,'version':catalog.lock_catalog(conn),'saved':True}


def reclassify(conn,plan_id,category,subs):
    old=[dict(r) for r in conn.execute('SELECT * FROM management_plan_scopes WHERE plan_id=?',(plan_id,)).fetchall()]
    if not old or all(r['category']==category and r['subcategory'] in subs for r in old) and {r['subcategory'] for r in old}==set(subs):return
    targets={(r['store_code'],r['type_id']) for r in old}
    others=[r for r in rows(conn) if r['plan_id']!=plan_id and r['status']=='Activo']
    if any((r['store_code'],r['type_id']) in targets and r['category']==category and r['subcategory'] in subs for r in others):
        raise ManagementError('La nueva subcategoría tiene referencias activas en esos PDV. Desasigna el planograma antes de cambiarla.',409)
    conn.execute('DELETE FROM management_plan_scopes WHERE plan_id=?',(plan_id,))
    for store,type_id in targets:
        for sub in subs:insert(conn,plan_id,store,category,sub,type_id,'classification')


def available(conn,store,category='',subcategories=(),type_id=None):
    bindings=[r for r in rows(conn) if r['store_code']==store and r['status']=='Activo' and (not category or r['category']==category) and (not subcategories or r['subcategory'] in subcategories)]
    if type_id is None:return bindings
    result=[]
    for sub in {r['subcategory'] for r in bindings}:
        matched=[r for r in bindings if r['subcategory']==sub and r['type_id']==type_id] if type_id else []
        result.extend(matched or [r for r in bindings if r['subcategory']==sub and not r['type_id']])
    return result


def resolve(conn,store,values,type_id='',preferred=None):
    candidates=available(conn,store,values.get('category',''),values.get('subcategories') or ([values['subcategory']] if values.get('subcategory') else []),type_id)
    ids={r['plan_id'] for r in candidates}
    if preferred:
        if preferred not in ids:raise ManagementError('El planograma seleccionado ya no está asignado a este PDV, subcategoría o tipo de góndola.',409)
        return preferred
    if len(ids)>1:raise ManagementError('Hay varias referencias disponibles. Selecciona el planograma que deseas comparar.',409)
    return next(iter(ids),None)
