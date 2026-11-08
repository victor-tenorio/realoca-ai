# Frontend Realoca AI

Interface React + TypeScript + Vite para o painel operacional. O repositório não continha uma exportação do Lovable nem outro frontend; esta implementação foi criada localmente, não gerada pelo Lovable.

## Requisitos e comandos

Use Node.js 20.19+ ou 22.12+ e npm. No PowerShell:

    cd frontend
    Copy-Item .env.example .env
    npm install
    npm run dev

Comandos de qualidade:

    npm test
    npm run test:e2e
    npm run lint
    npm run typecheck
    npm run build
    npm run preview

## API

VITE_API_BASE_URL define a base da API. No desenvolvimento, o padrão /api/v1 é encaminhado pelo proxy do Vite a VITE_DEV_PROXY_TARGET (padrão http://127.0.0.1:8000), evitando CORS local. A API precisa estar iniciada, com migrações aplicadas e seed executado, conforme o README da raiz.

Rotas verificadas no backend atual e consumidas:

- GET /api/v1/employees
- GET /api/v1/tasks
- GET /api/v1/teams
- POST /api/v1/absences
- GET /api/v1/cases e GET /api/v1/cases/{case_id}
- POST /api/v1/cases/{case_id}/plan (somente quando não existe proposta)
- GET /api/v1/dashboard (métricas de cobertura persistidas)
- GET /api/v1/audit?case_id=... (histórico auditável)
- POST /api/v1/proposals/{attempt_id}/approval (decisão BP por ator/motivo)

O backend **já disponibiliza** consultas de casos, dashboard, aprovações e auditoria. As páginas consomem essas rotas reais, mostram estados provenientes do servidor e permitem planejar somente casos sem propostas, e decidir propostas pendentes de BP com ator/justificativa explícitos. A página de casos também registra ausências reais. A tela **Simulador Slack** permanece isolada, fictícia e não invoca callbacks nem altera o banco. Não confundir dados do simulador com eventos n8n reais.

Em produção, se o frontend e API estiverem em origens diferentes, o backend precisará permitir explicitamente a origem implantada via CORS. Não foi alterada a configuração do backend porque a origem final ainda não existe.

## Simulador Slack e estados

O Simulador Slack é uma demonstração isolada com quatro cenários fixos e fictícios. Aceites e recusas alteram somente o estado React da página; nenhum endpoint de callback é chamado, nenhum dado é gravado e não se alega que uma mensagem saiu pelo Slack. O backend atual só aceita callbacks autenticados para ofertas reais não simuladas; não existe um endpoint de resposta do simulador no contrato/backend.

Os indicadores do dashboard somam as estimativas das tarefas `open` e `in_progress`; `done` não entra na demanda ativa. Uma lista vazia retornada pela API produz zero; falha ou dado ainda carregando permanece indisponível. Casos, aprovações, reservas por tentativa, auditoria e cobertura confirmada não são calculados sem as consultas correspondentes.

## Testes ponta a ponta

Playwright inicia uma instância Vite exclusiva na porta 5188 (`--strictPort`) e intercepta as consultas da API com fixtures determinísticas. Os fluxos de ausência não escrevem no banco real. Para instalar o navegador Chromium do Playwright, execute `npx playwright install chromium`; depois `npm run test:e2e`. O relatório HTML e screenshots ficam em `playwright-report/` e `test-results/`, ignorados pelo Git. `npm run test:e2e:ui` abre a interface de depuração.

## Dados e segurança

As telas operacionais consultam a API real; os únicos dados fictícios em runtime pertencem ao Simulador Slack, isolado e rotulado. O frontend não contém tokens. Os dados de aprovação, reserva, aceite, cobertura confirmada e conclusão permanecem distinguíveis; a interface operacional não atualiza estados localmente para fingir uma resposta do servidor.

Um npm run build gera frontend/dist, ignorado pelo Git. O arquivo frontend/.env.example contém somente endereços não sensíveis. Para incorporar uma futura exportação do Lovable, revisar e mesclar componentes em frontend/src; não inicializar um repositório Git dentro desta pasta.


## Demonstração final / frontend e backend no mesmo computador

O backend de Amanda foi testado em \`http://127.0.0.1:8001\`; o Vite
usa \`http://127.0.0.1:8000\` por padrão. Ajuste **antes** de iniciar
\`npm run dev\`:

    cd frontend
    Copy-Item .env.example .env
    Add-Content .env 'VITE_DEV_PROXY_TARGET=http://127.0.0.1:8001'
    npm ci
    npm run dev

Abra a URL impressa pelo Vite (\`http://localhost:5173\` por padrão).
O proxy \`/api/v1\` evita problemas de CORS, desde que a API esteja viva.
Mantenha o túnel Cloudflare e o workflow n8n apenas se quiser fazer
nova demonstração com Slack real; as **consultas** de casos/auditoria
funcionam localmente sem tunnel.

Use a aba **Casos** para observar uma ausência já criada, suas propostas
e estados do backend; **Visão geral** mostra horas planejadas,
confirmadas e concluídas a partir de \`/dashboard\`. A aba
**Aprovações** só permite ações após o operador digitar identificador e
justificativa do BP (ambiente fictício, sem login corporativo). A aba
**Auditoria** mostra os eventos auditáveis sem inventar dados.

### Validação

    npm run typecheck
    npm run lint
    npm test
    npm run build
    npm run test:e2e

Para o último comando, instale o Chromium previamente com
\`npx playwright install chromium\` (e dependências de sistema no Linux).
Os testes \`frontend/e2e/journeys.spec.ts\` utilizam **interceptação de
API com dados fictícios**, não o banco de Amanda nem o Slack real.
O GitHub Actions executa testes unitários, TypeScript, build e E2E visual
com captura em caso de falha.

### Limites honestos

- A UI não autentica papéis BP corporativos; apenas registra \`actor_id\`
  informado no endpoint real, adequado à demo sintética.
- A interface não faz clique real no Slack: a demo externa comprovada
  ocorre no workflow n8n; o painel Slack da UI continua **simulador**.
- A aplicação React foi implementada diretamente em \`frontend/\`, **não
  é uma exportação do Lovable**, embora o Notion use essa linguagem nas
  tarefas M13/M14. O código versionado e os comandos de reprodução
  cumprem o objetivo de ter uma interface operacional demonstrável.
- M20 (otimização inteira e tarefas divisíveis) é evolução P1, não
  requisito para o MVP P0; o motor atual não divide tarefas.
