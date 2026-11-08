from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.demo.seed import seed_demo
from app.enums import AttemptStatus, CaseStatus, Channel, IntegrationEventType
from app.models import (
    Absence, AuditEvent, Case, CoverageAttempt, CoveragePlan, Employee,
    MessageDelivery, OutboundMessage, PolicyVersion, ProcessedEvent,
    Reservation, Task,
)
from app.services.capacity import employee_capacity
from conftest import migration_config
from app.db import make_engine

NOW = datetime(2026, 11, 8, 11, tzinfo=timezone.utc)
PREVIOUS = "d00209376958"


@pytest.fixture
def workflow(session):
    seed_demo(session)
    task = session.scalar(select(Task))
    candidate = session.scalar(select(Employee).where(Employee.employee_id != task.assignee_employee_id))
    absence = Absence(absence_id="absence-1", employee_id=task.assignee_employee_id,
                      starts_at=NOW, ends_at=NOW + timedelta(hours=8), confirmed=True,
                      source_system="hr_simulator", external_id="absence-1", updated_at=NOW)
    policy = PolicyVersion(policy_version=1, created_at=NOW)
    case = Case(case_id="case-1", status=CaseStatus.OPEN, plan_version=1,
                created_at=NOW, absences=[absence], tasks=[task])
    session.add_all([policy, case])
    session.flush()
    plan = CoveragePlan(plan_id="plan-1", case_id=case.case_id, plan_version=1,
                        policy_version=1, created_at=NOW)
    session.add(plan)
    session.flush()
    attempt = CoverageAttempt(attempt_id="attempt-1", case_id=case.case_id,
        plan_id=plan.plan_id, plan_version=1, task_id=task.task_id,
        candidate_employee_id=candidate.employee_id, policy_version=1,
        status=AttemptStatus.PROPOSED, created_at=NOW, reason="Synthetic proposal",
        response_deadline_at=NOW + timedelta(minutes=15))
    session.add(attempt)
    session.commit()
    return case, task, candidate, attempt


def test_case_links_survive_assignment_change(session, workflow):
    case, task, candidate, attempt = workflow
    original_employee = case.absences[0].employee_id
    task.assignee = candidate
    session.commit()
    session.expire_all()
    assert case.tasks == [task]
    assert case.absences[0].employee_id == original_employee
    assert attempt.plan.case_id == case.case_id


@pytest.mark.parametrize("state", ["proposed", "pending_approval", "reserved", "notified"])
def test_one_active_attempt_globally(session, workflow, state):
    _, task, candidate, attempt = workflow
    session.execute(text("UPDATE coverage_attempts SET status=:s WHERE attempt_id='attempt-1'"), {"s": state})
    session.commit()
    duplicate = CoverageAttempt(attempt_id="attempt-2", case_id="case-1", plan_id="plan-1",
        plan_version=1, task_id=task.task_id, candidate_employee_id=candidate.employee_id,
        policy_version=1, status=AttemptStatus.PROPOSED, created_at=NOW)
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_terminal_history_and_escalation_without_candidate(session, workflow):
    _, task, _, attempt = workflow
    # Persistence setup only; the transition service is intentionally not implemented.
    session.execute(text("UPDATE coverage_attempts SET status='refused' WHERE attempt_id='attempt-1'"))
    session.commit()
    session.add(CoverageAttempt(attempt_id="attempt-2", case_id="case-1", plan_id="plan-1",
        plan_version=1, task_id=task.task_id, candidate_employee_id=None, policy_version=1,
        status=AttemptStatus.ESCALATED, reason="No eligible candidate", created_at=NOW))
    session.commit()
    assert session.scalar(select(func.count()).select_from(CoverageAttempt)) == 2
    session.refresh(attempt)
    assert attempt.status == AttemptStatus.REFUSED
    with pytest.raises(IntegrityError):
        session.execute(text("DELETE FROM coverage_attempts WHERE attempt_id='attempt-1'"))
    session.rollback()


def test_policy_defaults_and_immutable_historical_version(session, workflow):
    policy = session.get(PolicyVersion, 1)
    assert (policy.max_utilization_pct, policy.critical_requires_bp, policy.cross_team_requires_bp,
            policy.response_timeout_minutes, policy.allow_automatic_same_team,
            policy.reminder_before_expiry_minutes) == (90, True, True, 15, True, 5)
    session.add(PolicyVersion(policy_version=2, max_utilization_pct=80, created_at=NOW))
    session.commit()
    assert workflow[3].policy_version == 1
    with pytest.raises(IntegrityError):
        session.execute(text("UPDATE policy_versions SET max_utilization_pct=80 WHERE policy_version=1"))
    session.rollback()


