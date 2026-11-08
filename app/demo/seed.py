"""Explicit deterministic synthetic seed. Never resets existing records."""

from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEMO_REFERENCE_DATE
from app.db import SessionLocal
from app.enums import Channel, Priority, TaskStatus
from app.models import Employee, EmployeeShift, Shift, Skill, Task, Team
from app.models.core import DemoSeedRun

TEAMS = [
    (
        "atendimento",
        "Atendimento",
        47,
        Decimal("47.5"),
        ["chat", "telefone", "reclamacoes", "crm", "ingles"],
        ["Liga??o de reten??o", "Atendimento internacional", "Retorno de reclama??o"],
    ),
    (
        "operacoes",
        "Opera??es",
        47,
        Decimal(50),
        ["estoque", "sap"],
        ["Confer?ncia de estoque", "Lan?ar notas no SAP"],
    ),
    (
        "financeiro",
        "Financeiro",
        47,
        Decimal("75.5"),
        ["auditoria", "conciliacao", "excel"],
        ["Preparar auditoria", "Concilia??o financeira"],
    ),
    (
        "tecnologia",
        "Tecnologia",
        46,
        Decimal("52.5"),
        ["python", "excel", "acessos"],
        ["Revis?o de acessos", "Automa??o Python", "Relat?rio Excel"],
    ),
]
FIRST_NAMES = [
    "Ana",
    "Bruno",
    "Clara",
    "Davi",
    "Elisa",
    "Fabio",
    "Gabriela",
    "Hugo",
    "Iara",
    "Jonas",
]
LAST_NAMES = ["Luz", "Vale", "Rios", "Prado"]


def seed_demo(session: Session, reference_date: date = DEMO_REFERENCE_DATE) -> bool:
    shift_id = f"demo-{reference_date.isoformat()}"
    # Entire seed is atomic; reruns refuse partial/colliding fixtures, and preserve
    # every existing value (including modifications) for an already seeded shift.
    if session.get(DemoSeedRun, "principal-v1"):
        return False
    if session.scalar(
        select(Employee.employee_id).where(Employee.employee_id.like("demo-%")).limit(1)
    ):
        raise ValueError(
            "Demo already exists for another date; use a separate database"
        )
    start = datetime.combine(reference_date, time(8), timezone(timedelta(hours=-3)))
    updated = start.astimezone(UTC)
    session.add(
        Shift(
            shift_id=shift_id,
            reference_date=reference_date,
            starts_at=start,
            ends_at=start + timedelta(hours=8),
        )
    )
    title_skills = {
        "Liga??o de reten??o": "telefone",
        "Atendimento internacional": "ingles",
        "Retorno de reclama??o": "reclamacoes",
        "Confer?ncia de estoque": "estoque",
        "Lan?ar notas no SAP": "sap",
        "Preparar auditoria": "auditoria",
        "Concilia??o financeira": "conciliacao",
        "Revis?o de acessos": "acessos",
        "Automa??o Python": "python",
        "Relat?rio Excel": "excel",
    }
    all_skills = sorted({skill for *_, skills, titles in TEAMS for skill in skills})
    skills = {}
    for identifier in all_skills:
        skill = session.get(Skill, identifier)
        if skill is None:
            skill = Skill(skill_id=identifier)
            session.add(skill)
        skills[identifier] = skill
    for team_index, (key, name, count, total, skill_ids, titles) in enumerate(TEAMS):
        team = Team(
            team_id=f"demo-{key}",
            name=name,
            source_system="hr_simulator",
            external_id=f"team-{key}",
            updated_at=updated,
        )
        session.add(team)
        employees = []
        for index in range(10):
            employee = Employee(
                employee_id=f"demo-{key}-{index + 1:02}",
                name=f"{FIRST_NAMES[index]} {LAST_NAMES[team_index]}",
                job_title=f"Analista de {name}",
                team=team,
                skills_known=True,
                skills=[skills[s] for s in skill_ids],
                preferred_channel=Channel.SLACK,
                channel_user_id=f"synthetic-{key}-{index + 1:02}",
                source_system="hr_simulator",
                external_id=f"employee-{key}-{index + 1:02}",
                updated_at=updated,
            )
            session.add(employee)
            employees.append(employee)
            session.add(
                EmployeeShift(
                    employee=employee, shift_id=shift_id, shift_hours=Decimal(8)
                )
            )
        # Start with 0.5h each, then distribute half-hour units round robin.
        units = [1] * count
        extra = int(total * 2) - count
        for i in range(extra):
            units[i % count] += 1
        for index, unit in enumerate(units):
            session.add(
                Task(
                    task_id=f"demo-{key}-task-{index + 1:03}",
                    title=titles[index % len(titles)],
                    team=team,
                    assignee=employees[index % 10],
                    shift_id=shift_id,
                    priority=[
                        Priority.LOW,
                        Priority.MEDIUM,
                        Priority.HIGH,
                        Priority.CRITICAL,
                    ][index % 4],
                    due_at=start + timedelta(hours=8),
                    estimated_hours=Decimal(unit) / 2,
                    status=TaskStatus.OPEN if index % 3 else TaskStatus.IN_PROGRESS,
                    transfer_allowed=True,
                    required_skills_known=True,
                    required_skills=[skills[title_skills[titles[index % len(titles)]]]],
                    source_system="task_simulator",
                    external_id=f"task-{key}-{index + 1:03}",
                    updated_at=updated,
                )
            )
    session.flush()
    session.add(
        DemoSeedRun(seed_id="principal-v1", shift_id=shift_id, created_at=updated)
    )
    session.flush()
    return True


def main() -> None:
    with SessionLocal.begin() as session:
        created = seed_demo(session)
    print(
        "Synthetic demo created" if created else "Demo already exists; no changes made"
    )


if __name__ == "__main__":
    main()
