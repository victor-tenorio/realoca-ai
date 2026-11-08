import type {
  AbsenceCreate,
  AbsenceCreated,
  ApiErrorBody,
  AuditTrailResponse,
  CaseDetail,
  CaseList,
  CoverageDashboard,
  Employee,
  Task,
  Team,
} from "./types";

const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim() || "/api/v1";
const API_BASE_URL = configuredBase.replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(API_BASE_URL + path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch {
    if (init.signal?.aborted) throw new Error("Request aborted");
    throw new ApiError(
      "Não foi possível conectar ao backend. Verifique se a API está em execução.",
      0,
      "NETWORK_ERROR",
    );
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    throw new ApiError(
      body.error?.message || "A API respondeu com HTTP " + response.status + ".",
      response.status,
      body.error?.code || "HTTP_" + response.status,
      body.error?.details || {},
    );
  }
  return (await response.json()) as T;
}

export const api = {
  listEmployees(signal?: AbortSignal) {
    return request<Employee[]>("/employees", { signal });
  },
  listTasks(signal?: AbortSignal) {
    return request<Task[]>("/tasks", { signal });
  },
  listTeams(signal?: AbortSignal) {
    return request<Team[]>("/teams", { signal });
  },
  listCases(signal?: AbortSignal) {
    return request<CaseList>("/cases", { signal });
  },
  getCase(caseId: string, signal?: AbortSignal) {
    return request<CaseDetail>("/cases/" + encodeURIComponent(caseId), { signal });
  },
  planCase(caseId: string) {
    return request<Record<string, unknown>>("/cases/" + encodeURIComponent(caseId) + "/plan", { method: "POST" });
  },
  getDashboard(signal?: AbortSignal) {
    return request<CoverageDashboard>("/dashboard", { signal });
  },
  getAudit(caseId?: string, signal?: AbortSignal) {
    const filter = caseId ? "?case_id=" + encodeURIComponent(caseId) : "";
    return request<AuditTrailResponse>("/audit" + filter, { signal });
  },
  decideApproval(attemptId: string, decision: "approve" | "reject", actorId: string, reason: string) {
    return request<Record<string, unknown>>("/proposals/" + encodeURIComponent(attemptId) + "/approval", {
      method: "POST",
      body: JSON.stringify({ decision, actor_id: actorId, reason }),
    });
  },
  createAbsence(payload: AbsenceCreate) {
    return request<AbsenceCreated>("/absences", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return error.message + " Confira os dados atuais antes de tentar novamente.";
    }
    if (error.status === 422) {
      return error.message + " A API encontrou informações incompletas.";
    }
    return error.message;
  }
  return "Ocorreu um erro inesperado ao consultar o backend.";
}
