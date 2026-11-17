import test from 'node:test';
import assert from 'node:assert/strict';
import {GROUPS,allowed} from './modules.mjs';
const visible=role=>GROUPS.flatMap(([,ids])=>ids.filter(id=>allowed(id,role)));
test('customer sidebar preserves business modules and hides internal verification',()=>{
 for(const role of ['admin','analyst','replenisher','viewer']){
  const ids=visible(role);
  for(const id of ['revision','gondolas','enlaces','cuenta'])assert(!ids.includes(id),role+':'+id);
  assert(allowed('cuenta',role));assert(allowed('gondolas',role));assert(!allowed('revision',role));
 }
 assert(!visible('admin').includes('dashboards'));
 assert(visible('analyst').includes('mediciones'));assert(visible('viewer').includes('uso-analisis'));
 assert.deepEqual(visible('local-neura'),['revision']);
});
