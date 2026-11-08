"""A08 integration: DB source -> Mateus engine -> audited, unreserved proposals."""

from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.demo.seed import seed_demo
from app.enums import AttemptStatus, CaseStatus, TaskStatus
from app.errors import APIError
from app.models import (
    Absence, AuditEvent, Case, CoverageAttempt, CoveragePlan, Employee, PolicyVersion,
    Reservation, Shift, Task, TaskAssignment, MessageDelivery, OutboundMessage,
)
from app.services import planning, snapshot
from app.services.reservations import reserve_attempt_atomic
from app.services.dispatch import offer_payload, queue_offer, send_queued_offer, dispatch_pending
from app.services.approvals import decide_atomic


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
    # Endpoint tests use the real clock: never build a proposal in its future.
    created = min(shift.starts_at + timedelta(minutes=1),
                  datetime.now(UTC) - timedelta(hours=1))
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


def test_concurrent_reservation_attempts_cannot_double_book(scenario):
    session, case, tasks, created = scenario
    result = planning.create_plan(session, case, actor="test:bridge",
                                  at=created + timedelta(seconds=1))
    attempt = session.get(CoverageAttempt, result["proposals"][0]["attempt_id"])
    attempt.approval_decision = "approve"
    attempt.approval_actor_id = "bp-test"
    attempt.approval_decided_at = created + timedelta(seconds=2)
    attempt_id = attempt.attempt_id
    session.commit()
    barrier = Barrier(2)

    def compete(_):
        barrier.wait(timeout=5)
        with Session(session.get_bind()) as worker:
            return reserve_attempt_atomic(worker, attempt_id,
                                          actor="test:concurrency").reservation_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        reservation_ids = list(pool.map(compete, range(2)))
    assert reservation_ids[0] == reservation_ids[1]
    session.expire_all()
    assert _count(session, Reservation) == 1


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


def _queued_offer(scenario):
    session, case, tasks, created = scenario
    result = planning.create_plan(session, case, actor="test:bridge",
                                  at=created + timedelta(seconds=1))
    assert result["proposals"]
    attempt = session.get(CoverageAttempt, result["proposals"][0]["attempt_id"])
    attempt.approval_decision = "approve"
    attempt.approval_actor_id = "bp-test"
    attempt.approval_decided_at = created + timedelta(seconds=2)
    session.commit()
    with Session(session.get_bind()) as reserver:
        reserve_attempt_atomic(reserver, attempt.attempt_id,
                               actor="test:reserve", at=created + timedelta(seconds=3))
    session.expire_all()
    offer = queue_offer(session, attempt, actor="test:offer",
                        at=created + timedelta(seconds=4))
    offer_again = queue_offer(session, attempt, actor="test:offer",
                              at=created + timedelta(seconds=5))
    assert offer.message_id == offer_again.message_id
    payload = offer_payload(offer)
    session.commit()
    return offer.message_id, payload


def test_offer_created_payload_and_durable_delivery_are_idempotent(scenario):
    session, case, tasks, created = scenario
    message_id, payload = _queued_offer(scenario)
    assert payload["event_type"] == "offer.created"
    assert payload["channel"] == "slack"
    assert set(payload) == {
        "event_id", "event_type", "case_id", "attempt_id", "task_id",
        "task_title", "estimated_hours", "due_at", "candidate_employee_id",
        "candidate_name", "channel", "channel_user_id",
        "response_deadline_at", "message",
    }
    transmitted = []

    def fake_post(url, *, json, headers, timeout):
        transmitted.append((url, json, headers, timeout))
        return type("Response", (), {"status_code": 202})()

    maker = lambda: Session(session.get_bind())
    sent = send_queued_offer(maker, message_id, url="https://n8n.test/webhook",
                             token="dummy-private", post=fake_post)
    again = send_queued_offer(maker, message_id, url="https://n8n.test/webhook",
                              token="dummy-private", post=fake_post)
    assert sent == {"event_id": payload["event_id"], "status": "sent", "duplicate": False}
    assert again["duplicate"] is True
    assert len(transmitted) == 1
    assert transmitted[0][1] == payload
    assert transmitted[0][2] == {"X-Internal-Token": "dummy-private"}
    assert "dummy-private" not in str(transmitted[0][1])
    session.expire_all()
    assert _count(session, OutboundMessage) == 1
    assert _count(session, MessageDelivery) == 1
    assert session.get(CoverageAttempt, payload["attempt_id"]).status == AttemptStatus.NOTIFIED
    assert _count(session, TaskAssignment) == 0


def test_failed_delivery_remains_reserved_and_reuses_event_id(scenario):
    session, case, tasks, created = scenario
    message_id, payload = _queued_offer(scenario)
    maker = lambda: Session(session.get_bind())

    def fail_post(url, *, json, headers, timeout):
        return type("Response", (), {"status_code": 503})()

    with pytest.raises(APIError) as exc:
        send_queued_offer(maker, message_id, url="https://n8n.test/webhook",
                          token="dummy-private", post=fail_post)
    assert exc.value.code == "N8N_DISPATCH_FAILED"
    session.expire_all()
    assert session.get(CoverageAttempt, payload["attempt_id"]).status == AttemptStatus.RESERVED
    assert _count(session, MessageDelivery) == 1
    sent = send_queued_offer(maker, message_id, url="https://n8n.test/webhook",
                             token="dummy-private",
                             post=lambda *args, **kwargs: type("Response", (), {"status_code": 200})())
    assert sent["event_id"] == payload["event_id"]
    assert _count(session, MessageDelivery) == 2


