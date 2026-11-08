from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.demo.seed import seed_demo
from app.enums import AttemptStatus, TaskStatus
from app.main import app
from app.models import (
    Case,
    CoverageAttempt,
    CoveragePlan,
    Employee,
    EmployeeShift,
    PolicyVersion,
    Reservation,
    Shift,
    Task,
    Team,
)
from app.schemas.teams import TeamResponse

REFERENCE = date(2026, 11, 8)
FIELDS = {
    "team_id",
    "name",
    "reference_date",
    "employee_count",
    "shift_hours",
    "committed_hours",
    "reserved_hours",
    "occupied_hours",
    "utilization_pct",
    "complete",
}


@pytest.fixture
def client(database, monkeypatch):
    from app.services import queries

    monkeypatch.setattr(queries, "DEMO_REFERENCE_DATE", REFERENCE)

    def temporary_session():
        with Session(database[0]) as session:
            yield session

    app.dependency_overrides[get_session] = temporary_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_empty_teams(client):
    response = client.get("/api/v1/teams")
    assert response.status_code == 200
    assert response.json() == []


def test_approved_schema_and_seed_totals(client, session):
    seed_demo(session, REFERENCE)
    session.commit()
    response = client.get("/api/v1/teams")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 4
    expected = {
        "demo-atendimento": (47.5, 59.375),
        "demo-operacoes": (50, 62.5),
        "demo-financeiro": (75.5, 94.375),
        "demo-tecnologia": (52.5, 65.625),
    }
    for row in rows:
        assert set(row) == FIELDS
        TeamResponse.model_validate(row)
        hours, utilization = expected[row["team_id"]]
        assert row["reference_date"] == REFERENCE.isoformat()
        assert row["employee_count"] == 10
        assert row["shift_hours"] == 80
        assert row["committed_hours"] == row["occupied_hours"] == hours
        assert row["reserved_hours"] == 0
        assert row["utilization_pct"] == utilization
        assert row["complete"] is True
    assert client.get("/health").json() == {"status": "ok"}
    assert len(client.get("/api/v1/employees").json()) == 40
    assert len(client.get("/api/v1/tasks").json()) == 187
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/teams"]["get"]
    assert (
        operation["responses"]["200"]["content"]["application/json"]["schema"]["type"]
        == "array"
    )
    assert not operation.get("parameters")
    assert not operation.get("security")


def isolate_team(session):
    seed_demo(session, REFERENCE)
    team = session.get(Team, "demo-atendimento")
    employees = list(
        session.scalars(
            select(Employee)
            .where(Employee.team_id == team.team_id)
            .order_by(Employee.employee_id)
        )
    )
    shift = session.scalar(select(Shift))
    for task in session.scalars(select(Task).where(Task.team_id == team.team_id)):
        task.status = TaskStatus.DONE
    for employee in employees:
        session.get(
            EmployeeShift, (employee.employee_id, shift.shift_id)
        ).shift_hours = 0
    session.flush()
    return team, employees, shift


def row_for(client, team_id):
    response = client.get("/api/v1/teams")
    assert response.status_code == 200
    return next(row for row in response.json() if row["team_id"] == team_id)


def test_weighted_utilization_zero_and_existing_overload(client, session):
    team, employees, shift = isolate_team(session)
    session.get(
        EmployeeShift, (employees[0].employee_id, shift.shift_id)
    ).shift_hours = 2
    session.get(
        EmployeeShift, (employees[1].employee_id, shift.shift_id)
    ).shift_hours = 8
    task = session.scalar(
        select(Task).where(Task.assignee_employee_id == employees[0].employee_id)
    )
    task.status = TaskStatus.OPEN
    task.estimated_hours = Decimal(2)
    session.commit()
    row = row_for(client, team.team_id)
    assert row["shift_hours"] == 10
    assert row["utilization_pct"] == 20  # not mean(100%, 0%) = 50%
    task.estimated_hours = Decimal("12.123456")
    session.commit()
    assert row_for(client, team.team_id)["utilization_pct"] == pytest.approx(121.23456)
    for employee in employees[:2]:
        session.get(
            EmployeeShift, (employee.employee_id, shift.shift_id)
        ).shift_hours = 0
    session.commit()
    row = row_for(client, team.team_id)
    assert row["shift_hours"] == 0
    assert row["utilization_pct"] is None
    assert row["complete"] is True


@pytest.mark.parametrize(
    "unknown", ["capacity", "missing_capacity", "estimate", "assignee"]
)
def test_unknowns_propagate_without_partial_totals(client, session, unknown):
    team, employees, shift = isolate_team(session)
    task = session.scalar(
        select(Task).where(Task.assignee_employee_id == employees[0].employee_id)
    )
    task.status = TaskStatus.OPEN
    capacity = session.get(EmployeeShift, (employees[0].employee_id, shift.shift_id))
    if unknown == "capacity":
        capacity.shift_hours = None
    elif unknown == "missing_capacity":
        session.delete(capacity)
    elif unknown == "estimate":
        task.estimated_hours = None
    else:
        task.assignee_employee_id = None
    session.commit()
    row = row_for(client, team.team_id)
    assert row["complete"] is False
    assert row["utilization_pct"] is None
    if unknown in {"capacity", "missing_capacity"}:
        assert row["shift_hours"] is None
        assert row["committed_hours"] is not None
    else:
        assert row["committed_hours"] is None
        assert row["occupied_hours"] is None


