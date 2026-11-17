import test from 'node:test';
import assert from 'node:assert/strict';
import {can, normalizeUser, profileOf, ROLE_NAMES, scopeLabel} from './profiles.mjs';

test('client and internal profiles preserve compatible legacy accounts', () => {
  assert.deepEqual(Object.keys(ROLE_NAMES), ['admin', 'analyst', 'replenisher', 'viewer','local-neura']);
  assert.equal(profileOf('supervisor'), 'analyst');
  assert.equal(profileOf('tienda'), 'replenisher');
  assert.equal(normalizeUser({username: 'legacy', role: 'tienda', store_id: 'L128'}).role, 'replenisher');
  assert.equal(profileOf('unknown'), null);
});

test('the capability matrix never grants management or review by fallback', () => {
  const expected = {
    admin: ['read', 'manage', 'report'],
    analyst: ['read', 'scan', 'review', 'resolve', 'report', 'dashboard'],
    replenisher: ['read', 'scan'],
    viewer: ['read', 'report', 'dashboard'],
  };
  for (const [role, actions] of Object.entries(expected)) {
    for (const action of ['read', 'scan', 'review', 'resolve', 'manage', 'report', 'dashboard']) {
      assert.equal(can({role}, action), actions.includes(action), `${role}:${action}`);
    }
  }
  assert.equal(can({role: 'unknown'}, 'read'), false);
  assert.equal(can({role: 'admin'}, 'unknown-action'), false);
});

test('scope labels distinguish assigned and unassigned field profiles', () => {
  assert.equal(scopeLabel({role: 'analyst'}), 'Sin PDV asignados');
  assert.equal(scopeLabel({role: 'replenisher'}), 'Sin PDV asignados');
  assert.equal(scopeLabel({role: 'replenisher', store_ids: ['L128', 'L129']}), '2 PDV asignados');
});


test('provider training is isolated from customer and console capabilities',()=>{
 const user={role:'local-neura',internal:true};
 assert.equal(can(user,'train'),true);assert.equal(can(user,'read'),true);
 for(const action of ['manage','scan','review','report','dashboard','resolve'])assert.equal(can(user,action),false);
 assert.equal(can({role:'local-neura'},'train'),false);
 assert.equal(can({role:'analyst'},'train'),false);
 assert.equal(can({...user,read_only:true},'train'),false);
});
