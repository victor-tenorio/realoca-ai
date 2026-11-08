from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.demo.seed import seed_demo
from app.enums import AttemptStatus, TaskStatus
from app.main import app
from app.models import (
    Absence,
    AuditEvent,
    Case,
    CoverageAttempt,
    CoveragePlan,
    Employee,
    PolicyVersion,
    Reservation,
    Shift,
    Task,
    TaskAssignment,
)
from app.models.workflow import case_absences, case_tasks

REFERENCE = date(2026, 11, 8)
PREVIOUS = "65aad520e5e0"
PAYLOAD = {
    "employee_id": "demo-atendimento-01",
    "starts_at": "2026-11-08T08:00:00-03:00",
    "ends_at": "2026-11-08T16:00:00-03:00",
    "confirmed": True,
    "source_system": "hr_simulator",
    "external_id": "absence-query-001",
}


@pytest.fixture
def client(database, monkeypatch):
    from app.services import task_source

    monkeypatch.setattr(task_source, "DEMO_REFERENCE_DATE", REFERENCE)

    def temporary_session():
        with Session(database[0]) as session:
            yield session

    app.dependency_overrides[get_session] = temporary_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def seeded(session):
    seed_demo(session, REFERENCE)
    session.commit()


def counts(session):
    return [
        session.scalar(select(func.count()).select_from(table))
        for table in (Absence, Case, case_absences, case_tasks, AuditEvent)
    ]


def test_confirmed_creation_task_links_audit_and_no_side_effects(
    client, session, seeded
):
    tasks = list(
        session.scalars(
            select(Task).where(Task.assignee_employee_id == PAYLOAD["employee_id"])
        )
    )
    tasks[0].status = TaskStatus.DONE
    # transfer_allowed is a planning rule, not a reason to hide an affected task.
    tasks[1].transfer_allowed = False
    session.commit()
    expected = {task.task_id for task in tasks if task.status != TaskStatus.DONE}
    before = list(
        session.execute(
            select(
                Task.task_id,
                Task.assignee_employee_id,
                Task.estimated_hours,
                Task.status,
            )
        )
    )
    response = client.post("/api/v1/absences", json=PAYLOAD)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"absence_id", "case_id", "status"}
    assert body["status"] == "open"
    session.expire_all()
    absence = session.get(Absence, body["absence_id"])
    case = session.get(Case, body["case_id"])
    assert absence.confirmed is True
    assert absence.employee_id == PAYLOAD["employee_id"]
    assert {task.task_id for task in case.tasks} == expected
    assert case.absences == [absence]
    assert case.plan_version == 0 and case.closed_at is None
    events = list(
        session.scalars(select(AuditEvent).where(AuditEvent.case_id == case.case_id))
    )
    assert {event.action for event in events} == {
        "absence.confirmed",
        "case.opened",
        "impact.detected",
    }
    assert all(event.policy_version is None for event in events)
    divergence = next(event for event in events if event.action == "impact.detected")
    assert set(divergence.result["task_ids"]) == expected
    assert divergence.result["employee_id"] == PAYLOAD["employee_id"]
    assert divergence.result["divergence_detected"] is True
    assert before == list(
        session.execute(
            select(
                Task.task_id,
                Task.assignee_employee_id,
                Task.estimated_hours,
                Task.status,
            )
        )
    )
    assert session.scalar(select(func.count()).select_from(Reservation)) == 0
    assert session.scalar(select(func.count()).select_from(TaskAssignment)) == 0
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/employees").status_code == 200
    assert client.get("/api/v1/teams").status_code == 200
    assert client.get("/api/v1/tasks").status_code == 200


def test_identical_retry_and_equivalent_timezone_do_not_duplicate(
    client, session, seeded
):
    first = client.post("/api/v1/absences", json=PAYLOAD)
    snapshot = counts(session)
    retry = client.post(
        "/api/v1/absences",
        json={
            **PAYLOAD,
            "starts_at": "2026-11-08T11:00:00Z",
            "ends_at": "2026-11-08T19:00:00Z",
        },
    )
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert counts(session) == snapshot


