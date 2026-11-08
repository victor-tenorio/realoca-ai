# Encerramento das tarefas V11, V13, V14 e V15 — alertas Slack

## O que foi implementado

- **V11**: lembrete enviado **uma vez** para tentativa \`notified\` somente quando entrar na janela configurada em \`PolicyVersion.reminder_before_expiry_minutes\`; não cria nova oferta nem atribui tarefa.
- **V13**: aviso de aprovação pendente (\`pending_approval\`) com o ID da tentativa e o endpoint autorizado; o BP decide em \`POST /api/v1/proposals/{attempt_id}/approval\` com \`actor_id\`, \`decision\` e \`reason\`. Mensagem Slack **nunca** aprova automaticamente.
- **V14**: tentativas do webhook n8n limitadas a 3. Ao falhar, a reserva continua pendente, a auditoria grava \`offer.send_failed\`; na terceira falha grava \`offer.delivery_escalated\`. Worker avisa BP quando canal de alerta voltar.
- **V15**: auditoria existente em \`GET /api/v1/audit?case_id=...\` registra propostas, despachos, callbacks, recusas/replanejamento; alertas acrescentam ações próprias sem expor tokens.

## Configuração n8n (uma vez, sem substituir a V2)

1. Importe \`n8n/workflows/realoca-operational-alerts.template.json\` como **workflow novo**, mantendo a V2 principal.
2. Webhook alertas: Header Auth com \`X-Internal-Token\` = mesmo valor de \`N8N_DISPATCH_TOKEN\` no backend; path \`realoca-ai-alertas-v1\`; produção ativa.
3. Slack \`Enviar aviso Slack\`: escolha OAuth existente e canal fictício \`#novo-canal\`. A mensagem é somente notificação simples, não \`Send and Wait\`.
4. Publique/ative. Copie a URL Production do webhook para \`N8N_ALERT_URL\` no PowerShell **do worker**. Mantenha \`N8N_DISPATCH_TOKEN\` como variável no mesmo PowerShell. Não inclua tokens em GitHub.

Em PowerShell à parte, a partir da raiz do projeto:

    $env:N8N_ALERT_URL = 'https://vtl2026.app.n8n.cloud/webhook/realoca-ai-alertas-v1'
    # N8N_DISPATCH_TOKEN deve estar configurado neste terminal, mesmo token do webhook de alertas.
    .\.venv\Scripts\python.exe -m app.services.operational_alerts --watch

Roda uma checagem a cada 30 segundos. **Deixar somente uma instância** do worker, para não segurar transações do SQLite desnecessariamente. Ctrl+C para interromper após a demo. Sem \`N8N_ALERT_URL\` ou \`N8N_DISPATCH_TOKEN\`, o worker não realiza envios.

## Testes offline (não consomem execuções n8n)

    .\.venv\Scripts\python.exe -m pytest tests/integration/test_planning_bridge.py -q

Verifica, entre outros itens: lembrete único em tentativa notificada, BP pendente que não vira aprovação automaticamente e falha de envio escalada após 3 tentativas, sem aceite indevido.

## Como validar o resultado de verdade

1. Após o caso real ser planejado e uma oferta ser despachada, confira \`GET /api/v1/cases/{case_id}\`.
2. Clique Aceitar ou Recusar na mensagem **original** da V2 no Slack; os lembretes não contêm botões.
3. Consulte \`GET /api/v1/audit?case_id=...\`. Procure \`offer.queued\`, \`offer.dispatched\`, \`alert.reminder_sent\` quando devido, e \`offer.accepted\` ou \`offer.refused\` + \`plan.replanned\`.
4. Para proposta BP, não é suficiente o aviso Slack. A chamada autenticada/atribuída de decisão continua sendo o endpoint \`/proposals/{attempt_id}/approval\`.

**Limites**: Receber HTTP 2xx do webhook n8n prova a entrada no n8n, não a entrega final no Slack. \`alert.*_sent\` registra confirmação HTTP do webhook, e não o clique de alguém. Credencial de BP e identidade do clicador não são demonstradas pelo canal compartilhado. Os testes precisam rodar na máquina Amanda e uma pessoa ainda precisa ativar o workflow auxiliar no n8n Cloud.
