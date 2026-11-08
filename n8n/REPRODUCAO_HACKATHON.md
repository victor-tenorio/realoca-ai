# Realoca AI — reprodução do n8n/Slack (V01, V16)

**Estado verificado em 08/11/2026:** o trio adotou **n8n Cloud** em vez de instalar
n8n local: \`https://vtl2026.app.n8n.cloud\`. A instância publicou o workflow
"Realoca AI | Slack → API v2 (TESTE)" com webhook Production
\`realoca-ai-notificacoes-v2\`. No ambiente real a equipe observou cinco
\`offer.dispatched\` na auditoria, clique **Aceitar** no Slack com
\`offer.accepted\` e, após correção de precisão do PR #23, uma execução
n8n #15 (retry da #13) concluída e \`offer.expired\` seguido de
\`plan.replanned\` persistidos. Isso demonstra a instância funcional.
**Não** significa que um segundo colega já refez a instalação do zero.

## Artefatos compartilhados (sem segredos)

- \`n8n/workflows/realoca-slack-api-v2.template.json\`: fluxo principal,
  *desativado* por padrão, 6 nós, webhook -> validação -> Slack
  Send and Wait -> resposta -> normalização -> callback HTTP.
- \`n8n/workflows/realoca-operational-alerts.template.json\`: auxiliar
  para V11/V13/V14, *não publicado na instância por padrão*.
- \`n8n/tests/workflow-v2.test.mjs\` e
  \`n8n/tests/operational-alerts.test.mjs\`: contrato, ids e respostas;
  não são testes contra o Slack real.
- \`n8n/OPERATIONS.md\`: configuração e limites dos alertas.
- \`scripts/verify_hackathon.ps1\`: validação local e plano de teste real
  **somente quando explicitamente solicitado**.

## Restaurar em outra conta n8n Cloud (Amanda/Mateus)

1. Criar/abrir instância Cloud e escolher **Import from File** para o
   \`realoca-slack-api-v2.template.json\`. **Não** publicar ainda.
2. No primeiro **Webhook**, selecionar credencial **Header Auth** com
   header \`X-Internal-Token\` e o valor acordado em privado para
   \`N8N_DISPATCH_TOKEN\`; path
   \`realoca-ai-notificacoes-v2\`. Não publicar dois fluxos com
   o mesmo webhook na mesma instância.
3. No nó Slack \`Send a message\`, selecionar credencial OAuth autorizada,
   operação \`sendAndWait\`, e canal de demo \`#novo-canal\`. A equipe usa
   **canal compartilhado**, **não DM individual**, e IDs dos funcionários são
   sintéticos; nenhuma identidade real de funcionário é validada.
4. No nó \`Enviar callback ao backend\`, selecionar **Header Auth** com
   \`X-Internal-Token\` igual a \`INTEGRATIONS_INTERNAL_TOKEN\` do FastAPI,
   e URL da API disponível naquele momento
   \`https://SEU-TUNEL/api/v1/integrations/attempt-events\`.
   O Quick Tunnel é **temporário**, não é URL de produção estável.
5. Publicar workflow; no servidor FastAPI, configurar
   \`N8N_DISPATCH_URL\` para a URL **Production** do Webhook publicado e
   \`N8N_DISPATCH_TOKEN\` para o header de entrada. Em um PowerShell com
   os segredos em variável de ambiente, usar \`app.services.dispatch\`
   para reenviar somente ofertas válidas/reservadas se necessário;
   **não repetir** POST \`/plan\` em caso com propostas ativas.
6. Para testar o fluxo, gerar caso **fictício novo**; conferir que a API
   registra \`offer.queued\` e \`offer.dispatched\`; clicar Aceitar no Slack;
   consultar \`GET /api/v1/cases/{case_id}\` e
   \`GET /api/v1/audit?case_id={case_id}\` para ver \`offer.accepted\`.
   Teste de recusa exige um convite ainda dentro do prazo. Para timeout,
   observar \`offer.expired\` e \`plan.replanned\`; o backend inclui a
   correção de precisão de microssegundos do PR #23.
7. Quem importar assinala os três fatos: workflow publicado, callback
   recebido no backend, e um evento de auditoria real. Capturar print da
   execução n8n (sem tokens) e anexar ao checklist de handoff.

## Reproduzir testes sem depender da máquina da Amanda

    node --test n8n/tests/*.test.mjs

O GitHub Actions em \`.github/workflows/verify.yml\` executa estes testes
e toda a suíte Python automaticamente em cada PR/push. No PR #23,
foram **341 testes Python aprovados** além dos testes de n8n.

## Fatos comprovados versus pendências

- Comprovado no ambiente real: import/publicação, mensagens no canal Slack,
  **cinco** ofertas despachadas, aceite processado e timeout com
  replanejamento (após PR #23).
- Simuladores e código validados: recusa com motivo, proteção contra
  duplicidade, avisos de BP e lembretes; os testes automatizados
  não se confundem com E2E publicado.
- Não comprovado: **reimportação independente por Mateus ou Amanda**,
  DM para destinatário correto, execução dos alertas auxiliares na instância
  n8n, e recusa efetiva no backend durante uma sessão de Slack.
  Esses fatos não devem ser descritos como testados.

**Segurança:** nunca exportar credenciais reais nem colocar token/URL privada
com segredo em commits; usar dados sintéticos e desativar túnel após a demo.
