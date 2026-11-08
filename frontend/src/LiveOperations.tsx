import { useEffect, useState } from "react";
import { api, errorMessage } from "./api";
import type { AuditRecord, CaseDetail, CaseList, CaseProposal, CoverageDashboard } from "./types";
import { presentStatus } from "./status-presentation";

function Status({ entity, value }: { entity: "case" | "attempt"; value: string }) {
  const state = presentStatus(entity, value);
  return <span className={"status-pill " + state.tone} title={state.description}>{state.label}</span>;
}
function Time({ value }: { value: string }) {
  return <time dateTime={value}>{new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value))}</time>;
}
function Info({ error }: { error: string }) {
  return error ? <p className="inline-error" role="alert">{error}</p> : null;
}
function Blank({ children }: { children: React.ReactNode }) {
  return <p className="live-empty">{children}</p>;
}
const amount = (hours: number | null) => hours === null ? "Indisponível" : new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(hours) + "h";

export function CoverageMetrics({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<CoverageDashboard | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    api.getDashboard(controller.signal).then(setData).catch(e => {
      if (!controller.signal.aborted) { setData(null); setError(errorMessage(e)); }
    });
    return () => controller.abort();
  }, [refreshKey]);
  return (
    <section className="panel live-panel" aria-label="Cobertura real do backend">
      <div className="panel-heading"><div><h2>Cobertura real dos casos</h2><p>Indicadores derivados do banco, não de respostas simuladas</p></div><span className="read-only-tag">API /dashboard</span></div>
      <Info error={error} />
      {!error && !data && <Blank>Carregando métricas operacionais…</Blank>}
      {data && <div className="live-metrics">
        <div><small>Tarefas afetadas</small><strong>{data.affected_tasks}</strong></div>
        <div><small>Horas planejadas</small><strong>{amount(data.planned_hours)}</strong></div>
        <div><small>Horas confirmadas</small><strong>{amount(data.confirmed_hours)}</strong></div>
        <div><small>Horas concluídas</small><strong>{amount(data.completed_hours)}</strong></div>
        <div><small>Sem cobertura confirmada</small><strong>{data.without_confirmed_coverage}</strong></div>
        <div><small>Casos abertos</small><strong>{data.cases_open}</strong></div>
        <div><small>Recusas / Expirações</small><strong>{data.refusals} / {data.expirations}</strong></div>
        <div><small>BP pendente</small><strong>{data.pending_bp}</strong></div>
      </div>}
      <p className="field-hint">Planejado ≠ confirmado ≠ concluído. O Slack registra uma resposta; somente a API confirma a mudança da tarefa.</p>
    </section>
  );
}

