"""Configuration is authorized, versioned and consumed by actual master-data entry points."""
import copy
from concurrent.futures import ThreadPoolExecutor
import io
from openpyxl import Workbook


class SettingsCases:
    def configuration(self):
        return self.client('admin').get('/api/admin/settings').json()

    def configure(self, section, value, version=None, username='admin'):
        if version is None:
            version = self.configuration()['version']
        return self.client(username).patch('/api/admin/settings/' + section, json={'value': value, 'version': version})

    def classification(self):
        state = self.configuration()['state']
        return {**state['catalog'], 'ownBrands': state['productParameters']['ownBrands']}

    def test_configuration_is_admin_only(self):
        for user in (None, 'replenisher', 'analyst', 'viewer'):
            expected = 401 if user is None else 403
            self.assertEqual(self.client(user).get('/api/admin/settings').status_code, expected)
            self.assertEqual(self.configure('score', {'redMax': 40, 'yellowMax': 80}, username=user).status_code, expected)
            self.assertEqual(self.client(user).get('/api/display-settings').status_code, 401 if user is None else 200)

    def test_configured_pdv_type_is_usable_and_protected_when_referenced(self):
        initial = self.configuration()
        response = self.configure('pdv-types', initial['state']['pdvTypes'] + ['Farmacia comunitaria'])
        self.assertEqual(response.status_code, 200, response.text)
        admin = self.client('admin')
        self.assertIn('Farmacia comunitaria', admin.get('/api/admin/location-catalog').json()['store_types'])
        created = admin.post('/api/admin/stores', json={**self.store_payload(), 'store_type': 'Farmacia comunitaria'})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(self.configure('pdv-types', initial['state']['pdvTypes']).status_code, 409)
        self.assertEqual(self.configure('pdv-types', ['Farmacia', 'Ｆａｒｍａｃｉａ']).status_code, 400)

    def test_classification_reaches_product_forms_api_and_excel_preview(self):
        self.create_product()
        value = self.classification()
        value['brands'].append('Nueva marca')
        value['categories']['Nueva categoría'] = ['Nueva subcategoría']
        value['brandClassifications']['Nueva marca'] = {'category':'Nueva categoría','subcategory':'Nueva subcategoría'}
        value['ownBrands'] = ['Nueva marca']
        response = self.configure('catalog', value)
        self.assertEqual(response.status_code, 200, response.text)
        catalog = self.client('admin').get('/api/admin/catalog').json()['classification']
        self.assertEqual(catalog['ownBrands'], ['Nueva marca'])
        valid = {**self.product_fields('NEW'), 'subBrand': 'Nueva marca', 'category': 'Nueva categoría', 'subcategory': 'Nueva subcategoría'}
        self.assertEqual(self.client('admin').post('/api/admin/catalog/products', json=valid).status_code, 201)
        invalid = {**valid, 'sku': 'BAD', 'subcategory':'Subcategoría no configurada'}
        self.assertEqual(self.client('admin').post('/api/admin/catalog/products', json=invalid).status_code, 400)
        import catalog_excel
        book = Workbook();sheet = book.active;sheet.title = 'Productos';sheet.append(catalog_excel.COLUMNS)
        sheet.append([invalid.get(field, '') for field in catalog_excel.FIELDS])
        output = io.BytesIO();book.save(output)
        preview = self.client('admin').post('/api/admin/catalog/products/import', files={'file': ('bad.xlsx', output.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()['errors'])
        self.assertIn('configuradas', preview.json()['errors'][0]['message'])

    def test_used_classifications_are_protected_and_exclusivity_is_removed(self):
        self.create_product()
        current = self.classification()
        for key, replacement in [('brands', ['Otra']), ('categories', {'Otra': ['Otra']})]:
            value = {**current, key: replacement}
            self.assertEqual(self.configure('catalog', value).status_code, 409)
        invalid = copy.deepcopy(current);invalid['brands'].append('marca qa')
        self.assertEqual(self.configure('catalog', invalid).status_code, 400)
        invalid = copy.deepcopy(current);invalid['brands'].append('Otra');invalid['exclusive']['Cuidado personal'] = 'Otra'
        invalid['brandClassifications']['Otra'] = {'category':'Cuidado personal','subcategory':'Desodorantes'}
        response=self.configure('catalog', invalid)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['state']['catalog']['exclusive'],{})

    def test_settings_concurrency_persistence_and_section_preservation(self):
        initial = self.configuration()
        def write(red):
            return self.configure('score', {'redMax': red, 'yellowMax': 80}, version=initial['version'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(write, [30, 40]))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        saved = self.configuration()
        margin = self.configure('product', {'dimensionMarginPct': 25})
        self.assertEqual(margin.status_code, 200)
        self.assertEqual(margin.json()['state']['scoreParameters'], saved['state']['scoreParameters'])
        self.db.init_db()
        again = self.configuration()
        self.assertEqual(again['state']['productParameters']['dimensionMarginPct'], 25)
        self.assertEqual(again['updated_by'], 'admin')
        self.assertEqual(self.configure('score', {'redMax': 90, 'yellowMax': 80}).status_code, 400)
        self.assertEqual(self.configure('product', {'dimensionMarginPct': True}).status_code, 400)

    def test_score_colors_change_without_changing_scores_or_approval(self):
        before = self.db.get_reading(self.own['id'])
        self.assertEqual(self.configure('score', {'redMax': 97, 'yellowMax': 98}).status_code, 200)
        after = self.db.get_reading(self.own['id'])
        self.assertEqual(after['standards']['overall_score'], before['standards']['overall_score'])
        self.assertEqual(after['standards']['score_band'], 'bad')
        self.assertEqual(after['review'], before['review'])
        rows = self.client('analyst').get('/api/reports/measurements').json()['rows']
        self.assertTrue(all(row['score_band'] == 'bad' for row in rows))
        kpis = self.configuration()['state']['kpiParameters']
        kpis['coverage'].update(warn=0, good=0)
        self.assertEqual(self.configure('kpi', kpis).status_code, 200)
        summary = self.client('analyst').get('/api/summary').json()
        self.assertEqual(summary['indicators']['coverage']['band'], 'ok')
        self.assertEqual(summary['totals']['approved_readings_in_period'], 0)

    def test_dimension_margin_uses_captured_geometry_and_keeps_capacity_theoretical(self):
        product = self.create_product()
        analysis = {**self.analysis, 'products': [{'product': product['name'], 'brand': product['subBrand'],
                    'facings': 2, 'shelf_level': 1, 'position_index': 1}]}
        reading = self.db.add_reading('point-a', analysis, [], capture_context={'depths': [30]})
        self.configure('product', {'dimensionMarginPct': 0})
        first = self.db.get_reading(reading['id'])
        self.assertTrue(first['capacity']['maximumOnly'])
        self.assertEqual(first['capacity']['products'][0]['maximumUnits'], 20)
        self.configure('product', {'dimensionMarginPct': 50})
        second = self.db.get_reading(reading['id'])
        self.assertEqual(second['capacity']['products'][0]['maximumUnits'], 12)
        self.assertEqual(first['products'], second['products'])
        self.assertEqual(first['standards']['overall_score'], second['standards']['overall_score'])

    def test_score_breakdown_normalizes_missing_components_and_keeps_zero(self):
        products=[{'shelf_level':1,'category':'A','facings':10},{'shelf_level':2,'category':'B','facings':15}]
        score=self.db.compute_shelf_standards(products,30)
        self.assertEqual(score['overall_score'],81)
        detail=score['breakdown'];self.assertEqual(detail['unrounded_score'],81.25)
        self.assertEqual(detail['weighted_sum'],65)
        self.assertEqual(detail['available_weight_pct'],80)
        rows={r['key']:r for r in detail['components']}
        self.assertEqual(rows['stock']['effective_weight_pct'],43.75)
        self.assertEqual(rows['space']['contribution'],12.5)
        self.assertIsNone(rows['price']['score']);self.assertIsNone(rows['price']['contribution'])
        self.assertEqual(rows['price']['effective_weight_pct'],0)
        self.assertEqual(rows['organization']['inputs']['dominant_faces'],25)
        self.assertEqual(sum(r['contribution'] or 0 for r in rows.values()),81.25)
        for p in products:p['price_tag_visible']=False
        zero=self.db.compute_shelf_standards(products,30)
        self.assertEqual(zero['overall_score'],65)
        self.assertEqual(zero['breakdown']['available_weight_pct'],100)
        price=next(r for r in zero['breakdown']['components'] if r['key']=='price')
        self.assertEqual(price['score'],0);self.assertEqual(price['effective_weight_pct'],20)
        self.assertEqual(price['inputs'],{'visible':0,'evaluated':2})

    def test_score_breakdown_handles_no_data_partial_data_and_weighted_levels(self):
        empty=self.db.compute_shelf_standards([],None)
        self.assertIsNone(empty['overall_score']);self.assertIsNone(empty['breakdown']['unrounded_score'])
        self.assertEqual(empty['breakdown']['available_weight_pct'],0)
        self.assertTrue(all(r['contribution'] is None for r in empty['breakdown']['components']))
        partial=self.db.compute_shelf_standards([{}],None)
        self.assertEqual(partial['overall_score'],100)
        self.assertEqual(partial['breakdown']['available_weight_pct'],35)
        self.assertEqual(partial['breakdown']['components'][0]['effective_weight_pct'],100)
        products=[{'shelf_level':1,'category':'A','facings':3},{'shelf_level':1,'category':'B','facings':1},
                  {'shelf_level':2,'category':'A','facings':1},{'shelf_level':2,'category':'B','facings':1}]
        score=self.db.compute_shelf_standards(products,150)
        self.assertEqual(score['space_score'],0)
        self.assertEqual(score['organization_score'],67)
        row=next(r for r in score['breakdown']['components'] if r['key']=='organization')
        self.assertEqual(row['inputs']['dominant_faces'],4);self.assertEqual(row['inputs']['faces'],6)
        self.assertEqual(len(row['inputs']['levels']),2)