@pytest.mark.parametrize("sql", [
    "UPDATE cases SET status='escalated'",
    "UPDATE coverage_attempts SET status='completed'",
    "UPDATE coverage_attempts SET candidate_employee_id='missing'",
    "UPDATE coverage_attempts SET candidate_employee_id=NULL",
    "UPDATE coverage_attempts SET plan_version=99",
    "UPDATE coverage_attempts SET policy_version=99",
    "UPDATE coverage_attempts SET task_id='missing'",
    "UPDATE absences SET employee_id='missing'",
    "UPDATE absences SET ends_at=starts_at",
    "UPDATE policy_versions SET response_timeout_minutes=0",
    "INSERT INTO case_absences VALUES ('case-1','missing')",
])
def test_workflow_constraints(session, workflow, sql):
    with pytest.raises(IntegrityError):
        session.execute(text(sql))
    session.rollback()


def test_processed_event_result_and_unique_id(session, workflow):
    event = ProcessedEvent(event_id="event-1", event_type=IntegrationEventType.ACCEPTED,
        attempt_id="attempt-1", channel=Channel.TEAMS, occurred_at=NOW, received_at=NOW,
        processed_at=NOW, result={"accepted": True}, response_status=200)
    session.add(event)
    session.commit()
    session.expire_all()
    assert session.get(ProcessedEvent, "event-1").result == {"accepted": True}
    with pytest.raises(IntegrityError):
        session.execute(text("INSERT INTO processed_events SELECT * FROM processed_events"))
    session.rollback()


@pytest.mark.parametrize("sql", ["UPDATE audit_events SET actor='changed'", "DELETE FROM audit_events",
                                  "INSERT OR REPLACE INTO audit_events SELECT * FROM audit_events"])
def test_audit_append_only_even_raw_sql(session, workflow, sql):
    session.add(AuditEvent(audit_event_id="audit-1", case_id="case-1", attempt_id="attempt-1",
        actor="synthetic-test", action="proposal.recorded", timestamp=NOW,
        policy_version=1, reason="Synthetic test", result={"stored": True}))
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(text(sql))
    session.rollback()


def test_delivery_retries_do_not_create_proposals_or_acceptance(session, workflow):
    session.add(OutboundMessage(message_id="message-1", event_id="out-1", attempt_id="attempt-1",
        channel=Channel.SLACK, channel_user_id="synthetic-user", message="Synthetic offer",
        simulated=True, created_at=NOW))
    session.flush()
    session.add_all([
        MessageDelivery(delivery_id="delivery-1", message_id="message-1", delivery_number=1,
                        started_at=NOW, failed_at=NOW, error_code="TIMEOUT"),
        MessageDelivery(delivery_id="delivery-2", message_id="message-1", delivery_number=2,
                        started_at=NOW, sent_at=NOW, delivered_at=NOW),
    ])
    session.commit()
    session.expire_all()
    message = session.get(OutboundMessage, "message-1")
    assert len(message.deliveries) == 2
    assert message.simulated is True
    assert workflow[3].status == AttemptStatus.PROPOSED
    assert session.scalar(select(func.count()).select_from(CoverageAttempt)) == 1


def test_reservations_feed_capacity_once_and_release_keeps_history(session, workflow):
    _, task, candidate, _ = workflow
    before = employee_capacity(session, candidate.employee_id, task.shift_id)
    session.execute(text("UPDATE coverage_attempts SET status='reserved' WHERE attempt_id='attempt-1'"))
    reservation = Reservation(reservation_id="reservation-1", attempt_id="attempt-1",
                              reserved_hours=Decimal("1.5"), created_at=NOW)
    session.add(reservation)
    session.commit()
    result = employee_capacity(session, candidate.employee_id, task.shift_id)
    assert result.reserved_hours == Decimal("1.5")
    assert result.committed_hours == before.committed_hours
    assert result.occupied_hours == before.committed_hours + Decimal("1.5")
    assert result.reservations_supported
    assert workflow[3].reserved_hours == Decimal("1.5")
    reservation.released_at = NOW
    session.commit()
    assert employee_capacity(session, candidate.employee_id, task.shift_id).reserved_hours == 0
    assert session.get(Reservation, "reservation-1") is not None


