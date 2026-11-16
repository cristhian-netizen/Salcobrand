"""The Superusuario sees provider gondola spending, independent of local readings."""
import json
import os
from unittest.mock import patch
import httpx


class UsageCases:
    def usage_client(self, handler):
        import analysis_usage
        factory = httpx.Client
        def create_client(**kwargs):
            client = factory(base_url='https://provider.invalid', transport=httpx.MockTransport(handler))
            self.addCleanup(client.close)
            return client
        env = patch.dict(os.environ, {'NEURAVISION_REMOTE_URL':'https://provider.invalid',
                                     'NEURAVISION_REMOTE_USERNAME':'server-user','NEURAVISION_REMOTE_PASSWORD':'private-usage-password'})
        env.start(); self.addCleanup(env.stop)
        mocked = patch.object(analysis_usage.httpx,'Client',side_effect=create_client)
        mocked.start(); self.addCleanup(mocked.stop)
        return analysis_usage

    def test_usage_permission_matrix_and_validation_before_provider_calls(self):
        import analysis_usage
        with patch.object(analysis_usage,'provider_client') as provider:
            for role in (None,'admin','analyst','replenisher','legacy-supervisor','legacy-tienda'):
                response=self.client(role).get('/api/reports/analysis-usage')
                self.assertEqual(response.status_code,401 if role is None else 403,response.text)
            for params in ({'date_from':'invalid'}, {'date_from':'2026-02-30'},
                           {'date_from':'2026-04-01','date_to':'2026-03-01'},
                           {'date_from':'2016-01-01','date_to':'2026-01-01'}):
                self.assertEqual(self.client('viewer').get('/api/reports/analysis-usage',params=params).status_code,400)
            provider.assert_not_called()
        self.assertEqual(analysis_usage.month_range('2016-01-31','2025-12-31')[2],120)
        self.assertEqual(analysis_usage.month_range('9999-12-01','9999-12-31')[2],1)

    def test_usage_months_sum_only_gondola_decimal_costs_and_preserve_missing(self):
        calls=[]
        def handler(request):
            calls.append((request.method,request.url.path,dict(request.url.params)))
            if request.url.path=='/api/auth/login':
                return httpx.Response(200,json={'ok':True})
            month=request.url.params['date_from'][:7]
            payload={
                '2024-01':{'by_endpoint':[{'endpoint':'vision_gondola','cost_usd':'0.1'},
                                          {'endpoint':'vision_gondola','cost_usd':'0.2'},
                                          {'endpoint':'vision_ocr','cost_usd':'9999'}]},
                '2024-02':{'by_endpoint':None},
                '2024-03':{'by_endpoint':[]},
            }[month]
            return httpx.Response(200,json=payload)
        self.usage_client(handler)
        response=self.client('viewer').get('/api/reports/analysis-usage?date_from=2024-01-31&date_to=2024-03-31&store=L128')
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()
        self.assertEqual(data['months'],[{'month':'2024-01','cost_usd':'0.3'},
                                         {'month':'2024-02','cost_usd':None},{'month':'2024-03','cost_usd':'0'}])
        self.assertEqual(data['total_cost_usd'],'0.3')
        self.assertEqual((data['scope'],data['currency'],data['estimated'],data['known_months']),('organization','USD',True,2))
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertNotIn('private-usage-password',json.dumps(data))
        self.assertEqual(sum(path=='/api/auth/login' for _,path,_ in calls),1)
        summaries=[params for _,path,params in calls if path=='/api/usage/summary']
        self.assertEqual(summaries,[{'date_from':'2024-01-01','date_to':'2024-01-31'},
                                    {'date_from':'2024-02-01','date_to':'2024-02-29'},
                                    {'date_from':'2024-03-01','date_to':'2024-03-31'}])

    def test_usage_invalid_gondola_costs_are_unknown_and_other_services_are_excluded(self):
        import analysis_usage
        for value in (None,'NaN','Infinity','-1','bad',True,'1E+1000000'):
            summary={'by_endpoint':[{'endpoint':'vision_gondola','cost_usd':'1.2'}, {'endpoint':'vision_gondola','cost_usd':value}]}
            self.assertIsNone(analysis_usage.gondola_cost(summary))
        for summary in ({},None,[],{'by_endpoint':{}},{'by_endpoint':[None]}, {'by_endpoint':[{'endpoint':'vision_gondola'}]}):
            self.assertIsNone(analysis_usage.gondola_cost(summary))
        self.assertEqual(analysis_usage.gondola_cost({'by_endpoint':[{'endpoint':'vision_ocr','cost_usd':'-999'}]}),'0')
        self.assertEqual(analysis_usage.gondola_cost({'by_endpoint':[{'endpoint':'vision_gondola','cost_usd':'0.00004'},
                                                                   {'endpoint':'vision_gondola','cost_usd':'0.00004'}]}),'0.00008')

    def test_usage_provider_errors_do_not_become_zero_or_leak_credentials(self):
        status = {'value':404}
        def handler(request):
            if request.url.path=='/api/auth/login':return httpx.Response(200,json={'ok':True})
            return httpx.Response(status['value'],json={'detail':'private-usage-password'})
        self.usage_client(handler)
        for value in (404,401,403,500):
            with self.subTest(status=value):
                status['value'] = value
                response=self.client('viewer').get('/api/reports/analysis-usage?date_from=2026-01-01&date_to=2026-02-01')
                self.assertEqual(response.status_code,503,response.text)
                self.assertNotIn('private-usage-password',response.text)
                self.assertNotIn('months',response.json())

    def test_usage_transport_login_and_bad_json_fail_safely(self):
        mode={'value':'bad_json'}
        def handler(request):
            if request.url.path=='/api/auth/login':
                return httpx.Response(403 if mode['value']=='login' else 200,json={'ok':True})
            if mode['value']=='timeout':
                raise httpx.ReadTimeout('private-usage-password',request=request)
            return httpx.Response(200,text='<html>Unexpected</html>')
        self.usage_client(handler)
        for value,expected in [('bad_json',502),('login',503),('timeout',503)]:
            mode['value']=value
            response=self.client('viewer').get('/api/reports/analysis-usage')
            self.assertEqual(response.status_code,expected,response.text)
            self.assertNotIn('private-usage-password',response.text)
        with patch.dict(os.environ,{'NEURAVISION_REMOTE_PASSWORD':''}):
            self.assertEqual(self.client('viewer').get('/api/reports/analysis-usage').status_code,503)

    def test_usage_missing_information_has_no_total(self):
        def handler(request):
            return httpx.Response(200,json={'ok':True} if request.url.path=='/api/auth/login' else {'by_endpoint':None})
        self.usage_client(handler)
        data=self.client('viewer').get('/api/reports/analysis-usage?date_from=2026-01-01&date_to=2026-02-01').json()
        self.assertEqual(data['known_months'],0)
        self.assertIsNone(data['total_cost_usd'])
        self.assertTrue(all(row['cost_usd'] is None for row in data['months']))