export function CasesExplorer({ focusCaseId, refreshKey }: { focusCaseId?: string | null; refreshKey: number }) {
  const [list, setList] = useState<CaseList | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState("");
  const [mutation, setMutation] = useState("");
  const [working, setWorking] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => { if (focusCaseId) setSelectedId(focusCaseId); }, [focusCaseId]);
  useEffect(() => {
    const controller = new AbortController();
    api.listCases(controller.signal).then(data => {
      setList(data);
      setSelectedId(current => current || focusCaseId || data.cases[0]?.case_id || "");
    }).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); });
    return () => controller.abort();
  }, [refreshKey, tick, focusCaseId]);
  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    const controller = new AbortController();
    setDetail(null); setError("");
    api.getCase(selectedId, controller.signal).then(setDetail)
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); });
    return () => controller.abort();
  }, [selectedId, refreshKey, tick]);
  async function plan() {
    if (!detail || detail.proposals.length !== 0 || !["open", "planning"].includes(detail.status)) return;
    setWorking(true); setMutation(""); setError("");
    try {
      await api.planCase(detail.case_id);
      setMutation("Planejamento solicitado ao backend. Verifique as propostas abaixo.");
      setTick(x => x + 1);
    } catch (e) { setError(errorMessage(e)); }
    finally { setWorking(false); }
  }
  return (
    <section className="panel live-panel">
      <div className="panel-heading"><div><h2>Casos e propostas da API</h2><p>Selecione um caso para acompanhar o planejamento, as respostas e os escalonamentos</p></div><button type="button" className="button button-secondary" onClick={() => setTick(x => x + 1)}>Recarregar casos</button></div>
      <Info error={error} />
      {mutation && <p className="success-result" role="status">{mutation}</p>}
      {!list && !error && <Blank>Consultando casos…</Blank>}
      {list && list.cases.length === 0 && <Blank>Nenhum caso registrado até agora.</Blank>}
      {list && list.cases.length > 0 && <>
        <label className="live-label">Selecionar caso
          <select value={selectedId} onChange={e => { setSelectedId(e.target.value); setMutation(""); }}>
            {list.cases.map(row => <option key={row.case_id} value={row.case_id}>{row.case_id.slice(0, 21)} · {row.status} · {row.task_count} tarefas</option>)}
          </select>
        </label>
        {detail ? <>
          <div className="live-case-heading"><strong><Status entity="case" value={detail.status} /> · versão {detail.plan_version}</strong>
            {detail.proposals.length === 0 && detail.tasks.length > 0 && ["open", "planning"].includes(detail.status) &&
              <button type="button" className="button button-primary" disabled={working} onClick={plan}>{working ? "Planejando…" : "Gerar plano neste caso"}</button>}
          </div>
          <p className="field-hint">ID: <code>{detail.case_id}</code> · Registrado em <Time value={detail.created_at} /></p>
          <h3>Tarefas afetadas ({detail.tasks.length})</h3>
          {detail.tasks.length === 0 ? <Blank>Sem tarefas afetadas registradas.</Blank> :
            <div className="table-scroll"><table className="live-table"><thead><tr><th>Tarefa</th><th>Responsável atual</th><th>Estado</th></tr></thead><tbody>
              {detail.tasks.map(task => <tr key={task.task_id}><td>{task.title}<small>{task.task_id}</small></td><td>{task.assignee_employee_id ?? "Não informado"}</td><td>{task.status}</td></tr>)}
            </tbody></table></div>}
          <h3>Propostas e decisões ({detail.proposals.length})</h3>
          {detail.proposals.length === 0 ? <Blank>O caso não tem propostas persistidas.</Blank> :
            <div className="table-scroll"><table className="live-table"><thead><tr><th>Tentativa</th><th>Candidato</th><th>Decisão</th><th>Motivo</th></tr></thead><tbody>
              {detail.proposals.map(p => <tr key={p.attempt_id}><td><code>{p.attempt_id.slice(0, 20)}…</code><small>{p.task_id}</small></td><td>{p.candidate_employee_id ?? "Sem candidato"}</td><td><Status entity="attempt" value={p.status}/></td><td>{p.reason ?? "—"}</td></tr>)}
            </tbody></table></div>}
          {detail.escalations.length > 0 && <div className="notice notice-neutral"><p><strong>{detail.escalations.length} escalonamento(s) requerem análise BP.</strong> {detail.escalations.map(x => x.alternatives.join(", ")).join("; ")}</p></div>}
        </> : selectedId && !error && <Blank>Carregando detalhes…</Blank>}
      </>}
    </section>
  );
}

