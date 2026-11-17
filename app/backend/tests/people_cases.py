"""Person/account atomicity, real session permissions and legacy Excel compatibility."""
import base64
from datetime import datetime
import io
import time
from openpyxl import Workbook, load_workbook


class PeopleCases:
    def test_assigning_all_current_stores_keeps_an_explicit_analyst_scope(self):
        self.client('admin').get('/api/admin/stores')
        person = {**self.person_payload('current-stores-analyst'), 'allStores': True, 'storeCodes': []}
        response = self.client('admin').post('/api/admin/people', json={
            'person': person, 'enable_access': True, 'password': 'Assigned-current-stores-2026!'})
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertFalse(result['allStores'])
        self.assertEqual(set(result['storeCodes']), {'L128','L129','L130'})
        created = self.client('admin').post('/api/admin/stores', json=self.store_payload('L131'))
        self.assertEqual(created.status_code, 201, created.text)
        self.assertNotIn('L131', {store['code'] for store in self.client('current-stores-analyst').get('/api/stores').json()})

    def person_payload(self, username='qa-person', role='analyst'):
        return dict(names='María', paternal='Prueba', maternal='QA', email=username+'@example.test', username=username,
                    position='Analista de prueba', startDate='2026-01-02', endDate='', status='Vigente', role=role,
                    storeCodes=['L128'] if role in ('analyst','replenisher') else [], allStores=False)

    def create_person(self, username='qa-person', role='analyst', access=True):
        payload={'person':self.person_payload(username,role), 'enable_access':access}
        if access:
            payload['password']='Isolated-person-password-2026!'
        response=self.client('admin').post('/api/admin/people',json=payload)
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def update_person(self, current, **changes):
        fields=self.person_payload(current['username'],current['role']).keys()
        data={key:current.get(key,'') for key in fields}
        response=self.client('admin').patch('/api/admin/people/'+current['id'],json={
            'person':{**data,**changes},'version':current['version']})
        return response

    def test_people_permissions_and_legacy_accounts_without_fabricated_fields(self):
        for role in (None,'analyst','replenisher','viewer'):
            client=self.client(role)
            expected=401 if role is None else 403
            for path in ('','/template.xlsx'):
                self.assertEqual(client.get('/api/admin/people'+path).status_code,expected)
            self.assertEqual(client.post('/api/admin/people',json={'person':self.person_payload()}).status_code,expected)
            self.assertEqual(client.delete('/api/admin/people/missing?version=1').status_code,expected)
        rows=self.client('admin').get('/api/admin/people').json()
        analyst=next(row for row in rows if row['username']=='analyst')
        self.assertTrue(analyst['needs_completion'])
        self.assertNotIn('names',analyst)
        self.assertNotIn('startDate',analyst)
        self.assertEqual(analyst['storeCodes'],['L128','L129'])
        self.assertTrue(all('password_hash' not in row and 'salt' not in row for row in rows))

    def test_people_suspension_is_read_only_and_baja_blocks_login(self):
        person=self.create_person()
        client=self.client(None)
        login=lambda:client.post('/api/auth/login',json={'username':person['username'],'password':'Isolated-person-password-2026!'})
        self.assertEqual(login().status_code,200)
        self.assertEqual(client.get('/api/points/point-a').status_code,200)
        self.assertEqual(client.get('/api/points/point-c').status_code,403)
        changed=self.update_person(person,status='Suspendido',storeCodes=['L130'])
        self.assertEqual(changed.status_code,200,changed.text)
        person=changed.json()
        self.assertEqual(person['storeCodes'],['L128'])
        self.assertEqual(client.get('/api/auth/me').status_code,401)
        self.assertEqual(login().status_code,200)
        session_data = client.get('/api/auth/me').json()
        self.assertTrue(session_data['read_only'])
        self.assertNotIn('scan', session_data['permissions'])
        self.assertEqual(client.get('/api/points/point-a').status_code,200)
        self.assertEqual(client.post('/api/points/point-a/analyze',files={'images':('x.jpg',b'test','image/jpeg')}).status_code,403)
        self.assertEqual(client.post('/api/auth/change-password',json={'current_password':'Isolated-person-password-2026!','new_password':'Updated-password-2026!'}).status_code,403)
        changed=self.update_person(person,status='Vigente')
        self.assertEqual(changed.status_code,200,changed.text)
        person=changed.json()
        self.assertEqual(client.get('/api/auth/me').status_code,401)
        self.assertEqual(login().status_code,200)
        self.assertFalse(client.get('/api/auth/me').json()['read_only'])
        self.assertEqual(self.update_person(person,status='De baja').status_code,400)
        changed=self.update_person(person,status='De baja',endDate='2026-11-12')
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(login().status_code,403)

    def test_people_drafts_enable_access_duplicates_and_atomic_validation(self):
        person=self.create_person(access=False)
        self.assertFalse(person['access_enabled'])
        self.assertIsNone(self.db.get_user('qa-person'))
        current=self.person_payload()
        admin=self.client('admin')
        path='/api/admin/people/'+person['id']
        response=admin.patch(path,json={'person':current,'version':person['version'],'enable_access':True,'password':'short'})
        self.assertEqual(response.status_code,400)
        self.assertIsNone(self.db.get_user('qa-person'))
        response=admin.patch(path,json={'person':current,'version':person['version'],'enable_access':True,'password':'Isolated-person-password-2026!'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['access_enabled'])
        self.assertEqual(self.update_person(person,names='Stale').status_code,409)
        duplicate={**self.person_payload('other-person'),'email':current['email'].upper()}
        self.assertEqual(admin.post('/api/admin/people',json={'person':duplicate,'enable_access':True,'password':'Isolated-person-password-2026!'}).status_code,409)
        self.assertIsNone(self.db.get_user('other-person'))
        person=response.json()
        self.assertEqual(self.update_person(person,username='renamed').status_code,400)
        self.assertEqual(self.update_person(person,startDate='2026-02-30').status_code,400)
        self.assertEqual(self.update_person(person,storeCodes=['UNKNOWN']).status_code,400)

    def test_people_password_reset_delete_recreate_and_self_protection(self):
        person=self.create_person()
        session=self.client('qa-person')
        self.assertEqual(session.get('/api/auth/me').status_code,200)
        self.db.add_reading('point-a',self.analysis,[],captured_by='qa-person')
        admin=self.client('admin')
        body={'version':person['version'],'password':'New-person-password-2026!','confirmation':'different'}
        path='/api/admin/people/'+person['id']+'/password'
        self.assertEqual(admin.post(path,json=body).status_code,400)
        body['confirmation']=body['password']
        self.assertEqual(admin.post(path,json=body).status_code,200)
        self.assertEqual(session.get('/api/auth/me').status_code,401)
        person=next(row for row in admin.get('/api/admin/people').json() if row['username']=='qa-person')
        current_session=self.client('qa-person')
        self.assertEqual(admin.delete('/api/admin/people/'+person['id']+'?version='+str(person['version'])).status_code,200)
        with self.db.get_conn() as conn:
            self.assertIsNotNone(conn.execute("SELECT id FROM readings WHERE captured_by='qa-person'").fetchone())
        self.create_person()
        self.assertEqual(current_session.get('/api/auth/me').status_code,401)
        own=next(row for row in admin.get('/api/admin/people').json() if row['username']=='admin')
        person_data=self.person_payload('admin','admin')
        self.assertEqual(admin.patch('/api/admin/people/'+own['id'],json={'person':{**person_data,'status':'Suspendido'},'version':own['version']}).status_code,403)
        self.assertEqual(admin.delete('/api/admin/people/'+own['id']+'?version='+str(own['version'])).status_code,403)

    def test_people_legacy_account_edits_invalidate_stale_person_and_sessions(self):
        person=self.create_person()
        client=self.client('qa-person')
        admin=self.client('admin')
        response=admin.patch('/api/admin/users/qa-person',json={'role':'viewer'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(client.get('/api/auth/me').status_code,401)
        updated=next(row for row in admin.get('/api/admin/people').json() if row['username']=='qa-person')
        self.assertEqual(updated['role'],'viewer')
        self.assertEqual(updated['storeCodes'],[])
        self.assertEqual(self.update_person(person,names='Stale').status_code,409)
        self.assertEqual(admin.delete('/api/admin/users/qa-person').status_code,200)
        self.assertNotIn('qa-person',{row['username'] for row in admin.get('/api/admin/people').json()})

    def test_people_legacy_session_upgrade_and_password_revocation(self):
        with self.db.get_conn() as conn:
            conn.execute("UPDATE users SET auth_version=0 WHERE username='viewer'")
        payload='viewer:'+str(int(time.time())+3600)
        token=base64.urlsafe_b64encode((payload+':'+self.auth._sign(payload)).encode()).decode()
        self.assertEqual(self.auth.verify_session_token(token),'viewer')
        hashed,salt=self.auth.hash_password('Changed-password-2026!')
        self.db.update_user_password('viewer',hashed,salt)
        self.assertIsNone(self.auth.verify_session_token(token))
        modern=self.auth.create_session_token('viewer')
        self.assertEqual(self.auth.verify_session_token(modern),'viewer')
        self.assertIsNone(self.auth.verify_session_token('invalid'))

    def test_people_own_password_change_renews_current_session_and_revokes_others(self):
        current = self.client('viewer')
        other = self.client('viewer')
        response = current.post('/api/auth/change-password',json={
            'current_password':'Isolated-local-password-2026!', 'new_password':'Changed-own-password-2026!'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(current.get('/api/auth/me').status_code,200)
        self.assertEqual(other.get('/api/auth/me').status_code,401)

    def people_excel_file(self,rows):
        from people_excel import COLUMNS,FIELDS
        book=Workbook();sheet=book.active;sheet.title='Personas';sheet.append(COLUMNS)
        for row in rows:
            sheet.append([row.get(key,'') for key in FIELDS])
        output=io.BytesIO();book.save(output)
        return output.getvalue()

    def people_import(self,content,commit=False,version=None):
        data={'commit':str(commit).lower()}
        if version:data['version']=version
        return self.client('admin').post('/api/admin/people/import',data=data,files={'file':('Personas.xlsx',content)})

    def test_people_excel_preserves_columns_dates_preview_and_draft_access(self):
        from people_excel import COLUMNS
        response=self.client('admin').get('/api/admin/people/template.xlsx')
        book=load_workbook(io.BytesIO(response.content))
        self.assertEqual(book.sheetnames,['Personas'])
        self.assertEqual([cell.value for cell in book['Personas'][1]],COLUMNS)
        book.close()
        payload={**self.person_payload('excel-person'),'role':'Analista','startDate':datetime(2026,1,2),'storeCode':'L128'}
        content=self.people_excel_file([payload])
        preview=self.people_import(content)
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(preview.json()['errors'],[])
        self.assertEqual(preview.json()['sample'][0]['startDate'],'2026-01-02')
        self.assertIsNone(self.db.get_user('excel-person'))
        result=self.people_import(content,True,preview.json()['version'])
        self.assertEqual(result.status_code,200,result.text)
        self.assertIsNone(self.db.get_user('excel-person'))
        self.assertFalse(next(row for row in self.client('admin').get('/api/admin/people').json() if row['username']=='excel-person')['access_enabled'])
        self.assertEqual(self.people_import(content,True,preview.json()['version']).status_code,409)

    def test_people_excel_is_atomic_and_protects_linked_permissions(self):
        person=self.create_person()
        invalid={**self.person_payload('invalid-person'),'role':'Analista','storeCode':'NO-PDV'}
        valid={**self.person_payload('excel-person'),'role':'Analista','storeCode':'L128'}
        content=self.people_excel_file([valid,invalid])
        preview=self.people_import(content).json()
        self.assertTrue(preview['errors'])
        self.assertEqual(self.people_import(content,True,preview['version']).status_code,400)
        self.assertNotIn('excel-person',{row['username'] for row in self.client('admin').get('/api/admin/people').json()})
        changed={**self.person_payload(),'role':'Superusuario','storeCode':''}
        self.assertTrue(self.people_import(self.people_excel_file([changed])).json()['errors'])
        for row in [{**valid,'names':'=1+1'}, {**valid,'username':123}, {**valid,'email':'bad'}]:
            self.assertTrue(self.people_import(self.people_excel_file([row])).json()['errors'])
        duplicate=self.people_import(self.people_excel_file([valid,{**valid,'username':'EXCEL-PERSON'}])).json()
        self.assertTrue(duplicate['errors'])
