from copy import deepcopy
from decimal import Decimal
import math

import pytest

from app.engine import plan_coverage, replan_coverage
from app.engine import planning as planning_module
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


def test_higher_priority_precedes_nearer_deadline(snapshot):
    snapshot["tasks"][0]["priority"] = "low"
    snapshot["tasks"][0]["due_at"] = "2026-11-08T09:00:00-03:00"
    snapshot["tasks"][1]["priority"] = "critical"
    snapshot["tasks"][1]["due_at"] = "2026-11-09T09:00:00-03:00"
    result = plan_coverage(snapshot)
    assert [item["task_id"] for item in result["assignments"]] == ["task-B", "task-A"]


def test_nearer_deadline_precedes_within_same_priority(snapshot):
    snapshot["tasks"][0]["due_at"] = "2026-11-08T10:00:00-03:00"
    snapshot["tasks"][1]["due_at"] = "2026-11-08T09:00:00-03:00"
    result = plan_coverage(snapshot)
    assert [item["task_id"] for item in result["assignments"]] == ["task-B", "task-A"]


def test_equivalent_instants_with_different_offsets_tie_by_task_id(snapshot):
    snapshot["tasks"][0]["due_at"] = "2026-11-08T10:00:00-03:00"
    snapshot["tasks"][1]["due_at"] = "2026-11-08T13:00:00Z"
    result = plan_coverage(snapshot)
    assert [item["task_id"] for item in result["assignments"]] == ["task-A", "task-B"]


def test_equal_priority_and_deadline_tie_by_task_id_not_input_order(snapshot):
    snapshot["tasks"][1]["due_at"] = snapshot["tasks"][0]["due_at"]
    snapshot["tasks"].reverse()
    result = plan_coverage(snapshot)
    assert [item["task_id"] for item in result["assignments"]] == ["task-A", "task-B"]


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


@pytest.mark.parametrize("availability", ["absent", "unavailable"])
def test_absent_or_unavailable_employees_are_not_eligible(snapshot, availability):
    snapshot["absent_employee_ids"] = []
    snapshot["employees"] = [snapshot["employees"][0]]
    snapshot["employees"][0]["availability"] = availability
    result = plan_coverage(snapshot)
    assert result["assignments"] == []
    assert result["uncovered"][0]["reason_code"] == "NO_AVAILABLE_CANDIDATE"


def test_missing_required_skill_produces_uncovered(snapshot):
    snapshot["employees"] = [snapshot["employees"][1]]
    result = plan_coverage(snapshot)
    assert not any(item["task_id"] == "task-B" for item in result["assignments"])
    uncovered = {item["task_id"]: item["reason_code"] for item in result["uncovered"]}
    assert uncovered["task-B"] == "NO_SKILL_MATCH"


def test_transfer_disallowed_task_is_uncovered(snapshot):
    snapshot["tasks"][0]["transfer_allowed"] = False
    result = plan_coverage(snapshot)
    assert result["uncovered"][0] == {
        "task_id": "task-A", "reason_code": "TRANSFER_NOT_ALLOWED", "alternatives": []
    }


def test_all_excluded_candidates_leave_task_uncovered(snapshot):
    snapshot["exclusions"] = [
        {"task_id": "task-A", "employee_id": "emp-carlos"},
        {"task_id": "task-A", "employee_id": "emp-pedro"},
    ]
    result = plan_coverage(snapshot)
    uncovered = {item["task_id"]: item["reason_code"] for item in result["uncovered"]}
    assert uncovered["task-A"] == "ALL_CANDIDATES_EXCLUDED"


def test_completed_task_is_excluded_from_proposals_uncovered_and_demand(snapshot):
    snapshot["tasks"][0]["status"] = "done"
    snapshot["tasks"][0]["transfer_allowed"] = False
    result = plan_coverage(snapshot)
    assert [item["task_id"] for item in result["assignments"]] == ["task-B"]
    assert all(item["task_id"] != "task-A" for item in result["uncovered"])
    assert result["metrics"]["demand_hours"] == 2


def test_active_non_transferable_task_remains_in_demand_and_uncovered(snapshot):
    snapshot["tasks"][0]["transfer_allowed"] = False
    result = plan_coverage(snapshot)
    assert any(item["task_id"] == "task-A" for item in result["uncovered"])
    assert result["uncovered"][0]["reason_code"] == "TRANSFER_NOT_ALLOWED"
    assert result["metrics"]["demand_hours"] == 4


