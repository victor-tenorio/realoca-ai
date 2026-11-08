"""Regression: Slack-only demo must never generate an offer for Teams users."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.demo.seed import seed_demo
from app.enums import CaseStatus, Channel, TaskStatus
from app.models import Absence, Case, Employee, PolicyVersion, Shift, Task
from app.services import planning, snapshot


def test_slack_only_planning_excludes_teams_and_blank_slack_recipients(session):
    seed_demo(session)
    task = session.scalar(select(Task).where(
        Task.status == TaskStatus.OPEN,
        Task.team_id == "demo-atendimento",
    ).order_by(Task.task_id).limit(1))
    assert task is not None
    shift = session.get(Shift, task.shift_id)
    created = min(shift.starts_at + timedelta(minutes=1),
                  datetime.now(UTC) - timedelta(hours=1))
    absence = Absence(
        absence_id="slack-only-absence", employee_id=task.assignee_employee_id,
        starts_at=shift.starts_at, ends_at=shift.ends_at,
        confirmed=True, source_system="test", external_id="slack-only-absence",
        updated_at=created,
    )
    case = Case(
        case_id="slack-only-case", status=CaseStatus.OPEN, plan_version=0,
        created_at=created, tasks=[task], absences=[absence],
    )
    policy = PolicyVersion(policy_version=1, created_at=created)
    session.add_all([case, policy])
    # This matches the user's failure: employees with a channel_user_id but
    # the wrong channel were mistakenly considered valid Slack candidates.
    teams_employee = session.get(Employee, "demo-atendimento-08")
    teams_employee.preferred_channel = Channel.TEAMS
    blank_employee = session.get(Employee, "demo-atendimento-09")
    blank_employee.channel_user_id = "   "
    session.commit()

    built = snapshot.build(session, case, policy=policy, plan_version=1)
    candidates = {employee["employee_id"] for employee in built["employees"]}
    assert "demo-atendimento-08" not in candidates
    assert "demo-atendimento-09" not in candidates
    assert "demo-atendimento-03" in candidates
    assert candidates
    for employee_id in candidates:
        employee = session.get(Employee, employee_id)
        assert employee.preferred_channel == Channel.SLACK
        assert employee.channel_user_id and employee.channel_user_id.strip()

    # Release the read transaction before the writer-locked orchestration.
    session.rollback()
    assert not session.in_transaction()
    # Rollback expires case's ORM attributes. Accessing case.case_id here
    # would auto-open a read transaction before plan_and_authorize.begin().
    # Use the known stable ID instead to keep a fresh transaction boundary.
    result = planning.plan_and_authorize(session, "slack-only-case", actor="test:slack")
    assert result["proposals"]
    assert all(
        session.get(Employee, proposal["candidate_employee_id"]).preferred_channel == Channel.SLACK
        for proposal in result["proposals"]
    )
