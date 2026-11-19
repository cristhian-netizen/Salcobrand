import test from 'node:test';
import assert from 'node:assert/strict';
import {parseToken, stateOf, messageFor, counterText, progressText, remainingText,
        freshSession, afterUpload, retryQueue} from './captura.mjs';

const TOKEN = 'A'.repeat(43);

test('the token comes from the hash and anything malformed means no link at all', () => {
  assert.equal(parseToken('#' + TOKEN), TOKEN);
  assert.equal(parseToken(TOKEN), TOKEN); // some browsers hand the hash without '#'
  assert.equal(parseToken('#short'), null);
  assert.equal(parseToken('#' + 'A'.repeat(101)), null);
  assert.equal(parseToken('#' + TOKEN + '/../x'), null);
  assert.equal(parseToken(''), null);
  assert.equal(parseToken(undefined), null);
});

test('screen state: the link decides, and dead links collapse into one polite message', () => {
  assert.equal(stateOf({token: null}), 'inactive');
  assert.equal(stateOf({token: TOKEN, errorStatus: 401}), 'inactive');
  assert.equal(stateOf({token: TOKEN, errorStatus: 410}), 'inactive');
  assert.equal(stateOf({token: TOKEN, errorStatus: 500}), 'error');
  assert.equal(stateOf({token: TOKEN, errorStatus: 0}), 'error'); // network: retry, not "inactive"
  assert.equal(stateOf({token: TOKEN, loading: true}), 'loading');
  assert.equal(stateOf({token: TOKEN, loading: false, photosLeft: 0}), 'full');
  assert.equal(stateOf({token: TOKEN, loading: false, photosLeft: 7}), 'ready');
  assert.equal(messageFor('inactive'), 'Este enlace ya no está activo.');
  assert.equal(messageFor('full', 0), 'Este enlace ya no está activo.');
  assert.equal(messageFor('full', 12), 'Se envió todo: este enlace alcanzó su máximo de fotos. ¡Gracias!');
  assert.equal(messageFor('ready', 3), null);
});

test('wording matches the agreed copy exactly', () => {
  assert.equal(counterText(12), '12 fotos enviadas ✓');
  assert.equal(counterText(1), '1 foto enviada ✓');
  assert.equal(progressText(3, 5), 'Subiendo 3/5…');
  assert.equal(remainingText(498), 'Quedan 498 fotos disponibles');
  assert.equal(remainingText(1), 'Queda 1 foto disponible');
});

test('sequential upload bookkeeping: success counts, failure queues for retry, 409/410 stop', () => {
  const fileA = {name: 'a.jpg'};
  let state = freshSession(3);
  state = afterUpload(state, {ok: true, photosLeft: 2});
  assert.deepEqual([state.sent, state.photosLeft, state.failed], [1, 2, []]);
  state = afterUpload(state, {ok: true}); // a response without the count still decrements locally
  assert.deepEqual([state.sent, state.photosLeft], [2, 1]);
  state = afterUpload(state, {ok: false, status: 0, file: fileA, message: 'Sin conexión.'});
  assert.deepEqual([state.sent, state.failed, state.failMessage], [2, [fileA], 'Sin conexión.']);
  const retry = retryQueue(state);
  assert.deepEqual(retry.files, [fileA]);
  assert.deepEqual([retry.state.failed, retry.state.failMessage], [[], '']);
  const full = afterUpload(retry.state, {ok: false, status: 409, file: fileA});
  assert.deepEqual([full.sent, full.photosLeft, full.failed], [2, 0, []]); // what landed stays counted
  const dead = afterUpload(state, {ok: false, status: 410, file: fileA});
  assert.deepEqual([dead.photosLeft, dead.failed], [0, []]);
});
