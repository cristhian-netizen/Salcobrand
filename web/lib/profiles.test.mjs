import test from 'node:test';
import assert from 'node:assert/strict';
import {can, normalizeUser, profileOf, ROLE_NAMES, scopeLabel} from './profiles.mjs';

test('four explicit profiles and compatible legacy accounts', () => {
  assert.deepEqual(Object.keys(ROLE_NAMES), ['admin', 'analyst', 'replenisher', 'viewer']);
  assert.equal(profileOf('supervisor'), 'analyst');
  assert.equal(profileOf('tienda'), 'replenisher');
  assert.equal(normalizeUser({username: 'legacy', role: 'tienda', store_id: 'L128'}).role, 'replenisher');
  assert.equal(profileOf('unknown'), null);
});

test('the capability matrix never grants management or review by fallback', () => {
  const expected = {
    admin: ['read', 'manage', 'report', 'dashboard'],
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

test('scope labels distinguish unrestricted analysts from unassigned replenishers', () => {
  assert.equal(scopeLabel({role: 'analyst'}), 'Todos los locales');
  assert.equal(scopeLabel({role: 'replenisher'}), 'Sin PDV asignados');
  assert.equal(scopeLabel({role: 'replenisher', store_ids: ['L128', 'L129']}), '2 PDV asignados');
});
