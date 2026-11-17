import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {byLocationName, captureStores, filterCaptureStores, pointStoreCode, regionFor} from './scan-locations.mjs';

const regions = JSON.parse(readFileSync(new URL('../../../app/backend/chile_locations.json', import.meta.url), 'utf8'));
const stores = [
  {code: 'PDV-001', name: 'Farmacia Buin', status: 'Activo', region: 'RM', commune: 'Buin'},
  {code: 'PDV-002', name: 'Farmacia Costa', status: 'Activo', region: 'Valparaíso', commune: 'Viña del Mar'},
  {code: 'PDV-003', name: 'Farmacia inactiva', status: 'Inactivo', region: 'RM', commune: 'Santiago'},
];
const filters = (region = '', commune = '', query = '') => ({region, commune, query});

test('region catalog and every commune remain available when the account has no stores', () => {
  assert.equal(regions.length, 16);
  assert.equal(regions.reduce((sum, region) => sum + region.communes.length, 0), 346);
  assert.deepEqual(captureStores([], []), []);
  assert.equal(regionFor(regions, 'RM').communes.length, 52);
  assert(regionFor(regions, 'RM').communes.some(commune => commune.name === 'Santiago'));
  assert.equal(regionFor(regions, '05').communes.length, 38);
});

test('region aliases, commune inference and alphabetical ordering preserve legacy PDV', () => {
  const available = captureStores(stores, []);
  const metropolitan = regionFor(regions, 'Metropolitana').name;
  assert.deepEqual(filterCaptureStores(available, regions, filters(metropolitan)).map(store => store.code), ['PDV-001']);
  assert.equal(filterCaptureStores(available, regions, filters(metropolitan, 'Santiago')).length, 0);
  assert.equal(filterCaptureStores(available, regions, filters(metropolitan, 'Buin')).length, 1);
  assert.equal(filterCaptureStores([{...stores[0], region: ''}], regions, filters(metropolitan)).length, 1);
  const communes = [...regionFor(regions, 'RM').communes].sort(byLocationName);
  assert.equal(communes.length, 52);
  assert(communes.some(commune => commune.name === 'Buin'));
});

test('search combines with region and commune without shrinking the commune catalog', () => {
  const available = captureStores(stores, []);
  assert.equal(filterCaptureStores(available, regions, filters('', '', 'pdv-001'))[0].code, 'PDV-001');
  assert.equal(filterCaptureStores(available, regions, filters('Valparaíso', 'Vina del Mar', 'costa'))[0].code, 'PDV-002');
  assert.equal(filterCaptureStores(available, regions, filters('Valparaíso', '', 'PDV-001')).length, 0);
  assert.equal(filterCaptureStores(available, regions, filters()).length, 2);
  assert.equal(regionFor(regions, 'Valparaíso').communes.length, 38);
});

test('inactive stores and archived points stay excluded, with support for historical scoped points', () => {
  const points = [
    {id: 'point-a', store_id: 'PDV-001', can_capture: true},
    {id: 'inactive', store_id: 'PDV-003', can_capture: false},
    {id: 'archived', store_id: 'ARCHIVED', can_capture: false},
    {id: 'historical', store_key: 'Legacy store', store_name: 'Local anterior', can_capture: true},
  ];
  const available = captureStores(stores, points);
  assert.deepEqual(available.map(store => store.code), ['PDV-001', 'PDV-002', 'Legacy store']);
  assert.equal(pointStoreCode(points[3]), 'Legacy store');
  assert.equal(pointStoreCode({id: 'unassigned-historical'}), 'unassigned-historical');
});


test('official north-south order and compatible type references', async () => {
  const {orderRegions,orderRegionNames} = await import('../../lib/locations.mjs');
  const {capturePointForType} = await import('./scan-locations.mjs');
  assert.deepEqual(orderRegions(regions).map(r=>r.code),['15','01','02','03','04','05','13','06','07','16','08','09','14','10','11','12']);
  assert.deepEqual(orderRegionNames(['Maule','Arica y Parinacota','Metropolitana de Santiago'],regions),['Arica y Parinacota','Metropolitana de Santiago','Maule']);
  const make=(id,plan,cat,number=1)=>({id,planogram_id:plan,infrastructure:{type_id:'G1',number},planogram_classification:{category:cat,subcategories:['A']}});
  const points=[make('p2','planB','Salud'),make('p1','planA','Cuidado')];
  assert.equal(capturePointForType(points,'G1',{category:'',subcategories:[]}).ambiguous,true);
  assert.equal(capturePointForType(points,'G1',{category:'Cuidado',subcategories:['A']}).point.id,'p1');
  assert.equal(capturePointForType([make('p2','planA','Cuidado',2),make('p1','planA','Cuidado')],'G1',{category:'Cuidado',subcategories:['A']}).point.id,'p1');
  assert.equal(capturePointForType(points,'Other',{category:'',subcategories:[]}).point,null);
});
