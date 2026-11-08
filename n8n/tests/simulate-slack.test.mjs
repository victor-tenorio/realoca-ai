import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createSimulator,simulateSlackResponse} from '../simulate-slack.mjs';

const sample={attempt_id:'att-real-demo',decision:'accepted',responded_at:'2026-11-08T10:05:00-03:00'};

test('accepted: exact callback schema, preserved ID and timezone',()=>{
  const cb=simulateSlackResponse(sample);
  assert.deepEqual(Object.keys(cb).sort(),['event_id','event_type','attempt_id','channel','occurred_at','reason'].sort());
  assert.equal(cb.attempt_id,sample.attempt_id);
  assert.equal(cb.event_type,'offer.accepted');
  assert.equal(cb.event_id,'evt-n8n-att-real-demo-accepted');
  assert.equal(cb.occurred_at,'2026-11-08T13:05:00.000Z');
});

test('declined: distinct ID, reason and retry stability',()=>{
  const input={...sample,decision:'declined',reason:'Outro turno'};
  const cb=simulateSlackResponse(input);
  assert.equal(cb.event_type,'offer.refused');
  assert.equal(cb.reason,'Outro turno');
  assert.equal(cb.event_id,'evt-n8n-att-real-demo-refused');
  assert.equal(simulateSlackResponse(input).event_id,cb.event_id);
});

test('invalid inputs rejected before callback',()=>{
  assert.throws(()=>simulateSlackResponse({...sample,attempt_id:''}),/attempt_id/);
  assert.throws(()=>simulateSlackResponse({...sample,decision:'other'}),/decision/);
  assert.throws(()=>simulateSlackResponse({...sample,responded_at:'2026-11-08T10:05:00'}),/responded_at/);
});

async function withServer(server,fn){
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try { await fn('http://127.0.0.1:'+server.address().port+'/simulate'); }
  finally { await new Promise(resolve=>server.close(resolve)); }
}

test('POST webhook defaults to preview and never mutates backend',async()=>{
  await withServer(createSimulator(),async(url)=>{
    const resp=await fetch(url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(sample)});
    assert.equal(resp.status,200);
    const body=await resp.json();
    assert.equal(body.mode,'preview');
    assert.equal(body.applied,false);
    assert.equal(body.callback.event_type,'offer.accepted');
  });
});

test('optional forwarding sends A13 payload and secret only in header',async()=>{
  let count=0;
  const server=createSimulator({
    forwardUrl:'https://api.demo.example/api/v1/integrations/attempt-events',
    token:'secret-for-test',
    fetchImpl:async(url,opts)=>{
      count++;
      assert.equal(url,'https://api.demo.example/api/v1/integrations/attempt-events');
      assert.equal(opts.headers['X-Internal-Token'],'secret-for-test');
      assert.equal(JSON.parse(opts.body).event_type,'offer.refused');
      return {ok:true,status:202};
    },
  });
  await withServer(server,async(url)=>{
    const resp=await fetch(url,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({...sample,decision:'declined'})});
    assert.equal(resp.status,200);
    const body=await resp.json();
    assert.equal(body.api_status,202);
    assert.equal(body.applied,false);
    assert.equal(JSON.stringify(body).includes('secret-for-test'),false);
  });
  assert.equal(count,1);
});

test('forwarding without complete config or to unsafe target fails closed',()=>{
  assert.throws(()=>createSimulator({forwardUrl:'https://api.demo.example/api/v1/integrations/attempt-events'}),/URL and token/);
  assert.throws(()=>createSimulator({forwardUrl:'http://example.com/api/v1/integrations/attempt-events',token:'secret'}),/HTTPS/);
  assert.throws(()=>createSimulator({forwardUrl:'https://example.com/other',token:'secret'}),/authorized callback/);
});
