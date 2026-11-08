CLAUDE.md — Backend Realoca AI

Atualização 08/11/2026: Slack é o único canal de comunicação do MVP; remover implementação de Microsoft Teams.

Converge Challenge 2026 · Branch: feat/backend-api · Dona: Amanda Leia este arquivo inteiro antes de gerar ou alterar código.

Hierarquia de fontes: (1) docs/api-contract.md (Contrato Técnico de Integração v1.2) manda em rotas, JSON, nomes de campos, estados e eventos. (2) docs/spec.md (MVP) manda em regras de negócio. (3) Este arquivo resume os dois e define convenções de código. Em conflito, pare e pergunte; nunca "resolva" mudando o contrato.

1. O que é o projeto

Plataforma B2B que mantém a continuidade das tarefas quando funcionários se ausentam: cruza RH, tarefas e capacidade, calcula um plano de cobertura global, coordena a execução por Slack, recupera recusas e acompanha até a confirmação. O produto realoca a responsabilidade pelas tarefas; não executa o trabalho delas.

É um MVP de hackathon: dados 100% fictícios, integrações simuladas e rotuladas "Integração simulada", demo de 5 minutos. P1 nunca bloqueia a demo de ponta a ponta. Nada é declarado entregue sem evidência (teste passando).

2. Divisão do trio (quem é dono de quê)
   Pessoa Dona de Não faz sem alinhar
   Amanda (eu/este repo) API HTTP, banco, estado de casos/tentativas, fonte simulada de tarefas, reservas, políticas, aprovação BP, auditoria, integração dos módulos Trocar payload contratado sem atualizar consumidores
   Mateus Motor Python determinístico (plan_coverage, replan_coverage) e frontend (Lovable) Gravar no meu banco; declarar tarefa atribuída porque o motor propôs
   Victor Workflows n8n: eventos de entrada/saída, Slack (real ou simulado), lembretes/expiração Escolher substituto, mexer em carga, confirmar tarefa ou aprovar remanejamento

Arquitetura: um backend HTTP central. O motor do Mateus é um módulo Python importado (sem segunda API). O n8n é um serviço separado ligado por webhooks HTTP. O frontend só chama a minha API.

3. Stack

Framework é escolha minha (contrato fixa só rotas e JSON). Sugestão:

Python 3.11+, FastAPI, Pydantic v2, SQLModel/SQLAlchemy, SQLite
httpx para chamar o webhook do n8n; pytest + TestClient; ruff
Sem LLM no MVP. Políticas, reservas e orquestração são determinísticas.
O planejador é do Mateus. Eu só chamo a interface (seção 4). 4. Estrutura de pastas
app/
main.py # FastAPI, CORS (origem do front Lovable), routers, handlers de erro
config.py # env: N8N_DISPATCH_URL, INTERNAL_TOKEN, DATABASE_URL
db.py
enums.py # ÚNICA fonte dos enums (seção 7)
errors.py # exceções de domínio -> formato de erro padrão
models/ # tabelas
schemas/ # Pydantic I/O (== contrato; separados dos models)
api/v1/ # routers finos
health.py demo.py employees.py tasks.py absences.py cases.py
proposals.py integrations.py dashboard.py audit.py policies.py
services/
cases.py # criação/estado derivado do caso
impact.py # tarefas abertas da ausente, divergência RH x tarefas
snapshot.py # monta o snapshot para o motor
planning.py # chama o motor, aplica política, cria tentativas
policy.py # classificação auto | needs_approval (funções puras)
reservations.py # reservar / liberar / converter (transacional)
attempts.py # máquina de estados (transition)
approvals.py # decisão do BP + revalidação
events.py # processa attempt-events, idempotência
dispatch.py # cliente do webhook n8n (offer.created)
task_source.py # fonte SIMULADA de tarefas (único ponto que altera assignee)
audit.py
dashboard.py
engine/ # ← DO MATEUS. Não editar. Só importar.
**init**.py # plan_coverage, replan_coverage
demo/
seed.py scenarios.py # fixtures fictícias (inclui Carlos/Pedro)
tests/
unit/ integration/ # integration/ = os 12 contratos da seção 13
docs/
api-contract.md spec.md

Regra: routers finos, regra em services/. Nenhuma regra de negócio em api/.

5. Comandos
   bash
   pip install -r requirements.txt
   uvicorn app.main:app --reload # :8000, docs em /docs
   pytest -q # tudo
   pytest tests/integration -q # contratos de integração
   ruff check . && ruff format .
