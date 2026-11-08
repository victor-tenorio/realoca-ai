# Realoca AI — Converge Challenge 2026

## Projeto

Realoca AI mantém a continuidade operacional quando uma pessoa se ausenta.
Relaciona a ausência às tarefas do turno, calcula candidatos com competências
e capacidade compatíveis, aplica políticas de aprovação e acompanha propostas,
recusas, replanejamentos e cobertura em uma trilha auditável.

Repositório: https://github.com/victor-tenorio/realoca-ai

Frontend da demonstração: http://localhost:5173

API local: http://127.0.0.1:8001 — documentação: http://127.0.0.1:8001/docs

As URLs locais funcionam no computador AMANDA, que executa os servidores.
Em outro computador, `localhost` aponta para esse outro computador. As capturas
neste repositório documentam a demo; não existe hospedagem pública validada nesta
entrega. Para uma demonstração remota, compartilhe a tela da máquina AMANDA ou
utilize acesso remoto autenticado; a API não deve ser exposta publicamente sem
autenticação.

## Arquitetura e diferencial dos agentes

O frontend React/TypeScript consulta o FastAPI pelo proxy do Vite. O backend é
a autoridade sobre estado e persistência: SQLAlchemy, SQLite e migrações Alembic.
O motor Python é importado no backend; n8n integra os webhooks com Slack.

O diferencial está na coordenação de responsabilidades especializadas:

- Detecção de impacto: transforma ausência confirmada em um caso com tarefas afetadas.
- Planejamento: motor determinístico considera competências, capacidade, prioridade,
  prazos e políticas; propõe cobertura e identifica lacunas.
- Orquestração: backend controla versões, reservas e aprovações do BP, valida os
  eventos e mantém a auditoria. Proposta não equivale a atribuição confirmada.
- Comunicação e recuperação: n8n/Slack transportam propostas e respostas; uma
  recusa pode liberar a reserva e provocar replanejamento rastreável.

Esses papéis compõem o fluxo de agentes do produto. O MVP não utiliza LLM nem
agentes generativos autônomos: decisões e políticas são determinísticas.
O sistema redistribui responsabilidade; não executa o trabalho das tarefas.

## Demonstração para a banca

1. **Visão Geral:** indicadores da API; destaque 11h planejadas, 1h confirmada e
   0h concluída. Os totais são globais, não exclusivos do caso de recusa.
2. **Casos de Ausência:** selecione
   `case-5c3d64a2-c22a-4f92-b2af-25109f4f053c`. Mostre cinco tarefas, seis
   tentativas históricas e plano versão 2 em `awaiting_responses`.
3. **Auditoria:** filtre pelo mesmo ID e mostre `offer.refused` seguido de
   `plan.replanned`, ambos às 08:06:10 de 08/11/2026 em São Paulo. A reserva
   anterior de 1,5h foi liberada e outro candidato foi selecionado.
4. **Tarefas, Equipes e Aprovações:** consulte as 187 tarefas, quatro equipes e a
   fila de BP atualmente vazia. Não efetue novas aprovações ou planejamentos.

O [roteiro detalhado](demo-historico-validado.md) explica as tentativas e os
limites da evidência. Nenhum convite precisa ser reenviado para demonstrar o fluxo.

## Evidências da execução real

Validação local com Playwright/Chrome em 08/11/2026, sem mocks, conectada ao
FastAPI existente na porta 8001. As seis abas passaram; não houve exceções
JavaScript nem requisições de escrita durante a navegação. O console registra
somente o HTTP 422 conhecido de `/employees`, apresentado explicitamente na UI.
O React em modo de desenvolvimento cancela algumas consultas com `ERR_ABORTED`
durante montagem/desmontagem; essas ocorrências estão preservadas no relatório.

