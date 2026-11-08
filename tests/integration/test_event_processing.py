"""A14/A15: actual callback processing, source assignment and replanning."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.demo.seed import seed_demo
from app.enums import AttemptStatus, CaseStatus, TaskStatus
from app.main import app
from app.models import (
    Absence, Case, CoverageAttempt, OutboundMessage, PolicyVersion,
    ProcessedEvent, Reservation, Shift, Task, TaskAssignment,
)
from app.services import dispatch, planning, reservations
from app.errors import APIError


@pytest.fixture
def offer_fixture(session, monkeypatch):
    monkeypatch.setenv("INTEGRATIONS_INTERNAL_TOKEN", "test-only")
    seed_demo(session)
    task = session.scalar(select(Task).where(Task.status == TaskStatus.OPEN).limit(1))
    shift = session.get(Shift, task.shift_id)
    original_owner = task.assignee_employee_id
    now = datetime.now(UTC)
    created = now - timedelta(minutes=3)
    absence = Absence(absence_id="event-absence", employee_id=original_owner,
                      starts_at=shift.starts_at, ends_at=shift.ends_at,
                      confirmed=True, source_system="event-tests", external_id="evt-1",
                      updated_at=created)
    related = list(session.scalars(select(Task).where(
        Task.assignee_employee_id == original_owner,
        Task.shift_id == task.shift_id, Task.status == TaskStatus.OPEN,
    )))
    case = Case(case_id="event-case", status=CaseStatus.OPEN, plan_version=0,
                created_at=created, absences=[absence], tasks=related)
    session.add_all([case, PolicyVersion(policy_version=1, created_at=created)])
    result = planning.create_plan(session, case, actor="test:events", at=created)
    assert result["proposals"]
    attempt = session.get(CoverageAttempt, result["proposals"][0]["attempt_id"])
    attempt.approval_decision = "approve"
    attempt.approval_actor_id = "bp-test"
    attempt.approval_decided_at = created + timedelta(seconds=1)
    session.commit()
    with Session(session.get_bind()) as reserver:
        reservations.reserve_attempt_atomic(reserver, attempt.attempt_id,
                                            actor="test:reserve", at=created + timedelta(seconds=2))
    session.expire_all()
    dispatch.queue_offer(session, attempt, actor="test:offer", at=created + timedelta(seconds=3))
    session.commit()

    def override():
        with Session(session.get_bind()) as request_session:
            yield request_session

    app.dependency_overrides[get_session] = override
    with TestClient(app) as client:
        yield client, session, case.case_id, attempt.attempt_id, attempt.task_id, original_owner
    app.dependency_overrides.clear()


def _callback(client, attempt_id, event_type, event_id="event-in-1", reason=None):
    return client.post("/api/v1/integrations/attempt-events", headers={
        "X-Internal-Token": "test-only",
    }, json={
        "event_id": event_id, "event_type": event_type, "attempt_id": attempt_id,
        "channel": "slack", "occurred_at": datetime.now(UTC).isoformat(),
        "reason": reason,
    })


def test_acceptance_reassigns_source_only_once_after_authorized_response(offer_fixture):
    client, session, case_id, attempt_id, task_id, original_owner = offer_fixture
    attempt = session.get(CoverageAttempt, attempt_id)
    candidate_id = attempt.candidate_employee_id
    assert session.get(Task, task_id).assignee_employee_id == original_owner
    assert session.scalar(select(func.count()).select_from(TaskAssignment)) == 0
    accepted = _callback(client, attempt_id, "offer.accepted")
    assert accepted.status_code == 202, accepted.text
    session.expire_all()
    event = session.get(ProcessedEvent, "event-in-1")
    assert event.processed_at is not None, event.result
    assert event.result["status"] == "accepted"
    assert session.get(CoverageAttempt, attempt_id).status == AttemptStatus.ACCEPTED
    assert session.get(Task, task_id).assignee_employee_id == candidate_id
    assert session.get(CoverageAttempt, attempt_id).reservation.released_at is not None
    assert session.scalar(select(func.count()).select_from(TaskAssignment)) == 1
    repeat = client.post("/api/v1/integrations/attempt-events", headers={
        "X-Internal-Token": "test-only",
    }, json={
        "event_id": event.event_id, "event_type": event.event_type.value,
        "attempt_id": attempt_id, "channel": "slack",
        "occurred_at": event.occurred_at.isoformat(), "reason": None,
    })
    assert repeat.status_code == 202 and repeat.json()["duplicate"] is True
    assert session.scalar(select(func.count()).select_from(TaskAssignment)) == 1


def test_refusal_releases_capacity_and_replans_excluding_same_candidate(offer_fixture):
    client, session, case_id, attempt_id, task_id, original_owner = offer_fixture
    former = session.get(CoverageAttempt, attempt_id).candidate_employee_id
    response = _callback(client, attempt_id, "offer.refused", reason="Sem tempo")
    assert response.status_code == 202, response.text
    session.expire_all()
    old = session.get(CoverageAttempt, attempt_id)
    assert old.status == AttemptStatus.REFUSED
    assert old.reservation.released_at is not None
    assert session.get(Task, task_id).assignee_employee_id == original_owner
    newer = session.scalar(select(CoverageAttempt).where(
        CoverageAttempt.task_id == task_id,
        CoverageAttempt.plan_version > old.plan_version,
    ))
    assert newer is not None
    assert newer.candidate_employee_id != former
    assert newer.status in {AttemptStatus.RESERVED, AttemptStatus.PENDING_APPROVAL,
                             AttemptStatus.ESCALATED}
    assert session.get(Case, case_id).plan_version == 2


def test_expiration_frees_reservation_and_replans(offer_fixture):
    client, session, case_id, attempt_id, task_id, original_owner = offer_fixture
    attempt = session.get(CoverageAttempt, attempt_id)
    attempt.response_deadline_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    response = _callback(client, attempt_id, "offer.expired")
    assert response.status_code == 202, response.text
    session.expire_all()
    attempt = session.get(CoverageAttempt, attempt_id)
    assert attempt.status == AttemptStatus.EXPIRED
    assert attempt.reservation.released_at is not None
    assert session.get(Case, case_id).plan_version == 2


def test_new_candidate_absence_blocks_unsafe_acceptance(offer_fixture):
    client, session, case_id, attempt_id, task_id, original_owner = offer_fixture
    attempt = session.get(CoverageAttempt, attempt_id)
    shift = session.get(Shift, attempt.affected_task.shift_id)
    session.add(Absence(absence_id="candidate-now-absent",
                        employee_id=attempt.candidate_employee_id,
                        starts_at=shift.starts_at, ends_at=shift.ends_at,
                        confirmed=True, source_system="event-tests", external_id="evt-2",
                        updated_at=datetime.now(UTC)))
    session.commit()
    response = _callback(client, attempt_id, "offer.accepted")
    assert response.status_code == 202
    session.expire_all()
    event = session.get(ProcessedEvent, "event-in-1")
    assert event.response_status == 409
    assert event.result["error_code"] == "ACCEPTANCE_CONFLICT"
    assert session.get(CoverageAttempt, attempt_id).status == AttemptStatus.RESERVED
    assert session.get(Task, task_id).assignee_employee_id == original_owner
    assert session.scalar(select(func.count()).select_from(TaskAssignment)) == 0


def test_business_error_rolls_back_task_change_and_preserves_inbox(offer_fixture, monkeypatch):
    from app.services import event_processing

    client, session, case_id, attempt_id, task_id, original_owner = offer_fixture

    def fail_mid_transaction(worker_session, event, attempt, now):
        attempt.affected_task.assignee_employee_id = attempt.candidate_employee_id
        raise APIError(409, "TEST_CONFLICT", "Revalidação falhou", {})

    monkeypatch.setattr(event_processing, "_apply_accepted", fail_mid_transaction)
    response = _callback(client, attempt_id, "offer.accepted")
    assert response.status_code == 202
    session.expire_all()
    assert session.get(Task, task_id).assignee_employee_id == original_owner
    assert session.get(CoverageAttempt, attempt_id).reservation.released_at is None
    assert session.scalar(select(func.count()).select_from(TaskAssignment)) == 0
    event = session.get(ProcessedEvent, "event-in-1")
    assert event.result == {"status": "rejected", "error_code": "TEST_CONFLICT"}


def test_replan_after_refusal_is_idempotent(offer_fixture):
    client, session, case_id, attempt_id, task_id, original_owner = offer_fixture
    assert _callback(client, attempt_id, "offer.refused").status_code == 202
    from app.models import CoveragePlan

    before = session.scalar(select(func.count()).select_from(CoveragePlan))
    outcome = planning.replan_failed_task(lambda: Session(session.get_bind()),
                                          attempt_id, actor="test:retry")
    assert outcome["status"] == "already_replanned"
    assert session.scalar(select(func.count()).select_from(CoveragePlan)) == before
