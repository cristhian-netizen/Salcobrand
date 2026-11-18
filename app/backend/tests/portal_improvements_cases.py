import io
from datetime import datetime, timedelta, timezone
from openpyxl import Workbook, load_workbook


class PortalImprovementsCases:
    def test_admin_alerts_are_operational_and_thresholds_are_configurable(self):
        admin = self.client('admin')
        admin.get('/api/admin/stores')
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        with self.db.get_conn() as conn:
            conn.execute('UPDATE readings SET created_at=?', (old,))
            conn.execute('UPDATE management_stores SET created_at=?', (old,))
        result = admin.get('/api/alerts').json()
        self.assertEqual(result['mode'], 'administrative')
        self.assertEqual(result['parameters'], {'reviewDays':7,'noMeasurementDays':7})
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['rejected'], [])
        self.assertEqual({r['id'] for r in result['overdue_reviews']}, {self.own['id'],self.other['id'],self.foreign['id']})
        self.assertIn('L130', {s['store_id'] for s in result['unassigned_stores']})
        self.assertNotIn('L128', {s['store_id'] for s in result['unassigned_stores']})
        self.assertIn('L128', {s['store_id'] for s in result['inactive_stores']})
        self.assertEqual(self.configure('alerts', {'reviewDays':14,'noMeasurementDays':14}).status_code, 200)
        result = admin.get('/api/alerts').json()
        self.assertEqual(result['overdue_reviews'], [])
        self.assertEqual(result['inactive_stores'], [])
        self.assertEqual(self.configure('alerts', {'reviewDays':0,'noMeasurementDays':7}).status_code,400)
        self.assertEqual(self.configure('alerts', {'reviewDays':7,'noMeasurementDays':7},username='analyst').status_code,403)

    def test_inactive_pdv_recent_measurements_and_reviewed_readings_are_not_overdue(self):
        admin = self.client('admin')
        admin.get('/api/admin/stores')
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        with self.db.get_conn() as conn:
            conn.execute('UPDATE readings SET created_at=?', (old,))
            conn.execute('UPDATE management_stores SET created_at=?', (old,))
            conn.execute("UPDATE management_stores SET status='Inactivo' WHERE code='L130'")
            conn.execute('UPDATE readings SET created_at=? WHERE id=?', (self.db.now_iso(),self.own['id']))
        self.client('analyst').patch(f"/api/readings/{self.other['id']}/review",json={'status':'Rechazado','note':'Prueba','version':0})
        data = admin.get('/api/alerts').json()
        self.assertNotIn('L130',{r['store_id'] for r in data['inactive_stores']})
        self.assertNotIn('L128',{r['store_id'] for r in data['inactive_stores']})
        self.assertNotIn(self.other['id'],{r['id'] for r in data['overdue_reviews']})
        with self.db.get_conn() as conn:
            conn.execute("UPDATE users SET store_ids_json='[]' WHERE username IN ('analyst','legacy-supervisor')")
        row = next(r for r in admin.get('/api/alerts').json()['unassigned_stores'] if r['store_id']=='L128')
        self.assertIn('Analista', row['missing'])

    def test_measurement_geography_and_sorting_apply_before_pagination_and_export(self):
        admin = self.client('admin')
        admin.get('/api/admin/stores')
        with self.db.get_conn() as conn:
            conn.execute("UPDATE management_stores SET region='Maule',commune='Talca' WHERE code='L128'")
            conn.execute("UPDATE management_stores SET region='Tarapacá',commune='Iquique' WHERE code='L130'")
        for _ in range(52):
            self.db.add_reading('point-a',self.analysis,[],captured_by='replenisher')
        query={'region':'Maule','commune':'Talca','sort':'id','direction':'asc'}
        page=admin.get('/api/measurements',params=query).json()
        self.assertEqual(len(page['rows']),50)
        self.assertEqual(page['rows'][0]['id'],self.own['id'])
        self.assertEqual(page['count'],54)
        self.assertTrue(all(r['region']=='Maule' for r in page['rows']))
        self.assertTrue(all('region' in s and 'commune' in s for s in page['stores']))
        exported=admin.get('/api/reports/measurements.xlsx',params=query)
        book=load_workbook(io.BytesIO(exported.content))
        self.assertEqual(book.active.max_row,55)
        self.assertEqual(book.active.cell(2,1).value,self.own['id'])
        self.assertEqual(admin.get('/api/measurements?sort=unknown').status_code,400)
        self.assertEqual(self.client('replenisher').get('/api/measurements?region=Tarapacá').json()['rows'],[])

    def classification_file(self, catalog_rows=(), assignments=()):
        from classification_transfer import HEADERS
        book=Workbook();book.remove(book.active)
        for name, rows in [('Catalogo',catalog_rows),('Asignaciones',assignments)]:
            sheet=book.create_sheet(name);sheet.append(HEADERS[name])
            for row in rows:sheet.append(row)
        output=io.BytesIO();book.save(output);return output.getvalue()

    def test_classification_import_previews_and_atomically_assigns_existing_sku(self):
        product=self.create_product()
        admin=self.client('admin')
        content=self.classification_file([['Marca QA','Salud','Sexual','No','No']], [['000123','Salud','Sexual','Marca QA']])
        path='/api/admin/settings/classification/import'
        preview=admin.post(path,files={'file':('test.xlsx',content)}).json()
        self.assertFalse(preview['has_errors'],preview)
        self.assertEqual(preview['products_updated'],1)
        self.assertNotIn('Salud',self.configuration()['state']['catalog']['categories'])
        committed=admin.post(path,files={'file':('test.xlsx',content)},data={'commit':'true','version':preview['version']})
        self.assertEqual(committed.status_code,200,committed.text)
        updated=next(p for p in admin.get('/api/admin/catalog').json()['products'] if p['id']==product['id'])
        for key in ('sku','name','price','height','width','thickness','quantity'):
            self.assertEqual(updated[key],product[key])
        self.assertEqual((updated['category'],updated['subcategory']),('Salud','Sexual'))
        self.assertEqual(admin.post(path,files={'file':('test.xlsx',content)},data={'commit':'true','version':preview['version']}).status_code,409)
        self.assertEqual(self.db.get_reading(self.own['id'])['total_facings'],2)

    def test_classification_rejects_unknown_sku_formulas_and_stale_manual_changes(self):
        self.create_product()
        admin=self.client('admin');path='/api/admin/settings/classification'
        before=self.configuration()
        content=self.classification_file([['Marca QA','Salud','Sexual','No','No']], [['UNKNOWN','Salud','Sexual','Marca QA']])
        preview=admin.post(path+'/import',files={'file':('test.xlsx',content)}).json()
        self.assertTrue(preview['has_errors'])
        self.assertEqual(admin.post(path+'/import',files={'file':('test.xlsx',content)},data={'commit':'true','version':preview['version']}).status_code,400)
        self.assertEqual(before['version'],self.configuration()['version'])
        options=admin.get(path).json()
        body={'version':options['version'],'assignments':[{'sku':'000123','category':'Cuidado personal','subcategory':'Desodorantes','subBrand':'Marca QA'}]}
        self.assertEqual(admin.post(path+'/assign',json=body).status_code,200)
        self.assertEqual(admin.post(path+'/assign',json=body).status_code,409)
        for role in ('analyst','viewer','replenisher'):
            self.assertEqual(self.client(role).get(path).status_code,403)
            self.assertEqual(self.client(role).post(path+'/import',files={'file':('test.xlsx',content)}).status_code,403)
        malicious=self.classification_file([['=1+1','Salud','Sexual','No','No']])
        self.assertEqual(admin.post(path+'/import',files={'file':('test.xlsx',malicious)}).status_code,400)

    def test_pdv_filtered_excel_keeps_only_matching_relationships(self):
        admin=self.client('admin');admin.get('/api/admin/stores')
        with self.db.get_conn() as conn:
            conn.execute("UPDATE management_stores SET region='Maule',commune='Talca' WHERE code='L128'")
        exported=admin.get('/api/admin/store-transfer/workbook.xlsx?region=Maule&commune=Talca')
        self.assertEqual(exported.status_code,200)
        book=load_workbook(io.BytesIO(exported.content))
        self.assertEqual([row[0] for row in book['PDV'].iter_rows(min_row=2,values_only=True)],['L128'])
        self.assertTrue(all(row[0]=='L128' for row in book['Gondolas'].iter_rows(min_row=2,values_only=True)))
