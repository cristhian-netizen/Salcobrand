import {test} from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';

test('tab selectors persist reloads while different tabs and logins stay independent', async () => {
  globalThis.crypto ??= webcrypto;
  const storage = new Map();
  globalThis.window = {location: {origin: 'https://portal.example'}, sessionStorage: {
    getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value),
  }};
  const first = await import('./tab-session.mjs?first');
  const id = first.getTabSession();
  assert.match(id, /^[a-f0-9]{32}$/);
  const reloaded = await import('./tab-session.mjs?reload');
  assert.equal(reloaded.getTabSession(), id);
  assert.equal(reloaded.sessionHeaders()['X-Portal-Session'], id);
  storage.clear();
  const second = await import('./tab-session.mjs?second');
  assert.notEqual(second.getTabSession(), id);
  const fresh = second.createTabSession();
  second.setTabSession(fresh);
  assert.equal(second.getTabSession(), fresh);
  assert.notEqual(fresh, id);
  assert.equal(second.sessionUrl('/uploads/a.jpg?size=2'), `/uploads/a.jpg?size=2&portal_session=${fresh}`);
  assert.equal(second.sessionUrl('/api/readings/1/crop.jpg'), `/api/readings/1/crop.jpg?portal_session=${fresh}`);
  for (const url of ['data:image/png;base64,abc', 'blob:https://portal.example/123', 'https://other.example/photo.jpg', '/vendor/pdfjs/build/pdf.min.mjs']) {
    assert.equal(second.sessionUrl(url), url);
  }
  delete globalThis.window;
  assert.equal(second.getTabSession(), null);
});
