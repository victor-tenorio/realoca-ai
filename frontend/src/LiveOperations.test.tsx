import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { ApprovalQueue, AuditTrail, CasesExplorer, CoverageMetrics } from "./LiveOperations";

vi.mock("./api", async importOriginal => {
  const original = await importOriginal<typeof import("./api")>();
  return { ...original, api: {
    ...original.api,
    listCases: vi.fn(),
    getCase: vi.fn(),
    planCase: vi.fn(),
    decideApproval: vi.fn(),
    getAudit: vi.fn(),
    getDashboard: vi.fn(),
  }};
});

const proposal = {
  attempt_id: "att-demo-1", task_id: "task-1", candidate_employee_id: "emp-2",
  status: "pending_approval" as const, reason: "Equipe distinta requer BP",
  plan_version: 1, approval_decision: null, approval_actor_id: null,
  response_deadline_at: null,
};
const caseSummary = {
  case_id: "case-1", status: "pending_approval" as const, plan_version: 1,
  created_at: "2026-11-08T11:00:00Z", task_count: 1,
  pending_approval_count: 1, escalation_count: 0, requires_bp_review: true,
};
const caseDetail = {
  case_id: "case-1", status: "pending_approval" as const, plan_version: 1,
  created_at: "2026-11-08T11:00:00Z", absences: [{ absence_id: "abs-1", employee_id: "emp-1" }],
  tasks: [{ task_id: "task-1", title: "Revisar pagamento", status: "open" as const,
    assignee_employee_id: "emp-1" }],
  proposals: [proposal], pending_approvals: [proposal.attempt_id], escalations: [],
};

beforeEach(() => {
  vi.mocked(api.listCases).mockResolvedValue({ cases: [caseSummary], total: 1 });
  vi.mocked(api.getCase).mockResolvedValue(caseDetail);
  vi.mocked(api.planCase).mockResolvedValue({});
  vi.mocked(api.decideApproval).mockResolvedValue({ status: "approved" });
  vi.mocked(api.getAudit).mockResolvedValue({ total: 1, events: [{
    audit_event_id: "audit-1", case_id: "case-1", attempt_id: "att-demo-1",
    action: "proposal.pending_approval", actor: "api:cases",
    timestamp: "2026-11-08T11:00:00Z", policy_version: 1,
    reason: "Regra BP", result: {},
  }] });
  vi.mocked(api.getDashboard).mockResolvedValue({
    confirmed_absences: 1, cases_total: 1, cases_open: 1,
    affected_tasks: 1, affected_hours: 2, planned_hours: 2,
    confirmed_hours: 0, completed_hours: 0, completed_tasks: 0,
    in_progress_tasks: 0, without_confirmed_coverage: 1,
    affected_teams: 1, refusals: 0, expirations: 0, escalations: 0, pending_bp: 1,
  });
});

it("shows backend coverage and keeps planned and confirmed hours separate", async () => {
  render(<CoverageMetrics refreshKey={0} />);
  expect(await screen.findByText("Cobertura real dos casos")).toBeTruthy();
  expect(await screen.findByText("2h")).toBeTruthy();
  expect(screen.getAllByText("0h").length).toBeGreaterThan(0);
  expect(screen.getByText(/Planejado ≠ confirmado ≠ concluído/)).toBeTruthy();
});

it("shows authoritative case proposals without claiming BP approval is acceptance", async () => {
  render(<CasesExplorer refreshKey={0} />);
  expect(await screen.findByText("Revisar pagamento")).toBeTruthy();
  expect(screen.getAllByText("Aprovação pendente").length).toBeGreaterThan(0);
  expect(screen.queryByRole("button", { name: "Gerar plano neste caso" })).toBeNull();
  expect(api.planCase).not.toHaveBeenCalled();
});

it("requires explicit BP identity and reason before API mutation", async () => {
  render(<ApprovalQueue refreshKey={0} />);
  const approve = await screen.findByRole("button", { name: "Aprovar via API" });
  expect((approve as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByPlaceholderText("Ex.: bp-demo"), { target: { value: "bp-oficial-demo" } });
  fireEvent.change(screen.getByPlaceholderText("Motivo da aprovação ou rejeição"), { target: { value: "Revisado em reunião" } });
  fireEvent.click(approve);
  await waitFor(() => expect(api.decideApproval).toHaveBeenCalledWith(
    "att-demo-1", "approve", "bp-oficial-demo", "Revisado em reunião",
  ));
});

it("renders read-only audit records, never fabricated counters", async () => {
  render(<AuditTrail refreshKey={0} />);
  expect(await screen.findByText("proposal.pending_approval")).toBeTruthy();
  expect(screen.getByText("api:cases")).toBeTruthy();
  expect(screen.getByText("Regra BP")).toBeTruthy();
  expect(api.getAudit).toHaveBeenCalledWith(undefined, expect.anything());
});