@pytest.mark.parametrize(
    "change",
    [
        {"ends_at": "2026-11-08T17:00:00-03:00"},
        {"employee_id": "demo-atendimento-02"},
    ],
)
def test_external_id_conflict_does_not_overwrite(client, session, seeded, change):
    first = client.post("/api/v1/absences", json=PAYLOAD).json()
    before = counts(session)
    response = client.post("/api/v1/absences", json={**PAYLOAD, **change})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXTERNAL_ID_CONFLICT"
    assert response.json()["error"]["details"]["case_id"] == first["case_id"]
    assert counts(session) == before


@pytest.mark.parametrize(
    "starts,ends",
    [
        ("07:00:00", "09:00:00"),
        ("15:00:00", "17:00:00"),
        ("09:00:00", "10:00:00"),
        ("07:00:00", "17:00:00"),
        ("08:00:00", "16:00:00"),
    ],
)
def test_overlap_conflict(client, session, seeded, starts, ends):
    first = client.post("/api/v1/absences", json=PAYLOAD).json()
    response = client.post(
        "/api/v1/absences",
        json={
            **PAYLOAD,
            "external_id": "another",
            "starts_at": f"2026-11-08T{starts}-03:00",
            "ends_at": f"2026-11-08T{ends}-03:00",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ABSENCE_OVERLAP"
    assert response.json()["error"]["details"]["case_id"] == first["case_id"]
    assert counts(session)[0:2] == [1, 1]


@pytest.mark.parametrize(
    "starts,ends", [("07:00:00", "08:00:00"), ("16:00:00", "17:00:00")]
)
def test_adjacent_intervals_are_allowed(client, session, seeded, starts, ends):
    assert client.post("/api/v1/absences", json=PAYLOAD).status_code == 201
    response = client.post(
        "/api/v1/absences",
        json={
            **PAYLOAD,
            "external_id": "adjacent",
            "starts_at": f"2026-11-08T{starts}-03:00",
            "ends_at": f"2026-11-08T{ends}-03:00",
        },
    )
    assert response.status_code == 201
    assert counts(session)[0:2] == [2, 2]


def test_external_scope_is_source_plus_id(client, session, seeded):
    assert client.post("/api/v1/absences", json=PAYLOAD).status_code == 201
    response = client.post(
        "/api/v1/absences",
        json={
            **PAYLOAD,
            "source_system": "other_hr",
            "employee_id": "demo-atendimento-02",
        },
    )
    assert response.status_code == 201


@pytest.mark.parametrize(
    "change,status",
    [
        ({"employee_id": "missing"}, 404),
        ({"starts_at": "2026-11-08T08:00:00"}, 400),
        ({"ends_at": "2026-11-08T08:00:00-03:00"}, 400),
        ({"ends_at": "2026-11-08T07:00:00-03:00"}, 400),
        ({"confirmed": False}, 422),
        ({"confirmed": "true"}, 400),
        ({"diagnosis": "forbidden"}, 400),
        ({"external_id": ""}, 400),
        ({"starts_at": 1794124800}, 400),
    ],
)
def test_invalid_requests_are_standard_and_leave_no_data(
    client, session, seeded, change, status
):
    response = client.post("/api/v1/absences", json={**PAYLOAD, **change})
    assert response.status_code == status
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message", "details"}
    assert "forbidden" not in response.text
    assert counts(session) == [0, 0, 0, 0, 0]


def test_employee_without_open_tasks_remains_open(client, session, seeded):
    for task in session.scalars(
        select(Task).where(Task.assignee_employee_id == PAYLOAD["employee_id"])
    ):
        task.status = TaskStatus.DONE
    session.commit()
    response = client.post("/api/v1/absences", json=PAYLOAD)
    assert response.status_code == 201
    case = session.get(Case, response.json()["case_id"])
    assert case.status == "open" and case.tasks == [] and case.closed_at is None
    event = session.scalar(
        select(AuditEvent).where(AuditEvent.action == "impact.no_registered_tasks")
    )
    assert event.result["task_ids"] == []
    assert event.result["coverage_confirmed"] is False


def test_other_period_tasks_are_not_linked(client, session, seeded):
    original = session.scalar(
        select(Task).where(Task.assignee_employee_id == PAYLOAD["employee_id"])
    )
    shift = session.scalar(select(Shift))
    other = Shift(
        shift_id="other",
        reference_date=REFERENCE + timedelta(days=1),
        starts_at=shift.starts_at + timedelta(days=1),
        ends_at=shift.ends_at + timedelta(days=1),
    )
    session.add(other)
    session.flush()
    session.add(
        Task(
            task_id="other-task",
            title="Another period",
            assignee_employee_id=PAYLOAD["employee_id"],
            team_id=original.team_id,
            shift=other,
            priority=original.priority,
            due_at=other.ends_at,
            estimated_hours=1,
            status=TaskStatus.OPEN,
            transfer_allowed=True,
            required_skills_known=True,
            source_system="task_fixture",
            external_id="other-task",
            updated_at=shift.starts_at,
        )
    )
    session.commit()
    response = client.post(
        "/api/v1/absences", json={**PAYLOAD, "ends_at": "2026-11-09T16:00:00-03:00"}
    )
    assert response.status_code == 201
    assert "other-task" not in {
        task.task_id for task in session.get(Case, response.json()["case_id"]).tasks
    }


def test_audit_failure_rolls_back_everything(client, session, seeded, monkeypatch):
    from app.services import audit

    original_record = audit.record
    calls = []

    def fail(transaction_session, **kwargs):
        calls.append(kwargs["action"])
        if len(calls) == 2:
            raise RuntimeError("internal failure, must not leak")
        original_record(transaction_session, **kwargs)
        transaction_session.flush()

    monkeypatch.setattr(audit, "record", fail)
    response = client.post("/api/v1/absences", json=PAYLOAD)
    assert response.status_code == 500
    assert len(calls) == 2
    assert "must not leak" not in response.text
    assert counts(session) == [0, 0, 0, 0, 0]


@pytest.mark.parametrize("same_id", [True, False])
def test_simultaneous_requests_are_serialized(client, session, seeded, same_id):
    barrier = Barrier(2)

    def post(index):
        barrier.wait(timeout=10)
        payload = {
            **PAYLOAD,
            "external_id": PAYLOAD["external_id"] if same_id else f"parallel-{index}",
        }
        return client.post("/api/v1/absences", json=payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(post, range(2)))
    assert sorted(result.status_code for result in results) == (
        [200, 201] if same_id else [201, 409]
    )
    assert counts(session) == [1, 1, 1, 5, 3]
    bodies = [response.json() for response in results]
    case_ids = [
        body["case_id"] if "case_id" in body else body["error"]["details"]["case_id"]
        for body in bodies
    ]
    assert len(set(case_ids)) == 1


def test_migration_and_database_overlap_guard(database, session, seeded):
    _, config = database
    command.check(config)
    shift = session.scalar(select(Shift))
    first = Absence(
        absence_id="raw-1",
        employee_id=PAYLOAD["employee_id"],
        starts_at=shift.starts_at,
        ends_at=shift.ends_at,
        confirmed=True,
        source_system="hr_fixture",
        external_id="raw-1",
        updated_at=shift.starts_at,
    )
    session.add(first)
    session.commit()
    session.add(
        Absence(
            absence_id="raw-2",
            employee_id=PAYLOAD["employee_id"],
            starts_at=shift.starts_at,
            ends_at=shift.ends_at,
            confirmed=True,
            source_system="hr_fixture",
            external_id="raw-2",
            updated_at=shift.starts_at,
        )
    )
    with pytest.raises(IntegrityError, match="absence_overlap"):
        session.flush()
    session.rollback()


def test_incremental_migration_downgrade_empty(database):
    engine, config = database
    command.downgrade(config, PREVIOUS)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1


def test_migration_preserves_old_audit_and_blocks_lossy_downgrade(
    client, session, database, seeded
):
    engine, config = database
    now = session.scalar(select(Shift.starts_at))
    session.add(PolicyVersion(policy_version=1, created_at=now))
    session.flush()
    session.add(
        AuditEvent(
            audit_event_id="legacy-audit",
            actor="legacy-test",
            action="policy.created",
            timestamp=now,
            policy_version=1,
            result={"legacy": True},
        )
    )
    session.commit()
    session.close()
    command.downgrade(config, PREVIOUS)
    command.upgrade(config, "head")
    with Session(engine) as verification:
        assert verification.get(AuditEvent, "legacy-audit").result == {"legacy": True}
        assert verification.scalar(select(func.count()).select_from(Employee)) == 40
        assert verification.scalar(select(func.count()).select_from(Task)) == 187
    assert client.post("/api/v1/absences", json=PAYLOAD).status_code == 201
    with pytest.raises(RuntimeError, match="Downgrade blocked"):
        command.downgrade(config, PREVIOUS)
    with Session(engine) as verification:
        assert verification.scalar(select(func.count()).select_from(AuditEvent)) == 4
        with pytest.raises(IntegrityError):
            verification.execute(text("DELETE FROM audit_events"))
        verification.rollback()


def test_retry_keeps_original_task_links_and_current_case_status(
    client, session, seeded
):
    original = client.post("/api/v1/absences", json=PAYLOAD).json()
    case = session.get(Case, original["case_id"])
    affected = {task.task_id for task in case.tasks}
    candidate = session.scalar(
        select(Employee).where(Employee.employee_id != PAYLOAD["employee_id"])
    )
    case.tasks[0].assignee = candidate
    case.status = "planning"  # persistence fixture, not a new API transition
    session.commit()
    before = counts(session)
    response = client.post("/api/v1/absences", json=PAYLOAD)
    assert response.status_code == 200
    assert response.json() == {**original, "status": "planning"}
    session.expire_all()
    assert {task.task_id for task in case.tasks} == affected
    assert counts(session) == before


def test_unconfirmed_import_and_missing_case_are_not_silently_repaired(
    client, session, seeded
):
    shift = session.scalar(select(Shift))
    absence = Absence(
        absence_id="imported",
        employee_id=PAYLOAD["employee_id"],
        starts_at=shift.starts_at,
        ends_at=shift.ends_at,
        confirmed=False,
        source_system=PAYLOAD["source_system"],
        external_id=PAYLOAD["external_id"],
        updated_at=shift.starts_at,
    )
    session.add(absence)
    session.commit()
    response = client.post("/api/v1/absences", json=PAYLOAD)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EXTERNAL_ID_CONFLICT"
    absence.confirmed = True
    session.commit()
    response = client.post("/api/v1/absences", json=PAYLOAD)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ABSENCE_CASE_MISSING"
    assert counts(session) == [1, 0, 0, 0, 0]


def test_registration_preserves_existing_reservation_load_and_assignment_history(
    client, session, seeded
):
    from app.services.capacity import employee_capacity

    shift = session.scalar(select(Shift))
    task = session.scalar(
        select(Task).where(Task.assignee_employee_id == PAYLOAD["employee_id"])
    )
    candidate = session.scalar(
        select(Employee).where(Employee.employee_id != PAYLOAD["employee_id"])
    )
    now = shift.starts_at
    session.add(PolicyVersion(policy_version=1, created_at=now))
    session.add(Case(case_id="prior-case", created_at=now, tasks=[task]))
    session.flush()
    session.add(
        CoveragePlan(
            plan_id="prior-plan",
            case_id="prior-case",
            plan_version=1,
            policy_version=1,
            created_at=now,
        )
    )
    session.flush()
    session.add(
        CoverageAttempt(
            attempt_id="prior-attempt",
            case_id="prior-case",
            plan_id="prior-plan",
            plan_version=1,
            task_id=task.task_id,
            candidate_employee_id=candidate.employee_id,
            policy_version=1,
            status=AttemptStatus.RESERVED,
            created_at=now,
            response_deadline_at=now + timedelta(minutes=15),
        )
    )
    session.flush()
    session.add(
        Reservation(
            reservation_id="prior-reservation",
            attempt_id="prior-attempt",
            reserved_hours=1,
            created_at=now,
        )
    )
    session.add(
        TaskAssignment(
            assignment_id="prior-history",
            task_id=task.task_id,
            from_employee_id=None,
            to_employee_id=PAYLOAD["employee_id"],
            occurred_at=now,
            reason="Synthetic import history",
        )
    )
    session.commit()
    before = {
        employee_id: employee_capacity(session, employee_id, shift.shift_id)
        for employee_id in (PAYLOAD["employee_id"], candidate.employee_id)
    }
    response = client.post("/api/v1/absences", json=PAYLOAD)
    assert response.status_code == 201
    session.expire_all()
    after = {
        employee_id: employee_capacity(session, employee_id, shift.shift_id)
        for employee_id in before
    }
    assert after == before
    assert session.get(Reservation, "prior-reservation").released_at is None
    assert (
        session.get(CoverageAttempt, "prior-attempt").status == AttemptStatus.RESERVED
    )
    assert task.assignee_employee_id == PAYLOAD["employee_id"]
    assert session.scalar(select(func.count()).select_from(Reservation)) == 1
    assert session.scalar(select(func.count()).select_from(TaskAssignment)) == 1
