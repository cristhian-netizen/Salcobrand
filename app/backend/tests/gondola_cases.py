"""Which góndola a photo shows, against the store's real góndolas, and moving a reading to the one it shows.

Store L128 gets two góndolas: G1 with the Salud Sexual planogram and G2 with the real deodorant planogram; the photo is the
pilot's reading 105 (deodorant ideal render, catalog v4). The rule itself is in test_gondola_check.py."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


class GondolaCases:
    def _gondolas_in_l128(self):
        pilot = json.loads((HERE / 'planogram_position_pilot.json').read_text(encoding='utf-8'))
        deo = {'id': 'deo-l128', 'name': 'Desodorantes', 'module_cm': None, 'bands': 6, 'source_filename': None,
               'items': [{**it, 'order_seq': i + 1, 'section_label': '', 'module': 1, 'segment': None, 'price_clp': None}
                         for i, it in enumerate(pilot['planogram']['items'])]}
        salud = json.loads((HERE.parent / 'planogramas' / 'planograms_seed.json').read_text(encoding='utf-8'))[0]
        self.db.create_planogram(deo)
        self.db.create_planogram(salud)
        self.db.create_point('g1-salud', 'L128 · G1', planogram_id=salud['id'], store_id='L128', owner_client='test-client')
        self.db.create_point('g2-deo', 'L128 · G2', planogram_id='deo-l128', store_id='L128', owner_client='test-client')
        return self.db.get_planogram(salud['id']), self.db.get_planogram('deo-l128'), [dict(p) for p in pilot['reading_105']['products']]

    def _stored_on_the_wrong_gondola(self, captured_by='replenisher'):
        import gondola_check
        salud, deo, products = self._gondolas_in_l128()
        verdict = gondola_check.check_reading('g1-salud', products, salud)
        analysis = {'products': products, 'total_facings': 100, 'shelf_levels_detected': 6,
                    'engine': {'images': [], 'kilby': {'job_id': 'vjob_move'}, 'gondola_check': verdict}}
        return self.db.add_reading('g1-salud', analysis, ['g1-salud/photo.jpg'], None, salud['id'], captured_by=captured_by,
                                   capture_context={'category': 'Salud sexual', 'subcategories': ['Preservativos']},
                                   plan_snapshot=salud)

    def test_store_gondolas_point_to_the_planogram_the_photo_belongs_to(self):
        import gondola_check
        salud, deo, products = self._gondolas_in_l128()
        verdict = gondola_check.check_reading('g1-salud', products, salud)
        self.assertEqual((verdict['suggested_point_id'], verdict['suggested_name'], verdict['current_matches']), ('g2-deo', 'L128 · G2', 0))
        self.assertEqual(verdict['suggested_planogram_id'], 'deo-l128')
        self.assertGreaterEqual(verdict['suggested_matches'], 40)
        self.assertIsNone(gondola_check.check_reading('g2-deo', products, deo)['suggested_point_id'])
        self.assertIsNone(gondola_check.check_reading('point-c', products, None))  # L130 has no other góndola
        self.assertIsNone(gondola_check.check_reading('no-such-point', products, None))

    def test_moving_a_reading_to_the_gondola_it_shows(self):
        reading = self._stored_on_the_wrong_gondola()
        self.assertEqual(reading['engine']['gondola_check']['suggested_point_id'], 'g2-deo')
        response = self.client('replenisher').post(f"/api/readings/{reading['id']}/move", json={'point_id': 'g2-deo'})
        self.assertEqual(response.status_code, 200, response.text)
        moved = response.json()
        self.assertEqual((moved['point_id'], moved['planogram_id']), ('g2-deo', 'deo-l128'))
        self.assertEqual(moved['compliance']['compliance_pct'], 78.9)  # now compared with the deodorant planogram
        self.assertIsNone(moved['engine']['gondola_check']['suggested_point_id'])
        self.assertEqual((moved['engine']['moved']['from'], moved['engine']['moved']['by']), ('g1-salud', 'replenisher'))
        self.assertEqual(moved['engine']['kilby']['job_id'], 'vjob_move')
        self.assertNotEqual((moved.get('infrastructure') or {}).get('category'), 'Salud sexual')
        self.assertEqual(moved['review']['status'], 'En revisión')
        stored = self.db.get_reading(reading['id'])
        self.assertEqual((stored['point_id'], stored['planogram_reference']['id']), ('g2-deo', 'deo-l128'))
        with self.db.get_conn() as conn:
            event = conn.execute("SELECT actor, before_json, after_json FROM management_events WHERE action = 'reading.move' AND resource_id = ?",
                                 (str(reading['id']),)).fetchone()
        self.assertEqual(event['actor'], 'replenisher')
        self.assertEqual((json.loads(event['before_json'])['point_id'], json.loads(event['after_json'])['point_id']), ('g1-salud', 'g2-deo'))

    def test_moving_is_for_who_measures_and_stays_in_the_store(self):
        reading = self._stored_on_the_wrong_gondola(captured_by='analyst')
        url = f"/api/readings/{reading['id']}/move"
        # viewer and admin do not capture; a replenisher only moves its own measurements
        for user, status in (('viewer', 403), ('admin', 403), ('replenisher', 403), (None, 401)):
            self.assertEqual(self.client(user).post(url, json={'point_id': 'g2-deo'}).status_code, status, user)
        analyst = self.client('analyst')
        for target, status in (('point-b', 409), ('point-c', 403), ('no-such-point', 404), ('g1-salud', 409)):
            self.assertEqual(analyst.post(url, json={'point_id': target}).status_code, status, target)
        self.assertEqual(self.db.get_reading(reading['id'])['point_id'], 'g1-salud')  # refused moves change nothing
        response = analyst.post(url, json={'point_id': 'point-a'})  # any capturable góndola of the same store
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()['point_id'], response.json()['planogram_id']), ('point-a', None))
