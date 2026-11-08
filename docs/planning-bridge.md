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

**Callbacks A14–A15:** `POST /api/v1/integrations/attempt-events` confirma o
recebimento de maneira idempotente e agenda o processamento da inbox. Um
`offer.accepted` revalida competências, presença, autorização BP e capacidade
(descontando apenas a própria reserva) e, em uma transação, libera a reserva,
registra `TaskAssignment`, muda o proprietário na fonte de tarefas e audita.
Uma recusa ou expiração libera a reserva e grava o motivo antes de solicitar
um novo plano ao motor para **somente a tarefa recusada**, excluindo candidatos
que já recusaram/expiraram. Se não houver candidato, registra tentativa
`escalated` e lacuna, sem inventar cobertura. Eventos inválidos ficam
registrados como rejeitados; falhas transitórias de processamento permanecem
na inbox para recuperação por `python -m app.services.event_processing`.

**Consultas BP:** `GET /api/v1/cases` lista casos e contagem de aprovações;
`GET /api/v1/cases/{case_id}` mostra tentativas, motivos e pendências reais.

**A16 — Escalonamentos:** qualquer tarefa sem candidato, com recusa sem
alternativa ou com dados insuficientes é persistida como tentativa `escalated`
com motivo auditado e sugestões de ação **genéricas** para o BP (rever prazo,
dividir, pedir apoio, corrigir dados). `GET /cases` fornece `escalation_count`
e `requires_bp_review`, e `GET /cases/{id}` fornece `escalations` com motivos
e opções. Esses casos nunca são contados como cobertura confirmada.

**A17 — Auditoria e métricas:** `GET /api/v1/audit?case_id=...` retorna apenas
eventos persistidos, com autor, ação, motivo, horário e versão de política.
`GET /api/v1/dashboard` agrega ausências, casos, tarefas únicas, horas
impactadas/planejadas/confirmadas/concluídas, recusas, expirações,
escalonamentos e fila BP; horas desconhecidas são `null`. Sem números
financeiros artificiais. Métricas de conclusão só refletem tarefas realmente
marcadas `done`.

**A18 — Conclusão da origem:** aceite põe a tarefa `in_progress`, mas não
concluída. `POST /api/v1/tasks/{task_id}/complete` é idempotente, exige
aceite no caso de tarefas relacionadas a uma ausência, grava auditoria,
marca `done`, libera horas comprometidas pelo cálculo de capacidade e só
então permite ao caso transicionar para `completed`.

**Limites atuais:** o motor do Mateus permanece heurístico. O outbox foi
testado com um webhook simulado, não foi executado contra n8n real; é preciso
conectar a URL ao fluxo de Victor antes do teste ponta a ponta. O envio pode
falhar depois de gravar a intenção e ser retomado pelo worker, sem criar um
novo `event_id`. A etapa `offer.created` não confirma aceite nem muda o
responsável. As falhas de replanejamento também podem ser retomadas pelo
worker; o último callback recebido não é descartado.

**Validação:** `python -m pytest -q`, com testes de banco → motor → reserva,
aprovação/rejeição BP e simulação de envio, falha e reenvio do outbox.
