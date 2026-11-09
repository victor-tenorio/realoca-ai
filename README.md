# Realoca AI

**Continuidade operacional inteligente para equipes que não podem parar.**

O Realoca AI ajuda gestores a reagir a ausências e outros imprevistos que deixam tarefas sem cobertura. A plataforma reúne informações sobre atividades, competências, disponibilidade e carga de trabalho para **recomendar quem pode assumir cada tarefa — e explicar por quê**.

**A decisão final de realocação pertence ao gestor.** A proposta é apoiar decisões melhores e mais rápidas, não substituir a liderança da equipe.

> **Estado do projeto:** protótipo desenvolvido para o Converge Challenge 2026, agora em evolução para a visão original do produto. As capacidades descritas como *visão* ou *planejadas* ainda não devem ser interpretadas como funcionalidades prontas.

## O problema

Quando alguém se ausenta, o trabalho não desaparece. Um gestor precisa identificar tarefas afetadas, avaliar prioridades, encontrar pessoas qualificadas, verificar se elas têm capacidade para assumir novas responsabilidades e reorganizar a operação. Fazer isso manualmente consome tempo e pode sobrecarregar a equipe.

## Nossa proposta

O Realoca AI transforma informações operacionais em **recomendações de realocação justificadas**. Em vez de escolher um substituto apenas por estar disponível, o gestor poderá comparar alternativas com base em critérios como:

- **Competências:** correspondência entre habilidades exigidas pela tarefa e habilidades da pessoa.
- **Capacidade:** horas já comprometidas, reservas e margem disponível no período.
- **Prioridade e prazo:** urgência e impacto das atividades descobertas.
- **Restrições:** regras da organização, equipe, turno e dados incompletos.

O sistema deve mostrar os fatores que sustentam cada recomendação, indicar limitações e permitir que o gestor aprove ou rejeite a proposta. **Não há pontuação de “match” definitiva ou modelo de ranking validado anunciado nesta versão**: sua definição e validação fazem parte da evolução do produto.

## Como queremos que funcione

1. **Detectar o imprevisto.** Uma ausência confirmada chega por integração ou é registrada na plataforma.
2. **Identificar o impacto.** O sistema encontra as tarefas afetadas e suas prioridades.
3. **Comparar alternativas.** O mecanismo analisa competências, capacidade, turno e restrições para sugerir possíveis responsáveis.
4. **Explicar a recomendação.** O gestor vê as opções, os critérios utilizados e eventuais riscos.
5. **Decidir.** O gestor escolhe e aprova a realocação. A equipe não fica sujeita a uma decisão autônoma e irreversível da IA.
6. **Executar e acompanhar.** Após a aprovação e as validações necessárias, a mudança é registrada, comunicada e auditada. Se não houver alternativa segura, o caso é escalado.

Esse fluxo representa **a direção do produto**, não uma declaração de que todas as etapas já estão disponíveis na versão atual.

## O que foi construído no hackathon

A equipe desenvolveu uma base técnica para demonstrar um cenário de continuidade operacional, incluindo:

- API em **Python/FastAPI**, persistência com **SQLAlchemy**, migrações com **Alembic** e banco **SQLite** na demonstração.
- Dados sintéticos de **40 funcionários**, **4 equipes** e **187 tarefas** para experimentar cenários.
- Consultas de funcionários, equipes e tarefas; registro de ausências confirmadas e associação das tarefas afetadas a um caso.
- Estruturas para planos, tentativas, reservas de capacidade, políticas, eventos de integração e trilha de auditoria.
- Um contrato de callback para eventos de propostas via integração com **n8n**.
- Fluxos de demonstração e testes automatizados desenvolvidos durante o desafio.

**Importante:** a documentação técnica foi produzida em etapas. Alguns registros e endpoints recebem eventos sem necessariamente concluir toda a realocação. Por exemplo, o recebimento de um callback com status `queued` confirma o armazenamento do evento, **não** a atribuição de uma tarefa. Integrações simuladas também não equivalem a comunicação real com funcionários.

A demonstração do hackathon utilizou um fluxo de **aceite ou recusa pelo funcionário**. Para a próxima versão, a equipe pretende priorizar **recomendações explicáveis e decisão do gestor**. Essa mudança ainda requer revisão dos contratos, estados e interfaces existentes.

## Visão de evolução: agentes de IA

A visão original é ampliar o sistema para uma arquitetura com agentes especializados que cooperam na análise de impacto, na busca de alternativas e no acompanhamento de exceções.

A IA deverá auxiliar na interpretação e coordenação do trabalho; **regras de capacidade, permissões, aprovação e integridade dos dados continuarão sendo verificadas de forma determinística**. O uso de agentes não significa delegar decisões sensíveis sem supervisão.

## Próximos passos

- [ ] Formalizar os requisitos da nova experiência centrada no gestor.
- [ ] Auditar os fluxos e contratos existentes para reaproveitar o que já funciona.
- [ ] Definir critérios transparentes de correspondência entre tarefas e funcionários.
- [ ] Criar uma interface de comparação e aprovação de recomendações.
- [ ] Adaptar os fluxos de aceite/recusa da demonstração ao novo modelo de decisão.
- [ ] Evoluir a orquestração e as integrações com sistemas reais.
- [ ] Validar recomendações e usabilidade com cenários e usuários representativos.

## Executar o backend localmente

**Requisitos:** Python 3.11+ e PowerShell no Windows. Os comandos abaixo iniciam o backend com dados fictícios; não configuram automaticamente todas as integrações externas.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DATABASE_URL = "sqlite:///./realoca.db"
$env:DEMO_REFERENCE_DATE = "2026-11-08"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.demo.seed
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Com o servidor ativo:

- **Documentação interativa da API:** http://127.0.0.1:8000/docs
- **Verificação de saúde:** http://127.0.0.1:8000/health

Para executar os testes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

O seed é sintético e não deve ser confundido com dados de produção. Consulte [`.env.example`](.env.example) para variáveis de ambiente; nunca publique credenciais.

## Documentação técnica

- [Decisões de modelagem e histórico técnico](docs/spec.md) — registro de decisões e etapas da demonstração, incluindo seções históricas que podem não representar o estado mais recente.
- [Exemplos de respostas da API](docs/query-response-examples.md).
- [Proposta de consulta de equipes](docs/teams-query-proposal.md).

Os documentos acima registram a evolução técnica do hackathon. Eles ainda serão reorganizados e revisados para refletir a nova visão de produto.

## Origem e equipe

O Realoca AI nasceu no **Converge Challenge 2026**. Depois do evento, a equipe decidiu continuar o desenvolvimento e aproximar a implementação da proposta original: apoiar a continuidade operacional com inteligência, explicabilidade e controle humano.

---

**Realoca AI — recomendações inteligentes; decisões nas mãos de quem conhece a operação.**
