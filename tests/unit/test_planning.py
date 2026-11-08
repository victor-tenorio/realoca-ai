from copy import deepcopy

import pytest

from app.engine import plan_coverage, replan_coverage
from app.engine.planning import SnapshotValidationError


@pytest.fixture
def snapshot():
    return {
        "case_id": "case-001",
        "plan_version": 1,
        "absent_employee_ids": ["emp-joao"],
        "tasks": [
            {"task_id": "task-A", "title": "Automação Python", "priority": "high", "estimated_hours": 2,
             "required_skills": ["python"], "team_id": "ops", "due_at": "2026-11-08T10:00:00-03:00", "transfer_allowed": True},
            {"task_id": "task-B", "title": "Relatório Excel", "priority": "high", "estimated_hours": 2,
             "required_skills": ["excel"], "team_id": "ops", "due_at": "2026-11-08T10:00:00-03:00", "transfer_allowed": True},
        ],
        "employees": [
            {"employee_id": "emp-carlos", "team_id": "ops", "skills": ["python", "excel"], "shift_hours": 2,
             "committed_hours": 0, "reserved_hours": 0, "availability": "available"},
            {"employee_id": "emp-pedro", "team_id": "ops", "skills": ["python"], "shift_hours": 2,
             "committed_hours": 0, "reserved_hours": 0, "availability": "available"},
        ],
        "exclusions": [],
        "policies": {"max_utilization_pct": 100},
    }


def test_valid_example_produces_proposals(snapshot):
    result = plan_coverage(snapshot)
    assert result["case_id"] == "case-001"
    assert result["plan_version"] == 1
    assert [(item["task_id"], item["candidate_employee_id"]) for item in result["assignments"]] == [
        ("task-A", "emp-pedro"), ("task-B", "emp-carlos")
    ]
    assert result["uncovered"] == []
    assert result["metrics"] == {"demand_hours": 4, "planned_hours": 4}
    assert all("status" not in item for item in result["assignments"])


def test_missing_field_fails(snapshot):
    del snapshot["case_id"]
    with pytest.raises(SnapshotValidationError, match="case_id"):
        plan_coverage(snapshot)


@pytest.mark.parametrize("field,value", [("case_id", []), ("case_id", " "), ("plan_version", True), ("plan_version", 0)])
def test_invalid_snapshot_identifiers_fail(snapshot, field, value):
    snapshot[field] = value
    with pytest.raises(SnapshotValidationError, match=field):
        plan_coverage(snapshot)


def test_duplicate_ids_fail(snapshot):
    snapshot["tasks"].append(deepcopy(snapshot["tasks"][0]))
    with pytest.raises(SnapshotValidationError, match="duplicate task_id"):
        plan_coverage(snapshot)


@pytest.mark.parametrize("hours", [0, -1, float("nan"), float("inf"), "2"])
def test_invalid_task_hours_fail(snapshot, hours):
    snapshot["tasks"][0]["estimated_hours"] = hours
    with pytest.raises(SnapshotValidationError, match="estimated_hours"):
        plan_coverage(snapshot)


@pytest.mark.parametrize("field,value", [
    ("shift_hours", 0), ("shift_hours", float("inf")),
    ("committed_hours", -1), ("committed_hours", float("nan")),
    ("reserved_hours", -1), ("reserved_hours", float("inf")),
])
def test_invalid_employee_hours_fail(snapshot, field, value):
    snapshot["employees"][0][field] = value
    with pytest.raises(SnapshotValidationError, match=field):
        plan_coverage(snapshot)


def test_extreme_finite_hours_cannot_overflow_totals(snapshot):
    snapshot["tasks"][0]["estimated_hours"] = 1e308
    snapshot["tasks"][1]["estimated_hours"] = 1e308
    with pytest.raises(SnapshotValidationError, match="total estimated_hours"):
        plan_coverage(snapshot)


def test_extreme_employee_hours_cannot_overflow_occupied_total(snapshot):
    snapshot["employees"][0]["committed_hours"] = 1e308
    snapshot["employees"][0]["reserved_hours"] = 1e308
    with pytest.raises(SnapshotValidationError, match="combined committed and reserved"):
        plan_coverage(snapshot)


def test_malformed_skills_fail(snapshot):
    snapshot["employees"][0]["skills"] = "python,excel"
    with pytest.raises(SnapshotValidationError, match="skills"):
        plan_coverage(snapshot)


