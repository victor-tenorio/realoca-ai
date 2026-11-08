# Realoca AI — documento pendente

Conteúdo oficial pendente. Este arquivo é apenas um marcador estrutural; não define rotas, payloads ou requisitos.


## Decis?es de modelagem da demo

Decis?es autorizadas para esta atividade em 07/11/2026. O marcador original
acima foi preservado. Esta se??o especifica a persist?ncia da demo; n?o substitui
os nomes, formatos ou enums p?blicos do contrato v1.0.

### RH, tarefas e origem

- `teams`: ID string, nome e metadados de origem. `employees`: ID string, nome,
  `job_title` interno, uma equipe opcional, canal e metadados de origem.
- `skills`, `employee_skills`, `task_skills`: identificadores normalizados por
  trim/lowercase; associa??es ?nicas. A representa??o p?blica continua sendo
  arrays de strings, nunca objetos ou nomes de funcion?rios. `skills_known` e
  `required_skills_known` distinguem desconhecido de lista conhecida vazia.
  Flags falsas invalidam o conjunto inteiro para elegibilidade/publica??o,
  mesmo se houver associa??es parciais importadas.
- `tasks`: campos do contrato, turno interno obrigat?rio, equipe de origem e
  respons?vel atual independentes. Prioridades: critical/high/medium/low;
  estados: open/in_progress/done. Nenhum endpoint de neg?cio foi criado.
- `task_assignments`: estrutura para hist?rico expl?cito futuro, com IDs string,
  tarefa, respons?vel anterior opcional, pr?ximo respons?vel, instante e motivo.
  Equipes distintas n?o provam transfer?ncia. O seed n?o cria hist?rico.
  O fluxo futuro dever? registrar hist?rico/auditoria na mesma transa??o da
  altera??o, ap?s aceite e aprova??es; esta etapa n?o executa transfer?ncias.
- Registros de RH/tarefas usam `source_system`, `external_id`, `updated_at`;
  o par (source_system, external_id) ? ?nico por entidade. Fontes fict?cias
  separadas: hr_simulator e task_simulator. IDs internos s?o strings est?veis.
  FKs restringem remo??o de registros referenciados, sem cascade destrutivo.

### Turno, precis?o e carga

- `shifts` identifica um ?nico turno operacional por data de refer?ncia;
  `employee_shifts` identifica a capacidade por funcion?rio/turno (chave composta).
  A demo usa DEMO_REFERENCE_DATE (padr?o 2026-11-08), 08h?16h UTC?03:00 e 8h
  por pessoa, 80h por equipe. N?o h? planejador de m?ltiplos turnos.
- Datas recebidas pelo ORM exigem fuso. SQLite armazena datetime UTC sem fuso;
  o tipo UTCDateTime restitui UTC com fuso. SQL direto deve gravar UTC; a
  valida??o de fuso pertence ? camada de entrada, pois SQLite n?o o preserva.
- Horas usam Decimal/Numeric(12,6). A entrada ORM rejeita n?o finitos,
  magnitude >= 1000000 e precis?o superior a seis casas em vez de arredondar.
  O SQLite usa afinidade NUMERIC; importadores devem usar os tipos ORM, n?o SQL
  direto, para preservar essas valida??es. Nenhum c?lculo intermedi?rio de
  capacidade ? arredondado; arredondamento de exibi??o cabe ao consumidor.
- `committed_hours` ? soma das estimativas das tarefas do turno cujo estado ?
  open ou in_progress e cujo respons?vel atual ? o funcion?rio. N?o h? contador
  persistido/cache. `done` n?o entra nessa soma. Estimativas conhecidas > 0;
  capacidade conhecida >= 0. NULL nunca vira zero.
- Ocupa??o = committed_hours + reserved_hours; utiliza??o = ocupa??o /
  shift_hours ? 100; folga f?sica = shift_hours ? ocupa??o; margem = max(0,
  shift_hours ? limite/100 ? ocupa??o). A margem usa 90% por padr?o. Carga
  preexistente acima desse limite, ou mesmo acima da capacidade, pode ser
  representada; o banco n?o aplica limite de admiss?o. Presen?a n?o prova folga.