6. Convenções do contrato (obrigatórias)
   Prefixo /api/v1 (exceto GET /health). JSON UTF-8. Campos em snake_case inglês; textos de interface em português. (Isto substitui os nomes em português da spec.)
   IDs são strings opacas: employee_id, team_id, task_id, absence_id, case_id, plan_id, attempt_id, event_id. Nunca comparar nomes como ID.
   Datas ISO 8601 com fuso. Horas numéricas positivas.
   Dados vindos de fonte carregam source_system, external_id, updated_at.
   Congelar nomes públicos de campos. Mudança incompatível = nova versão + atualização de todos os consumidores + docs/api-contract.md.
   Códigos HTTP: 200 ok · 201 criado · 202 evento aceito para processamento · 400 payload inválido · 401/403 credencial/permissão · 404 ID inexistente · 409 conflito/estado obsoleto · 422 regra de negócio · 500/503 falha técnica.
   Erro padrão (sem stack trace): {"error":{"code":"CAPACITY_CONFLICT","message":"...","details":{"attempt_id":"att-001"}}}
   Servidor↔n8n: token em env (X-Internal-Token). Nunca token no GitHub, Notion ou JS do navegador.
   Idempotência: todo evento tem event_id único; reenvio devolve o resultado anterior sem reaplicar a ação.
7. Estados (enums — idênticos aos do contrato)

Caso: open, planning, pending_approval, awaiting_responses, coverage_confirmed, closed_with_gaps, completed (derivado das tentativas e tarefas; recalcular num único lugar, services/cases.py).

Tentativa: proposed, pending_approval, reserved, notified, accepted, refused, expired, rejected_by_bp, escalated

Transições permitidas (derivadas do contrato; qualquer outra lança InvalidTransition):

De Para
proposed pending_approval, reserved, escalated
pending_approval reserved, rejected_by_bp
reserved notified, escalated
notified accepted, refused, expired

Terminais: accepted, refused, expired, rejected_by_bp, escalated.

Toda mudança passa por attempts.transition(attempt, novo, actor, reason), que valida, persiste e audita. Nunca attempt.status = ... direto.
pending_approval não reserva horas; a reserva ocorre na aprovação, após revalidar (seção 9).
Histórico de tentativas nunca é apagado; nova tentativa = nova linha.
Conclusão da tarefa é tratada na tarefa (done), não como estado de tentativa. Cobertura confirmada ≠ concluída. 8. Invariantes (inegociáveis)
Notificar ≠ atribuir. Reserva ≠ aceite. Aprovação BP ≠ aceite. Aceite ≠ conclusão.
Uma tarefa tem no máximo uma tentativa ativa de cobertura.
Capacidade reservada não pode ser reutilizada; reservas pendentes contam como horas ocupadas.
Recusa e expiração liberam a reserva.
O responsável da tarefa só muda em task_source e somente após aceite + aprovações aplicáveis.
Revalidar capacidade e política imediatamente antes de converter reserva e gravar na origem. Se mudou: 409 CAPACITY_CONFLICT, não grava, replaneja.
Cobertura confirmada nunca inclui convites pendentes. Caso com tarefa sem substituto nunca aparece como 100% resolvido.
Sem solução → registrar escalonamento com alternativas concretas ao BP. Nunca inventar substituto.
Dado ausente (horas, skills, tarefas) é marcado como ausente, não deduzido. Só existem as tarefas cadastradas/importadas.
Convite não revela causa médica; nem armazenar/trafegar diagnóstico.
Dashboard calculado de registros reais. Sem ROI fictício.
Toda transição e ação relevante gera evento de auditoria imutável. 9. Fluxos
9.1 Ausência → caso

POST /absences (201) cria ausência + caso (open), identifica tarefas abertas da pessoa em task_source e marca divergência (RH ausente, tarefa ainda no dono original).

Mesmo external_id repetido: 200 com o mesmo case_id (idempotente), sem abrir segunda cobertura.
Ausência sobreposta com external_id diferente: 409 com o case_id existente em details.
9.2 Planejamento — POST /cases/{id}/plan
snapshot.build(case) → inclui ausentes, tarefas, funcionários (com reserved_hours atuais), exclusions (pares tarefa × candidato de recusas/expirações anteriores) e policies.
engine.plan_coverage(snapshot) (ou replan_coverage em replanejamento). O motor é puro: não acessa banco nem notifica.
Para cada assignment: policy.classify → auto ou needs_approval; cria tentativa.
auto: reserva (transacional) → reserved → envia offer.created ao n8n → notified.
needs_approval: pending_approval (sem reserva, sem convite).
uncovered do motor → tentativa/registro escalated com reason_code e alternativas.
Resposta: {case_id, plan_id, plan_version, proposals[], uncovered[]} (formato do contrato).

