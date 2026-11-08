from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
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
)
from app.models.workflow import case_tasks
from app.services import impact

REFERENCE = date(2026, 11, 8)
PAYLOAD = {
    "employee_id": "demo-atendimento-01",
    "starts_at": "2026-11-08T08:00:00-03:00",
    "ends_at": "2026-11-08T16:00:00-03:00",
    "confirmed": True,
    "source_system": "hr_simulator",
    "external_id": "impact-absence",
}


@pytest.fixture
def setup(database, session, monkeypatch):
    from app.services import task_source

    monkeypatch.setattr(task_source, "DEMO_REFERENCE_DATE", REFERENCE)
    seed_demo(session, REFERENCE)
    session.commit()

    def temporary_session():
        with Session(database[0]) as transaction:
            yield transaction

    app.dependency_overrides[get_session] = temporary_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, session, database[0]
    finally:
        app.dependency_overrides.pop(get_session, None)


def observation(session, case_id):
    return session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.case_id == case_id, AuditEvent.action.in_(impact.IMPACT_ACTIONS)
        )
        .order_by(AuditEvent.timestamp.desc())
    )


def reanalyze(engine, response):
    with Session(engine) as transaction:
        return impact.analyze_case(
            transaction, response["case_id"], response["absence_id"]
        )


def test_initial_known_impact_evidence_and_identical_reanalysis(setup):
    client, session, engine = setup
    tasks = list(
        session.scalars(
            select(Task).where(Task.assignee_employee_id == PAYLOAD["employee_id"])
        )
    )
    tasks[0].status = TaskStatus.DONE
    session.commit()
    expected = {task.task_id for task in tasks if task.status != TaskStatus.DONE}
    expected_hours = sum(
        (task.estimated_hours for task in tasks if task.status != TaskStatus.DONE),
        Decimal(0),
    )
    response = client.post("/api/v1/absences", json=PAYLOAD)
    assert response.status_code == 201
    ids = response.json()
    initial = observation(session, ids["case_id"])
    original_payload = dict(initial.result)
    assert set(initial.result["task_ids"]) == expected
    assert initial.result["hours_at_risk"] == float(expected_hours)
    assert initial.result["known_hours_at_risk"] == float(expected_hours)
    assert initial.result["estimates_complete"] and initial.result["data_complete"]
    assert len(initial.result["divergences"]) == len(expected)
    assert initial.result["detected_at"] == initial.timestamp.isoformat()
    for evidence in initial.result["divergences"]:
        assert evidence["absence_id"] == ids["absence_id"]
        assert evidence["source_system"] == "task_simulator"
        assert evidence["external_id"] and evidence["task_updated_at"]
        assert evidence["correction_confirmed"] is False
    before = session.scalar(select(func.count()).select_from(AuditEvent))
    report = reanalyze(engine, ids)
    assert report.changed is False
    assert report.current.hours_at_risk == expected_hours
    assert report.original == original_payload
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == before
    retry = client.post("/api/v1/absences", json=PAYLOAD)
    assert retry.status_code == 200 and retry.json() == ids
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == before


def test_missing_estimate_and_skills_are_quality_issues_not_zero(setup):
    client, session, engine = setup
    tasks = list(
        session.scalars(
            select(Task).where(Task.assignee_employee_id == PAYLOAD["employee_id"])
        )
    )
    tasks[0].estimated_hours = None
    tasks[0].required_skills_known = False
    tasks[1].required_skills = []
    tasks[1].required_skills_known = True
    session.commit()
    ids = client.post("/api/v1/absences", json=PAYLOAD).json()
    report = reanalyze(engine, ids)
    assert report.current.hours_at_risk is None
    assert report.current.known_hours_at_risk == sum(
        (task.estimated_hours for task in tasks if task.estimated_hours is not None),
        Decimal(0),
    )
    payload = report.current.payload
    assert payload["hours_at_risk"] is None and not payload["estimates_complete"]
    assert not payload["data_complete"]
    quality = next(
        issue
        for issue in payload["data_quality_issues"]
        if issue["task_id"] == tasks[0].task_id
    )
    assert quality["kind"] == "data_quality"
    assert (
        "estimated_hours" in quality["fields"]
        and "required_skills" in quality["fields"]
    )
    evidence = {row["task_id"]: row for row in payload["tasks"]}
    assert evidence[tasks[0].task_id]["required_skills"] is None
    assert evidence[tasks[1].task_id]["required_skills"] == []
    assert len(payload["divergences"]) == len(
        tasks
    )  # quality does not hide operational divergence


