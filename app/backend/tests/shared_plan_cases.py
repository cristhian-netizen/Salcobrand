"""Shared references, atomic assignments, permissions and frozen capture history."""
import json


class SharedPlanCases:
    def shared_master(self, name='Shared QA'):
        product=self.create_product(sku=name,barcode="bar-"+name)
        self.client('admin').get('/api/admin/stores')
        body={**self.plan_fields(product),'store_code':None,'name':name,'category':product['category'],'subcategories':[product['subcategory']]}
        response=self.client('admin').post('/api/admin/catalog/planograms',json=body)
        self.assertEqual(response.status_code,201,response.text)
        return response.json(),body

    def assignment(self,plan,stores,type_id='',commit=True,replace=False,version=None):
        client=self.client('admin');path='/api/admin/catalog/planograms/'+plan['id']+'/assignments'
        if version is None:version=client.get(path).json()['version']
        body={'stores':stores,'type_id':type_id,'version':version,'replace_conflicts':replace}
        return client.put(path,json=body) if commit else client.post(path+'/preview',json=body)

    def test_shared_plan_country_assignments_preview_atomicity_and_removal(self):
        plan,body=self.shared_master();admin=self.client('admin')
        self.assertEqual(plan['assigned_count'],0)
        preview=self.assignment(plan,['L128','L129'],commit=False)
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(admin.get('/api/admin/catalog/planograms/'+plan['id']).json()['assigned_count'],0)
        self.assertEqual(self.assignment(plan,['L128','missing']).status_code,404)
        self.assertEqual(self.assignment(plan,['L128','L129']).status_code,200)
        detail=admin.get('/api/admin/catalog/planograms/'+plan['id']).json()
        self.assertEqual(detail['assigned_store_codes'],['L128','L129'])
        self.assertEqual(len(admin.get('/api/admin/catalog').json()['planograms']),1)
        self.assertEqual(self.assignment(plan,[],version=preview.json()['version']).status_code,409)
        self.assertEqual(self.assignment(plan,[]).status_code,200)
        for _ in range(2):self.assertEqual(admin.get('/api/admin/catalog/planograms/'+plan['id']).json()['assigned_count'],0)
        self.assertEqual(self.db.get_point('point-a')['planogram_id'],None)

    def test_shared_plan_conflicts_require_confirmation_and_preserve_readings(self):
        first,_=self.shared_master('First');second,_=self.shared_master('Second')
        self.assertEqual(self.assignment(first,['L128','L129']).status_code,200)
        reading=self.db.add_reading('point-a',self.analysis,[],planogram_id=first['id'])
        original=self.db.get_reading(reading['id'])
        preview=self.assignment(second,['L128'],commit=False)
        self.assertEqual(len(preview.json()['conflicts']),1)
        self.assertEqual(self.assignment(second,['L128']).status_code,409)
        self.assertEqual(self.assignment(second,['L128'],replace=True).status_code,200)
        admin=self.client('admin')
        self.assertEqual(admin.get('/api/admin/catalog/planograms/'+first['id']).json()['assigned_store_codes'],['L129'])
        self.assertEqual(self.db.get_reading(reading['id']),original)

    def test_shared_plan_type_precedence_and_scope_permissions(self):
        import plan_assignments
        general,_=self.shared_master('General');specific,_=self.shared_master('Specific')
        shelf=self.create_type();admin=self.client('admin')
        admin.put('/api/admin/stores/L128/shelf-assignments/'+shelf['id'],json={'quantity':1,'version':0}).raise_for_status()
        self.assertEqual(self.assignment(general,['L128','L129']).status_code,200)
        self.assertEqual(self.assignment(specific,['L129'],shelf['id']).status_code,409)
        self.assertEqual(self.assignment(specific,['L128'],shelf['id']).status_code,200)
        with self.db.get_conn() as conn:
            values={'category':general['category'],'subcategories':general['subcategories']}
            self.assertEqual(plan_assignments.resolve(conn,'L128',values,shelf['id']),specific['id'])
            self.assertEqual(plan_assignments.resolve(conn,'L128',values,''),general['id'])
        path='/api/admin/catalog/planograms/'+general['id']+'/assignments'
        for role in ('replenisher','analyst','viewer',None):
            expected=401 if role is None else 403
            for method,url in (('get',path),('put',path),('post',path+'/preview')):
                self.assertEqual(getattr(self.client(role),method)(url).status_code,expected)
        query={'store':'L128','category':general['category'],'subcategories':general['subcategories'],'type_id':shelf['id']}
        response=self.client('replenisher').get('/api/capture/planograms',params=query)
        self.assertEqual([p['id'] for p in response.json()],[specific['id']])
        self.assertEqual(self.client('replenisher').get('/api/capture/planograms',params={**query,'store':'L130'}).status_code,403)

    def test_shared_plan_capture_freezes_reference_without_point_link(self):
        plan,body=self.shared_master();self.assignment(plan,['L129']).raise_for_status()
        client=self.client('replenisher')
        fields={'category':plan['category'],'subcategories':plan['subcategories'],'reference_plan_id':plan['id'],'linear_meters':'1.2'}
        response=client.post('/api/stores/L129/analysis-jobs',headers={'Idempotency-Key':'shared-capture-frozen-0001'},data=fields,files={'images':('photo.jpg',b'synthetic','image/jpeg')})
        self.assertEqual(response.status_code,202,response.text)
        job=self.db.get_job(response.json()['job_id']);before=job['payload']['plan_snapshot']
        self.assertEqual(before['id'],plan['id'])
        self.assertIsNone(self.db.get_point(job['point_id'])['planogram_id'])
        body['positionRows'][0]['faces']=5
        update=self.client('admin').patch('/api/admin/catalog/planograms/'+plan['id'],json={**body,'version':1})
        self.assertEqual(update.status_code,200,update.text)
        self.assertEqual(self.db.get_job(job['job_id'])['payload']['plan_snapshot'],before)
        self.assignment(plan,[]).raise_for_status()
        fields['reference_plan_id']=plan['id']
        stale=client.post('/api/stores/L129/analysis-jobs',headers={'Idempotency-Key':'shared-capture-stale-0001'},data=fields,files={'images':('photo.jpg',b'synthetic','image/jpeg')})
        self.assertEqual(stale.status_code,409,stale.text)

    def test_shared_plan_legacy_migration_is_once_only_and_preserves_type(self):
        product=self.create_product();shelf=self.create_type();admin=self.client('admin');admin.get('/api/admin/stores')
        admin.put('/api/admin/stores/L128/shelf-assignments/'+shelf['id'],json={'quantity':1,'version':0}).raise_for_status()
        plan=self.legacy_multi_plan(product,{'category':product['category'],'subcategories':[product['subcategory']]})
        point=next(p for p in self.client('replenisher').get('/api/summary').json()['points'] if p.get('infrastructure'))
        self.db.set_point_planogram(point['id'],plan['id'])
        # Force a pre-migration fixture, then lazily initialize from the physical link.
        with self.db.get_conn() as conn:
            conn.execute('DELETE FROM management_plan_scopes WHERE plan_id=?',(plan['id'],))
            conn.execute('DELETE FROM management_plan_scope_state WHERE plan_id=?',(plan['id'],))
        detail=admin.get('/api/admin/catalog/planograms/'+plan['id']+'/assignments').json()
        self.assertEqual([(a['store_code'],a['type_id']) for a in detail['assignments']],[('L128',shelf['id'])])
        self.assignment(plan,[],shelf['id']).raise_for_status()
        detail=admin.get('/api/admin/catalog/planograms/'+plan['id']+'/assignments').json()
        self.assertEqual(detail['assignments'],[])
        self.assertEqual(self.db.get_point(point['id'])['planogram_id'],plan['id'])

    def test_shared_plan_store_only_assignment_preserves_types_and_allows_untyped_pdv(self):
        plan,_=self.shared_master('PDV-only');admin=self.client('admin');first=self.create_type()
        response=admin.post('/api/admin/shelf-types',json={'name':'Another type','width_cm':100,'depths':[30]})
        self.assertEqual(response.status_code,201,response.text);second=response.json()
        for store,shelf in [('L128',first),('L129',second)]:
            admin.put('/api/admin/stores/'+store+'/shelf-assignments/'+shelf['id'],json={'quantity':1,'version':0}).raise_for_status()
            self.assignment(plan,[store],shelf['id']).raise_for_status()
        path='/api/admin/catalog/planograms/'+plan['id']+'/assignments'
        before=admin.get(path).json();body={'stores':['L128','L129','L130'],'version':before['version']}
        preview=admin.post(path+'/preview',json=body);self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(preview.json()['added'],['L130']);self.assertEqual(preview.json()['removed'],[])
        self.assertEqual(admin.get(path).json()['assignments'],before['assignments'])
        result=admin.put(path,json=body);self.assertEqual(result.status_code,200,result.text)
        after=admin.get(path).json()
        for row in before['assignments']:self.assertIn(row,after['assignments'])
        self.assertEqual({(r['store_code'],r['type_id']) for r in after['assignments']},{('L128',first['id']),('L129',second['id']),('L130','')})
        result=admin.put(path,json={'stores':['L129','L130'],'version':after['version']});self.assertEqual(result.status_code,200,result.text)
        detail=admin.get(path).json();self.assertEqual({r['store_code'] for r in detail['assignments']},{'L129','L130'})
        self.assertEqual(admin.put(path,json={'stores':[],'version':detail['version']}).status_code,200)
        self.assertEqual(admin.get(path).json()['assignments'],[])

    def test_shared_plan_store_only_assignment_keeps_conflict_confirmation_and_versions(self):
        first,_=self.shared_master('PDV-first');second,_=self.shared_master('PDV-second');admin=self.client('admin')
        self.assignment(first,['L128']).raise_for_status()
        path='/api/admin/catalog/planograms/'+second['id']+'/assignments';version=admin.get(path).json()['version']
        body={'stores':['L128','L129'],'version':version}
        preview=admin.post(path+'/preview',json=body);self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(len(preview.json()['conflicts']),1)
        self.assertEqual(admin.put(path,json=body).status_code,409)
        saved=admin.put(path,json={**body,'replace_conflicts':True});self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(admin.put(path,json={**body,'replace_conflicts':True}).status_code,409)
        self.assertEqual(admin.get('/api/admin/catalog/planograms/'+first['id']).json()['assigned_count'],0)
