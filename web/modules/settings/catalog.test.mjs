import test from 'node:test';
import assert from 'node:assert/strict';
import {catalogDraft, updateCatalog} from './catalog.mjs';

const state = {
  catalog:{brands:['Casa','Rival'], categories:{Bebidas:['Agua','Jugo']}, exclusive:{}},
  productParameters:{dimensionMarginPct:12, ownBrands:['Casa']},
  products:[{id:1,sku:'A1',subBrand:'Casa',category:'Bebidas',subcategory:'Agua'}],
  stores:[{id:2,name:'Local'}],
};

test('editor carga marcas, propias y filas desde el workspace', () => {
  const draft = catalogDraft(state);
  assert.equal(draft.brands.find(brand => brand.name === 'Casa').own, true);
  assert.equal(draft.rows.length, 2);
  assert.equal(draft.rows[0].subcategory, 'Agua');
});

test('guardar conserva productos, locales y margen existente', () => {
  const draft = catalogDraft(state);
  draft.brands.push({id:'new',name:'Nueva',own:true});
  draft.rows.push({id:'new-row',category:'Snacks',subcategory:'Barras',brandId:'new'});
  const next = updateCatalog(state, draft);
  assert.deepEqual(next.catalog.categories.Snacks, ['Barras']);
  assert.equal(next.catalog.exclusive.Snacks, 'Nueva');
  assert.deepEqual(next.productParameters, {dimensionMarginPct:12,ownBrands:['Casa','Nueva']});
  assert.equal(next.products[0].sku, 'A1');
  assert.equal(next.stores[0].id, 2);
  assert.equal(state.catalog.brands.length, 2);
});

test('no permite quitar o renombrar clasificaciones utilizadas', () => {
  const withoutBrand = catalogDraft(state);
  withoutBrand.brands = withoutBrand.brands.filter(brand => brand.name !== 'Casa');
  assert.throws(() => updateCatalog(state, withoutBrand), /productos asociados/);
  const withoutSubcategory = catalogDraft(state);
  withoutSubcategory.rows = withoutSubcategory.rows.filter(row => row.subcategory !== 'Agua');
  assert.throws(() => updateCatalog(state, withoutSubcategory), /productos asociados/);
});

test('rechaza duplicados, categorías reservadas y exclusividad incompatible', () => {
  const duplicate = catalogDraft(state);
  duplicate.brands.push({id:'extra',name:'casa',own:false});
  assert.throws(() => updateCatalog(state, duplicate), /repetida/);
  const reserved = catalogDraft(state);
  reserved.rows[0].category = '__proto__';
  assert.throws(() => updateCatalog(state, reserved), /reservado/);
  const exclusive = catalogDraft(state);
  exclusive.rows.forEach(row => { row.brandId = 'b1'; });
  assert.throws(() => updateCatalog(state, exclusive), /otras marcas/);
});

test('la exclusividad debe ser coherente entre filas de la misma categoría', () => {
  const draft = catalogDraft(state);
  draft.rows[0].brandId = 'b0';
  assert.throws(() => updateCatalog(state, draft), /misma submarca exclusiva/);
});
