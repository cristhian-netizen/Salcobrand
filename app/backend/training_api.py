"""Provider-only training verification, isolated from production readings."""
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
import auth
import core
import db
import storage
from catalog_service import lock_catalog
from infrastructure import ManagementError, _text, _audit


def review_payload(reading):
    payload = core.review_items_for_reading(reading, crop_prefix='/api')
    with db.get_conn() as conn:
        labelled = {(r['image_index'],r['item_index']) for r in conn.execute('SELECT image_index,item_index FROM management_training_labels WHERE reading_id=?',(reading['id'],)).fetchall()}
    payload['items'] = [item for item in payload['items'] if (item['image_index'],item['item_index']) not in labelled]
    return payload


def pending():
    # Verified labels leave the original reading untouched. Skip them before
    # applying the page size so completed recent readings never hide older work.
    with db.get_conn() as conn:
        done={(row['reading_id'],row['image_index'],row['item_index']) for row in conn.execute('SELECT reading_id,image_index,item_index FROM management_training_labels').fetchall()}
    result=[];cursor=None
    while len(result)<20:
        with db.get_conn() as conn:
            rows=conn.execute('SELECT id,products_json FROM readings '+('WHERE id<? ' if cursor is not None else '')+'ORDER BY id DESC LIMIT 100',(cursor,) if cursor is not None else ()).fetchall()
        if not rows:break
        for row in rows:
            products=json.loads(row['products_json'])
            if any(p.get('needs_review') and p.get('item_index') is not None and (row['id'],p.get('image_index'),p['item_index']) not in done for p in products):
                reading=db.get_reading(row['id'])
                if reading:
                    payload=review_payload(reading)
                    if payload['items']:result.append(payload)
            if len(result)>=20:break
        cursor=rows[-1]['id']
    return result


def save_label(reading, image_index, item_index, title, facings, actor):
    title = _text(title or '', 'Producto verificado',180)
    if facings is not None and (type(facings) is not int or not 0 <= facings <= 5000):
        raise ManagementError('Las caras deben ser un entero entre 0 y 5.000.')
    target = next((p for p in reading['products'] if p.get('image_index')==image_index and p.get('item_index')==item_index),None)
    if target is None or image_index < 0 or item_index < 0:
        raise LookupError('Producto no encontrado en la lectura')
    label_id = uuid.uuid4().hex
    path = '_training/'+label_id+'.jpg'
    stored = False
    try:
        with db.get_conn() as conn:
            lock_catalog(conn)
            old = conn.execute('SELECT id,data_json FROM management_training_labels WHERE reading_id=? AND image_index=? AND item_index=?',(reading['id'],image_index,item_index)).fetchone()
            if old:
                values = json.loads(old['data_json'])
                if values['title'] != title or values['facings'] != facings:
                    raise ManagementError('Este producto ya fue verificado. Actualiza la lista.',409)
                return {'ok':True,'label_id':old['id'],'training_only':True}
            crop = core.crop_jpeg(reading,image_index,item_index)
            storage.put(path,crop,'image/jpeg');stored=True
            values = {'reading_id':reading['id'],'point_id':reading['point_id'],'image_index':image_index,'item_index':item_index,
                      'title':title,'facings':facings,'original_product':target,'planogram_id':reading.get('planogram_id'),
                      'captured_at':reading['created_at'],'verified_by':actor,'verified_at':db.now_iso()}
            conn.execute('INSERT INTO management_training_labels (id,reading_id,image_index,item_index,data_json,crop_path,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
                         (label_id,reading['id'],image_index,item_index,json.dumps(values),path,actor,values['verified_at']))
            _audit(conn,actor,'training.label',label_id,None,{'reading_id':reading['id'],'image_index':image_index,'item_index':item_index})
    except Exception:
        if stored:storage.delete_many([path])
        raise
    return {'ok':True,'label_id':label_id,'training_only':True}


class Account(BaseModel):
    username: str = 'local-neura'
    password: str = Field(min_length=4,max_length=512)


class KilbyTrain(BaseModel):
    catalog: str = Field(default='',max_length=80)  # required (409) when the workspace has several catalogs


