# A08–A10 — Ponte inicial de planejamento e capacidade

Os serviços abaixo estão implementados e testados **sem criar ou alterar
endpoints públicos**. A resposta HTTP de `POST /api/v1/cases/{case_id}/plan`
continua pendente até que as etapas de classificação, aprovação, envio e
reserva sejam orquestradas com os status previstos no contrato.

| Serviço | Responsabilidade | Efeito |
| --- | --- | --- |
| `snapshot.build` | Lê tarefas da fonte, ausências, competências, turnos, reservas, política e exclusões por recusa | Nenhuma escrita |
| `planning.create_plan` | Invoca `engine.plan_coverage`, valida cobertura de IDs, persiste versão do plano e tentativas `proposed` | Plano e auditoria; não troca responsável |
| `policy.classify` | Regra determinística de elegibilidade, capacidade, criticidade e fronteira de equipe | Decisão `auto`, `needs_approval` ou `inviable` com motivo |
| `reservations.reserve_attempt_atomic` | Revalida a situação atual sob `BEGIN IMMEDIATE`, reserva capacidade e registra auditoria | Tentativa `reserved`, prazo e reserva; sem convite ou aceite |

Os dados da seed são fictícios. Um funcionário sem dados confiáveis de
competências ou horas não vira candidato elegível; uma tarefa afetada com
campos obrigatórios desconhecidos bloqueia o planejamento. A consulta de
ausências cobre o turno inteiro da tarefa, e as recusas/expirações anteriores
integram as exclusões do snapshot. A versão da política é preservada em cada
plano/tentativa.

**Limites atuais:** o algoritmo do Mateus ainda se declara heurístico em
`app/engine/planning.py`; o serviço de reserva espera uma sessão nova e gera
um lock de escrita antes das leituras no SQLite. A criação de propostas não é
envio, BP nem redistribuição. Falta orquestrar as operações para cumprir a
resposta HTTP contratada, adicionar decisões BP, o outbox `offer.created` e o
processamento efetivo dos callbacks (A11–A15). Não chamar n8n antes disso.

**Validação:** `python -m pytest -q` — 291 testes aprovados, incluindo
integração banco → snapshot → motor → propostas, classificação e reserva
idempotente com revalidação após nova ausência.