@pytest.mark.parametrize("skills", [None, ["python", ""], [" python", "python"], [1]])
def test_invalid_skill_values_fail(snapshot, skills):
    snapshot["tasks"][0]["required_skills"] = skills
    with pytest.raises(SnapshotValidationError, match="required_skills"):
        plan_coverage(snapshot)


def test_absent_employee_is_never_a_candidate(snapshot):
    snapshot["employees"].append(
        {"employee_id": "emp-joao", "team_id": "ops", "skills": ["python", "excel"], "shift_hours": 8,
         "committed_hours": 0, "reserved_hours": 0, "availability": "available"}
    )
    result = plan_coverage(snapshot)
    assert all(item["candidate_employee_id"] != "emp-joao" for item in result["assignments"])


@pytest.mark.parametrize("availability", [None, [], "on_leave", "Available"])
def test_invalid_availability_fails(snapshot, availability):
    snapshot["employees"][0]["availability"] = availability
    with pytest.raises(SnapshotValidationError, match="availability"):
        plan_coverage(snapshot)


@pytest.mark.parametrize("due_at", [None, "2026-11-08T10:00:00", "not-a-date", 123])
def test_missing_or_invalid_timezone_fails(snapshot, due_at):
    snapshot["tasks"][0]["due_at"] = due_at
    with pytest.raises(SnapshotValidationError, match="due_at"):
        plan_coverage(snapshot)


def test_due_at_accepts_utc_z(snapshot):
    snapshot["tasks"][0]["due_at"] = "2026-11-08T13:00:00Z"
    assert plan_coverage(snapshot)["assignments"]


def test_missing_due_at_fails(snapshot):
    del snapshot["tasks"][0]["due_at"]
    with pytest.raises(SnapshotValidationError, match="due_at"):
        plan_coverage(snapshot)


def test_duplicate_employee_ids_fail(snapshot):
    snapshot["employees"].append(deepcopy(snapshot["employees"][0]))
    with pytest.raises(SnapshotValidationError, match="duplicate employee_id"):
        plan_coverage(snapshot)


@pytest.mark.parametrize("exclusions", [
    "emp-carlos",
    [{"task_id": "task-A"}],
    [{"task_id": "task-unknown", "employee_id": "emp-carlos"}],
    [{"task_id": "task-A", "employee_id": "emp-unknown"}],
    [{"task_id": "task-A", "employee_id": "emp-carlos"},
     {"task_id": "task-A", "employee_id": "emp-carlos"}],
])
def test_invalid_exclusions_fail(snapshot, exclusions):
    snapshot["exclusions"] = exclusions
    with pytest.raises(SnapshotValidationError, match="exclusion"):
        plan_coverage(snapshot)


def test_valid_exclusion_removes_candidate(snapshot):
    snapshot["exclusions"] = [{"task_id": "task-A", "employee_id": "emp-pedro"}]
    result = plan_coverage(snapshot)
    assert next(item for item in result["assignments"] if item["task_id"] == "task-A")["candidate_employee_id"] == "emp-carlos"


@pytest.mark.parametrize("policies", [
    {"max_utilization_pct": 0},
    {"max_utilization_pct": 101},
    {"max_utilization_pct": float("nan")},
    {"critical_requires_bp": 1},
    {"cross_team_requires_bp": "true"},
    {"allow_automatic_same_team": None},
    {"response_timeout_minutes": 0},
    {"response_timeout_minutes": 1.5},
    {"reminder_before_expiry_minutes": 20, "response_timeout_minutes": 15},
])
def test_invalid_policies_fail(snapshot, policies):
    snapshot["policies"] = policies
    with pytest.raises(SnapshotValidationError, match="policies"):
        plan_coverage(snapshot)


def test_policy_defaults_are_used_without_mutating_input(snapshot):
    del snapshot["policies"]
    before = deepcopy(snapshot)
    result = plan_coverage(snapshot)
    assert result["metrics"]["planned_hours"] == 0
    assert snapshot == before


def test_planning_is_deterministic(snapshot):
    assert plan_coverage(snapshot) == plan_coverage(snapshot)
    assert replan_coverage(snapshot) == plan_coverage(snapshot)


def test_input_is_immutable(snapshot):
    before = deepcopy(snapshot)
    plan_coverage(snapshot)
    assert snapshot == before
