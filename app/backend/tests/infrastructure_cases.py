"""Management invariants exercised against authenticated routes and a real temporary DB."""
from unittest.mock import patch


class InfrastructureCases:
    def test_old_shelf_schema_upgrade_preserves_existing_rows(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.db'
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE management_shelf_types (id TEXT PRIMARY KEY,name TEXT NOT NULL,width_cm REAL NOT NULL,'
                             'depths_json TEXT NOT NULL,photo TEXT NOT NULL DEFAULT \'\',status TEXT NOT NULL DEFAULT \'Activo\','
                             'version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)')
                conn.execute('CREATE UNIQUE INDEX management_shelf_name_ci ON management_shelf_types(LOWER(name))')
                conn.execute("INSERT INTO management_shelf_types(id,name,width_cm,depths_json,created_at,updated_at) VALUES('old','Anterior',120,'[30,40]','2026-01-01','2026-01-01')")
            conn.close()
            with patch.object(self.db, 'DB_PATH', path):
                self.db.init_db()
                self.db.init_db()
                with self.db.get_conn() as conn:
                    row = dict(conn.execute('SELECT * FROM management_shelf_types').fetchone())
                self.assertEqual((row['id'],row['name'],row['depths_json'],row['version']), ('old','Anterior','[30,40]',1))
                self.assertEqual((row['kind'],row['supplier'],row['height_cm'],row['deleted']), ('Estante','',None,0))

    def test_shelf_kinds_supplier_height_and_photo(self):
        import base64
        import io
        from PIL import Image
        image = io.BytesIO()
        Image.new('RGB', (32, 32), 'teal').save(image, format='PNG')
        photo = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
        admin = self.client('admin')
        for kind in ('Estante', 'Vin', 'Vitrina'):
            payload = dict(name=kind, kind=kind, supplier='Fabricante QA', width_cm=120,
                           height_cm=None if kind == 'Vitrina' else 180,
                           depths=[30, 40] if kind == 'Estante' else [40], photo=photo)
            response = admin.post('/api/admin/shelf-types', json=payload)
            self.assertEqual(response.status_code, 201, response.text)
            shelf = response.json()
            self.assertEqual((shelf['kind'], shelf['supplier'], shelf['photo']), (kind, 'Fabricante QA', photo))
            legacy_update = {key:shelf[key] for key in ('name', 'width_cm', 'depths', 'photo', 'status', 'version')}
            updated = admin.patch('/api/admin/shelf-types/' + shelf['id'], json=legacy_update).json()
            self.assertEqual((updated['kind'], updated['height_cm'], updated['supplier']),
                             (shelf['kind'], shelf['height_cm'], shelf['supplier']))
        for payload in [dict(kind='Otro', height_cm=180, depths=[30]), dict(kind='Vin', height_cm=180, depths=[30, 40]),
                        dict(kind='Estante', height_cm=None, depths=[30])]:
            response = admin.post('/api/admin/shelf-types', json=dict(name='Inválida', width_cm=120, **payload))
            self.assertEqual(response.status_code, 400, response.text)

    def test_store_assignments_save_atomically_with_its_form(self):
        admin = self.client('admin')
        first = self.create_type()
        second = admin.post('/api/admin/shelf-types', json={'name':'Segundo', 'width_cm':100, 'depths':[30]}).json()
        payload = {**self.store_payload(), 'assignments':[
            {'type_id':first['id'], 'quantity':2, 'version':0},
            {'type_id':second['id'], 'quantity':1, 'version':0}]}
        response = admin.post('/api/admin/stores', json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        code = payload['code']
        state = admin.get('/api/admin/infrastructure?store_code=' + code).json()
        ids = {item['point_id'] for item in state['instances']}
        self.assertEqual(len(ids), 3)
        admin.put(f"/api/admin/stores/{code}/shelf-assignments/{second['id']}", json={'quantity':0,'version':1})
        changed = {**payload, 'name':'Cambio que debe revertirse', 'version':1,
                   'assignments':[{'type_id':first['id'],'quantity':1,'version':1},
                                  {'type_id':second['id'],'quantity':2,'version':1}]}
        changed.pop('code')
        self.assertEqual(admin.patch('/api/admin/stores/' + code, json=changed).status_code, 409)
        store = next(item for item in admin.get('/api/admin/stores').json() if item['code'] == code)
        self.assertEqual((store['name'], store['version']), (payload['name'], 1))
        state = admin.get('/api/admin/infrastructure?store_code=' + code).json()
        self.assertEqual(next(item['quantity'] for item in state['assignments'] if item['type_id'] == first['id']), 2)
        changed['assignments'][1]['version'] = 2
        self.assertEqual(admin.patch('/api/admin/stores/' + code, json=changed).status_code, 200)
        state = admin.get('/api/admin/infrastructure?store_code=' + code).json()
        self.assertTrue(ids.issubset({item['point_id'] for item in state['instances']}))
        failed = {**self.store_payload('ROLLBACK'), 'assignments':[{'type_id':'missing','quantity':1,'version':0}]}
        self.assertEqual(admin.post('/api/admin/stores', json=failed).status_code, 404)
        self.assertNotIn('ROLLBACK', {item['code'] for item in admin.get('/api/admin/stores').json()})

    def test_shelf_delete_retires_assignments_and_preserves_history(self):
        admin = self.client('admin')
        admin.get('/api/admin/stores')
        shelf = self.create_type()
        admin.post('/api/admin/shelf-instances/link-existing', json={
            'store_code':'L128','type_id':shelf['id'],'point_id':'point-a','version':0})
        path = '/api/admin/shelf-types/' + shelf['id']
        for role in (None, 'analyst', 'replenisher', 'viewer'):
            self.assertEqual(self.client(role).delete(path + '?version=1').status_code, 401 if role is None else 403)
        self.assertEqual(admin.delete(path + '?version=2').status_code, 409)
        self.assertEqual(admin.delete(path + '?version=1').status_code, 200)
        self.assertNotIn(shelf['id'], {item['id'] for item in admin.get('/api/admin/shelf-types').json()})
        state = admin.get('/api/admin/infrastructure?store_code=L128').json()
        self.assertEqual(state['assignments'][0]['quantity'], 0)
        self.assertFalse(state['instances'][0]['active'])
        self.assertEqual(state['instances'][0]['point_id'], 'point-a')
        self.assertIsNotNone(self.db.get_reading(self.own['id']))
        self.assertFalse(admin.get('/api/points/point-a').json()['can_capture'])
        self.assertEqual(admin.get('/api/admin/stores/L128/history').json()[0]['action'], 'assignment.type-delete')
        self.assertEqual(admin.put(f"/api/admin/stores/L128/shelf-assignments/{shelf['id']}", json={'quantity':1,'version':2}).status_code, 409)
        replacement = self.create_type()
        self.assertNotEqual(replacement['id'], shelf['id'])
        self.db.init_db()
        self.assertEqual(len(admin.get('/api/admin/shelf-types').json()), 1)

    def store_payload(self, code="QA-001"):
        return dict(code=code, name="Farmacia de prueba", store_type="Farmacia", region="Metropolitana de Santiago",
                    commune="Santiago", address="Dirección ficticia 123", manager="Encargado ficticio", status="Activo")

    def create_type(self):
        response = self.client("admin").post('/api/admin/shelf-types', json=dict(name="Góndola QA", width_cm=120, depths=[35,40]))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_management_permission_matrix_and_store_scope(self):
        for role in (None,"analyst","viewer","replenisher"):
            client=self.client(role)
            for path in ('stores','shelf-types','infrastructure','location-catalog'):
                self.assertEqual(client.get('/api/admin/'+path).status_code,401 if role is None else 403)
            self.assertEqual(client.post('/api/admin/stores',json=self.store_payload()).status_code,401 if role is None else 403)
            self.assertEqual(client.post('/api/admin/shelf-types',json={}).status_code,401 if role is None else 403)
            self.assertEqual(client.put('/api/admin/stores/L128/shelf-assignments/fake',json={'quantity':1,'version':0}).status_code,401 if role is None else 403)
        visible=self.client('replenisher').get('/api/stores').json()
        self.assertEqual({s['code'] for s in visible},{'L128','L129'})
        self.assertNotIn('manager',visible[0])

    def test_store_crud_geography_versions_and_audit(self):
        admin=self.client('admin');payload=self.store_payload()
        bad={**payload,'commune':'Comuna inexistente'}
        self.assertEqual(admin.post('/api/admin/stores',json=bad).status_code,400)
        response=admin.post('/api/admin/stores',json=payload)
        self.assertEqual(response.status_code,201,response.text)
        store=response.json();self.assertEqual(store['version'],1)
        self.assertEqual(admin.post('/api/admin/stores',json={**payload,'code':'qa-001'}).status_code,409)
        update={k:v for k,v in payload.items() if k!='code'};update.update(name='Nombre editado',version=1)
        self.assertEqual(admin.patch('/api/admin/stores/QA-001',json=update).status_code,200)
        self.assertEqual(admin.patch('/api/admin/stores/QA-001',json=update).status_code,409)
        history=admin.get('/api/admin/stores/QA-001/history').json()
        self.assertEqual([h['action'] for h in history],['store.update','store.create'])
        self.assertTrue(all(h['actor']=='admin' for h in history))

    def test_legacy_bootstrap_does_not_change_point_ids_or_fabricate_location(self):
        admin=self.client('admin')
        first=admin.get('/api/admin/stores').json();second=admin.get('/api/admin/stores').json()
        self.assertEqual({s['code'] for s in first},{'L128','L129','L130'})
        self.assertEqual(first,second)
        self.assertTrue(all(s['needs_completion'] and not s['region'] for s in first))
        self.assertEqual(self.db.get_reading(self.own['id'])['point_id'],'point-a')

    def test_quantity_reuses_ids_and_linking_preserves_history(self):
        admin=self.client('admin');admin.get('/api/admin/stores');t=self.create_type()
        path=f"/api/admin/stores/L128/shelf-assignments/{t['id']}"
        initial=admin.put(path,json={'quantity':2,'version':0}).json()
        ids={i['point_id'] for i in initial['instances']}
        self.assertEqual(len(ids),2)
        self.assertEqual(admin.put(path,json={'quantity':1,'version':0}).status_code,409)
        reduced=admin.put(path,json={'quantity':1,'version':1}).json()
        self.assertEqual(sum(i['active'] for i in reduced['instances']),1)
        linked=admin.post('/api/admin/shelf-instances/link-existing',json={'store_code':'L128','type_id':t['id'],'point_id':'point-a','version':2})
        self.assertEqual(linked.status_code,200,linked.text)
        active={i['point_id'] for i in linked.json()['instances'] if i['active']}
        same=admin.put(path,json={'quantity':2,'version':3}).json()
        self.assertEqual(active,{i['point_id'] for i in same['instances'] if i['active']})
        restored=admin.put(path,json={'quantity':3,'version':4}).json()
        self.assertEqual({i['point_id'] for i in restored['instances']},ids|{'point-a'})
        self.assertEqual(self.db.get_reading(self.own['id'])['point_id'],'point-a')
        self.assertEqual(admin.delete('/api/points/point-a').status_code,409)
        self.assertEqual(admin.post('/api/admin/shelf-instances/link-existing',json={'store_code':'L128','type_id':t['id'],'point_id':'point-c','version':5}).status_code,400)
        self.assertEqual(admin.put(path,json={'quantity':True,'version':5}).status_code,422)

    def test_inactive_structures_block_capture_and_keep_history(self):
        admin=self.client('admin');admin.get('/api/admin/stores');t=self.create_type()
        admin.post('/api/admin/shelf-instances/link-existing',json={'store_code':'L128','type_id':t['id'],'point_id':'point-a','version':0})
        self.assertEqual(admin.delete('/api/admin/stores/L128?version=1').status_code,200)
        self.assertIsNotNone(self.db.get_reading(self.own['id']))
        self.assertFalse(self.client('analyst').get('/api/points/point-a').json()['can_capture'])
        response=self.client('analyst').post('/api/points/point-a/analyze',files={'images':('test.jpg',b'test','image/jpeg')})
        self.assertEqual(response.status_code,409)
        self.jobs.enqueue.assert_not_called()
        self.assertNotIn('L128',{s['code'] for s in admin.get('/api/admin/stores').json()})
        restored=admin.post('/api/admin/stores/L128/restore',json={'version':2})
        self.assertEqual(restored.json()['status'],'Inactivo')

    def test_capture_geometry_snapshot_is_immutable(self):
        admin=self.client('admin');admin.get('/api/admin/stores');t=self.create_type()
        admin.post('/api/admin/shelf-instances/link-existing',json={'store_code':'L128','type_id':t['id'],'point_id':'point-a','version':0})
        with patch.object(self.db,'get_job',return_value={'status':'done','reading_id':self.own['id']}):
            r=self.client('replenisher').post('/api/points/point-a/analyze',files={'images':('test.jpg',b'test','image/jpeg')})
        self.assertEqual(r.status_code,200,r.text)
        context=self.jobs.enqueue.call_args.args[2]['infrastructure']
        self.assertEqual(context['depths'],[35,40])
        reading=self.db.add_reading('point-a',self.analysis,[],capture_context=context)
        update={k:t[k] for k in ('name','width_cm','depths','photo','status','version')};update['width_cm']=150
        self.assertEqual(admin.patch('/api/admin/shelf-types/'+t['id'],json=update).status_code,200)
        self.assertEqual(self.db.get_reading(reading['id'])['infrastructure']['width_cm'],120)

    def test_type_validation_and_instance_versions(self):
        admin=self.client('admin');admin.get('/api/admin/stores');t=self.create_type()
        self.assertEqual(admin.post('/api/admin/shelf-types',json={'name':'Bad','width_cm':0,'depths':[30]}).status_code,400)
        self.assertEqual(admin.post('/api/admin/shelf-types',json={'name':'Bad','width_cm':90,'depths':[]}).status_code,400)
        self.assertEqual(admin.post('/api/admin/shelf-types',json={'name':'Bad','width_cm':True,'depths':[30]}).status_code,422)
        self.assertEqual(admin.post('/api/admin/shelf-types',json={'name':'Bad','width_cm':90,'depths':[30],'photo':'data:image/jpeg;base64,ZmFrZQ=='}).status_code,400)
        state=admin.put(f"/api/admin/stores/L128/shelf-assignments/{t['id']}",json={'quantity':1,'version':0}).json()
        instance=state['instances'][0]
        path='/api/admin/shelf-instances/'+instance['id'];body={'version':1,'label':'Pasillo 2','note':'QA'}
        self.assertEqual(admin.patch(path,json=body).status_code,200)
        self.assertEqual(admin.patch(path,json=body).status_code,409)

    def test_inactive_type_and_quantity_block_new_captures(self):
        admin=self.client('admin');admin.get('/api/admin/stores');t=self.create_type()
        link=admin.post('/api/admin/shelf-instances/link-existing',json={'store_code':'L128','type_id':t['id'],'point_id':'point-a','version':0})
        self.assertEqual(link.status_code,200)
        path=f"/api/admin/stores/L128/shelf-assignments/{t['id']}"
        admin.put(path,json={'quantity':0,'version':1})
        self.assertFalse(admin.get('/api/points/point-a').json()['can_capture'])
        self.assertIsNotNone(self.db.get_reading(self.own['id']))
        admin.put(path,json={'quantity':1,'version':2})
        self.assertTrue(admin.get('/api/points/point-a').json()['can_capture'])
        update={k:t[k] for k in ('name','width_cm','depths','photo','status','version')};update['status']='Inactivo'
        self.assertEqual(admin.patch('/api/admin/shelf-types/'+t['id'],json=update).status_code,200)
        self.assertFalse(admin.get('/api/points/point-a').json()['can_capture'])
        self.assertEqual(admin.put(path,json={'quantity':2,'version':3}).status_code,409)
