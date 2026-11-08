// n8n Code node: "Validar proposta Realoca" (Run Once for All Items).
// Place immediately after the incoming production Webhook and before Slack.
const raw = $input.first().json;
const p = raw.body && typeof raw.body === 'object' ? raw.body : raw;
const mandatory = ['event_id','case_id','attempt_id','task_id','task_title','candidate_employee_id','candidate_name','channel_user_id','response_deadline_at','due_at','message'];
for (const field of mandatory) {
  if (typeof p[field] !== 'string' || !p[field].trim()) {
    throw new Error('INVALID_OFFER: missing ' + field);
  }
}
if (p.event_type !== 'offer.created' || p.channel !== 'slack') {
  throw new Error('INVALID_OFFER: event_type/channel');
}
if (typeof p.estimated_hours !== 'number' || !Number.isFinite(p.estimated_hours) || p.estimated_hours <= 0) {
  throw new Error('INVALID_OFFER: estimated_hours');
}
const deadline = new Date(p.response_deadline_at).getTime();
const due = new Date(p.due_at).getTime();
if (!Number.isFinite(deadline) || !Number.isFinite(due) || deadline <= Date.now()) {
  throw new Error('INVALID_OFFER: deadline or due_at');
}
// No automatic business decision here. Backend remains the authority.
return [{ json: { ...p } }];