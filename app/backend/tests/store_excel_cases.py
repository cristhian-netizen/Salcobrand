"""Regression coverage for the legacy PDV transfer contract."""
import io
from openpyxl import Workbook, load_workbook


class StoreExcelCases:
    def store_excel_file(self, rows, alias=False, extra=False):
        from store_excel import COLUMNS, FIELDS
        book = Workbook()
        sheet = book.active
        sheet.title = 'PDV'
        headers = list(COLUMNS)
        if alias:
            headers[7] = 'Responsable de local'
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(field, '') for field in FIELDS])
        if extra:
            book.create_sheet('Gondolas').append(['Datos deliberadamente ignorados'])
        output = io.BytesIO()
        book.save(output)
        return output.getvalue()

    def transfer_excel(self, content, commit=False, version=None, role='admin'):
        data = {'commit': str(commit).lower()}
        if version:
            data['version'] = version
        return self.client(role).post('/api/admin/store-transfer/import', data=data,
                                     files={'file': ('PDV.xlsx', content, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})

    def test_store_excel_permissions_and_workbook_contract(self):
        from store_excel import COLUMNS, REL_COLUMNS
        content = self.store_excel_file([self.store_payload()])
        for role in (None, 'analyst', 'replenisher', 'viewer'):
            expected = 401 if role is None else 403
            for path in ('workbook.xlsx', 'filtered.csv'):
                self.assertEqual(self.client(role).get('/api/admin/store-transfer/' + path).status_code, expected)
            self.assertEqual(self.transfer_excel(content, role=role).status_code, expected)
        admin = self.client('admin')
        for template, sheets in [(True, ['PDV']), (False, ['PDV', 'Gondolas'])]:
            response = admin.get('/api/admin/store-transfer/workbook.xlsx', params={'template': str(template).lower()})
            self.assertEqual(response.status_code, 200, response.text[:100])
            book = load_workbook(io.BytesIO(response.content))
            self.assertEqual(book.sheetnames, sheets)
            self.assertEqual([cell.value for cell in book['PDV'][1]], COLUMNS)
            if not template:
                self.assertEqual([cell.value for cell in book['Gondolas'][1]], REL_COLUMNS)
            self.assertEqual(book['PDV'].freeze_panes, 'A2')
            book.close()

    def test_store_excel_preview_commit_and_preserve_infrastructure(self):
        admin = self.client('admin')
        admin.get('/api/admin/stores')
        shelf = self.create_type()
        linked = admin.post('/api/admin/shelf-instances/link-existing', json={
            'store_code': 'L128', 'type_id': shelf['id'], 'point_id': 'point-a', 'version': 0})
        self.assertEqual(linked.status_code, 200, linked.text)
        with self.db.get_conn() as conn:
            before = {table: [dict(row) for row in conn.execute('SELECT * FROM ' + table)]
                      for table in ('management_assignments', 'management_instances', 'points', 'users', 'readings')}
        content = self.store_excel_file([{**self.store_payload('0001'), 'region': 'Región Metropolitana de Santiago'},
                                       self.store_payload('L128')], alias=True, extra=True)
        response = self.transfer_excel(content)
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertEqual((preview['creates'], preview['updates'], preview['errors']), (1, 1, []))
        self.assertEqual(preview['sample'][0]['region'], 'Metropolitana de Santiago')
        self.assertNotIn('0001', {store['code'] for store in admin.get('/api/admin/stores').json()})
        result = self.transfer_excel(content, True, preview['version'])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()['committed'])
        with self.db.get_conn() as conn:
            for table, rows in before.items():
                self.assertEqual([dict(row) for row in conn.execute('SELECT * FROM ' + table)], rows, table)
        exported = admin.get('/api/admin/store-transfer/workbook.xlsx')
        book = load_workbook(io.BytesIO(exported.content))
        codes = [row[0] for row in book['PDV'].iter_rows(min_row=2)]
        cell = next(cell for cell in codes if cell.value == '0001')
        self.assertEqual((cell.data_type, cell.number_format), ('s', '@'))
        self.assertEqual(book['Gondolas'].cell(2, 3).value, 1)
        book.close()
        self.assertEqual(self.transfer_excel(content, True, preview['version']).status_code, 409)

    def test_store_excel_errors_are_atomic(self):
        admin = self.client('admin')
        for invalid in [self.store_payload('qa-001'), {**self.store_payload('BAD'), 'commune': 'Inexistente'},
                        {**self.store_payload('BAD'), 'store_type': 'Inexistente'},
                        {**self.store_payload('BAD'), 'name': '=1+1'}, self.store_payload(123)]:
            content = self.store_excel_file([self.store_payload(), invalid])
            preview = self.transfer_excel(content)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertTrue(preview.json()['errors'])
            self.assertEqual(self.transfer_excel(content, True, preview.json()['version']).status_code, 400)
            self.assertNotIn('QA-001', {store['code'] for store in admin.get('/api/admin/stores').json()})

    def test_store_excel_changed_file_or_store_requires_preview(self):
        admin = self.client('admin')
        content = self.store_excel_file([self.store_payload()])
        preview = self.transfer_excel(content).json()
        changed = self.store_excel_file([{**self.store_payload(), 'name': 'Otro nombre'}])
        self.assertEqual(self.transfer_excel(changed, True, preview['version']).status_code, 409)
        self.assertEqual(admin.post('/api/admin/stores', json=self.store_payload('OTHER')).status_code, 201)
        self.assertEqual(self.transfer_excel(content, True, preview['version']).status_code, 409)
        fresh = self.transfer_excel(content).json()
        self.assertEqual(self.transfer_excel(content, True, fresh['version']).status_code, 200)
        self.assertEqual(admin.delete('/api/admin/stores/QA-001?version=1').status_code, 200)
        self.assertTrue(self.transfer_excel(content).json()['errors'])

    def test_store_excel_csv_filters_and_formula_safety(self):
        admin = self.client('admin')
        payload = {**self.store_payload(), 'name': '=Nombre', 'description': 'Texto especial'}
        self.assertEqual(admin.post('/api/admin/stores', json=payload).status_code, 201)
        response = admin.get('/api/admin/store-transfer/filtered.csv', params={
            'search': 'especial', 'region': payload['region'], 'commune': 'Santiago', 'status': 'Activo'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        self.assertIn("'=Nombre", response.text)
        self.assertNotIn('L128', response.text)
        self.assertNotIn('QA-001', admin.get('/api/admin/store-transfer/filtered.csv?commune=Providencia').text)
        book = load_workbook(io.BytesIO(admin.get('/api/admin/store-transfer/workbook.xlsx').content))
        cell = next(row[1] for row in book['PDV'].iter_rows(min_row=2) if row[0].value == 'QA-001')
        self.assertEqual((cell.value, cell.data_type), ('=Nombre', 's'))
        book.close()

    def test_store_excel_invalid_files(self):
        self.assertEqual(self.transfer_excel(b'invalid').status_code, 400)
        self.assertEqual(self.transfer_excel(b'x' * (5 * 1024 * 1024 + 1)).status_code, 400)
        self.assertEqual(self.transfer_excel(self.store_excel_file([])).status_code, 400)
