# Realoca AI — Contrato de API e integração v1.2

> Fonte de verdade: https://app.notion.com/p/4111e6cf66888114b1fcdbbd9a93e075
> Esta documentação define interfaces a implementar; não afirma que endpoints já existem.
> Atualização 08/11/2026: Slack é o único canal de comunicação do MVP. Microsoft Teams foi retirado do escopo.
> Extensão compatível v1.2: consulta de equipes aprovada por Mateus, responsável pelo frontend, conforme aprovação informada pela usuária. Os endpoints e payloads anteriores permanecem preservados.


**REALOCA AI — CONTRATO TÉCNICO DE INTEGRAÇÃO v1.2**

Decisão de arquitetura tomada em 07/11/2026 para implementação paralela por Amanda, Mateus e Victor. Este documento especifica o comportamento **esperado**; a existência dos endpoints no código e os testes devem ser verificados antes de marcá-los como entregues.


**Fonte do produto:** [MVP](https://app.notion.com/p/4111e6cf668880c99eb2d4cd003a9d8e)
**Checklist:** [DIVISÃO DE TAREFAS](https://app.notion.com/p/4111e6cf66888009976cd823b7a14e47)
**Repositório:** [realoca-ai](https://github.com/victor-tenorio/realoca-ai)
**Versão:** `1.2` — congelar nomes públicos dos campos até aprovação explícita do trio. Mudança incompatível exige nova versão e atualização de todos os consumidores.

## 1. Responsáveis e limites

| Pessoa | É dona de | Não deve fazer sem alinhar |
| --- | --- | --- |
| **Amanda** | API HTTP, banco, estado de casos e tentativas, fonte simulada de tarefas, reservas e políticas, aprovação BP, auditoria, integração dos módulos | Trocar payload contratado sem atualizar consumidores |
| **Mateus** | Funções determinísticas de impacto/capacidade/planejamento global; frontend gerado no Lovable e exportado para o repositório | Gravar diretamente no banco da Amanda; declarar tarefa atribuída só porque motor propôs |
| **Victor** | Workflows n8n, entrada/saída de eventos, notificações Slack reais quando possível e simulador rotulado quando necessário, lembretes/expiração | Escolher substituto, mexer na carga, confirmar tarefa ou aprovar remanejamento por conta própria |

**Decisão arquitetural:** um backend HTTP central; motor do Mateus chamado por Amanda como módulo Python dentro do projeto (não é necessário criar uma segunda API); n8n em serviço separado, conectado por webhooks HTTP; frontend JavaScript/React exportado do Lovable chama somente a API. A linguagem/framework HTTP permanece escolha de Amanda; as rotas e o JSON abaixo são o contrato obrigatório.

## 2. Convenções gerais

- Prefixo de endpoints da aplicação: `/api/v1`. JSON em UTF-8, nomes técnicos `snake_case` em inglês, textos da interface em português.
- IDs são strings opacas e estáveis: `employee_id`, `team_id`, `task_id`, `absence_id`, `case_id`, `plan_id`, `attempt_id`, `event_id`. Nunca comparar nomes como identificadores.
- Datas/horas em ISO 8601 com fuso (`2026-11-08T08:00:00-03:00` ou UTC `Z`). Duração/capacidade em horas numéricas positivas.
- Em produção, cada dado deve carregar `source_system`, `external_id` e `updated_at` quando aplicável. No hackathon, dados fictícios em fontes simuladas distintas.
- Respostas HTTP: `200` leitura/ação concluída; `201` recurso criado; `202` evento recebido para processamento; `400` payload inválido; `401/403` credencial/permissão; `404` ID inexistente; `409` conflito/estado obsoleto; `422` regra de negócio não satisfeita; `500/503` falha técnica.
- Erro padrão: `{"error":{"code":"CAPACITY_CONFLICT","message":"Capacidade alterada","details":{"attempt_id":"att-001"}}}`. Não retornar stack trace no frontend.
- Chamadas servidor↔n8n usam token configurado em ambiente (ex.: `X-Internal-Token`); nunca colocar token real em GitHub, Notion ou JavaScript do navegador.
- Cada evento tem `event_id` único e cada tentativa tem `attempt_id`. Reenvio do mesmo evento devolve resultado idempotente, não reaplica a ação.

## 3. Modelo de dados comum

**Funcionário**: `employee_id`, `name`, `team_id`, `skills[]`, `shift_hours`, `committed_hours`, `reserved_hours`, `availability` (`available`/`absent`/`unavailable`), `preferred_channel` (`slack`), `channel_user_id`, `source_system`, `external_id`, `updated_at`.

**Tarefa**: `task_id`, `title`, `assignee_employee_id`, `team_id`, `priority` (`critical`/`high`/`medium`/`low`), `due_at`, `estimated_hours`, `required_skills[]`, `status` (`open`/`in_progress`/`done`), `transfer_allowed`, `source_system`, `external_id`, `updated_at`.

**Ausência**: `absence_id`, `employee_id`, `starts_at`, `ends_at`, `confirmed`, `source_system`. Não armazenar nem trafegar diagnóstico médico no convite.

**Caso**: `case_id`, `absence_ids[]`, `task_ids[]`, `status`, `plan_version`, `created_at`, `closed_at`.

**Tentativa de cobertura**: `attempt_id`, `case_id`, `plan_id`, `task_id`, `candidate_employee_id`, `reserved_hours`, `status`, `response_deadline_at`, `reason`, `created_at`, `responded_at`. Histórico de tentativas não pode ser apagado após recusa.

**Política padrão DEMO** (configurável, não equivale a regra trabalhista): `max_utilization_pct: 90`, `critical_requires_bp: true`, `cross_team_requires_bp: true`, `response_timeout_minutes: 15`, `allow_automatic_same_team: true`, `reminder_before_expiry_minutes: 5`.

## 4. Amanda → Mateus: contrato interno do motor

**Funções exportadas pelo módulo Python:**

- `plan_coverage(snapshot: dict) -> dict`
- `replan_coverage(snapshot: dict) -> dict` — usa as mesmas regras; snapshot carrega estado/reservas e exclusões atualizados.

O motor **não** consulta o banco diretamente, não notifica funcionários e não grava propostas. Ele calcula a distribuição de todo o conjunto de tarefas e devolve resultados puros e determinísticos.

**Exemplo de entrada:**

```json
{
  "case_id": "case-001",
  "plan_version": 1,
  "absent_employee_ids": ["emp-joao"],
  "tasks": [
    {"task_id": "task-A", "title": "Automação Python", "priority": "high", "estimated_hours": 2, "required_skills": ["python"], "team_id": "ops", "due_at": "2026-11-08T10:00:00-03:00", "transfer_allowed": true},
    {"task_id": "task-B", "title": "Relatório Excel", "priority": "high", "estimated_hours": 2, "required_skills": ["excel"], "team_id": "ops", "due_at": "2026-11-08T10:00:00-03:00", "transfer_allowed": true}
  ],
  "employees": [
    {"employee_id": "emp-carlos", "team_id": "ops", "skills": ["python", "excel"], "shift_hours": 2, "committed_hours": 0, "reserved_hours": 0, "availability": "available"},
    {"employee_id": "emp-pedro", "team_id": "ops", "skills": ["python"], "shift_hours": 2, "committed_hours": 0, "reserved_hours": 0, "availability": "available"}
  ],
  "exclusions": [],
  "policies": {"max_utilization_pct": 100}
}
```

**Resposta esperada:**

```json
{
  "case_id": "case-001",
  "plan_version": 1,
  "assignments": [
    {"task_id": "task-A", "candidate_employee_id": "emp-pedro", "estimated_hours": 2, "reason": "Python disponível; preserva Carlos para Excel"},
    {"task_id": "task-B", "candidate_employee_id": "emp-carlos", "estimated_hours": 2, "reason": "Único elegível para Excel"}
  ],
  "uncovered": [],
  "metrics": {"demand_hours": 4, "planned_hours": 4}
}
```

**Observação do exemplo:** política de 100% de utilização usada somente neste teste isolado para disponibilidades de 2h; no fluxo demonstrativo, aplicar política configurável real do caso (padrão 90%). A saída do motor é uma **proposta**, não um aceite, reserva executada ou conclusão.

**Regras obrigatórias do motor:** excluir ausentes, competências obrigatórias, prazo/jornada, capacidade descontando compromissos e reservas, políticas de elegibilidade; otimizar conjuntamente tarefas críticas, horas cobertas, equilíbrio e quantidade de movimentações. Se não houver solução, devolver `uncovered` com `reason_code` e alternativas, nunca inventar substituto.

## 5. API pública da Amanda — endpoints v1

| Método e rota | Responsável pelo uso | Função / retorno |
| --- | --- | --- |
| `GET /health` | Todos | Healthcheck simples da API |
| `POST /api/v1/demo/reset` | Demo (restrito) | Recarregar seeds 100% fictícios |
| `GET /api/v1/employees` | Front/Motor via Amanda | Lista equipes/capacidade/competências |
| `GET /api/v1/teams` | Front | Equipes persistidas e agregados do turno de referência; seção 13 |
| `GET /api/v1/tasks` | Front | Tarefas na fonte simulada e seus donos reais |
| `POST /api/v1/absences` | Front/BP | Registrar ausência confirmada e criar caso |
| `GET /api/v1/cases` | Front | Lista de casos, status e contagem |
| `GET /api/v1/cases/{case_id}` | Front | Detalhe com tentativas, propostas, pendências e timeline |
| `POST /api/v1/cases/{case_id}/plan` | Backend/BP | Invocar motor de Mateus e aplicar política/reservas |
| `POST /api/v1/proposals/{attempt_id}/approval` | BP via Front | Aprovar/rejeitar proposta restrita |
| `POST /api/v1/integrations/attempt-events` | n8n → Amanda | Registrar entrega, falha, aceite, recusa ou expiração |
| `POST /api/v1/tasks/{task_id}/complete` | Fonte de tarefas simulada | Confirmar conclusão e liberar carga |
| `GET /api/v1/dashboard` | Front | Métricas calculadas, sem números decorativos |
| `GET /api/v1/audit?case_id={case_id}` | Front/BP | Timeline auditável |
| `GET /api/v1/policies` | Admin/Front | Consultar políticas vigentes |
| `PATCH /api/v1/policies` | Admin (restrito) | Alterar limites configuráveis e auditar |

**POST ausência:**

```json
{
  "employee_id": "emp-joao",
  "starts_at": "2026-11-08T08:00:00-03:00",
  "ends_at": "2026-11-08T18:00:00-03:00",
  "confirmed": true,
  "source_system": "hr_simulator",
  "external_id": "absence-hr-001"
}
```

**Resposta HTTP 201:**

```json
{"absence_id": "abs-001", "case_id": "case-001", "status": "open"}
```

**POST planejamento — resposta HTTP 200:**

```json
{
  "case_id": "case-001",
  "plan_id": "plan-001",
  "plan_version": 1,
  "proposals": [
    {"attempt_id": "att-001", "task_id": "task-A", "candidate_employee_id": "emp-pedro", "policy_action": "auto", "status": "reserved", "reason": "Elegível e dentro da capacidade"},
    {"attempt_id": "att-002", "task_id": "task-B", "candidate_employee_id": "emp-carlos", "policy_action": "needs_approval", "status": "pending_approval", "reason": "Prioridade crítica ou regra restritiva"}
  ],
  "uncovered": []
}
```

O exemplo acima mostra formatos válidos de classificação; os valores reais dependem das políticas e prioridades enviadas no caso. `auto` significa **enviar pedido automaticamente** após reservar; **não significa alterar o responsável antes de aceite**.

**POST aprovação BP:** `{"decision":"approve","actor_id":"bp-demo","reason":"Cobertura autorizada"}`; decisão pode ser `approve` ou `reject`. Depois de `approve`, Amanda revalida capacidade e reserva antes de notificar. Rejeitar não abre caminho de envio automático para a mesma proposta.

## 6. Amanda → Victor: webhook de saída para n8n

**Endereço de desenvolvimento:** variável de ambiente `N8N_DISPATCH_URL` (ex.: webhook local `/webhook/realoca/dispatch`). Não fixar domínio/credencial no código.

**Evento de oferta:**

```json
{
  "event_id": "evt-out-001",
  "event_type": "offer.created",
  "case_id": "case-001",
  "attempt_id": "att-001",
  "task_id": "task-A",
  "task_title": "Automação Python",
  "estimated_hours": 2,
  "due_at": "2026-11-08T10:00:00-03:00",
  "candidate_employee_id": "emp-pedro",
  "candidate_name": "Pedro",
  "channel": "slack",
  "channel_user_id": "user-demo-pedro",
  "response_deadline_at": "2026-11-08T08:15:00-03:00",
  "message": "Pedro, você pode assumir temporariamente a tarefa Automação Python (2h), com prazo às 10h? Aceitar / Recusar."
}
```

**Responsabilidade de Victor:** validar payload, validar canal `slack` e destinatário, enviar/registrar convite, correlacionar `attempt_id` e devolver à API eventos de entrega/resposta. **Não** alterar dono da tarefa, não mudar capacidade e não escolher candidato. O canal real pode ser substituído por simulador declaradamente identificado, mantendo o mesmo JSON.

## 7. Victor → Amanda: webhook de retorno

**Endpoint único:** `POST /api/v1/integrations/attempt-events` com token interno.

**Evento de aceite:**

```json
{
  "event_id": "evt-in-001",
  "event_type": "offer.accepted",
  "attempt_id": "att-001",
  "channel": "slack",
  "occurred_at": "2026-11-08T08:05:00-03:00",
  "reason": null
}
```

**Evento de recusa:** mesma estrutura, com `event_type = "offer.refused"` e `reason` explicando impedimento.

**Eventos aceitos:** `offer.delivered`, `offer.delivery_failed`, `offer.accepted`, `offer.refused`, `offer.expired`.

**Regras de Amanda ao receber:**

- `delivered`: somente registra entrega, não transforma em aceite.
- `delivery_failed`: registra falha técnica e tenta recuperação/escalonamento, sem inventar aceite.
- `accepted`: confere tentativa pendente, deadline, política e capacidade; converte reserva em compromisso; atualiza responsável na fonte simulada; audita; avisa frontend.
- `refused`: registra motivo, libera reserva, exclui aquele candidato da tarefa, chama `replan_coverage`, envia nova proposta se viável.
- `expired`: só vale se horário de vencimento já passou e tentativa ainda está pendente; libera, replaneja, registra expiração.
- Mesmo `event_id` recebido duas vezes: não aplicar novamente; retornar resultado idempotente. Evento novo para tentativa já finalizada: `409` ou registro ignorado conforme política documentada.
- Quando não houver candidato, registrar caso escalado com alternativas; cobertura confirmada nunca inclui convites pendentes.

**Simulador de mensagens:** o frontend de Mateus envia uma interação fictícia ao webhook de demonstração de Victor, `POST {N8N_DEMO_RESPONSE_URL}`, contendo `attempt_id`, `event_id`, `action: "accept"|"refuse"`, `reason`. Victor converte para `offer.accepted`/`offer.refused` e chama a API. Assim, a demo realmente passa pelo n8n.

## 8. Estado, reserva e auditoria — autoridade exclusiva da API

**Estado de caso:** `open`, `planning`, `pending_approval`, `awaiting_responses`, `coverage_confirmed`, `closed_with_gaps`, `completed`.

**Estado de tentativa:** `proposed`, `pending_approval`, `reserved`, `notified`, `accepted`, `refused`, `expired`, `rejected_by_bp`, `escalated`.

**Invariantes:** uma tarefa pode ter no máximo uma tentativa ativa de cobertura; capacidade reservada não pode ser reutilizada; recusa e expiração liberam reserva; aprovação BP não é aceite do funcionário; notificação não altera assignee; conclusão de tarefa é diferente de cobertura confirmada; política e capacidade devem ser revalidadas antes de gravar a mudança.

**Auditoria mínima:** `audit_event_id`, `case_id`, `attempt_id` (se houver), `actor`, `action`, `timestamp`, `policy_version`, `reason`, `result`. Eventos antigos são imutáveis.

## 9. Frontend do Mateus ↔ API da Amanda

A aplicação exportada do Lovable usa `API_BASE_URL` configurável. Não chama motor diretamente nem precisa conhecer credenciais n8n.

- **Dashboard:** `GET /api/v1/dashboard` com ausências, tarefas afetadas, horas planejadas, horas confirmadas, tarefas concluídas, sem cobertura, equipes impactadas e recusas.
- **Central de casos:** `GET /api/v1/cases` e `/cases/{id}`; abrir ausência via `POST /api/v1/absences`.
- **Aprovação BP:** `POST /api/v1/proposals/{attempt_id}/approval`.
- **Equipe/tarefas:** `GET /api/v1/employees`, `GET /api/v1/teams` e `GET /api/v1/tasks`.
- **Auditoria:** `GET /api/v1/audit?case_id=...`.
- **Simulador Slack:** UI envia resposta para webhook demo do n8n, nunca modifica atribuição direto no estado local.
- **Estados visuais:** loading, error, empty, planned, approval, reserved/notified, accepted, refused, expired, escalated e completed.
- Dados e indicadores devem refletir estados da API. **Sem ROI fictício nem cobertura de 100% antes de todos os aceites.**

## 10. Contratos de testes obrigatórios

1. **Inicial:** criar ausência confirmada, encontrar tarefa ainda aberta na fonte simulada.
2. **Global:** caso Python/Excel cobre duas tarefas com A→Pedro e B→Carlos.
3. **Política:** operação crítica exige BP; negativa não envia convite.
4. **Reserva:** convite pendente bloqueia horas, aceite consolida, recusa libera.
5. **Recusa:** novo candidato escolhido, recusante excluído da mesma tarefa e sem duplicidade.
6. **Timeout:** evento expirar antecipado é rejeitado; evento válido replaneja.
7. **Idempotência:** dois cliques/callbacks idênticos não causam segunda alteração.
8. **Concorrência:** três ausências simultâneas não ultrapassam capacidade global.
9. **Sem cobertura:** BP recebe alternativas e status escalado, nunca falsa resolução.
10. **Origem:** tarefa só troca responsável depois de aceite mais aprovação aplicável.
11. **Slack:** demonstrar envio e aceite/recusa no canal único, com integração real quando disponível e simulador explicitamente rotulado quando necessário.
12. **Auditoria/UI:** linha do tempo e dashboard batem com os eventos persistidos.

## 11. Contratos de entrega e sequenciamento

- **Amanda:** criar API e fixtures em paralelo ao trabalho dos outros; fornecer stub/mocks dos endpoints rapidamente. Centralizar mudanças de esquema e validação.
- **Mateus:** construir módulo Python com fixtures locais desde o início, retornar dicionário conforme contrato; gerar frontend no Lovable e importar para GitHub, conectando-o aos endpoints.
- **Victor:** começar agora pelo n8n com webhook de entrada e retorno simulados conforme contratos de seções 6–7; usar mensagens fictícias, sem depender de conta empresarial.
- **Trio:** PR por branch, teste antes de concluir cada tarefa, registro no Notion com evidência. Fazer integração parcial cedo e repetir os 12 testes ao final.
- **Escopo:** todas as 77 linhas do backlog são metas; ordem de implementação deve respeitar dependências. P1 não deve impedir a primeira demo de ponta a ponta e só se diz concluída com evidência.

## 12. Perguntas que o código deve responder, sem suposições

- O que ocorre se a ausência é duplicada? Retornar mesmo caso/indicar conflito, sem abrir duas coberturas.
- O que ocorre se dois candidatos respondem quase simultaneamente? Só tentativa ativa é válida; validação transacional no backend.
- O que ocorre se Slack falha? Não considerar tarefa aceita; registrar falha, retentar com limite e escalar se persistir.
- O que ocorre se a capacidade mudou desde o plano? Revalidar, recusar commit e replanejar, sem sobrecarga.
- O que ocorre se a empresa não registra tarefas? Mostrar apenas o conjunto cadastrado/importado e marcar dados ausentes; nunca deduzir tarefas não registradas.
- O que ocorre se não há substituto? Fornecer alternativas ao BP e marcar tarefa descoberta.

**Regra final:** o contrato acima é a fonte única de integração. Qualquer dúvida estrutural deve resultar em ajuste explícito de versão no documento e no `docs/api-contract.md` do GitHub, com comunicação aos outros dois responsáveis.

## 13. Extensão aprovada — GET /api/v1/teams

Adição compatível baseada em `docs/teams-query-proposal.md`, aprovada por Mateus
para consumo no frontend. HTTP 200 retorna `list[TeamResponse]`: array JSON
direto, sem envelope, paginação ou filtros. Todos os campos abaixo são
obrigatórios; somente os explicitamente indicados aceitam `null`.

| Campo | Tipo JSON | Definição |
| --- | --- | --- |
| team_id | string | Identificador estável da equipe persistida |
| name | string | Nome persistido da equipe |
| reference_date | string (YYYY-MM-DD) | Data selecionada por DEMO_REFERENCE_DATE |
| employee_count | integer | Quantidade de membros na equipe atual |
| shift_hours | number ou null | Soma das capacidades dos membros no turno |
| committed_hours | number ou null | Soma das estimativas das tarefas abertas dos membros |
| reserved_hours | number | Soma das reservas ativas destinadas aos membros no turno |
| occupied_hours | number ou null | committed_hours + reserved_hours |
| utilization_pct | number ou null | 100 × soma da ocupação / soma da capacidade |
| complete | boolean | Capacidade e compromisso conhecidos integralmente |

Exemplo (um registro do array do seed, sem reservas):

```json
[
  {
    "team_id": "demo-atendimento",
    "name": "Atendimento",
    "reference_date": "2026-11-08",
    "employee_count": 10,
    "shift_hours": 80.0,
    "committed_hours": 47.5,
    "reserved_hours": 0.0,
    "occupied_hours": 47.5,
    "utilization_pct": 59.375,
    "complete": true
  }
]
```

Regras aprovadas:

- Equipes e nomes vêm de `teams`; membros são agrupados pela equipe atual. Carga
  e reservas acompanham o responsável/candidato atual, independentemente da
  equipe de origem da tarefa. Tarefas concluídas não entram na carga.
- Todos os valores pertencem ao turno da data configurada. Reservas com baixa e
  tarefas de outros turnos são excluídas. A consulta é somente leitura.
- Utilização é a razão dos totais, calculada com Decimal, sem média simples de
  percentuais individuais ou arredondamento intermediário. Pode exceder 90% ou
  100% para cargas preexistentes.
- Capacidade ou estimativa desconhecida torna o agregado correspondente `null`
  e `complete=false`. Ocupação depende de compromisso conhecido; utilização
  depende também de capacidade conhecida e total maior que zero. Zero é um
  valor conhecido; denominador zero produz utilização `null`, sem divisão.
- Sem membros, capacidade e carga são zero e utilização é `null`. Tarefas
  abertas sem responsável tornam o compromisso da equipe de origem desconhecido,
  conforme a regra já documentada de agregados incompletos. Sem turno persistido
  para a data, a capacidade de membros é desconhecida; não há tarefas/reservas
  vinculadas a esse período inexistente, portanto seus totais registrados são zero.
- Pessoas sem equipe impedem publicação com HTTP 422, no erro padrão
  `INCOMPLETE_SOURCE_DATA`, sem criar equipe fictícia ou omitir pessoas. Tarefas
  abertas sem responsável e sem equipe também impedem publicação, por não ser
  possível atribuir o agregado incompleto a uma equipe.
- Sem equipes/pessoas cadastradas, retorna `[]`. Não são aceitos parâmetros por
  query string; parâmetros desconhecidos recebem HTTP 400 e
  `INVALID_QUERY_PARAMETERS`. Os demais erros seguem as convenções gerais.
- Assim como nas consultas existentes, não se exige token de integração n8n.
  Autenticação futura do frontend permanece pendente de definição. Nenhum campo
  adicional de RH, mensagem, diagnóstico ou credencial é exposto.