- Capacidade desconhecida ou zero produz utiliza??o n?o aplic?vel (None);
  capacidade zero conhecida tem margem zero. Estimativa desconhecida numa soma
  torna o total desconhecido. N?o se apresenta soma parcial como total.
  Carga da equipe segue a equipe do respons?vel atual; capacidade nominal soma
  seus membros. Tarefas da equipe com respons?vel desconhecido marcam esse
  agregado como incompleto. A origem da tarefa permanece dispon?vel separada.

### Reservas, aus?ncias e aus?ncia de dupla contagem

Casos, tentativas, aus?ncias, aprova??o e aceite ainda n?o existem. N?o foram
criadas FKs falsas, reservas fict?cias ou um estado persistido de aus?ncia.
`availability` permanece um enum p?blico; quando o m?dulo de aus?ncias existir,
ser? derivado de aus?ncias confirmadas no turno e da indisponibilidade aplic?vel,
sem confundir disponibilidade pessoal com margem de carga. A fixture Carlos/Pedro
n?o inventa um estado persistido de aus?ncia para Jo?o.

Reservas dependem de casos/tentativas: uma migra??o posterior dever? criar os
registros ligados ? tentativa, tarefa, candidato e turno, com horas n?o negativas,
hist?rico preservado e unicidade de tentativa ativa por tarefa. `reserved_hours`
ser? exclusivamente a soma dessas reservas ativas. At? l?, o c?lculo desta etapa
retorna zero e `reservations_supported=False`, indicando que a integra??o ainda
n?o existe; isso n?o representa m?tricas de propostas/aceites implementadas.
A futura convers?o altera o respons?vel e baixa a reserva atomicamente. N?o se
incrementa committed_hours manualmente: a tarefa passa a entrar na soma do novo
respons?vel, sem contar tamb?m sua reserva. Aprova??o n?o ? aceite.

### Importa??o incompleta e contrato p?blico

Equipe, respons?vel, estimativa, prazo, habilidades, capacidade, canal e prioridade
podem estar desconhecidos internamente. Os modelos SQLAlchemy n?o s?o schemas
Pydantic. `app/services/data_quality.py` lista pend?ncias para os futuros
serializadores impedirem publica??o de registros incompletos no formato p?blico;
nenhum schema p?blico foi alterado para aceitar null. Informa??o essencial
faltante impede decis?o autom?tica. Os servi?os futuros devem verificar tamb?m
a completude da carga e a disponibilidade antes de montar snapshots.

### Seed e fixtures

`python -m app.demo.seed` grava atomicamente 40 funcion?rios fict?cios, quatro
equipes de dez e 187 tarefas abertas (open/in_progress), todas no turno
configurado. Horas resultantes das tarefas: Atendimento 47,5; Opera??es 50;
Financeiro 75,5; Tecnologia 52,5. Estimativas entre 0,5h e 2h e requisitos
compat?veis com as habilidades do respons?vel. Nenhuma aus?ncia, reserva,
realoca??o ou transfer?ncia ? criada.

`demo_seed_runs` ? um marcador interno de conclus?o transacional. Reexecutar
preserva todos os valores existentes, mesmo se alterados; n?o restaura nem apaga
registros. Seeds n?o s?o migra??es: aplicar Alembic antes. Para experimentar
outra data/cen?rio, use outro banco. Colis?es n?o s?o corrigidas silenciosamente;
erros causam rollback. N?o existe comando de reset nesta atividade.

`app/demo/scenarios.py` fornece fixtures separadas: incomplete, no_slack,
above_policy, completed e carlos_pedro. S?o destinadas a bancos isolados. A ?ltima
mant?m Python/Excel, candidatos Carlos/Pedro com 2h, tarefas de Jo?o e pol?tica
100% apenas nesse teste. Criar essa fixture n?o valida o planejador.

