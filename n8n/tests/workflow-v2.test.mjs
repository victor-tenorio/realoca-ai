import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const workflow = JSON.parse(readFileSync(new URL('../workflows/realoca-slack-api-v2.template.json', import.meta.url), 'utf8'));
const nodes = Object.fromEntries(workflow.nodes.map((node) => [node.name, node]));
function runNode(node, input, currentTime = '2026-11-08T12:00:00Z') {
  const code = nodes[node].parameters.jsCode;
  const now = Date.parse(currentTime);
  class DateAt extends Date { static now() { return now; } }
  return runInNewContext('(function(){' + code + '\n})()', {
    $input: { first() { return { json: input }; } },
    Date: DateAt, Number, String, Error,
  })[0].json;
}

test('workflow is inactive and has six connected nodes', () => {
  assert.equal(workflow.active, false);
  assert.equal(workflow.nodes.length, 6);
  assert.equal(new Set(workflow.nodes.map((node) => node.name)).size, 6);
  assert.equal(nodes.Webhook.parameters.path, 'realoca-ai-notificacoes-v2');
  const seen = new Set();
  let current = 'Webhook';
  while (current) {
    assert.ok(!seen.has(current), 'cycle');
    seen.add(current);
    current = workflow.connections[current]?.main?.[0]?.[0]?.node;
  }
  assert.equal(seen.size, 6);
  assert.equal(nodes['Enviar callback ao backend'].parameters.genericAuthType, 'httpHeaderAuth');
});

test('template contains no real credential or channel IDs', () => {
  for (const node of workflow.nodes) assert.ok(!node.credentials);
  assert.equal(nodes['Send a message'].parameters.channelId.value, '');
  assert.match(nodes['Enviar callback ao backend'].parameters.url, /^https:\/\/SEU-BACKEND-PUBLICO\.example/);
});

test('valid offer retains IDs; malformed offers rejected before Slack', () => {
  const offer = {
    event_id: 'evt-out-demo', event_type: 'offer.created', case_id: 'case-1',
    attempt_id: 'att-1', task_id: 'task-1', task_title: 'Relatorio',
    candidate_employee_id: 'emp-1', candidate_name: 'Demo',
    channel_user_id: 'U_DEMO', channel: 'slack',
    due_at: '2026-11-10T15:00:00Z', response_deadline_at: '2026-11-09T15:00:00Z',
    estimated_hours: 2, message: 'Aceitar ou Recusar'
  };
  assert.equal(runNode('Code in JavaScript', { body: offer }).attempt_id, 'att-1');
  assert.throws(() => runNode('Code in JavaScript', { body: { ...offer, attempt_id: '' }}), /INVALID_OFFER/);
  assert.throws(() => runNode('Code in JavaScript', { body: { ...offer, channel: 'teams' }}), /INVALID_OFFER/);
});

test('accept sends exact callback schema', () => {
  const result = runNode('Converter resposta para API', {
    attempt_id: 'att-1', decision: 'accepted', channel: 'slack', source: 'slack',
    responded_at: '2026-11-08T09:02:00-03:00',
  });
  assert.deepEqual(Object.keys(result).sort(), ['event_id','event_type','attempt_id','channel','occurred_at','reason'].sort());
  assert.equal(result.event_type, 'offer.accepted');
  assert.equal(result.occurred_at, '2026-11-08T12:02:00.000Z');
  assert.equal(result.event_id, 'evt-n8n-att-1-accepted');
});

test('refusal keeps reason and distinct event id', () => {
  const result = runNode('Converter resposta para API', {
    attempt_id: 'att-1', decision: 'declined', channel: 'slack', source: 'slack',
    responded_at: '2026-11-08T09:02:00-03:00', decline_reason: 'Sem disponibilidade'
  });
  assert.equal(result.event_type, 'offer.refused');
  assert.equal(result.event_id, 'evt-n8n-att-1-refused');
  assert.equal(result.reason, 'Sem disponibilidade');
});

test('expiry is blocked until deadline and then uses stable deadline timestamp', () => {
  const payload = {
    attempt_id: 'att-1', decision: 'expired', channel: 'slack', source: 'slack',
    response_deadline_at: '2026-11-08T12:15:00Z'
  };
  assert.throws(() => runNode('Converter resposta para API', payload), /INVALID_CALLBACK/);
  const result = runNode('Converter resposta para API', payload, '2026-11-08T12:15:01Z');
  assert.equal(result.event_type, 'offer.expired');
  assert.equal(result.event_id, 'evt-n8n-att-1-expired');
  assert.equal(result.occurred_at, '2026-11-08T12:15:00.000Z');
  assert.equal(nodes['Send a message'].parameters.options.limitWaitTime.values.limitType, 'atSpecifiedTime');
});
