"""A09 decisions are deterministic and expose reasons for BP/audit."""

from decimal import Decimal

import pytest

from app.enums import Priority, TaskStatus
from app.models import Employee, PolicyVersion, Skill, Task
from app.services.capacity import Capacity
from app.services.policy import classify


@pytest.fixture
def context():
    task = Task(task_id="task", priority=Priority.HIGH, status=TaskStatus.OPEN,
                estimated_hours=Decimal("2"), transfer_allowed=True,
                required_skills_known=True, team_id="team-a",
                required_skills=[Skill(skill_id="python")])
    employee = Employee(employee_id="candidate", team_id="team-a",
                        skills_known=True, skills=[Skill(skill_id="python")])
    policy = PolicyVersion(policy_version=1, max_utilization_pct=Decimal("90"),
                           critical_requires_bp=True, cross_team_requires_bp=True,
                           allow_automatic_same_team=True)
    capacity = Capacity(Decimal("8"), Decimal("2"), Decimal("1"),
                        Decimal("3"), Decimal("37.5"), Decimal("5"),
                        Decimal("4.2"), True)
    return task, employee, policy, capacity


def decide(context, absent=None):
    task, employee, policy, capacity = context
    return classify(task, employee, policy, capacity,
                    absent_employee_ids=absent or set())


def test_same_team_eligible_proposal_is_auto(context):
    assert decide(context).action == "auto"
    assert decide(context).reason_code == "POLICY_AUTO"


def test_critical_and_cross_team_require_bp(context):
    task, employee, policy, _ = context
    task.priority = Priority.CRITICAL
    assert decide(context).reason_code == "CRITICAL_TASK"
    task.priority = Priority.HIGH
    employee.team_id = "team-b"
    assert decide(context).reason_code == "CROSS_TEAM"
    assert decide(context).action == "needs_approval"


def test_policy_can_require_bp_for_same_team(context):
    context[2].allow_automatic_same_team = False
    assert decide(context).reason_code == "SAME_TEAM_RESTRICTED"


@pytest.mark.parametrize("change,code", [
    ("absent", "CANDIDATE_ABSENT"),
    ("transfer", "TRANSFER_NOT_ALLOWED"),
    ("skills", "SKILL_MISMATCH"),
    ("unknown", "UNKNOWN_CAPACITY"),
    ("hours", "INSUFFICIENT_CAPACITY"),
    ("done", "TASK_ALREADY_DONE"),
])
def test_inviable_proposals_are_blocked(context, change, code):
    task, employee, policy, capacity = context
    absent = set()
    if change == "absent":
        absent.add("candidate")
    elif change == "transfer":
        task.transfer_allowed = False
    elif change == "skills":
        employee.skills = []
    elif change == "unknown":
        capacity = Capacity(None, None, Decimal(0), None, None, None, None, False)
    elif change == "hours":
        capacity = Capacity(Decimal(8), Decimal(7), Decimal(0),
                            Decimal(7), Decimal("87.5"), Decimal(1),
                            Decimal("0.2"), True)
    elif change == "done":
        task.status = TaskStatus.DONE
    action = classify(task, employee, policy, capacity, absent_employee_ids=absent)
    assert action.action == "inviable"
    assert action.reason_code == code