def test_incremental_upgrade_preserves_previous_seed_and_downgrade(tmp_path):
    url = f"sqlite:///{(tmp_path / 'incremental.sqlite').as_posix()}"
    config = migration_config(url)
    command.upgrade(config, PREVIOUS)
    engine = make_engine(url)
    try:
        with Session(engine) as session:
            seed_demo(session)
            session.scalar(select(Employee)).name = "Preserved change"
            session.commit()
        command.upgrade(config, "head")
        command.check(config)
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Task)) == 187
            assert session.scalar(select(Employee.name).where(Employee.name == "Preserved change"))
        command.downgrade(config, PREVIOUS)
        assert "cases" not in inspect(engine).get_table_names()
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Employee)) == 40
            assert session.scalar(select(func.count()).select_from(Task)) == 187
        command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_downgrade_with_workflow_data_keeps_original_tables(database, session, workflow):
    session.add(AuditEvent(audit_event_id="audit-downgrade", case_id="case-1", attempt_id="attempt-1",
        actor="synthetic-test", action="proposal.recorded", timestamp=NOW,
        policy_version=1, result={"stored": True}))
    session.commit()
    session.close()
    engine, config = database
    command.downgrade(config, PREVIOUS)
    with Session(engine) as prior:
        assert prior.scalar(select(func.count()).select_from(Task)) == 187
        assert prior.scalar(select(func.count()).select_from(Employee)) == 40
        assert prior.scalar(text("SELECT count(*) FROM sqlite_master WHERE type='trigger'")) == 0
    command.upgrade(config, "head")


@pytest.mark.parametrize("values", [
    {"max_utilization_pct": 0}, {"max_utilization_pct": 101},
    {"response_timeout_minutes": 0}, {"reminder_before_expiry_minutes": -1},
    {"reminder_before_expiry_minutes": 15},
])
def test_new_policy_ranges(session, values):
    session.add(PolicyVersion(policy_version=1, created_at=NOW, **values))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


@pytest.mark.parametrize("sql", [
    "UPDATE processed_events SET event_type='offer.unknown'",
    "UPDATE processed_events SET channel='email'",
    "UPDATE processed_events SET attempt_id='missing'",
    "UPDATE processed_events SET processed_at=received_at, result='{}'",
])
def test_inbox_constraints(session, workflow, sql):
    session.add(ProcessedEvent(event_id="pending-1", event_type=IntegrationEventType.DELIVERED,
        attempt_id="attempt-1", channel=Channel.TEAMS, occurred_at=NOW, received_at=NOW))
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(text(sql))
    session.rollback()


def test_inbox_processing_fields_can_be_filled_once(session, workflow):
    event = ProcessedEvent(event_id="pending-1", event_type=IntegrationEventType.DELIVERED,
        attempt_id="attempt-1", channel=Channel.TEAMS, occurred_at=NOW, received_at=NOW)
    session.add(event)
    session.commit()
    event.processed_at = NOW
    event.result = {"recorded": True}
    event.response_status = 202
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(text("UPDATE processed_events SET result='{}'"))
    session.rollback()


def test_reservation_lifecycle_constraints_and_atomic_storage_conversion(session, workflow):
    _, task, candidate, attempt = workflow
    reservation = Reservation(reservation_id="r-1", attempt_id="attempt-1", reserved_hours=1, created_at=NOW)
    session.add(reservation)
    with pytest.raises(IntegrityError):  # proposed does not reserve
        session.flush()
    session.rollback()
    session.execute(text("UPDATE coverage_attempts SET status='reserved' WHERE attempt_id='attempt-1'"))
    session.add(Reservation(reservation_id="r-1", attempt_id="attempt-1", reserved_hours=-1, created_at=NOW))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    session.execute(text("UPDATE coverage_attempts SET status='reserved' WHERE attempt_id='attempt-1'"))
    session.add(Reservation(reservation_id="r-1", attempt_id="attempt-1", reserved_hours=1, created_at=NOW))
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(text("UPDATE tasks SET assignee_employee_id=:candidate WHERE task_id=:task"),
                        {"candidate": candidate.employee_id, "task": task.task_id})
    session.rollback()
    with pytest.raises(IntegrityError):
        session.execute(text("UPDATE coverage_attempts SET status='accepted' WHERE attempt_id='attempt-1'"))
    session.rollback()
    # Demonstrates storage atomicity only, not an acceptance/transition service.
    reservation = session.get(Reservation, "r-1")
    reservation.released_at = NOW
    session.flush()
    task.assignee = candidate
    session.flush()
    session.execute(text("UPDATE coverage_attempts SET status='accepted' WHERE attempt_id='attempt-1'"))
    session.rollback()  # all three writes revert together
    session.refresh(task)
    session.refresh(reservation)
    session.refresh(attempt)
    assert task.assignee_employee_id != candidate.employee_id
    assert reservation.released_at is None
    assert attempt.status == AttemptStatus.RESERVED