@pytest.mark.parametrize("status", [None, [], "pending"])
def test_invalid_task_status_fails(snapshot, status):
    snapshot["tasks"][0]["status"] = status
    with pytest.raises(SnapshotValidationError, match="status"):
        plan_coverage(snapshot)


@pytest.mark.parametrize("record", ["task", "employee"])
def test_malformed_explicit_team_id_fails(snapshot, record):
    collection = "tasks" if record == "task" else "employees"
    snapshot[collection][0]["team_id"] = []
    with pytest.raises(SnapshotValidationError, match="team_id"):
        plan_coverage(snapshot)


def test_global_coverage_can_prefer_approval_required_candidate(snapshot):
    snapshot["employees"][1]["team_id"] = "other-team"
    result = plan_coverage(snapshot)
    first_task = next(item for item in result["assignments"] if item["task_id"] == "task-A")
    # Global coverage keeps Carlos for the Excel-only task, so Python is
    # proposed to Pedro even though the cross-team policy requires BP review.
    assert first_task["candidate_employee_id"] == "emp-pedro"
    assert "aprovação BP" in first_task["reason"]


def test_cross_team_candidate_remains_proposal_and_is_marked_for_approval(snapshot):
    snapshot["employees"] = [snapshot["employees"][1]]
    snapshot["employees"][0]["team_id"] = "other-team"
    result = plan_coverage(snapshot)
    proposed = next(item for item in result["assignments"] if item["task_id"] == "task-A")
    assert proposed["candidate_employee_id"] == "emp-pedro"
    assert "aprovação BP" in proposed["reason"]
    assert "status" not in proposed


def test_critical_requires_bp_is_reflected_without_claiming_acceptance(snapshot):
    snapshot["tasks"][0]["priority"] = "critical"
    result = plan_coverage(snapshot)
    proposed = next(item for item in result["assignments"] if item["task_id"] == "task-A")
    assert "aprovação BP" in proposed["reason"]
    assert "status" not in proposed


def test_same_team_automatic_policy_can_require_bp(snapshot):
    snapshot["policies"]["allow_automatic_same_team"] = False
    result = plan_coverage(snapshot)
    proposed = next(item for item in result["assignments"] if item["task_id"] == "task-A")
    assert "aprovação BP" in proposed["reason"]


def test_cross_team_without_bp_requirement_is_not_marked_for_approval(snapshot):
    snapshot["employees"][1]["team_id"] = "other-team"
    snapshot["employees"] = [snapshot["employees"][1]]
    snapshot["policies"]["cross_team_requires_bp"] = False
    result = plan_coverage(snapshot)
    proposed = next(item for item in result["assignments"] if item["task_id"] == "task-A")
    assert "política permite proposta sem aprovação" in proposed["reason"]


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


def _one_candidate_snapshot(snapshot, *, shift_hours, committed_hours, reserved_hours, task_hours):
    snapshot["tasks"] = [deepcopy(snapshot["tasks"][0])]
    snapshot["tasks"][0]["estimated_hours"] = task_hours
    snapshot["employees"] = [deepcopy(snapshot["employees"][0])]
    snapshot["employees"][0].update(
        shift_hours=shift_hours,
        committed_hours=committed_hours,
        reserved_hours=reserved_hours,
    )
    snapshot["absent_employee_ids"] = []
    return snapshot


def test_capacity_uses_ninety_percent_utilization(snapshot):
    _one_candidate_snapshot(
        snapshot, shift_hours=8, committed_hours=2, reserved_hours=1.2, task_hours=4
    )
    snapshot["policies"]["max_utilization_pct"] = 90
    result = plan_coverage(snapshot)
    assert len(result["assignments"]) == 1
    assert result["metrics"]["planned_hours"] == 4


def test_committed_and_reserved_hours_are_each_subtracted_once(snapshot):
    _one_candidate_snapshot(
        snapshot, shift_hours=10, committed_hours=2, reserved_hours=1, task_hours=6
    )
    snapshot["policies"]["max_utilization_pct"] = 90
    result = plan_coverage(snapshot)
    assert len(result["assignments"]) == 1
    assert result["metrics"]["planned_hours"] == 6


