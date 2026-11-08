from datetime import datetime, timezone
from decimal import Decimal
import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from app.db import Base
from app.demo.seed import seed_demo
from app.demo.scenarios import edge_scenario
from app.enums import TaskStatus
from app.models import Employee, EmployeeShift, Shift, Skill, Task, TaskAssignment, Team
from app.services.capacity import committed_hours, employee_capacity, team_capacity
from app.services.data_quality import employee_publication_issues, task_publication_issues


def test_migration_upgrade_downgrade(database):
    engine, config = database
    assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    command.check(config)
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    command.upgrade(config, "head")
    assert "tasks" in inspect(engine).get_table_names()


def test_populated_downgrade(database):
    from sqlalchemy.orm import Session
    engine, config = database
    with Session(engine) as session:
        seed_demo(session)
        session.commit()
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}


def test_seed_counts_totals_relationships_and_idempotence(session):
    assert seed_demo(session)
    session.commit()
    shift_id = session.scalar(select(Shift.shift_id))
    assert session.scalar(select(func.count()).select_from(Employee)) == 40
    assert session.scalar(select(func.count()).select_from(Team)) == 4
    assert session.scalar(select(func.count()).select_from(Task).where(Task.status != TaskStatus.DONE)) == 187
    for key, expected in [("atendimento", "47.5"), ("operacoes", "50"), ("financeiro", "75.5"), ("tecnologia", "52.5")]:
        team = session.get(Team, f"demo-{key}")
        assert len(team.employees) == 10
        result = team_capacity(session, team.team_id, shift_id)
        assert result == {"shift_hours": Decimal("80"), "committed_hours": Decimal(expected), "complete": True}
    for task in session.scalars(select(Task)):
        assert task.assignee.team_id == task.team_id
        assert set(task.required_skills) <= set(task.assignee.skills)
        assert Decimal("0.5") <= task.estimated_hours <= 2
        assert task.due_at.tzinfo == timezone.utc
        assert not task_publication_issues(task)
    assert session.scalar(select(func.count()).select_from(TaskAssignment)) == 0
    employee = session.scalar(select(Employee))
    employee.name = "Nome alterado"
    task = session.scalar(select(Task))
    task.status = TaskStatus.DONE
    session.commit()
    assert not seed_demo(session)
    session.commit()
    session.expire_all()
    assert employee.name == "Nome alterado"
    assert task.status == TaskStatus.DONE
    assert session.scalar(select(func.count()).select_from(Task)) == 187


@pytest.mark.parametrize("kind,committed,slack,margin", [
    ("no_slack", "8", "0", "0"),
    ("above_policy", "7.5", "0.5", "0"),
    ("completed", "0", "8", "7.2"),
])
def test_edge_capacities(session, kind, committed, slack, margin):
    scenario = edge_scenario(session, kind)
    session.commit()
    result = employee_capacity(session, scenario["employees"][0].employee_id, scenario["shift_id"])
    assert result.committed_hours == Decimal(committed)
    assert result.physical_slack_hours == Decimal(slack)
    assert result.reassignment_margin_hours == Decimal(margin)
    assert result.reserved_hours == 0
    assert result.reservations_supported is True


def test_unknowns_empty_skills_zero_and_incomplete_aggregates(session):
    scenario = edge_scenario(session, "incomplete")
    employee = scenario["employees"][0]
    task = session.scalar(select(Task))
    capacity = session.get(EmployeeShift, (employee.employee_id, scenario["shift_id"]))
    assert "skills" in employee_publication_issues(employee, capacity)
    assert "required_skills" in task_publication_issues(task)
    assert "assignee_employee_id" in task_publication_issues(task)
    assert committed_hours(session, scenario["shift_id"]) is None
    assert employee_capacity(session, employee.employee_id, scenario["shift_id"]).utilization_pct is None
    task.assignee = employee
    task.team_id = scenario["team_id"]
    employee.team_id = scenario["team_id"]
    session.flush()
    assert employee_capacity(session, employee.employee_id, scenario["shift_id"]).committed_hours is None
    assert not team_capacity(session, scenario["team_id"], scenario["shift_id"])["complete"]
    employee.skills_known = True
    task.required_skills_known = True
    task.estimated_hours = Decimal("1")
    capacity.shift_hours = 0
    session.flush()
    result = employee_capacity(session, employee.employee_id, scenario["shift_id"])
    assert result.utilization_pct is None
    assert result.reassignment_margin_hours == 0
    assert "skills" not in employee_publication_issues(employee, capacity)
    assert "required_skills" not in task_publication_issues(task)
    assert employee.skills == [] and task.required_skills == []