def test_team_without_members_and_missing_shift(client, session):
    seed_demo(session, REFERENCE + timedelta(days=1))
    now = session.scalar(select(Shift.starts_at))
    session.add(
        Team(
            team_id="empty",
            name="Empty persisted team",
            source_system="hr_fixture",
            external_id="empty",
            updated_at=now,
        )
    )
    session.commit()
    empty = row_for(client, "empty")
    assert (
        empty["employee_count"] == empty["shift_hours"] == empty["occupied_hours"] == 0
    )
    assert empty["utilization_pct"] is None
    assert empty["complete"] is True
    populated = row_for(client, "demo-atendimento")
    assert populated["shift_hours"] is None
    assert populated["complete"] is False


def test_employee_without_team_blocks_publication(client, session):
    seed_demo(session, REFERENCE)
    employee = session.scalar(select(Employee))
    employee.team_id = None
    session.commit()
    response = client.get("/api/v1/teams")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INCOMPLETE_SOURCE_DATA"
    assert response.json()["error"]["details"]["records"] == [
        {"id": employee.employee_id, "fields": ["team_id"]}
    ]


def test_workload_follows_current_owner_and_completed_tasks_are_excluded(
    client, session
):
    seed_demo(session, REFERENCE)
    task = session.scalar(select(Task).where(Task.team_id == "demo-atendimento"))
    candidate = session.scalar(
        select(Employee).where(Employee.team_id == "demo-tecnologia")
    )
    hours = float(task.estimated_hours)
    task.assignee = candidate
    session.commit()
    assert row_for(client, "demo-atendimento")["committed_hours"] == 47.5 - hours
    assert row_for(client, "demo-tecnologia")["committed_hours"] == 52.5 + hours
    assert task.team_id == "demo-atendimento"
    task.status = TaskStatus.DONE
    session.commit()
    assert row_for(client, "demo-tecnologia")["committed_hours"] == 52.5


def test_active_reservations_and_reference_period(client, session):
    team, employees, shift = isolate_team(session)
    task = session.scalar(select(Task).where(Task.team_id == "demo-tecnologia"))
    now = shift.starts_at
    session.add(Case(case_id="team-case", created_at=now, tasks=[task]))
    session.add(PolicyVersion(policy_version=1, created_at=now))
    session.flush()
    session.add(
        CoveragePlan(
            plan_id="team-plan",
            case_id="team-case",
            plan_version=1,
            policy_version=1,
            created_at=now,
        )
    )
    session.flush()
    session.add(
        CoverageAttempt(
            attempt_id="team-attempt",
            case_id="team-case",
            plan_id="team-plan",
            plan_version=1,
            task_id=task.task_id,
            candidate_employee_id=employees[0].employee_id,
            policy_version=1,
            status=AttemptStatus.RESERVED,
            created_at=now,
            response_deadline_at=now + timedelta(minutes=15),
        )
    )
    session.flush()
    reservation = Reservation(
        reservation_id="team-reservation",
        attempt_id="team-attempt",
        reserved_hours=Decimal("1.25"),
        created_at=now,
    )
    session.add(reservation)
    other = Shift(
        shift_id="other",
        reference_date=REFERENCE + timedelta(days=1),
        starts_at=now + timedelta(days=1),
        ends_at=shift.ends_at + timedelta(days=1),
    )
    session.add(other)
    session.flush()
    session.add(
        Task(
            task_id="other-task",
            title="Other shift",
            assignee=employees[0],
            team_id=team.team_id,
            shift=other,
            priority=task.priority,
            estimated_hours=100,
            status=TaskStatus.OPEN,
            due_at=other.ends_at,
            transfer_allowed=True,
            required_skills_known=True,
            source_system="task_fixture",
            external_id="other-task",
            updated_at=now,
        )
    )
    session.commit()
    row = row_for(client, team.team_id)
    assert row["committed_hours"] == 0
    assert row["reserved_hours"] == row["occupied_hours"] == 1.25
    reservation.released_at = now
    session.commit()
    assert row_for(client, team.team_id)["reserved_hours"] == 0


def test_read_only_bounded_queries_and_invalid_parameters(client, session, database):
    seed_demo(session, REFERENCE)
    session.commit()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(database[0], "before_cursor_execute", capture)
    try:
        assert client.get("/api/v1/teams").status_code == 200
    finally:
        event.remove(database[0], "before_cursor_execute", capture)
    assert len(statements) <= 7
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    response = client.get("/api/v1/teams?team_id=any")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUERY_PARAMETERS"
    assert client.post("/api/v1/teams").status_code == 405
