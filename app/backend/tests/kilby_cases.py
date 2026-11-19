"""Neuravision on Kilby: Administración → APIs (keys encrypted, never returned), the analysis adapter and the catalog
sync for "Entrenar en Kilby". Kilby is replaced by httpx.MockTransport; no network, no cloud, no model."""
import json
import os
from unittest.mock import patch
import httpx

KEY = 'kai_' + 'IsolatedTestKey' * 3
OTHER_KEY = 'kai_' + 'AnotherTestKey00' * 3
RESULT = {'total_facings': 5, 'shelf_levels_detected': 2, 'empty_space_pct': 3.5, 'needs_review': 1, 'categories': ['Salud sexual'],
          'possible_missing': ['Producto Z'],
          'products': [{'product': 'Producto A', 'brand': 'Marca', 'sku': 'A1', 'facings': 3, 'shelf_level': 1, 'position_index': 1,
                        'match_status': 'match', 'confidence': 0.93, 'needs_review': False, 'image_index': 0, 'item_index': 0}]}


class KilbyCases:
    def kilby(self, handler):
        """Every KilbyNeuravision client built during the test talks to `handler`."""
        import kilby_neuravision
        factory = httpx.Client
        def create(**kwargs):
            client = factory(transport=httpx.MockTransport(handler), timeout=kwargs.get('timeout'))
            self.addCleanup(client.close)
            return client
        mocked = patch.object(kilby_neuravision.httpx, 'Client', side_effect=create)
        mocked.start(); self.addCleanup(mocked.stop)
        env = patch.dict(os.environ, {'NEURAVISION_ANALYSIS_BACKEND': 'kilby', 'KILBY_NEURAVISION_URL': 'https://kilby.invalid/v1'})
        env.start(); self.addCleanup(env.stop)
        import kilby_model
        kilby_model._HEALTH.update(generation=None)  # tables are emptied between tests without bumping the generation

    def save_key(self, key=KEY, **values):
        admin = self.client('admin')
        version = admin.get('/api/admin/integrations').json()['integrations'][0]['version']
        response = admin.put('/api/admin/integrations/neuravision', json={'version': version, 'values': {'api_key': key, **values}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # ------------------------------------------------------------------ Administración → APIs
    def test_apis_section_permissions_and_keys_never_leave_the_server(self):
        for role, expected in ((None, 401), ('analyst', 403), ('replenisher', 403), ('admin', 200), ('viewer', 200)):
            self.assertEqual(self.client(role).get('/api/admin/integrations').status_code, expected, role)
        for role in ('viewer', 'analyst', 'replenisher'):
            client = self.client(role)
            self.assertEqual(client.put('/api/admin/integrations/neuravision', json={'version': 0, 'values': {'api_key': KEY}}).status_code, 403)
            self.assertEqual(client.post('/api/admin/integrations/neuravision/test', json={}).status_code, 403)
        saved = self.save_key(catalog='salud-sexual')
        field = {f['name']: f for f in saved['fields']}
        self.assertEqual((field['api_key']['configured'], field['api_key']['source'], field['api_key']['last4']), (True, 'panel', KEY[-4:]))
        self.assertEqual(field['catalog']['value'], 'salud-sexual')
        viewer = self.client('viewer').get('/api/admin/integrations')
        self.assertFalse(viewer.json()['can_edit'])
        self.assertEqual(viewer.headers['cache-control'], 'no-store')
        for text in (viewer.text, self.client('admin').get('/api/admin/integrations').text, json.dumps(saved)):
            self.assertNotIn(KEY, text); self.assertNotIn(KEY[4:-4], text)
        with self.db.get_conn() as conn:
            stored = json.dumps([dict(r) for r in conn.execute('SELECT * FROM management_integrations').fetchall()])
            events = json.dumps([dict(r) for r in conn.execute('SELECT * FROM management_events').fetchall()])
        self.assertNotIn(KEY[4:-4], stored)  # encrypted at rest
        self.assertNotIn(KEY[4:-4], events)
        import integrations_service
        self.assertEqual(integrations_service.secret('neuravision', 'api_key'), KEY)

    def test_apis_validation_versions_rotation_and_environment_fallback(self):
        import integrations_service
        admin = self.client('admin')
        for values in ({'api_key': 'sk-live-not-kilby'}, {'api_key': 'kai_short'}, {'catalog': 'Salud Sexual'}, {'unknown': 'x'}):
            response = admin.put('/api/admin/integrations/neuravision', json={'version': 0, 'values': values})
            self.assertIn(response.status_code, (400, 404), values)
        self.save_key()
        stale = admin.put('/api/admin/integrations/neuravision', json={'version': 0, 'values': {'api_key': OTHER_KEY}})
        self.assertEqual(stale.status_code, 409)
        with patch.dict(os.environ, {'INTEGRATIONS_SECRET_KEY': 'a-different-encryption-key-for-qa'}):
            field = {f['name']: f for f in integrations_service.field_states('neuravision')}['api_key']
            self.assertEqual((field['configured'], field['unreadable']), (False, True))
            self.assertIsNone(integrations_service.secret('neuravision', 'api_key'))
            with patch.dict(os.environ, {'NEURAVISION_API_KEY': OTHER_KEY}):
                self.assertEqual(integrations_service.secret('neuravision', 'api_key'), OTHER_KEY)
        version = admin.get('/api/admin/integrations').json()['integrations'][0]['version']
        removed = admin.put('/api/admin/integrations/neuravision', json={'version': version, 'values': {}, 'remove': ['api_key']})
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertFalse({f['name']: f for f in removed.json()['fields']}['api_key']['configured'])

    def test_connection_check_sends_no_photo_and_keeps_result_for_viewer(self):
        import integrations_service
        calls = []
        def handler(request):
            calls.append((request.method, request.url.path, request.headers['authorization'], len(request.content)))
            if request.method == 'GET':
                return httpx.Response(200, json={'object': 'list', 'data': []})
            self.assertNotIn(b'filename=', request.content)
            return httpx.Response(400, json={'error': {'type': 'invalid_request_error', 'code': 'invalid_request', 'param': 'images', 'message': 'send 1 to 6 photos'}})
        self.kilby(handler)
        self.save_key()
        integrations_service._TESTS.clear()
        result = self.client('admin').post('/api/admin/integrations/neuravision/test', json={})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()['ok'])
        self.assertEqual([c[:2] for c in calls], [('GET', '/v1/neuravision/jobs'), ('POST', '/v1/neuravision/analyze')])
        self.assertEqual({c[2] for c in calls}, {'Bearer ' + KEY})
        self.assertTrue(self.client('viewer').get('/api/admin/integrations').json()['integrations'][0]['test']['ok'])
        self.assertEqual(self.client('admin').post('/api/admin/integrations/neuravision/test', json={}).status_code, 429)

    # ------------------------------------------------------------------ analysis adapter
    def test_kilby_adapter_submits_once_maps_the_result_and_resumes_without_paying_twice(self):
        import kilby_model
        posts = []
        def handler(request):
            if request.method == 'POST':
                posts.append(request)
                return httpx.Response(200, json={'id': 'vjob_qa1', 'object': 'neuravision.job', 'status': 'done', 'photos': 1,
                                                 'catalog': 'salud-sexual', 'billed': True, 'engine_ms': 6100, 'result_available': True, 'result': RESULT})
            self.assertEqual(request.url.path, '/v1/neuravision/jobs/vjob_qa1')
            return httpx.Response(200, json={'id': 'vjob_qa1', 'status': 'done', 'photos': 1, 'billed': True, 'result_available': True, 'result': RESULT})
        self.kilby(handler)
        self.save_key(catalog='salud-sexual')
        self.db.create_job('kilby-job', 'app', 'point-a', {'user': 'analyst'})
        analysis = kilby_model.analyze('point-a', [(b'\xff\xd8\xffsynthetic', 'image/jpeg')], 1.2, 'kilby-job')
        self.assertEqual(len(posts), 1)
        body = posts[0].content
        for field, value in (('store_id', b'L128'), ('gondola_id', b'point-a'), ('catalog', b'salud-sexual'), ('wait', b'25'), ('linear_meters', b'1.2')):
            self.assertIn(b'name="' + field.encode() + b'"\r\n\r\n' + value, body)
        self.assertEqual(posts[0].headers['authorization'], 'Bearer ' + KEY)
        self.assertEqual(analysis['total_facings'], 5)
        self.assertEqual(analysis['products'][0]['sku'], 'A1')
        self.assertEqual(analysis['engine']['kilby']['job_id'], 'vjob_qa1')
        self.assertEqual(analysis['engine']['images'], [])
        self.assertNotIn(KEY, json.dumps(analysis))
        payload = self.db.get_job('kilby-job')['payload']
        self.assertEqual((payload['kilby_job_id'], payload['remote_submitted']), ('vjob_qa1', True))
        kilby_model.analyze('point-a', [(b'\xff\xd8\xffsynthetic', 'image/jpeg')], 1.2, 'kilby-job')  # "Recuperar"
        self.assertEqual(len(posts), 1)

    def test_kilby_adapter_without_key_does_not_analyze(self):
        import kilby_model
        calls = []
        self.kilby(lambda request: calls.append(request) or httpx.Response(500))
        import kilby_model
        kilby_model._HEALTH.update(generation=None)
        self.db.create_job('no-key', 'app', 'point-a', {'user': 'analyst'})
        with patch.dict(os.environ, {'NEURAVISION_API_KEY': ''}):
            with self.assertRaises(ValueError) as caught:
                kilby_model.analyze('point-a', [(b'\xff\xd8\xffx', 'image/jpeg')], job_id='no-key')
            self.assertIn('Administración → APIs', str(caught.exception))
            self.assertFalse(kilby_model.health()['engine_ready'])
        self.assertEqual(calls, [])
        self.assertTrue(self.db.get_job('no-key')['payload']['remote_final_failed'])

    def test_kilby_adapter_rejection_and_broken_connection_recovery(self):
        import kilby_model
        state = {'posts': 0, 'mode': 'rejected'}
        def handler(request):
            if request.method == 'POST':
                state['posts'] += 1
                if state['mode'] == 'broken':
                    raise httpx.ReadTimeout('connection lost after sending', request=request)
                return httpx.Response(200, json={'id': 'vjob_rej', 'status': 'failed', 'photos': 1,
                                                 'error': {'code': 'analysis_rejected', 'message': 'no shelf'}})
            if request.url.path == '/v1/neuravision/jobs':
                return httpx.Response(200, json={'object': 'list', 'data': [
                    {'id': 'vjob_late', 'status': 'done', 'photos': 1, 'created_at': '2999-01-01T00:00:00Z'}]})
            return httpx.Response(200, json={'id': 'vjob_late', 'status': 'done', 'photos': 1, 'billed': True, 'result_available': True, 'result': RESULT})
        self.kilby(handler)
        self.save_key()
        self.db.create_job('rejected', 'app', 'point-a', {'user': 'analyst'})
        analysis = kilby_model.analyze('point-a', [(b'\xff\xd8\xffx', 'image/jpeg')], job_id='rejected')
        self.assertFalse(analysis['is_pharmacy_shelf'])
        self.assertIn('No se cobró', analysis['rejection_reason'])
        self.assertTrue(self.db.get_job('rejected')['payload']['remote_final_failed'])
        state['mode'] = 'broken'
        self.db.create_job('broken', 'app', 'point-a', {'user': 'analyst'})
        with self.assertRaises(ValueError):
            kilby_model.analyze('point-a', [(b'\xff\xd8\xffx', 'image/jpeg')], job_id='broken')
        payload = self.db.get_job('broken')['payload']
        self.assertTrue(payload['remote_submitted']); self.assertNotIn('remote_final_failed', payload)
        posts_before = state['posts']
        recovered = kilby_model.analyze('point-a', [(b'\xff\xd8\xffx', 'image/jpeg')], job_id='broken')
        self.assertEqual(state['posts'], posts_before)  # recovered from Kilby's job list, never sent again
        self.assertEqual(recovered['engine']['kilby']['job_id'], 'vjob_late')

    def test_kilby_ids_fit_the_gateway_rules(self):
        import kilby_model
        self.assertEqual(kilby_model.kilby_id('SB-INF-3F05DC9DAFCC4199'), 'SB-INF-3F05DC9DAFCC4199')
        long_id = 'SB-MANUAL-' + 'EFBCDDF8DD16BFF2F460EDDD53A9375B'
        mapped = kilby_model.kilby_id(long_id)
        self.assertLessEqual(len(mapped), 40); self.assertEqual(mapped, kilby_model.kilby_id(long_id))
        self.assertRegex(kilby_model.kilby_id('PDV 001 / Ñuñoa'), r'^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$')

    def test_reanalysis_is_blocked_with_kilby(self):
        with patch.dict(os.environ, {'NEURAVISION_ANALYSIS_BACKEND': 'kilby', 'ROLE': 'all'}), \
                patch.object(self.core, 'analysis_backend', create=True, new=lambda: 'kilby'), patch.object(self.main, 'ROLE', 'all'):
            response = self.client('analyst').post('/api/admin/reanalyze')
        self.assertEqual(response.status_code, 409, response.text)

    # ------------------------------------------------------------------ Entrenar en Kilby (dataset API, not deployed yet)
    def test_product_changes_are_queued_and_sent_to_kilby(self):
        import kilby_catalog
        seen = []
        def handler(request):
            seen.append((request.method, request.url.path, request.headers.get('content-type', '')))
            if request.url.path == '/v1/neuravision/catalogs':
                return httpx.Response(200, json={'object': 'list', 'data': [{'slug': 'salud-sexual', 'name': 'Salud sexual', 'products': 0}]})
            if request.method == 'PUT':
                return httpx.Response(201, json={'sku': '000123', 'photos': 0})
            return httpx.Response(204)
        self.kilby(handler)
        self.save_key()
        product = self.create_product()
        with self.db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT pending FROM management_kilby_products WHERE sku='000123'").fetchone()['pending'], 'put')
        self.assertEqual(kilby_catalog.drain(), {'sent': 1, 'deleted': 0, 'failed': 0})
        self.assertIn(('PUT', '/v1/neuravision/catalogs/salud-sexual/products/000123', 'application/json'), seen)
        response = self.client('admin').post('/api/admin/catalog/products/delete', json={'products': [{'id': product['id'], 'version': product['version']}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(kilby_catalog.drain()['deleted'], 1)
        self.assertIn(('DELETE', '/v1/neuravision/catalogs/salud-sexual/products/000123', ''), seen)

    def test_labels_use_kilby_job_ids_and_skip_older_readings(self):
        import kilby_catalog
        product = self.create_product(name='Producto verificado')
        kilby_reading = self.db.add_reading('point-a', {**self.analysis, 'engine': {'images': [], 'kilby': {'job_id': 'vjob_ok'}}}, [])
        old_reading = self.db.add_reading('point-a', self.analysis, [])
        with self.db.get_conn() as conn:
            for label_id, reading, title in (('l1', kilby_reading, 'Producto verificado'), ('l2', old_reading, 'Producto verificado'), ('l3', kilby_reading, ''), ('l4', kilby_reading, 'Desconocido')):
                conn.execute('INSERT INTO management_training_labels(id,reading_id,image_index,item_index,data_json,crop_path,created_by,created_at) VALUES(?,?,0,?,?,?,?,?)',
                             (label_id, reading['id'], int(label_id[1]), json.dumps({'title': title}), '_training/' + label_id, 'local-neura', self.db.now_iso()))
        labels, skipped = kilby_catalog.labels()
        self.assertEqual(labels, [{'job_id': 'vjob_ok', 'image_index': 0, 'item_index': 1, 'sku': product['sku']}])
        self.assertEqual(skipped, {'sin_job_kilby': 1, 'sin_sku': 1, 'ajeno': 1})

    def test_train_in_kilby_route_is_internal_and_reports_metrics(self):
        trainings = {}
        def handler(request):
            path = request.url.path
            if path == '/v1/neuravision/catalogs':
                return httpx.Response(200, json={'object': 'list', 'data': [{'slug': 'salud-sexual', 'name': 'Salud sexual', 'trainings_left': 1,
                                                                            'published_version': {'version': 'v1', 'top1': 0.81, 'top3': 0.93}}]})
            if path.endswith('/trainings') and request.method == 'POST':
                trainings['tr_1'] = 0
                return httpx.Response(202, json={'id': 'tr_1', 'status': 'queued'})
            if path.endswith('/trainings/tr_1'):
                return httpx.Response(200, json={'id': 'tr_1', 'status': 'done', 'metrics': {'top1': 0.84, 'top3': 0.95, 'skus': 1},
                                                 'baseline': {'top1': 0.81, 'top3': 0.93}, 'version': 'v2', 'published': True, 'error': None})
            if path.endswith('/versions'):
                return httpx.Response(200, json={'object': 'list', 'data': []})
            return httpx.Response(404, json={'error': {'type': 'invalid_request_error', 'message': 'not found'}})
        self.kilby(handler)
        self.save_key()
        for role in ('admin', 'viewer', 'analyst'):
            self.assertEqual(self.client(role).post('/api/internal/training/kilby/trainings').status_code, 403, role)
        trainer = self.trainer()
        started = trainer.post('/api/internal/training/kilby/trainings')
        self.assertEqual(started.status_code, 202, started.text)
        self.assertEqual((started.json()['status'], started.json()['metrics']['top1'], started.json()['baseline']['top1']), ('done', 0.84, 0.81))
        overview = trainer.get('/api/internal/training/kilby').json()
        self.assertEqual(overview['catalog']['slug'], 'salud-sexual')
        self.assertEqual(overview['trainings'][0]['version'], 'v2')

    def test_dataset_api_not_deployed_is_reported_plainly(self):
        self.kilby(lambda request: httpx.Response(404, json={'error': {'type': 'invalid_request_error', 'message': 'not found'}}))
        self.save_key()
        trainer = self.trainer()
        self.assertEqual(trainer.get('/api/internal/training/kilby').json()['error'], 'Kilby todavía no ofrece la API de catálogos y entrenamientos.')
        response = trainer.post('/api/internal/training/kilby/trainings')
        self.assertEqual(response.status_code, 503, response.text)
