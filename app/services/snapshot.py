"""A08: read a consistent, conservative input for the pure planning engine."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import AttemptStatus, Channel
from app.errors import APIError
from app.models import Absence, Case, CoverageAttempt, Employee, EmployeeShift, Shift
from app.services.capacity import employee_capacities


def build(session: Session, case: Case, *, policy, plan_version: int) -> dict:
    """Read source tasks, current assignments, absences and live reservations.

    Never invent missing hours/skills. An incomplete affected task is a blocker;
    an incomplete candidate is ineligible for this planning snapshot.
    """
    tasks = sorted(case.tasks, key=lambda item: item.task_id)
    if not tasks or not case.absences:
        raise APIError(422, "CASE_WITHOUT_IMPACT", "Caso sem tarefas e ausência para planejar", {
            "case_id": case.case_id,
        })
    shifts = {task.shift_id for task in tasks}
    if len(shifts) != 1:
        raise APIError(422, "MULTIPLE_SHIFTS_UNSUPPORTED", "Caso contém turnos diferentes", {
            "case_id": case.case_id,
        })
    shift = session.get(Shift, next(iter(shifts)))
    if shift is None:
        raise APIError(422, "SHIFT_NOT_FOUND", "Turno das tarefas não encontrado", {
            "case_id": case.case_id,
        })

    task_rows = []
    for task in tasks:
        if (task.priority is None or task.estimated_hours is None or task.due_at is None
                or task.transfer_allowed is None or not task.required_skills_known):
            raise APIError(422, "INCOMPLETE_TASK_DATA", "Tarefa sem dados para planejar", {
                "task_id": task.task_id,
            })
        task_rows.append({
            "task_id": task.task_id,
            "title": task.title,
            "priority": task.priority.value,
            "estimated_hours": float(task.estimated_hours),
            "required_skills": sorted(skill.skill_id for skill in task.required_skills),
            "team_id": task.team_id,
            "due_at": task.due_at.isoformat(),
            "transfer_allowed": task.transfer_allowed,
            "status": task.status.value,
        })

    absent_ids = set(session.scalars(
        select(Absence.employee_id).where(
            Absence.confirmed.is_(True),
            Absence.starts_at < shift.ends_at,
            Absence.ends_at > shift.starts_at,
        )
    ))
    # Explicitly include employees linked to the case; this protects a
    # historical case even if other source rows were edited afterward.
    absent_ids.update(absence.employee_id for absence in case.absences if absence.confirmed)
    employees = list(session.scalars(
        select(Employee).join(EmployeeShift).where(
            EmployeeShift.shift_id == shift.shift_id,
            EmployeeShift.shift_hours.is_not(None),
            EmployeeShift.shift_hours > 0,
            Employee.skills_known.is_(True),
            # Demo integrates exclusively with Slack. Teams-only, missing or
            # blank recipients cannot be sent an offer by the current n8n flow.
            Employee.preferred_channel == Channel.SLACK,
            Employee.channel_user_id.is_not(None),
            func.length(func.trim(Employee.channel_user_id)) > 0,
        ).order_by(Employee.employee_id)
    ))
    capacities = employee_capacities(session, [item.employee_id for item in employees], shift.shift_id)
    employee_rows = []
    for employee in employees:
        capacity = capacities[employee.employee_id]
        if not capacity.complete or capacity.shift_hours is None or capacity.committed_hours is None:
            continue
        employee_rows.append({
            "employee_id": employee.employee_id,
            "team_id": employee.team_id,
            "skills": sorted(skill.skill_id for skill in employee.skills),
            "shift_hours": float(capacity.shift_hours),
            "committed_hours": float(capacity.committed_hours),
            "reserved_hours": float(capacity.reserved_hours),
            "availability": "absent" if employee.employee_id in absent_ids else "available",
        })

    known_ids = {employee["employee_id"] for employee in employee_rows}
    task_ids = {task.task_id for task in tasks}
    excluded = set(session.execute(
        select(CoverageAttempt.task_id, CoverageAttempt.candidate_employee_id).where(
            CoverageAttempt.case_id == case.case_id,
            CoverageAttempt.status.in_({AttemptStatus.REFUSED, AttemptStatus.EXPIRED}),
        )
    ))
    return {
        "case_id": case.case_id,
        "plan_version": plan_version,
        "absent_employee_ids": sorted(absent_ids),
        "tasks": task_rows,
        "employees": employee_rows,
        "exclusions": [
            {"task_id": task_id, "employee_id": employee_id}
            for task_id, employee_id in sorted(excluded)
            if task_id in task_ids and employee_id in known_ids
        ],
        "policies": {
            "max_utilization_pct": float(policy.max_utilization_pct),
            "critical_requires_bp": policy.critical_requires_bp,
            "cross_team_requires_bp": policy.cross_team_requires_bp,
            "response_timeout_minutes": policy.response_timeout_minutes,
            "allow_automatic_same_team": policy.allow_automatic_same_team,
            "reminder_before_expiry_minutes": policy.reminder_before_expiry_minutes,
        },
    }
