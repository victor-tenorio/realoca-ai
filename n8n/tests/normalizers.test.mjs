import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const runCode = (path, value, now = Date.parse('2026-11-08T12:00:00Z')) => {
  const source = readFileSync(new URL('../' + path, import.meta.url), 'utf8');
  class FakeDate extends Date { static now() { return now; } }
  return runInNewContext('(function () { ' + source + '\n})()', {
    $input: { first() { return { json: value }; } },
    Date: FakeDate, Number, String, Error,
  });
};
const payload = {
  event_id: 'evt-out-test', event_type: 'offer.created',
  case_id: 'case-1', attempt_id: 'att-1', task_id: 'task-1',
  task_title: 'Relatório', candidate_employee_id: 'emp-1',
  candidate_name: 'Demo', channel_user_id: 'U_TEST',
  channel: 'slack', estimated_hours: 2,
  due_at: '2026-11-09T12:00:00Z',
  response_deadline_at: '2026-11-09T11:00:00Z',
  message: 'Aceitar / Recusar',
};
test('valid n8n webhook payload preserves outbound IDs', () => {
  const [out] = runCode('validate-offer.js', { body: payload });
  assert.deepEqual(Object.keys(out.json).sort(), Object.keys(payload).sort());
  assert.equal(out.json.attempt_id, 'att-1');
});
test('wrong channel and empty attempt fail closed', () => {
  assert.throws(() => runCode('validate-offer.js', { body: { ...payload, channel: 'teams' } }), /INVALID_OFFER/);
  assert.throws(() => runCode('validate-offer.js', { body: { ...payload, attempt_id: '' } }), /INVALID_OFFER/);
});
test('accepted callback uses exact backend contract', () => {
  const x = { attempt_id:'att-1', decision:'accepted', channel:'slack', responded_at:'2026-11-08T09:05:00-03:00' };
  const [out] = runCode('normalize-callback.js', x);
  assert.deepEqual(Object.keys(out.json).sort(), ['event_id','event_type','attempt_id','channel','occurred_at','reason'].sort());
  assert.equal(out.json.event_type, 'offer.accepted');
  assert.equal(out.json.occurred_at, '2026-11-08T12:05:00.000Z');
  assert.equal(out.json.reason, null);
  assert.equal(out.json.event_id, runCode('normalize-callback.js', x)[0].json.event_id);
});
test('declined callback propagates the reason', () => {
  const [out] = runCode('normalize-callback.js', {
    attempt_id:'att-2', decision:'declined', source:'slack',
    responded_at:'2026-11-08T12:05:00Z', decline_reason:'Falta de tempo',
  });
  assert.equal(out.json.event_type, 'offer.refused');
  assert.equal(out.json.reason, 'Falta de tempo');
  assert.equal(out.json.event_id, 'evt-n8n-att-2-refused');
});
test('malformed/unknown callback is rejected before HTTP', () => {
  assert.throws(() => runCode('normalize-callback.js', { attempt_id:'', decision:'accepted', channel:'slack', responded_at:'2026-11-08T12:05:00Z' }), /INVALID_CALLBACK/);
  assert.throws(() => runCode('normalize-callback.js', { attempt_id:'att-1', decision:'approved', channel:'slack', responded_at:'2026-11-08T12:05:00Z' }), /INVALID_CALLBACK/);
  assert.throws(() => runCode('normalize-callback.js', { attempt_id:'att-1', decision:'accepted', channel:'slack', responded_at:'2026-11-08T12:05:00' }), /INVALID_CALLBACK/);
  assert.throws(() => runCode('normalize-callback.js', { attempt_id:'att-1', decision:'accepted', channel:'teams', responded_at:'2026-11-08T12:05:00Z' }), /INVALID_CALLBACK/);
});