def test_dispatch_pending_retries_unsent_offers_without_using_real_n8n(scenario, monkeypatch):
    session, case, tasks, created = scenario
    message_id, payload = _queued_offer(scenario)
    monkeypatch.setenv("N8N_DISPATCH_URL", "https://n8n.test/webhook")
    monkeypatch.setenv("N8N_DISPATCH_TOKEN", "test-only")
    sent = []

    def fake_post(url, *, json, headers, timeout):
        sent.append(json["event_id"])
        return type("Response", (), {"status_code": 200})()

    monkeypatch.setattr("app.services.dispatch.httpx.post", fake_post)
    maker = lambda: Session(session.get_bind())
    assert dispatch_pending(maker, case_id=case.case_id) == {"sent": 1, "failed": 0}
    assert dispatch_pending(maker, case_id=case.case_id) == {"sent": 0, "failed": 0}
    assert sent == [payload["event_id"]]


def _pending_bp(scenario):
    session, case, tasks, created = scenario
    result = planning.create_plan(session, case, actor="test:plan",
                                  at=created + timedelta(seconds=1))
    attempt = session.get(CoverageAttempt, result["proposals"][0]["attempt_id"])
    attempt.status = AttemptStatus.PENDING_APPROVAL
    session.commit()
    return attempt.attempt_id, created


def test_bp_approval_reserves_and_queues_atomically(scenario):
    session, case, tasks, created = scenario
    attempt_id, created = _pending_bp(scenario)
    with Session(session.get_bind()) as decider:
        response = decide_atomic(decider, attempt_id, decision="approve",
                                 actor_id="bp-demo", reason="Cobertura autorizada",
                                 at=created + timedelta(seconds=2))
    assert response["status"] == "reserved"
    session.expire_all()
    attempt = session.get(CoverageAttempt, attempt_id)
    assert attempt.status == AttemptStatus.RESERVED
    assert attempt.approval_decision == "approve"
    assert attempt.approval_actor_id == "bp-demo"
    assert _count(session, Reservation) == 1
    assert _count(session, OutboundMessage) == 1
    with Session(session.get_bind()) as decider:
        duplicate = decide_atomic(decider, attempt_id, decision="approve",
                                  actor_id="bp-demo", reason="Cobertura autorizada")
    assert duplicate["duplicate"] is True
    assert _count(session, OutboundMessage) == 1


def test_bp_rejection_never_reserves_or_queues(scenario):
    session, case, tasks, created = scenario
    attempt_id, created = _pending_bp(scenario)
    with Session(session.get_bind()) as decider:
        response = decide_atomic(decider, attempt_id, decision="reject",
                                 actor_id="bp-demo", reason="Sem substituição viável",
                                 at=created + timedelta(seconds=2))
    assert response["status"] == "rejected_by_bp"
    session.expire_all()
    assert session.get(CoverageAttempt, attempt_id).status == AttemptStatus.REJECTED_BY_BP
    assert _count(session, Reservation) == 0
    assert _count(session, OutboundMessage) == 0
    assert case.status == CaseStatus.PLANNING


def test_bp_approval_endpoint_uses_contract_body(scenario, monkeypatch):
    from app.db import get_session
    from app.main import app
    from app.api.v1 import proposals

    session, case, tasks, created = scenario
    attempt_id, created = _pending_bp(scenario)

    def override():
        with Session(session.get_bind()) as s:
            yield s

    app.dependency_overrides[get_session] = override
    monkeypatch.setenv("N8N_DISPATCH_URL", "https://n8n.test/webhook")
    monkeypatch.setenv("N8N_DISPATCH_TOKEN", "test-only")
    dispatched = []
    monkeypatch.setattr(proposals, "dispatch_pending", lambda factory, case_id: dispatched.append(case_id))
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/proposals/{attempt_id}/approval",
                json={"decision": "approve", "actor_id": "bp-demo", "reason": "Autorizado"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "reserved"
        assert dispatched == [case.case_id]
    finally:
        app.dependency_overrides.clear()


def test_post_plan_http_classifies_reserves_and_prepares_outbox(scenario, monkeypatch):
    from app.db import get_session
    from app.main import app
    from app.api.v1 import cases as cases_router

    session, case, tasks, created = scenario
    before = {t.task_id: t.assignee_employee_id for t in tasks}

    def override():
        with Session(session.get_bind()) as s:
            yield s

    app.dependency_overrides[get_session] = override
    monkeypatch.setenv("N8N_DISPATCH_URL", "https://n8n.test/webhook")
    monkeypatch.setenv("N8N_DISPATCH_TOKEN", "test-only")
    dispatched = []
    monkeypatch.setattr(cases_router, "dispatch_pending", lambda factory, case_id: dispatched.append(case_id))
    try:
        with TestClient(app) as client:
            response = client.post(f"/api/v1/cases/{case.case_id}/plan")
            second = client.post(f"/api/v1/cases/{case.case_id}/plan")
        assert response.status_code == 200, response.text
        assert second.status_code == 409
        body = response.json()
        assert set(body) == {"case_id", "plan_id", "plan_version", "proposals", "uncovered"}
        assert body["plan_version"] == 1
        assert {p["status"] for p in body["proposals"]} <= {"reserved", "pending_approval"}
        assert all(p["policy_action"] in {"auto", "needs_approval"}
                   for p in body["proposals"])
        assert len(body["proposals"]) + len(body["uncovered"]) == len(tasks)
        assert _count(session, Reservation) == sum(
            p["policy_action"] == "auto" for p in body["proposals"])
        assert _count(session, OutboundMessage) == _count(session, Reservation)
        assert {t.task_id: t.assignee_employee_id for t in tasks} == before
        assert dispatched == [case.case_id]
    finally:
        app.dependency_overrides.clear()