### Fontes futuras do dashboard

| Indicador | Registros / regra |
| --- | --- |
| Funcion?rios | employees; agrupamento pela equipe atual |
| Ausentes | futuras aus?ncias confirmadas que intersectam o turno; ainda indispon?vel |
| Tarefas abertas | tasks com open/in_progress no turno |
| Horas ainda atribu?das a ausentes | futuras aus?ncias + respons?vel atual de tasks abertas; indispon?vel |
| Carga/utiliza??o por equipe | tarefas dos membros atuais + reservas ativas futuras / employee_shifts |
| Horas reservadas | futuras reservas ativas; integra??o ainda indispon?vel |
| Cobertura planejada | futuros planos/tentativas; indispon?vel |
| Cobertura confirmada | futuros aceites v?lidos + aprova??es aplic?veis; indispon?vel |
| Tarefas conclu?das | tasks com done no turno |

Aprova??o isolada n?o confirma cobertura. Com demanda zero, porcentagem de
cobertura ? n?o aplic?vel (None, exib?vel como ???), nunca 100%. Nenhum dashboard,
indicador fict?cio ou fluxo de orquestra??o foi implementado. N?o houve conflito
expl?cito que exigisse alterar o contrato; detalhes de m?dulos futuros permanecem
para suas atividades e migra??es correspondentes.

## Persistência de casos, tentativas, políticas, eventos e mensagens

Esta seção atualiza as dependências adiadas na etapa anterior. Não altera o
contrato público v1.0. A migração incremental `65aad520e5e0`, após
`d00209376958`, acrescenta as estruturas abaixo sem reescrever a migração inicial
ou modificar os dados de RH/tarefas existentes. IDs de entidades continuam strings;
versões de plano e política são inteiros positivos.

### Ocorrências e decisões

- `absences` implementa a dependência mínima: funcionário, intervalo com fuso,
  confirmação, origem, identificador externo e atualização. O par de origem é
  único e o intervalo exige fim posterior ao início. Não há diagnóstico ou
  campo médico. Sobreposição, criação de caso e resposta idempotente HTTP serão
  responsabilidade do futuro serviço, não de um registro sintético.
- `cases` mantém status oficial, versão atual do plano (zero antes do primeiro
  plano), criação e encerramento. `case_absences` e `case_tasks` são associações
  permanentes e únicas. Mudar o responsável da tarefa não muda o conjunto
  originalmente afetado. Remover/alterar esses vínculos é bloqueado no SQLite.
  O serviço futuro de criação garantirá um conjunto não vazio e coerente de
  ausências/tarefas; o estado será recalculado em `services/cases.py`.
- `coverage_plans` identifica o plano e sua versão única por caso, com política
  aplicada e criação. Planos são históricos imutáveis. O ponteiro
  `cases.plan_version` será sincronizado pelo futuro serviço de planejamento.
- `coverage_attempts` referencia uma tarefa efetivamente vinculada ao caso e um
  plano/versão do mesmo caso por FKs compostas, além de candidato e política.
  Prazo de resposta, motivo, criação e resposta usam UTC. Os estados permanecem
  exatamente os oficiais, sem `completed` para tentativa. Candidato pode ser
  desconhecido somente em `escalated`, permitindo registrar falta de solução.
  O formato futuro de `uncovered.reason_code/alternatives` permanece pendente de
  alinhamento conforme CLAUDE.md; não foi inventada uma estrutura pública.
- São ativos: `proposed`, `pending_approval`, `reserved` e `notified`.
  O índice parcial único `uq_active_attempt_task` limita a uma tentativa ativa
  por tarefa em todo o banco, inclusive entre casos e versões diferentes.
  `accepted`, `refused`, `expired`, `rejected_by_bp` e `escalated` são terminais
  para esse índice. A tarefa aceita continua ocupando capacidade via suas horas.
  Propor novamente exige outra linha; identidades da tentativa são imutáveis,
  e exclusão do histórico é bloqueada. Validação de transições, exclusões por
  recusa, deadline e revalidação de capacidade/política permanecem nos serviços
  futuros. Os testes que gravam estados diretamente verificam persistência,
  sem substituir `attempts.transition`.
