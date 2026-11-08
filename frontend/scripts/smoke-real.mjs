// Read-only verification against the running demo. No fixtures or request mocks.
import { chromium, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import os from 'node:os';
import process from 'node:process';

const base = 'http://localhost:5173';
const caseId = 'case-5c3d64a2-c22a-4f92-b2af-25109f4f053c';
const output = resolve(import.meta.dirname, '../../docs/evidencias');
await mkdir(output, { recursive: true });
const report = { timestamp: new Date().toISOString(), computer: os.hostname(), base,
  backend: 'http://127.0.0.1:8001', http: [], pages: [], consoleErrors: [], pageErrors: [], failedRequests: [], mutations: [] };
const browser = await chromium.launch({ channel: 'chrome' });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'pt-BR', timezoneId: 'America/Sao_Paulo' });
  const page = await context.newPage();
  page.on('console', msg => { if (msg.type() === 'error') report.consoleErrors.push({ message: msg.text(), url: msg.location().url }); });
  page.on('pageerror', error => report.pageErrors.push(error.message));
  page.on('requestfailed', request => report.failedRequests.push({ url: request.url(), failure: request.failure() }));
  page.on('request', request => { if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) report.mutations.push({ method: request.method(), url: request.url() }); });
  for (const path of ['/health', '/api/v1/employees', '/api/v1/tasks', '/api/v1/teams', '/api/v1/cases', '/api/v1/dashboard', '/api/v1/audit']) {
    const api = await context.request.get(report.backend + path);
    const data = await api.json();
    const expected = path.endsWith('/employees') ? 422 : 200;
    expect(api.status()).toBe(expected);
    if (expected === 422) expect(data.error.code).toBe('INCOMPLETE_SOURCE_DATA');
    const row = { path, backendStatus: api.status(), shape: Array.isArray(data) ? 'array' : 'object', count: Array.isArray(data) ? data.length : data.total, keys: Array.isArray(data) ? Object.keys(data[0] ?? {}) : Object.keys(data) };
    if (path !== '/health') {
      const proxy = await context.request.get(base + path);
      expect(proxy.status()).toBe(expected);
      expect(await proxy.json()).toEqual(data);
      row.proxyStatus = proxy.status();
    }
    report.http.push(row);
  }
  await page.goto(base);
  await expect(page.getByText('Dados legados incompletos de funcionários.', { exact: true })).toBeVisible();
  await expect(page.getByText('Horas confirmadas', { exact: true })).toBeVisible();
  await expect(page.locator('.metric-card').filter({ hasText: 'Funcionários publicados' }).locator('.metric-value')).toHaveText('—');
  const tabs = [
    ['01-visao-geral', 'Visão Geral', 'Cobertura real dos casos'],
    ['02-casos', 'Casos de Ausência', 'Casos e propostas da API'],
    ['03-tarefas', 'Tarefas', 'Tarefas do turno'],
    ['04-equipes', 'Equipes e Capacidade', 'Capacidade por equipe'],
    ['05-aprovacoes', 'Aprovações', 'Aprovações do BP'],
    ['06-auditoria', 'Auditoria', 'Trilha auditável real'],
  ];
  for (const [file, tab, heading] of tabs) {
    await page.getByRole('navigation').getByRole('button', { name: tab, exact: false }).click();
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
    if (file === '02-casos') {
      const caseSelect = page.getByLabel('Selecionar caso');
      if (await caseSelect.inputValue() !== caseId) await caseSelect.selectOption(caseId);
      await expect(page.locator('.field-hint').filter({ hasText: caseId })).toBeVisible();
      await expect(page.getByText('Proposta recusada', { exact: true })).toBeVisible();
      const owners = await (await context.request.get(base + '/api/v1/tasks')).json();
      const id = owners.find(task => task.assignee_employee_id)?.assignee_employee_id;
      await page.locator('select[name="employee_id"]').selectOption(id);
      await expect(page.locator('select[name="employee_id"]')).toHaveValue(id);
      await expect(page.getByRole('button', { name: 'Registrar ausência', exact: true })).toBeDisabled();
    }
    if (file === '05-aprovacoes') await expect(page.getByText('Nenhuma proposta aguardando decisão BP.', { exact: true })).toBeVisible();
    if (file === '06-auditoria') {
      await page.getByLabel('Filtrar por ID de caso').fill(caseId);
      await expect(page.getByText('offer.refused', { exact: true })).toBeVisible();
      await expect(page.getByText('plan.replanned', { exact: true })).toBeVisible();
      await expect(page.getByText('21 eventos no servidor; exibindo os 100 mais recentes.', { exact: true })).toBeVisible();
    }
    await expect(page.getByText(/Carregando|Consultando casos|Consultando aprovações/).first()).toBeHidden();
    await page.screenshot({ path: resolve(output, `${file}.png`), fullPage: true });
    report.pages.push({ tab, heading, screenshot: `${file}.png`, passed: true });
  }
  report.dashboard = await (await context.request.get(base + '/api/v1/dashboard')).json();
  expect(report.pageErrors).toEqual([]);
  expect(report.mutations).toEqual([]);
  report.expectedConsoleErrors = report.consoleErrors.filter(item => item.url.endsWith('/api/v1/employees') && /422/.test(item.message));
  expect(report.consoleErrors.filter(item => !report.expectedConsoleErrors.includes(item))).toEqual([]);
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.error = String(error);
  throw error;
} finally {
  await writeFile(resolve(output, 'smoke-real.json'), JSON.stringify(report, null, 2) + '\n');
  await browser.close();
}
process.stdout.write(JSON.stringify(report, null, 2) + '\n');
