import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api, errorMessage } from "./api";
import { useResource } from "./hooks/use-resource";
import type { Resource } from "./hooks/use-resource";
import { initialSlackDemoState, respondToSlackProposal, slackScenarios } from "./slack-demo";
import type { SlackScenarioId } from "./slack-demo";
import { presentStatus } from "./status-presentation";
import { ApprovalQueue, AuditTrail, CasesExplorer, CoverageMetrics } from "./LiveOperations";
import type { AbsenceCreated, Employee, Task, Team } from "./types";

type Page = "overview" | "cases" | "tasks" | "teams" | "slack" | "approvals" | "audit";

const navigation: { id: Page; label: string; icon: string }[] = [
  { id: "overview", label: "Visão Geral", icon: "◫" },
  { id: "cases", label: "Casos de Ausência", icon: "◷" },
  { id: "tasks", label: "Tarefas", icon: "▤" },
  { id: "teams", label: "Equipes e Capacidade", icon: "⌘" },
  { id: "slack", label: "Simulador Slack", icon: "✉" },
  { id: "approvals", label: "Aprovações", icon: "✓" },
  { id: "audit", label: "Auditoria", icon: "◷" },
];

const pageTitles: Record<Page, { title: string; subtitle: string }> = {
  overview: { title: "Visão geral", subtitle: "Acompanhe a continuidade da operação e a capacidade das equipes." },
  cases: { title: "Casos de ausência", subtitle: "Registre ausências confirmadas e acompanhe o retorno real da API." },
  tasks: { title: "Tarefas", subtitle: "Consulte tarefas do turno e filtre os dados publicados pelo backend." },
  teams: { title: "Equipes e capacidade", subtitle: "Capacidade e carga calculadas pelo backend para o turno de referência." },
  slack: { title: "Simulador Slack", subtitle: "Demonstração local e fictícia de respostas a propostas; não envia mensagens." },
  approvals: { title: "Aprovações", subtitle: "Fila real de propostas aguardando autorização do BP na API." },
  audit: { title: "Auditoria", subtitle: "Histórico operacional somente para leitura." },
};

const loadEmployees = (signal: AbortSignal) => api.listEmployees(signal);
const loadTasks = (signal: AbortSignal) => api.listTasks(signal);
const loadTeams = (signal: AbortSignal) => api.listTeams(signal);