def test_active_constraint_across_cases_and_plans(session, workflow):
    _, task, candidate, _ = workflow
    session.add(Case(case_id="case-2", status=CaseStatus.OPEN, plan_version=1,
                     created_at=NOW, tasks=[task]))
    session.flush()
    session.add(CoveragePlan(plan_id="plan-2", case_id="case-2", plan_version=1, policy_version=1, created_at=NOW))
    session.flush()
    session.add(CoverageAttempt(attempt_id="attempt-2", case_id="case-2", plan_id="plan-2",
        plan_version=1, task_id=task.task_id, candidate_employee_id=candidate.employee_id,
        policy_version=1, status=AttemptStatus.PROPOSED, created_at=NOW))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


@pytest.mark.parametrize("sql", [
    "INSERT INTO message_deliveries SELECT 'duplicate',message_id,delivery_number,started_at,sent_at,delivered_at,failed_at,error_code,provider_message_id FROM message_deliveries",
    "UPDATE outbound_messages SET channel='email'",
    "UPDATE outbound_messages SET attempt_id='missing'",
    "INSERT INTO outbound_messages SELECT 'duplicate',event_id,event_type,attempt_id,channel,channel_user_id,message,simulated,created_at FROM outbound_messages",
    "UPDATE message_deliveries SET delivered_at=started_at",
])
def test_message_constraints(session, workflow, sql):
    session.add(OutboundMessage(message_id="m-1", event_id="out-1", attempt_id="attempt-1",
        channel=Channel.TEAMS, channel_user_id="synthetic-user", message="Synthetic offer",
        simulated=True, created_at=NOW))
    session.flush()
    session.add(MessageDelivery(delivery_id="d-1", message_id="m-1", delivery_number=1, started_at=NOW))
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(text(sql))
    session.rollback()


@pytest.mark.parametrize("state", list(CaseStatus))
def test_official_case_states_roundtrip(session, workflow, state):
    session.execute(text("UPDATE cases SET status=:state"), {"state": state.value})
    session.commit()
    session.expire_all()
    assert session.get(Case, "case-1").status is state


@pytest.mark.parametrize("state", list(AttemptStatus))
def test_official_attempt_states_roundtrip(session, workflow, state):
    # Verifies enum storage, not validation of transition paths.
    session.execute(text("UPDATE coverage_attempts SET status=:state"), {"state": state.value})
    session.commit()
    session.expire_all()
    assert session.get(CoverageAttempt, "attempt-1").status is state


@pytest.mark.parametrize("changes", [
    {"candidate_employee_id": "missing"}, {"plan_version": 99},
    {"policy_version": 99}, {"case_id": "missing"}, {"task_id": "missing"},
])
def test_attempt_foreign_keys_on_insert(session, workflow, changes):
    values = dict(attempt_id="historical-2", case_id="case-1", plan_id="plan-1",
                  plan_version=1, task_id=workflow[1].task_id,
                  candidate_employee_id=workflow[2].employee_id, policy_version=1,
                  status=AttemptStatus.REFUSED, created_at=NOW)
    values.update(changes)
    session.add(CoverageAttempt(**values))
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        session.flush()
    session.rollback()


def test_attempt_must_reference_originally_affected_task(session, workflow):
    other_task = session.scalar(select(Task).where(Task.task_id != workflow[1].task_id))
    session.add(CoverageAttempt(attempt_id="historical-2", case_id="case-1", plan_id="plan-1",
        plan_version=1, task_id=other_task.task_id, candidate_employee_id=workflow[2].employee_id,
        policy_version=1, status=AttemptStatus.REFUSED, created_at=NOW))
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        session.flush()
    session.rollback()
