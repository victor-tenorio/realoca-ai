# Realoca AI

Inteligência para decisões operacionais. Continuidade para equipes.

O *Realoca AI* é uma plataforma inteligente de apoio à gestão de equipes, desenvolvida para ajudar empresas a lidar com imprevistos operacionais e tomar decisões mais eficientes sobre a distribuição de tarefas.

A proposta é simples: quando um funcionário se ausenta ou uma atividade precisa ser redistribuída, o sistema analisa os profissionais disponíveis, suas competências, cargas de trabalho e condições operacionais para recomendar as melhores alternativas.

Em vez de apenas indicar um substituto, o Realoca AI busca explicar **quem é mais adequado, por quais motivos e quais impactos a decisão pode causar na equipe**.

A decisão final permanece nas mãos do gestor.

> **Status:** projeto em desenvolvimento. O protótipo inicial foi construído durante o Converge Challenge 2026. A equipe está evoluindo a solução para uma plataforma de apoio à decisão com inteligência artificial e supervisão humana.

---

## O problema

A ausência inesperada de um funcionário pode comprometer prazos, sobrecarregar colegas e interromper atividades importantes.

Em muitas organizações, reorganizar essas responsabilidades ainda depende de decisões manuais, consultas a planilhas e conversas entre gestores.

Esse processo apresenta dificuldades recorrentes:

- Identificar rapidamente quais tarefas serão afetadas.
- Encontrar profissionais com as competências necessárias.
- Verificar quem realmente possui capacidade para assumir novas responsabilidades.
- Evitar sobrecarga e distribuição desigual de trabalho.
- Justificar decisões de realocação.
- Acompanhar os impactos das mudanças realizadas.

O Realoca AI surge para tornar essas decisões mais rápidas, fundamentadas e transparentes.

## Nossa solução

O Realoca AI pretende reunir dados operacionais e inteligência artificial em uma plataforma que auxilia gestores a reorganizar suas equipes diante de imprevistos.

O sistema deverá identificar tarefas afetadas, analisar possíveis substitutos e apresentar recomendações acompanhadas de justificativas claras.

### Como funcionará

**1. Identificação do imprevisto**

Uma ausência ou indisponibilidade é registrada no sistema, manualmente ou por integração com ferramentas da empresa.

**2. Análise do impacto**

O Realoca AI identifica as atividades comprometidas, seus prazos, prioridades e requisitos.

**3. Análise de compatibilidade**

O sistema compara possíveis responsáveis considerando competências, disponibilidade, carga de trabalho e restrições operacionais.

**4. Recomendações explicáveis**

O gestor recebe alternativas de realocação, acompanhadas dos critérios que justificam cada recomendação.

**5. Decisão do gestor**

O responsável pela equipe avalia as alternativas e escolhe como proceder. A IA oferece suporte à decisão, sem substituir a autoridade do gestor.

**6. Execução e acompanhamento**

Após a aprovação, o sistema deverá registrar a mudança, atualizar as informações operacionais e acompanhar seus efeitos.

---

## Nosso diferencial

### Não queremos apenas automatizar tarefas. Queremos melhorar decisões.

O diferencial do Realoca AI está na combinação de inteligência artificial, análise operacional e supervisão humana.

**Compatibilidade inteligente**

As recomendações deverão considerar não apenas quem está disponível, mas quem possui as competências e condições mais adequadas para assumir determinada atividade.

**Explicabilidade**

Cada recomendação deverá apresentar seus principais critérios, permitindo que o gestor compreenda por que determinado profissional foi sugerido.

**Prevenção de sobrecarga**

O sistema deverá considerar a distribuição atual de trabalho antes de sugerir novas responsabilidades.

**Decisão humana**

O gestor mantém o controle sobre a realocação, podendo avaliar alternativas, rejeitar recomendações ou escolher outra solução.

**Arquitetura multiagente**

A visão de longo prazo inclui agentes de IA especializados, capazes de colaborar na identificação de impactos, análise de alternativas e acompanhamento operacional.

**Integração com ferramentas existentes**

O objetivo é permitir que o Realoca AI trabalhe com informações provenientes dos sistemas já utilizados pelas empresas, reduzindo a necessidade de processos paralelos.

---

## O que já foi desenvolvido

Durante o Converge Challenge 2026, foi construída uma base funcional para demonstrar cenários de redistribuição de tarefas.

Entre os componentes desenvolvidos estão:

- Backend em Python com FastAPI.
- Persistência de dados com SQLAlchemy e Alembic.
- Modelagem de funcionários, equipes, tarefas, ausências e casos operacionais.
- Consultas de capacidade e carga de trabalho.
- Estruturas de planejamento e registro de tentativas de realocação.
- Integrações experimentais com n8n.
- Registros de auditoria e eventos.
- Interface de demonstração e testes automatizados.

O ambiente demonstrativo utiliza dados fictícios de 40 funcionários, distribuídos entre quatro equipes, com 187 tarefas cadastradas.

Essa implementação constitui a base técnica do projeto, mas ainda não representa integralmente a visão de produto.

## Próxima etapa de desenvolvimento

Com a conclusão do hackathon, o Realoca AI entra em uma nova fase.

As prioridades são:

- [ ] Definir os critérios de compatibilidade entre profissionais e tarefas.
- [ ] Desenvolver recomendações justificadas e comparáveis.
- [ ] Criar uma experiência de aprovação centrada no gestor.
- [ ] Evoluir a arquitetura de agentes inteligentes.
- [ ] Aprimorar a interface de gestão e acompanhamento.
- [ ] Integrar fontes reais de dados operacionais.
- [ ] Validar a solução em cenários próximos da realidade empresarial.
- [ ] Desenvolver mecanismos de avaliação da qualidade das recomendações.

---

## Tecnologias

A base técnica do projeto utiliza:

| Tecnologia | Aplicação |
|---|---|
| Python | Desenvolvimento do backend |
| FastAPI | APIs e serviços |
| SQLAlchemy | Persistência de dados |
| Alembic | Migrações do banco |
| SQLite | Banco de dados da demonstração |
| n8n | Integrações e automações experimentais |
| Pytest | Testes automatizados |

A arquitetura e as tecnologias poderão evoluir conforme os requisitos da nova versão.

## Executando o backend

Para executar o backend localmente, utilize Python 3.11 ou superior.

No Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:DATABASE_URL = "sqlite:///./realoca.db"
$env:DEMO_REFERENCE_DATE = "2026-11-08"

.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.demo.seed
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Com o servidor iniciado, a documentação interativa da API estará disponível em:

`http://127.0.0.1:8000/docs`

Para executar os testes:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Algumas integrações exigem configurações adicionais. Consulte os arquivos de configuração e a documentação técnica do repositório.

---

## Origem do projeto

O Realoca AI foi criado durante o **Converge Challenge 2026**, como uma proposta de aplicação de inteligência artificial à continuidade operacional de empresas.

A experiência permitiu desenvolver um protótipo inicial e explorar desafios relacionados à redistribuição de tarefas, disponibilidade de profissionais e automação de processos.

Após o evento, a equipe decidiu continuar o projeto, aprimorando sua proposta e evoluindo a tecnologia para atender à visão original.

---

**Realoca AI — A inteligência recomenda. O gestor decide. A operação continua.**
