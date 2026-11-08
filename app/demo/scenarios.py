"""Separate synthetic edge-case builders; never called by the principal seed."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from app.enums import Channel, Priority, TaskStatus
from app.models import Employee, EmployeeShift, Shift, Skill, Task, Team

def edge_scenario(session: Session, kind: str):
    if kind not in {"incomplete", "no_slack", "above_policy", "completed", "carlos_pedro"}:
        raise ValueError(kind)
    prefix = f"fixture-{kind}"
    now = datetime(2026, 11, 8, 11, tzinfo=timezone.utc)
    shift = Shift(shift_id=prefix, reference_date=date(2026, 11, 8), starts_at=now, ends_at=now+timedelta(hours=8))
    team = Team(team_id=prefix, name="Equipe sint?tica", source_system="hr_fixture", external_id=prefix, updated_at=now)
    session.add_all([shift, team])
    skills = []
    for key in ["python", "excel"]:
        skill = session.get(Skill, key)
        if skill is None:
            skill = Skill(skill_id=key)
            session.add(skill)
        skills.append(skill)
    employees = []
    names = ["Carlos", "Pedro", "Jo?o"] if kind == "carlos_pedro" else ["Pessoa sint?tica"]
    for index, name in enumerate(names):
        employee = Employee(employee_id=f"{prefix}-{index}", name=name,
            team=team if kind != "incomplete" else None, skills_known=kind != "incomplete",
            skills=[] if kind == "incomplete" else (skills[:1] if name == "Pedro" else skills),
            preferred_channel=Channel.TEAMS, channel_user_id=f"synthetic-{prefix}-{index}",
            source_system="hr_fixture", external_id=f"{prefix}-{index}", updated_at=now)
        session.add(employee)
        session.add(EmployeeShift(employee=employee, shift=shift,
            shift_hours=None if kind == "incomplete" else Decimal("2" if kind == "carlos_pedro" else "8")))
        employees.append(employee)
    count = 2 if kind == "carlos_pedro" else 1
    for index in range(count):
        session.add(Task(task_id=f"{prefix}-task-{index}", title=["Automa??o Python", "Relat?rio Excel"][index],
            team=team if kind != "incomplete" else None,
            assignee=None if kind == "incomplete" else employees[-1], shift=shift,
            estimated_hours=None if kind == "incomplete" else Decimal({"no_slack":"8", "above_policy":"7.5"}.get(kind,"2")),
            due_at=None if kind == "incomplete" else now+timedelta(hours=2),
            priority=Priority.HIGH, status=TaskStatus.DONE if kind == "completed" else TaskStatus.OPEN,
            transfer_allowed=True, required_skills_known=kind != "incomplete",
            required_skills=[] if kind == "incomplete" else [skills[index]],
            source_system="task_fixture", external_id=f"{prefix}-task-{index}", updated_at=now))
    session.flush()
    return {"shift_id": prefix, "team_id": prefix, "employees": employees,
            "max_utilization_pct": 100 if kind == "carlos_pedro" else 90}