| Aba | Captura real |
| --- | --- |
| Visão Geral | [01-visao-geral.png](evidencias/01-visao-geral.png) |
| Casos de Ausência | [02-casos.png](evidencias/02-casos.png) |
| Tarefas | [03-tarefas.png](evidencias/03-tarefas.png) |
| Equipes e Capacidade | [04-equipes.png](evidencias/04-equipes.png) |
| Aprovações | [05-aprovacoes.png](evidencias/05-aprovacoes.png) |
| Auditoria | [06-auditoria.png](evidencias/06-auditoria.png) |

[Relatório HTTP, console e navegação](evidencias/smoke-real.json).

HTTP 200 em `/health`, `/api/v1/tasks`, `/api/v1/teams`, `/api/v1/cases`,
`/api/v1/dashboard` e `/api/v1/audit`. As respostas `/api/v1/...` foram comparadas
entre backend e proxy do Vite e são idênticas. `/employees` mantém HTTP 422 com
`INCOMPLETE_SOURCE_DATA` em ambos, preservando a validação.

Validação desta entrega:

- 31 testes React aprovados, incluindo três regressões da seleção por ID.
- 34 testes Python direcionados aprovados: consultas e planejamento exclusivo Slack.
- Typecheck TypeScript, build de produção e lint aprovados.
- Script `scripts/start_demo.ps1` reexecutado duas vezes: mesmos PIDs nas portas
  5173 e 8001, sem reiniciar ou duplicar os serviços existentes.

Não foi repetida a suíte completa histórica de CI nesta finalização.

## Execução da demo existente

Na raiz do repositório: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_demo.ps1`.
O script utiliza o virtualenv e dependências já instalados, exige o banco
existente, define a API na porta 8001 e o proxy do Vite para essa porta. Serviços
são mantidos em processos Windows independentes e logs locais em `.demo-logs/`.
Portas ocupadas são verificadas; processos existentes não são encerrados.
Não executa seed, reset ou migração automática. Não constitui serviço de boot:
após reiniciar o Windows, execute novamente o script.

Para repetir somente a verificação de leitura: em `frontend/`, execute
`node scripts/smoke-real.mjs` com Chrome instalado e ambos os servidores ativos.

## Limitações transparentes

- Dados de pessoas/tarefas são sintéticos da demo, mas casos, tentativas e eventos
  exibidos são persistidos e consultados na API real, sem substituição por fixtures.
- Vinte registros legados usam Teams e não têm mapeamento Slack autorizado.
  `/employees` permanece bloqueado. A UI avisa sobre dados incompletos e permite
  selecionar apenas IDs já presentes em `/tasks`, sem inventar nomes ou contatos.
  O total de funcionários permanece desconhecido, não zero. O registro de ausência
  fica bloqueado nesse modo; demais consultas continuam funcionando.
- A seleção alternativa por ID não autoriza ou envia convites Slack. Nenhum
  destinatário foi convertido e nenhuma validação do backend foi relaxada.
- Os prazos das propostas históricas já passaram. Estados persistidos não foram
  alterados para a apresentação. Reserva/enfileiramento não comprovam entrega,
  aceite, cobertura confirmada ou conclusão.
- O segundo convite do caso demonstrado aparece enfileirado, sem evento de
  entrega ou aceite. O histórico comprova a recusa e o replanejamento.
- O Simulador Slack é local e fictício, rotulado como tal; não é evidência da
  integração real. Para a banca, use a auditoria persistida.
- Autenticação corporativa, operação em produção e implantação pública não foram
  validadas. Segredos, banco local e logs não fazem parte do commit.

## Envio ao desafio

Use este texto, o link do repositório e as seis capturas no formulário oficial.
Caso o formulário exija vídeo, grave a sequência de leitura acima e anexe o link
conforme o requisito do evento. Confirme os campos obrigatórios, os integrantes
e conclua o envio no portal até 13h de 08/11/2026 (São Paulo).
Preparar este repositório não equivale a enviar o formulário: a submissão no
portal e seu comprovante ainda precisam ser concluídos.
