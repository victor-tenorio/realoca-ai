"""Deterministic, side-effect-free coverage proposal generation.

This engine validates and prioritizes deterministically, then searches for a
joint feasible assignment. Search is bounded for predictable runtime.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
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
    utilization = _as_decimal(data["policies"]["max_utilization_pct"])
    zero = Decimal("0")

    remaining = {
        employee_id: max(zero, _effective_capacity(employee, utilization)
                         - _as_decimal(employee["committed_hours"])
                         - _as_decimal(employee["reserved_hours"]))
        for employee_id, employee in employees.items()
    }
    # Completed work is retained in the validated snapshot but is not part of
    # current planning demand and must not be reported as an uncovered task.
    tasks = sorted(
        (task for task in data["tasks"] if task.get("status") != "done"),
        key=lambda task: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}[task["priority"]],
            _iso_datetime(task["due_at"], f"task {task['task_id']} due_at"),
            task["task_id"],
        ),
    )
    options: list[list[str]] = []
    uncovered_reasons: dict[str, str] = {}
    flexibility = {
        employee_id: sum(
            1 for task in tasks
            if set(task["required_skills"]).issubset(employee["skills"])
        )
        for employee_id, employee in employees.items()
    }
    for task in tasks:
        task_options, reason_code = _candidate_options(
            task, employees, absent, exclusions, data["policies"], remaining
        )
        options.append(sorted(task_options, key=lambda eid: (flexibility[eid], eid)))
        if reason_code:
            uncovered_reasons[task["task_id"]] = reason_code

    selected, _ = _joint_assignment(tasks, options, employees, remaining, data["policies"])
    assignments: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []
    for task, candidate_id in zip(tasks, selected):
        if candidate_id is None:
            reason_code = uncovered_reasons.get(task["task_id"], "INSUFFICIENT_CAPACITY")
            uncovered.append(_uncovered(task, reason_code, []))
            continue
        employee = employees[candidate_id]
        approval_note = _approval_explanation(task, employee, data["policies"])
        free_capacity = remaining[candidate_id]
        skills = ", ".join(task["required_skills"])
        team_note = _team_explanation(task, employee)
        reason = (
            f"Prioridade {task['priority']}; prazo {task['due_at']}; "
            f"competências exigidas atendidas ({skills}); estimativa de "
            f"{_clean_number(task['estimated_hours'])}h cabe na capacidade livre "
            f"de {_clean_decimal(free_capacity)}h antes do plano"
            f"{team_note}{approval_note}; proposta do planejador"
        )
        assignments.append({
            "task_id": task["task_id"],
            "candidate_employee_id": candidate_id,
            "estimated_hours": task["estimated_hours"],
            "reason": reason,
        })

    demand_hours = sum(task["estimated_hours"] for task in tasks)
    planned_hours = sum(item["estimated_hours"] for item in assignments)
    return {
        "case_id": data["case_id"],
        "plan_version": data["plan_version"],
        "assignments": assignments,
        "uncovered": uncovered,
        "metrics": {"demand_hours": _clean_number(demand_hours), "planned_hours": _clean_number(planned_hours)},
    }


_SEARCH_NODE_LIMIT = 50_000


def _candidate_options(task, employees, absent, exclusions, policies, remaining):
    if not task["transfer_allowed"]:
        return [], "TRANSFER_NOT_ALLOWED"
    available = [
        (employee_id, employee) for employee_id, employee in employees.items()
        if employee_id not in absent and employee["availability"] == "available"
    ]
    if not available:
        return [], "NO_AVAILABLE_CANDIDATE"
    skilled = [
        (employee_id, employee) for employee_id, employee in available
        if set(task["required_skills"]).issubset(employee["skills"])
    ]
    if not skilled:
        return [], "NO_SKILL_MATCH"
    eligible = [
        employee_id for employee_id, employee in skilled
        if employee_id not in exclusions.get(task["task_id"], set())
    ]
    if not eligible:
        return [], "ALL_CANDIDATES_EXCLUDED"
    # Keep candidates with less than this task's hours out of the search. The
    # solver still accounts for contention between individually feasible tasks.
    task_hours = _as_decimal(task["estimated_hours"])
    eligible = [employee_id for employee_id in eligible if remaining[employee_id] >= task_hours]
    if not eligible:
        return [], "INSUFFICIENT_CAPACITY"
    return eligible, ""


def _joint_assignment(tasks, options, employees, initial_remaining, policies):
    """Bounded deterministic DFS; returns a feasible incumbent if capped."""
    remaining = dict(initial_remaining)
    # Always start with a valid feasible plan. If the node budget is reached
    # before DFS finds a better one, the returned incumbent still respects
    # skills and capacity and never invents a candidate.
    best: list[str | None] = [None] * len(tasks)
    greedy_remaining = dict(initial_remaining)
    for index, task in enumerate(tasks):
        hours = _as_decimal(task["estimated_hours"])
        candidate_id = next(
            (employee_id for employee_id in options[index]
             if greedy_remaining[employee_id] >= hours),
            None,
        )
        best[index] = candidate_id
        if candidate_id is not None:
            greedy_remaining[candidate_id] -= hours
    best_score = _assignment_score(best, tasks, employees, initial_remaining, policies)
    current: list[str | None] = [None] * len(tasks)
    nodes = 0

    def visit(index: int) -> None:
        nonlocal nodes, best, best_score
        if nodes >= _SEARCH_NODE_LIMIT:
            return
        nodes += 1
        if index == len(tasks):
            score = _assignment_score(current, tasks, employees, initial_remaining, policies)
            if score > best_score:
                best, best_score = list(current), score
            return
        task = tasks[index]
        hours = _as_decimal(task["estimated_hours"])
        # Candidate order is stable and favors constrained employees first.
        for employee_id in options[index]:
            if remaining[employee_id] < hours:
                continue
            current[index] = employee_id
            remaining[employee_id] -= hours
            visit(index + 1)
            remaining[employee_id] += hours
            current[index] = None
        visit(index + 1)

    visit(0)
    return best, nodes < _SEARCH_NODE_LIMIT


def _assignment_score(assignment, tasks, employees, initial_remaining, policies):
    covered_by_priority = tuple(
        sum(
            1 for task, employee_id in zip(tasks, assignment)
            if task["priority"] == priority and employee_id is not None
        )
        for priority in ("critical", "high", "medium", "low")
    )
    covered_in_task_order = tuple(1 if employee_id is not None else 0 for employee_id in assignment)
    hours = sum((_as_decimal(task["estimated_hours"]) for task, eid in zip(tasks, assignment) if eid), Decimal("0"))
    approvals = sum(
        1 for task, eid in zip(tasks, assignment)
        if eid is not None and _requires_approval(task, employees[eid], policies)
    )
    loads = {eid: initial_remaining[eid] for eid in employees}
    for task, eid in zip(tasks, assignment):
        if eid is not None:
            loads[eid] -= _as_decimal(task["estimated_hours"])
    utilization = []
    for eid in sorted(employees):
        employee = employees[eid]
        capacity = _effective_capacity(employee, _as_decimal(policies["max_utilization_pct"]))
        if capacity > 0:
            utilization.append(((capacity - loads[eid]) / capacity) ** 2)
    # Minimize the spread proxy and number of recipient employees after the
    # higher-order coverage and approval criteria. Assignment tuple gives a
    # stable final tie-break (IDs lexically smaller are preferred).
    balance = -sum(utilization, Decimal("0"))
    recipients = -len({eid for eid in assignment if eid is not None})
    # Tasks were sorted by priority, due instant and ID. Prefer coverage of
    # earlier tasks only after the higher-level objective tuple is tied.
    tie = tuple("~" if eid is None else eid for eid in assignment)
    inverse_tie = tuple(
        "".join(chr(0x10ffff - ord(char)) for char in employee_id)
        for employee_id in tie
    )
    return covered_by_priority, covered_in_task_order, hours, -approvals, balance, recipients, inverse_tie


def _approval_explanation(task, employee, policies):
    if not _requires_approval(task, employee, policies):
        return "; política permite proposta sem aprovação"
    if task["priority"] == "critical" and policies.get("critical_requires_bp", True):
        return "; prioridade critical exige aprovação BP"
    if _team_explanation(task, employee):
        return "; política exige aprovação BP para atuação na mesma equipe"
    return "; política exige aprovação BP para atuação entre equipes ou equipe não informada"


def _team_explanation(task, employee):
    task_team, employee_team = task.get("team_id"), employee.get("team_id")
    if task_team is None or employee_team is None:
        return "; equipe de origem ou do candidato não informada"
    if task_team == employee_team:
        return "; mesma equipe"
    return f"; atuação entre equipes ({employee_team} para {task_team})"


def _clean_decimal(value):
    return _clean_number(float(value)) if value.adjusted() < 300 else str(value)


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


def _as_decimal(value: int | float) -> Decimal:
    """Use decimal string conversion to match persisted Decimal hour values."""
    return Decimal(str(value))


def _effective_capacity(employee: dict, utilization_pct: Decimal) -> Decimal:
    return _as_decimal(employee["shift_hours"]) * utilization_pct / Decimal("100")


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


def _iso_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise SnapshotValidationError(f"{label} must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotValidationError(f"{label} must be an ISO 8601 string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotValidationError(f"{label} must include a timezone")
    return parsed


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