def test_employee_at_capacity_has_zero_available_hours(snapshot):
    _one_candidate_snapshot(
        snapshot, shift_hours=8, committed_hours=7.2, reserved_hours=0, task_hours=0.1
    )
    snapshot["policies"]["max_utilization_pct"] = 90
    result = plan_coverage(snapshot)
    assert result["assignments"] == []
    assert result["uncovered"][0]["reason_code"] == "INSUFFICIENT_CAPACITY"


def test_existing_load_above_limit_still_has_zero_available_capacity(snapshot):
    _one_candidate_snapshot(
        snapshot, shift_hours=8, committed_hours=8, reserved_hours=1, task_hours=0.1
    )
    snapshot["policies"]["max_utilization_pct"] = 90
    result = plan_coverage(snapshot)
    assert result["assignments"] == []
    assert result["uncovered"][0]["reason_code"] == "INSUFFICIENT_CAPACITY"


def test_multiple_tasks_cannot_overconsume_candidate_capacity(snapshot):
    _one_candidate_snapshot(
        snapshot, shift_hours=4, committed_hours=0, reserved_hours=0, task_hours=3
    )
    snapshot["tasks"].append(deepcopy(snapshot["tasks"][0]))
    snapshot["tasks"][1]["task_id"] = "task-C"
    snapshot["policies"]["max_utilization_pct"] = 100
    result = plan_coverage(snapshot)
    assert [item["task_id"] for item in result["assignments"]] == ["task-A"]
    assert result["uncovered"] == [
        {"task_id": "task-C", "reason_code": "INSUFFICIENT_CAPACITY", "alternatives": []}
    ]
    assert result["metrics"]["planned_hours"] == 3


def test_task_equal_to_remaining_capacity_is_eligible(snapshot):
    _one_candidate_snapshot(
        snapshot, shift_hours=10, committed_hours=0, reserved_hours=0, task_hours=9
    )
    snapshot["policies"]["max_utilization_pct"] = 90
    result = plan_coverage(snapshot)
    assert len(result["assignments"]) == 1
    assert result["uncovered"] == []


def test_replanning_uses_updated_reservations_without_mutating_snapshot(snapshot):
    _one_candidate_snapshot(
        snapshot, shift_hours=10, committed_hours=0, reserved_hours=0, task_hours=2
    )
    snapshot["policies"]["max_utilization_pct"] = 100
    first_plan = plan_coverage(snapshot)
    assert len(first_plan["assignments"]) == 1

    replanning_snapshot = deepcopy(snapshot)
    replanning_snapshot["employees"][0]["reserved_hours"] = 8.5
    before = deepcopy(replanning_snapshot)
    replanned = replan_coverage(replanning_snapshot)
    assert replanned["assignments"] == []
    assert replanned["uncovered"][0]["reason_code"] == "INSUFFICIENT_CAPACITY"
    assert replanning_snapshot == before


def test_extreme_finite_capacities_do_not_overflow(snapshot):
    _one_candidate_snapshot(
        snapshot, shift_hours=1e308, committed_hours=1e308, reserved_hours=0, task_hours=1
    )
    snapshot["policies"]["max_utilization_pct"] = 100
    result = plan_coverage(snapshot)
    assert result["assignments"] == []
    assert result["metrics"]["demand_hours"] == 1


def test_planning_is_deterministic(snapshot):
    assert plan_coverage(snapshot) == plan_coverage(snapshot)
    assert replan_coverage(snapshot) == plan_coverage(snapshot)


def test_input_is_immutable(snapshot):
    before = deepcopy(snapshot)
    plan_coverage(snapshot)
    assert snapshot == before


def test_global_search_finds_feasible_combination_missed_by_greedy(snapshot):
    task_template = deepcopy(snapshot["tasks"][0])
    snapshot["tasks"] = []
    for task_id, hours in (("task-A", 2), ("task-B", 2), ("task-C", 3)):
        task = deepcopy(task_template)
        task.update(task_id=task_id, estimated_hours=hours, priority="high")
        snapshot["tasks"].append(task)
    snapshot["employees"] = [
        {"employee_id": "emp-1", "team_id": "ops", "skills": ["python"], "shift_hours": 3,
         "committed_hours": 0, "reserved_hours": 0, "availability": "available"},
        {"employee_id": "emp-2", "team_id": "ops", "skills": ["python"], "shift_hours": 4,
         "committed_hours": 0, "reserved_hours": 0, "availability": "available"},
    ]
    snapshot["absent_employee_ids"] = []
    snapshot["policies"]["max_utilization_pct"] = 100

    result = plan_coverage(snapshot)

    assert len(result["assignments"]) == 3
    assert result["uncovered"] == []
    assert result["metrics"]["planned_hours"] == 7


