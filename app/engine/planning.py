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
            employee["shift_hours"] * utilization / 100
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

        candidates = []
        for employee_id, employee in employees.items():
            if employee_id in absent or employee["availability"] != "available":
                continue
            if not set(task["required_skills"]).issubset(employee["skills"]):
                continue
            if employee_id in exclusions.get(task["task_id"], set()):
                continue
            if remaining[employee_id] + 1e-9 < task["estimated_hours"]:
                continue
            # Prefer the least flexible eligible employee, then lower current
            # utilization and stable employee ID as deterministic tie-breakers.
            flexibility = sum(
                1
                for other in tasks
                if set(other["required_skills"]).issubset(employee["skills"])
            )
            used = (
                employee["committed_hours"]
                + employee["reserved_hours"]
                + (employee["shift_hours"] * utilization / 100 - remaining[employee_id])
            )
            candidates.append((flexibility, used, employee_id))

        candidates.sort()
        if not candidates:
            uncovered.append(_uncovered(task, "NO_ELIGIBLE_CANDIDATE", []))
            continue

        candidate_id = candidates[0][2]
        remaining[candidate_id] -= task["estimated_hours"]
        skills = ", ".join(task["required_skills"])
        assignments.append(
            {
                "task_id": task["task_id"],
                "candidate_employee_id": candidate_id,
                "estimated_hours": task["estimated_hours"],
                "reason": f"Competências disponíveis ({skills}); capacidade elegível",
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
    task_ids = {task["task_id"] for task in data["tasks"]}
    missing_exclusions = set(_normalize_exclusions(data.get("exclusions", []))) - task_ids
    if missing_exclusions:
        raise SnapshotValidationError(f"exclusion references unknown task: {', '.join(sorted(missing_exclusions))}")
    policies = data.get("policies", {})
    if not isinstance(policies, dict):
        raise SnapshotValidationError("policies must be a dict")
    utilization = policies.get("max_utilization_pct", 90)
    if not _valid_number(utilization) or utilization <= 0 or utilization > 100:
        raise SnapshotValidationError("policies.max_utilization_pct must be greater than 0 and at most 100")
    data["policies"] = {**policies, "max_utilization_pct": utilization}
    data["exclusions"] = data.get("exclusions", [])
    return data


def _normalize_task(task: Any) -> dict:
    if not isinstance(task, dict):
        raise SnapshotValidationError("each task must be a dict")
    task = deepcopy(task)
    _required(task, ("task_id", "priority", "estimated_hours", "required_skills", "transfer_allowed"), "task")
    if not _nonempty_string(task["task_id"]):
        raise SnapshotValidationError("task_id must be a non-empty string")
    if task["priority"] not in {"critical", "high", "medium", "low"}:
        raise SnapshotValidationError(f"invalid priority for task {task['task_id']}")
    if not _valid_number(task["estimated_hours"]) or task["estimated_hours"] <= 0:
        raise SnapshotValidationError(f"estimated_hours must be positive and finite for task {task['task_id']}")
    task["estimated_hours"] = _clean_number(task["estimated_hours"])
    _skills(task["required_skills"], f"task {task['task_id']} required_skills")
    if not isinstance(task["transfer_allowed"], bool):
        raise SnapshotValidationError(f"transfer_allowed must be boolean for task {task['task_id']}")
    if "due_at" in task:
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
    _skills(employee["skills"], f"employee {employee['employee_id']} skills")
    if not _valid_number(employee["shift_hours"]) or employee["shift_hours"] <= 0:
        raise SnapshotValidationError(f"shift_hours must be positive and finite for employee {employee['employee_id']}")
    for field in ("committed_hours", "reserved_hours"):
        if not _valid_number(employee[field]) or employee[field] < 0:
            raise SnapshotValidationError(f"{field} must be non-negative and finite for employee {employee['employee_id']}")
        employee[field] = _clean_number(employee[field])
    employee["shift_hours"] = _clean_number(employee["shift_hours"])
    if employee["availability"] not in {"available", "absent", "unavailable"}:
        raise SnapshotValidationError(f"invalid availability for employee {employee['employee_id']}")
    return employee


def _normalize_exclusions(exclusions: Any) -> dict[str, set[str]]:
    if not isinstance(exclusions, list):
        raise SnapshotValidationError("exclusions must be a list")
    result: dict[str, set[str]] = {}
    for item in exclusions:
        if not isinstance(item, dict) or not _nonempty_string(item.get("task_id")) or not _nonempty_string(item.get("employee_id")):
            raise SnapshotValidationError("each exclusion must contain task_id and employee_id strings")
        result.setdefault(item["task_id"], set()).add(item["employee_id"])
    return result


def _skills(value: Any, label: str) -> None:
    if not isinstance(value, list) or any(not _nonempty_string(skill) for skill in value):
        raise SnapshotValidationError(f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise SnapshotValidationError(f"{label} contains duplicate skills")


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
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _clean_number(value: int | float) -> int | float:
    return int(value) if isinstance(value, float) and value.is_integer() else value
