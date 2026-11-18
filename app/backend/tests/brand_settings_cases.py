import io
from openpyxl import Workbook, load_workbook


class BrandSettingsCases:
    def test_categories_brands_and_pdv_types_save_independently(self):
        initial=self.configuration()['state']
        result=self.configure('categories',{'categories':{'Salud':['Bienestar']}})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['state']['catalog']['brands'],[])
        value={'brands':['Nueva'],'ownBrands':['Nueva'],'brandClassifications':{'Nueva':{'category':'Salud','subcategory':'Bienestar'}}}
        result=self.configure('brands',value)
        self.assertEqual(result.status_code,200,result.text)
        state=result.json()['state']
        self.assertEqual(state['catalog']['categories'],{'Salud':['Bienestar']})
        self.assertEqual(state['pdvTypes'],initial['pdvTypes'])
        self.assertEqual(state['scoreParameters'],initial['scoreParameters'])
        self.assertEqual(state['productParameters']['ownBrands'],['Nueva'])
        result=self.configure('pdv-types',state['pdvTypes']+['Especial'])
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['state']['catalog'],state['catalog'])
        result=self.configure('categories',{'categories':{'Salud':['Bienestar','Otra']}})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['state']['catalog']['brandClassifications'],value['brandClassifications'])
        self.assertEqual(result.json()['state']['productParameters']['ownBrands'],['Nueva'])
        for section,payload in [('categories',{'categories':{'Otra':['Una']}}),('brands',value)]:
            self.assertEqual(self.configure(section,payload,username='analyst').status_code,403)

    def test_new_brand_requires_a_real_subcategory(self):
        self.configure('categories',{'categories':{'Salud':['Bienestar'],'Cuidado':['Piel']}})
        missing={'brands':['Nueva'],'ownBrands':[],'brandClassifications':{}}
        self.assertEqual(self.configure('brands',missing).status_code,400)
        wrong={**missing,'brandClassifications':{'Nueva':{'category':'Salud','subcategory':'Piel'}}}
        self.assertEqual(self.configure('brands',wrong).status_code,409)
        good={**missing,'brandClassifications':{'Nueva':{'category':'Cuidado','subcategory':'Piel'}}}
        result=self.configure('brands',good)
        self.assertEqual(result.status_code,200,result.text)
        classification=self.client('admin').get('/api/admin/catalog').json()['classification']
        self.assertEqual(classification['brandClassifications']['Nueva'],{'category':'Cuidado','subcategory':'Piel'})
        fields={**self.product_fields('NEW'),'subBrand':'Nueva','category':'Cuidado','subcategory':'Piel'}
        self.assertEqual(self.client('admin').post('/api/admin/catalog/products',json=fields).status_code,201)

    def test_brand_relation_protects_assigned_subcategory_from_removal(self):
        self.configure('categories',{'categories':{'Uno':['Igual'],'Dos':['Igual']}})
        value={'brands':['Nueva'],'ownBrands':[],'brandClassifications':{'Nueva':{'category':'Uno','subcategory':'Igual'}}}
        self.assertEqual(self.configure('brands',value).status_code,200)
        self.assertEqual(self.configure('categories',{'categories':{'Dos':['Igual']}}).status_code,409)
        value['brandClassifications']['Nueva']['category']='Dos'
        self.assertEqual(self.configure('brands',value).status_code,200)
        self.assertEqual(self.configure('categories',{'categories':{'Dos':['Igual']}}).status_code,200)

    def test_existing_ambiguous_brand_is_not_reclassified_automatically(self):
        one=self.create_product(sku='ONE')
        two=self.create_product(sku='TWO',category='Otra categoría',subcategory='Otra subcategoría')
        config=self.configuration()
        self.assertNotIn('Marca QA',config['state']['catalog']['brandClassifications'])
        value={'brands':['Marca QA'],'ownBrands':[],'brandClassifications':{'Marca QA':{'category':one['category'],'subcategory':one['subcategory']}}}
        response=self.configure('brands',value)
        self.assertEqual(response.status_code,200,response.text)
        products=self.client('admin').get('/api/admin/catalog').json()['products']
        self.assertEqual(next(p for p in products if p['sku']=='TWO')['subcategory'],two['subcategory'])

    def test_classification_excel_supports_brand_relations_and_ignores_legacy_exclusivity(self):
        self.create_product()
        admin=self.client('admin')
        template=admin.get('/api/admin/settings/classification/template.xlsx')
        book=load_workbook(io.BytesIO(template.content))
        self.assertNotIn('Exclusiva',[c.value for c in book['Catalogo'][1]])
        legacy=Workbook();sheet=legacy.active;sheet.title='Catalogo'
        sheet.append(['Submarca','Categoría','Subcategoría','Marca propia','Exclusiva'])
        sheet.append(['Nueva','Salud','Bienestar','No','Sí'])
        output=io.BytesIO();legacy.save(output)
        url='/api/admin/settings/classification/import'
        preview=admin.post(url,files={'file':('old.xlsx',output.getvalue())}).json()
        self.assertFalse(preview['has_errors'],preview)
        response=admin.post(url,files={'file':('old.xlsx',output.getvalue())},data={'commit':'true','version':preview['version']})
        self.assertEqual(response.status_code,200,response.text)
        config=self.configuration()['state']['catalog']
        self.assertEqual(config['exclusive'],{})
        self.assertEqual(config['brandClassifications']['Nueva'],{'category':'Salud','subcategory':'Bienestar'})
