# realoca-ai
Sistema multiagente de continuidade operacional e redistribuição inteligente de tarefas — Converge Challenge 2026.


## Backend: persist?ncia da demo

Execute na pasta `realoca-ai`, usando Windows PowerShell e Python 3.11+:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DATABASE_URL = "sqlite:///./realoca.db"
$env:DEMO_REFERENCE_DATE = "2026-11-08"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.demo.seed
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

`GET http://127.0.0.1:8000/health` permanece dispon?vel. `.env.example` cont?m
somente exemplos; a aplica??o l? vari?veis de ambiente e n?o carrega `.env`
automaticamente. N?o coloque credenciais no c?digo.

Depend?ncias diretas adicionadas: SQLAlchemy >=2.0,<3 e Alembic >=1.13,<2.
O seed ? expl?cito, sint?tico e transacional: 40 pessoas, quatro equipes,
187 tarefas abertas. Reexecutar n?o duplica nem restaura dados alterados.
As horas s?o calculadas das tarefas persistidas, sem contador paralelo.

Os testes aplicam Alembic em SQLite tempor?rio, verificam FKs, constraints,
relacionamentos, precis?o, seed, capacidade, sa?de e revers?o com/sem dados.
N?o abrem nem apagam o banco de desenvolvimento. N?o existiam testes al?m dos
marcadores de pasta antes desta atividade. Fluxos de neg?cio dos 12 contratos
continuam para atividades futuras; n?o s?o considerados validados aqui.

Para inspecionar e reverter **somente um banco descart?vel**, selecione-o
explicitamente antes do comando destrutivo de downgrade:

```powershell
$env:DATABASE_URL = "sqlite:///./migration-review.sqlite"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic downgrade base
# Voltar ao banco local ap?s a revis?o:
$env:DATABASE_URL = "sqlite:///./realoca.db"
```

Consulte [as decis?es de modelagem](docs/spec.md) para dados ausentes,
representa??o do turno, precis?o, hist?rico e migra??es futuras de reservas,
aus?ncias, casos e tentativas. Modelos de banco ficam em `app/models/`;
schemas p?blicos futuros ficam em `app/schemas/`. Nenhum endpoint de neg?cio,
frontend ou planejador foi implementado nesta etapa.

## Casos, tentativas e integração: segunda migração

A revisão `65aad520e5e0` acrescenta ausências mínimas, casos e vínculos às tarefas,
planos, tentativas, políticas versionadas, reservas, eventos recebidos, auditoria,
mensagens de saída e tentativas de transporte. Reutiliza SQLAlchemy/Alembic;
nenhuma dependência adicional é necessária. A migração inicial permanece intacta.

```powershell
# Na pasta realoca-ai, com DATABASE_URL apontando para o banco desejado:
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m pytest -q
```

Os testes incluem atualização da revisão anterior com seed e dados alterados,
reversão em banco temporário e preservação dos registros originais. O seed não
cria casos, políticas ou mensagens automaticamente. Políticas novas usam os
defaults oficiais, com versões preservadas para decisões históricas.

Auditoria append-only, FKs e unicidade de tentativa ativa são garantias do banco
SQLite migrado. Eventos têm armazenamento de resultado anterior. O receptor HTTP
idempotente está descrito abaixo; processamento das transições, a aprovação/aceite
e o envio ainda não existem.
Reservas agora são persistidas e entram no cálculo de capacidade; sua criação,
liberação e conversão permanecem para os serviços futuros. Veja os detalhes em
[docs/spec.md](docs/spec.md). Os mesmos comandos de instalação e inicialização
acima continuam válidos. O downgrade para `d00209376958` remove os módulos novos
e seus registros; use-o apenas em banco descartável durante validação.

## API de consulta

Na pasta `realoca-ai`, após instalar dependências, aplicar migrações e executar
o seed explícito:

