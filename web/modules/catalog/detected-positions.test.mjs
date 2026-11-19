import test from 'node:test';
import assert from 'node:assert/strict';
import {detectedRows, cleanRow} from './detected-positions.mjs';

test('detected rows become editor rows and keep the detected title as a hint', () => {
 const detected = {positionRows: [
  {level: 2, position: 1, faces: 3, productId: 'p1', sku: '000123', barcode: '7801234567890', detected_title: 'DESODORANTE ROLL ON'},
  {level: 1, position: 4, faces: 0, productId: '', sku: '999888', barcode: '', detected_title: 'TALCO DESCONOCIDO'},
 ]};
 const rows = detectedRows(detected);
 assert.equal(rows.length, 2);
 assert.deepEqual(rows[0], {level: 2, position: 1, faces: 3, productId: 'p1', sku: '000123', barcode: '7801234567890',
  legacy_item_id: null, legacy_title: '', detected_title: 'DESODORANTE ROLL ON'});
 assert.deepEqual(rows[1], {level: 1, position: 4, faces: 1, productId: '', sku: '999888', barcode: '',
  legacy_item_id: null, legacy_title: '', detected_title: 'TALCO DESCONOCIDO'});
 assert.deepEqual(detectedRows(null), []);
 assert.deepEqual(detectedRows({positionRows: []}), []);
});

test('clean rows never send the detection hint to the API', () => {
 const row = {level: 1, position: 1, faces: 2, productId: 'p1', sku: 'A', barcode: 'B',
  legacy_item_id: null, legacy_title: '', detected_title: 'ALGO'};
 assert.deepEqual(cleanRow(row), {level: 1, position: 1, faces: 2, productId: 'p1', sku: 'A', barcode: 'B',
  legacy_item_id: null, legacy_title: ''});
 assert.ok(!('detected_title' in cleanRow(row)));
});