def router(require_training, require_internal):
    api=APIRouter(prefix='/api/internal/training',tags=['Verificación interna para entrenamiento'])
    @api.post('/accounts')
    def create_account(payload:Account,user=Depends(require_internal)):
        username=_text(payload.username,'Usuario interno',80,True).lower()
        with db.get_conn() as conn:
            lock_catalog(conn)
            current=conn.execute('SELECT role,is_internal FROM users WHERE username=?',(username,)).fetchone()
            if current:
                if current['role']!='local-neura' or not current['is_internal']:
                    raise ManagementError('Ese usuario ya existe con otro perfil.',409)
                return {'username':username,'role':'local-neura','created':False}
            auth.validate_password(payload.password)
            hashed,salt=auth.hash_password(payload.password)
            db.create_user(username,hashed,salt,role='local-neura',conn=conn)
            _audit(conn,user['username'],'training.account',username,None,{'role':'local-neura'})
        return {'username':username,'role':'local-neura','created':True}

    @api.get('/labels.jsonl')
    def export(user=Depends(require_training)):
        with db.get_conn() as conn:
            rows=conn.execute('SELECT id,data_json FROM management_training_labels ORDER BY created_at,id').fetchall()
        content=''.join(json.dumps({**json.loads(row['data_json']),'id':row['id'],'crop_url':'/api/internal/training/labels/'+row['id']+'/crop.jpg'},ensure_ascii=False)+'\n' for row in rows)
        return Response(content,media_type='application/x-ndjson',headers={'Cache-Control':'no-store','Content-Disposition':'attachment; filename="Neuravision_Etiquetas_Entrenamiento.jsonl"'})

    @api.get('/labels/{label_id}/crop.jpg')
    def crop(label_id:str,request:Request,user=Depends(require_training)):
        with db.get_conn() as conn:
            row=conn.execute('SELECT crop_path FROM management_training_labels WHERE id=?',(label_id,)).fetchone()
        content=storage.get(row['crop_path']) if row else None
        if content is None:raise HTTPException(404,'Recorte no disponible.')
        import image_cache
        return image_cache.response(request,content,'image/jpeg',immutable=True)

    # Entrenar en Kilby. Depends on Kilby's Neuravision dataset API (contract 2026-11-18, not deployed yet).
    def kilby_call(action,*args):
        import kilby_catalog
        kn=kilby_catalog.kn
        try:
            return action(*args)
        except kn.NeuravisionError as exc:
            if exc.status==404 and exc.code in (None,'not_found'):
                raise HTTPException(503,'Kilby todavía no ofrece la API de catálogos y entrenamientos.')
            status=exc.status if exc.status in (403,409,429) else 502 if (exc.status or 500)>=500 else 409
            raise HTTPException(status,exc.message_es)
        except LookupError as exc:
            raise HTTPException(404,str(exc))
        except ValueError as exc:
            raise HTTPException(409,str(exc))

    @api.get('/kilby')
    def kilby_overview(user=Depends(require_training)):
        import kilby_catalog
        return JSONResponse(kilby_catalog.overview(),headers={'Cache-Control':'no-store'})

    @api.post('/kilby/sync')
    def kilby_sync(full:bool=False,user=Depends(require_training)):
        import kilby_catalog
        marked=kilby_catalog.mark_all() if full else None
        return {**kilby_call(kilby_catalog.drain),'marked':marked}

    @api.post('/kilby/trainings',status_code=202)
    def kilby_train(payload:KilbyTrain=None,user=Depends(require_training)):
        import kilby_catalog
        return kilby_call(kilby_catalog.start_training,user['username'],(payload.catalog if payload else '').strip() or None)

    @api.get('/kilby/trainings/{training_id}')
    def kilby_training(training_id:str,user=Depends(require_training)):
        import kilby_catalog
        return kilby_call(kilby_catalog.training_status,training_id)

    @api.post('/kilby/versions/{version}/publish')
    def kilby_publish(version:str,catalog:str=None,user=Depends(require_training)):
        import kilby_catalog
        return kilby_call(kilby_catalog.publish,version,user['username'],catalog)
    return api
