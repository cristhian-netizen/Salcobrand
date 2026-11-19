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
test('APIs closes Administración for admin and Superusuario only',()=>{
 const admin=GROUPS.find(([name])=>name==='Administración')[1];
 assert.equal(admin.at(-1),'apis');
 assert.equal(visible('admin').at(-1),'apis');assert.equal(visible('viewer').at(-1),'apis');
 for(const role of ['analyst','replenisher','local-neura'])assert(!allowed('apis',role),role);
});
