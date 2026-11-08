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

O backend atual não tem rotas implementadas para consulta de casos, dashboard, propostas/aprovações ou auditoria. As páginas correspondentes identificam essa indisponibilidade; aprovações e auditoria não oferecem ações simuladas. A página de casos permite somente o registro real de uma ausência confirmada pela rota existente.

Em produção, se o frontend e API estiverem em origens diferentes, o backend precisará permitir explicitamente a origem implantada via CORS. Não foi alterada a configuração do backend porque a origem final ainda não existe.

## Simulador Slack e estados

O Simulador Slack é uma demonstração isolada com quatro cenários fixos e fictícios. Aceites e recusas alteram somente o estado React da página; nenhum endpoint de callback é chamado, nenhum dado é gravado e não se alega que uma mensagem saiu pelo Slack. O backend atual só aceita callbacks autenticados para ofertas reais não simuladas; não existe um endpoint de resposta do simulador no contrato/backend.

Os indicadores do dashboard somam as estimativas das tarefas `open` e `in_progress`; `done` não entra na demanda ativa. Uma lista vazia retornada pela API produz zero; falha ou dado ainda carregando permanece indisponível. Casos, aprovações, reservas por tentativa, auditoria e cobertura confirmada não são calculados sem as consultas correspondentes.

## Testes ponta a ponta

Playwright inicia uma instância Vite exclusiva na porta 5188 (`--strictPort`) e intercepta as consultas da API com fixtures determinísticas. Os fluxos de ausência não escrevem no banco real. Para instalar o navegador Chromium do Playwright, execute `npx playwright install chromium`; depois `npm run test:e2e`. O relatório HTML e screenshots ficam em `playwright-report/` e `test-results/`, ignorados pelo Git. `npm run test:e2e:ui` abre a interface de depuração.

## Dados e segurança

As telas operacionais consultam a API real; os únicos dados fictícios em runtime pertencem ao Simulador Slack, isolado e rotulado. O frontend não contém tokens. Os dados de aprovação, reserva, aceite, cobertura confirmada e conclusão permanecem distinguíveis; a interface operacional não atualiza estados localmente para fingir uma resposta do servidor.

Um npm run build gera frontend/dist, ignorado pelo Git. O arquivo frontend/.env.example contém somente endereços não sensíveis. Para incorporar uma futura exportação do Lovable, revisar e mesclar componentes em frontend/src; não inicializar um repositório Git dentro desta pasta.