- Informações internas de aprovação (`approval_decision`, `approval_actor_id`,
  `approval_reason`, `approval_decided_at`) são distintas da resposta do
  funcionário (`responded_at`, `decision_actor_id`, `reason`). A decisão BP usa
  apenas `approve`/`reject`; ator e instante são obrigatórios quando ela existe.
  Esses campos não acrescentam payloads públicos ou implementam aprovação.

### Política e auditoria

`policy_versions` guarda versões imutáveis com os seis campos oficiais e defaults
90%, true, true, 15 minutos, true e 5 minutos. A utilização deve ser >0 e <=100,
timeout positivo e lembrete entre zero e o timeout (exclusivo). São configurações
da demo, sem equivalência a regra trabalhista. Criar a primeira versão é explícito:
a migração não cria decisões, casos, registros de teste ou política ativa oculta.
O futuro serviço de políticas selecionará a versão vigente, publicará alterações
como novas versões e auditará essa seleção.

Cada plano e tentativa referencia a versão aplicada. A tentativa guarda a versão
da classificação original; novas decisões/revalidações com outra versão devem
registrá-la na auditoria, preservando a anterior. Não se sobrescrevem versões.

`audit_events` é separado da caixa de entrada de integração. Guarda
`audit_event_id`, `case_id`, `attempt_id`, `actor`, `action`, `timestamp`,
`policy_version`, `reason` e `result`. Caso é opcional para ações globais, como
mudança de política; uma tentativa exige caso correspondente. UPDATE, DELETE e
substituição de um ID existente são bloqueados por triggers SQLite, inclusive em
SQL direto. A geração automática dos eventos pelo serviço de auditoria ainda não
existe. Campos livres devem conter somente razões operacionais e resultados
sanitizados, sem dados médicos, tokens ou credenciais.

### Integração e mensagens

- `processed_events` guarda o `event_id` único recebido, tipo oficial, tentativa,
  canal, instante original, motivo operacional, recebimento e processamento.
  Antes de processar, resultado e HTTP status são NULL; ao registrar resultado,
  os três campos devem estar presentes. O resultado persistido e o código HTTP
  permitem ao futuro consumidor devolver a resposta anterior. Identidade e
  conteúdo recebido não podem ser alterados, nem o resultado após processamento.
  Não são persistidos headers, tokens ou cópias arbitrárias do request.
- Isso **não é idempotência completa**: ainda faltam reivindicação/concorrência,
  tratamento de duplicatas, validação semântica, aplicação dos efeitos e gravação
  do resultado na mesma transação, além da recuperação após falha. Receber
  `offer.accepted` não muda a tentativa ou atribui uma tarefa nesta etapa.
- `outbound_messages` guarda evento único `offer.created`, tentativa, canal
  teams/slack, destinatário, conteúdo operacional e indicação explícita
  `simulated`. Não há flag default que confunda integração real e simulada.
  O conteúdo deve conter somente oferta de tarefa e prazo, sem causa da ausência.
- `message_deliveries` registra cada tentativa de transporte da mesma mensagem:
  número sequencial único por mensagem, início, envio, entrega ou falha,
  código sanitizado de erro e ID do provedor. Falha permite outro registro de
  envio sem outra proposta de cobertura. Entrega exige envio anterior; falha de
  transporte e envio bem-sucedido são resultados distintos. Falha de entrega
  posterior é registrada como evento de integração. Nenhum desses instantes
  representa resposta/aceite do funcionário. Não foram criados estados públicos
  novos de tentativa nem qualquer chamada a Teams/Slack/n8n.
