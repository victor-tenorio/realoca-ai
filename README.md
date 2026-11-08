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
SQLite migrado. Eventos têm armazenamento de resultado anterior, mas o consumidor
idempotente, as transições, a aprovação/aceite e o envio ainda não existem.
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
$tasks = Invoke-RestMethod http://127.0.0.1:8000/api/v1/tasks
$employees | Select-Object employee_id, name, team_id, committed_hours, reserved_hours
$tasks | Select-Object task_id, title, team_id, assignee_employee_id, status
# Seleção local no cliente; não é um filtro da API:
$tasks | Where-Object { $_.status -ne "done" }
```

Abra `http://127.0.0.1:8000/docs`, expanda **employees** ou **tasks**, clique em
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

Dados incompletos bloqueiam toda a listagem com HTTP 422 e campos pendentes em
`error.details.records`, sem inventar zero/arrays vazios ou ocultar registros.
O contrato v1.1 aceita somente Slack: novos seeds usam `slack`, mas reexecutar o
seed preserva dados existentes. Pessoas legadas com `teams` precisam de correção
explícita na fonte antes de serem publicadas; o GET não escreve nem converte.

`GET /api/v1/teams` ainda não está contratado ou publicado. Consulte a
[proposta de equipes](docs/teams-query-proposal.md) para schema e exemplo.
O frontend em outra origem precisará de CORS com uma lista explícita de origens
permitidas; essa configuração depende da URL do frontend e não foi presumida.

Para verificar a implementação em bancos temporários:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_queries.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Não são necessárias novas dependências ou migrações para estas consultas.

Veja [exemplos reais das respostas](docs/query-response-examples.md), obtidos em
banco temporário. Ruff foi usado como ferramenta local de verificação, sem
adicionar dependências de execução; para repetir seus checks em outro ambiente,
instale-o explicitamente com `python -m pip install ruff`.
