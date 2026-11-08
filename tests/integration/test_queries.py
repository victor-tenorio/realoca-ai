from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.db import get_session
from app.demo.seed import seed_demo
from app.enums import AttemptStatus, Channel, TaskStatus
from app.main import app
from app.models import (
    Absence,
    Case,
    CoverageAttempt,
    CoveragePlan,
    Employee,
    EmployeeShift,
    PolicyVersion,
    Reservation,
    Shift,
    Task,
)
from app.schemas.employees import EmployeeResponse
from app.schemas.tasks import TaskResponse
from app.services.capacity import employee_capacities, employee_capacity

REFERENCE = date(2026, 11, 8)
EMPLOYEE_FIELDS = {
    "employee_id",
    "name",
    "team_id",
    "skills",
    "shift_hours",
    "committed_hours",
    "reserved_hours",
    "availability",
    "preferred_channel",
    "channel_user_id",
    "source_system",
    "external_id",
    "updated_at",
}
TASK_FIELDS = {
    "task_id",
    "title",
    "assignee_employee_id",
    "team_id",
    "priority",
    "due_at",
    "estimated_hours",
    "required_skills",
    "status",
    "transfer_allowed",
    "source_system",
    "external_id",
    "updated_at",
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


@pytest.mark.parametrize("path", ["employees", "tasks"])
def test_empty_lists(client, path):
    response = client.get(f"/api/v1/{path}")
    assert response.status_code == 200
    assert response.json() == []


def test_seed_exact_fields_and_database_changes(client, session):
    seed_demo(session, REFERENCE)
    session.commit()
    employees = client.get("/api/v1/employees")
    tasks = client.get("/api/v1/tasks")
    assert employees.status_code == tasks.status_code == 200
    assert len(employees.json()) == 40
    assert len(tasks.json()) == 187
    for row in employees.json():
        assert set(row) == EMPLOYEE_FIELDS
        EmployeeResponse.model_validate(row)
        assert isinstance(row["shift_hours"], (int, float))
        assert row["preferred_channel"] == "slack"
    for row in tasks.json():
        assert set(row) == TASK_FIELDS
        TaskResponse.model_validate(row)
        assert row["status"] in {"open", "in_progress"}
        assert isinstance(row["estimated_hours"], (int, float))
    first = session.get(Employee, employees.json()[0]["employee_id"])
    first.name = "Updated synthetic name"
    task = session.get(Task, tasks.json()[0]["task_id"])
    task.title = "Updated synthetic task"
    task.status = TaskStatus.DONE
    session.commit()
    assert client.get("/api/v1/employees").json()[0]["name"] == first.name
    assert client.get("/api/v1/tasks").json()[0]["title"] == task.title
    assert client.get("/api/v1/tasks").json()[0]["status"] == "done"


@pytest.mark.parametrize("path", ["employees", "tasks"])
@pytest.mark.parametrize(
    "query",
    [
        "status=open",
        "team_id=demo-atendimento",
        "limit=1",
        "page=2",
        "status=wrong",
        "status=open&status=done",
    ],
)
def test_unsupported_parameters_are_standard_400(client, path, query):
    response = client.get(f"/api/v1/{path}?{query}")
    assert response.status_code == 400
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "INVALID_QUERY_PARAMETERS"
    assert set(response.json()["error"]) == {"code", "message", "details"}


def test_teams_is_not_published_and_health_is_preserved(client):
    assert client.get("/api/v1/teams").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/health").status_code == 404
    schema = client.get("/openapi.json").json()
    for path in ("/api/v1/employees", "/api/v1/tasks"):
        operation = schema["paths"][path]["get"]
        assert (
            operation["responses"]["200"]["content"]["application/json"]["schema"][
                "type"
            ]
            == "array"
        )
        assert not operation.get("parameters")
        assert not operation.get("security")


def test_absence_is_derived_from_confirmed_overlap_not_workload(client, session):
    seed_demo(session, REFERENCE)
    employees = list(session.scalars(select(Employee).order_by(Employee.employee_id)))
    shift = session.scalar(select(Shift))
    for i, (employee, confirmed, starts, ends) in enumerate(
        [
            (employees[0], True, shift.starts_at, shift.ends_at),
            (employees[1], False, shift.starts_at, shift.ends_at),
            (employees[2], True, shift.ends_at, shift.ends_at + timedelta(hours=1)),
        ]
    ):
        session.add(
            Absence(
                absence_id=f"query-absence-{i}",
                employee_id=employee.employee_id,
                confirmed=confirmed,
                starts_at=starts,
                ends_at=ends,
                source_system="hr_fixture",
                external_id=f"query-absence-{i}",
                updated_at=shift.starts_at,
            )
        )
    session.get(
        EmployeeShift, (employees[3].employee_id, shift.shift_id)
    ).shift_hours = 0
    session.commit()
    rows = {row["employee_id"]: row for row in client.get("/api/v1/employees").json()}
    assert rows[employees[0].employee_id]["availability"] == "absent"
    assert rows[employees[1].employee_id]["availability"] == "available"
    assert rows[employees[2].employee_id]["availability"] == "available"
    assert rows[employees[3].employee_id]["shift_hours"] == 0
    assert rows[employees[3].employee_id]["availability"] == "unavailable"
    overloaded = next(
        row
        for row in rows.values()
        if row["committed_hours"] >= 8 and row["shift_hours"] == 8
    )
    assert overloaded["availability"] == "available"


@pytest.mark.parametrize(
    "entity,field",
    [
        ("employee", "skills_known"),
        ("employee", "team_id"),
        ("employee", "preferred_channel"),
        ("capacity", "shift_hours"),
        ("task", "estimated_hours"),
        ("task", "due_at"),
        ("task", "required_skills_known"),
        ("task", "assignee_employee_id"),
    ],
)
def test_incomplete_records_block_whole_list_without_silent_omission(
    client, session, entity, field
):
    seed_demo(session, REFERENCE)
    employee = session.scalar(select(Employee).order_by(Employee.employee_id))
    task = session.scalar(
        select(Task).where(Task.assignee_employee_id == employee.employee_id)
    )
    capacity = session.scalar(
        select(EmployeeShift).where(EmployeeShift.employee_id == employee.employee_id)
    )
    row = {"employee": employee, "task": task, "capacity": capacity}[entity]
    setattr(row, field, False if field.endswith("known") else None)
    session.commit()
    path = "tasks" if entity == "task" else "employees"
    response = client.get(f"/api/v1/{path}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INCOMPLETE_SOURCE_DATA"
    assert response.json()["error"]["details"]["records"]
    if field == "estimated_hours":
        assert client.get("/api/v1/employees").status_code == 422


def test_known_empty_skills_and_legacy_channel(client, session):
    seed_demo(session, REFERENCE)
    employee = session.scalar(select(Employee).order_by(Employee.employee_id))
    employee.skills = []
    task = session.scalar(select(Task).order_by(Task.task_id))
    task.required_skills = []
    session.commit()
    assert client.get("/api/v1/employees").json()[0]["skills"] == []
    assert client.get("/api/v1/tasks").json()[0]["required_skills"] == []
    employee.preferred_channel = Channel.TEAMS
    session.commit()
    response = client.get("/api/v1/employees")
    assert response.status_code == 422
    assert response.json()["error"]["details"]["records"][0]["fields"] == [
        "preferred_channel"
    ]


def test_origin_team_remains_independent_without_invented_transfer(client, session):
    seed_demo(session, REFERENCE)
    task = session.scalar(select(Task).order_by(Task.task_id))
    original_team = task.team_id
    candidate = session.scalar(
        select(Employee).where(Employee.team_id != original_team)
    )
    task.assignee = candidate
    session.commit()
    row = client.get("/api/v1/tasks").json()[0]
    assert row["team_id"] == original_team
    assert row["assignee_employee_id"] == candidate.employee_id
    assert "transferred" not in row
    assert task.assignments == []


def test_listings_are_select_only_and_bounded_queries(client, session, database):
    seed_demo(session, REFERENCE)
    session.commit()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(database[0], "before_cursor_execute", capture)
    try:
        assert client.get("/api/v1/employees").status_code == 200
        assert client.get("/api/v1/tasks").status_code == 200
    finally:
        event.remove(database[0], "before_cursor_execute", capture)
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    assert len(statements) <= 10


def test_missing_reference_shift_is_not_fake_zero(client, session):
    seed_demo(session, REFERENCE + timedelta(days=1))
    session.commit()
    assert client.get("/api/v1/tasks").json() == []
    response = client.get("/api/v1/employees")
    assert response.status_code == 422


def test_database_error_is_sanitized(client, database):
    with Session(database[0]) as session:
        seed_demo(session, REFERENCE)
        session.commit()
    with database[0].begin() as connection:
        connection.execute(text("DROP TABLE employee_skills"))
    response = client.get("/api/v1/employees")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "employee_skills" not in response.text


def test_capacity_period_completed_tasks_active_and_released_reservations(
    client, session
):
    seed_demo(session, REFERENCE)
    shift = session.scalar(select(Shift))
    task = session.scalar(select(Task).order_by(Task.task_id))
    candidate = session.scalar(
        select(Employee)
        .where(Employee.employee_id != task.assignee_employee_id)
        .order_by(Employee.employee_id)
    )
    completed = session.scalar(
        select(Task).where(Task.assignee_employee_id == candidate.employee_id)
    )
    completed.status = TaskStatus.DONE
    now = shift.starts_at
    session.add(Case(case_id="query-case", created_at=now, tasks=[task]))
    session.add(PolicyVersion(policy_version=1, created_at=now))
    session.flush()
    session.add(
        CoveragePlan(
            plan_id="query-plan",
            case_id="query-case",
            plan_version=1,
            policy_version=1,
            created_at=now,
        )
    )
    session.flush()
    session.add(
        CoverageAttempt(
            attempt_id="query-attempt",
            case_id="query-case",
            plan_id="query-plan",
            plan_version=1,
            task_id=task.task_id,
            candidate_employee_id=candidate.employee_id,
            policy_version=1,
            status=AttemptStatus.NOTIFIED,
            created_at=now,
            response_deadline_at=now + timedelta(minutes=15),
        )
    )
    session.flush()
    reservation = Reservation(
        reservation_id="query-reservation",
        attempt_id="query-attempt",
        reserved_hours=Decimal("1.25"),
        created_at=now,
    )
    session.add(reservation)
    other_shift = Shift(
        shift_id="another-day",
        reference_date=REFERENCE + timedelta(days=1),
        starts_at=now + timedelta(days=1),
        ends_at=shift.ends_at + timedelta(days=1),
    )
    session.add(other_shift)
    session.flush()
    other_task = Task(
        task_id="another-day-task",
        title="Other shift task",
        assignee=candidate,
        team_id=task.team_id,
        shift=other_shift,
        priority=task.priority,
        due_at=other_shift.ends_at,
        estimated_hours=Decimal(100),
        status=TaskStatus.OPEN,
        required_skills_known=True,
        transfer_allowed=True,
        source_system="task_fixture",
        external_id="another-day-task",
        updated_at=now,
    )
    session.add(other_task)
    session.add(EmployeeShift(employee=candidate, shift=other_shift, shift_hours=0))
    session.commit()
    expected = employee_capacity(session, candidate.employee_id, shift.shift_id)
    batch = employee_capacities(session, [candidate.employee_id], shift.shift_id)[
        candidate.employee_id
    ]
    assert batch == expected
    rows = {r["employee_id"]: r for r in client.get("/api/v1/employees").json()}
    assert rows[candidate.employee_id]["committed_hours"] == float(
        expected.committed_hours
    )
    assert rows[candidate.employee_id]["reserved_hours"] == 1.25
    assert rows[candidate.employee_id]["shift_hours"] == 8
    tasks = client.get("/api/v1/tasks").json()
    assert any(
        t["task_id"] == completed.task_id and t["status"] == "done" for t in tasks
    )
    assert not any(t["task_id"] == "another-day-task" for t in tasks)
    reservation.released_at = now
    session.commit()
    rows = {r["employee_id"]: r for r in client.get("/api/v1/employees").json()}
    assert rows[candidate.employee_id]["reserved_hours"] == 0


def test_no_business_commands_exposed(client):
    assert client.post("/api/v1/employees").status_code == 405
    assert client.post("/api/v1/tasks").status_code == 405
    assert client.post("/api/v1/tasks/any/complete").status_code == 404


def test_read_only_does_not_apply_pending_changes_or_autoflush(session):
    from app.services.queries import list_employees

    seed_demo(session, REFERENCE)
    session.commit()
    employee = session.scalar(select(Employee))
    employee.name = "Pending change"
    list_employees(session)
    with session.no_autoflush:
        persisted_name = session.scalar(
            select(Employee.name).where(Employee.employee_id == employee.employee_id)
        )
    assert persisted_name != "Pending change"
    session.rollback()
