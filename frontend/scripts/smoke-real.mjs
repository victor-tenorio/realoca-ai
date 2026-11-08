// Read-only verification against the running demo. No fixtures or request mocks.
import { chromium, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import os from 'node:os';
import process from 'node:process';

const base = process.env.REALOCA_DEMO_URL || 'http://localhost:5173';
const isPublic = base.startsWith('https://');
const caseId = 'case-5c3d64a2-c22a-4f92-b2af-25109f4f053c';
const output = resolve(import.meta.dirname, isPublic ? '../../docs/evidencias-publicas' : '../../docs/evidencias');
await mkdir(output, { recursive: true });
const report = { timestamp: new Date().toISOString(), computer: os.hostname(), base,
  backend: isPublic ? base : 'http://127.0.0.1:8001', http: [], pages: [], consoleErrors: [], pageErrors: [], failedRequests: [], mutations: [] };
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
  const navigation = await page.goto(base);
  expect(navigation.status()).toBe(200);
  if (isPublic) {
    expect(navigation.headers()['x-realoca-mode']).toBe('public-read-only');
    report.tls = await navigation.securityDetails();
    expect(report.tls).not.toBeNull();
    await expect(page.getByText(/DEMO PÚBLICA · SOMENTE LEITURA/)).toBeVisible();
  }
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
  if (isPublic) {
    await page.getByRole('navigation').getByRole('button', { name: /Simulador Slack/ }).click();
    await expect(page.getByText(/SIMULAÇÃO LOCAL · DADOS FICTÍCIOS/)).toBeVisible();
    await page.getByRole('button', { name: 'Aceitar · simulação' }).click();
    await expect(page.getByText('Aceite fictício registrado', { exact: true })).toBeVisible();
    await page.screenshot({ path: resolve(output, '07-simulador-local.png'), fullPage: true });
    report.simulator = 'Local acceptance only; no API mutation';
    report.blockedWrites = [];
    for (const path of ['/api/v1/absences', `/api/v1/cases/${caseId}/plan`, '/api/v1/proposals/unknown/approval', '/integrations/n8n/events']) {
      const response = await context.request.post(base + path, { data: {} });
      expect(response.status()).toBe(405);
      expect((await response.json()).error.code).toBe('PUBLIC_DEMO_READ_ONLY');
      report.blockedWrites.push({ path, status: response.status() });
    }
    report.blockedPaths = [];
    for (const path of ['/docs', '/openapi.json', '/redoc', '/.env', '/realoca.db', '/.public-demo/snapshot.db', '/api/v1/policies', '/integrations/n8n/events', '/src/main.tsx']) {
      const response = await context.request.get(base + path);
      expect(response.status()).toBe(404);
      report.blockedPaths.push({ path, status: response.status() });
    }
    expect(await (await context.request.get(base + '/api/v1/dashboard')).json()).toEqual(report.dashboard);
    // Compare responses with credential values without writing any values to evidence.
    const secrets = Object.entries(process.env).filter(([key, value]) => /^(N8N|SLACK)_/.test(key) && /TOKEN|SECRET|KEY/.test(key) && value.length > 8).map(([, value]) => value);
    const exposed = await (await context.request.get(base + '/api/v1/audit')).text() + await page.content();
    expect(secrets.some(secret => exposed.includes(secret))).toBe(false);
    expect(/xox[baprs]-[a-zA-Z0-9-]{10,}|-----BEGIN .*PRIVATE KEY-----/.test(exposed)).toBe(false);
    report.secretCheck = 'No credential values or Slack token/private-key patterns in audit or HTML; internal paths blocked';
  }
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