```powershell
$env:DATABASE_URL = "sqlite:///./realoca.db"
$env:DEMO_REFERENCE_DATE = "2026-11-08"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Em outro PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$employees = Invoke-RestMethod http://127.0.0.1:8000/api/v1/employees
$teams = Invoke-RestMethod http://127.0.0.1:8000/api/v1/teams
$tasks = Invoke-RestMethod http://127.0.0.1:8000/api/v1/tasks
$employees | Select-Object employee_id, name, team_id, committed_hours, reserved_hours
$teams | Select-Object team_id, name, employee_count, occupied_hours, utilization_pct, complete
$tasks | Select-Object task_id, title, team_id, assignee_employee_id, status
# Seleção local no cliente; não é um filtro da API:
$tasks | Where-Object { $_.status -ne "done" }
```

Abra `http://127.0.0.1:8000/docs`, expanda **employees**, **teams** ou **tasks**, clique em
**Try it out** e **Execute**. Os schemas de sucesso e erro estão disponíveis ali.
As respostas são arrays JSON, sem paginação. Não há filtros contratados ou token
exigido para essas consultas. Query strings, inclusive `status`, `team_id`,
`limit` e `page`, recebem HTTP 400 em formato padronizado.

As consultas usam o turno de `DEMO_REFERENCE_DATE`, sem aceitar datas por query.
Tarefas incluem abertas, em andamento e concluídas do período; concluídas não
ocupam carga. Funcionários exibem horas derivadas do banco e reservas ativas.
Ausência é derivada dos registros confirmados que intersectam o turno. Uma pessoa
presente e sem folga pode continuar `available`; disponibilidade não significa
que ela possa receber trabalho adicional.

Nas consultas de funcionários e tarefas, dados incompletos bloqueiam toda a
listagem com HTTP 422 e campos pendentes em
`error.details.records`, sem inventar zero/arrays vazios ou ocultar registros.
O contrato v1.2 aceita somente Slack: novos seeds usam `slack`, mas reexecutar o
seed preserva dados existentes. Pessoas legadas com `teams` precisam de correção
explícita na fonte antes de serem publicadas; o GET não escreve nem converte.

`GET /api/v1/teams` implementa a extensão aprovada do contrato v1.2. Consulte a
[proposta de equipes](docs/teams-query-proposal.md) e a seção 13 do contrato para
schema e regras. Os totais são calculados a partir dos membros atuais e dos
registros do turno configurado. Utilização é a soma da carga dividida pela soma
da capacidade, nunca a média dos percentuais individuais. Dados incompletos de
capacidade/estimativa produzem `null` e `complete=false`; capacidade zero produz
utilização `null`. Pessoas sem equipe bloqueiam a listagem com HTTP 422.
O frontend em outra origem precisará de CORS com uma lista explícita de origens
permitidas; essa configuração depende da URL do frontend e não foi presumida.

Para verificar a implementação em bancos temporários:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_queries.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration/test_teams.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Não são necessárias novas dependências ou migrações para estas consultas.

Veja [exemplos reais das respostas](docs/query-response-examples.md), obtidos em
banco temporário. Ruff foi usado como ferramenta local de verificação, sem
adicionar dependências de execução; para repetir seus checks em outro ambiente,
instale-o explicitamente com `python -m pip install ruff`.

## Registrar ausência confirmada

Antes de iniciar a API, aplique a nova migração incremental:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Em outro PowerShell, use um funcionário real do seed e os campos exatos do contrato:

```powershell
$body = @'
{
  "employee_id": "demo-atendimento-01",
  "starts_at": "2026-11-08T08:00:00-03:00",
  "ends_at": "2026-11-08T18:00:00-03:00",
  "confirmed": true,
  "source_system": "hr_simulator",
  "external_id": "absence-hr-001"
}
'@
$result = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/absences -ContentType "application/json; charset=utf-8" -Body $body
$result | ConvertTo-Json
```

Nova ocorrência: HTTP **201**, por exemplo (IDs gerados variam):

```json
{"absence_id":"abs-<uuid>","case_id":"case-<uuid>","status":"open"}
```