interface ApprovalItem { caseId: string; proposal: CaseProposal }
export function ApprovalQueue({ refreshKey }: { refreshKey: number }) {
  const [pending, setPending] = useState<ApprovalItem[] | null>(null);
  const [error, setError] = useState("");
  const [actorId, setActorId] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState("");
  const [feedback, setFeedback] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    api.listCases(controller.signal).then(async rows => {
      const caseDetails = await Promise.all(rows.cases.filter(row => row.pending_approval_count > 0)
        .map(row => api.getCase(row.case_id, controller.signal)));
      if (!controller.signal.aborted) setPending(caseDetails.flatMap(detail =>
        detail.proposals.filter(proposal => proposal.status === "pending_approval")
          .map(proposal => ({ caseId: detail.case_id, proposal }))));
    }).catch(e => { if (!controller.signal.aborted) { setPending(null); setError(errorMessage(e)); } });
    return () => controller.abort();
  }, [refreshKey, tick]);
  async function decide(item: ApprovalItem, decision: "approve" | "reject") {
    if (!actorId.trim() || !reason.trim()) { setError("Informe o identificador do BP e a justificativa."); return; }
    setBusy(item.proposal.attempt_id); setError(""); setFeedback("");
    try {
      await api.decideApproval(item.proposal.attempt_id, decision, actorId.trim(), reason.trim());
      setFeedback("Decisão recebida pela API. Atualizando a fila…");
      setTick(x => x + 1);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(""); }
  }
  return (
    <section className="panel live-panel">
      <div className="panel-heading"><div><h2>Aprovações do BP</h2><p>Decisão real via API; aprovação não é aceite da proposta no Slack</p></div><button type="button" className="button button-secondary" onClick={() => setTick(x => x + 1)}>Atualizar fila</button></div>
      <div className="notice notice-neutral"><p>Ambiente de demonstração com dados fictícios. O backend ainda não possui autenticação corporativa: informe quem está atuando como BP. Não usar em produção.</p></div>
      <Info error={error} />
      {feedback && <p className="success-result" role="status">{feedback}</p>}
      <div className="live-form-row">
        <label>Identificador do BP<input value={actorId} onChange={e => setActorId(e.target.value)} placeholder="Ex.: bp-demo" /></label>
        <label>Justificativa<input value={reason} onChange={e => setReason(e.target.value)} placeholder="Motivo da aprovação ou rejeição" /></label>
      </div>
      {pending === null && !error && <Blank>Consultando aprovações…</Blank>}
      {pending?.length === 0 && <Blank>Nenhuma proposta aguardando decisão BP.</Blank>}
      {pending?.map(item => <article className="live-approval" key={item.proposal.attempt_id}>
        <div><strong>{item.proposal.task_id}</strong><small>Case: {item.caseId} · Tentativa: {item.proposal.attempt_id}</small>
          <p>{item.proposal.reason || "Aprovação de política necessária."}</p>
          <p>Candidato: {item.proposal.candidate_employee_id ?? "Não informado"}</p></div>
        <div className="live-actions">
          <button type="button" className="button button-primary" onClick={() => decide(item, "approve")} disabled={!!busy || !actorId.trim() || !reason.trim()}>Aprovar via API</button>
          <button type="button" className="button button-secondary" onClick={() => decide(item, "reject")} disabled={!!busy || !actorId.trim() || !reason.trim()}>Rejeitar via API</button>
        </div>
      </article>)}
    </section>
  );
}

export function AuditTrail({ refreshKey }: { refreshKey: number }) {
  const [caseId, setCaseId] = useState("");
  const [events, setEvents] = useState<AuditRecord[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setEvents(null); setError("");
    api.getAudit(caseId.trim() || undefined, controller.signal).then(data => {
      setTotal(data.total);
      setEvents([...data.events].reverse().slice(0, 100));
    }).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); });
    return () => controller.abort();
  }, [caseId, refreshKey, tick]);
  return (
    <section className="panel live-panel">
      <div className="panel-heading"><div><h2>Trilha auditável real</h2><p>Eventos persistidos com horário, ator, tentativa e motivo; somente leitura</p></div><button type="button" className="button button-secondary" onClick={() => setTick(x => x + 1)}>Atualizar auditoria</button></div>
      <label className="live-label">Filtrar por ID de caso<input value={caseId} onChange={e => setCaseId(e.target.value)} placeholder="Vazio = todos os casos" /></label>
      <Info error={error} />
      {events === null && !error && <Blank>Carregando histórico…</Blank>}
      {events && <><p className="field-hint">{total} eventos no servidor; exibindo os 100 mais recentes.</p>
        {events.length === 0 ? <Blank>Nenhum evento encontrado para este filtro.</Blank> :
          <div className="table-scroll"><table className="live-table"><thead><tr><th>Quando</th><th>Ação</th><th>Ator</th><th>Referência / motivo</th></tr></thead><tbody>
            {events.map(event => <tr key={event.audit_event_id}>
              <td><Time value={event.timestamp} /></td>
              <td><strong>{event.action}</strong></td>
              <td>{event.actor}</td>
              <td>{event.attempt_id || event.case_id || "—"}{event.reason && <small>{event.reason}</small>}</td>
            </tr>)}
          </tbody></table></div>}
      </>}
    </section>
  );
}