def test_completion_and_transfer_keep_original_history(setup):
    client, session, engine = setup
    ids = client.post("/api/v1/absences", json=PAYLOAD).json()
    original_event = observation(session, ids["case_id"])
    baseline = dict(original_event.result)
    tasks = list(
        session.scalars(
            select(Task).where(Task.assignee_employee_id == PAYLOAD["employee_id"])
        )
    )
    original_ids = set(baseline["task_ids"])
    tasks[0].status = TaskStatus.DONE
    candidate = session.scalar(
        select(Employee).where(Employee.team_id == "demo-tecnologia")
    )
    original_team = tasks[1].team_id
    tasks[1].assignee = candidate
    session.commit()
    report = reanalyze(engine, ids)
    assert report.changed
    assert set(report.current.payload["historical_task_ids"]) == original_ids
    assert len(report.current.payload["task_ids"]) == len(original_ids) - 2
    historical = {
        row["task_id"]: row for row in report.current.payload["historical_tasks"]
    }
    assert historical[tasks[0].task_id]["status"] == "done"
    assert historical[tasks[1].task_id]["team_id"] == original_team
    assert historical[tasks[1].task_id]["assignee_team_id"] == "demo-tecnologia"
    assert report.original == baseline
    session.refresh(original_event)
    assert original_event.result == baseline
    assert (
        set(
            session.scalars(
                select(case_tasks.c.task_id).where(
                    case_tasks.c.case_id == ids["case_id"]
                )
            )
        )
        == original_ids
    )
    assert session.get(Case, ids["case_id"]).status == "open"
    assert not reanalyze(engine, ids).changed


def test_newly_observed_task_adds_one_link_and_one_observation(setup):
    client, session, engine = setup
    ids = client.post("/api/v1/absences", json=PAYLOAD).json()
    task = session.scalar(
        select(Task).where(Task.assignee_employee_id != PAYLOAD["employee_id"])
    )
    task.assignee_employee_id = PAYLOAD["employee_id"]
    session.commit()
    before = session.scalar(select(func.count()).select_from(AuditEvent))
    assert reanalyze(engine, ids).changed
    assert not reanalyze(engine, ids).changed
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == before + 1
    assert task.task_id in set(
        session.scalars(
            select(case_tasks.c.task_id).where(case_tasks.c.case_id == ids["case_id"])
        )
    )


@pytest.mark.parametrize(
    "starts,ends,count",
    [
        ("07:00:00", "08:00:00", 0),
        ("16:00:00", "17:00:00", 0),
        ("15:59:59", "16:00:00", 5),
    ],
)
def test_temporal_boundaries_use_shift_not_due_date(setup, starts, ends, count):
    client, session, engine = setup
    task = session.scalar(
        select(Task).where(Task.assignee_employee_id == PAYLOAD["employee_id"])
    )
    task.due_at += timedelta(days=3)
    session.commit()
    ids = client.post(
        "/api/v1/absences",
        json={
            **PAYLOAD,
            "starts_at": f"2026-11-08T{starts}-03:00",
            "ends_at": f"2026-11-08T{ends}-03:00",
        },
    ).json()
    report = reanalyze(engine, ids)
    assert report.current.payload["task_count"] == count
    assert report.current.hours_at_risk == (Decimal("5.5") if count else Decimal(0))


def test_explicit_reanalysis_failure_rolls_back_links_and_events(setup, monkeypatch):
    from app.services import audit

    client, session, engine = setup
    ids = client.post("/api/v1/absences", json=PAYLOAD).json()
    task = session.scalar(
        select(Task).where(Task.assignee_employee_id != PAYLOAD["employee_id"])
    )
    task.assignee_employee_id = PAYLOAD["employee_id"]
    session.commit()
    before = session.scalar(select(func.count()).select_from(AuditEvent))

    def fail(*args, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(audit, "record", fail)
    with pytest.raises(RuntimeError, match="injected"):
        reanalyze(engine, ids)
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == before
    assert task.task_id not in set(
        session.scalars(
            select(case_tasks.c.task_id).where(case_tasks.c.case_id == ids["case_id"])
        )
    )
    assert session.scalar(select(func.count()).select_from(Absence)) == 1
    assert session.scalar(select(func.count()).select_from(Case)) == 1


def test_concurrent_reanalysis_deduplicates_changed_observation(setup):
    client, session, engine = setup
    ids = client.post("/api/v1/absences", json=PAYLOAD).json()
    task = session.scalar(
        select(Task).where(Task.assignee_employee_id == PAYLOAD["employee_id"])
    )
    task.estimated_hours = Decimal("1.123456")
    session.commit()
    before = session.scalar(select(func.count()).select_from(AuditEvent))
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda _: reanalyze(engine, ids), range(2)))
    assert sorted(report.changed for report in reports) == [False, True]
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == before + 1
    assert session.scalar(select(func.count()).select_from(Reservation)) == 0


