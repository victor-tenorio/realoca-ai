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


def test_duplicate_ids_fail(snapshot):
    snapshot["tasks"].append(deepcopy(snapshot["tasks"][0]))
    with pytest.raises(SnapshotValidationError, match="duplicate task_id"):
        plan_coverage(snapshot)


@pytest.mark.parametrize("hours", [0, -1, float("nan"), float("inf"), "2"])
def test_invalid_task_hours_fail(snapshot, hours):
    snapshot["tasks"][0]["estimated_hours"] = hours
    with pytest.raises(SnapshotValidationError, match="estimated_hours"):
        plan_coverage(snapshot)


def test_malformed_skills_fail(snapshot):
    snapshot["employees"][0]["skills"] = "python,excel"
    with pytest.raises(SnapshotValidationError, match="skills"):
        plan_coverage(snapshot)


def test_absent_employee_is_never_a_candidate(snapshot):
    snapshot["employees"].append(
        {"employee_id": "emp-joao", "team_id": "ops", "skills": ["python", "excel"], "shift_hours": 8,
         "committed_hours": 0, "reserved_hours": 0, "availability": "available"}
    )
    result = plan_coverage(snapshot)
    assert all(item["candidate_employee_id"] != "emp-joao" for item in result["assignments"])


def test_planning_is_deterministic(snapshot):
    assert plan_coverage(snapshot) == plan_coverage(snapshot)
    assert replan_coverage(snapshot) == plan_coverage(snapshot)


def test_input_is_immutable(snapshot):
    before = deepcopy(snapshot)
    plan_coverage(snapshot)
    assert snapshot == before