Política vem de GET /policies (padrão DEMO): max_utilization_pct: 90, critical_requires_bp: true, cross_team_requires_bp: true, response_timeout_minutes: 15, allow_automatic_same_team: true, reminder_before_expiry_minutes: 5. Não equivale a regra trabalhista.

9.3 Aprovação — POST /proposals/{attempt_id}/approval

Body {decision: approve|reject, actor_id, reason}.

approve: revalidar capacidade/política → reservar → reserved → enviar convite → notified. Falha de capacidade → 409 CAPACITY_CONFLICT e replanejar.
reject: rejected_by_bp; não abre caminho de envio automático da mesma proposta.
9.4 Eventos do n8n — POST /integrations/attempt-events (token interno, 202)

Tipos: offer.delivered, offer.delivery_failed, offer.accepted, offer.refused, offer.expired.

Evento Ação
delivered Só registra entrega. Não é aceite.
delivery_failed Registra falha técnica; retenta com limite; se persistir, escala. Nunca vira aceite.
accepted Confere tentativa em notified, prazo, política, capacidade → converte reserva em compromisso → atualiza responsável em task_source → audita → atualiza estado do caso.
refused Registra motivo, libera reserva, adiciona exclusão (tarefa × candidato), replan_coverage, envia nova proposta se viável.
expired Só vale se response_deadline_at já passou e a tentativa segue notified; senão rejeitar. Libera, replaneja, registra expiração.
Mesmo event_id duas vezes → devolve resultado anterior (tabela processed_events com event_id único). Não reaplica.
Evento novo para tentativa já terminal → 409 ATTEMPT_NOT_ACTIVE (decisão a confirmar com Victor; o n8n deve tratar o 409).
Concorrência (duas respostas quase simultâneas): só a tentativa ativa vale; validação transacional.
9.5 Conclusão — POST /tasks/{task_id}/complete

Marca tarefa done, libera carga e atualiza indicadores. Não confundir com cobertura confirmada. Caso completed só quando todas as tarefas cobertas estiverem concluídas e não houver pendências.

9.6 Webhook de saída (offer.created)

Enviado a N8N_DISPATCH_URL com os campos do contrato: event_id (evt-out-\*), event_type, case_id, attempt_id, task_id, task_title, estimated_hours, due_at, candidate_employee_id, candidate_name, channel, channel_user_id, response_deadline_at (= agora + response_timeout_minutes), message. O canal vem de preferred_channel. Falha de rede: não considerar notificado; registrar e retentar com limite.

10. Contrato do motor (Mateus)
    python
    plan_coverage(snapshot: dict) -> dict
    replan_coverage(snapshot: dict) -> dict # mesmas regras; snapshot com exclusões/reservas atualizadas

Saída: {case_id, plan_version, assignments[{task_id, candidate_employee_id, estimated_hours, reason}], uncovered[{task_id, reason_code, alternatives}], metrics{demand_hours, planned_hours}}.

Eu não reimplemento planejamento. Se o motor ainda não existir, usar um stub determinístico em tests/ com a mesma assinatura (nunca em app/engine/).
A saída é uma proposta: nunca tratá-la como reserva, aceite ou atribuição.
Caso de referência: A (Python, 2h; Carlos ou Pedro) e B (Excel, 2h; só Carlos) → A→Pedro, B→Carlos. (Neste teste isolado a política usa max_utilization_pct: 100; no fluxo real vale a política do caso, padrão 90.) 11. Endpoints (v1, contrato)
GET /health
POST /api/v1/demo/reset (restrito)
GET /api/v1/employees
GET /api/v1/teams
GET /api/v1/tasks
POST /api/v1/absences
GET /api/v1/cases
GET /api/v1/cases/{case_id} detalhe: tentativas, propostas, pendências, timeline
POST /api/v1/cases/{case_id}/plan
POST /api/v1/proposals/{attempt_id}/approval
POST /api/v1/integrations/attempt-events (token interno)
POST /api/v1/tasks/{task_id}/complete
GET /api/v1/dashboard
GET /api/v1/audit?case_id={case_id}
GET /api/v1/policies
PATCH /api/v1/policies (admin, restrito, auditado)
Não existe POST /attempts/{id}/respond: aceite/recusa do simulador passam pelo n8n (N8N_DEMO_RESPONSE_URL) e voltam por attempt-events. O frontend nunca altera atribuição direto.
Endpoints extras (ex.: /demo/scenarios/{A..F}) só se não alterarem o contrato; avisar o trio e documentar.
Rotas restritas (demo/reset, PATCH policies): token/papel simples no MVP; 401/403 conforme o caso. 12. Auditoria

