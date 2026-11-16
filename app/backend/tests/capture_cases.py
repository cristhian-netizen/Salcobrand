"""Capture regressions: duplicate submissions, scope, recovery and actual image decoding."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import httpx
from PIL import Image
from starlette.datastructures import UploadFile


class CaptureCases:
    def capture(self, client, key="capture-request-001", point="point-a"):
        return client.post('/api/points/'+point+'/analysis-jobs', headers={'Idempotency-Key':key},
                           files={'images':('photo.jpg',b'synthetic','image/jpeg')})

    def test_capture_permissions_and_job_ownership(self):
        for role in (None,'admin','viewer'):
            self.assertEqual(self.capture(self.client(role)).status_code,401 if role is None else 403)
        first=self.capture(self.client('analyst')).json()
        second=self.capture(self.client('replenisher')).json()
        self.assertNotEqual(first['job_id'],second['job_id'])
        self.assertEqual(self.client('replenisher').get('/api/analysis-jobs/'+first['job_id']).status_code,404)
        self.assertEqual(self.client('viewer').get('/api/analysis-jobs/'+first['job_id']).status_code,404)
        self.assertEqual(self.client('admin').get('/api/analysis-jobs/'+first['job_id']).status_code,200)
        self.assertEqual(self.capture(self.client('replenisher'),point='point-c').status_code,403)
        self.assertEqual([j['job_id'] for j in self.client('replenisher').get('/api/analysis-jobs').json()],[second['job_id']])

    def test_capture_retries_keep_one_job_and_reject_changed_photos(self):
        client=self.client('analyst')
        first=self.capture(client);second=self.capture(client)
        self.assertEqual(first.status_code,202,first.text)
        self.assertEqual(first.json()['job_id'],second.json()['job_id'])
        self.assertEqual(self.jobs._dispatch.call_count,1)
        self.core.read_image_uploads.return_value=[(b'different','image/jpeg')]
        self.assertEqual(self.capture(client).status_code,409)
        self.assertEqual(self.jobs._dispatch.call_count,1)
        found=client.get('/api/analysis-requests/capture-request-001').json()
        self.assertEqual(found['job_id'],first.json()['job_id'])

    def test_concurrent_capture_retries_dispatch_once(self):
        clients=[self.client('analyst'),self.client('analyst')]
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(self.capture,clients))
        self.assertTrue(all(r.status_code==202 for r in responses),[r.text for r in responses])
        self.assertEqual(responses[0].json()['job_id'],responses[1].json()['job_id'])
        self.assertEqual(self.jobs._dispatch.call_count,1)
        with self.db.get_conn() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM management_capture_requests').fetchone()['n'],1)

    def test_completed_capture_and_remote_recovery(self):
        client=self.client('replenisher');job=self.capture(client).json()
        self.db.finish_job(job['job_id'],'done',reading_id=self.own['id'])
        done=client.get('/api/analysis-jobs/'+job['job_id']).json()
        self.assertEqual(done['reading']['id'],self.own['id'])
        self.assertNotIn('payload',done)
        other=self.capture(client,key='capture-request-recovery').json()
        with self.db.get_conn() as conn:
            row=conn.execute('SELECT payload_json FROM api_jobs WHERE job_id=?',(other['job_id'],)).fetchone()
            payload=json.loads(row['payload_json']);payload['remote_submitted']=True
            conn.execute('UPDATE api_jobs SET payload_json=? WHERE job_id=?',(json.dumps(payload),other['job_id']))
        self.db.finish_job(other['job_id'],'failed',error='engine_error: ValueError: Respuesta interrumpida')
        failed=client.get('/api/analysis-jobs/'+other['job_id']).json()
        self.assertTrue(failed['can_recover'])
        resumed=client.post('/api/analysis-jobs/'+other['job_id']+'/resume')
        self.assertEqual(resumed.status_code,202,resumed.text)
        self.assertEqual(resumed.json()['status'],'queued')
        self.assertEqual(client.post('/api/analysis-jobs/'+other['job_id']+'/resume').status_code,409)

    def test_expired_capture_key_does_not_create_another_analysis(self):
        client=self.client('analyst');job=self.capture(client).json()
        with self.db.get_conn() as conn:
            conn.execute('DELETE FROM api_jobs WHERE job_id=?',(job['job_id'],))
        self.assertEqual(self.capture(client).status_code,410)
        self.assertEqual(self.jobs._dispatch.call_count,1)

    def test_remote_capture_waits_for_pending_or_ambiguous_result(self):
        client=self.client('analyst')
        with patch.object(self.core,'remote_enabled',return_value=True,create=True):
            job=self.capture(client).json()
            self.assertEqual(self.capture(client,key='another-capture-request').status_code,409)
            with self.db.get_conn() as conn:
                row=conn.execute('SELECT payload_json FROM api_jobs WHERE job_id=?',(job['job_id'],)).fetchone()
                payload=json.loads(row['payload_json']);payload['remote_submitted']=True
                conn.execute('UPDATE api_jobs SET payload_json=? WHERE job_id=?',(json.dumps(payload),job['job_id']))
            self.db.finish_job(job['job_id'],'failed',error='Interrupted response')
            self.assertEqual(self.capture(client,key='another-capture-request').status_code,409)
            self.db.finish_job(job['job_id'],'done',reading_id=self.own['id'])
            self.assertEqual(self.capture(client,key='another-capture-request').status_code,202)

    def test_real_image_validation_orientation_and_limits(self):
        location=Path(__file__).resolve().parents[1]/'core.py'
        spec=importlib.util.spec_from_file_location('_capture_real_core',location)
        real=importlib.util.module_from_spec(spec);spec.loader.exec_module(real)
        buffer=io.BytesIO();photo=Image.new('RGB',(20,40),'white');exif=photo.getexif();exif[274]=6
        photo.save(buffer,'JPEG',exif=exif)
        upload=UploadFile(io.BytesIO(buffer.getvalue()),filename='rotated.jpg',headers={'content-type':'image/jpeg'})
        # Starlette accepts a Headers instance for content_type.
        from starlette.datastructures import Headers
        upload.headers=Headers({'content-type':'image/jpeg'})
        images=asyncio.run(real.read_image_uploads([upload],max_bytes_each=100000,max_bytes_total=100000))
        with Image.open(io.BytesIO(images[0][0])) as normalized:
            self.assertEqual(normalized.size,(40,20))
        invalid=UploadFile(io.BytesIO(b'<svg>bad</svg>'),filename='bad.jpg',headers=Headers({'content-type':'image/jpeg'}))
        with self.assertRaises(ValueError):
            asyncio.run(real.read_image_uploads([invalid]))
        with self.assertRaises(ValueError):
            asyncio.run(real.read_image_uploads([upload]*7))

    def test_remote_adapter_recovers_interrupted_response_without_resubmitting(self):
        import remote_model
        calls=[];posted=False;temporary_failure=False
        remote_reading={'id':101,'point_id':'REMOTE-QA','products':[{'product':'Real contract sample','facings':2}],
                        'total_facings':2,'shelf_levels_detected':1,'empty_space_pct':3,'categories':[],'notes':'','engine':{'images':[]}}
        def handler(request):
            nonlocal posted,temporary_failure
            calls.append((request.method,request.url.path))
            if request.url.path=='/api/auth/login':
                return httpx.Response(200,json={'username':'service'})
            if request.method=='POST' and request.url.path.endswith('/analyze'):
                posted=True
                raise httpx.ReadTimeout('interrupted',request=request)
            if posted and not temporary_failure:
                temporary_failure=True
                return httpx.Response(503,json={'detail':'Temporary interruption'})
            return httpx.Response(200,json={'id':'REMOTE-QA','readings':[remote_reading] if posted else []})
        transport=httpx.MockTransport(handler)
        client=httpx.Client(base_url='https://model.example',transport=transport)
        self.db.create_job('remote-adapter','app','point-a',{'user':'analyst'})
        env={'NEURAVISION_REMOTE_URL':'https://model.example','NEURAVISION_REMOTE_USERNAME':'service',
             'NEURAVISION_REMOTE_PASSWORD':'private-test-password','NEURAVISION_REMOTE_POINT_MAP':'{"point-a":"REMOTE-QA"}'}
        with patch.dict(os.environ,env),patch.object(remote_model.httpx,'Client',return_value=client):
            analysis=remote_model.analyze('point-a',[(b'photo','image/jpeg')],job_id='remote-adapter')
        self.assertEqual(sum(method=='POST' and path.endswith('/analyze') for method,path in calls),1)
        self.assertEqual(analysis['engine']['remote']['reading_id'],101)
        self.assertNotIn('private-test-password',json.dumps(analysis))
        self.assertTrue(self.db.get_job('remote-adapter')['payload']['remote_submitted'])

    def test_remote_plan_reference_is_versioned_before_upload(self):
        import remote_model
        product=self.create_product();plan=self.save_plan(product)
        snapshot=self.db.get_planogram(plan['id'])
        calls=[]
        def handler(request):
            calls.append((request.method,request.url.path))
            if request.url.path=='/api/auth/login':
                return httpx.Response(200,json={'username':'service'})
            if request.method=='GET' and request.url.path.startswith('/api/planograms/'):
                return httpx.Response(404)
            if request.url.path=='/api/admin/planograms':
                submitted=json.loads(request.content)
                self.assertTrue(submitted['id'].startswith('MIGLOCAL-PG-'))
                self.assertEqual(submitted['items'][0]['title'],product['name'])
                self.assertNotIn('photo',submitted)
                return httpx.Response(201,json={'id':submitted['id']})
            if request.method=='PUT':
                return httpx.Response(200,json={'ok':True})
            if request.method=='POST' and request.url.path.endswith('/analyze'):
                return httpx.Response(200,json={'id':1,'point_id':'REMOTE-QA','products':[],'engine':{}})
            return httpx.Response(200,json={'id':'REMOTE-QA','planogram_id':None,'readings':[]})
        client=httpx.Client(base_url='https://model.example',transport=httpx.MockTransport(handler))
        env={'NEURAVISION_REMOTE_URL':'https://model.example','NEURAVISION_REMOTE_USERNAME':'service',
             'NEURAVISION_REMOTE_PASSWORD':'private-test-password','NEURAVISION_REMOTE_POINT_MAP':'{"point-a":"REMOTE-QA"}'}
        with patch.dict(os.environ,env),patch.object(remote_model.httpx,'Client',return_value=client):
            remote_model.analyze('point-a',[(b'photo','image/jpeg')],plan_snapshot=snapshot)
        assigned=next(index for index,(method,_) in enumerate(calls) if method=='PUT')
        uploaded=next(index for index,(method,path) in enumerate(calls) if method=='POST' and path.endswith('/analyze'))
        self.assertLess(assigned,uploaded)