def test_optimizer_reduces_approval_required_proposals_after_coverage(snapshot):
    snapshot["employees"][0]["team_id"] = "different-team"
    snapshot["employees"][1]["team_id"] = "ops"
    snapshot["tasks"] = [deepcopy(snapshot["tasks"][0])]

    proposed = plan_coverage(snapshot)["assignments"][0]

    assert proposed["candidate_employee_id"] == "emp-pedro"
    assert "mesma equipe" in proposed["reason"]
    assert "aprovação BP" not in proposed["reason"]


def test_assignment_explanation_uses_snapshot_evidence(snapshot):
    snapshot["tasks"] = [deepcopy(snapshot["tasks"][0])]
    result = plan_coverage(snapshot)
    explanation = result["assignments"][0]["reason"]

    assert "Prioridade high" in explanation
    assert "prazo 2026-11-08T10:00:00-03:00" in explanation
    assert "python" in explanation
    assert "2h" in explanation
    assert "capacidade livre" in explanation
    assert "proposta" in explanation
    assert "aceita" not in explanation


def test_replanning_exclusion_is_scoped_to_task_and_uses_updated_snapshot(snapshot):
    snapshot["tasks"] = [deepcopy(snapshot["tasks"][0]), deepcopy(snapshot["tasks"][0])]
    snapshot["tasks"][1]["task_id"] = "task-C"
    snapshot["exclusions"] = [{"task_id": "task-A", "employee_id": "emp-pedro"}]
    snapshot["employees"][1]["shift_hours"] = 4
    snapshot["policies"]["max_utilization_pct"] = 100
    before = deepcopy(snapshot)

    result = replan_coverage(snapshot)

    assert {item["task_id"]: item["candidate_employee_id"] for item in result["assignments"]} == {
        "task-A": "emp-carlos", "task-C": "emp-pedro"
    }
    assert snapshot == before


def test_optimizer_output_remains_deterministic_and_input_immutable(snapshot):
    before = deepcopy(snapshot)

    assert plan_coverage(snapshot) == plan_coverage(snapshot)
    assert replan_coverage(snapshot) == plan_coverage(snapshot)
    assert snapshot == before


def test_optimizer_is_independent_of_employee_input_order(snapshot):
    forward = plan_coverage(snapshot)
    snapshot["employees"].reverse()

    assert plan_coverage(snapshot) == forward


def test_python_excel_global_trap_is_stable_for_plan_and_replan(snapshot):
    before = deepcopy(snapshot)

    expected = {"task-A": "emp-pedro", "task-B": "emp-carlos"}
    result = plan_coverage(snapshot)
    assert {item["task_id"]: item["candidate_employee_id"] for item in result["assignments"]} == expected
    assert result["metrics"]["planned_hours"] == 4
    _assert_planner_invariants(snapshot, result)

    reordered = deepcopy(snapshot)
    reordered["employees"].reverse()
    reordered["tasks"].reverse()
    assert plan_coverage(reordered) == result
    assert replan_coverage(reordered) == result
    assert snapshot == before


