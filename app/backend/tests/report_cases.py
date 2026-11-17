"""Export contracts, Chilean date boundaries, approval and performance regressions."""
import csv
from datetime import date, time
import io
from openpyxl import load_workbook


class ReportCases:
    def test_individual_excel_includes_detected_products_and_author_scope(self):
        path = f"/api/readings/{self.own['id']}/report.xlsx"
        for role in ('replenisher', 'analyst', 'viewer', 'admin'):
            response = self.client(role).get(path)
            self.assertEqual(response.status_code, 200, response.text)
            workbook = load_workbook(io.BytesIO(response.content))
            self.assertIn('Productos detectados', workbook.sheetnames)
            self.assertEqual(workbook['Productos detectados']['A2'].value, 'Synthetic product')
            self.assertEqual(workbook['Medición']['G2'].number_format, 'hh:mm "hrs."')
        self.assertEqual(self.client('replenisher').get(f"/api/readings/{self.other['id']}/report.xlsx").status_code, 403)
        self.assertEqual(self.client('analyst').get(f"/api/readings/{self.foreign['id']}/report.xlsx").status_code, 403)
        self.assertEqual(self.client(None).get(path).status_code, 401)

    def test_registered_empty_stores_are_filterable_without_expanding_scope(self):
        import infrastructure
        for code in ('L129', 'L131'):
            infrastructure.save_store({'code':code,'name':'Local sin góndola ' + code,'store_type':'Farmacia',
                'region':'Metropolitana de Santiago','commune':'Santiago','address':'Dirección ficticia 123',
                'manager':'Encargado ficticio','status':'Activo'},'admin')
        with self.db.get_conn() as conn:
            conn.execute("DELETE FROM points WHERE id='point-b'")
        for role in ('admin','viewer'):
            client=self.client(role)
            result=client.get('/api/reports/measurements?store=L131')
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['rows'],[])
            self.assertIn('L131',[s['code'] for s in result.json()['stores']])
            exported=client.get('/api/reports/measurements.xlsx?store=L131')
            self.assertEqual(exported.status_code,200)
            self.assertEqual(load_workbook(io.BytesIO(exported.content))['Mediciones'].max_row,1)
        analyst=self.client('analyst')
        self.assertEqual(analyst.get('/api/reports/measurements?store=L129').status_code,200)
        self.assertEqual(analyst.get('/api/reports/measurements?store=L131').status_code,403)
        self.assertNotIn('L131',[s['code'] for s in analyst.get('/api/reports/measurements').json()['stores']])
        self.assertEqual(self.client('replenisher').get('/api/measurements?store=L129').json()['count'],0)
        self.assertEqual(self.client('replenisher').get('/api/measurements?store=L131').status_code,403)
        self.assertEqual(self.client('admin').get('/api/reports/measurements?store=UNKNOWN').status_code,403)

    def test_superuser_catalog_exports_preserve_workbooks_and_read_only_permissions(self):
        import infrastructure
        infrastructure.bootstrap_legacy_stores()
        self.create_product(sku='REPORT-1',name='=Not a formula')
        for role in (None,'admin','analyst','replenisher'):
            for kind in ('products','stores'):
                response=self.client(role).get('/api/reports/catalog/'+kind+'.xlsx')
                self.assertEqual(response.status_code,401 if role is None else 403)
        for kind,sheet in (('products','Productos'),('stores','PDV')):
            response=self.client('viewer').get('/api/reports/catalog/'+kind+'.xlsx')
            self.assertEqual(response.status_code,200,response.text[:150])
            self.assertEqual(response.headers['cache-control'],'no-store')
            book=load_workbook(io.BytesIO(response.content))
            self.assertIn(sheet,book.sheetnames)
            if kind=='products':
                self.assertEqual(book[sheet].cell(2,4).value,'=Not a formula')
                self.assertEqual(book[sheet].cell(2,4).data_type,'s')
                self.assertEqual(book[sheet].cell(2,6).value,'REPORT-1')
            else:
                self.assertIn('L128',[row[0] for row in book[sheet].iter_rows(min_row=2,values_only=True)])
        person=self.create_person('suspended-viewer',role='viewer')
        self.assertEqual(self.update_person(person,status='Suspendido').status_code,200)
        self.assertEqual(self.client('suspended-viewer').get('/api/reports/catalog/products.xlsx').status_code,200)
        self.assertEqual(self.client('viewer').get('/api/admin/catalog').status_code,403)

    def test_measurement_history_preserves_filters_and_own_readings_without_report_access(self):
        client = self.client('replenisher')
        result = client.get('/api/measurements').json()
        self.assertEqual([r['id'] for r in result['rows']], [self.own['id']])
        self.assertEqual(result['rows'][0]['image_url'], '/uploads/point-a/own.jpg')
        with self.db.get_conn() as conn:
            conn.execute('UPDATE readings SET image_paths_json = NULL, image_path = ? WHERE id = ?', ('point-a/own.jpg', self.own['id']))
        self.assertEqual(client.get('/api/measurements').json()['rows'][0]['image_url'], '/uploads/point-a/own.jpg')
        self.assertNotIn('totals', result)
        self.assertEqual(client.get('/api/measurements?store=L130').status_code, 403)
        self.assertEqual(client.get('/api/measurements?status=Rechazado').json()['count'], 0)
        self.assertEqual(self.client(None).get('/api/measurements').status_code, 401)
        analyst = self.client('analyst')
        self.assertEqual(analyst.get('/api/measurements?store=L128').json()['count'], 2)
        self.assertEqual(analyst.get('/api/measurements?offset=2').json()['rows'], [])
        self.assertEqual(analyst.get('/api/measurements?offset=-1').status_code, 422)

    def review_measurement(self, reading, status="Aprobado", note="", version=0, username="analyst"):
        return self.client(username).patch(f'/api/readings/{reading["id"]}/review',
                                         json={"status": status, "note": note, "version": version})

    def test_report_and_approval_permissions_and_scope(self):
        for username in (None, 'admin', 'analyst', 'viewer', 'replenisher'):
            client = self.client(username)
            for extension in ('', '.csv', '.xlsx'):
                response = client.get('/api/reports/measurements' + extension)
                self.assertEqual(response.status_code, 401 if username is None else 403 if username == 'replenisher' else 200)
            review = self.review_measurement(self.other, username=username)
            self.assertEqual(review.status_code, 401 if username is None else 200 if username == 'analyst' else 403)
        analyst = self.client('analyst')
        self.assertNotIn(self.foreign['id'], [r['id'] for r in analyst.get('/api/reports/measurements').json()['rows']])
        self.assertEqual(analyst.get('/api/reports/measurements.xlsx?store=L130').status_code, 403)
        self.assertEqual(self.review_measurement(self.foreign).status_code, 403)

    def test_excel_measurement_columns_dates_time_and_safe_text(self):
        import measurement_reports
        self.client('admin').get('/api/admin/stores')
        with self.db.get_conn() as conn:
            conn.execute("UPDATE management_stores SET name = ?, region = ?, commune = ?, manager = ? WHERE code = 'L128'",
                         ('Farmacia Providencia', 'Metropolitana de Santiago', 'Providencia', '=HYPERLINK("bad")'))
            conn.execute('UPDATE readings SET created_at = ? WHERE id = ?', ('2026-11-12T18:35:00+00:00', self.own['id']))
        result = self.client('analyst').get('/api/reports/measurements.xlsx?from=2026-11-12&to=2026-11-12')
        self.assertEqual(result.status_code, 200, result.text[:200] if result.status_code != 200 else '')
        book = load_workbook(io.BytesIO(result.content))
        sheet = book['Mediciones']
        self.assertEqual([cell.value for cell in sheet[1]], measurement_reports.HEADERS)
        values = next(row for row in sheet.iter_rows(min_row=2) if row[0].value == self.own['id'])
        self.assertEqual(values[1].value, 'L128')
        self.assertEqual(values[2].value, 'Farmacia Providencia')
        self.assertEqual(values[5].value.date(), date(2026, 11, 12))
        self.assertEqual(values[6].value, time(15, 35))
        self.assertEqual(values[6].number_format, 'hh:mm "hrs."')
        self.assertEqual(values[10].value, 'No')
        self.assertEqual(values[11].value, 'replenisher')
        self.assertEqual(values[12].data_type, 's')
        self.assertEqual(sheet.freeze_panes, 'A2')
        self.assertTrue(sheet.auto_filter.ref)
        csv_result = self.client('analyst').get('/api/reports/measurements.csv?from=2026-11-12&to=2026-11-12')
        rows = list(csv.DictReader(io.StringIO(csv_result.content.decode('utf-8-sig')), delimiter=';'))
        own = next(r for r in rows if r['ID'] == str(self.own['id']))
        self.assertEqual(own['Hora'], '15:35 hrs.')
        self.assertTrue(own['Encargado de Local'].startswith("'="))
        self.assertEqual(result.headers['cache-control'], 'no-store')

    def test_report_date_filters_use_local_day_and_daylight_saving(self):
        with self.db.get_conn() as conn:
            conn.execute('UPDATE readings SET created_at = ? WHERE id = ?', ('2026-11-13T02:30:00Z', self.own['id']))
            conn.execute('UPDATE readings SET created_at = ? WHERE id = ?', ('2026-11-13T03:00:00+00:00', self.other['id']))
        client = self.client('analyst')
        rows = client.get('/api/reports/measurements?from=2026-11-12&to=2026-11-12').json()['rows']
        self.assertEqual([r['id'] for r in rows], [self.own['id']])
        self.assertEqual(rows[0]['time'], '23:30 hrs.')
        import measurement_reports
        self.assertEqual(measurement_reports.local_datetime('2026-07-12T19:35:00Z').strftime('%H:%M'), '15:35')
        for query in ('from=bad', 'from=20261112', 'from=2026-11-13&to=2026-11-12', 'status=unknown'):
            self.assertEqual(client.get('/api/reports/measurements?' + query).status_code, 400)

    def test_only_explicitly_approved_measurements_contribute_to_performance(self):
        self.assertEqual(self.review_measurement(self.own).status_code, 200)
        self.assertEqual(self.review_measurement(self.other, 'Rechazado', 'Foto borrosa').status_code, 200)
        pending = self.db.add_reading('point-a', {**self.analysis, 'empty_space_pct': 95, 'total_facings': 500}, [])
        result = self.client('analyst').get('/api/reports/measurements').json()
        self.assertEqual(result['totals']['approved'], 1)
        self.assertEqual(result['totals']['rejected'], 1)
        self.assertEqual(result['totals']['in_review'], 1)
        self.assertEqual(result['totals']['average_score'], self.own['standards']['overall_score'])
        summary = self.client('analyst').get('/api/summary').json()
        point = next(p for p in summary['points'] if p['id'] == 'point-a')
        self.assertEqual(point['last']['id'], pending['id'])
        self.assertEqual(point['performance']['id'], self.own['id'])
        self.assertEqual(summary['totals']['approved_readings_in_period'], 1)
        self.assertEqual(summary['totals']['points_measured_in_period'], 1)
        trends = self.client('analyst').get('/api/points/point-a/trends').json()
        self.assertEqual([r['id'] for r in trends['readings']], [self.own['id']])
        daily = self.client('analyst').get('/api/points/point-a/daily-metrics').json()
        self.assertEqual(sum(r['readings'] for r in daily), 1)
        self.assertEqual(daily[0]['avg_total_facings'], 2)
        replenishment = self.client('analyst').get('/api/points/point-a/replenishment').json()
        self.assertEqual(len(replenishment['empty_space_trend']), 1)

    def test_empty_approved_set_and_filtered_reports_do_not_invent_averages(self):
        client = self.client('analyst')
        result = client.get('/api/reports/measurements?status=Rechazado').json()
        self.assertEqual(result['totals']['measurements'], 0)
        self.assertIsNone(result['totals']['average_score'])
        summary = client.get('/api/summary').json()['totals']
        self.assertIsNone(summary['avg_compliance_pct'])
        self.assertEqual(summary['points_measured_in_period'], 0)
        self.assertEqual(client.get('/api/points/point-a/trends').json()['readings'], [])
        self.assertEqual(self.review_measurement(self.own).status_code, 200)
        filtered = client.get('/api/reports/measurements?status=En+revisión').json()
        self.assertIsNone(filtered['totals']['average_score'])
        self.assertNotIn(self.own['id'], [r['id'] for r in filtered['rows']])

    def test_summary_compliance_uses_approved_evidence_inside_selected_period(self):
        product = self.create_product()
        plan = self.save_plan(product)
        self.db.set_point_planogram('point-a', plan['id'])
        approved = self.db.add_reading('point-a', {**self.analysis, 'products': [
            {'product': product['name'], 'facings': 2, 'shelf_level': 1, 'position_index': 1}]}, [], planogram_id=plan['id'])
        self.assertEqual(self.review_measurement(approved).status_code, 200)
        rejected = self.db.add_reading('point-a', {**self.analysis, 'products': [], 'total_facings': 0}, [], planogram_id=plan['id'])
        self.assertEqual(self.review_measurement(rejected, 'Rechazado', 'Foto incompleta').status_code, 200)
        self.db.add_reading('point-a', {**self.analysis, 'products': [], 'total_facings': 0}, [], planogram_id=plan['id'])
        summary = self.client('analyst').get('/api/summary?days=7').json()
        self.assertGreater(approved['compliance']['compliance_pct'], 0)
        self.assertEqual(summary['totals']['avg_compliance_pct'], approved['compliance']['compliance_pct'])
        self.assertEqual(summary['totals']['total_missing'], 0)
        self.assertEqual(summary['stores'][0]['avg_compliance_pct'], approved['compliance']['compliance_pct'])
        with self.db.get_conn() as conn:
            conn.execute("UPDATE readings SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (approved['id'],))
        summary = self.client('analyst').get('/api/summary?days=7').json()
        self.assertIsNone(summary['totals']['avg_compliance_pct'])
        self.assertEqual(summary['totals']['approved_readings_in_period'], 0)

    def test_approval_conflicts_rejection_reason_and_changed_evidence(self):
        self.assertEqual(self.review_measurement(self.own, 'Rechazado').status_code, 400)
        first = self.review_measurement(self.own)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.review_measurement(self.own, 'Rechazado', 'Updated').status_code, 409)
        corrected = self.db.update_reading_products(self.own['id'], self.analysis['products'])
        self.assertEqual(corrected['review']['status'], 'En revisión')
        self.assertEqual(corrected['review']['version'], 2)
        self.assertEqual(self.review_measurement(self.own, version=1).status_code, 409)
        self.assertEqual(self.review_measurement(self.own, version=2).status_code, 200)
        reanalyzed = self.db.update_reading_analysis(self.own['id'], self.analysis)
        self.assertEqual(reanalyzed['review']['status'], 'En revisión')
