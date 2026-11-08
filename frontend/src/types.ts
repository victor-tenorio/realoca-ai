export type Priority = "critical" | "high" | "medium" | "low";
export type TaskStatus = "open" | "in_progress" | "done";
export type Availability = "available" | "absent" | "unavailable";
export type CaseStatus =
  | "open"
  | "planning"
  | "pending_approval"
  | "awaiting_responses"
  | "coverage_confirmed"
  | "closed_with_gaps"
  | "completed";
export type AttemptStatus =
  | "proposed"
  | "pending_approval"
  | "reserved"
  | "notified"
  | "accepted"
  | "refused"
  | "expired"
  | "rejected_by_bp"
  | "escalated";

export interface Employee {
  employee_id: string;
  name: string;
  team_id: string;
  skills: string[];
  shift_hours: number;
  committed_hours: number;
  reserved_hours: number;
  availability: Availability;
  preferred_channel: "slack";
  channel_user_id: string;
  source_system: string;
  external_id: string;
  updated_at: string;
}

export interface Task {
  task_id: string;
  title: string;
  assignee_employee_id: string;
  team_id: string;
  priority: Priority;
  due_at: string;
  estimated_hours: number;
  required_skills: string[];
  status: TaskStatus;
  transfer_allowed: boolean;
  source_system: string;
  external_id: string;
  updated_at: string;
}

export interface Team {
  team_id: string;
  name: string;
  reference_date: string;
  employee_count: number;
  shift_hours: number | null;
  committed_hours: number | null;
  reserved_hours: number;
  occupied_hours: number | null;
  utilization_pct: number | null;
  complete: boolean;
}

export interface AbsenceCreate {
  employee_id: string;
  starts_at: string;
  ends_at: string;
  confirmed: true;
  source_system: string;
  external_id: string;
}

export interface AbsenceCreated {
  absence_id: string;
  case_id: string;
  status: CaseStatus;
}

export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  };
}


/** Read-only, authoritative responses from FastAPI A11/A17. */
export interface CaseSummary {
  case_id: string;
  status: CaseStatus;
  plan_version: number;
  created_at: string;
  task_count: number;
  pending_approval_count: number;
  escalation_count: number;
  requires_bp_review: boolean;
}
export interface CaseList { cases: CaseSummary[]; total: number }
export interface CaseProposal {
  attempt_id: string;
  task_id: string;
  candidate_employee_id: string | null;
  status: AttemptStatus;
  reason: string | null;
  plan_version: number;
  approval_decision: string | null;
  approval_actor_id: string | null;
  response_deadline_at: string | null;
}
export interface CaseDetail {
  case_id: string;
  status: CaseStatus;
  plan_version: number;
  created_at: string;
  absences: Array<{absence_id: string; employee_id: string}>;
  tasks: Array<{task_id: string; title: string; status: TaskStatus; assignee_employee_id: string | null}>;
  proposals: CaseProposal[];
  pending_approvals: string[];
  escalations: Array<{attempt_id: string; task_id: string; reason_code: string; alternatives: string[]}>;
}
export interface CoverageDashboard {
  confirmed_absences: number;
  cases_total: number;
  cases_open: number;
  affected_tasks: number;
  affected_hours: number | null;
  planned_hours: number | null;
  confirmed_hours: number | null;
  completed_hours: number | null;
  completed_tasks: number;
  in_progress_tasks: number;
  without_confirmed_coverage: number;
  affected_teams: number;
  refusals: number;
  expirations: number;
  escalations: number;
  pending_bp: number;
}
export interface AuditRecord {
  audit_event_id: string;
  case_id: string | null;
  attempt_id: string | null;
  actor: string;
  action: string;
  timestamp: string;
  policy_version: number | null;
  reason: string | null;
  result: Record<string, unknown> | string;
}
export interface AuditTrailResponse { total: number; events: AuditRecord[] }