Reenviar exatamente a mesma ocorrência retorna **200** com os mesmos IDs, sem
duplicar auditoria ou vínculos. O escopo da chave é `(source_system, external_id)`.
Reutilizar a chave com conteúdo diferente ou informar outra ocorrência
sobreposta retorna **409**, incluindo `case_id` existente nos detalhes quando
houver vínculo. Intervalos são `[início, fim)`: períodos adjacentes são permitidos.
`confirmed=false` retorna 422; não existe uma rota separada de confirmação.
Datas devem conter fuso e o funcionário deve existir. Campos extras, inclusive
diagnóstico/causa médica, são rejeitados. Não há token n8n exigido nessa rota.

A ausência, o caso, as tarefas afetadas e a auditoria são gravados atomicamente.
Apenas tarefas abertas do funcionário no turno de referência intersectado são
vinculadas; o responsável e a carga permanecem intactos. Sem tarefas registradas,
o caso continua `open`, sem alegar cobertura confirmada. Consulte as decisões em
[docs/spec.md](docs/spec.md). O Swagger em `/docs` também documenta a operação.

A revisão `b07c91d42e36` adiciona proteções de sobreposição no SQLite e permite
auditoria sem política aplicada para os eventos dessa operação, preservando o
histórico existente. Seu downgrade é bloqueado se houver novos eventos com
política não aplicável, pois a revisão anterior não consegue representá-los sem
perda ou adulteração. Não execute downgrade destrutivo no banco de desenvolvimento.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_absences.py -q
.\.venv\Scripts\python.exe -m pytest -q
```
## Endpoint de callbacks do n8n (A13)

Configure `INTEGRATIONS_INTERNAL_TOKEN` como segredo no ambiente do backend.
Sem esse segredo, o endpoint falha fechado (`503`); chamadas sem o header
`X-Internal-Token` correto retornam `401`.

`POST /api/v1/integrations/attempt-events` recebe o contrato interno:

```json
{
  "event_id": "evt-001",
  "event_type": "offer.refused",
  "attempt_id": "att-001",
  "channel": "slack",
  "occurred_at": "2026-11-08T08:05:00-03:00",
  "reason": null
}
```

Resposta `202`: `{ "event_id": "evt-001", "status": "queued", "duplicate": false }`.
Repetição **idêntica** retorna `duplicate: true`, sem novo registro; colisão
de ID ou decisão concorrente retorna `409`. Também são validados existência e
estado pendente da tentativa, prazo, fuso horário e uma oferta real (não simulada)
no canal informado. Eventos de expiração exigem prazo encerrado.

**Limite importante:** `queued` significa que o evento foi persistido na inbox
`processed_events`, **não** que a pessoa já foi alocada ou que a decisão foi
aplicada. A transição com verificação de capacidade/política, liberação de reserva,
atribuição e auditoria pertence ao processador de negócios posterior. O n8n deve
enviar o payload no formato contratado (o JSON de saída dos botões, sozinho, ainda
não é uma chamada a este endpoint). Execute `pytest -q` para os testes HTTP e gerais.

## Agente de impacto

O registro de ausência agora grava uma análise detalhada das tarefas afetadas:
quantidade, horas conhecidas em risco, total completo ou desconhecido, pendências
de qualidade e evidências de divergência RH × tarefas. O JSON público de
`POST /api/v1/absences` permanece inalterado. Não há nova rota de impacto.

A análise seleciona tarefas abertas do funcionário pelo turno de referência
intersectado pela ausência, sem usar apenas o prazo como prova de execução.
Desconhecido não vira zero; competências desconhecidas não viram lista vazia.
Propostas e reservas não corrigem divergências. Não há realocação, chamada ao
motor, envio de mensagens ou alteração da carga.

Para os próximos serviços internos, `services.impact.analyze_case(session,
case_id, absence_id)` retorna o impacto original e o atual, preservando o histórico.
Use uma sessão nova; a função controla sua transação. Reanálises idênticas não
duplicam vínculos/eventos. Mudanças geram novas observações de auditoria; tarefas
concluídas ou transferidas continuam vinculadas ao histórico do caso. O reenvio
idêntico da criação de ausência não dispara nova análise.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_impact.py tests/integration/test_absences.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Não são necessárias novas dependências ou migrações. Veja as regras e os campos
internos em [docs/spec.md](docs/spec.md). Snapshot, planejamento e correção efetiva
permanecem nas atividades correspondentes.