- O despachante futuro deverá montar/validar o webhook contratado e seu contexto
  de tarefa/prazo. Limites de retentativa e intervalos continuam pendentes de
  alinhamento conforme CLAUDE.md. Não há envio real nem worker nesta etapa.

### Reservas e capacidade

A dependência de reservas está resolvida na persistência: `reservations` tem ID,
tentativa única, horas não negativas, criação e baixa. Tarefa e candidato derivam
da tentativa; turno deriva da tarefa. Isso evita identidades duplicadas que
possam divergir. O turno da tarefa fica protegido contra alterações após existir
histórico de tentativa. Reservas ativas exigem tentativa `reserved`/`notified`,
candidato diferente do responsável atual e vínculo do candidato ao turno.
`pending_approval` não admite reserva ativa. Uma baixa é definitiva; reserva e
horas originais permanecem no histórico. Nova proposta exige nova tentativa.

A fonte de `reserved_hours` é a soma das reservas sem `released_at`, consultada
por funcionário/turno em `services/capacity.py`. O campo público da tentativa é
uma propriedade derivada, não outro contador. `reservations_supported=True`
substitui a indicação provisória da etapa anterior. Carga comprometida continua
derivada exclusivamente das tarefas abertas e a ocupação soma ambos os valores.
O helper `team_capacity` mantém seus totais de capacidade nominal e compromisso;
o dashboard futuro deverá somar reservas dos membros para obter ocupação.

Antes de finalizar uma tentativa ou atribuir sua tarefa ao candidato, o SQLite
exige a baixa da reserva ativa, impedindo dupla contagem. O serviço futuro deverá
efetuar baixa, atribuição, transição e auditoria na mesma transação, após todas as
validações. Não há conversão automática, admissão pela política, checagem de
capacidade global concorrente ou liberação automática por timeout/recusa.
O seed principal permanece com zero casos, ausências, tentativas e reservas.

### Garantias e migrações

As proteções append-only e de ciclo de reserva são instaladas por Alembic na
stack SQLite adotada, não por `create_all`. A migração usa tipos SQL estáveis sem
importar os modelos atuais. O downgrade remove somente estas tabelas, índices e
triggers, preservando RH, tarefas, turno e seed da revisão anterior; naturalmente
descarta os registros dos módulos novos. Testes usam bancos temporários para
upgrade vazio, atualização com seed existente, downgrade com dados novos e
reaplicação. Nenhum endpoint, planejador ou schema público foi alterado.

## Consultas de funcionários e tarefas — contrato v1.1

As rotas de consulta agora publicadas são `GET /api/v1/employees` e
`GET /api/v1/tasks`. Retornam arrays JSON diretos dos registros persistidos, com
os campos do modelo comum do contrato, sem campos internos ou envelopes.
Não há autenticação exigida para essas consultas no contrato atual; o token de
integração servidor/n8n não foi aplicado às leituras. A autenticação do frontend
permanece uma decisão pendente do contrato.

O contrato não define filtros, paginação ou seleção de data por query string.
Não foram acrescentados. Parâmetros desconhecidos são rejeitados com HTTP 400
e `INVALID_QUERY_PARAMETERS`, em vez de serem ignorados. As tarefas incluem
todos os estados oficiais no turno configurado, inclusive `done`; somente o
cálculo de carga exclui concluídas. Esta leitura não implementa conclusão.

### Período, projeção e publicação

- O período é o único turno cuja `reference_date` coincide com
  `DEMO_REFERENCE_DATE`. As listagens não criam turno, seed ou qualquer registro.
  Sem pessoas cadastradas, a consulta retorna `[]`. Sem turno da data, tarefas
  retorna `[]`, pois não existem tarefas desse período; havendo pessoas sem
  capacidade de referência, funcionários retorna 422, sem presumir carga zero.
- Capacidade individual usa as mesmas fórmulas de `services/capacity.py`, com
  projeção em lote: tarefas abertas e reservas ativas somente do mesmo turno.
  Não existem queries por pessoa/tarefa. O helper individual continua disponível;
  a versão em lote compartilha a soma com propagação de desconhecidos e o cálculo.
