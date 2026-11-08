"""Real HTTP tests of the authenticated, idempotent n8n callback inbox."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import get_session
from app.demo.seed import seed_demo
from app.enums import AttemptStatus, CaseStatus, Channel
from app.main import app
from app.models import (
    Case,
    CoverageAttempt,
    CoveragePlan,
    Employee,
    OutboundMessage,
    PolicyVersion,
    ProcessedEvent,
    Task,
)

TOKEN = "unit-test-token-not-a-real-secret"


@pytest.fixture
def callback_client(monkeypatch, session):
    monkeypatch.setenv("INTEGRATIONS_INTERNAL_TOKEN", TOKEN)
    seed_demo(session)
    task = session.scalar(select(Task).limit(1))
    candidate = session.scalar(
        select(Employee)
        .where(Employee.employee_id != task.assignee_employee_id)
        .limit(1)
    )
    now = datetime.now(UTC)
    created_at = now - timedelta(minutes=2)
    case = Case(
        case_id="cb-case",
        status=CaseStatus.OPEN,
        plan_version=1,
        created_at=created_at,
        tasks=[task],
    )
    policy = PolicyVersion(policy_version=1, created_at=created_at)
    session.add_all([case, policy])
    session.flush()
    plan = CoveragePlan(
        plan_id="cb-plan",
        case_id=case.case_id,
        plan_version=1,
        policy_version=1,
        created_at=created_at,
    )
    session.add(plan)
    session.flush()
    attempt = CoverageAttempt(
        attempt_id="cb-attempt",
        case_id=case.case_id,
        plan_id=plan.plan_id,
        plan_version=1,
        task_id=task.task_id,
        candidate_employee_id=candidate.employee_id,
        policy_version=1,
        status=AttemptStatus.NOTIFIED,
        response_deadline_at=now + timedelta(minutes=10),
        created_at=created_at,
    )
    session.add(attempt)
    session.flush()
    session.add(
        OutboundMessage(
            message_id="cb-message",
            event_id="out-cb",
            event_type="offer.created",
            attempt_id=attempt.attempt_id,
            channel=Channel.SLACK,
            channel_user_id="employee-test",
            message="Test offer",
            simulated=False,
            created_at=created_at,
        )
    )
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, session, attempt, task
    app.dependency_overrides.clear()


def data(event_id="cb-evt-1", event_type="offer.accepted", **changes):
    payload = {
        "event_id": event_id,
        "event_type": event_type,
        "attempt_id": "cb-attempt",
        "channel": "slack",
        "occurred_at": datetime.now(UTC).isoformat(),
        "reason": None,
    }
    payload.update(changes)
    return payload


def send(client, payload, token=TOKEN):
    return client.post(
        "/api/v1/integrations/attempt-events",
        json=payload,
        headers={"X-Internal-Token": token},
    )


def test_receipt_is_durable_and_duplicate_is_idempotent(callback_client):
    client, session, attempt, task = callback_client
    payload = data()
    first = send(client, payload)
    assert first.status_code == 202
    assert first.json() == {
        "event_id": "cb-evt-1",
        "status": "queued",
        "duplicate": False,
    }
    repeat = send(client, payload)
    assert repeat.status_code == 202
    assert repeat.json()["duplicate"] is True
    events = session.scalars(select(ProcessedEvent)).all()
    assert len(events) == 1
    assert events[0].processed_at is None
    assert events[0].result is None
    session.refresh(attempt)
    session.refresh(task)
    assert attempt.status == AttemptStatus.NOTIFIED
    assert task.assignee_employee_id != attempt.candidate_employee_id


@pytest.mark.parametrize(
    "event_type", ["offer.refused", "offer.delivered", "offer.delivery_failed"]
)
def test_supported_event_types_are_accepted(callback_client, event_type):
    client, session, *_ = callback_client
    response = send(client, data(event_type=event_type))
    assert response.status_code == 202
    assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 1


def test_reusing_event_id_with_different_payload_conflicts(callback_client):
    client, session, *_ = callback_client
    payload = data()
    assert send(client, payload).status_code == 202
    assert send(client, {**payload, "event_type": "offer.refused"}).status_code == 409
    assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 1


def test_second_decision_with_new_id_conflicts(callback_client):
    client, session, *_ = callback_client
    assert send(client, data()).status_code == 202
    assert send(client, data("cb-evt-2", "offer.refused")).status_code == 409
    assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 1


def test_missing_wrong_and_unconfigured_auth_are_rejected(callback_client, monkeypatch):
    client, session, *_ = callback_client
    payload = data()
    assert (
        client.post("/api/v1/integrations/attempt-events", json=payload).status_code
        == 401
    )
    assert send(client, payload, "wrong").status_code == 401
    monkeypatch.delenv("INTEGRATIONS_INTERNAL_TOKEN")
    assert send(client, payload).status_code == 503
    assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 0


def test_unknown_attempt_and_wrong_channel_are_rejected(callback_client):
    client, session, *_ = callback_client
    assert send(client, data(attempt_id="missing")).status_code == 404
    assert send(client, data(channel="teams")).status_code == 409
    assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 0


def test_stale_and_terminal_attempt_never_reassign(callback_client):
    client, session, attempt, task = callback_client
    original = task.assignee_employee_id
    attempt.response_deadline_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    assert send(client, data()).status_code == 409
    attempt.status = AttemptStatus.EXPIRED
    session.commit()
    assert send(client, data("cb-evt-2", "offer.expired")).status_code == 409
    session.refresh(task)
    assert task.assignee_employee_id == original
    assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 0


def test_expiry_requires_elapsed_deadline(callback_client):
    client, session, attempt, *_ = callback_client
    assert send(client, data(event_type="offer.expired")).status_code == 409
    attempt.response_deadline_at = datetime.now(UTC) - timedelta(seconds=2)
    session.commit()
    response = send(client, data("cb-evt-expired", "offer.expired"))
    assert response.status_code == 202


def test_invalid_payload_is_rejected_without_writing(callback_client):
    client, session, *_ = callback_client
    # The application handler follows the contract: malformed payloads are 400.
    assert send(client, data(occurred_at="2026-11-08T12:00:00")).status_code == 400
    assert send(client, data(event_type="unexpected")).status_code == 400
    assert session.scalar(select(func.count()).select_from(ProcessedEvent)) == 0
