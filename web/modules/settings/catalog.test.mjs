import test from 'node:test';
import assert from 'node:assert/strict';
import {catalogDraft,updateCatalog,categoryValue,brandValue,subcategoryOptions,applyBrandClassification} from './catalog.mjs';
const state={catalog:{brands:['Casa','Rival'],categories:{Bebidas:['Agua','Jugo']},exclusive:{}},productParameters:{dimensionMarginPct:12,ownBrands:['Casa']},products:[{sku:'A1',subBrand:'Casa',category:'Bebidas',subcategory:'Agua'}],stores:[{name:'Local'}]};

test('existing brands infer only an unambiguous product classification',()=>{
  const draft=catalogDraft(state);assert.equal(draft.brands[0].subcategory,'Agua');assert.equal(draft.brands[0].category,'Bebidas');assert(draft.brands[0].own);
  const ambiguous=catalogDraft({...state,products:[...state.products,{subBrand:'Casa',category:'Bebidas',subcategory:'Jugo'}]});assert.equal(ambiguous.brands[0].subcategory,'');
});
test('category validation is independent of brand drafts',()=>{
  assert.deepEqual(categoryValue([{category:'Salud',subcategory:'Bienestar'}]),{categories:{Salud:['Bienestar']}});
  assert.throws(()=>categoryValue([{category:'__proto__',subcategory:'x'}]),/reservado/);
  assert.throws(()=>categoryValue([{category:'Salud',subcategory:'Uno'},{category:'Salud',subcategory:'uno'}]),/repetida/);
});
test('new brands must select an existing subcategory and derive its category',()=>{
  assert.throws(()=>brandValue([{name:'Nueva',own:false}],state.catalog.categories,state.catalog.brands),/subcategoría existente/);
  const option=subcategoryOptions(state.catalog.categories).find(o=>o.subcategory==='Jugo');
  const value=brandValue([{name:'Nueva',own:true,...option}],state.catalog.categories,state.catalog.brands);
  assert.deepEqual(value.brandClassifications.Nueva,{category:'Bebidas',subcategory:'Jugo'});
  assert.deepEqual(value.ownBrands,['Nueva']);
  assert.throws(()=>brandValue([{name:'Nueva',category:'Otra',subcategory:'Jugo'}],state.catalog.categories,[]),/creada/);
});
test('classification changes preserve products, locations, and other parameters',()=>{
  const draft=catalogDraft(state);draft.rows.push({category:'Snacks',subcategory:'Barras'});draft.brands.push({name:'Nueva',own:true,category:'Snacks',subcategory:'Barras'});
  const next=updateCatalog(state,draft);assert.deepEqual(next.catalog.exclusive,{});assert.equal(next.catalog.brandClassifications.Nueva.category,'Snacks');assert.equal(next.products[0].sku,'A1');assert.equal(next.stores[0].name,'Local');assert.equal(next.productParameters.dimensionMarginPct,12);
});
test('used classifications and duplicate brand names remain protected',()=>{
  const draft=catalogDraft(state);draft.rows=draft.rows.filter(r=>r.subcategory!=='Agua');assert.throws(()=>updateCatalog(state,draft),/productos asociados|creada/);
  const brands=catalogDraft(state).brands;brands.push({name:'casa'});assert.throws(()=>brandValue(brands,state.catalog.categories,state.catalog.brands),/repetida/);
});
test('selecting a brand fills product classification without altering product information',()=>{
  const form={sku:'0001',price:4990,category:'',subcategory:''};
  const catalog={...state.catalog,brandClassifications:{Casa:{category:'Bebidas',subcategory:'Agua'}}};
  const selected=applyBrandClassification(form,'Casa',catalog);assert.equal(selected.category,'Bebidas');assert.equal(selected.subcategory,'Agua');assert.equal(selected.sku,'0001');assert.equal(selected.price,4990);
  const options=subcategoryOptions({Uno:['Igual'],Dos:['Igual']});assert.equal(new Set(options.map(o=>o.key)).size,2);
});

test('brand labels never modify object prototypes',()=>{
  const value=brandValue([{name:'__proto__',category:'Bebidas',subcategory:'Agua'}],state.catalog.categories,[]);
  assert(Object.hasOwn(value.brandClassifications,'__proto__'));
  assert.equal(JSON.parse(JSON.stringify(value.brandClassifications)).__proto__.subcategory,'Agua');
  assert.equal(applyBrandClassification({category:'',subcategory:''},'constructor',{categories:state.catalog.categories,brandClassifications:{}}).category,'');
});
