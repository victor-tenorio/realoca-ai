"""A08 integration: DB source -> Mateus engine -> audited, unreserved proposals."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.demo.seed import seed_demo
from app.enums import AttemptStatus, CaseStatus, TaskStatus
from app.errors import APIError
from app.models import (
    Absence, AuditEvent, Case, CoverageAttempt, CoveragePlan, Employee, PolicyVersion,
    Reservation, Shift, Task, TaskAssignment,
)
from app.services import planning, snapshot
from app.services.reservations import reserve_attempt_atomic


@pytest.fixture
def scenario(session):
    seed_demo(session)
    task = session.scalar(select(Task).where(Task.status == TaskStatus.OPEN).limit(1))
    assert task is not None
    owner = task.assignee_employee_id
    affected = list(session.scalars(select(Task).where(
        Task.assignee_employee_id == owner, Task.shift_id == task.shift_id,
        Task.status == TaskStatus.OPEN,
    )))
    shift = session.get(Shift, task.shift_id)
    created = shift.starts_at + timedelta(minutes=1)
    absence = Absence(
        absence_id="bridge-absence", employee_id=owner,
        starts_at=shift.starts_at, ends_at=shift.ends_at,
        confirmed=True, source_system="bridge-test", external_id="absence-1",
        updated_at=created,
    )
    case = Case(case_id="bridge-case", status=CaseStatus.OPEN,
                plan_version=0, created_at=created, tasks=affected,
                absences=[absence])
    session.add_all([case, PolicyVersion(policy_version=1, created_at=created)])
    session.commit()
    return session, case, affected, created


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_real_database_snapshot_invokes_engine_and_persists_only_proposals(scenario):
    session, case, tasks, created = scenario
    before = {t.task_id: t.assignee_employee_id for t in tasks}
    result = planning.create_plan(session, case, actor="test:bridge",
                                  at=created + timedelta(seconds=1))
    session.commit()
    assert result["case_id"] == case.case_id
    assert result["plan_version"] == 1
    assert session.get(CoveragePlan, result["plan_id"]).policy_version == 1
    assert case.status == CaseStatus.PLANNING
    assert case.plan_version == 1
    assert {t.task_id: t.assignee_employee_id for t in tasks} == before
    assert _count(session, Reservation) == 0
    assert _count(session, TaskAssignment) == 0
    assert _count(session, CoverageAttempt) == len(result["proposals"])
    assert len(result["proposals"]) + len(result["uncovered"]) == len(tasks)
    assert all(item["status"] == "proposed" for item in result["proposals"])
    assert all(item["candidate_employee_id"] != case.absences[0].employee_id
               for item in result["proposals"])
    assert all(item.status == AttemptStatus.PROPOSED for item in session.scalars(
        select(CoverageAttempt)))
    audits = list(session.scalars(select(AuditEvent).where(
        AuditEvent.case_id == case.case_id)))
    assert {item.action for item in audits} == {"case.status_changed", "plan.proposed"}
    assert all(item.policy_version == 1 for item in audits)


def test_snapshot_uses_live_absences_and_source_data(scenario):
    session, case, tasks, created = scenario
    policy = session.get(PolicyVersion, 1)
    built = snapshot.build(session, case, policy=policy, plan_version=1)
    assert set(built["absent_employee_ids"]) == {case.absences[0].employee_id}
    assert {item["task_id"] for item in built["tasks"]} == {t.task_id for t in tasks}
    assert all(item["shift_hours"] > 0 for item in built["employees"])
    assert all(item["reserved_hours"] >= 0 for item in built["employees"])
    assert built["policies"]["max_utilization_pct"] == 90
    employee_id = next(item["employee_id"] for item in built["employees"]
                       if item["availability"] == "available")
    other = Absence(absence_id="other-absence", employee_id=employee_id,
                    starts_at=case.absences[0].starts_at,
                    ends_at=case.absences[0].ends_at,
                    confirmed=True, source_system="bridge-test", external_id="absence-2",
                    updated_at=created)
    session.add(other)
    session.flush()
    after = snapshot.build(session, case, policy=policy, plan_version=1)
    assert employee_id in after["absent_employee_ids"]
    assert next(item["availability"] for item in after["employees"]
                if item["employee_id"] == employee_id) == "absent"


def test_rejects_second_plan_while_first_proposal_is_active(scenario):
    session, case, tasks, created = scenario
    result = planning.create_plan(session, case, actor="test:bridge",
                                  at=created + timedelta(seconds=1))
    assert result["proposals"]
    with pytest.raises(APIError) as exc:
        planning.create_plan(session, case, actor="test:bridge",
                             at=created + timedelta(seconds=2))
    assert exc.value.code == "PLAN_ALREADY_ACTIVE"
    session.commit()
    assert case.plan_version == 1


def test_incomplete_source_task_prevents_invented_plan(scenario):
    session, case, tasks, created = scenario
    tasks[0].required_skills_known = False
    with pytest.raises(APIError) as exc:
        planning.create_plan(session, case, actor="test:bridge",
                             at=created + timedelta(seconds=1))
    assert exc.value.code == "INCOMPLETE_TASK_DATA"
    assert case.plan_version == 0
    assert _count(session, CoveragePlan) == 0


def test_plan_and_audit_are_rolled_back_together(scenario):
    session, case, tasks, created = scenario
    planning.create_plan(session, case, actor="test:bridge",
                         at=created + timedelta(seconds=1))
    assert _count(session, CoveragePlan) == 1
    session.rollback()
    session.refresh(case)
    assert case.plan_version == 0 and case.status == CaseStatus.OPEN
    assert _count(session, CoveragePlan) == 0
    assert _count(session, CoverageAttempt) == 0
    assert _count(session, AuditEvent) == 0


def test_rejects_corrupt_engine_result_before_persisting(scenario, monkeypatch):
    session, case, tasks, created = scenario

    def broken_engine(data):
        return {"case_id": data["case_id"], "plan_version": data["plan_version"],
                "assignments": [], "uncovered": []}

    monkeypatch.setattr(planning, "plan_coverage", broken_engine)
    with pytest.raises(APIError) as exc:
        planning.create_plan(session, case, actor="test:bridge",
                             at=created + timedelta(seconds=1))
    assert exc.value.code == "INVALID_ENGINE_RESULT"
    assert case.plan_version == 0
    assert _count(session, CoveragePlan) == 0


def test_reservation_is_single_use_and_visible_to_capacity(scenario):
    session, case, tasks, created = scenario
    result = planning.create_plan(session, case, actor="test:bridge",
                                  at=created + timedelta(seconds=1))
    assert result["proposals"]
    attempt = session.get(CoverageAttempt, result["proposals"][0]["attempt_id"])
    # A11 supplies the explicit BP decision when required. Here we seed its
    # persisted approval to test A10 independently of the approval endpoint.
    attempt.approval_decision = "approve"
    attempt.approval_actor_id = "bp-test"
    attempt.approval_decided_at = created + timedelta(seconds=2)
    session.commit()
    with Session(session.get_bind()) as reserver:
        first = reserve_attempt_atomic(reserver, attempt.attempt_id,
                                       actor="test:reserve", at=created + timedelta(seconds=3))
        first_id = first.reservation_id
    with Session(session.get_bind()) as reserver:
        second = reserve_attempt_atomic(reserver, attempt.attempt_id,
                                        actor="test:reserve", at=created + timedelta(seconds=4))
        assert first_id == second.reservation_id
    session.expire_all()
    assert _count(session, Reservation) == 1
    assert session.get(CoverageAttempt, attempt.attempt_id).status == AttemptStatus.RESERVED
    assert case.status == CaseStatus.AWAITING_RESPONSES
    assert all(t.assignee_employee_id != attempt.candidate_employee_id for t in tasks)
    assert _count(session, TaskAssignment) == 0


def test_new_absence_invalidates_pending_reservation(scenario):
    session, case, tasks, created = scenario
    result = planning.create_plan(session, case, actor="test:bridge",
                                  at=created + timedelta(seconds=1))
    assert result["proposals"]
    attempt = session.get(CoverageAttempt, result["proposals"][0]["attempt_id"])
    attempt.approval_decision = "approve"
    attempt.approval_actor_id = "bp-test"
    attempt.approval_decided_at = created + timedelta(seconds=2)
    session.add(Absence(
        absence_id="new-candidate-absence", employee_id=attempt.candidate_employee_id,
        starts_at=case.absences[0].starts_at,
        ends_at=case.absences[0].ends_at, confirmed=True,
        source_system="bridge-test", external_id="candidate-absence",
        updated_at=created,
    ))
    session.commit()
    with Session(session.get_bind()) as reserver:
        with pytest.raises(APIError) as exc:
            reserve_attempt_atomic(reserver, attempt.attempt_id,
                                   actor="test:reserve", at=created + timedelta(seconds=3))
        assert exc.value.code == "CAPACITY_OR_POLICY_CONFLICT"
    assert _count(session, Reservation) == 0
