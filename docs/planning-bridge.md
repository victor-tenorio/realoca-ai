# A08–A12 — Planejamento, aprovação, reserva e saída n8n

Os serviços abaixo persistem propostas e reservas na mesma API, com auditoria.
O endpoint `POST /api/v1/cases/{case_id}/plan` classifica e reserva as
propostas `auto` e deixa propostas restritas em `pending_approval`.
`POST /api/v1/proposals/{attempt_id}/approval` permite ao BP autorizar
ou rejeitar uma proposta; autorizar revalida e reserva, rejeitar não envia.

| Serviço | Responsabilidade | Efeito |
| --- | --- | --- |
| `snapshot.build` | Lê tarefas da fonte, ausências, competências, turnos, reservas, política e exclusões por recusa | Nenhuma escrita |
| `planning.create_plan` | Invoca `engine.plan_coverage`, valida cobertura de IDs, persiste versão do plano e tentativas `proposed` | Plano e auditoria; não troca responsável |
| `policy.classify` | Regra determinística de elegibilidade, capacidade, criticidade e fronteira de equipe | Decisão `auto`, `needs_approval` ou `inviable` com motivo |
| `reservations.reserve_attempt_atomic` | Revalida a situação atual sob `BEGIN IMMEDIATE`, reserva capacidade e registra auditoria | Tentativa `reserved`, prazo e reserva; sem convite ou aceite |
| `planning.plan_and_authorize` | Orquestra política, plano, reservas automáticas e fila BP | Resposta HTTP contratada; nunca altera o responsável |
| `approvals.decide_atomic` | Decide BP com motivo e revalida reserva sob lock | Autoriza e enfileira ou rejeita sem notificar |
| `dispatch.queue_offer` | Persiste `offer.created` no outbox na mesma transação da reserva | Evento durável e idempotente; nenhum envio prematuro |
| `dispatch.send_queued_offer` | Envia por HTTP ao webhook n8n e registra tentativas | Só marca `notified` após 2xx; mantém `reserved` se falhar |

Os dados da seed são fictícios. Um funcionário sem dados confiáveis de
competências ou horas não vira candidato elegível; uma tarefa afetada com
campos obrigatórios desconhecidos bloqueia o planejamento. A consulta de
ausências cobre o turno inteiro da tarefa, e as recusas/expirações anteriores
integram as exclusões do snapshot. A versão da política é preservada em cada
plano/tentativa.

**Configurar para o n8n:** definir no processo FastAPI `N8N_DISPATCH_URL`
(endereço alcançável de um webhook do n8n) e `N8N_DISPATCH_TOKEN` (segredo
validado pelo fluxo do n8n). Sem ambos, a API apenas grava ofertas no outbox,
sem gastar execuções do n8n. Com ambos, o envio é agendado em segundo plano
após as rotas de planejamento e aprovação BP. Falhas ficam registradas para
nova tentativa; o envio pode ser retomado por
`python -m app.services.dispatch` no ambiente do backend. O `event_id` é
preservado entre tentativas. **Não publicar esses segredos no repositório.**

**Limites atuais:** o motor do Mateus permanece heurístico. O outbox foi
testado com um webhook simulado, não foi executado contra n8n real; é preciso
conectar a URL ao fluxo de Victor antes do teste ponta a ponta. A API já
recebe callbacks na inbox, mas **a aplicação de aceite, recusa e expiração
ao estado de tarefas/reservas ainda depende das etapas A14–A15**. A etapa
`offer.created` não confirma aceite nem muda o responsável.

**Validação:** `python -m pytest -q`, com testes de banco → motor → reserva,
aprovação/rejeição BP e simulação de envio, falha e reenvio do outbox.
