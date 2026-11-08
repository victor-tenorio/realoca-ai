import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { ApiError, api } from "./api";
import type { Employee, Task, Team } from "./types";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    api: {
      listEmployees: vi.fn(),
      listTasks: vi.fn(),
      listTeams: vi.fn(),
      createAbsence: vi.fn(),
      listCases: vi.fn(),
      getCase: vi.fn(),
      planCase: vi.fn(),
      getDashboard: vi.fn(),
      getAudit: vi.fn(),
      decideApproval: vi.fn(),
    },
  };
});

const employee: Employee = {
  employee_id: "emp-ana", name: "Ana Lima", team_id: "ops", skills: ["python"],
  shift_hours: 8, committed_hours: 3, reserved_hours: 1, availability: "available",
  preferred_channel: "slack", channel_user_id: "demo-ana", source_system: "hr_simulator",
  external_id: "ana-01", updated_at: "2026-11-08T08:00:00Z",
};
const task = (changes: Partial<Task> = {}): Task => ({
  task_id: "task-001", title: "Revisar automação", assignee_employee_id: "emp-ana",
  team_id: "ops", priority: "critical", due_at: "2026-11-08T10:00:00-03:00",
  estimated_hours: 2, required_skills: ["python"], status: "open",
  transfer_allowed: true, source_system: "task_simulator", external_id: "job-1",
  updated_at: "2026-11-08T08:00:00Z", ...changes,
});
const team: Team = {
  team_id: "ops", name: "Operações", reference_date: "2026-11-08",
  employee_count: 1, shift_hours: null, committed_hours: null,
  reserved_hours: 0, occupied_hours: null, utilization_pct: null, complete: false,
};

function mockApi(data: { employees?: Employee[]; tasks?: Task[]; teams?: Team[] } = {}) {
  vi.mocked(api.listEmployees).mockResolvedValue(data.employees ?? [employee]);
  vi.mocked(api.listTasks).mockResolvedValue(data.tasks ?? [task()]);
  vi.mocked(api.listTeams).mockResolvedValue(data.teams ?? [team]);
  vi.mocked(api.createAbsence).mockResolvedValue({
    absence_id: "abs-001", case_id: "case-001", status: "open",
  });
  vi.mocked(api.listCases).mockResolvedValue({ cases: [], total: 0 });
  vi.mocked(api.getCase).mockResolvedValue({
    case_id: "case-001", status: "open", plan_version: 0, created_at: "2026-11-08T10:00:00Z",
    absences: [], tasks: [], proposals: [], pending_approvals: [], escalations: [],
  });
  vi.mocked(api.planCase).mockResolvedValue({});
  vi.mocked(api.getDashboard).mockResolvedValue({
    confirmed_absences: 0, cases_total: 0, cases_open: 0, affected_tasks: 0,
    affected_hours: 0, planned_hours: 0, confirmed_hours: 0, completed_hours: 0,
    completed_tasks: 0, in_progress_tasks: 0, without_confirmed_coverage: 0,
    affected_teams: 0, refusals: 0, expirations: 0, escalations: 0, pending_bp: 0,
  });
  vi.mocked(api.getAudit).mockResolvedValue({ events: [], total: 0 });
  vi.mocked(api.decideApproval).mockResolvedValue({ status: "approved" });
}

