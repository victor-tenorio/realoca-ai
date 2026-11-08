// n8n Code node: "Converter resposta para API" (Run Once for All Items).
// Input: the existing "Registrar resposta da proposta" Code node output.
// Expected: attempt_id, decision (accepted/declined), responded_at, channel/source, decline_reason.
const x = $input.first().json;
const attemptId = String(x.attempt_id || '').trim();
const decision = String(x.decision || '').trim().toLowerCase();
const channel = String(x.channel || x.source || '').trim().toLowerCase();
if (!attemptId || attemptId.length > 130) throw new Error('INVALID_CALLBACK: attempt_id');
if (!['accepted', 'declined'].includes(decision)) throw new Error('INVALID_CALLBACK: decision');
if (channel !== 'slack') throw new Error('INVALID_CALLBACK: channel/source');
if (!x.responded_at || typeof x.responded_at !== 'string' ||
    !/(Z|[+-][0-9]{2}:[0-9]{2})$/i.test(x.responded_at)) {
  throw new Error('INVALID_CALLBACK: responded_at requires timezone');
}
const when = new Date(x.responded_at);
if (!Number.isFinite(when.getTime())) throw new Error('INVALID_CALLBACK: responded_at');
const refused = decision === 'declined';
// Deterministic per attempt/decision: retries preserve event_id.
// A different/late response is rejected by the backend; never reassign here.
const eventId = 'evt-n8n-' + attemptId + '-' + (refused ? 'refused' : 'accepted');
const reason = refused ? (String(x.decline_reason || '').trim() || 'Recusa registrada no Slack') : null;
return [{ json: {
  event_id: eventId,
  event_type: refused ? 'offer.refused' : 'offer.accepted',
  attempt_id: attemptId,
  channel: 'slack',
  occurred_at: when.toISOString(),
  reason,
} }];