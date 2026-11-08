import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const flow = JSON.parse(readFileSync(new URL('../workflows/realoca-operational-alerts.template.json', import.meta.url), 'utf8'));
const byName = Object.fromEntries(flow.nodes.map(n=>[n.name,n]));
const check = input => runInNewContext('(function(){'+byName['Validar alerta'].parameters.jsCode+'\n})()',{
  $input:{first:()=>({json:{body:input}})},Error,Number,String,Array,
},{timeout:1000})[0].json;

const base={event_type:'offer.reminder',event_id:'evt-op-1',case_id:'case-1',attempt_id:'att-1',channel:'slack',message:'Lembrete da oferta'};

test('alert workflow is inactive, connected, and never waits for response',()=>{
  assert.equal(flow.active,false);
  assert.equal(flow.nodes.length,3);
  assert.equal(byName['Webhook alertas'].parameters.authentication,'headerAuth');
  assert.equal(byName['Enviar aviso Slack'].parameters.operation,'post');
  assert.equal(byName['Enviar aviso Slack'].parameters.messageType,'text');
  assert.equal(flow.connections['Webhook alertas'].main[0][0].node,'Validar alerta');
  assert.equal(flow.connections['Validar alerta'].main[0][0].node,'Enviar aviso Slack');
  assert.ok(flow.nodes.every(n=>!n.credentials));
  assert.equal(byName['Enviar aviso Slack'].parameters.channelId.value,'');
});

test('reminder, BP and failure alerts preserve exact IDs',()=>{
  for(const event_type of ['offer.reminder','bp.approval_requested','offer.delivery_escalated']){
    const result=check({...base,event_type});
    assert.equal(result.event_type,event_type);
    assert.equal(result.attempt_id,base.attempt_id);
    assert.equal(result.case_id,base.case_id);
  }
});

test('wrong channels, arbitrary event types, and incomplete alerts are rejected',()=>{
  for(const invalid of [
    {...base,channel:'teams'},
    {...base,event_type:'offer.accepted'},
    {...base,attempt_id:''},
    {...base,message:''},
  ])assert.throws(()=>check(invalid),/INVALID_ALERT/);
});

test('alerts contain no approval operation or callback HTTP node',()=>{
  assert.ok(flow.nodes.every(n=>n.type!=='n8n-nodes-base.httpRequest'));
  assert.ok(!flow.nodes.some(n=>/approve|sendAndWait|approval/i.test(n.parameters.operation||'')));
});
