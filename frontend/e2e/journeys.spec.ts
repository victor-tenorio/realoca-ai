import { expect, test, type Page } from "@playwright/test";

const employees = [{
  employee_id: "emp-ana", name: "Ana Lima", team_id: "ops", skills: ["python"],
  shift_hours: 8, committed_hours: 3, reserved_hours: 1, availability: "available",
  preferred_channel: "slack", channel_user_id: "demo-ana", source_system: "hr_simulator",
  external_id: "ana-01", updated_at: "2026-11-08T08:00:00Z",
}];

const tasks = [
  {
    task_id: "task-001", title: "Revisar automação", assignee_employee_id: "emp-ana",
    team_id: "ops", priority: "critical", due_at: "2026-11-08T10:00:00-03:00",
    estimated_hours: 2, required_skills: ["python"], status: "open",
    transfer_allowed: true, source_system: "task_simulator", external_id: "job-1",
    updated_at: "2026-11-08T08:00:00Z",
  },
  {
    task_id: "task-002", title: "Exportar relatório", assignee_employee_id: "emp-ana",
    team_id: "ops", priority: "high", due_at: "2026-11-08T11:00:00-03:00",
    estimated_hours: 1.5, required_skills: ["excel"], status: "in_progress",
    transfer_allowed: true, source_system: "task_simulator", external_id: "job-2",
    updated_at: "2026-11-08T08:00:00Z",
  },
  {
    task_id: "task-003", title: "Arquivo encerrado", assignee_employee_id: "emp-ana",
    team_id: "ops", priority: "low", due_at: "2026-11-08T12:00:00-03:00",
    estimated_hours: 9, required_skills: [], status: "done",
    transfer_allowed: true, source_system: "task_simulator", external_id: "job-3",
    updated_at: "2026-11-08T08:00:00Z",
  },
];

const teams = [{
  team_id: "ops", name: "Operações", reference_date: "2026-11-08", employee_count: 1,
  shift_hours: 8, committed_hours: 10, reserved_hours: 0, occupied_hours: 10,
  utilization_pct: 125, complete: true,
}];

async function installApiFixtures(page: Page, options: { tasksStatus?: number; empty?: boolean } = {}) {
  await page.route("**/api/v1/employees", (route) => route.fulfill({ json: employees }));
  await page.route("**/api/v1/tasks", (route) => options.tasksStatus
    ? route.fulfill({ status: options.tasksStatus, json: { error: { code: "DATABASE_UNAVAILABLE", message: "Consulta indisponível", details: {} } } })
    : route.fulfill({ json: options.empty ? [] : tasks }));
  await page.route("**/api/v1/teams", (route) => route.fulfill({ json: teams }));
  await page.route("**/api/v1/dashboard", (route) => route.fulfill({ json: {
    confirmed_absences: 0, cases_total: 0, cases_open: 0, affected_tasks: 0, affected_hours: 0,
    planned_hours: 0, confirmed_hours: 0, completed_hours: 0, completed_tasks: 0,
    in_progress_tasks: 0, without_confirmed_coverage: 0, affected_teams: 0,
    refusals: 0, expirations: 0, escalations: 0, pending_bp: 0,
  }}));
  await page.route("**/api/v1/cases", (route) => route.fulfill({ json: { cases: [], total: 0 } }));
  await page.route("**/api/v1/audit*", (route) => route.fulfill({ json: { events: [], total: 0 } }));
}

test("dashboard indicators, priority distribution and no unexpected errors", async ({ page }, testInfo) => {
  await installApiFixtures(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("/");

  await expect(page.locator(".metric-card").nth(0)).toContainText("2");
  await expect(page.locator(".metric-card").nth(1)).toContainText("3,5h");
  await expect(page.getByText("Prioridade crítica")).toBeVisible();
  await expect(page.getByText("Estados não são equivalentes")).toBeVisible();
  await expect(page.getByText("Cobertura real dos casos")).toBeVisible();
  expect(pageErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("dashboard.png"), fullPage: true });
});

