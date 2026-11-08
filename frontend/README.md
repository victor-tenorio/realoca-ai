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

## Dados e segurança

O frontend não tem fixtures de demonstração em runtime e não contém tokens. O modo de desenvolvimento usa apenas o proxy e a API real. Os dados de aprovação, reserva, aceite, cobertura confirmada e conclusão permanecem distinguíveis; a interface não atualiza estados localmente para fingir uma resposta do servidor.

Um npm run build gera frontend/dist, ignorado pelo Git. O arquivo frontend/.env.example contém somente endereços não sensíveis. Para incorporar uma futura exportação do Lovable, revisar e mesclar componentes em frontend/src; não inicializar um repositório Git dentro desta pasta.
