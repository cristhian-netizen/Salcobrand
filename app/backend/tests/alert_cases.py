from concurrent.futures import ThreadPoolExecutor
import json


class AlertCases:
    def alert_for(self, reading_id, kind='empty-space', client=None, status=''):
        client = client or self.client('analyst')
        response = client.get('/api/alerts', params={'status':status})
        self.assertEqual(response.status_code, 200, response.text)
        return next(item for item in response.json()['findings'] if item['reading']['id'] == reading_id and item['kind'] == kind)

    @staticmethod
    def alert_payload(item, status='Resuelta'):
        return {'status':status, 'fingerprint':item['fingerprint'], 'version':item['version']}

    def test_alerts_read_permissions_author_and_store_scope(self):
        self.assertEqual(self.client(None).get('/api/alerts').status_code, 401)
        expected = {'admin':0, 'viewer':3, 'analyst':2, 'replenisher':1}
        for role, count in expected.items():
            result = self.client(role).get('/api/alerts')
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(len(result.json()['findings']), count)
        self.assertEqual(self.client('analyst').get('/api/alerts?point=point-c').status_code, 403)
        self.assertEqual(self.client('replenisher').get('/api/alerts?store=L130').status_code, 403)
        with self.db.get_conn() as conn:
            conn.execute("UPDATE users SET store_ids_json='[]',store_id=NULL WHERE username='replenisher'")
        data = self.client('replenisher').get('/api/alerts').json()
        self.assertEqual(data['findings'], [])
        self.assertEqual(data['suppliers'], [])

    def test_alert_resolve_and_reopen_are_analyst_only_persisted_and_do_not_change_review(self):
        item = self.alert_for(self.other['id'])
        url = f"/api/alerts/readings/{self.other['id']}/empty-space"
        for role in ('admin','viewer','replenisher'):
            self.assertEqual(self.client(role).patch(url, json=self.alert_payload(item)).status_code, 403)
        before = self.db.measurement_review(self.other['id'])
        response = self.client('analyst').patch(url, json=self.alert_payload(item))
        self.assertEqual(response.status_code, 200, response.text)
        resolved = self.alert_for(self.other['id'], status='Resuelta')
        self.assertEqual((resolved['status'],resolved['version'],resolved['updated_by']), ('Resuelta',1,'analyst'))
        reopened = self.client('analyst').patch(url, json=self.alert_payload(resolved,'Pendiente'))
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(self.alert_for(self.other['id'])['version'], 2)
        self.assertEqual(self.db.measurement_review(self.other['id']), before)
        with self.db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM management_events WHERE action='alert.status'").fetchone()['n'],2)
        self.assertEqual(self.client('analyst').patch(url,json={**self.alert_payload(resolved),'owner':'another'}).status_code,422)

    def test_alert_kinds_unknown_price_priority_and_stable_identity_after_changes(self):
        products = [{'product':'Precio desconocido'}, {'product':'Ausente','price_clp':None,'out_of_stock':True}]
        with self.db.get_conn() as conn:
            conn.execute('UPDATE readings SET products_json=?,capture_context_json=? WHERE id=?',
                         (json.dumps(products),json.dumps({'planogramAlert':{'message':'Revisar referencia','severity':'warning'}}),self.other['id']))
        data = self.client('analyst').get('/api/alerts?point=point-a&status=').json()
        items = [item for item in data['findings'] if item['reading']['id']==self.other['id']]
        self.assertEqual([item['kind'] for item in items],['planogram','empty-space','no-price','absent'])
        self.assertEqual([item['priority'] for item in items],['Alta','Media','Media','Media'])
        self.assertEqual(items[2]['title'],'1 posiciones sin precio visible')
        self.assertTrue(all(item['owner']=='Sin asignar' for item in items))
        url=f"/api/alerts/readings/{self.other['id']}/no-price"
        self.client('analyst').patch(url,json=self.alert_payload(items[2]))
        with self.db.get_conn() as conn:
            conn.execute("UPDATE readings SET empty_space_pct=0,capture_context_json=NULL WHERE id=?",(self.other['id'],))
        self.assertEqual(self.alert_for(self.other['id'],'no-price')['status'],'Resuelta')
        products[1]['product']='Otro producto ausente'
        with self.db.get_conn() as conn:
            conn.execute('UPDATE readings SET products_json=? WHERE id=?',(json.dumps(products),self.other['id']))
        self.assertEqual(self.client('analyst').patch(url,json=self.alert_payload(items[2])).status_code,409)
        changed=self.alert_for(self.other['id'],'no-price')
        self.assertEqual((changed['status'],changed['version']),('Pendiente',1))
        self.assertEqual(self.client('analyst').patch(url,json=self.alert_payload(changed)).status_code,200)

    def test_alert_concurrent_edits_and_missing_evidence_reject_stale_payloads(self):
        item=self.alert_for(self.other['id'])
        url=f"/api/alerts/readings/{self.other['id']}/empty-space"
        clients=[self.client('analyst'),self.client('analyst')]
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(lambda client:client.patch(url,json=self.alert_payload(item)).status_code,clients))
        self.assertEqual(sorted(statuses),[200,409])
        with self.db.get_conn() as conn:
            conn.execute('UPDATE readings SET empty_space_pct=0 WHERE id=?',(self.other['id'],))
        self.assertEqual(self.client('analyst').patch(url,json=self.alert_payload(item)).status_code,409)

    def test_alert_rejections_follow_profiles_dates_and_reviewer(self):
        analyst=self.client('analyst')
        for reading in (self.own,self.other):
            analyst.patch(f"/api/readings/{reading['id']}/review",json={'status':'Rechazado','note':'Foto borrosa','version':0})
        data=analyst.get('/api/alerts').json()
        self.assertEqual([row['id'] for row in data['own_rejected']],[self.other['id']])
        self.assertEqual([row['id'] for row in data['other_rejected']],[self.own['id']])
        self.assertEqual(data['own_rejected'][0]['reviewed_by'],'analyst')
        own=self.client('replenisher').get('/api/alerts').json()
        self.assertEqual([row['id'] for row in own['rejected']],[self.own['id']])
        self.assertEqual(own['other_rejected'],[])
        with self.db.get_conn() as conn:
            conn.execute("UPDATE readings SET created_at='2026-11-01T02:30:00+00:00' WHERE id=?",(self.own['id'],))
        filtered=self.client('replenisher').get('/api/alerts?from=2026-11-01').json()
        self.assertEqual(filtered['findings'],[])
        self.assertEqual(filtered['rejected'],[])
        self.assertEqual(analyst.get('/api/alerts?from=2026-12-01&to=2026-11-01').status_code,400)
        self.assertEqual(analyst.get('/api/alerts?status=Unknown').status_code,400)

    def test_alerts_preserve_approved_gaps_supplier_resolution_and_delete_cleanup(self):
        payload,_,_=self.detail_fixture()
        analyst=self.client('analyst')
        analyst.patch(f"/api/readings/{self.other['id']}/review",json={'status':'Aprobado','note':'','version':0})
        response=analyst.post('/api/points/point-a/supplier-stockouts',json={'product_title':'Proveedor QA','planogram_item_id':1,'note':'Sin despacho'})
        self.assertEqual(response.status_code,200,response.text)
        supplier=response.json()
        data=analyst.get('/api/alerts?point=point-a').json()
        self.assertEqual(len(data['gaps']),1)
        self.assertEqual([row['id'] for row in data['suppliers']],[supplier['id']])
        self.assertEqual(self.client('replenisher').get('/api/alerts').json()['suppliers'],[])
        analyst.post(f"/api/supplier-stockouts/{supplier['id']}/resolve")
        self.assertEqual(analyst.get('/api/alerts').json()['suppliers'],[])
        item=self.alert_for(self.other['id'])
        analyst.patch(f"/api/alerts/readings/{self.other['id']}/empty-space",json=self.alert_payload(item))
        self.db.delete_reading(self.other['id'])
        with self.db.get_conn() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM management_reading_alerts').fetchone()['n'],0)