Campos mínimos: audit_event_id, case_id, attempt_id?, actor, action, timestamp, policy_version, reason, result. Append-only. Serviço central audit.record(...) chamado por attempts.transition e por toda ação relevante (ausência, divergência, plano, reserva/liberação, convite, falha de entrega, aprovação, escrita na origem, alteração de política). Timeline do front = esta tabela.

13. Testes obrigatórios (os 12 do contrato)
    Ausência confirmada → encontra tarefa aberta na fonte simulada.
    Global: Python/Excel → A→Pedro, B→Carlos.
    Política: crítica exige BP; rejeição não envia convite.
    Reserva: convite pendente bloqueia horas; aceite consolida; recusa libera.
    Recusa: novo candidato, recusante excluído da mesma tarefa, sem duplicidade.
    Timeout: offer.expired antecipado é rejeitado; válido replaneja.
    Idempotência: dois callbacks idênticos não geram segunda alteração.
    Concorrência: três ausências simultâneas não excedem capacidade.
    Sem cobertura: BP recebe alternativas, status escalado, nunca falsa resolução.
    Origem: assignee só muda após aceite + aprovação aplicável.
    Slack: envio e aceite/recusa em integração real ou simulação rotulada.
    Auditoria/UI: timeline e dashboard batem com eventos persistidos.

Cenários da demo (spec seção 14, A–F) mapeiam para estes testes. Também testar: ausência duplicada, falha de canal, capacidade alterada desde o plano, transição inválida, evento em tentativa terminal. Relógio injetável (now()) para simular expiração.

14. Dashboard

GET /dashboard: ausências, tarefas afetadas, horas em risco, horas planejadas e confirmadas separadas, tarefas concluídas, sem cobertura, equipes impactadas, recusas, tempo ausência → cobertura confirmada, divergências detectadas/corrigidas. Tudo derivado de registros. Sem ROI, economia em R$ ou SLA como fato.

15. Estilo de código
    Type hints; Pydantic para I/O; models separados de schemas.
    Políticas e snapshot.build puras onde possível.
    Exceções de domínio (InvalidTransition, CapacityConflict, PolicyViolation, AttemptNotActive) → mapeadas para o formato de erro padrão.
    Commits pequenos (feat:, fix:, test:), PR por branch, teste antes de concluir, evidência no Notion.
    Priorizar stubs/mocks dos endpoints cedo para Mateus e Victor trabalharem em paralelo.
16. Como trabalhar comigo (IA)
    Testes primeiro, a partir dos 12 contratos. Um recurso por vez.
    Rodar código e testes após cada mudança; não presumir que bibliotecas/métodos existem.
    Sem dependências novas sem avisar.
    Parar e perguntar antes de mudar: contrato (rotas, campos, enums), transições, invariantes da seção 8.
    Ao concluir: o que mudou, o que foi testado, o que ficou pendente.
17. Não fazer
    Regra de negócio em router; status atribuído direto sem transition.
    Editar app/engine/ ou reimplementar planejamento.
    Gravar assignee antes de aceite + aprovações, ou sem revalidar.
    Tratar delivered, reserva ou aprovação como aceite.
    Segredos no repositório ou no front; dados reais.
    Renomear/remover campos públicos congelados.
    Declarar entregue sem teste passando.
18. Definição de pronto (antes do merge)
    pytest verde, incluindo os 12 contratos
    JSON e rotas idênticos ao docs/api-contract.md
    Enums de enums.py = enums do contrato
    Nenhuma reserva duplicada nem sobrecarga (3 ausências simultâneas)
    Recusa libera reserva e exclui candidato × tarefa
    Origem muda só após aceite + aprovações, com revalidação
    Toda transição auditada com motivo
    Caso sem solução nunca aparece como resolvido
    ruff limpo
19. Decisões a confirmar com o trio
    409 ATTEMPT_NOT_ACTIVE para evento em tentativa terminal (Victor trata no n8n?)
    Tentativa sem estado completed: conclusão só na tarefa (ok para o front do Mateus?)
    pending_approval não reserva horas; reserva só após aprovação + revalidação
    Ausência duplicada: 200 idempotente (mesmo external_id) vs 409 (sobreposição)
    Autenticação das rotas restritas e do front no MVP
    Política de retentativa para delivery_failed (limite e intervalo)
    Formato de alternatives e reason_code em uncovered (alinhar com Mateus)