def test_carlos_pedro_fixture_only(session):
    scenario = edge_scenario(session, "carlos_pedro")
    carlos, pedro, joao = scenario["employees"]
    assert {s.skill_id for s in carlos.skills} == {"python", "excel"}
    assert {s.skill_id for s in pedro.skills} == {"python"}
    assert scenario["max_utilization_pct"] == 100
    assert len(joao.tasks) == 2
    for employee in (carlos, pedro):
        result = employee_capacity(session, employee.employee_id, scenario["shift_id"], Decimal("100"))
        assert result.reassignment_margin_hours == 2


@pytest.mark.parametrize("sql", [
    "UPDATE tasks SET estimated_hours=0",
    "UPDATE tasks SET estimated_hours=-1",
    "UPDATE tasks SET status='pending'",
    "UPDATE tasks SET priority='urgent'",
    "UPDATE tasks SET assignee_employee_id='missing'",
    "UPDATE tasks SET shift_id='missing'",
    "UPDATE employees SET team_id='missing'",
    "UPDATE employees SET preferred_channel='email'",
    "UPDATE employee_shifts SET shift_hours=-1",
    "UPDATE shifts SET ends_at=starts_at",
    "UPDATE employees SET external_id='employee-atendimento-01' WHERE employee_id='demo-atendimento-02'",
    "DELETE FROM teams WHERE team_id='demo-atendimento'",
    "INSERT INTO employee_skills SELECT * FROM employee_skills LIMIT 1",
])
def test_constraints(session, sql):
    seed_demo(session)
    session.commit()
    assert session.scalar(text("PRAGMA foreign_keys")) == 1
    with pytest.raises(IntegrityError):
        session.execute(text(sql))
        session.flush()
    session.rollback()


def test_timezone_rejects_naive_and_normalizes_offset(session):
    scenario = edge_scenario(session, "completed")
    session.commit()
    task = session.scalar(select(Task))
    task.due_at = datetime(2026, 11, 8, 12)
    with pytest.raises(StatementError, match="timezone required"):
        session.flush()
    session.rollback()
    task = session.scalar(select(Task))
    task.due_at = datetime.fromisoformat("2026-11-08T08:00:00-03:00")
    session.commit()
    session.refresh(task)
    assert task.due_at == datetime(2026, 11, 8, 11, tzinfo=timezone.utc)


def test_skill_normalization(session):
    skill = Skill(skill_id="  PYTHON  ")
    session.add(skill)
    session.commit()
    assert session.get(Skill, "python") is skill


def test_origin_team_is_independent_and_history_is_explicit(session):
    seed_demo(session)
    task = session.scalar(select(Task))
    origin = task.team_id
    candidate = session.scalar(select(Employee).where(Employee.team_id != origin))
    task.assignee = candidate
    session.flush()
    assert task.team_id == origin
    assert task.assignments == []  # cross-team ownership alone is no history
    session.add(TaskAssignment(assignment_id="test-history", task=task,
        from_employee_id=None, to_employee_id=candidate.employee_id,
        occurred_at=datetime.now(timezone.utc), reason="Synthetic persistence test"))
    session.commit()
    session.expire_all()
    assert task.assignments[0].to_employee_id == candidate.employee_id


@pytest.mark.parametrize("hours", [Decimal("NaN"), Decimal("Infinity"), Decimal("0.0000001")])
def test_hours_do_not_silently_round_or_accept_nonfinite(session, hours):
    edge_scenario(session, "completed")
    session.commit()
    task = session.scalar(select(Task))
    task.estimated_hours = hours
    with pytest.raises(StatementError, match="hours must be finite"):
        session.flush()
    session.rollback()


def test_capacity_is_recomputed_after_task_change(session):
    scenario = edge_scenario(session, "above_policy")
    employee = scenario["employees"][0]
    task = session.scalar(select(Task))
    task.estimated_hours = Decimal("1.123456")
    session.flush()
    result = employee_capacity(session, employee.employee_id, scenario["shift_id"])
    assert result.committed_hours == Decimal("1.123456")
    assert result.reassignment_margin_hours == Decimal("6.076544")
    task.status = TaskStatus.DONE
    session.flush()
    assert employee_capacity(session, employee.employee_id, scenario["shift_id"]).committed_hours == 0
