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
