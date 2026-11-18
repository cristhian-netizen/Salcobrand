import {test} from 'node:test';
import assert from 'node:assert/strict';
import {compareValues} from './table-sort.mjs';
import {orderRegions} from './locations.mjs';
test('sorting respects Chilean numbers, accents, missing data, and date values',()=>{
  assert.deepEqual(['10.000','900','1.200'].sort(compareValues),['900','1.200','10.000']);
  assert(compareValues('Árbol','Zapato')<0);
  assert(compareValues('12,5 %','9,2 %')>0);
  assert(compareValues('2026-01-31','2026-02-01')<0);
  assert(compareValues(null,1,'desc')>0);
  assert(compareValues(2,10,'desc')>0);
  assert.deepEqual(orderRegions([{name:'Maule'},{name:'Tarapacá'},{name:'Metropolitana de Santiago'}]).map(r=>r.name),['Tarapacá','Metropolitana de Santiago','Maule']);
});
