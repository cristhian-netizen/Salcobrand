from copy import deepcopy


class DetailCases:
    def detail_fixture(self, planogram=True):
        import infrastructure
        infrastructure.bootstrap_legacy_stores()
        shelf = infrastructure.save_type({'name': 'Detalle QA', 'width_cm': 100, 'depths': [30], 'status': 'Activo'}, 'admin')
        state = infrastructure.link_existing('L128', shelf['id'], 'point-a', 0, 'admin')
        instance = state['instances'][0]['id']
        first = self.create_product(sku='MANUAL-1', name='Producto propio')
        second = self.create_product(sku='MANUAL-2', name='Producto competencia', barcode='000790')
        if planogram:
            response = self.client('admin').post('/api/admin/catalog/planograms', json=self.plan_fields(first))
            self.assertEqual(response.status_code, 201, response.text)
            plan = response.json()
            with self.db.get_conn() as conn:
                conn.execute('UPDATE readings SET planogram_id = ? WHERE id = ?', (plan['id'], self.other['id']))
        row = {'productId': first['id'], 'position': 'Nivel 1 / 1', 'ownership': 'Propio',
               'expected': True, 'present': True, 'faces': 3, 'match': 'Sí' if planogram else 'N/A',
               'observedPrice': 0, 'confidence': 0}
        payload = {'version': 0, 'reviewVersion': 0, 'shelfInstanceId': instance, 'details': [row],
                   'scopeConfirmed': True, 'expectedConfirmed': True, 'comparisonConfirmed': planogram}
        return payload, first, second

    def test_manual_detail_permissions_and_scope(self):
        payload, _, _ = self.detail_fixture()
        url = f"/api/readings/{self.other['id']}/product-details"
        for role in ('admin', 'viewer', 'replenisher'):
            self.assertEqual(self.client(role).patch(url, json=payload).status_code, 403)
        self.assertEqual(self.client(None).get(url).status_code, 401)
        self.assertEqual(self.client('replenisher').get(url).status_code, 403)
        self.assertEqual(self.client('analyst').get(f"/api/readings/{self.foreign['id']}/product-detail-options").status_code, 403)
        for role in ('admin', 'viewer', 'analyst'):
            self.assertEqual(self.client(role).get(url).status_code, 200)
        self.assertTrue(self.client('analyst').get(url).json()['shelfLabel'])
        options = self.client('analyst').get(f"/api/readings/{self.other['id']}/product-detail-options").json()
        self.assertEqual(len(options['products']), 2)
        self.assertEqual(len(options['instances']), 1)

    def test_manual_metrics_group_products_and_weight_faces_after_approval(self):
        payload, first, second = self.detail_fixture()
        payload['details'] += [
            {**payload['details'][0], 'position': 'Nivel 1 / 2', 'present': False, 'faces': 0, 'match': 'No'},
            {**payload['details'][0], 'productId': second['id'], 'position': 'Nivel 1 / 3',
             'ownership': 'Competencia', 'faces': 1, 'match': 'N/A'},
        ]
        url = f"/api/readings/{self.other['id']}/product-details"
        result = self.client('analyst').patch(url, json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIsNone(result.json()['metrics']['indicators']['osa']['value'])
        self.assertEqual(result.json()['details'][0]['observedPrice'], 0)
        self.assertEqual(result.json()['details'][0]['confidence'], 0)
        self.assertEqual(result.json()['details'][0]['name'], first['name'])
        self.client('analyst').patch(f"/api/readings/{self.other['id']}/review", json={'status': 'Aprobado', 'note': '', 'version': 1})
        metrics = self.client('viewer').get(url).json()['metrics']
        self.assertEqual(metrics['expected'], 2)
        self.assertEqual({key: value['value'] for key, value in metrics['indicators'].items()}, {'osa': 100, 'sos': 75, 'cp': 50})
        self.assertTrue(self.db.reading_planogram_snapshot(self.other['id']))
        self.assertEqual(self.db.get_reading(self.other['id'])['products'][0]['product'], 'Synthetic product')

    def test_manual_detail_conflicts_do_not_overwrite_and_changes_invalidate_approval(self):
        payload, _, _ = self.detail_fixture()
        client = self.client('analyst')
        url = f"/api/readings/{self.other['id']}/product-details"
        self.assertEqual(client.patch(url, json=payload).status_code, 200)
        self.assertEqual(client.patch(url, json=payload).status_code, 409)
        client.patch(f"/api/readings/{self.other['id']}/review", json={'status': 'Aprobado', 'note': '', 'version': 1})
        payload.update(version=1, reviewVersion=1)
        self.assertEqual(client.patch(url, json=payload).status_code, 409)
        payload['reviewVersion'] = 2
        payload['details'][0]['faces'] = 4
        result = client.patch(url, json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['review']['status'], 'En revisión')
        self.assertEqual(result.json()['reviewVersion'], 3)
        self.assertEqual(result.json()['version'], 2)
        self.assertIsNone(result.json()['metrics']['indicators']['sos']['value'])

    def test_manual_detail_validation_and_atomic_rollback(self):
        payload, _, _ = self.detail_fixture(False)
        client = self.client('analyst')
        url = f"/api/readings/{self.other['id']}/product-details"
        invalid = []
        for field, value in [('faces', -1), ('faces', True), ('faces', 1.5), ('confidence', 101), ('observedPrice', -1),
                             ('present', 'true'), ('position', '  '), ('productId', 'unknown'), ('match', 'Sí')]:
            candidate = deepcopy(payload)
            candidate['details'][0][field] = value
            invalid.append(candidate)
        absent = deepcopy(payload)
        absent['details'][0]['present'] = False
        invalid.append(absent)
        duplicate = deepcopy(payload)
        duplicate['details'].append(deepcopy(duplicate['details'][0]))
        invalid.append(duplicate)
        invalid.append({**payload, 'details': []})
        invalid.append({**payload, 'comparisonConfirmed': True})
        for candidate in invalid:
            response = client.patch(url, json=candidate)
            self.assertIn(response.status_code, (400, 422), response.text)
            self.assertEqual(client.get(url).json()['version'], 0)
            self.assertEqual(self.db.measurement_review(self.other['id'])['version'], 0)
        result = client.patch(url, json=payload)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json()['hasPlanogram'])

    def test_model_evidence_change_clears_confirmations_and_product_references_are_protected(self):
        payload, first, _ = self.detail_fixture(False)
        url = f"/api/readings/{self.other['id']}/product-details"
        self.client('analyst').patch(url, json=payload)
        self.db.update_reading_products(self.other['id'], self.analysis['products'])
        data = self.client('analyst').get(url).json()
        self.assertEqual(data['version'], 2)
        self.assertFalse(data['scopeConfirmed'])
        self.assertFalse(data['expectedConfirmed'])
        self.assertEqual(len(data['details']), 1)
        import catalog_service
        import infrastructure
        with self.assertRaises(infrastructure.ManagementError):
            catalog_service.delete_products([{'id': first['id'], 'version': first['version']}], 'admin')
        self.db.delete_reading(self.other['id'])
        with self.db.get_conn() as conn:
            self.assertIsNone(conn.execute('SELECT * FROM management_reading_details WHERE reading_id = ?', (self.other['id'],)).fetchone())
