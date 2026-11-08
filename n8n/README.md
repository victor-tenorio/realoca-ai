# n8n ↔ Slack ↔ FastAPI — handoff do Realoca AI

**Status:** adaptadores de validação e conversão versionados; ainda **não importados nem testados no workflow real**. O n8n da equipe já possui Webhook, Slack "Send and Wait for Response" e um Code node "Registrar resposta da proposta". Não substitua esse fluxo sem exportá-lo primeiro.

## Contratos verificáveis
- Saída real do backend: 'offer.created' com os 14 campos listados em 'docs/payload-n8n.json' e 'app/services/dispatch.py::offer_payload'.
- Entrada na API: POST /api/v1/integrations/attempt-events. O body JSON aceita **somente** 'event_id', 'event_type', 'attempt_id', 'channel', 'occurred_at' e 'reason'. 'event_type' é 'offer.accepted', 'offer.refused' ou 'offer.expired'; para este adaptador, apenas as duas primeiras opções.
- Não enviar 'decision', 'responded_at', 'decline_reason', 'source', 'channel_user_id' ou 'case_id' como campos extras à API: o schema rejeita campos extras com HTTP 422.
- Header obrigatório para o callback: 'X-Internal-Token', definido por credencial **HTTP Header Auth** do n8n, com o mesmo valor privado de 'INTEGRATIONS_INTERNAL_TOKEN' no backend.
- **Não** reutilizar 'N8N_DISPATCH_TOKEN' como valor do callback por acaso: são direções e configurações distintas.

## Como adaptar o workflow n8n existente
1. **Antes de editar**: no workflow "Realoca AI | Notificações e Confirmações", faça Download/Export do JSON; não inclua credenciais reais no arquivo. Preserve uma cópia desse export em 'n8n/'.
2. No Webhook de entrada, configure autenticação nativa **Header Auth** com header 'X-Internal-Token' e segredo correspondente a 'N8N_DISPATCH_TOKEN' do backend; use resposta imediata HTTP 200/202, não "when last node finishes" — o Slack pode esperar a pessoa responder.
3. Depois do Webhook, insira Code "Validar proposta Realoca" com o código de 'n8n/validate-offer.js'. Só envio válido deve seguir ao Slack; falha não deve disparar convite. Teste com dados **fictícios**.
4. No Slack, use o destinatário explicitamente mapeado de 'channel_user_id' **somente se for um usuário Slack válido** (não confundir ID de canal ou '#novo-canal' com DM). O canal fixo atual serve apenas à demonstração compartilhada; não afirma destinatário validado.
5. Depois de "Registrar resposta da proposta" (que produz 'decision' = 'accepted'/'declined' e 'responded_at'), adicione Code "Converter resposta para API" com 'n8n/normalize-callback.js'.
6. Conecte um node **HTTP Request**: Method POST; URL = BASE_URL_PUBLICA + '/api/v1/integrations/attempt-events'; Authentication = Generic Credential Type / HTTP Header Auth; Name = 'X-Internal-Token'; Value = segredo privado da variável 'INTEGRATIONS_INTERNAL_TOKEN' da API. Configure 'Send Body = true', 'Body Content Type = JSON', 'Specify Body = Using JSON', body expression '={{ $json }}'. Nunca cole tokens no próprio workflow.
7. Trate 202 como **recebido na inbox**, não como confirmação da alteração; cheque depois 'GET /api/v1/cases/{case_id}' e 'GET /api/v1/audit?case_id=...'. HTTP 409 pode significar resposta repetida, fora do prazo ou conflito e **não deve** provocar reenvio cego; 401/503 requer revisão de token/configuração.
8. Na máquina da Amanda, depois de atualizar a main e aplicar migrations, configure: 'INTEGRATIONS_INTERNAL_TOKEN', 'N8N_DISPATCH_URL' (URL da aba **Production** do webhook publicado) e 'N8N_DISPATCH_TOKEN' (valor esperado pela credencial de autenticação do Webhook n8n). Reinicie o backend para carregar as variáveis. Não compartilhe os valores em chat, GitHub ou prints.
9. Teste um caso **novo** com ausência confirmada, chame 'POST /api/v1/cases/{case_id}/plan'; se houver proposta automática e destinatário válido, o backend enfileira 'offer.created' e despacha para o n8n. Se exigir BP, aprove via 'POST /api/v1/proposals/{attempt_id}/approval' antes do envio. Após Slack, aceite ou recuse e confira auditoria/realocação.
10. Teste repetição, atraso, indisponibilidade e expiração em ambiente fictício antes de marcar V08–V17 como concluídas; documente horário, status HTTP, IDs e diferenças entre execução real e mock.

## Cuidados
- A URL 'trycloudflare.com' é **temporária**; não use como URL de deploy estável.
- **Não** publicar um backend mutável sem proteção em produção. O Quick Tunnel expõe endpoints de consulta e de alteração da demo; use somente dados fictícios e desligue-o após os testes.
- A resposta atual do n8n pode ter o campo 'event_id' de entrada. O adaptador gera ID **novo, determinístico** por tentativa/decisão, para não reutilizar o ID de 'offer.created'. Repetir mesmo evento deve conservar 'occurred_at' original; se mudar o timestamp, a API pode rejeitar como colisão 409 — situação segura, sem duplicar atribuição.
- O backend recusa callback para tentativa inexistente, prazo passado, canal incompatível ou oferta nunca enviada. Não forjar IDs nos testes reais: obtenha IDs de caso/tentativa da própria API.
- **V10/V11** (expiração/lembrete) e **V13/V14/V15/V17** exigem testes adicionais no workflow real; estes scripts não implementam esses requisitos por si.
- Nenhum teste documentado aqui prova integração n8n real; o fluxo atual deve ser exportado/importado e executado para validar.

## Teste rápido SEM n8n
Em projeto local que tenha Node.js 18+: 'node --test n8n/tests/normalizers.test.mjs'. Valida o Code node com entradas fictícias sem abrir n8n nem usar créditos.
