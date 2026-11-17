"""Internal console isolation, identity persistence and server-only model binding."""
import copy
import json
import os
from unittest.mock import patch
import httpx


class ConsoleCases:
    def test_training_queue_skips_verified_recent_readings_to_reach_older_work(self):
        import json
        trainer=self.trainer()
        products=[{'product':'Synthetic product','facings':1,'needs_review':True,'image_index':0,'item_index':0,'shelf_level':1}]
        reading=self.db.add_reading('point-a',{**self.analysis,'products':products},[],captured_by='replenisher')
        for index in range(21):
            done=self.db.add_reading('point-a',{**self.analysis,'products':products},[],captured_by='replenisher')
            with self.db.get_conn() as conn:
                conn.execute('INSERT INTO management_training_labels(id,reading_id,image_index,item_index,data_json,crop_path,created_by,created_at) VALUES(?,?,0,0,?,?,?,?)',
                             ('done-'+str(index),done['id'],json.dumps({'title':'Known','facings':1}),'_training/test-'+str(index),'local-neura',self.db.now_iso()))
        with patch.object(self.core,'review_items_for_reading',side_effect=lambda r,**kw:{'reading_id':r['id'],'items':[{'image_index':0,'item_index':0}]}):
            result=trainer.get('/api/review/pending')
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual([row['reading_id'] for row in result.json()],[reading['id']])

    def trainer(self):
        response=self.console_operator().post('/api/internal/training/accounts',json={'username':'local-neura','password':'Provider-training-test-2026!'})
        self.assertEqual(response.status_code,200,response.text)
        return self.client('local-neura')

    def test_provider_training_role_is_internal_and_customer_admin_cannot_assign_it(self):
        trainer=self.trainer();me=trainer.get('/api/auth/me').json()
        self.assertEqual(me['profile'],'local-neura');self.assertTrue(me['internal'])
        self.assertEqual(set(me['permissions']),{'read','train'})
        admin=self.client('admin')
        self.assertNotIn('local-neura',admin.get('/api/admin/users').text)
        self.assertNotIn('local-neura',admin.get('/api/admin/people').text)
        self.assertEqual(admin.post('/api/admin/users',json={'username':'forged','password':'Strong-password-2026!','role':'local-neura'}).status_code,400)
        self.assertEqual(admin.patch('/api/admin/users/analyst',json={'role':'local-neura'}).status_code,400)
        for path in ('/api/internal/clients','/api/admin/people','/api/admin/settings','/api/dashboard'):
            self.assertEqual(trainer.get(path).status_code,403,path)
        self.assertEqual(trainer.patch(f"/api/readings/{self.own['id']}/review",json={'status':'Aprobado','note':'','version':0}).status_code,403)
        self.assertEqual(admin.delete('/api/admin/users/local-neura').status_code,403)
        self.assertEqual(admin.post('/api/internal/training/accounts',json={'password':'Strong-password-2026!'}).status_code,403)
        with self.db.get_conn() as conn:
            conn.execute("UPDATE users SET is_internal=0 WHERE username='local-neura'")
        self.assertEqual(trainer.get('/api/auth/me').status_code,403)

    def test_training_labels_preserve_client_measurement_review_and_photos(self):
        import copy,json,measurement_reports
        trainer=self.trainer()
        analysis={**self.analysis,'products':[{'product':'Synthetic product','facings':2,'needs_review':True,'image_index':0,'item_index':0,'shelf_level':1}]}
        reading=self.db.add_reading('point-a',analysis,['point-a/training-example.jpg'],captured_by='replenisher')
        measurement_reports.save_review(reading['id'],'Aprobado','',0,'analyst')
        before=copy.deepcopy(self.db.get_reading(reading['id']))
        body={'image_index':0,'item_index':0,'title':'Verified product','facings':3}
        path=f"/api/readings/{reading['id']}/confirm"
        for role in ('admin','analyst','replenisher','viewer'):
            self.assertEqual(self.client(role).post(path,json=body).status_code,403)
            self.assertEqual(self.client(role).get('/api/review/pending').status_code,403)
            self.assertEqual(self.client(role).get('/api/internal/training/labels.jsonl').status_code,403)
        response=trainer.post(path,json=body);self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['training_only'])
        self.assertEqual(trainer.post(path,json=body).json()['label_id'],response.json()['label_id'])
        self.assertEqual(trainer.post(path,json={**body,'facings':4}).status_code,409)
        self.assertEqual(self.db.get_reading(reading['id']),before)
        self.core.confirm_reading_item.assert_not_called()
        self.assertEqual(self.storage.put.call_count,1)
        exported=trainer.get('/api/internal/training/labels.jsonl');self.assertEqual(exported.status_code,200)
        label=json.loads(exported.text.strip());self.assertEqual(label['title'],'Verified product')
        self.assertEqual(label['original_product']['product'],'Synthetic product')
        self.assertEqual(self.client('admin').get('/uploads/_training/'+label['id']+'.jpg').status_code,404)
        self.assertEqual(self.client('analyst').get(label['crop_url']).status_code,403)
        self.db.delete_reading(reading['id'])
        self.assertEqual(trainer.get(label['crop_url']).status_code,200)

    def console_operator(self):
        import client_identity
        client_identity.seed_local_operator()
        return self.client('local-internal')

    def console_current(self, client):
        directory = client.get('/api/internal/clients').json()
        return directory['deployment_client_id'], client.get('/api/internal/clients/' + directory['deployment_client_id']).json()

    def test_console_separate_permission_and_portal_access(self):
        for role in (None, 'admin', 'analyst', 'replenisher', 'viewer'):
            client = self.client(role)
            expected = 401 if role is None else 403
            for method, path, data in [('get', '', None), ('get', '/unknown', None), ('patch', '/unknown', {'tenant':{},'version':1})]:
                response = getattr(client, method)('/api/internal/clients' + path, **({'json':data} if data else {}))
                self.assertEqual(response.status_code, expected, response.text)
        operator = self.console_operator()
        me = operator.get('/api/auth/me').json()
        self.assertTrue(me['internal']); self.assertFalse(me['portal_access'])
        self.assertEqual(me['permissions'], ['console']); self.assertIsNone(me['tenant'])
        for path in ('/api/summary', '/api/admin/people', '/api/admin/settings', '/api/dashboard'):
            self.assertEqual(operator.get(path).status_code, 403)
        admin = self.client('admin')
        self.assertFalse(admin.get('/api/auth/me').json()['internal'])
        self.assertNotIn('local-internal', admin.get('/api/admin/users').text)
        self.assertNotIn('local-internal', admin.get('/api/admin/people').text)
        self.assertEqual(admin.patch('/api/admin/users/local-internal', json={'role':'analyst'}).status_code, 403)
        self.assertEqual(admin.delete('/api/admin/users/local-internal').status_code, 403)
        attempt = admin.post('/api/admin/people', json={'person':self.person_payload('local-internal'),'enable_access':True,'password':'Attempted-password-2026!'})
        self.assertEqual(attempt.status_code, 403, attempt.text)

    def test_console_local_operator_seed_idempotence_and_collision_protection(self):
        import client_identity
        self.console_operator()
        before = self.db.get_user('local-internal')
        client_identity.seed_local_operator()
        self.assertEqual(self.db.get_user('local-internal'), before)
        with self.db.get_conn() as conn:
            conn.execute('UPDATE users SET is_internal=0,portal_access=1 WHERE username=?', ('local-internal',))
        with self.assertRaises(ValueError): client_identity.seed_local_operator()
        after = self.db.get_user('local-internal')
        self.assertEqual(after['is_internal'], 0); self.assertEqual(after['portal_access'], 1)

    def test_console_versions_and_other_client_isolation_preserve_catalogs(self):
        operator = self.console_operator()
        client_id, initial = self.console_current(operator)
        tenant = copy.deepcopy(initial['tenant'])
        with self.db.get_conn() as conn:
            tenant['catalog'] = {'brands':['Private classification']}
            conn.execute('UPDATE management_clients SET tenant_json=? WHERE id=?', (json.dumps(tenant),client_id))
            other = {**tenant,'id':'other-client','name':'Other client'}
            conn.execute('INSERT INTO management_clients (id,slug,name,tenant_json,model_json,updated_at) VALUES (?,?,?,?,?,?)', ('other-id','other-client','Other client',json.dumps(other),json.dumps(initial['model']),self.db.now_iso()))
            before = {table:[dict(row) for row in conn.execute('SELECT * FROM ' + table).fetchall()] for table in ('points','readings','management_stores','management_products','management_settings')}
        payload = {'version':1,'tenant':{**other,'name':'Other renamed','catalog':{'brands':['Overwrite attempt']}}}
        self.assertEqual(operator.patch('/api/internal/clients/other-id',json=payload).status_code,200)
        self.assertEqual(self.client('admin').get('/api/auth/me').json()['tenant']['name'], 'Salcobrand')
        saved = operator.get('/api/internal/clients/other-id').json()
        self.assertEqual(saved['tenant']['catalog'], tenant['catalog'])
        self.assertEqual(saved['version'],2)
        self.assertEqual(operator.patch('/api/internal/clients/other-id',json=payload).status_code,409)
        self.assertEqual(operator.patch('/api/internal/clients/'+client_id,json={'version':1,'tenant':other}).status_code,400)
        me = self.client('admin').get('/api/auth/me').json()
        self.assertNotIn('catalog',me['tenant']); self.assertNotIn('model',me)
        self.assertNotIn('INTEGRATION_',json.dumps(me))
        with self.db.get_conn() as conn:
            self.assertEqual(before,{table:[dict(row) for row in conn.execute('SELECT * FROM ' + table).fetchall()] for table in before})

    def test_console_invalid_identity_and_model_references_never_persist(self):
        operator = self.console_operator(); client_id, initial = self.console_current(operator)
        invalid = [{'schema':True}, {'name':''}, {'primaryColor':'red'}, {'logo':'data:image/png;base64,ZmFrZQ=='},
                   {'modules':{'vision':1,'planograms':True,'sales':False}}, {'typography':{'sidebar':{'fontFamily':'url(evil)'}}},
                   {'typography':{'sidebar':{'fontSize':10.5}}}, {'typography':{'content':{'fontSize':15}}}]
        for changes in invalid:
            response = operator.patch('/api/internal/clients/'+client_id,json={'version':1,'tenant':{**initial['tenant'],**changes}})
            self.assertEqual(response.status_code,400,response.text)
        for model in ({'remoteOrgId':'other org'}, {'credentialEnv':'AWS_SECRET_ACCESS_KEY'}, {'apiKey':'never-persist-this'}, {'remoteOrgId':False}):
            response = operator.patch('/api/internal/clients/'+client_id,json={'version':1,'tenant':initial['tenant'],'model':model})
            self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(operator.get('/api/internal/clients/'+client_id).json(),initial)

    def test_console_model_binding_waits_for_captures_and_recovery(self):
        operator = self.console_operator(); client_id, initial = self.console_current(operator)
        payload = {'tenant':initial['tenant'],'version':1,'model':{'remoteOrgId':'customer-123','credentialEnv':'INTEGRATION_QA_KEY'}}
        job = self.capture(self.client('analyst')).json()
        self.assertEqual(operator.patch('/api/internal/clients/'+client_id,json=payload).status_code,409)
        identity_only = {'tenant':{**initial['tenant'],'name':'Renamed'},'version':1}
        self.assertEqual(operator.patch('/api/internal/clients/'+client_id,json=identity_only).status_code,200)
        with self.db.get_conn() as conn:
            conn.execute("UPDATE api_jobs SET status='failed',payload_json=? WHERE job_id=?",(json.dumps({'remote_submitted':True}),job['job_id']))
        payload['version'] = 2
        self.assertEqual(operator.patch('/api/internal/clients/'+client_id,json=payload).status_code,409)
        self.db.finish_job(job['job_id'],'done',reading_id=self.own['id'])
        self.assertEqual(operator.patch('/api/internal/clients/'+client_id,json=payload).status_code,200)
        self.assertEqual(self.client('admin').get('/api/auth/me').json()['tenant']['name'],'Salcobrand')
        self.assertNotIn('INTEGRATION_QA_KEY',self.client('viewer').get('/api/auth/me').text)
        self.assertEqual(operator.get('/api/internal/clients/'+client_id).json()['model'],payload['model'])
        # Omitting model leaves the current binding unchanged.
        self.assertEqual(operator.patch('/api/internal/clients/'+client_id,json={**identity_only,'version':3}).status_code,200)
        self.assertEqual(operator.get('/api/internal/clients/'+client_id).json()['model'],payload['model'])

    def test_console_model_key_verifies_organization_before_analysis(self):
        import remote_model
        operator = self.console_operator(); client_id, initial = self.console_current(operator)
        operator.patch('/api/internal/clients/'+client_id,json={'tenant':initial['tenant'],'version':1,'model':{'remoteOrgId':'customer-123','credentialEnv':'INTEGRATION_QA_KEY'}})
        calls = []
        def handler(request):
            calls.append(request.url.path)
            self.assertEqual(request.headers['X-API-Key'],'secret-test-only')
            return httpx.Response(200,json={'org_id':'different-client'})
        with patch.dict(os.environ,{'INTEGRATION_QA_KEY':'secret-test-only','NEURAVISION_REMOTE_URL':'https://provider.invalid'}):
            with httpx.Client(base_url='https://provider.invalid',transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(ValueError): remote_model.authenticate(client)
            self.assertEqual(calls,['/api/auth/me'])
            def authorized(request): return httpx.Response(200,json={'org_id':'customer-123'})
            with httpx.Client(base_url='https://provider.invalid',transport=httpx.MockTransport(authorized)) as client:
                remote_model.authenticate(client)
                self.assertEqual(client.headers['X-API-Key'],'secret-test-only')
        with self.db.get_conn() as conn:
            self.assertNotIn('secret-test-only',json.dumps([dict(row) for row in conn.execute('SELECT * FROM management_events').fetchall()]))

    def test_console_planogram_flag_freezes_capture_without_changing_assignment(self):
        operator = self.console_operator(); client_id, initial = self.console_current(operator)
        tenant = copy.deepcopy(initial['tenant']); tenant['modules']['planograms'] = False
        self.assertEqual(operator.patch('/api/internal/clients/'+client_id,json={'tenant':tenant,'version':1}).status_code,200)
        self.db.set_point_planogram('point-a','old-plan')
        job = self.capture(self.client('analyst')).json()
        payload = self.db.get_job(job['job_id'])['payload']
        self.assertIsNone(payload['planogram_id']); self.assertIsNone(payload['plan_snapshot'])
        self.assertEqual(self.db.get_point('point-a')['planogram_id'],'old-plan')
