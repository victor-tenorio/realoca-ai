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
}

describe("Realoca AI frontend", () => {
  beforeEach(() => mockApi());

  it("shows API-derived dashboard indicators and identifies unavailable coverage metrics", async () => {
    render(<App />);
    const cardLabel = await screen.findByText("Tarefas em andamento");
    expect(within(cardLabel.parentElement!).getByText("1")).toBeTruthy();
    expect(screen.getByText(/Indicadores de cobertura indisponíveis/)).toBeTruthy();
    expect(screen.getByText(/não expõe consultas de casos/)).toBeTruthy();
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

  it("keeps approval and audit pages read-only when their routes are absent", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Aprovações/ }));
    expect(await screen.findByText("Consulta de aprovações não implementada")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Aprovar" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Rejeitar" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Auditoria/ }));
    expect(await screen.findByText("Consulta de auditoria não implementada")).toBeTruthy();
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