def test_proposal_and_reservation_never_correct_divergence(setup):
    client, session, engine = setup
    ids = client.post("/api/v1/absences", json=PAYLOAD).json()
    original = observation(session, ids["case_id"])
    task_id = original.result["task_ids"][0]
    candidate = session.scalar(
        select(Employee).where(Employee.employee_id != PAYLOAD["employee_id"])
    )
    now = session.get(Case, ids["case_id"]).created_at
    session.add(PolicyVersion(policy_version=1, created_at=now))
    session.flush()
    session.add(
        CoveragePlan(
            plan_id="impact-plan",
            case_id=ids["case_id"],
            plan_version=1,
            policy_version=1,
            created_at=now,
        )
    )
    session.flush()
    attempt = CoverageAttempt(
        attempt_id="impact-attempt",
        case_id=ids["case_id"],
        plan_id="impact-plan",
        plan_version=1,
        task_id=task_id,
        candidate_employee_id=candidate.employee_id,
        policy_version=1,
        status=AttemptStatus.PROPOSED,
        created_at=now,
        response_deadline_at=now + timedelta(minutes=15),
    )
    session.add(attempt)
    session.commit()
    assert not reanalyze(engine, ids).changed
    attempt.status = AttemptStatus.RESERVED
    reservation = Reservation(
        reservation_id="impact-reservation",
        attempt_id=attempt.attempt_id,
        reserved_hours=1,
        created_at=now,
    )
    session.add(reservation)
    session.commit()
    report = reanalyze(engine, ids)
    assert not report.changed
    assert report.current.payload["divergence_detected"]
    assert all(
        not entry["correction_confirmed"]
        for entry in report.current.payload["divergences"]
    )
    session.refresh(reservation)
    assert reservation.released_at is None and reservation.reserved_hours == 1
    assert session.get(Task, task_id).assignee_employee_id == PAYLOAD["employee_id"]


def test_return_to_previous_data_is_a_new_observation(setup):
    client, session, engine = setup
    ids = client.post("/api/v1/absences", json=PAYLOAD).json()
    task = session.scalar(
        select(Task).where(Task.assignee_employee_id == PAYLOAD["employee_id"])
    )
    hours = task.estimated_hours
    task.estimated_hours = hours + 1
    session.commit()
    assert reanalyze(engine, ids).changed
    task.estimated_hours = hours
    session.commit()
    assert reanalyze(engine, ids).changed
    assert not reanalyze(engine, ids).changed
    assert (
        session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action.in_(impact.IMPACT_ACTIONS))
        )
        == 3
    )


def test_missing_reference_shift_is_explicit_quality_gap(setup, monkeypatch):
    from app.services import task_source

    client, session, engine = setup
    monkeypatch.setattr(
        task_source, "DEMO_REFERENCE_DATE", REFERENCE + timedelta(days=5)
    )
    ids = client.post("/api/v1/absences", json=PAYLOAD).json()
    report = reanalyze(engine, ids)
    assert (
        report.current.hours_at_risk == 0
    )  # registered set is empty; not proof of no work
    assert report.current.payload["data_complete"] is False
    assert report.current.payload["period"]["shift_id"] is None
    assert report.current.payload["data_quality_issues"][0]["fields"] == [
        "reference_shift"
    ]
    assert session.get(Case, ids["case_id"]).status == "open"


def test_legacy_detection_is_preserved_without_inventing_original_hours(setup):
    _, session, engine = setup
    shift = session.scalar(select(Shift))
    task = session.scalar(
        select(Task).where(Task.assignee_employee_id == PAYLOAD["employee_id"])
    )
    absence = Absence(
        absence_id="legacy-absence",
        employee_id=PAYLOAD["employee_id"],
        starts_at=shift.starts_at,
        ends_at=shift.ends_at,
        confirmed=True,
        source_system="hr_fixture",
        external_id="legacy",
        updated_at=shift.starts_at,
    )
    session.add(
        Case(
            case_id="legacy-case",
            created_at=shift.starts_at,
            absences=[absence],
            tasks=[task],
        )
    )
    session.flush()
    original = {
        "absence_id": absence.absence_id,
        "employee_id": absence.employee_id,
        "task_ids": [task.task_id],
        "task_count": 1,
    }
    session.add(
        AuditEvent(
            audit_event_id="legacy-detection",
            case_id="legacy-case",
            actor="legacy-test",
            action="impact.detected",
            timestamp=shift.starts_at,
            policy_version=None,
            result=original,
        )
    )
    session.commit()
    ids = {"case_id": "legacy-case", "absence_id": "legacy-absence"}
    report = reanalyze(engine, ids)
    assert report.changed and report.original == original
    assert "hours_at_risk" not in report.original
    assert not reanalyze(engine, ids).changed
    session.expire_all()
    assert session.get(AuditEvent, "legacy-detection").result == original
