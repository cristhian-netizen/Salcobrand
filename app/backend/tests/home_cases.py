"""Regression coverage for the original profile-specific home semantics."""
from unittest.mock import patch


class HomeCases:
    def test_review_notifications_include_approval_and_rejection_for_the_author_only(self):
        reviewer = self.client('analyst')
        url = f"/api/readings/{self.own['id']}/review"
        self.assertEqual(reviewer.patch(url, json={'status':'Aprobado','note':'Correcta','version':0}).status_code, 200)
        notification = self.client('replenisher').get('/api/home').json()['notifications']
        self.assertEqual([(row['id'], row['status'], row['note'], row['reviewed_by']) for row in notification],
                         [(self.own['id'], 'Aprobado', 'Correcta', 'analyst')])
        self.assertTrue(notification[0]['reviewed_at'])
        self.assertEqual(reviewer.patch(url, json={'status':'Rechazado','note':'Repetir foto','version':1}).status_code, 200)
        self.assertEqual(self.client('replenisher').get('/api/home').json()['notifications'][0]['status'], 'Rechazado')
        self.assertEqual(self.client('analyst').get('/api/home').json()['notifications'], [])
        with self.db.get_conn() as conn:
            conn.execute("UPDATE users SET store_ids_json='[]',store_id=NULL WHERE username='analyst'")
        self.assertEqual(reviewer.patch(url, json={'status':'Aprobado','note':'','version':2}).status_code, 403)
        self.assertEqual(reviewer.get('/api/dashboard').json()['options'], [])
        self.assertEqual(reviewer.get('/api/measurements').json()['count'], 0)

    def test_home_requires_session_and_admin_has_management_home(self):
        self.assertEqual(self.client(None).get('/api/home').status_code, 401)
        self.assertEqual(self.client('admin').get('/api/home').json(), {'profile': 'admin'})

    def test_home_analyst_counts_own_history_and_all_accessible_pending(self):
        older = self.db.add_reading('point-b', self.analysis, ['point-b/older.jpg'], captured_by='analyst')
        with self.db.get_conn() as conn:
            conn.execute("UPDATE readings SET created_at = '2020-01-01T15:35:00+00:00' WHERE id = ?", (older['id'],))
        result = self.client('analyst').get('/api/home').json()
        self.assertEqual(result['totals'], {'own': 2, 'rejected': 0, 'pending': 3})
        self.assertEqual({row['id'] for row in result['pending']}, {self.own['id'], self.other['id'], older['id']})
        self.assertEqual([row['id'] for row in result['recent']], [self.other['id'], older['id']])
        self.assertNotIn(self.foreign['id'], [row['id'] for row in result['recent']])

    def test_home_rejections_are_own_and_update_after_review(self):
        reviewer = self.client('analyst')
        for reading in (self.own, self.other):
            response = reviewer.patch(f"/api/readings/{reading['id']}/review", json={
                'status': 'Rechazado', 'note': 'Foto borrosa', 'version': 0})
            self.assertEqual(response.status_code, 200)
        result = self.client('replenisher').get('/api/home').json()
        self.assertEqual(result['totals'], {'own': 1, 'rejected': 1, 'pending': 0})
        self.assertEqual([row['id'] for row in result['rejected']], [self.own['id']])
        self.assertEqual(result['rejected'][0]['note'], 'Foto borrosa')
        self.assertEqual(result['pending'], [])
        self.assertEqual([row['id'] for row in self.client('analyst').get('/api/home').json()['rejected']], [self.other['id']])
        reviewer.patch(f"/api/readings/{self.own['id']}/review", json={
            'status': 'En revisión', 'note': '', 'version': 1})
        refreshed = self.client('replenisher').get('/api/home').json()
        self.assertEqual(refreshed['totals'], {'own': 1, 'rejected': 0, 'pending': 1})

    def test_home_viewer_ranks_approved_only_and_preserves_rejected_followup(self):
        import measurement_reports
        measurement_reports.save_review(self.own['id'], 'Aprobado', '', 0, 'analyst')
        measurement_reports.save_review(self.other['id'], 'Rechazado', 'Repetir foto', 0, 'analyst')
        # Same PDV also has an extreme rejected score and an unreviewed score.
        with patch.object(measurement_reports.db, 'compute_shelf_standards', return_value={'overall_score': 35}):
            result = self.client('viewer').get('/api/home').json()
        self.assertEqual([store['code'] for store in result['attention']], ['L128'])
        self.assertEqual(result['attention'][0]['score'], 35)
        self.assertEqual(result['attention'][0]['score_band'], 'bad')
        self.assertEqual([row['id'] for row in result['rejected']], [self.other['id']])
        self.assertEqual(result['rejected'][0]['note'], 'Repetir foto')
        self.assertEqual(self.client('viewer').patch(f"/api/readings/{self.other['id']}/review", json={
            'status': 'Aprobado', 'note': '', 'version': 1}).status_code, 403)

    def test_home_recent_limits_do_not_truncate_counts_and_empty_assignments(self):
        for index in range(10):
            self.db.add_reading('point-b', self.analysis, [f'point-b/{index}.jpg'], captured_by='analyst')
        result = self.client('analyst').get('/api/home').json()
        self.assertEqual(result['totals']['own'], 11)
        self.assertEqual(result['totals']['pending'], 12)
        self.assertEqual(len(result['recent']), 8)
        self.assertEqual(len(result['pending']), 8)
        with self.db.get_conn() as conn:
            conn.execute("UPDATE users SET store_ids_json = '[]', store_id = NULL WHERE username = 'replenisher'")
        result = self.client('replenisher').get('/api/home').json()
        self.assertEqual(result['totals'], {'own': 0, 'rejected': 0, 'pending': 0})
        self.assertEqual(result['recent'], [])
