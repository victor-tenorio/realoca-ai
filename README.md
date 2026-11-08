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
