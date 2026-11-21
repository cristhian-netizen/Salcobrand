import test from 'node:test';
import assert from 'node:assert/strict';
import {precisionClass, overlayFor, imageSizeFor, hasPrecisionBoxes, precisionSummary, tooltip, LEGEND} from './precision-map.mjs';

const pack = {product: 'Pack Rexona Clinical Men', match_status: 'match', needs_review: false, confidence: 0.93, facings: 2,
  pack_units: 4, units_per_pack: 2, image_index: 0, image_size: [1688, 3000],
  boxes: [[791, 1015, 870, 1239], [866, 1028, 938, 1243], [965, 1028, 1045, 1243], [1041, 1020, 1123, 1238]]};
const doubtful = {product: 'Dove Men Shea Cedar', match_status: 'match', needs_review: true, confidence: 0.45, facings: 1,
  image_index: 0, boxes: [[100, 200, 180, 400]]};
const counted = {product: 'Nivea Clinical', match_status: 'confirmed', needs_review: false, count_uncertain: true, confidence: 1, facings: 1,
  image_index: 0, boxes: [[200, 200, 280, 400]]};
const unknown = {product: 'texto leído', match_status: 'unmatched', needs_review: true, confidence: 0.12, facings: 1,
  image_index: 0, boxes: [[300, 200, 380, 400]]};
const unreadable = {product: 'producto no identificado', match_status: 'unreadable', confidence: 0, facings: 1, image_index: 1,
  image_size: [1000, 2000], boxes: [[10, 10, 90, 200]]};
const hole = {product: 'espacio vacío', match_status: 'gap', out_of_stock: true, facings: 0, source: 'geometry', image_index: 0,
  boxes: [[400, 200, 520, 400]]};
const inferred = {product: 'AXE MUSK', match_status: 'gap', out_of_stock: true, facings: 0, source: 'prior', image_index: 0};

test('each product falls in one precision class', () => {
  assert.equal(precisionClass(pack), 'seguro');
  assert.equal(precisionClass(doubtful), 'por_confirmar');
  assert.equal(precisionClass(counted), 'seguro'); // the identity is sure; only its count may change: tooltip, not color
  assert.equal(precisionClass({...doubtful, count_uncertain: true}), 'por_confirmar');
  assert.equal(precisionClass(unknown), 'sin_identificar');
  assert.equal(precisionClass(unreadable), 'sin_identificar');
  assert.equal(precisionClass({match_status: 'foreign'}), 'sin_identificar');
  assert.equal(precisionClass(hole), 'hueco');
  assert.equal(precisionClass(inferred), null); // a gap the planogram infers is not a hole in the photo
});

test('a pack draws one rectangle per can and photo by photo', () => {
  const products = [pack, doubtful, unknown, hole, inferred, unreadable];
  const first = overlayFor(products, 0);
  assert.equal(first.length, 7); // 4 cans + doubtful + unknown + hole
  assert.deepEqual(first.filter(r => r.cls === 'seguro').map(r => r.box), pack.boxes);
  assert.equal(overlayFor(products, 1).length, 1);
  assert.deepEqual(imageSizeFor(products, 0), [1688, 3000]);
  assert.deepEqual(imageSizeFor(products, 1), [1000, 2000]);
  assert.equal(imageSizeFor(products, 2), null);
  assert.equal(new Set(first.map(r => r.key)).size, first.length);
});

test('broken or missing boxes draw nothing, and readings without boxes have no map', () => {
  const broken = {...doubtful, boxes: [[10, 10, 5, 50], [1, 2, 3], 'x', [0, 0, 10, 10]]};
  assert.deepEqual(overlayFor([broken], 0).map(r => r.box), [[0, 0, 10, 10]]);
  const old = [{...pack, boxes: undefined, image_size: undefined}, {...unknown, boxes: undefined}];
  assert.equal(hasPrecisionBoxes(old), false);
  assert.equal(overlayFor(old, 0).length, 0);
  assert.equal(hasPrecisionBoxes([pack]), true);
});

test('tooltips name the product, its class, its confidence and its pack', () => {
  assert.equal(tooltip(pack), 'Pack Rexona Clinical Men · Identificado seguro · confianza 93 % · pack de 2 (4 latas)');
  assert.equal(tooltip(unknown), 'producto no identificado · Sin identificar · confianza 12 %');
  assert.equal(tooltip(counted), 'Nivea Clinical · Identificado seguro · confianza 100 % · caras por confirmar');
  assert.equal(tooltip({...unknown, count_uncertain: true}), 'producto no identificado · Sin identificar · confianza 12 %');
  assert.equal(tooltip(hole), 'Hueco');
  assert.equal(tooltip({...hole, product: 'AXE MUSK'}), 'Hueco · falta AXE MUSK');
});

test('the summary counts facings, one per hole, and weighs confidence by facings', () => {
  const s = precisionSummary([pack, doubtful, counted, unknown, unreadable, hole, inferred]);
  const by = Object.fromEntries(s.classes.map(c => [c.cls, c]));
  assert.equal(s.total, 7); // pack 2 + doubtful 1 + counted 1 + unknown 1 + unreadable 1 + hole 1
  assert.deepEqual([by.seguro.count, by.por_confirmar.count, by.sin_identificar.count, by.hueco.count], [3, 1, 2, 1]);
  assert.deepEqual(s.classes.map(c => c.pct), [43, 14, 29, 14]);
  assert.equal(Math.round(s.meanConfidence * 100), Math.round((0.93 * 2 + 0.45 + 1) / 4 * 100));
  assert.equal(precisionSummary([]).total, 0);
  assert.equal(precisionSummary([]).meanConfidence, null);
  assert.match(LEGEND, /^Verde: identificado seguro · Amarillo: identificado, por confirmar · Rojo: sin identificar · Gris: hueco$/);
});
