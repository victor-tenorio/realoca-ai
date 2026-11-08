"""A07: case lifecycle must not confuse invitations, acceptance and completion."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.demo.seed import seed_demo
from app.enums import AttemptStatus, CaseStatus, TaskStatus
from app.errors import APIError
from app.models import AuditEvent, Case, CoverageAttempt, CoveragePlan, Employee, PolicyVersion, Task
from app.services.cases import (
    CASE_TRANSITIONS, derive_case_status, recalculate_case_status, transition_case,
)

NOW = datetime(2026, 11, 8, 11, tzinfo=UTC)


@pytest.fixture
def scenario(session):
    seed_demo(session)
    tasks = list(session.scalars(select(Task).limit(2)))
    assert len(tasks) == 2
    original = tasks[0].assignee_employee_id
    candidate = session.scalar(select(Employee).where(Employee.employee_id != original).limit(1))
    case = Case(case_id="state-case", status=CaseStatus.OPEN, plan_version=1,
                created_at=NOW, tasks=tasks)
    session.add_all([case, PolicyVersion(policy_version=1, created_at=NOW)])
    session.flush()
    plan = CoveragePlan(plan_id="state-plan", case_id=case.case_id,
                        plan_version=1, policy_version=1, created_at=NOW)
    session.add(plan)
    session.flush()
    attempt = CoverageAttempt(
        attempt_id="state-attempt", case_id=case.case_id, plan_id=plan.plan_id,
        plan_version=1, task_id=tasks[0].task_id,
        candidate_employee_id=candidate.employee_id, policy_version=1,
        status=AttemptStatus.PROPOSED, created_at=NOW,
        response_deadline_at=NOW + timedelta(minutes=15),
    )
    session.add(attempt)
    session.commit()
    return session, case, tasks, attempt, candidate


def _audit_count(session):
    return session.scalar(select(func.count()).select_from(AuditEvent))


def _change(session, case, status, reason="Teste auditável"):
    return transition_case(session, case, status, actor="test:case", reason=reason,
                           at=NOW + timedelta(minutes=1))


def test_start_planning_is_audited_and_repeat_is_noop(scenario):
    session, case, *_ = scenario
    assert _change(session, case, CaseStatus.PLANNING)
    assert not _change(session, case, CaseStatus.PLANNING)
    session.commit()
    events = list(session.scalars(select(AuditEvent).where(AuditEvent.case_id == case.case_id)))
    assert len(events) == 1
    assert events[0].action == "case.status_changed"
    assert events[0].actor == "test:case"
    assert events[0].reason == "Teste auditável"
    assert events[0].result == {"previous_status": "open", "status": "planning"}


@pytest.mark.parametrize("target", [
    CaseStatus.AWAITING_RESPONSES, CaseStatus.COVERAGE_CONFIRMED,
    CaseStatus.CLOSED_WITH_GAPS, CaseStatus.COMPLETED,
])
def test_cannot_skip_open_case_or_mutate_on_invalid_transition(scenario, target):
    session, case, *_ = scenario
    with pytest.raises(APIError) as exc:
        _change(session, case, target)
    assert exc.value.code == "INVALID_CASE_TRANSITION"
    session.commit()
    assert case.status == CaseStatus.OPEN and case.closed_at is None
    assert _audit_count(session) == 0


def test_bp_and_pending_response_need_real_attempts(scenario):
    session, case, _, attempt, _ = scenario
    _change(session, case, CaseStatus.PLANNING)
    with pytest.raises(APIError):
        _change(session, case, CaseStatus.PENDING_APPROVAL)
    with pytest.raises(APIError):
        _change(session, case, CaseStatus.AWAITING_RESPONSES)
    attempt.status = AttemptStatus.PENDING_APPROVAL
    assert _change(session, case, CaseStatus.PENDING_APPROVAL)
    attempt.status = AttemptStatus.NOTIFIED
    assert _change(session, case, CaseStatus.AWAITING_RESPONSES)
    session.commit()
    assert _audit_count(session) == 3


def test_accepted_invite_is_not_coverage_until_source_owner_changed(scenario):
    session, case, tasks, attempt, candidate = scenario
    _change(session, case, CaseStatus.PLANNING)
    attempt.status = AttemptStatus.ACCEPTED
    with pytest.raises(APIError) as exc:
        _change(session, case, CaseStatus.COVERAGE_CONFIRMED)
    assert exc.value.code == "CASE_COVERAGE_INCOMPLETE"
    tasks[0].assignee_employee_id = candidate.employee_id
    with pytest.raises(APIError):
        _change(session, case, CaseStatus.COVERAGE_CONFIRMED)
    # Both linked tasks must be covered. Even if a task has been marked done,
    # a missing accepted/assigned coverage record must not count as coverage.
    tasks[1].status = TaskStatus.DONE
    with pytest.raises(APIError):
        _change(session, case, CaseStatus.COVERAGE_CONFIRMED)
    session.commit()
    assert case.status == CaseStatus.PLANNING
    assert case.closed_at is None


def test_full_coverage_and_completion_are_separate_audited_states(scenario):
    session, case, tasks, attempt, candidate = scenario
    other = session.scalar(select(Employee).where(Employee.employee_id != tasks[1].assignee_employee_id).limit(1))
    attempt.status = AttemptStatus.ACCEPTED
    tasks[0].assignee_employee_id = candidate.employee_id
    second = CoverageAttempt(
        attempt_id="state-attempt-second", case_id=case.case_id,
        plan_id="state-plan", plan_version=1, task_id=tasks[1].task_id,
        candidate_employee_id=other.employee_id, policy_version=1,
        status=AttemptStatus.ACCEPTED, created_at=NOW,
    )
    session.add(second)
    tasks[1].assignee_employee_id = other.employee_id
    _change(session, case, CaseStatus.PLANNING)
    assert _change(session, case, CaseStatus.COVERAGE_CONFIRMED)
    with pytest.raises(APIError) as exc:
        _change(session, case, CaseStatus.COMPLETED)
    assert exc.value.code == "CASE_TASKS_PENDING"
    for task in tasks:
        task.status = TaskStatus.DONE
    assert _change(session, case, CaseStatus.COMPLETED)
    session.commit()
    assert case.status == CaseStatus.COMPLETED and case.closed_at is not None
    assert _audit_count(session) == 3
    with pytest.raises(APIError):
        _change(session, case, CaseStatus.PLANNING)


def test_gap_requires_explicit_escalation_and_no_pending_offer(scenario):
    session, case, tasks, attempt, candidate = scenario
    _change(session, case, CaseStatus.PLANNING)
    with pytest.raises(APIError):
        _change(session, case, CaseStatus.CLOSED_WITH_GAPS)
    attempt.status = AttemptStatus.ESCALATED
    assert _change(session, case, CaseStatus.CLOSED_WITH_GAPS)
    session.commit()
    assert case.status == CaseStatus.CLOSED_WITH_GAPS
    assert case.closed_at is not None
    assert _audit_count(session) == 2


def test_derivation_and_recalculation_preserve_full_lifecycle(scenario):
    session, case, tasks, attempt, candidate = scenario
    assert derive_case_status(session, case) == CaseStatus.PLANNING
    assert case.status == CaseStatus.OPEN
    attempt.status = AttemptStatus.NOTIFIED
    assert recalculate_case_status(session, case, actor="test:recalc",
                                   at=NOW + timedelta(minutes=1)) == CaseStatus.AWAITING_RESPONSES
    attempt.status = AttemptStatus.REFUSED
    assert recalculate_case_status(session, case, actor="test:recalc",
                                   at=NOW + timedelta(minutes=2)) == CaseStatus.PLANNING
    session.commit()
    assert _audit_count(session) == 3  # open -> planning -> waiting -> planning


def test_unplanned_empty_case_cannot_be_confirmed(session):
    case = Case(case_id="empty-state-case", status=CaseStatus.OPEN, plan_version=0, created_at=NOW)
    session.add_all([case, PolicyVersion(policy_version=1, created_at=NOW)])
    session.commit()
    assert derive_case_status(session, case) == CaseStatus.OPEN
    _change(session, case, CaseStatus.PLANNING)
    with pytest.raises(APIError) as exc:
        _change(session, case, CaseStatus.COVERAGE_CONFIRMED)
    assert exc.value.code == "CASE_COVERAGE_INCOMPLETE"
    session.commit()
    assert case.status == CaseStatus.PLANNING and case.closed_at is None


def test_audit_and_state_roll_back_together(scenario):
    session, case, *_ = scenario
    _change(session, case, CaseStatus.PLANNING)
    assert _audit_count(session) == 1
    session.rollback()
    session.refresh(case)
    assert case.status == CaseStatus.OPEN
    assert _audit_count(session) == 0


def test_all_contract_statuses_have_transition_declaration():
    assert set(CASE_TRANSITIONS) == set(CaseStatus)
    assert CASE_TRANSITIONS[CaseStatus.COMPLETED] == frozenset()
    assert CASE_TRANSITIONS[CaseStatus.CLOSED_WITH_GAPS] == frozenset()
