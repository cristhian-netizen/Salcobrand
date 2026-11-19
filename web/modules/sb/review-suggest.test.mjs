import test from 'node:test';
import assert from 'node:assert/strict';
import {suggestionState, preselect, applySuggestions, suggestSummary} from './review-suggest.mjs';

test('a confident suggestion pre-selects; NINGUNO or low confidence pre-selects nothing and says so', () => {
  const good = {suggestion: {title: 'Producto A', confidence: 0.91}};
  assert.deepEqual(suggestionState(good), {kind: 'ok', title: 'Producto A', pct: 91});
  assert.equal(preselect(good, 'Otro'), 'Producto A');
  for (const suggestion of [{title: null, confidence: 0.9}, {title: 'Producto A', confidence: 0.4}, {title: 'Producto A', confidence: null}]) {
    assert.equal(suggestionState({suggestion}).kind, 'sin-sugerencia');
    assert.equal(preselect({suggestion}, 'Otro'), '');
  }
  assert.equal(suggestionState({}).kind, 'none');
  assert.equal(preselect({}, 'Otro'), 'Otro'); // without IA the engine's first candidate keeps pre-selecting
});

test('fresh suggestions attach to their reading and item only', () => {
  const payloads = [
    {reading_id: 1, items: [{image_index: 0, item_index: 0}, {image_index: 0, item_index: 1}]},
    {reading_id: 2, items: [{image_index: 0, item_index: 0}]},
  ];
  const next = applySuggestions(payloads, 1, [{image_index: 0, item_index: 1, title: 'X', confidence: 0.8}]);
  assert.equal(next[0].items[0].suggestion, undefined);
  assert.equal(next[0].items[1].suggestion.title, 'X');
  assert.equal(next[1], payloads[1]);
});

test('the notification states every count in Spanish', () => {
  assert.equal(suggestSummary({sugeridos: 2, sin_sugerencia: 1, en_cache: 3, errores: 0}),
    'IA: 2 con sugerencia · 1 sin sugerencia · 3 ya sugeridos. Confirma o corrige cada recorte.');
  assert.match(suggestSummary({sugeridos: 0, sin_sugerencia: 0, en_cache: 0, errores: 1, error: 'Se alcanzó el límite de Gemini. Reintenta en unos minutos.'}),
    /1 con error \(Se alcanzó el límite/);
  assert.match(suggestSummary({}), /sin recortes pendientes/);
});
