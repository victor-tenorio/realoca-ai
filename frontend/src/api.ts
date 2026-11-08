import type {
  AbsenceCreate,
  AbsenceCreated,
  ApiErrorBody,
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