export default function App() {
  const [page, setPage] = useState<Page>("overview");
  const [refreshKey, setRefreshKey] = useState(0);
  const employees = useResource(loadEmployees, refreshKey);
  const tasks = useResource(loadTasks, refreshKey);
  const teams = useResource(loadTeams, refreshKey);
  const current = pageTitles[page];
  const apiHasError = employees.status === "error" || tasks.status === "error" || teams.status === "error";
  const apiLoading = employees.status === "loading" || tasks.status === "loading" || teams.status === "loading";

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Navegação principal">
        <a className="brand" href="#inicio" onClick={(event) => { event.preventDefault(); setPage("overview"); }}>
          <span className="brand-mark" aria-hidden="true">R</span>
          <span><strong>realoca<span>ai</span></strong><small>OPERAÇÕES INTELIGENTES</small></span>
        </a>
        <div className="workspace-label">ESPAÇO DE TRABALHO</div>
        <nav className="nav-list">
          {navigation.map((item) => (
            <button
              className={"nav-item " + (page === item.id ? "active" : "")}
              key={item.id}
              type="button"
              aria-current={page === item.id ? "page" : undefined}
              onClick={() => setPage(item.id)}
            >
              <span className="nav-icon" aria-hidden="true">{item.icon}</span>
              {item.label}
              
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-pulse" />
          <span><strong>API configurável</strong><small>Dados do backend</small></span>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumb">Realoca AI <span>/</span> {current.title}</div>
          <div className="topbar-actions">
            <span className="data-source"><span className={apiHasError ? "status-pulse offline" : "status-pulse"} />{apiHasError ? "Falha na consulta" : apiLoading ? "Consultando API" : "Dados da API"}</span>
            <button className="button button-secondary refresh-button" type="button" onClick={() => setRefreshKey((key) => key + 1)}>
              <span aria-hidden="true">↻</span> Atualizar
            </button>
            <div className="avatar" aria-label="Perfil RH">RH</div>
          </div>
        </header>

        <div className="page-wrap">
          <div className="page-heading">
            <div>
              <p className="eyebrow">PAINEL OPERACIONAL</p>
              <h1>{current.title}</h1>
              <p className="page-subtitle">{current.subtitle}</p>
            </div>
            {page === "overview" && <span className="live-tag"><span className="status-pulse" /> Dados atualizados sob demanda</span>}
          </div>

          {page === "overview" && <><Overview employees={employees} tasks={tasks} teams={teams} onRetry={() => setRefreshKey((key) => key + 1)} /><CoverageMetrics refreshKey={refreshKey} /></>}
          {page === "cases" && <CasesPage employees={employees} refreshKey={refreshKey} />}
          {page === "tasks" && <TasksPage resource={tasks} onRetry={() => setRefreshKey((key) => key + 1)} />}
          {page === "teams" && <TeamsPage resource={teams} onRetry={() => setRefreshKey((key) => key + 1)} />}
          {page === "slack" && <SlackSimulator />}
          {page === "approvals" && <ApprovalQueue refreshKey={refreshKey} />}
          {page === "audit" && <AuditTrail refreshKey={refreshKey} />}
        </div>
      </main>
    </div>
  );
}

function Overview({ employees, tasks, teams, onRetry }: {
  employees: Resource<Employee[]>;
  tasks: Resource<Task[]>;
  teams: Resource<Team[]>;
  onRetry: () => void;
}) {
  const activeTasks = tasks.status === "success"
    ? tasks.data.filter((task) => task.status === "open" || task.status === "in_progress")
    : [];
  const openHours = activeTasks.reduce((total, task) => total + task.estimated_hours, 0);
  const criticalTasks = activeTasks.filter((task) => task.priority === "critical").slice(0, 4);
  const priorities = (["critical", "high", "medium", "low"] as const).map((priority) => ({
    priority,
    count: activeTasks.filter((task) => task.priority === priority).length,
  }));
  const maxPriorityCount = Math.max(1, ...priorities.map((item) => item.count));

  return (
    <section className="stack">
      {(employees.status === "error" || tasks.status === "error" || teams.status === "error") && (
        <ErrorBanner message="Alguns dados não puderam ser carregados." onRetry={onRetry} />
      )}
      <div className="metrics-grid">
        <MetricCard label="Tarefas ativas" value={resourceCount(tasks, (items) => items.filter((task) => task.status === "open" || task.status === "in_progress").length)} detail="Open e in_progress; concluídas excluídas" icon="▤" tone="green" />
        <MetricCard label="Horas de demanda ativa" value={tasks.status === "success" ? formatHours(openHours) : "—"} detail="Soma das estimativas de tarefas ativas" icon="◷" tone="blue" />
        <MetricCard label="Funcionários publicados" value={resourceCount(employees, (items) => items.length)} detail="Pessoas disponíveis na consulta" icon="♙" tone="violet" />
        <MetricCard label="Equipes com capacidade completa" value={teams.status === "success" ? teams.data.filter((team) => team.complete).length + " / " + teams.data.length : "—"} detail="Agregados completos no turno atual" icon="⌘" tone="amber" />
      </div>

      <div className="dashboard-grid">
        <section className="panel priority-panel">
          <div className="panel-heading">
            <div><h2>Tarefas por prioridade</h2><p>Demanda ativa retornada pela API</p></div>
            <span className="panel-kicker">TURNO ATUAL</span>
          </div>
          {tasks.status === "loading" ? <LoadingState label="Carregando tarefas" /> :
            tasks.status === "error" ? <InlineError error={tasks.error} /> :
              tasks.data.length === 0 ? <EmptyState title="Nenhuma tarefa publicada" description="Quando o backend retornar tarefas do turno, os indicadores aparecerão aqui." /> :
                <div className="priority-bars">
                  {priorities.map(({ priority, count }) => (
                    <div className="priority-row" key={priority}>
                      <span className={"priority-dot " + priority} />
                      <span className="priority-name">{priorityLabel(priority)}</span>
                      <div className="bar-track" aria-label={priorityLabel(priority) + ": " + count + " tarefas"}>
                        <span className={"bar-fill " + priority} style={{ width: (count / maxPriorityCount) * 100 + "%" }} />
                      </div>
                      <strong>{count}</strong>
                    </div>
                  ))}
                </div>}
        </section>

        <section className="panel critical-panel">
          <div className="panel-heading">
            <div><h2>Prioridade crítica</h2><p>Tarefas críticas ainda não concluídas</p></div>
            <span className="critical-count">{tasks.status === "success" ? criticalTasks.length : "—"}</span>
          </div>
          {tasks.status === "loading" ? <LoadingState label="Carregando tarefas críticas" /> :
            tasks.status === "error" ? <InlineError error={tasks.error} /> :
              criticalTasks.length === 0 ? <EmptyState title="Sem tarefas críticas ativas" description="Não há tarefas críticas pendentes nos dados consultados." /> :
                <div className="critical-list">
                  {criticalTasks.map((task) => <TaskSummary task={task} key={task.task_id} />)}
                </div>}
        </section>
      </div>

      <StatusGuide />

    </section>
  );
}

function SlackSimulator() {
  const [scenarioId, setScenarioId] = useState<SlackScenarioId>("accept");
  const scenario = slackScenarios.find((item) => item.id === scenarioId)!;
  const [state, setState] = useState(() => initialSlackDemoState(scenario));
  const currentAttempt = state.attempts[state.attempts.length - 1];
  const currentCandidate = currentAttempt
    ? scenario.candidates.find((candidate) => candidate.employeeId === currentAttempt.employeeId)
    : undefined;
  const canRespond = state.outcome === "awaiting-response" && currentAttempt?.status === "notified";

  function changeScenario(value: SlackScenarioId) {
    const nextScenario = slackScenarios.find((item) => item.id === value)!;
    setScenarioId(value);
    setState(initialSlackDemoState(nextScenario));
  }

  return (
    <section className="stack slack-simulator" aria-label="Simulador Slack local">
      <div className="notice notice-demo" role="note">
        <span className="notice-icon" aria-hidden="true">!</span>
        <p><strong>SIMULAÇÃO LOCAL · DADOS FICTÍCIOS.</strong> Nenhuma mensagem sai pelo Slack/n8n e nenhuma resposta é enviada à API. Aceites, recusas e propostas deste painel existem somente no estado desta página; não criam reserva, atribuição nem cobertura confirmada.</p>
      </div>

      <div className="panel simulator-toolbar">
        <label htmlFor="slack-scenario">Cenário
          <select id="slack-scenario" value={scenarioId} onChange={(event) => changeScenario(event.target.value as SlackScenarioId)}>
            {slackScenarios.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
        <button className="button button-secondary" type="button" onClick={() => setState(initialSlackDemoState(scenario))}>Reiniciar cenário</button>
      </div>

      <div className="slack-layout">
        <section className="panel slack-conversation" aria-labelledby="conversation-heading">
          <div className="slack-window-heading">
            <div className="slack-logo" aria-hidden="true">#</div>
            <div><h2 id="conversation-heading">Canal fictício · cobertura-operacional</h2><p>Conversa simulada, sem conexão com workspace real</p></div>
            <span className="simulation-tag">SIMULADO</span>
          </div>

          <article className="slack-offer" aria-label="Proposta simulada">
            <div className="offer-topline"><span>Proposta de cobertura · {scenario.task.taskId}</span><StatusPill value={currentAttempt?.status ?? "proposed"} entity="attempt" /></div>
            <h3>{scenario.task.title}</h3>
            <div className="offer-facts">
              <span><small>Destinatário</small><strong>{currentCandidate?.name ?? "Nenhum candidato"}</strong></span>
              <span><small>Prioridade</small><strong>{priorityLabel(scenario.task.priority)}</strong></span>
              <span><small>Estimativa</small><strong>{formatHours(scenario.task.estimatedHours)}</strong></span>
              <span><small>Equipe da tarefa</small><strong>{scenario.task.team}</strong></span>
            </div>
            <p className="offer-reason"><strong>Justificativa:</strong> {scenario.task.reason}</p>
            <p className="offer-skills"><strong>Competências:</strong> {scenario.task.requiredSkills.join(", ")}</p>
            {currentCandidate && <p className="offer-skills"><strong>Capacidade fictícia:</strong> {formatHours(currentCandidate.availableHours)} · {currentCandidate.team}</p>}
          </article>

          <div className="chat-history" aria-label="Histórico das interações">
            {state.events.map((event, index) => (
              <div className={`chat-event ${event.actor}`} key={`${index}-${event.actor}`}>
                <span className="chat-avatar" aria-hidden="true">{event.actor === "employee" ? "RH" : event.actor === "system" ? "AI" : "#"}</span>
                <p><strong>{event.actor === "employee" ? event.employeeName ?? "Funcionário" : event.actor === "system" ? "Realoca AI · simulação" : "Slack · mensagem fictícia"}</strong><span>{event.text}</span></p>
              </div>
            ))}
          </div>

          {canRespond && <div className="response-actions" aria-label="Resposta fictícia do funcionário">
            <button className="button button-primary" type="button" onClick={() => setState((current) => respondToSlackProposal(scenario, current, "accept"))}>Aceitar · simulação</button>
            <button className="button button-danger" type="button" onClick={() => setState((current) => respondToSlackProposal(scenario, current, "refuse"))}>Recusar · simulação</button>
          </div>}
        </section>

        <aside className="panel attempt-history" aria-labelledby="attempt-history-heading">
          <div className="panel-heading"><div><h2 id="attempt-history-heading">Histórico de propostas</h2><p>Estados locais do cenário, não persistidos.</p></div></div>
          {state.attempts.length === 0 ? <EmptyState title="Nenhuma proposta simulada" description="Este cenário não possui candidatos fictícios predefinidos." /> :
            <ol className="attempt-list">{state.attempts.map((attempt, index) => {
              const candidate = scenario.candidates.find((item) => item.employeeId === attempt.employeeId);
              return <li key={`${attempt.employeeId}-${index}`}>
                <span className="attempt-number">{index + 1}</span>
                <div><strong>{candidate?.name ?? attempt.employeeId}</strong><small>{attempt.employeeId}</small><StatusPill value={attempt.status} entity="attempt" /></div>
              </li>;
            })}</ol>}
          {state.outcome === "accepted" && <div className="simulator-outcome positive" role="status"><strong>Aceite fictício registrado</strong><span>A resposta não foi persistida. A cobertura do caso continua desconhecida.</span></div>}
          {state.outcome === "replanning-required" && <div className="simulator-outcome pending" role="status"><strong>Replanejamento necessário</strong><span>A recusa não escolheu outro candidato; este cenário não chamou o motor nem consultou a API.</span></div>}
          {state.attempts.length > 1 && <div className="simulator-outcome pending" role="status"><strong>Nova proposta fictícia</strong><span>O candidato recusante não foi reutilizado para esta tarefa. A nova proposta aguarda resposta.</span></div>}
          {state.outcome === "uncovered" && <div className="simulator-outcome attention" role="status"><strong>Tarefa sem cobertura no cenário</strong><span>Não há outro candidato fictício elegível predefinido. É necessário escalonamento; nenhuma cobertura foi inventada.</span></div>}
        </aside>
      </div>
    </section>
  );
}

function StatusGuide() {
  const groups = [
    { title: "Tarefa", entity: "task" as const, values: ["open", "in_progress", "done"] },
    { title: "Caso", entity: "case" as const, values: ["open", "planning", "pending_approval", "awaiting_responses", "coverage_confirmed", "closed_with_gaps", "completed"] },
    { title: "Proposta", entity: "attempt" as const, values: ["proposed", "pending_approval", "reserved", "notified", "accepted", "refused", "expired", "rejected_by_bp", "escalated"] },
  ];

  return <section className="panel status-guide" aria-labelledby="status-guide-heading">
    <div className="panel-heading"><div><h2 id="status-guide-heading">Estados não são equivalentes</h2><p>Glossário do contrato; não representa uma consulta de casos ou propostas.</p></div></div>
    <div className="status-guide-groups">{groups.map((group) => <div className="status-guide-group" key={group.title}>
      <h3>{group.title}</h3>
      {group.values.map((value) => {
        const status = presentStatus(group.entity, value);
        return <div className="status-definition" key={value}><StatusPill value={value} entity={group.entity} /><span>{status.description}</span></div>;
      })}
    </div>)}</div>
  </section>;
}

function MetricCard({ label, value, detail, icon, tone }: {
  label: string; value: string; detail: string; icon: string; tone: string;
}) {
  return (
    <article className="metric-card">
      <div className={"metric-icon " + tone} aria-hidden="true">{icon}</div>
      <p className="metric-label">{label}</p>
      <strong className="metric-value">{value}</strong>
      <span className="metric-detail">{detail}</span>
    </article>
  );
}

function CasesPage({ employees, refreshKey }: { employees: Resource<Employee[]>; refreshKey: number }) {
  const [result, setResult] = useState<AbsenceCreated | null>(null);
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    setFormError("");
    setResult(null);
    const form = new FormData(formElement);
    const employeeId = String(form.get("employee_id") || "");
    const startsAt = localDateTimeToUtc(String(form.get("starts_at") || ""));
    const endsAt = localDateTimeToUtc(String(form.get("ends_at") || ""));
    const externalId = String(form.get("external_id") || "").trim();
    if (!employeeId || !startsAt || !endsAt || !externalId || !form.get("confirmed")) {
      setFormError("Preencha os campos e confirme que a ausência está registrada.");
      return;
    }
    if (new Date(endsAt) <= new Date(startsAt)) {
      setFormError("O fim da ausência precisa ser posterior ao início.");
      return;
    }
    setSubmitting(true);
    try {
      const created = await api.createAbsence({
        employee_id: employeeId,
        starts_at: startsAt,
        ends_at: endsAt,
        confirmed: true,
        source_system: "hr_simulator",
        external_id: externalId,
      });
      setResult(created);
      formElement.reset();
    } catch (error) {
      setFormError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="cases-layout">
      <section className="panel">
        <div className="panel-heading">
          <div><h2>Registrar ausência confirmada</h2><p>O backend cria o caso e vincula as tarefas abertas do turno.</p></div>
          <span className="panel-icon" aria-hidden="true">＋</span>
        </div>
        <form className="absence-form" onSubmit={submit}>
          <label>Funcionário
            <select name="employee_id" required defaultValue="" disabled={employees.status !== "success"}>
              <option value="" disabled>{employees.status === "loading" ? "Carregando funcionários…" : "Selecione"}</option>
              {employees.status === "success" && employees.data.map((employee) => (
                <option key={employee.employee_id} value={employee.employee_id}>{employee.name} · {employee.team_id}</option>
              ))}
            </select>
          </label>
          <div className="form-row">
            <label>Início<input name="starts_at" type="datetime-local" required /></label>
            <label>Fim<input name="ends_at" type="datetime-local" required /></label>
          </div>
          <label>Identificador de origem
            <input name="external_id" required maxLength={160} placeholder="Ex.: absence-rh-2026-001" />
          </label>
          <p className="field-hint">Origem enviada conforme o exemplo do contrato: hr_simulator. Não inclua diagnóstico ou informação médica.</p>
          <label className="checkbox-label">
            <input name="confirmed" type="checkbox" required />
            Confirmo que esta ausência foi registrada e está confirmada.
          </label>
          {formError && <div className="form-error" role="alert">{formError}</div>}
          {employees.status === "error" && <InlineError error={employees.error} />}
          <button className="button button-primary" type="submit" disabled={submitting || employees.status !== "success" || employees.data.length === 0}>
            {submitting ? "Enviando…" : "Registrar ausência"}
          </button>
        </form>
        {result && (
          <div className="success-result" role="status">
            <strong>Resposta confirmada pela API</strong>
            <span>Ausência: <code>{result.absence_id}</code></span>
            <span>Caso: <code>{result.case_id}</code> · Status: <StatusPill value={result.status} entity="case" /></span>
            <small>O caso foi criado; isso não significa que as tarefas já tenham cobertura confirmada.</small>
          </div>
        )}
      </section>
      <CasesExplorer focusCaseId={result?.case_id} refreshKey={refreshKey} />
    </div>
  );
}

function TasksPage({ resource, onRetry }: { resource: Resource<Task[]>; onRetry: () => void }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [priority, setPriority] = useState("all");
  const filtered = useMemo(() => {
    if (resource.status !== "success") return [];
    const query = search.trim().toLocaleLowerCase("pt-BR");
    return resource.data.filter((task) => {
      const haystack = (task.task_id + " " + task.title + " " + task.assignee_employee_id + " " + task.team_id).toLocaleLowerCase("pt-BR");
      const matchesText = !query || haystack.includes(query);
      return matchesText && (status === "all" || task.status === status) && (priority === "all" || task.priority === priority);
    });
  }, [resource, search, status, priority]);

  return (
    <section className="panel table-panel">
      <div className="panel-heading table-heading">
        <div><h2>Tarefas do turno</h2><p>Consulta oficial; filtros aplicados localmente.</p></div>
        <span className="result-count">{resource.status === "success" ? filtered.length + " resultados" : "—"}</span>
      </div>
      <div className="filters">
        <label className="search-field"><span aria-hidden="true">⌕</span><input aria-label="Buscar tarefa" placeholder="Buscar por título, ID ou equipe" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        <label className="filter-control"><span className="sr-only">Filtrar status</span><select aria-label="Filtrar status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">Todos os status</option><option value="open">Aberta</option><option value="in_progress">Em andamento</option><option value="done">Concluída</option></select></label>
        <label className="filter-control"><span className="sr-only">Filtrar prioridade</span><select aria-label="Filtrar prioridade" value={priority} onChange={(event) => setPriority(event.target.value)}><option value="all">Todas as prioridades</option><option value="critical">Crítica</option><option value="high">Alta</option><option value="medium">Média</option><option value="low">Baixa</option></select></label>
      </div>
      {resource.status === "loading" ? <LoadingState label="Carregando tarefas" /> :
        resource.status === "error" ? <InlineError error={resource.error} onRetry={onRetry} /> :
          filtered.length === 0 ? <EmptyState title={resource.data.length === 0 ? "Nenhuma tarefa publicada" : "Nenhum resultado"} description={resource.data.length === 0 ? "A API não retornou tarefas para o turno atual." : "Altere os filtros ou a busca para ver outras tarefas."} /> :
            <div className="table-scroll">
              <table>
                <thead><tr><th>Tarefa</th><th>Prioridade</th><th>Status</th><th>Responsável</th><th>Equipe</th><th>Horas</th><th>Prazo</th><th>Competências</th></tr></thead>
                <tbody>{filtered.map((task) => <tr key={task.task_id}>
                  <td><strong>{task.title}</strong><small>{task.task_id}</small></td>
                  <td><PriorityPill value={task.priority} /></td>
                  <td><StatusPill value={task.status} entity="task" /></td>
                  <td>{task.assignee_employee_id}</td><td>{task.team_id}</td>
                  <td>{formatHours(task.estimated_hours)}</td><td>{formatDate(task.due_at)}</td>
                  <td><div className="skill-list">{task.required_skills.map((skill) => <span key={skill}>{skill}</span>)}</div></td>
                </tr>)}</tbody>
              </table>
            </div>}
    </section>
  );
}

function TeamsPage({ resource, onRetry }: { resource: Resource<Team[]>; onRetry: () => void }) {
  return (
    <section className="panel table-panel">
      <div className="panel-heading table-heading">
        <div><h2>Capacidade por equipe</h2><p>Percentuais e totais agregados retornados pelo serviço de capacidade do backend.</p></div>
        {resource.status === "success" && <span className="result-count">{resource.data.length} equipes</span>}
      </div>
      {resource.status === "loading" ? <LoadingState label="Carregando equipes" /> :
        resource.status === "error" ? <InlineError error={resource.error} onRetry={onRetry} /> :
          resource.data.length === 0 ? <EmptyState title="Nenhuma equipe publicada" description="A API não retornou equipes para o turno configurado." /> :
            <div className="table-scroll">
              <table>
                <thead><tr><th>Equipe</th><th>Funcionários</th><th>Capacidade</th><th>Comprometido</th><th>Reservado</th><th>Ocupado</th><th>Utilização</th><th>Dados</th></tr></thead>
                <tbody>{resource.data.map((team) => <tr key={team.team_id}>
                  <td><strong>{team.name}</strong><small>{team.team_id} · {formatDateOnly(team.reference_date)}</small></td>
                  <td>{team.employee_count}</td><td>{optionalHours(team.shift_hours)}</td>
                  <td>{optionalHours(team.committed_hours)}</td><td>{formatHours(team.reserved_hours)}</td>
                  <td>{optionalHours(team.occupied_hours)}</td>
                  <td>{team.utilization_pct === null ? <span className="unknown-value">Não disponível</span> : <Utilization value={team.utilization_pct} />}</td>
                  <td><span className={"quality-pill " + (team.complete ? "complete" : "incomplete")}>{team.complete ? "Completo" : "Incompleto"}</span></td>
                </tr>)}</tbody>
              </table>
            </div>}
      <div className="notice notice-neutral table-note"><span className="notice-icon" aria-hidden="true">i</span><p>Valores nulos permanecem indisponíveis; não são convertidos em zero. Utilização pode superar 100% para carga já registrada.</p></div>
    </section>
  );
}

function TaskSummary({ task }: { task: Task }) {
  return (
    <article className="task-summary">
      <span className="critical-mark" aria-hidden="true">!</span>
      <div className="task-summary-main"><strong>{task.title}</strong><span>{task.task_id} · {task.team_id}</span></div>
      <span className="summary-hours">{formatHours(task.estimated_hours)}</span>
    </article>
  );
}

function Utilization({ value }: { value: number }) {
  const width = Math.max(0, Math.min(value, 100));
  const tone = value >= 90 ? "danger" : value >= 75 ? "warning" : "healthy";
  return <div className={"utilization " + tone}><span className="util-track"><span style={{ width: width + "%" }} /></span><strong>{formatPercent(value)}</strong></div>;
}

function PriorityPill({ value }: { value: string }) {
  return <span className={"priority-pill " + priorityClass(value)}>{priorityLabel(value)}</span>;
}

function StatusPill({ value, entity }: { value: string; entity: "task" | "case" | "attempt" }) {
  const status = presentStatus(entity, value);
  return <span className={"status-pill " + status.tone} title={status.description} data-entity={entity} data-status={value}>{status.label}</span>;
}

function LoadingState({ label }: { label: string }) {
  return <div className="loading-state" role="status"><span className="spinner" />{label}…</div>;
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="error-banner" role="alert"><span>{message}</span><button className="text-button" type="button" onClick={onRetry}>Tentar novamente</button></div>;
}

function InlineError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return <div className="inline-error" role="alert"><strong>Não foi possível carregar os dados.</strong><span>{errorMessage(error)}</span>{onRetry && <button className="text-button" type="button" onClick={onRetry}>Tentar novamente</button>}</div>;
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return <div className="empty-state"><span aria-hidden="true">⌕</span><strong>{title}</strong><p>{description}</p></div>;
}

function resourceCount<T>(resource: Resource<T[]>, count: (items: T[]) => number): string {
  if (resource.status === "loading") return "…";
  if (resource.status === "error") return "—";
  return String(count(resource.data));
}

function formatHours(value: number): string {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(value) + "h";
}

function optionalHours(value: number | null): string {
  return value === null ? "Não disponível" : formatHours(value);
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 }).format(value) + "%";
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Não disponível" : new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function formatDateOnly(value: string): string {
  const date = new Date(value + "T12:00:00");
  return Number.isNaN(date.getTime()) ? "Não disponível" : new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium" }).format(date);
}

function localDateTimeToUtc(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function priorityLabel(value: string): string {
  return ({ critical: "Crítica", high: "Alta", medium: "Média", low: "Baixa" } as Record<string, string>)[value] || "Desconhecida";
}

function priorityClass(value: string): string {
  return ["critical", "high", "medium", "low"].includes(value) ? value : "unknown";
}
