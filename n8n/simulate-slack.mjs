/**
 * V04 - simulator local de resposta Slack, usando a conversão do próprio V2.
 * Node.js >=18. Apenas 127.0.0.1; sem credenciais no código.
 * PREVIEW é o padrão; envio real exige URL e segredo no ambiente.
 */
import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';

const template = JSON.parse(readFileSync(new URL('./workflows/realoca-slack-api-v2.template.json', import.meta.url), 'utf8'));
const normalizer = template.nodes.find(node => node.name === 'Converter resposta para API');
if (!normalizer?.parameters?.jsCode) throw new Error('Normalizer missing from V2 template');

function reply(res, status, data) {
  res.writeHead(status, {'content-type':'application/json; charset=utf-8','cache-control':'no-store'});
  res.end(JSON.stringify(data));
}

export function simulateSlackResponse(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('Expected JSON object');
  if (typeof body.attempt_id !== 'string' || !body.attempt_id.trim()) throw new Error('attempt_id required');
  if (!['accepted','declined'].includes(body.decision)) throw new Error('decision must be accepted or declined');
  if (typeof body.responded_at !== 'string' || !body.responded_at.trim()) throw new Error('responded_at required');
  const x = {
    attempt_id:body.attempt_id, decision:body.decision,
    responded_at:body.responded_at, channel:'slack', source:'slack',
    decline_reason: typeof body.reason === 'string' ? body.reason : null,
  };
  const result = runInNewContext('(function(){'+normalizer.parameters.jsCode+'\n})()', {
    $input:{first:()=>({json:x})}, Date, String, Number, Error,
  }, {timeout:1000});
  return JSON.parse(JSON.stringify(result[0].json));
}

export function createSimulator({forwardUrl='', token='', fetchImpl=globalThis.fetch} = {}) {
  if (Boolean(forwardUrl) !== Boolean(token)) throw new Error('Forwarding requires URL and token together');
  if (forwardUrl) {
    const url = new URL(forwardUrl);
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost','127.0.0.1'].includes(url.hostname)))
      throw new Error('HTTPS required except localhost');
    if (url.pathname !== '/api/v1/integrations/attempt-events')
      throw new Error('Only the authorized callback endpoint is supported');
  }
  return createServer(async (req,res) => {
    if (req.method !== 'POST' || req.url !== '/simulate') return reply(res,404,{error:'Use POST /simulate'});
    if (!String(req.headers['content-type']||'').toLowerCase().startsWith('application/json'))
      return reply(res,415,{error:'Expected application/json'});
    const chunks=[];let size=0;
    for await (const part of req) {
      size += part.length;
      if (size > 8192) return reply(res,413,{error:'Payload too large'});
      chunks.push(part);
    }
    let callback;
    try { callback = simulateSlackResponse(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
    catch(error) { return reply(res,400,{error:error.message}); }
    if (!forwardUrl) return reply(res,200,{mode:'preview',callback,applied:false});
    try {
      const api=await fetchImpl(forwardUrl,{
        method:'POST',headers:{'content-type':'application/json','X-Internal-Token':token},
        body:JSON.stringify(callback), signal:AbortSignal.timeout(10000),
      });
      return reply(res,api.ok?200:502,{mode:'forwarded',api_status:api.status,event_id:callback.event_id,applied:false});
    } catch (_) {
      return reply(res,502,{error:'Callback transport failed',event_id:callback.event_id});
    }
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const url=process.env.SIMULATOR_CALLBACK_URL||'';
  const token=process.env.INTEGRATIONS_INTERNAL_TOKEN||'';
  const port=Number(process.env.SIMULATOR_PORT||8765);
  const server=createSimulator({forwardUrl:url,token});
  server.listen(port,'127.0.0.1',()=>console.log('V04 simulator: http://127.0.0.1:'+port+'/simulate - '+(url?'FORWARDING ENABLED':'PREVIEW ONLY')));
}