test("task search/filter and team capacity remain faithful to API values", async ({ page }, testInfo) => {
  await installApiFixtures(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Tarefas" }).click();
  await page.getByRole("textbox", { name: "Buscar tarefa" }).fill("relatório");
  await expect(page.getByText("Exportar relatório")).toBeVisible();
  await page.getByRole("combobox", { name: "Filtrar prioridade" }).selectOption("critical");
  await expect(page.getByText("Nenhum resultado")).toBeVisible();
  await page.getByRole("button", { name: "Equipes e Capacidade" }).click();
  const teamRow = page.getByRole("row", { name: /Operações/ });
  await expect(teamRow).toContainText("125%");
  await expect(teamRow).toContainText("Completo");
  await page.screenshot({ path: testInfo.outputPath("team-capacity.png"), fullPage: true });
});

test("absence form validates locally and uses only a mocked API response", async ({ page }) => {
  await installApiFixtures(page);
  let postCount = 0;
  await page.route("**/api/v1/absences", async (route) => {
    if (route.request().method() === "POST") postCount += 1;
    await route.fulfill({ status: 201, json: { absence_id: "abs-e2e", case_id: "case-e2e", status: "open" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Casos de Ausência" }).click();
  const submit = page.getByRole("button", { name: "Registrar ausência" });
  await submit.click();
  expect(postCount).toBe(0);
  await expect(page.getByLabel("Funcionário")).toHaveJSProperty("value", "");
  await page.getByLabel("Funcionário").selectOption("emp-ana");
  await page.getByLabel("Início").fill("2026-11-09T08:00");
  await page.getByLabel("Fim").fill("2026-11-09T16:00");
  await page.getByLabel("Identificador de origem").fill("absence-e2e-only");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Registrar ausência" }).click();
  await expect(page.getByText("Resposta confirmada pela API")).toBeVisible();
  await expect(page.getByText(/não significa que as tarefas já tenham cobertura confirmada/)).toBeVisible();
  expect(postCount).toBe(1);
});

test("Slack simulation covers acceptance, refusal, replan and gap without API writes", async ({ page }, testInfo) => {
  let writes = 0;
  await page.route("**/api/v1/**", async (route) => {
    if (["POST", "PATCH", "PUT", "DELETE"].includes(route.request().method())) writes += 1;
    await route.continue();
  });
  await installApiFixtures(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Simulador Slack" }).click();
  await expect(page.getByText(/SIMULAÇÃO LOCAL · DADOS FICTÍCIOS/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("slack-simulator.png"), fullPage: true });
  await page.getByRole("button", { name: "Aceitar · simulação" }).click();
  await expect(page.getByText("Aceite fictício registrado")).toBeVisible();
  await expect(page.getByText(/A cobertura do caso continua desconhecida/)).toBeVisible();

  await page.getByLabel("Cenário").selectOption("refuse");
  await page.getByRole("button", { name: "Recusar · simulação" }).click();
  await expect(page.getByText("Replanejamento necessário")).toBeVisible();

  await page.getByLabel("Cenário").selectOption("replan");
  await page.getByRole("button", { name: "Recusar · simulação" }).click();
  await expect(page.getByText(/Novo candidato fictício proposto: Beatriz Melo/)).toBeVisible();
  await expect(page.getByLabel("Histórico das interações").getByText("Lucas Prado")).toBeVisible();
  await expect(page.getByText("Proposta recusada")).toBeVisible();

  await page.getByLabel("Cenário").selectOption("no-substitute");
  await page.getByRole("button", { name: "Recusar · simulação" }).click();
  await expect(page.getByText("Tarefa sem cobertura no cenário")).toBeVisible();
  expect(writes).toBe(0);
});

test("empty and 503 responses stay explicit and the mobile navigation is usable", async ({ page }, testInfo) => {
  await installApiFixtures(page, { empty: true });
  await page.goto("/");
  await expect(page.getByText("Nenhuma tarefa publicada")).toBeVisible();
  await page.getByRole("button", { name: "Tarefas" }).click();
  await expect(page.getByText("Nenhuma tarefa publicada")).toBeVisible();
  await page.getByRole("button", { name: "Atualizar" }).click();

  await page.unrouteAll();
  await installApiFixtures(page, { tasksStatus: 503 });
  await page.reload();
  await expect(page.getByText("Alguns dados não puderam ser carregados.")).toBeVisible();
  await expect(page.getByText("Consulta indisponível").first()).toBeVisible();
  await page.getByRole("button", { name: "Simulador Slack" }).click();
  await expect(page.getByRole("heading", { name: "Simulador Slack" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("mobile-slack.png"), fullPage: true });
});

test("network errors keep dashboard demand unknown", async ({ page }) => {
  await page.route("**/api/v1/tasks", (route) => route.abort("failed"));
  await page.route("**/api/v1/employees", (route) => route.fulfill({ json: employees }));
  await page.route("**/api/v1/teams", (route) => route.fulfill({ json: teams }));
  await page.goto("/");

  await expect(page.getByRole("alert").first()).toBeVisible();
  await expect(page.locator(".metric-card").nth(0)).toContainText("—");
  await expect(page.locator(".metric-card").nth(1)).toContainText("—");
});


test("real case, approval and audit views are wired to backend contracts", async ({ page }) => {
  await installApiFixtures(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Casos de Ausência" }).click();
  await expect(page.getByText("Casos e propostas da API")).toBeVisible();
  await expect(page.getByText("Nenhum caso registrado até agora.")).toBeVisible();
  await page.getByRole("button", { name: "Aprovações" }).click();
  await expect(page.getByText("Aprovações do BP")).toBeVisible();
  await expect(page.getByText("Nenhuma proposta aguardando decisão BP.")).toBeVisible();
  await page.getByRole("button", { name: "Auditoria" }).click();
  await expect(page.getByText("Trilha auditável real")).toBeVisible();
  await expect(page.getByText("Nenhum evento encontrado para este filtro.")).toBeVisible();
});
