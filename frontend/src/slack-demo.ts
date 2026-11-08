import type { AttemptStatus, Priority } from "./types";

export type SlackScenarioId = "accept" | "refuse" | "replan" | "no-substitute";

export interface SlackDemoCandidate {
  employeeId: string;
  name: string;
  team: string;
  skills: string[];
  availableHours: number;
}

export interface SlackDemoScenario {
  id: SlackScenarioId;
  label: string;
  task: {
    taskId: string;
    title: string;
    priority: Priority;
    estimatedHours: number;
    team: string;
    reason: string;
    requiredSkills: string[];
  };
  candidates: SlackDemoCandidate[];
  refusal: "manual-replan" | "automatic-replan" | "gap";
}

export interface SlackDemoState {
  attempts: Array<{ employeeId: string; status: AttemptStatus }>;
  events: Array<{ actor: "slack" | "employee" | "system"; text: string; employeeName?: string }>;
  outcome: "awaiting-response" | "accepted" | "replanning-required" | "uncovered";
}

export const slackScenarios: SlackDemoScenario[] = [
  {
    id: "accept",
    label: "A · Aceitação",
    task: {
      taskId: "demo-task-fin-021",
      title: "Conciliar pagamentos do turno",
      priority: "critical",
      estimatedHours: 2.5,
      team: "Financeiro",
      reason: "Competências de conciliação disponíveis e capacidade elegível no cenário fictício.",
      requiredSkills: ["conciliação", "Excel"],
    },
    candidates: [
      { employeeId: "demo-camila", name: "Camila Nunes", team: "Financeiro", skills: ["conciliação", "Excel"], availableHours: 3 },
    ],
    refusal: "manual-replan",
  },
  {
    id: "refuse",
    label: "B · Recusa",
    task: {
      taskId: "demo-task-ops-014",
      title: "Revisar checklist de expedição",
      priority: "high",
      estimatedHours: 1.5,
      team: "Operações",
      reason: "Competências de operação e capacidade elegível no cenário fictício.",
      requiredSkills: ["operações"],
    },
    candidates: [
      { employeeId: "demo-rafael", name: "Rafael Costa", team: "Operações", skills: ["operações"], availableHours: 2 },
    ],
    refusal: "manual-replan",
  },
  {
    id: "replan",
    label: "C · Recusa e replanejamento",
    task: {
      taskId: "demo-task-data-008",
      title: "Validar relatório de indicadores",
      priority: "medium",
      estimatedHours: 2,
      team: "Dados",
      reason: "Competências de análise de dados e capacidade elegível no cenário fictício.",
      requiredSkills: ["Excel", "análise de dados"],
    },
    candidates: [
      { employeeId: "demo-lucas", name: "Lucas Prado", team: "Dados", skills: ["Excel", "análise de dados"], availableHours: 2.5 },
      { employeeId: "demo-beatriz", name: "Beatriz Melo", team: "Operações", skills: ["Excel", "análise de dados"], availableHours: 3 },
    ],
    refusal: "automatic-replan",
  },
  {
    id: "no-substitute",
    label: "D · Sem substituto",
    task: {
      taskId: "demo-task-rh-003",
      title: "Conferir arquivo de benefícios",
      priority: "high",
      estimatedHours: 3,
      team: "Pessoas",
      reason: "Único candidato fictício com competências e capacidade suficientes.",
      requiredSkills: ["folha", "Excel"],
    },
    candidates: [
      { employeeId: "demo-julia", name: "Júlia Reis", team: "Pessoas", skills: ["folha", "Excel"], availableHours: 3 },
    ],
    refusal: "gap",
  },
];

export function initialSlackDemoState(scenario: SlackDemoScenario): SlackDemoState {
  const candidate = scenario.candidates[0];
  return {
    attempts: candidate ? [{ employeeId: candidate.employeeId, status: "notified" }] : [],
    events: [{
      actor: "slack",
      text: "Mensagem fictícia exibida no simulador. Nenhuma mensagem foi enviada pelo Slack.",
    }],
    outcome: "awaiting-response",
  };
}

export function respondToSlackProposal(
  scenario: SlackDemoScenario,
  state: SlackDemoState,
  response: "accept" | "refuse",
): SlackDemoState {
  if (state.outcome !== "awaiting-response" || state.attempts.length === 0) return state;

  const current = state.attempts[state.attempts.length - 1];
  const respondingCandidate = scenario.candidates.find((candidate) => candidate.employeeId === current.employeeId);
  const status: AttemptStatus = response === "accept" ? "accepted" : "refused";
  const next = {
    ...state,
    attempts: state.attempts.map((attempt, index) => index === state.attempts.length - 1
      ? { ...attempt, status }
      : attempt),
    events: [...state.events, {
      actor: "employee" as const,
      employeeName: respondingCandidate?.name,
      text: response === "accept" ? "Resposta registrada: aceite (simulação)." : "Resposta registrada: recusa (simulação).",
    }],
  };

  if (response === "accept") {
    return {
      ...next,
      outcome: "accepted",
      events: [...next.events, {
        actor: "system",
        text: "Aceite apenas local. Não há reserva, atribuição nem cobertura confirmada no backend.",
      }],
    };
  }

  if (scenario.refusal === "automatic-replan") {
    const refusedIds = new Set(next.attempts.map((attempt) => attempt.employeeId));
    const substitute = scenario.candidates.find((candidate) => !refusedIds.has(candidate.employeeId));
    if (substitute) {
      return {
        ...next,
        attempts: [...next.attempts, { employeeId: substitute.employeeId, status: "notified" }],
        outcome: "awaiting-response",
        events: [...next.events, {
          actor: "system",
          text: `Novo candidato fictício proposto: ${substitute.name}. O candidato recusante foi excluído desta tarefa.`,
        }],
      };
    }
  }

  if (scenario.refusal === "gap") {
    return {
      ...next,
      outcome: "uncovered",
      events: [...next.events, {
        actor: "system",
        text: "Nenhum substituto fictício elegível foi predefinido. A tarefa permanece sem cobertura e requer escalonamento.",
      }],
    };
  }

  if (scenario.refusal === "automatic-replan") {
    return {
      ...next,
      outcome: "uncovered",
      events: [...next.events, {
        actor: "system",
        text: "Todos os candidatos fictícios predefinidos foram recusados. A tarefa permanece sem cobertura e requer escalonamento.",
      }],
    };
  }

  return {
    ...next,
    outcome: "replanning-required",
    events: [...next.events, {
      actor: "system",
      text: "A tarefa continua sem cobertura. É necessário replanejar com um snapshot atualizado.",
    }],
  };
}
