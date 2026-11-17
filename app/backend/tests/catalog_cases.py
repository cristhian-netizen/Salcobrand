import base64
import io
import json
from PIL import Image
from openpyxl import Workbook, load_workbook
from pypdf import PdfWriter


class CatalogCases:
    def multi_classification(self):
        import settings_service
        current = settings_service.read()
        catalog = current['state']['catalog']
        categories = {**catalog['categories'], 'Cuidado personal':['Desodorantes','Higiene'], 'Salud sexual':['Preservativos']}
        settings_service.save('catalog', {**catalog,'categories':categories,'ownBrands':current['state']['productParameters']['ownBrands']}, current['version'], 'admin')
        return {'category':'Cuidado personal','subcategories':['Desodorantes','Higiene']}

    def test_planogram_multiple_subcategories_validation_roundtrip_and_history(self):
        product = self.create_product();classification = self.multi_classification()
        admin = self.client('admin');admin.get('/api/admin/stores')
        body = {**self.plan_fields(product), **classification}
        response = admin.post('/api/admin/catalog/planograms',json=body)
        self.assertEqual(response.status_code,201,response.text)
        plan = response.json();path='/api/admin/catalog/planograms/'+plan['id']
        self.assertEqual(admin.get(path).json()['subcategories'],classification['subcategories'])
        self.db.set_point_planogram('point-a',plan['id'])
        reading = self.db.add_reading('point-a',self.analysis,[],planogram_id=plan['id'])
        for bad in (['Preservativos'],['Higiene','Higiene'],[]):
            self.assertEqual(admin.patch(path,json={**body,'version':1,'subcategories':bad}).status_code,400)
        updated = admin.patch(path,json={**body,'version':1,'subcategories':['Higiene']})
        self.assertEqual(updated.status_code,200,updated.text)
        self.assertEqual(self.db.reading_planogram_snapshot(reading['id'])['subcategories'],classification['subcategories'])
        # An older client omitting classification must preserve the saved selection.
        old_client = {**self.plan_fields(product),'version':2}
        self.assertEqual(admin.patch(path,json=old_client).json()['subcategories'],['Higiene'])
        self.assertEqual(admin.patch(path,json={**body,'version':1}).status_code,409)
        self.assertEqual(self.client('replenisher').post('/api/admin/catalog/planograms',json=body).status_code,403)

    def test_imported_planogram_keeps_product_numbering_multiple_faces_and_prices(self):
        admin = self.client('admin')
        first = self.create_product(sku='PILOT-1')
        second = self.create_product(sku='PILOT-2', name='Otro producto')
        admin.get('/api/admin/stores')
        payload = {'name': 'Planograma real por producto', 'bands': 1, 'items': [
            {'title': first['name'], 'internal_code': first['sku'], 'band': 1, 'position_in_section': 1, 'expected_facings': 2, 'price_clp': 0, 'price_source': 'manual'},
            {'title': second['name'], 'internal_code': second['sku'], 'band': 1, 'position_in_section': 2, 'expected_facings': 1, 'price_clp': 2990, 'price_source': 'manual'}]}
        response = admin.post('/api/admin/planograms/import-json', files={'file': ('plan.json', json.dumps(payload).encode(), 'application/json')}, data={'planogram_id': 'pilot-numbering'})
        self.assertEqual(response.status_code, 200, response.text)
        before = admin.get('/api/admin/catalog/planograms/pilot-numbering').json()
        self.assertEqual(before['position_mode'], 'products')
        self.assertEqual([i['price_clp'] for i in before['items']], [0, 2990])
        body = {**self.plan_fields(first), 'position_mode': 'products', 'positionRows': before['positionRows'], 'version': 0}
        response = admin.patch('/api/admin/catalog/planograms/pilot-numbering', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        after = response.json()
        self.assertEqual([(i['position_in_section'], i['expected_facings']) for i in after['items']], [(1, 2), (2, 1)])
        self.assertEqual([i['price_clp'] for i in after['items']], [0, 2990])
        self.assertEqual(after['position_mode'], 'products')

    def product_fields(self, sku="000123", name="Producto QA"):
        return dict(sku=sku, name=name, subBrand="Marca QA", category="Cuidado personal", subcategory="Desodorantes",
                    saleUnit="ml", productType="Envasado", quantity=150, height=15, width=4, thickness=3,
                    price=4990, barcode="000789")

    def create_product(self, **overrides):
        body={**self.product_fields(), **overrides}
        response=self.client("admin").post('/api/admin/catalog/products',json=body)
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def plan_fields(self, product, **overrides):
        image=io.BytesIO();Image.new('RGB',(20,20),'white').save(image,format='PNG')
        return dict(name="Planograma QA",store_code="L128",status="Activo",description="Prueba",
                    photo="data:image/png;base64,"+base64.b64encode(image.getvalue()).decode(),
                    positionRows=[dict(level=1,position=1,faces=2,productId=product['id'],sku=product['sku'],barcode=product['barcode'])],**overrides)

    def save_plan(self, product):
        admin=self.client('admin');admin.get('/api/admin/stores')
        response=admin.post('/api/admin/catalog/planograms',json=self.plan_fields(product))
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def test_catalog_permissions_cover_writes_and_excel(self):
        for role in (None,'analyst','replenisher','viewer'):
            client=self.client(role);expected=401 if role is None else 403
            for path in ('','/products.xlsx','/products.xlsx?template=true'):
                self.assertEqual(client.get('/api/admin/catalog'+path).status_code,expected)
            self.assertEqual(client.post('/api/admin/catalog/products',json=self.product_fields()).status_code,expected)
            self.assertEqual(client.post('/api/admin/catalog/products/delete',json={'products':[{'id':'fake','version':1}]}).status_code,expected)
            self.assertEqual(client.post('/api/admin/catalog/planograms',json={'name':'Fake','store_code':'L128'}).status_code,expected)
            self.assertEqual(client.post('/api/admin/catalog/reference',files={'file':('fake.pdf',b'fake','application/pdf')}).status_code,expected)

    def test_products_crud_validation_and_stale_updates(self):
        admin=self.client('admin');product=self.create_product()
        self.assertEqual(product['volume'],180)
        self.assertEqual(admin.post('/api/admin/catalog/products',json=self.product_fields()).status_code,409)
        self.assertEqual(admin.post('/api/admin/catalog/products',json={**self.product_fields('NEW'), 'width':0}).status_code,400)
        self.assertEqual(admin.post('/api/admin/catalog/products',json={**self.product_fields('NEW'), 'width':True}).status_code,422)
        update={**self.product_fields(), 'name':'Nombre actualizado','version':1}
        path='/api/admin/catalog/products/'+product['id']
        self.assertEqual(admin.patch(path,json=update).status_code,200)
        self.assertEqual(admin.patch(path,json=update).status_code,409)
        self.assertEqual(admin.get('/api/admin/catalog').json()['products'][0]['name'],'Nombre actualizado')

    def test_bulk_delete_is_atomic_and_preserves_referenced_products(self):
        admin=self.client('admin');first=self.create_product();second=self.create_product(sku='000124',barcode='000790')
        plan=self.save_plan(first)
        selected=[{'id':p['id'],'version':p['version']} for p in (first,second)]
        response=admin.post('/api/admin/catalog/products/delete',json={'products':selected})
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(len(admin.get('/api/admin/catalog').json()['products']),2)
        self.assertEqual(admin.delete(f"/api/admin/catalog/planograms/{plan['id']}?version=1").status_code,200)
        self.assertEqual(admin.post('/api/admin/catalog/products/delete',json={'products':selected}).status_code,200)
        self.assertEqual(admin.get('/api/admin/catalog').json()['products'],[])

    def test_plan_positions_validate_faces_identity_overlap_and_versions(self):
        admin=self.client('admin');product=self.create_product();plan=self.save_plan(product)
        self.assertEqual(plan['items'][0]['expected_facings'],2)
        self.assertEqual(plan['items'][0]['price_clp'],4990)
        body={**self.plan_fields(product),'version':1}
        body['positionRows'].append({**body['positionRows'][0],'position':2})
        path='/api/admin/catalog/planograms/'+plan['id']
        self.assertEqual(admin.patch(path,json=body).status_code,400)
        body={**self.plan_fields(product),'version':1};body['positionRows'][0]['sku']='WRONG'
        self.assertEqual(admin.patch(path,json=body).status_code,400)
        body={**self.plan_fields(product),'version':1};body['positionRows'][0]['level']=1.5
        self.assertEqual(admin.patch(path,json=body).status_code,422)
        body={**self.plan_fields(product),'version':1};body['positionRows'][0]['faces']=3
        updated=admin.patch(path,json=body)
        self.assertEqual(updated.status_code,200,updated.text)
        self.assertEqual(updated.json()['version'],2)
        self.assertEqual(admin.patch(path,json=body).status_code,409)
        self.assertEqual(admin.delete(path+'?version=1').status_code,409)

    def test_plan_edit_and_delete_preserve_historical_compliance(self):
        import catalog_service
        admin=self.client('admin');product=self.create_product();plan=self.save_plan(product)
        self.db.set_point_planogram('point-a',plan['id'])
        analysis={**self.analysis,'products':[{'product':product['name'],'brand':product['subBrand'],'facings':2,'shelf_level':1}]}
        reading=self.db.add_reading('point-a',analysis,[],planogram_id=plan['id'])
        snapshot=catalog_service.job_snapshot(plan['id'])
        before=reading['compliance']
        body={**self.plan_fields(product),'version':1};body['positionRows'][0]['faces']=5
        self.assertEqual(admin.patch('/api/admin/catalog/planograms/'+plan['id'],json=body).status_code,200)
        self.assertEqual(self.db.get_reading(reading['id'])['compliance'],before)
        historical=self.db.reading_planogram_snapshot(reading['id'])
        self.assertEqual(historical['items'][0]['expected_facings'],2)
        queued_reading=self.db.add_reading('point-a',analysis,[],planogram_id=plan['id'],plan_snapshot=snapshot)
        self.assertEqual(queued_reading['compliance'],before)
        self.assertEqual(admin.delete(f"/api/admin/catalog/planograms/{plan['id']}?version=2").status_code,200)
        self.assertEqual(self.db.get_reading(reading['id'])['compliance'],before)
        self.assertIsNone(self.db.get_point('point-a')['planogram_id'])

    def test_pdf_reference_page_navigation_and_validation(self):
        admin=self.client('admin');writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.add_blank_page(width=100,height=100)
        output=io.BytesIO();writer.write(output)
        reference=admin.post('/api/admin/catalog/reference',files={'file':('ref.pdf',output.getvalue(),'application/pdf')})
        self.assertEqual(reference.status_code,200,reference.text)
        self.assertEqual(reference.json()['document_pages'],2)
        product=self.create_product();admin.get('/api/admin/stores')
        fields=self.plan_fields(product);fields.update({key:value for key,value in reference.json().items() if key!='document_pages'})
        fields['document_page']=2
        saved=admin.post('/api/admin/catalog/planograms',json=fields)
        self.assertEqual(saved.status_code,201,saved.text)
        summary=admin.get('/api/admin/catalog').json()['planograms'][0]
        self.assertNotIn('document',summary)
        self.assertNotIn('photo',summary)
        detail=admin.get('/api/admin/catalog/planograms/'+saved.json()['id']).json()
        self.assertEqual(detail['document_page'],2)
        self.assertEqual(detail['document'],fields['document'])
        fields['document_page']=3;fields['name']='Invalid page'
        self.assertEqual(admin.post('/api/admin/catalog/planograms',json=fields).status_code,400)
        self.assertEqual(admin.post('/api/admin/catalog/reference',files={'file':('fake.pdf',b'fake','application/pdf')}).status_code,400)

    def excel_content(self, fields, invalid=False):
        from catalog_excel import COLUMNS,FIELDS
        book=Workbook();sheet=book.active;sheet.title='Productos';sheet.append(COLUMNS)
        sheet.append([fields.get(key,'') for key in FIELDS])
        if invalid:
            second={**fields,'sku':'BAD','width':0};sheet.append([second.get(key,'') for key in FIELDS])
        output=io.BytesIO();book.save(output);return output.getvalue()

    def test_excel_preview_commit_roundtrip_and_atomic_validation(self):
        admin=self.client('admin');content=self.excel_content(self.product_fields())
        files={'file':('Productos.xlsx',content,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
        preview=admin.post('/api/admin/catalog/products/import',files=files).json()
        self.assertEqual(preview['errors'],[])
        self.assertEqual(preview['creates'],1)
        self.assertEqual(admin.get('/api/admin/catalog').json()['products'],[])
        committed=admin.post('/api/admin/catalog/products/import',files=files,data={'commit':'true','version':str(preview['version'])})
        self.assertEqual(committed.status_code,200,committed.text)
        self.assertEqual(admin.post('/api/admin/catalog/products/import',files=files,data={'commit':'true','version':str(preview['version'])}).status_code,409)
        exported=admin.get('/api/admin/catalog/products.xlsx')
        book=load_workbook(io.BytesIO(exported.content));rows=list(book['Productos'].values)
        self.assertEqual(rows[1][5],'000123');self.assertEqual(rows[1][-1],'000789')
        bad=self.excel_content(self.product_fields('NEW'),invalid=True)
        failed=admin.post('/api/admin/catalog/products/import',files={'file':('bad.xlsx',bad)},data={'commit':'true','version':str(admin.get('/api/admin/catalog').json()['version'])})
        self.assertEqual(failed.status_code,400)
        self.assertEqual(len(admin.get('/api/admin/catalog').json()['products']),1)

    def test_legacy_plan_edit_keeps_unregistered_products_and_assignments(self):
        admin=self.client('admin');admin.get('/api/admin/stores')
        payload={'id':'legacy-plan','name':'Anterior','module_cm':90,'bands':1,'items':[{'order_seq':1,'section_label':'1/1','module':1,'band':1,'segment':0,'position_in_section':1,'title':'Producto anterior','internal_code':'OLD','barcode':'001','expected_facings':2}]}
        self.db.create_planogram(payload);self.db.set_point_planogram('point-a','legacy-plan')
        self.db.set_point_planogram('point-b','legacy-plan')
        legacy=admin.get('/api/admin/catalog/planograms/legacy-plan').json()
        product=self.create_product();fields=self.plan_fields(product);fields.update(positionRows=legacy['positionRows'],version=0)
        response=admin.patch('/api/admin/catalog/planograms/legacy-plan',json=fields)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.db.get_point('point-a')['planogram_id'],'legacy-plan')
        self.assertEqual(response.json()['items'][0]['title'],'Producto anterior')
        import catalog_service
        catalog_service.validate_assignment('legacy-plan','L129','point-b')
        self.assertTrue(admin.get('/api/points/point-b').json()['can_capture'])
        fields['version']=1;fields['positionRows'][0]['position']=3
        moved=admin.patch('/api/admin/catalog/planograms/legacy-plan',json=fields)
        self.assertEqual(moved.status_code,200,moved.text)
        fields.update(version=2,positionRows=moved.json()['positionRows'])
        self.assertEqual(admin.patch('/api/admin/catalog/planograms/legacy-plan',json=fields).status_code,200)

    def test_plan_assignment_checks_store_and_status(self):
        admin=self.client('admin');product=self.create_product();plan=self.save_plan(product)
        self.assertEqual(admin.put('/api/points/point-b/planogram',json={'planogram_id':plan['id']}).status_code,409)
        self.assertEqual(admin.put('/api/points/point-a/planogram',json={'planogram_id':plan['id']}).status_code,200)
        moved={**self.plan_fields(product),'store_code':'L129','version':1}
        self.assertEqual(admin.patch('/api/admin/catalog/planograms/'+plan['id'],json=moved).status_code,409)
        fields={**self.plan_fields(product),'status':'Inactivo','version':1}
        self.assertEqual(admin.patch('/api/admin/catalog/planograms/'+plan['id'],json=fields).status_code,200)
        self.assertFalse(admin.get('/api/points/point-a').json()['can_capture'])
        response=self.client('analyst').post('/api/points/point-a/analyze',files={'images':('test.jpg',b'test','image/jpeg')})
        self.assertEqual(response.status_code,409)

    def test_plan_edits_protect_queued_and_running_legacy_jobs(self):
        admin=self.client('admin');product=self.create_product();plan=self.save_plan(product)
        self.db.create_job('queued-old','app','point-a',{'planogram_id':plan['id']})
        fields={**self.plan_fields(product),'version':1};fields['positionRows'][0]['faces']=3
        response=admin.patch('/api/admin/catalog/planograms/'+plan['id'],json=fields)
        self.assertEqual(response.status_code,200,response.text)
        queued=self.db.get_job('queued-old')['payload']['plan_snapshot']
        self.assertEqual(queued['items'][0]['expected_facings'],2)
        self.db.create_job('running-old','app','point-a',{'planogram_id':plan['id']})
        self.db.set_job_running('running-old')
        fields['version']=2;fields['positionRows'][0]['faces']=4
        self.assertEqual(admin.patch('/api/admin/catalog/planograms/'+plan['id'],json=fields).status_code,409)
        self.assertEqual(self.db.get_planogram(plan['id'])['items'][0]['expected_facings'],3)

    def test_legacy_json_replace_is_validated_and_atomic(self):
        admin=self.client('admin')
        payload={'name':'Referencia','items':[{'title':'Anterior','band':1,'position_in_section':1,'expected_facings':2}]}
        def upload(data,replace=False):
            return admin.post('/api/admin/planograms/import-json',files={'file':('plan.json',json.dumps(data).encode(),'application/json')},data={'planogram_id':'legacy-json','replace':str(replace).lower()})
        self.assertEqual(upload(payload).status_code,200)
        self.db.set_point_planogram('point-a','legacy-json')
        self.assertEqual(upload({'items':[{'title':'Invalid','band':'bad'}]},True).status_code,400)
        self.assertEqual(upload([],True).status_code,400)
        self.assertEqual(self.db.get_planogram('legacy-json')['items'][0]['title'],'Anterior')
        payload['items'][0]['title']='Actualizado'
        self.assertEqual(upload(payload,True).status_code,200)
        self.assertEqual(self.db.get_point('point-a')['planogram_id'],'legacy-json')