describe("Realoca AI frontend", () => {
  beforeEach(() => mockApi());

  it("keeps legacy employee totals unknown and permits read-only selection of task owner IDs", async () => {
    vi.mocked(api.listEmployees).mockRejectedValue(new ApiError("Fonte incompleta", 422, "INCOMPLETE_SOURCE_DATA"));
    vi.mocked(api.listTasks).mockResolvedValue([task(), task({ task_id: "duplicate-owner" })]);
    render(<App />);
    await screen.findByText("Dados legados incompletos de funcionários.");
    expect(within(screen.getByText("Funcionários publicados").parentElement!).getByText("—")).toBeTruthy();
    expect(screen.getByText("Cobertura real dos casos")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Casos de Ausência/ }));
    const select = await screen.findByLabelText("Funcionário") as HTMLSelectElement;
    await waitFor(() => expect(select.disabled).toBe(false));
    expect(select.options.length).toBe(2);
    expect(select.options[1].text).toBe("emp-ana · ID registrado em /tasks");
    fireEvent.change(select, { target: { value: "emp-ana" } });
    expect(select.value).toBe("emp-ana");
    expect((screen.getByRole("button", { name: "Registrar ausência" }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.createAbsence).not.toHaveBeenCalled();
    expect(api.planCase).not.toHaveBeenCalled();
  });

  it("does not invent fallback IDs when tasks also fail", async () => {
    vi.mocked(api.listEmployees).mockRejectedValue(new ApiError("Fonte incompleta", 422, "INCOMPLETE_SOURCE_DATA"));
    vi.mocked(api.listTasks).mockRejectedValue(new ApiError("Tarefas indisponíveis", 503, "DATABASE_UNAVAILABLE"));
    render(<App />);
    await screen.findByText("Dados legados incompletos de funcionários.");
    fireEvent.click(screen.getByRole("button", { name: /Casos de Ausência/ }));
    expect((screen.getByLabelText("Funcionário") as HTMLSelectElement).disabled).toBe(true);
    expect(await screen.findByText("Tarefas indisponíveis")).toBeTruthy();
  });

  it("does not enable fallback selection for unrelated employee errors", async () => {
    vi.mocked(api.listEmployees).mockRejectedValue(new ApiError("Indisponível", 503, "DATABASE_UNAVAILABLE"));
    render(<App />);
    await screen.findByText("Alguns dados não puderam ser carregados.");
    fireEvent.click(screen.getByRole("button", { name: /Casos de Ausência/ }));
    expect((screen.getByLabelText("Funcionário") as HTMLSelectElement).disabled).toBe(true);
    expect(screen.queryByText("Dados legados incompletos de funcionários.")).toBeNull();
  });

  it("shows API-derived dashboard indicators and real coverage metrics", async () => {
    render(<App />);
    const cardLabel = await screen.findByText("Tarefas ativas");
    expect(within(cardLabel.parentElement!).getByText("1")).toBeTruthy();
    expect(await screen.findByText("Cobertura real dos casos")).toBeTruthy();
    expect(screen.getByText("Horas confirmadas")).toBeTruthy();
  });

  it("counts only active task demand and retains a real zero separately from unknown", async () => {
    mockApi({ tasks: [task(), task({ task_id: "task-002", title: "Encerrada", status: "done", estimated_hours: 8 })] });
    render(<App />);
    const activeCount = await screen.findByText("Tarefas ativas");
    expect(within(activeCount.parentElement!).getByText("1")).toBeTruthy();
    const activeHours = screen.getByText("Horas de demanda ativa");
    expect(within(activeHours.parentElement!).getByText("2h")).toBeTruthy();
    expect(screen.getByText("Estados não são equivalentes")).toBeTruthy();
  });

  it("keeps dashboard metrics unknown after a 503 instead of replacing them with zero", async () => {
    vi.mocked(api.listTasks).mockRejectedValue(new ApiError("Consulta indisponível", 503, "DATABASE_UNAVAILABLE"));
    render(<App />);
    await screen.findByText("Alguns dados não puderam ser carregados.");
    const activeCount = screen.getByText("Tarefas ativas");
    expect(within(activeCount.parentElement!).getByText("—")).toBeTruthy();
    const activeHours = screen.getByText("Horas de demanda ativa");
    expect(within(activeHours.parentElement!).getByText("—")).toBeTruthy();
  });

  it("runs Slack accept and refusal flows only in local demo state", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Simulador Slack/ }));
    expect(await screen.findByText(/SIMULAÇÃO LOCAL · DADOS FICTÍCIOS/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Aceitar · simulação" }));
    expect(await screen.findByText("Aceite fictício registrado")).toBeTruthy();
    expect(screen.getByText(/A cobertura do caso continua desconhecida/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reiniciar cenário" }));
    fireEvent.change(screen.getByLabelText("Cenário"), { target: { value: "refuse" } });
    fireEvent.click(screen.getByRole("button", { name: "Recusar · simulação" }));
    expect(await screen.findByText("Replanejamento necessário")).toBeTruthy();
    expect(api.createAbsence).not.toHaveBeenCalled();
  });

  it("shows the next fixture candidate after a refusal and the gap when none remains", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Simulador Slack/ }));
    fireEvent.change(screen.getByLabelText("Cenário"), { target: { value: "replan" } });
    fireEvent.click(screen.getByRole("button", { name: "Recusar · simulação" }));
    expect(await screen.findByText("Novo candidato fictício proposto: Beatriz Melo. O candidato recusante foi excluído desta tarefa.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Recusar · simulação" }));
    expect(await screen.findByText("Tarefa sem cobertura no cenário")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Cenário"), { target: { value: "no-substitute" } });
    fireEvent.click(screen.getByRole("button", { name: "Recusar · simulação" }));
    expect(await screen.findByText("Tarefa sem cobertura no cenário")).toBeTruthy();
    expect(api.createAbsence).not.toHaveBeenCalled();
  });

  it("navigates between operational pages", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Tarefas/ }));
    expect(await screen.findByText("Tarefas do turno")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Equipes e Capacidade/ }));
    expect(await screen.findByText("Capacidade por equipe")).toBeTruthy();
  });

  it("filters tasks by search and priority", async () => {
    mockApi({ tasks: [task(), task({ task_id: "task-002", title: "Exportar relatório", priority: "low" })] });
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Tarefas/ }));
    expect(await screen.findByText("Revisar automação")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Buscar tarefa" }), { target: { value: "relatório" } });
    expect(screen.getByText("Exportar relatório")).toBeTruthy();
    expect(screen.queryByText("Revisar automação")).toBeNull();
    fireEvent.change(screen.getByRole("combobox", { name: "Filtrar prioridade" }), { target: { value: "critical" } });
    expect(screen.getByText("Nenhum resultado")).toBeTruthy();
  });

  it("renders null team capacity as unavailable instead of zero", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Equipes e Capacidade/ }));
    const teamName = await screen.findByText("Operações");
    const row = teamName.closest("tr");
    expect(row).toBeTruthy();
    expect(within(row!).getAllByText("Não disponível").length).toBeGreaterThan(0);
    expect(within(row!).getByText("Incompleto")).toBeTruthy();
  });

  it("shows utilization above 100 percent without capping the reported value", async () => {
    mockApi({ teams: [{
      ...team, shift_hours: 8, committed_hours: 10, reserved_hours: 0,
      occupied_hours: 10, utilization_pct: 125, complete: true,
    }] });
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Equipes e Capacidade/ }));
    const teamName = await screen.findByText("Operações");
    expect(teamName.closest("tr")?.textContent).toContain("125%");
  });

  it("shows empty task state when the API returns an empty list", async () => {
    mockApi({ tasks: [] });
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Tarefas/ }));
    expect(await screen.findByText("Nenhuma tarefa publicada")).toBeTruthy();
  });

  it("shows real BP queue and immutable audit instead of unsupported API warnings", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Aprovações/ }));
    expect(await screen.findByText("Aprovações do BP")).toBeTruthy();
    expect(await screen.findByText("Nenhuma proposta aguardando decisão BP.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Auditoria/ }));
    expect(await screen.findByText("Trilha auditável real")).toBeTruthy();
    expect(await screen.findByText("Nenhum evento encontrado para este filtro.")).toBeTruthy();
  });

  it("reports backend connection errors and offers retry", async () => {
    vi.mocked(api.listTasks).mockRejectedValue(new Error("offline"));
    render(<App />);
    expect(await screen.findByText("Alguns dados não puderam ser carregados.")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Tentar novamente" }).length).toBeGreaterThan(0);
  });

  it("posts a confirmed absence and displays only the server response", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Casos de Ausência/ }));
    expect(await screen.findByText("Registrar ausência confirmada")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Funcionário"), { target: { value: "emp-ana" } });
    fireEvent.change(screen.getByLabelText("Início"), { target: { value: "2026-11-09T08:00" } });
    fireEvent.change(screen.getByLabelText("Fim"), { target: { value: "2026-11-09T16:00" } });
    fireEvent.change(screen.getByLabelText("Identificador de origem"), { target: { value: "absence-test-1" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Registrar ausência" }));

    expect(await screen.findByText("Resposta confirmada pela API")).toBeTruthy();
    await waitFor(() => expect(api.createAbsence).toHaveBeenCalledWith({
      employee_id: "emp-ana",
      starts_at: new Date("2026-11-09T08:00").toISOString(),
      ends_at: new Date("2026-11-09T16:00").toISOString(),
      confirmed: true,
      source_system: "hr_simulator",
      external_id: "absence-test-1",
    }));
    expect(screen.getByText(/não significa que as tarefas já tenham cobertura confirmada/)).toBeTruthy();
  });

  it("shows an API conflict without marking the absence as registered", async () => {
    vi.mocked(api.createAbsence).mockRejectedValue(
      new ApiError("Ausência sobreposta já registrada.", 409, "ABSENCE_OVERLAP"),
    );
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Casos de Ausência/ }));
    await screen.findByText("Registrar ausência confirmada");
    fireEvent.change(screen.getByLabelText("Funcionário"), { target: { value: "emp-ana" } });
    fireEvent.change(screen.getByLabelText("Início"), { target: { value: "2026-11-09T08:00" } });
    fireEvent.change(screen.getByLabelText("Fim"), { target: { value: "2026-11-09T16:00" } });
    fireEvent.change(screen.getByLabelText("Identificador de origem"), { target: { value: "absence-test-2" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Registrar ausência" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Ausência sobreposta já registrada.");
    expect(screen.queryByText("Resposta confirmada pela API")).toBeNull();
  });

  it("renders task fields without implying that a proposal was accepted", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Tarefas/ }));
    const title = await screen.findByText("Revisar automação");
    expect(title.closest("tr")?.textContent).toContain("Crítica");
    expect(title.closest("tr")?.textContent).toContain("emp-ana");
    expect(screen.queryByText("Cobertura confirmada")).toBeNull();
  });

  it("shows a loading state while a request is pending", async () => {
    let resolveTasks: ((value: Task[]) => void) | undefined;
    vi.mocked(api.listTasks).mockReturnValue(new Promise((resolve) => { resolveTasks = resolve; }));
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Tarefas/ }));
    expect(screen.getByRole("status").textContent).toContain("Carregando tarefas");
    resolveTasks?.([task()]);
    expect(await screen.findByText("Revisar automação")).toBeTruthy();
  });
});
