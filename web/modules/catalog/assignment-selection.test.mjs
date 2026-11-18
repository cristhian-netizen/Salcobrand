import test from 'node:test';
import assert from 'node:assert/strict';
import {INITIAL_FILTERS,filteredStores,selectStores} from './assignment-selection.mjs';
const stores=[
 {code:'A',name:'Arica',region:'Norte',commune:'Arica',store_type:'Farmacia',status:'Activo',type_ids:['G1'],references:[{category:'Salud',subcategory:'Sexual'}]},
 {code:'B',name:'Santiago',region:'Centro',commune:'Santiago',store_type:'Farmacia',status:'Activo',type_ids:[],references:[]},
 {code:'C',name:'Antiguo',status:'Inactivo',type_ids:['G1'],references:[]}
];
test('five filters narrow candidate stores without removing unreferenced stores by default',()=>{
 assert.equal(filteredStores(stores,INITIAL_FILTERS).length,3);
 const filters={...INITIAL_FILTERS,region:'Norte',commune:'Arica',store_type:'Farmacia',category:'Salud',subcategory:'Sexual'};
 assert.deepEqual(filteredStores(stores,filters).map(s=>s.code),['A']);
 assert.equal(filteredStores(stores,{...filters,subcategory:'Otra'}).length,0);
});
test('filtered and country selection retain hidden picks but exclude inactive and incompatible stores',()=>{
 assert.deepEqual(selectStores(['B'],stores,'G1'),['B','A']);
 assert.deepEqual(selectStores([],stores),['A','B']);
 assert.deepEqual(selectStores(['A'],[stores[0]]),['A']);
});
