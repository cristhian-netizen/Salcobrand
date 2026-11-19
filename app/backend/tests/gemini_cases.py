"""Gemini pre-labeling: the APIs card, the suggestion endpoint and the review payload. Google is replaced by
httpx.MockTransport; no network, no key leaves the server, labels keep being human confirmations."""
import json
import os
from unittest.mock import patch
import httpx

GKEY = 'AIzaIsolatedGeminiTestKey-0123456789_ab'
GEMINI_PATH = '/v1beta/models/gemini-flash-latest:generateContent'


def answer(text):
    return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': text}]}}]})


class GeminiCases:
    def gemini(self, handler):
        """Every httpx client built during the test talks to `handler` (same harness as the fake Kilby)."""
        import gemini_prelabel
        factory = httpx.Client
        def create(**kwargs):
            client = factory(transport=httpx.MockTransport(handler), timeout=kwargs.get('timeout'))
            self.addCleanup(client.close)
            return client
        mocked = patch.object(gemini_prelabel.httpx, 'Client', side_effect=create)
        mocked.start(); self.addCleanup(mocked.stop)

    def save_gemini_key(self, key=GKEY):
        admin = self.client('admin')
        overview = admin.get('/api/admin/integrations').json()['integrations']
        version = next(i['version'] for i in overview if i['id'] == 'gemini')
        response = admin.put('/api/admin/integrations/gemini', json={'version': version, 'values': {'api_key': key}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def review_stub(self, items, titles=('Producto A', 'Producto B')):
        return patch.object(self.core, 'review_items_for_reading',
                            side_effect=lambda r, **kw: {'reading_id': r['id'], 'point_id': r['point_id'],
                                                         'created_at': r['created_at'], 'titles': list(titles),
                                                         'items': [dict(item) for item in items]})

    # ------------------------------------------------------------------ Administración → APIs
    def test_gemini_card_validation_test_connection_and_no_key_leaves_the_server(self):
        import integrations_service
        admin = self.client('admin')
        self.assertEqual(self.client('viewer').put('/api/admin/integrations/gemini',
                                                   json={'version': 0, 'values': {'api_key': GKEY}}).status_code, 403)
        for bad in ('corta', 'clave con espacios y más de veinte', 'clave!con#simbolos$de%sobra&aqui'):
            response = admin.put('/api/admin/integrations/gemini', json={'version': 0, 'values': {'api_key': bad}})
            self.assertEqual(response.status_code, 400, bad)
        saved = self.save_gemini_key()
        field = {f['name']: f for f in saved['fields']}['api_key']
        self.assertEqual((field['configured'], field['source'], field['last4'], field['env']),
                         (True, 'panel', GKEY[-4:], 'GEMINI_API_KEY'))
        calls = []
        def handler(request):
            calls.append(request)
            self.assertEqual(request.url.path, GEMINI_PATH)
            self.assertEqual(request.headers['x-goog-api-key'], GKEY)
            self.assertNotIn('authorization', request.headers)
            body = json.loads(request.content)
            self.assertEqual(body['generationConfig']['temperature'], 0)
            return answer('{"ok": true}')
        self.gemini(handler)
        integrations_service._TESTS.clear()
        result = self.client('admin').post('/api/admin/integrations/gemini/test', json={})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()['ok'])
        self.assertEqual(len(calls), 1)
        viewer = self.client('viewer').get('/api/admin/integrations')
        gemini = next(i for i in viewer.json()['integrations'] if i['id'] == 'gemini')
        self.assertTrue(gemini['test']['ok'])
        for text in (viewer.text, json.dumps(saved), result.text):
            self.assertNotIn(GKEY, text); self.assertNotIn(GKEY[4:-4], text)
        with self.db.get_conn() as conn:
            stored = json.dumps([dict(r) for r in conn.execute('SELECT * FROM management_integrations').fetchall()])
        self.assertNotIn(GKEY[4:-4], stored)
        # Without any key the connection test answers plainly instead of calling Google.
        version = next(i['version'] for i in self.client('admin').get('/api/admin/integrations').json()['integrations'] if i['id'] == 'gemini')
        self.client('admin').put('/api/admin/integrations/gemini', json={'version': version, 'values': {}, 'remove': ['api_key']})
        integrations_service._TESTS.clear()
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            missing = self.client('admin').post('/api/admin/integrations/gemini/test', json={})
        self.assertEqual(missing.status_code, 200)
        self.assertFalse(missing.json()['ok'])
        self.assertIn('Administración → APIs', missing.json()['message'])
        self.assertEqual(len(calls), 1)

    # ------------------------------------------------------------------ suggestions
    def suggest_items(self):
        return [{'image_index': 0, 'item_index': 0, 'product': 'Producto A', 'ocr': 'PRODUCTO A',
                 'text_top3': [{'title': 'Producto A', 'sku': 'A1'}, {'title': 'Producto B', 'sku': 'B2'}], 'visual_top3': []},
                {'image_index': 0, 'item_index': 1, 'product': 'Producto B', 'ocr': '',
                 'text_top3': [], 'visual_top3': []}]

    def reviewable_reading(self):
        products = [{'product': 'Producto A', 'facings': 1, 'needs_review': True, 'image_index': 0, 'item_index': 0, 'shelf_level': 1},
                    {'product': 'Producto B', 'facings': 1, 'needs_review': True, 'image_index': 0, 'item_index': 1, 'shelf_level': 1}]
        return self.db.add_reading('point-a', {**self.analysis, 'products': products}, [], captured_by='replenisher')

    def test_suggestions_are_stored_cached_and_served_with_the_review_payload(self):
        self.save_gemini_key()
        calls = []
        def handler(request):
            calls.append(request)
            prompt = json.loads(request.content)['contents'][0]['parts'][0]['text']
            self.assertIn('NINGUNO', prompt)
            if '(SKU A1)' in prompt:
                return answer('```json\n{"eleccion": "A1", "confianza": 0.91, "texto_leido": "PRODUCTO A 30ml"}\n```')
            return answer('{"eleccion": "NINGUNO", "confianza": 0.2, "texto_leido": "borroso"}')
        self.gemini(handler)
        trainer = self.trainer()
        created = self.reviewable_reading()
        with self.review_stub(self.suggest_items()):
            first = trainer.post(f"/api/internal/training/suggest/{created['id']}")
            self.assertEqual(first.status_code, 200, first.text)
            body = first.json()
            self.assertEqual((body['sugeridos'], body['sin_sugerencia'], body['en_cache'], body['errores']), (1, 1, 0, 0))
            byitem = {(s['image_index'], s['item_index']): s for s in body['suggestions']}
            self.assertEqual((byitem[(0, 0)]['title'], byitem[(0, 0)]['sku'], byitem[(0, 0)]['confidence']), ('Producto A', 'A1', 0.91))
            self.assertEqual(byitem[(0, 0)]['ocr_text'], 'PRODUCTO A 30ml')
            self.assertIsNone(byitem[(0, 1)]['title'])  # NINGUNO stored: pressing again will not pay for it
            self.assertEqual(len(calls), 2)
            again = trainer.post(f"/api/internal/training/suggest/{created['id']}")
            self.assertEqual((again.json()['en_cache'], again.json()['sugeridos']), (2, 0))
            self.assertEqual(len(calls), 2)  # cached: no second Gemini call
            pending = trainer.get('/api/review/pending')
            self.assertEqual(pending.status_code, 200, pending.text)
            reading = next(p for p in pending.json() if p['reading_id'] == created['id'])
            suggestion = next(i['suggestion'] for i in reading['items'] if i['item_index'] == 0)
            self.assertEqual((suggestion['title'], suggestion['model']), ('Producto A', 'gemini-flash-latest'))
            self.assertIsNone(next(i['suggestion'] for i in reading['items'] if i['item_index'] == 1)['title'])
            self.assertNotIn(GKEY, first.text + again.text + pending.text)
        with self.db.get_conn() as conn:
            rows = conn.execute('SELECT * FROM management_training_suggestions').fetchall()
        self.assertEqual(len(rows), 2)
        self.assertNotIn(GKEY[4:-4], json.dumps([dict(r) for r in rows]))
        # Confirming keeps writing the human label through the same endpoint as before.
        confirmed = trainer.post(f"/api/readings/{created['id']}/confirm",
                                 json={'image_index': 0, 'item_index': 0, 'title': 'Producto A', 'facings': 2})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertTrue(confirmed.json()['training_only'])

    def test_suggest_profile_enforcement_and_missing_key(self):
        trainer = self.trainer()
        path = f"/api/internal/training/suggest/{self.other['id']}"
        for role in ('admin', 'analyst', 'replenisher', 'viewer'):
            self.assertEqual(self.client(role).post(path).status_code, 403, role)
        self.assertEqual(self.client(None).post(path).status_code, 401)
        calls = []
        self.gemini(lambda request: calls.append(request) or httpx.Response(500))
        with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
            with self.review_stub(self.suggest_items()):
                response = trainer.post(path)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('clave de Gemini', response.json()['detail'])
        self.assertEqual(calls, [])
        self.assertEqual(trainer.post('/api/internal/training/suggest/999999').status_code, 404)

    def test_suggest_respects_retry_after_once_and_reports_errors_in_spanish(self):
        self.save_gemini_key()
        state = {'calls': 0, 'mode': 'retry-once'}
        def handler(request):
            state['calls'] += 1
            if state['mode'] == 'always-429' or state['calls'] == 1:
                return httpx.Response(429, headers={'Retry-After': '0'}, json={'error': {'status': 'RESOURCE_EXHAUSTED'}})
            return answer('{"eleccion": "Producto A", "confianza": 0.8, "texto_leido": ""}')
        self.gemini(handler)
        trainer = self.trainer()
        with self.review_stub(self.suggest_items()[:1]):
            response = trainer.post(f"/api/internal/training/suggest/{self.other['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()['sugeridos'], response.json()['errores']), (1, 0))
        self.assertEqual(state['calls'], 2)  # one retry after the 429, never more
        # A persistent 429 surfaces as a Spanish error without storing anything.
        with self.db.get_conn() as conn:
            conn.execute('DELETE FROM management_training_suggestions')
        state.update(calls=0, mode='always-429')
        with self.review_stub(self.suggest_items()[:1]):
            limited_response = trainer.post(f"/api/internal/training/suggest/{self.other['id']}")
        self.assertEqual(limited_response.status_code, 200)
        self.assertEqual(limited_response.json()['errores'], 1)
        self.assertIn('límite de Gemini', limited_response.json()['error'])
        self.assertEqual(state['calls'], 2)
        with self.db.get_conn() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM management_training_suggestions').fetchone()['n'], 0)

    def test_answer_parsing_is_strict_but_tolerates_fences_and_unknown_choices(self):
        import gemini_prelabel
        candidates = [{'title': 'Producto A', 'sku': 'A1'}]
        self.assertEqual(gemini_prelabel.parse_answer('```json\n{"eleccion":"a1","confianza":1.4,"texto_leido":"X"}```', candidates),
                         ('Producto A', 'A1', 1.0, 'X'))
        self.assertEqual(gemini_prelabel.parse_answer('{"eleccion":"Producto inventado","confianza":0.9,"texto_leido":""}', candidates),
                         (None, '', 0.9, ''))
        self.assertEqual(gemini_prelabel.parse_answer('{"eleccion":"NINGUNO","confianza":"alta","texto_leido":""}', candidates),
                         (None, '', None, ''))
        for broken in ('sin json', '```json\n[1,2]\n```', '{"eleccion": '):
            with self.assertRaises(gemini_prelabel.GeminiError):
                gemini_prelabel.parse_answer(broken, candidates)
        # Items without own candidates fall back to the closest catalog titles.
        fallback = gemini_prelabel.candidates_for({'product': 'Producto B', 'ocr': ''}, ['Producto A', 'Producto B', 'Otro'])
        self.assertEqual(fallback[0]['title'], 'Producto B')
        self.assertEqual(gemini_prelabel.candidates_for({'product': '', 'ocr': ''}, []), [])
