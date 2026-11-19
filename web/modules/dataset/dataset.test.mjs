import test from 'node:test';
import assert from 'node:assert/strict';
import {fmtMB, progressLabel, categorySummary, totalsOf, dimensionsLabel, linkStatus} from './dataset.mjs';

test('sizes read like a phone photo: whole MB above 10, one decimal below, never a fake 0', () => {
  assert.equal(fmtMB(24 * 1024 * 1024), '24 MB');
  assert.equal(fmtMB(2.4 * 1024 * 1024), '2,4 MB');
  assert.equal(fmtMB(1), '0,1 MB'); // a stored photo never shows as empty
  assert.equal(fmtMB(0), '0 MB');
  assert.equal(fmtMB(undefined), '0 MB');
});

test('per-file progress and category header follow the agreed wording', () => {
  assert.equal(progressLabel(3, 8, 24 * 1024 * 1024), '3/8 · 24 MB');
  assert.equal(categorySummary(12, 340 * 1024 * 1024), '12 fotos · 340 MB');
  assert.equal(categorySummary(1, 1024 * 1024 * 5), '1 foto · 5 MB');
  assert.equal(categorySummary(0, 0), '0 fotos · 0 MB');
});

test('grid totals come from the loaded rows and tolerate missing byte counts', () => {
  assert.deepEqual(totalsOf([{bytes: 1048576}, {bytes: 2097152}, {}]), {count: 3, bytes: 3145728});
  assert.deepEqual(totalsOf([]), {count: 0, bytes: 0});
  assert.deepEqual(totalsOf(null), {count: 0, bytes: 0});
});

test('dimensions label is omitted when HEIC sizes could not be read', () => {
  assert.equal(dimensionsLabel({width: 4032, height: 3024}), '4032 × 3024 px');
  assert.equal(dimensionsLabel({width: null, height: null}), null);
  assert.equal(dimensionsLabel(undefined), null);
});

test('capture link status: revoked beats expired beats full beats active', () => {
  const now = Date.parse('2026-11-19T12:00:00Z');
  const base = {expires_at: '2026-12-01T00:00:00+00:00', revoked_at: null, photos: 0, max_photos: 500};
  assert.deepEqual(linkStatus(base, now), ['ok', 'Activo']);
  assert.deepEqual(linkStatus({...base, photos: 500}, now), ['warn', 'Lleno']);
  assert.deepEqual(linkStatus({...base, photos: 500, expires_at: '2026-11-01T00:00:00+00:00'}, now), ['', 'Vencido']);
  assert.deepEqual(linkStatus({...base, revoked_at: '2026-11-18T00:00:00+00:00', photos: 500}, now), ['', 'Revocado']);
  assert.deepEqual(linkStatus({...base, photos: undefined}, now), ['ok', 'Activo']); // a fresh link counts zero
});