def _three_absence_snapshot(snapshot):
    template = deepcopy(snapshot["tasks"][0])
    specifications = [
        ("task-critical-python", "emp-ana", "critical", 2, ["python"], "2026-11-08T09:00:00-03:00"),
        ("task-high-excel", "emp-bruno", "high", 1.5, ["excel"], "2026-11-08T10:00:00-03:00"),
        ("task-high-python", "emp-clara", "high", 2, ["python"], "2026-11-08T11:00:00-03:00"),
        ("task-medium-python", "emp-ana", "medium", 3, ["python"], "2026-11-08T12:00:00-03:00"),
        ("task-medium-sql", "emp-bruno", "medium", 1, ["sql"], "2026-11-08T13:00:00-03:00"),
    ]
    tasks = []
    for task_id, assignee, priority, hours, skills, due_at in specifications:
        task = deepcopy(template)
        task.update(
            task_id=task_id, assignee_employee_id=assignee,
            priority=priority, estimated_hours=hours,
            required_skills=skills, due_at=due_at,
            team_id={"emp-ana": "ops", "emp-bruno": "finance", "emp-clara": "data"}[assignee],
        )
        tasks.append(task)
    return {
        "case_id": "case-three-absences",
        "plan_version": 7,
        "absent_employee_ids": ["emp-ana", "emp-bruno", "emp-clara"],
        "tasks": tasks,
        "employees": [
            {"employee_id": "emp-ana", "team_id": "ops", "skills": ["python"], "shift_hours": 8,
             "committed_hours": 0, "reserved_hours": 0, "availability": "absent"},
            {"employee_id": "emp-bruno", "team_id": "finance", "skills": ["excel"], "shift_hours": 8,
             "committed_hours": 0, "reserved_hours": 0, "availability": "absent"},
            {"employee_id": "emp-clara", "team_id": "data", "skills": ["sql"], "shift_hours": 8,
             "committed_hours": 0, "reserved_hours": 0, "availability": "absent"},
            {"employee_id": "emp-alex", "team_id": "ops", "skills": ["python"], "shift_hours": 4,
             "committed_hours": 0, "reserved_hours": 0, "availability": "available"},
            {"employee_id": "emp-beto", "team_id": "data", "skills": ["python"], "shift_hours": 5,
             "committed_hours": 0, "reserved_hours": 0.5, "availability": "available"},
            {"employee_id": "emp-luiza", "team_id": "finance", "skills": ["excel", "sql"], "shift_hours": 2,
             "committed_hours": 0, "reserved_hours": 0.3, "availability": "available"},
        ],
        "exclusions": [],
        "policies": {"max_utilization_pct": 90, "critical_requires_bp": True},
    }


def test_three_simultaneous_absences_are_planned_jointly(snapshot):
    scenario = _three_absence_snapshot(snapshot)
    before = deepcopy(scenario)

    result = plan_coverage(scenario)

    assert result["case_id"] == "case-three-absences"
    assert result["plan_version"] == 7
    assert len(scenario["absent_employee_ids"]) == 3
    assert {item["task_id"] for item in result["assignments"]} == {
        "task-critical-python", "task-high-excel", "task-high-python", "task-medium-python"
    }
    assert {item["task_id"] for item in result["uncovered"]} == {"task-medium-sql"}
    assert all(item["candidate_employee_id"] not in scenario["absent_employee_ids"] for item in result["assignments"])
    python_allocations = {
        item["task_id"]: item["candidate_employee_id"]
        for item in result["assignments"]
        if item["task_id"] in {"task-critical-python", "task-high-python", "task-medium-python"}
    }
    # A first-fit greedy pass sends the critical 2h task to emp-alex (ID tie),
    # then cannot fit the 3h task there or on emp-beto after another 2h task.
    # The joint solution moves both 2h tasks to emp-beto and preserves emp-alex
    # for the 3h task.
    assert python_allocations == {
        "task-critical-python": "emp-beto",
        "task-high-python": "emp-beto",
        "task-medium-python": "emp-alex",
    }
    assert result["metrics"] == {"demand_hours": 9.5, "planned_hours": 8.5}
    _assert_planner_invariants(scenario, result)
    assert scenario == before


def test_three_absence_plan_is_deterministic_across_input_order(snapshot):
    scenario = _three_absence_snapshot(snapshot)
    expected = plan_coverage(scenario)
    reordered = deepcopy(scenario)
    reordered["tasks"].reverse()
    reordered["employees"].reverse()
    reordered["absent_employee_ids"].reverse()

    assert plan_coverage(reordered) == expected
    assert replan_coverage(reordered) == expected


def test_three_absence_replan_respects_updated_task_candidate_exclusion(snapshot):
    scenario = _three_absence_snapshot(snapshot)
    scenario["exclusions"] = [{"task_id": "task-high-excel", "employee_id": "emp-luiza"}]
    before = deepcopy(scenario)

    result = replan_coverage(scenario)

    assert all(
        not (item["task_id"] == "task-high-excel" and item["candidate_employee_id"] == "emp-luiza")
        for item in result["assignments"]
    )
    assert {item["task_id"]: item["reason_code"] for item in result["uncovered"]} == {
        "task-high-excel": "ALL_CANDIDATES_EXCLUDED"
    }
    _assert_planner_invariants(scenario, result)
    assert scenario == before


