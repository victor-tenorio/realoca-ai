# Prompt consolidado para Lovable — Realoca AI

Implemente ou refine a interface existente do **Realoca AI**, plataforma B2B em português brasileiro para gestão de ausências e continuidade operacional. O produto deve ajudar RH/BPs a compreender tarefas, capacidade e propostas de cobertura. Não afirme cobertura confirmada por existir uma proposta.

## Direção visual e acessibilidade

Use uma identidade SaaS profissional, sóbria e acolhedora: navegação lateral verde-escura, superfícies claras, verde como cor de ação, âmbar para espera e vermelho discreto para risco. Mantenha hierarquia forte, tipografia legível, tabelas compactas e ícones consistentes. O layout deve funcionar em desktop, tablet e celular; navegação por teclado, foco visível, contraste adequado, labels acessíveis e respeito a prefers-reduced-motion são obrigatórios. Evite animações decorativas e métricas sem fonte.

## Navegação e páginas

Crie navegação para Visão Geral, Casos de Ausência, Tarefas, Equipes e Capacidade, Aprovações e Auditoria.

- **Visão Geral:** cards apenas com dados reais. Quando disponíveis, separar casos abertos, ausências, tarefas afetadas, horas em risco, horas planejadas, cobertura confirmada, aprovações pendentes e lacunas. Sem endpoint/dado, mostrar “Indisponível” ou “Não disponível”, nunca zero. Incluir prioridade das tarefas e capacidade das equipes somente com dados suficientes.
- **Casos:** tabela e detalhe com IDs, ausente/equipe/período, status, tarefas, propostas e histórico somente se forem retornados pelo backend. O registro de ausência exige confirmação e usa somente os campos contratados. Não incluir informação médica.
- **Tarefas:** tabela com ID, título, prioridade, status, responsável, equipe, estimativa, prazo e competências. Busca/filtros podem ser locais se a API não aceitar query parameters. Não ofereça edição sem rota autorizada.
- **Equipes e Capacidade:** exibir quantidade de funcionários, capacidade, comprometido, reservado, ocupado, utilização e completude. Preservar null como desconhecido; não converter em zero nem recalcular de modo contraditório com o servidor.
- **Aprovações:** fila/detalhe só quando houver endpoints reais. Aprovar/rejeitar somente depois de confirmação do usuário e apenas com suporte/autorização real; erros 409 não atualizam o estado local.
- **Auditoria:** timeline/tabela somente leitura, sem criar ou alterar eventos.

## Contrato de integração

Centralize HTTP, tipos TypeScript, tratamento de erros e estados loading/success/empty/error. Use VITE_API_BASE_URL; não inclua segredo no frontend. Respeite os payloads e enums documentados em docs/api-contract.md. Consulte apenas endpoints confirmados no backend instalado. Não invente rotas, filtros, campos ou estados. Para rotas ausentes, apresente indisponibilidade clara. Requisições devem poder ser canceladas ao desmontar a tela.

Os estados de tarefa/caso/tentativa permanecem distintos: proposta, aprovação BP, reserva, notificação, aceite, cobertura confirmada e conclusão não são sinônimos. O frontend nunca grava responsável nem declara aceite/cobertura por inferência.

## Estados e qualidade

Cada página deve ter loading, erro com tentativa de recarga, empty e sucesso. Mostrar conflitos e validações recebidos da API sem stack trace. Usar dados demonstrativos só se estiverem isolados e identificados visualmente; nunca misturar com respostas reais.

## Critérios de aceite

Navegação completa; dashboard sem números inventados; filtros de tarefas funcionais; valores desconhecidos preservados; casos sem tarefas e equipes incompletas tratados; decisões de aprovação confirmadas pelo servidor; auditoria somente leitura; falha de rede e carregamento visíveis; responsividade e teclado; testes para navegação, cards, filtros, dados ausentes, erros, ações autorizadas e separação entre proposta/reserva/aceite/conclusão. Não sobrescreva backend, migrações ou configuração de segredo.
