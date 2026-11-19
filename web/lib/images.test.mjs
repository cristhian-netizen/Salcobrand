import test from 'node:test';
import assert from 'node:assert/strict';
import {imageUrl} from './images.mjs';

test('image urls carry no per-tab parameter and ask for a width only when given', () => {
  assert.equal(imageUrl('/uploads/point-a/x.jpg'), '/uploads/point-a/x.jpg');
  assert.equal(imageUrl('/uploads/point-a/x.jpg', 256), '/uploads/point-a/x.jpg?w=256');
  assert.equal(imageUrl('/api/readings/9/crops/0/1.jpg', 128), '/api/readings/9/crops/0/1.jpg?w=128');
  assert.equal(imageUrl('/uploads/x.jpg?size=2', 256), '/uploads/x.jpg?size=2&w=256');
});

test('data uris, foreign urls and empty values pass through untouched', () => {
  const data = 'data:image/png;base64,AAAA';
  assert.equal(imageUrl(data, 256), data);
  assert.equal(imageUrl('https://other.example/x.jpg', 256), 'https://other.example/x.jpg');
  assert.equal(imageUrl('', 256), '');
  assert.equal(imageUrl(null, 256), null);
});
