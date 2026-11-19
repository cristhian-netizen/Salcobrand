import test from 'node:test';
import assert from 'node:assert/strict';
import {initial, loaded, failed, retried, sourceFor, wrapperClass} from './img-state.mjs';

test('an image starts loading, becomes ready on load and keeps its first URL', () => {
  const start = initial('/uploads/a.jpg');
  assert.equal(start.phase, 'loading');
  assert.equal(wrapperClass(start), 'sb-img is-loading');
  assert.equal(sourceFor(start), '/uploads/a.jpg');
  const ready = loaded(start);
  assert.equal(ready.phase, 'ready');
  assert.equal(wrapperClass(ready), 'sb-img is-ready');
  assert.equal(initial('').phase, 'empty');
});

test('an error shows retry and each retry busts the negative cache with a fresh URL', () => {
  const error = failed(initial('/uploads/a.jpg'));
  assert.equal(error.phase, 'error');
  assert.equal(wrapperClass(error), 'sb-img is-error');
  const once = retried(error);
  assert.equal(once.phase, 'loading');
  assert.equal(sourceFor(once), '/uploads/a.jpg?retry=1');
  assert.equal(sourceFor(retried(failed(once))), '/uploads/a.jpg?retry=2');
  assert.equal(sourceFor(retried(failed(initial('/u/a.jpg?w=256')))), '/u/a.jpg?w=256&retry=1');
});

test('late events never fight the current phase', () => {
  const ready = loaded(initial('/uploads/a.jpg'));
  assert.equal(failed(ready), ready); // a stale onError after success keeps the image visible
  assert.equal(retried(ready), ready); // retry only exists on the error state
  const data = initial('data:image/png;base64,AA');
  assert.equal(sourceFor(retried(failed(data))), data.src); // data uris cannot take a query marker
});
