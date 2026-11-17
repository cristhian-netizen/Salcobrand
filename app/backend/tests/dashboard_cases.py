from copy import deepcopy
import csv
import io
import json


class DashboardCases:
    def test_dashboard_category_scope_applies_to_indicators_history_and_csv(self):
        import measurement_reports
        self.client('admin').get('/api/admin/stores')
        selected = {'category':'Salud sexual','subcategory':'Preservativos'}
        with self.db.get_conn() as conn:
            conn.execute('UPDATE readings SET capture_context_json=? WHERE id=?', (json.dumps(selected), self.own['id']))
            conn.execute('UPDATE readings SET capture_context_json=? WHERE id=?',
                         (json.dumps({'category':'Cuidado personal','subcategory':'Desodorantes'}), self.other['id']))
        measurement_reports.save_review(self.own['id'], 'Aprobado', '', 0, 'analyst')
        measurement_reports.save_review(self.other['id'], 'Aprobado', '', 0, 'analyst')
        viewer = self.client('viewer')
        result = viewer.get('/api/dashboard?category=Salud%20sexual&subcategory=Preservativos').json()
        self.assertEqual(result['totals']['measurements'], 1)
        self.assertEqual(result['totals']['approved'], 1)
        self.assertEqual([row['id'] for row in result['recent']], [self.own['id']])
        exported = viewer.get('/api/dashboard/export/measurements.csv?category=Salud%20sexual&subcategory=Preservativos')
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(len(list(csv.reader(io.StringIO(exported.content.decode('utf-8-sig')), delimiter=';'))), 2)
        self.assertEqual(viewer.get('/api/dashboard?subcategory=Preservativos').status_code, 400)
        self.assertEqual(self.client('replenisher').get('/api/dashboard?category=Salud%20sexual').status_code, 403)
        self.assertEqual(self.client('analyst').get('/api/dashboard?store=L130').status_code, 403)

    def dashboard_fixture(self):
        payload, first, second = self.detail_fixture()
        payload['details'].append({**payload['details'][0], 'productId': second['id'], 'position': '2',
                                   'ownership': 'Competencia', 'present': False, 'faces': 0, 'match': 'No'})
        analyst = self.client('analyst')
        response = analyst.patch(f"/api/readings/{self.other['id']}/product-details", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        analyst.patch(f"/api/readings/{self.other['id']}/review", json={'status': 'Aprobado', 'note': '', 'version': 1})
        with self.db.get_conn() as conn:
            conn.execute("UPDATE readings SET created_at = '2026-11-10T15:35:00+00:00'")
            conn.execute("UPDATE management_stores SET region='Región Uno', commune='Comuna A' WHERE code IN ('L128','L129')")
            conn.execute("UPDATE management_stores SET region='Región Dos', commune='Comuna B' WHERE code='L130'")
            conn.execute("UPDATE management_stores SET status='Inactivo' WHERE code='L129'")
            conn.execute("INSERT INTO management_stores (code,name,region,commune,status,created_at,updated_at) VALUES ('NEW','PDV sin capturas','Región Uno','Comuna A','Activo',?,?)", (self.db.now_iso(), self.db.now_iso()))
        return payload, first, second

    def test_dashboard_permissions_scope_and_geographic_filters(self):
        self.dashboard_fixture()
        self.assertEqual(self.client(None).get('/api/dashboard').status_code, 401)
        for path in ('/api/dashboard', '/api/dashboard/export/operation.csv'):
            self.assertEqual(self.client('replenisher').get(path).status_code, 403)
        for role in ('admin', 'analyst', 'viewer'):
            response = self.client(role).get('/api/dashboard?to=2026-11-12')
            self.assertEqual(response.status_code, 200, response.text)
        analyst = self.client('analyst')
        self.assertEqual({item['code'] for item in analyst.get('/api/dashboard?to=2026-11-12').json()['options']}, {'L128', 'L129'})
        self.assertEqual(analyst.get('/api/dashboard?store=L130').status_code, 403)
        self.assertEqual(analyst.get('/api/dashboard/export/operation.csv?store=L130').status_code, 403)
        filtered = self.client('viewer').get('/api/dashboard?region=Región Uno&commune=Comuna A&to=2026-11-12').json()
        self.assertEqual(filtered['totals']['measurements'], 2)
        self.assertNotIn('L130', {item['code'] for item in filtered['locations']})

    def test_dashboard_coverage_includes_unmeasured_active_pdv_and_historical_cutoff(self):
        self.dashboard_fixture()
        result = self.client('viewer').get('/api/dashboard?region=Región Uno&to=2026-11-12').json()
        self.assertEqual(result['operation']['total'], 2)
        self.assertEqual(result['operation']['indicator']['value'], 50)
        self.assertEqual(result['operation']['unmeasured'], 1)
        self.assertEqual(result['operation']['count'], 1)
        later = self.client('viewer').get('/api/dashboard?region=Región Uno&from=2026-11-11&to=2026-11-12').json()
        self.assertEqual(later['operation']['indicator']['value'], 0)
        store = next(item for item in later['operation']['rows'] if item['code'] == 'L128')
        self.assertEqual((store['last'], store['age'], store['gap']), ('2026-11-10', 2, None))
        self.assertIsNone(later['totals']['average_score'])

    def test_dashboard_weighted_confirmation_metrics_and_latest_recent_absence(self):
        payload, first, second = self.dashboard_fixture()
        reading = self.db.add_reading('point-a', self.analysis, ['point-a/new.jpg'], captured_by='analyst',
                                      planogram_id=self.db.get_reading(self.other['id'])['planogram_id'])
        with self.db.get_conn() as conn:
            conn.execute("UPDATE readings SET created_at='2026-11-11T15:35:00+00:00' WHERE id=?", (reading['id'],))
        new = deepcopy(payload)
        new['details'][0].update(present=False, faces=0, match='No')
        new['details'][1].update(present=True, faces=9, match='N/A')
        analyst = self.client('analyst')
        response = analyst.patch(f"/api/readings/{reading['id']}/product-details", json=new)
        self.assertEqual(response.status_code, 200, response.text)
        analyst.patch(f"/api/readings/{reading['id']}/review", json={'status': 'Aprobado', 'note': '', 'version': 1})
        result = self.client('viewer').get('/api/dashboard?store=L128&to=2026-11-12').json()
        self.assertEqual({key: result['vision']['indicators'][key]['value'] for key in ('osa','sos','cp','oos')},
                         {'osa': 50, 'sos': 25, 'cp': 33.3, 'oos': 1})
        self.assertEqual(result['vision']['missing'][0]['product'], first['name'])
        stale = self.client('viewer').get('/api/dashboard?store=L128&to=2026-12-12').json()
        self.assertIsNone(stale['vision']['indicators']['oos']['value'])
        # A newer approved capture without confirmations supersedes older manual absence evidence.
        latest = self.db.add_reading('point-a', self.analysis, ['point-a/latest.jpg'], captured_by='analyst')
        with self.db.get_conn() as conn:
            conn.execute("UPDATE readings SET created_at='2026-11-12T15:35:00+00:00' WHERE id=?", (latest['id'],))
        analyst.patch(f"/api/readings/{latest['id']}/review", json={'status': 'Aprobado', 'note': '', 'version': 0})
        self.assertIsNone(self.client('viewer').get('/api/dashboard?store=L128&to=2026-11-12').json()['vision']['indicators']['oos']['value'])

    def test_dashboard_rejected_and_pending_measurements_excluded_from_performance(self):
        self.dashboard_fixture()
        analyst = self.client('analyst')
        analyst.patch(f"/api/readings/{self.own['id']}/review", json={'status': 'Rechazado', 'note': 'Repetir', 'version': 0})
        result = self.client('viewer').get('/api/dashboard?to=2026-11-12').json()
        self.assertEqual((result['totals']['measurements'], result['totals']['approved'], result['totals']['rejected'], result['totals']['in_review']), (3,1,1,1))
        self.assertEqual(result['vision']['compared'], 2)
        self.assertEqual(result['totals']['average_score'], self.other['standards']['overall_score'])
        analyst.patch(f"/api/readings/{self.other['id']}/review", json={'status': 'Rechazado', 'note': 'Descartar', 'version': 2})
        result = self.client('viewer').get('/api/dashboard?to=2026-11-12').json()
        self.assertIsNone(result['totals']['average_score'])
        self.assertIsNone(result['vision']['indicators']['osa']['value'])
        self.assertEqual(result['operation']['count'], 0)

    def test_dashboard_month_gaps_calendar_leap_days_and_validation(self):
        self.dashboard_fixture()
        with self.db.get_conn() as conn:
            conn.execute("UPDATE readings SET created_at='2024-01-31T15:35:00+00:00'")
        result = self.client('viewer').get('/api/dashboard?from=2024-01-01&to=2024-03-31').json()
        self.assertEqual([item['month'] for item in result['months']], ['2024-01','2024-02','2024-03'])
        feb = result['months'][1]
        self.assertEqual(feb['count'], 0)
        self.assertIsNone(feb['score'])
        self.assertIsNone(feb['rejectionRate'])
        calendar = next(item for item in result['calendar'] if item['month']=='2024-02')
        self.assertEqual(calendar['days'][28:], [0,None,None])
        self.assertEqual(self.client('viewer').get('/api/dashboard?from=2024-03-01&to=2024-01-01').status_code, 400)
        self.assertEqual(self.client('viewer').get('/api/dashboard?from=2024-02-30').status_code, 400)
        self.assertEqual(self.client('viewer').get('/api/dashboard?commune=Comuna A').status_code, 400)

    def test_dashboard_csv_exports_use_filters_and_neutralize_formulas(self):
        self.dashboard_fixture()
        with self.db.get_conn() as conn:
            conn.execute("UPDATE management_stores SET name='=SUM(A1)' WHERE code='L128'")
        client = self.client('viewer')
        response = client.get('/api/dashboard/export/operation.csv?store=L128&to=2026-11-12')
        self.assertEqual(response.status_code, 200, response.text)
        rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig')), delimiter=';'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0:2], ['L128', "'=SUM(A1)"])
        self.assertEqual(rows[1][4], '1')
        for kind in ('locations','rejections','measurements'):
            self.assertEqual(client.get(f'/api/dashboard/export/{kind}.csv?store=L128&to=2026-11-12').status_code, 200)
        self.assertEqual(client.get('/api/dashboard/export/unknown.csv').status_code, 404)

    def test_dashboard_brand_share_and_frequency_use_approved_observations(self):
        self.dashboard_fixture()
        import settings_service
        config = settings_service.read()
        catalog = config['state']['catalog']
        settings_service.save('catalog', {**catalog, 'brands':catalog['brands'] + ['Marca propia','Competidor'],
                                         'ownBrands':['Marca propia']}, config['version'], 'admin')
        with self.db.get_conn() as conn:
            conn.execute('UPDATE readings SET products_json=? WHERE id=?', (json.dumps([
                {'brand':'Marca propia','facings':3}, {'brand':'Competidor','facings':1}, {'facings':2}]), self.other['id']))
        result = self.client('viewer').get('/api/dashboard?store=L128&to=2026-11-12').json()
        self.assertEqual(result['brands']['totalFacings'], 6)
        self.assertEqual([item['sharePct'] for item in result['brands']['groups']], [50,16.7,33.3])
        self.assertEqual(result['operation']['rows'][0]['days'], 1)
        with self.db.get_conn() as conn:
            conn.execute('UPDATE readings SET capture_context_json=? WHERE id=?',
                         (json.dumps({'brandShare': {'brands': [{'brand':'Marca histórica', 'classification':'client', 'facings':4}]}}), self.other['id']))
        captured = self.client('viewer').get('/api/dashboard?store=L128&to=2026-11-12').json()['brands']
        self.assertEqual(captured['brands'][0]['brand'], 'Marca histórica')
        self.assertEqual(captured['groups'][0]['sharePct'], 100)

    def test_dashboard_threshold_colors_use_unrounded_confirmed_values(self):
        payload, _, _ = self.dashboard_fixture()
        payload.update(version=1, reviewVersion=2)
        payload['details'][0]['faces'] = 2996
        payload['details'][1].update(present=True, faces=7004)
        analyst = self.client('analyst')
        analyst.patch(f"/api/readings/{self.other['id']}/product-details", json=payload).raise_for_status()
        analyst.patch(f"/api/readings/{self.other['id']}/review", json={'status':'Aprobado','note':'','version':3}).raise_for_status()
        result = self.client('viewer').get('/api/dashboard?store=L128&to=2026-11-12').json()
        self.assertEqual(result['vision']['indicators']['sos']['value'], 30)
        self.assertEqual(result['vision']['indicators']['sos']['band'], 'warn')