@pytest.mark.parametrize("planner", [plan_coverage, replan_coverage])
def test_public_uncovered_shape_has_no_invented_alternative_payload(snapshot, planner):
    snapshot["employees"] = []
    snapshot["tasks"] = [snapshot["tasks"][0]]

    result = planner(snapshot)

    assert result["uncovered"] == [{
        "task_id": "task-A",
        "reason_code": "NO_AVAILABLE_CANDIDATE",
        "alternatives": [],
    }]
    assert set(result) == {"case_id", "plan_version", "assignments", "uncovered", "metrics"}


def _assert_planner_invariants(snapshot, result):
    assert result["case_id"] == snapshot["case_id"]
    assert result["plan_version"] == snapshot["plan_version"]
    assert set(result) == {"case_id", "plan_version", "assignments", "uncovered", "metrics"}
    active_tasks = {task["task_id"]: task for task in snapshot["tasks"] if task.get("status") != "done"}
    employees = {employee["employee_id"]: employee for employee in snapshot["employees"]}
    excluded = {(item["task_id"], item["employee_id"]) for item in snapshot.get("exclusions", [])}
    absent = set(snapshot["absent_employee_ids"])
    assignments = result["assignments"]
    uncovered = result["uncovered"]
    assignment_ids = [item["task_id"] for item in assignments]
    uncovered_ids = [item["task_id"] for item in uncovered]

    assert len(assignment_ids) == len(set(assignment_ids))
    assert len(uncovered_ids) == len(set(uncovered_ids))
    assert set(assignment_ids).isdisjoint(uncovered_ids)
    assert set(assignment_ids + uncovered_ids).issubset(active_tasks)
    assert all(item["alternatives"] == [] for item in uncovered)
    assert all("status" not in item for item in assignments)

    planned_by_employee = {}
    for assignment in assignments:
        task = active_tasks[assignment["task_id"]]
        employee_id = assignment["candidate_employee_id"]
        employee = employees[employee_id]
        assert task["transfer_allowed"] is True
        assert employee_id not in absent
        assert employee["availability"] == "available"
        assert set(task["required_skills"]).issubset(employee["skills"])
        assert (task["task_id"], employee_id) not in excluded
        assert Decimal(str(assignment["estimated_hours"])) == Decimal(str(task["estimated_hours"]))
        planned_by_employee[employee_id] = planned_by_employee.get(employee_id, Decimal("0")) + Decimal(str(assignment["estimated_hours"]))

    utilization = Decimal(str(snapshot.get("policies", {}).get("max_utilization_pct", 90)))
    for employee_id, task_hours in planned_by_employee.items():
        employee = employees[employee_id]
        effective_limit = Decimal(str(employee["shift_hours"])) * utilization / Decimal("100")
        occupied = Decimal(str(employee["committed_hours"])) + Decimal(str(employee["reserved_hours"]))
        assert occupied + task_hours <= effective_limit

    demand = sum(Decimal(str(task["estimated_hours"])) for task in active_tasks.values())
    planned = sum(Decimal(str(item["estimated_hours"])) for item in assignments)
    assert Decimal(str(result["metrics"]["demand_hours"])) == demand
    assert Decimal(str(result["metrics"]["planned_hours"])) == planned
    assert all(math.isfinite(float(value)) and value >= 0 for value in result["metrics"].values())


@pytest.mark.parametrize("planner", [plan_coverage, replan_coverage])
@pytest.mark.parametrize("multi_absence", [False, True])
def test_planning_invariants_hold_for_plan_and_replan(snapshot, planner, multi_absence):
    scenario = _three_absence_snapshot(snapshot) if multi_absence else deepcopy(snapshot)
    before = deepcopy(scenario)

    result = planner(scenario)

    _assert_planner_invariants(scenario, result)
    assert scenario == before


def test_search_limit_returns_a_valid_feasible_incumbent(snapshot, monkeypatch):
    monkeypatch.setattr(planning_module, "_SEARCH_NODE_LIMIT", 1)
    before = deepcopy(snapshot)

    result = plan_coverage(snapshot)

    assert len(result["assignments"]) == 2
    _assert_planner_invariants(snapshot, result)
    assert snapshot == before
