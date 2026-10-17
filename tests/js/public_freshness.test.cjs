const test = require('node:test');
const assert = require('node:assert/strict');
const {classify, relative} = require('../../birdframe/public_template/freshness.js');
const checkedAt = '2026-10-18T00:00:00+00:00', start = Date.parse(checkedAt);
const current = {checkedAt, recorder:'listening', staleAfterSeconds:900};

test('recent healthy audio is online without a single bird detection', () => {
  assert.equal(classify(current, start + 300_000).state, 'online');
  assert.equal(classify(current, start + 899_000).state, 'online');
});
test('missed check-ins become stale even if the last status was healthy', () => {
  const result = classify(current, start + 900_000);
  assert.equal(result.state, 'stale');
  assert.equal(result.label, 'Recorder not reporting');
});
test('paused and unhealthy recorders never show a green online state', () => {
  assert.equal(classify({...current, recorder:'paused'}, start).state, 'paused');
  assert.equal(classify({...current, recorder:'attention'}, start).state, 'attention');
  assert.equal(classify({...current, recorder:'starting'}, start).state, 'starting');
});
test('missing or unverifiable status and future clocks cannot imply online', () => {
  for (const status of [null, {}, {...current, checkedAt:'invalid'},
      {...current, checkedAt:'2026-10-18T00:00:00'}, {...current, staleAfterSeconds:null}]) {
    assert.equal(classify(status, start).state, 'unknown');
  }
  assert.equal(classify(current, start - 121_000).state, 'unknown');
});
test('network errors retain the last-check time but never assert online', () => {
  assert.equal(classify(current, start + 120_000, true).label, 'Unable to check recorder');
  assert.equal(classify(current, start + 900_000, true).state, 'stale');
});
test('relative timestamps age independently of uploads', () => {
  assert.equal(relative(checkedAt, start + 10_000), 'just now');
  assert.equal(relative(checkedAt, start + 120_000), '2 min ago');
  assert.equal(relative(checkedAt, start + 3600_000), '1 hour ago');
  assert.equal(relative('invalid', start), 'Unavailable');
});
