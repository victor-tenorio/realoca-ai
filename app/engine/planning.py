"""Deterministic, side-effect-free coverage proposal generation.

This initial engine validates the snapshot and applies a deterministic greedy
heuristic. Joint optimization, full deadline/shift feasibility, and complete
policy handling remain future work (M03-M12).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import math
from typing import Any


class SnapshotValidationError(ValueError):
    """Raised when a planning snapshot is malformed or internally inconsistent."""


def plan_coverage(snapshot: dict) -> dict:
    """Return a deterministic set of coverage proposals for ``snapshot``."""
    return _plan(snapshot)


def replan_coverage(snapshot: dict) -> dict:
    """Recompute proposals from the current snapshot using the same rules."""
    return _plan(snapshot)


def _plan(snapshot: dict) -> dict:
    data = _normalize_snapshot(snapshot)
    employees = {employee["employee_id"]: employee for employee in data["employees"]}
    absent = set(data["absent_employee_ids"])
    exclusions = _normalize_exclusions(data["exclusions"])
    utilization = data["policies"].get("max_utilization_pct", 90)

    remaining = {
        employee_id: max(
            0.0,
            employee["shift_hours"] * (utilization / 100)
            - employee["committed_hours"]
            - employee["reserved_hours"],
        )
        for employee_id, employee in employees.items()
    }
    assignments: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []
    tasks = sorted(
        data["tasks"],
        key=lambda task: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}[task["priority"]],
            task["task_id"],
        ),
    )

    for task in tasks:
        if not task["transfer_allowed"]:
            uncovered.append(_uncovered(task, "TRANSFER_NOT_ALLOWED", []))
            continue
        if task.get("status") == "done":
            uncovered.append(_uncovered(task, "TASK_ALREADY_DONE", []))
            continue

        available_candidates = []
        skill_candidates = []
        non_excluded_candidates = []
        candidates = []
        for employee_id, employee in employees.items():
            if employee_id in absent or employee["availability"] != "available":
                continue
            available_candidates.append(employee)
            if not set(task["required_skills"]).issubset(employee["skills"]):
                continue
            skill_candidates.append(employee)
            if employee_id in exclusions.get(task["task_id"], set()):
                continue
            non_excluded_candidates.append((employee_id, employee))
            if remaining[employee_id] + 1e-9 < task["estimated_hours"]:
                continue
            # Prefer the least flexible eligible employee, then lower current
            # utilization and stable employee ID. Avoid approval-required
            # proposals when an otherwise eligible same-team option exists.
            flexibility = sum(
                1
                for other in tasks
                if set(other["required_skills"]).issubset(employee["skills"])
            )
            effective_capacity = employee["shift_hours"] * (utilization / 100)
            used = effective_capacity - remaining[employee_id]
            requires_approval = _requires_approval(task, employee, data["policies"])
            candidates.append((requires_approval, flexibility, used, employee_id))

        candidates.sort()
        if not candidates:
            if not available_candidates:
                reason_code = "NO_AVAILABLE_CANDIDATE"
            elif not skill_candidates:
                reason_code = "NO_SKILL_MATCH"
            elif not non_excluded_candidates:
                reason_code = "ALL_CANDIDATES_EXCLUDED"
            else:
                # Remaining capacity and detailed deadline/shift feasibility
                # are handled only partially here; M04 completes those checks.
                reason_code = "NO_ELIGIBLE_CANDIDATE"
            uncovered.append(_uncovered(task, reason_code, []))
            continue

        requires_approval, _, _, candidate_id = candidates[0]
        remaining[candidate_id] -= task["estimated_hours"]
        skills = ", ".join(task["required_skills"])
        approval_note = "; proposta requer aprovação BP segundo a política" if requires_approval else ""
        assignments.append(
            {
                "task_id": task["task_id"],
                "candidate_employee_id": candidate_id,
                "estimated_hours": task["estimated_hours"],
                "reason": f"Competências disponíveis ({skills}); candidato elegível{approval_note}",
            }
        )

    demand_hours = sum(task["estimated_hours"] for task in data["tasks"])
    planned_hours = sum(item["estimated_hours"] for item in assignments)
    return {
        "case_id": data["case_id"],
        "plan_version": data["plan_version"],
        "assignments": assignments,
        "uncovered": uncovered,
        "metrics": {"demand_hours": _clean_number(demand_hours), "planned_hours": _clean_number(planned_hours)},
    }


def _normalize_snapshot(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict):
        raise SnapshotValidationError("snapshot must be a dict")
    data = deepcopy(snapshot)
    _required(data, ("case_id", "plan_version", "absent_employee_ids", "tasks", "employees"), "snapshot")
    if not _nonempty_string(data["case_id"]):
        raise SnapshotValidationError("case_id must be a non-empty string")
    if isinstance(data["plan_version"], bool) or not isinstance(data["plan_version"], int) or data["plan_version"] < 1:
        raise SnapshotValidationError("plan_version must be a positive integer")
    if not isinstance(data["absent_employee_ids"], list) or any(not _nonempty_string(v) for v in data["absent_employee_ids"]):
        raise SnapshotValidationError("absent_employee_ids must be a list of non-empty strings")
    if len(data["absent_employee_ids"]) != len(set(data["absent_employee_ids"])):
        raise SnapshotValidationError("absent_employee_ids contains duplicate IDs")
    if not isinstance(data["tasks"], list) or not isinstance(data["employees"], list):
        raise SnapshotValidationError("tasks and employees must be lists")

    data["tasks"] = [_normalize_task(task) for task in data["tasks"]]
    data["employees"] = [_normalize_employee(employee) for employee in data["employees"]]
    _unique_ids(data["tasks"], "task_id", "tasks")
    _unique_ids(data["employees"], "employee_id", "employees")
    _finite_total(
        (task["estimated_hours"] for task in data["tasks"]),
        "total estimated_hours must be finite",
    )
    task_ids = {task["task_id"] for task in data["tasks"]}
    employee_ids = {employee["employee_id"] for employee in data["employees"]}
    normalized_exclusions = _normalize_exclusions(data.get("exclusions", []))
    missing_exclusions = set(normalized_exclusions) - task_ids
    if missing_exclusions:
        raise SnapshotValidationError(f"exclusion references unknown task: {', '.join(sorted(missing_exclusions))}")
    unknown_excluded_employees = {
        employee_id
        for excluded_ids in normalized_exclusions.values()
        for employee_id in excluded_ids
        if employee_id not in employee_ids
    }
    if unknown_excluded_employees:
        raise SnapshotValidationError(
            "exclusion references unknown employee: "
            + ", ".join(sorted(unknown_excluded_employees))
        )
    policies = data.get("policies", {})
    if not isinstance(policies, dict):
        raise SnapshotValidationError("policies must be a dict")
    data["policies"] = _normalize_policies(policies)
    data["exclusions"] = data.get("exclusions", [])
    return data


def _normalize_task(task: Any) -> dict:
    if not isinstance(task, dict):
        raise SnapshotValidationError("each task must be a dict")
    task = deepcopy(task)
    _required(task, ("task_id", "priority", "estimated_hours", "required_skills", "transfer_allowed"), "task")
    if not _nonempty_string(task["task_id"]):
        raise SnapshotValidationError("task_id must be a non-empty string")
    if not isinstance(task["priority"], str) or task["priority"] not in {"critical", "high", "medium", "low"}:
        raise SnapshotValidationError(f"invalid priority for task {task['task_id']}")
    if not _valid_number(task["estimated_hours"]) or task["estimated_hours"] <= 0:
        raise SnapshotValidationError(f"estimated_hours must be positive and finite for task {task['task_id']}")
    task["estimated_hours"] = _clean_number(task["estimated_hours"])
    task["required_skills"] = _skills(task["required_skills"], f"task {task['task_id']} required_skills")
    if not isinstance(task["transfer_allowed"], bool):
        raise SnapshotValidationError(f"transfer_allowed must be boolean for task {task['task_id']}")
    if "status" in task and (
        not isinstance(task["status"], str)
        or task["status"] not in {"open", "in_progress", "done"}
    ):
        raise SnapshotValidationError(f"invalid status for task {task['task_id']}")
    _validate_optional_team_id(task, f"task {task['task_id']}")
    _required(task, ("due_at",), f"task {task['task_id']}")
    _iso_datetime(task["due_at"], f"task {task['task_id']} due_at")
    return task


def _normalize_employee(employee: Any) -> dict:
    if not isinstance(employee, dict):
        raise SnapshotValidationError("each employee must be a dict")
    employee = deepcopy(employee)
    required = ("employee_id", "skills", "shift_hours", "committed_hours", "reserved_hours", "availability")
    _required(employee, required, "employee")
    if not _nonempty_string(employee["employee_id"]):
        raise SnapshotValidationError("employee_id must be a non-empty string")
    employee["skills"] = _skills(employee["skills"], f"employee {employee['employee_id']} skills")
    if not _valid_number(employee["shift_hours"]) or employee["shift_hours"] <= 0:
        raise SnapshotValidationError(f"shift_hours must be positive and finite for employee {employee['employee_id']}")
    for field in ("committed_hours", "reserved_hours"):
        if not _valid_number(employee[field]) or employee[field] < 0:
            raise SnapshotValidationError(f"{field} must be non-negative and finite for employee {employee['employee_id']}")
        employee[field] = _clean_number(employee[field])
    _finite_total(
        (employee["committed_hours"], employee["reserved_hours"]),
        f"combined committed and reserved hours must be finite for employee {employee['employee_id']}",
    )
    employee["shift_hours"] = _clean_number(employee["shift_hours"])
    if not isinstance(employee["availability"], str) or employee["availability"] not in {"available", "absent", "unavailable"}:
        raise SnapshotValidationError(f"invalid availability for employee {employee['employee_id']}")
    _validate_optional_team_id(employee, f"employee {employee['employee_id']}")
    return employee


def _validate_optional_team_id(record: dict, label: str) -> None:
    if "team_id" in record and record["team_id"] is not None and not _nonempty_string(record["team_id"]):
        raise SnapshotValidationError(f"{label} team_id must be a non-empty string when provided")


def _requires_approval(task: dict, employee: dict, policies: dict) -> bool:
    if task["priority"] == "critical" and policies.get("critical_requires_bp", True):
        return True

    task_team = task.get("team_id")
    employee_team = employee.get("team_id")
    same_known_team = task_team is not None and employee_team is not None and task_team == employee_team
    if same_known_team:
        return not policies.get("allow_automatic_same_team", True)
    return policies.get("cross_team_requires_bp", True)


def _normalize_exclusions(exclusions: Any) -> dict[str, set[str]]:
    if not isinstance(exclusions, list):
        raise SnapshotValidationError("exclusions must be a list")
    result: dict[str, set[str]] = {}
    seen: set[tuple[str, str]] = set()
    for item in exclusions:
        if not isinstance(item, dict) or not _nonempty_string(item.get("task_id")) or not _nonempty_string(item.get("employee_id")):
            raise SnapshotValidationError("each exclusion must contain task_id and employee_id strings")
        pair = (item["task_id"], item["employee_id"])
        if pair in seen:
            raise SnapshotValidationError(f"duplicate exclusion for task {pair[0]} and employee {pair[1]}")
        seen.add(pair)
        result.setdefault(item["task_id"], set()).add(item["employee_id"])
    return result


def _skills(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not _nonempty_string(skill) for skill in value):
        raise SnapshotValidationError(f"{label} must be a list of non-empty strings")
    normalized = [skill.strip() for skill in value]
    if len(normalized) != len(set(normalized)):
        raise SnapshotValidationError(f"{label} contains duplicate skills")
    return normalized


def _normalize_policies(policies: dict) -> dict:
    normalized = dict(policies)
    utilization = normalized.get("max_utilization_pct", 90)
    if not _valid_number(utilization) or utilization <= 0 or utilization > 100:
        raise SnapshotValidationError("policies.max_utilization_pct must be greater than 0 and at most 100")
    normalized["max_utilization_pct"] = _clean_number(utilization)

    boolean_fields = ("critical_requires_bp", "cross_team_requires_bp", "allow_automatic_same_team")
    for field in boolean_fields:
        if field in normalized and not isinstance(normalized[field], bool):
            raise SnapshotValidationError(f"policies.{field} must be a boolean")

    integer_fields = ("response_timeout_minutes", "reminder_before_expiry_minutes")
    for field in integer_fields:
        if field in normalized:
            value = normalized[field]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SnapshotValidationError(f"policies.{field} must be a positive integer")
    if (
        "response_timeout_minutes" in normalized
        and "reminder_before_expiry_minutes" in normalized
        and normalized["reminder_before_expiry_minutes"] > normalized["response_timeout_minutes"]
    ):
        raise SnapshotValidationError(
            "policies.reminder_before_expiry_minutes cannot exceed response_timeout_minutes"
        )
    return normalized


def _iso_datetime(value: Any, label: str) -> None:
    if not isinstance(value, str):
        raise SnapshotValidationError(f"{label} must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotValidationError(f"{label} must be an ISO 8601 string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotValidationError(f"{label} must include a timezone")


def _required(data: dict, fields: tuple[str, ...], label: str) -> None:
    missing = [field for field in fields if field not in data]
    if missing:
        raise SnapshotValidationError(f"{label} missing required field(s): {', '.join(missing)}")


def _unique_ids(items: list[dict], field: str, label: str) -> None:
    ids = [item[field] for item in items]
    if len(ids) != len(set(ids)):
        raise SnapshotValidationError(f"duplicate {field} in {label}")


def _uncovered(task: dict, reason_code: str, alternatives: list) -> dict:
    return {"task_id": task["task_id"], "reason_code": reason_code, "alternatives": alternatives}


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _clean_number(value: int | float) -> int | float:
    if isinstance(value, float) and value.is_integer():
        normalized = int(value)
        try:
            if math.isfinite(normalized):
                return normalized
        except OverflowError:
            pass
    return value


def _finite_total(values, message: str) -> float:
    try:
        total = math.fsum(values)
    except OverflowError as exc:
        raise SnapshotValidationError(message) from exc
    if not math.isfinite(total):
        raise SnapshotValidationError(message)
    return total