- `availability` é derivada: ausência confirmada que intersecciona o turno
  (`starts_at < shift.ends_at` e `ends_at > shift.starts_at`) produz `absent`.
  Sem essa ausência, capacidade conhecida zero produz `unavailable` para o turno;
  vínculo com turno e capacidade positiva produz `available`, mesmo que a carga
  já ocupe toda a capacidade. Não se infere folga por presença. A ausência tem
  precedência sobre capacidade zero; nenhuma causa de ausência é publicada.
  Outras causas de indisponibilidade pessoal ainda não têm fonte persistida e
  não são inventadas por estas consultas.
- Habilidades conhecidas vazias são arrays vazios. Habilidades desconhecidas não
  viram arrays vazios; são pendências de publicação. Equipe de origem e ID do
  responsável são retornados como campos separados da tarefa. Não se expõe um
  indicador de transferência sem histórico, nem se acrescenta esse campo ao
  contrato. A interface pode correlacionar o responsável com a lista de pessoas.
- Schemas de saída são Pydantic separados dos modelos ORM, com enums oficiais,
  datas com fuso e horas JSON numéricas. Campos opcionais da importação não foram
  tornados opcionais no contrato público. Horas não são arredondadas durante a
  soma; a serialização JSON é a apresentação final.

A estratégia de publicação é bloquear **a listagem inteira** com HTTP 422 e
`INCOMPLETE_SOURCE_DATA` se qualquer registro do escopo não puder cumprir o schema.
Os detalhes identificam registros e nomes dos campos pendentes, sem expor dados
médicos. Não se retorna lista parcial, não se omite registro inválido e não se
publica `null` em campo obrigatório. Estimativa desconhecida em tarefa atribuída
também bloqueia a carga do funcionário, não a transforma em soma parcial.

O contrato v1.1 permite somente `slack`. O seed de novas bases usa Slack para
todas as pessoas. Registros legados com `teams` permanecem no armazenamento
histórico, porém bloqueiam a publicação de funcionários com pendência em
`preferred_channel`; a consulta nunca os converte nem altera. Corrigir a fonte
ou planejar a migração desses registros é uma ação explícita posterior. As
migrações históricas e os testes de histórico não foram reescritos.

Erros seguem `{"error":{"code":"...","message":"...","details":{}}}`.
Validação de requisição usa 400, impedimento de publicação usa 422, falhas de
banco usam 503 e falhas internas usam 500 sem mensagens SQL ou stack traces.
Os handlers também normalizam 404/405. `/health` continua fora de `/api/v1`.

### Equipes e frontend

A proposta de equipes foi aprovada por Mateus, conforme informado pela usuária.
`GET /api/v1/teams` integra a extensão compatível do contrato v1.2, seção 13.
Schema, exemplo e regras estão também em `docs/teams-query-proposal.md`.
O serviço reutiliza o cálculo individual em lote e agrega por equipe atual;
não consulta novamente por equipe ou membro. Campos desconhecidos propagam
`null` no agregado correspondente e `complete=false`, sem publicar somas parciais.
O helper `team_capacity` anterior mantém sua interface; a projeção da nova rota
inclui adicionalmente reservas, ocupação e utilização. Sem turno para a data,
capacidade de membros é desconhecida e os totais registrados de tarefas/reservas
são zero, pois não existem vínculos com esse turno. Equipes sem membros têm
capacidade/carga zero e utilização não aplicável.

Não há filtros contratados a validar por valor: testes verificam a rejeição de
parâmetros não suportados. Novos filtros por equipe, status, prioridade ou
responsável exigem definição no contrato. CORS não foi aberto genericamente:
se o frontend usar outra origem, será necessário configurar explicitamente as
origens autorizadas. PowerShell e o Swagger na mesma origem não dependem de CORS.
