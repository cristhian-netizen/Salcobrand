"""Email aliases, minimal records, password rules and account-scope regressions."""
import io
from openpyxl import Workbook


class EmailAccessCases:
    def minimal_person(self,username='email-person',role='analyst'):
        return {'username':username,'email':username+'@example.test','role':role,'status':'Vigente'}

    def email_person(self,username='email-person',role='analyst',enable=True):
        response=self.client('admin').post('/api/admin/people',json={'person':self.minimal_person(username,role),'enable_access':enable,**({'password':'Admin123'} if enable else {})})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def login_identity(self,client,identifier,password='Admin123',selector=None):
        return client.post('/api/auth/login',json={'username':identifier,'password':password},headers={'X-Portal-Session':selector} if selector else {})

    def test_email_access_minimal_records_empty_scope_and_canonical_tab_sessions(self):
        person=self.email_person();self.assertFalse(person['needs_completion']);self.assertEqual(person['startDate'],'')
        self.assertEqual(person['name'],person['username']);self.assertEqual(person['storeCodes'],[])
        client=self.client(None)
        for selector,identifier in [('a'*32,'EMAIL-PERSON'),('b'*32,' EMAIL-PERSON@EXAMPLE.TEST ')]:
            response=self.login_identity(client,identifier,selector=selector);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['username'],'email-person')
            headers={'X-Portal-Session':selector};self.assertEqual(client.get('/api/auth/me',headers=headers).json()['username'],'email-person')
            self.assertEqual(client.get('/api/stores',headers=headers).json(),[])
            self.assertEqual(client.get('/api/points/point-a',headers=headers).status_code,403)
        self.assertEqual(client.post('/api/auth/logout',headers={'X-Portal-Session':'a'*32}).status_code,200)
        self.assertEqual(client.get('/api/auth/me',headers={'X-Portal-Session':'b'*32}).status_code,200)

    def test_email_access_draft_has_only_four_required_fields_and_never_logs_in(self):
        person=self.email_person(enable=False)
        self.assertFalse(person['access_enabled'])
        for identifier in (person['username'],person['email']):self.assertEqual(self.login_identity(self.client(None),identifier).status_code,401)
        for field in ('username','email','role','status'):
            body=self.minimal_person('missing-'+field);body.pop(field)
            self.assertEqual(self.client('admin').post('/api/admin/people',json={'person':body}).status_code,422)
        # Legacy credentials keep working: the new rules are for new/changed passwords.
        hashed,salt=self.auth.hash_password('admin');self.db.update_user_password('viewer',hashed,salt)
        self.assertEqual(self.login_identity(self.client(None),'viewer','admin').status_code,200)

    def test_email_access_password_policy_covers_create_reset_change_and_legacy_routes(self):
        admin=self.client('admin');base=self.minimal_person()
        for password in ('Admin12','abcdefgh1','ABCDEFGH','12345678','a'*513+'A1'):
            r=admin.post('/api/admin/people',json={'person':base,'enable_access':True,'password':password})
            self.assertEqual(r.status_code,400,r.text);self.assertIsNone(self.db.get_user(base['username']))
        self.assertEqual(self.console_operator().post('/api/internal/training/accounts',json={'username':'training-weak','password':'weakpass1'}).status_code,400)
        person=self.email_person();path='/api/admin/people/'+person['id']+'/password'
        for password in ('abcdefgh1','ABCDEFGH','Admin12'):
            self.assertEqual(admin.post(path,json={'version':person['version'],'password':password,'confirmation':password}).status_code,400)
            client=self.client('email-person')
            self.assertEqual(client.post('/api/auth/change-password',json={'current_password':'Admin123','new_password':password}).status_code,400)
        self.assertEqual(admin.post('/api/admin/users',json={'username':'legacy-weak','password':'weakpass1','role':'viewer'}).status_code,400)
        self.assertEqual(admin.patch('/api/admin/users/viewer',json={'password':'weakpass1'}).status_code,400)
        self.assertEqual(self.client(None).post('/api/auth/register',json={'username':'weak-invite','password':'weakpass1','code':'isolated-test-invite'}).status_code,400)
        client=self.client('email-person')
        self.assertEqual(client.post('/api/auth/change-password',json={'current_password':'Admin123','new_password':'Nueva123'}).status_code,200)
        self.assertEqual(self.login_identity(self.client(None),person['email'],'Nueva123').status_code,200)

    def test_email_access_changes_alias_and_respects_suspended_and_disabled_accounts(self):
        person=self.email_person(role='viewer');admin=self.client('admin');client=self.client(None);original=person['email']
        def change(**updates):
            nonlocal person
            fields={key:person[key] for key in ('username','email','role','status')}
            r=admin.patch('/api/admin/people/'+person['id'],json={'person':{**fields,**updates},'version':person['version']})
            self.assertEqual(r.status_code,200,r.text);person=r.json()
        change(email='changed@example.test')
        self.assertEqual(self.login_identity(client,original).status_code,401)
        self.assertEqual(self.login_identity(client,person['email']).status_code,200)
        change(status='Suspendido')
        self.assertEqual(self.login_identity(client,person['email']).status_code,200)
        self.assertTrue(client.get('/api/auth/me').json()['read_only'])
        change(status='De baja')  # End date is optional too.
        for identifier in (person['username'],person['email']):self.assertEqual(self.login_identity(client,identifier).status_code,403)

    def test_email_access_rejects_cross_namespace_collisions_and_old_ambiguity(self):
        person=self.email_person(role='viewer');admin=self.client('admin')
        for body in ({**self.minimal_person('other'),'username':person['email'].upper()},
                     {**self.minimal_person('other'),'email':person['email'].upper()},
                     {**self.minimal_person('other'),'email':'VIEWER'},
                     {**self.minimal_person('viewer@example.test'),'email':'unrelated@example.test'}):
            # An invalid email is rejected separately, while valid collisions are conflicts.
            expected=400 if body['email']=='VIEWER' else 409 if body['username']!='viewer@example.test' else 201
            r=admin.post('/api/admin/people',json={'person':body});self.assertEqual(r.status_code,expected,r.text)
        alias_collision={**self.minimal_person('collision'),'email':'viewer@example.test'}
        self.assertEqual(admin.post('/api/admin/people',json={'person':alias_collision}).status_code,409)
        self.assertEqual(admin.post('/api/admin/users',json={'username':person['email'],'password':'Admin123','role':'viewer'}).status_code,409)
        # Simulate an old duplicate alias with a direct fixture insert; login must fail closed.
        account=self.db.get_user('viewer')
        with self.db.get_conn() as conn:
            conn.execute('INSERT INTO users(username,password_hash,salt,created_at,role) VALUES(?,?,?,?,?)',(person['email'],account['password_hash'],account['salt'],self.db.now_iso(),'viewer'))
        self.assertEqual(self.login_identity(self.client(None),person['email']).status_code,401)

    def test_email_access_excel_accepts_four_columns_preserves_optional_fields_and_previews_conflicts(self):
        def book(rows):
            out=io.BytesIO();wb=Workbook();sheet=wb.active;sheet.title='Personas';sheet.append(['Nombre de usuario','Email','Rol','Estado'])
            for row in rows:sheet.append(row)
            wb.save(out);return out.getvalue()
        person=self.create_person()
        content=book([[person['username'],'new-alias@example.test','Analista','Vigente'],['minimal-import','minimal@example.test','Reponedor','Vigente']])
        preview=self.people_import(content);self.assertEqual(preview.status_code,200,preview.text);self.assertEqual(preview.json()['errors'],[])
        result=self.people_import(content,True,preview.json()['version']);self.assertEqual(result.status_code,200,result.text)
        updated=next(p for p in self.client('admin').get('/api/admin/people').json() if p['username']==person['username'])
        self.assertEqual(updated['names'],person['names']);self.assertEqual(updated['storeCodes'],person['storeCodes']);self.assertEqual(updated['startDate'],person['startDate'])
        self.assertIsNone(self.db.get_user('minimal-import'))
        collision=book([['alias-one','alias-two@example.test','Analista','Vigente'],['alias-two@example.test','other@example.test','Analista','Vigente']])
        self.assertTrue(self.people_import(collision).json()['errors'])
