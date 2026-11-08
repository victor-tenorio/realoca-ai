# V04 — Simulador local de aceite/recusa (Slack)

Implementação: n8n/simulate-slack.mjs. **Não é uma integração real com Slack nem substitui V17.**
Usa o mesmo JavaScript de "Converter resposta para API" do template n8n V2, evitando um contrato divergente.
Escuta apenas em 127.0.0.1:8765. Não altera tarefas, reservas ou casos por conta própria.

## Testar sem créditos n8n

Requer Node.js >= 18. Na raiz do repositório:

    node --test n8n/tests/simulate-slack.test.mjs
    node n8n/simulate-slack.mjs

Em outro PowerShell no mesmo computador:

    $payload = @{
      attempt_id = 'att-demo-local'
      decision = 'accepted'
      responded_at = (Get-Date).ToUniversalTime().ToString('o')
    } | ConvertTo-Json
    Invoke-RestMethod -Uri 'http://127.0.0.1:8765/simulate' -Method Post -ContentType 'application/json' -Body $payload

Alterar decision para 'declined' e acrescentar reason para simular recusa.
Resposta: mode=preview, callback com event_id/event_type/attempt_id/channel/occurred_at/reason, applied=false.
Os IDs "att-demo-local" servem **somente para preview**; nunca funcionariam para aplicar uma decisão no backend.

## Enviar um callback simulado ao backend (OPCIONAL)

Somente com uma tentativa real (coverage_attempt) e oferta real previamente despachada no banco.
Sem esses registros, a API recusa o callback — não invente IDs.

No terminal do simulador:

    $env:SIMULATOR_CALLBACK_URL = 'http://127.0.0.1:8001/api/v1/integrations/attempt-events'
    # INTEGRATIONS_INTERNAL_TOKEN já deve estar definido nesse mesmo terminal.
    node n8n/simulate-slack.mjs

O simulador passa a encaminhar respostas autenticadas. **Este modo altera o estado da API se a tentativa for válida; é opt-in.**
Também aceita URL HTTPS pública. Use somente dados fictícios de demo e não exponha este servidor local externamente.
O HTTP 202 indica recebimento na inbox, não comprova tarefa atribuída. Conferir GET /api/v1/cases/{case_id} e GET /api/v1/audit?case_id=....
Credenciais e valores dos tokens nunca devem entrar no repositório ou em prints.

## Limitações

- Webhook de demonstração local, não Slack OAuth/identidade real.
- Aceite/recusa com motivo; expiração, lembretes, erros de canal e aprovação BP ainda exigem testes/implementação no fluxo real.
- A API só aceita callbacks para ofertas reais e ainda no prazo; eventos falsos são rejeitados.
- Transições e auditoria de negócio pertencem ao FastAPI, nunca ao simulador.

Evidência: seis testes locais automatizados (aceite, recusa, inválidos, webhook preview, forwarding autenticado mock e bloqueio de configuração insegura).
