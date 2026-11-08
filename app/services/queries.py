"""Read-only list projections from persisted records for the configured shift."""

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import DEMO_REFERENCE_DATE
from app.enums import Availability, Channel
from app.errors import APIError
from app.models import Absence, Employee, Shift, Task
from app.schemas.employees import EmployeeResponse
from app.schemas.tasks import TaskResponse
from app.services.capacity import employee_capacities
from app.services.data_quality import (
    employee_publication_issues,
    task_publication_issues,
)


def incomplete(records: list[dict]) -> None:
    if records:
        raise APIError(
            422,
            "INCOMPLETE_SOURCE_DATA",
            "Dados de origem impedem a publicação",
            {"records": records},
        )


def validate_projection(schema, data, record_id: str, issues: list[dict]):
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        issues.append(
            {
                "id": record_id,
                "fields": sorted({str(e["loc"][0]) for e in exc.errors()}),
            }
        )
        return None


def reference_shift(session: Session) -> Shift | None:
    return session.scalar(
        select(Shift).where(Shift.reference_date == DEMO_REFERENCE_DATE)
    )


def list_employees(session: Session) -> list[EmployeeResponse]:
    with session.no_autoflush:
        employees = list(
            session.scalars(
                select(Employee)
                .options(selectinload(Employee.skills))
                .order_by(Employee.employee_id)
            )
        )
        if not employees:
            return []
        shift = reference_shift(session)
        if shift is None:
            incomplete(
                [
                    {
                        "id": employee.employee_id,
                        "fields": ["shift_hours", "availability"],
                    }
                    for employee in employees
                ]
            )
        capacities = employee_capacities(
            session, [e.employee_id for e in employees], shift.shift_id
        )
        absent = set(
            session.scalars(
                select(Absence.employee_id).where(
                    Absence.confirmed.is_(True),
                    Absence.starts_at < shift.ends_at,
                    Absence.ends_at > shift.starts_at,
                )
            )
        )
        issues, results = [], []
        for employee in employees:
            capacity = capacities[employee.employee_id]
            # Existing publication gate only needs shift_hours, not an ORM lookup.
            fields = employee_publication_issues(employee, capacity)
            if employee.preferred_channel not in (None, Channel.SLACK):
                fields.append("preferred_channel")
            if capacity.committed_hours is None:
                fields.append("committed_hours")
            if fields:
                issues.append(
                    {"id": employee.employee_id, "fields": sorted(set(fields))}
                )
                continue
            availability = (
                Availability.ABSENT
                if employee.employee_id in absent
                else Availability.UNAVAILABLE
                if capacity.shift_hours == 0
                else Availability.AVAILABLE
            )
            data = {
                field: getattr(employee, field)
                for field in (
                    "employee_id",
                    "name",
                    "team_id",
                    "preferred_channel",
                    "channel_user_id",
                    "source_system",
                    "external_id",
                    "updated_at",
                )
            }
            data.update(
                skills=sorted(skill.skill_id for skill in employee.skills),
                shift_hours=capacity.shift_hours,
                committed_hours=capacity.committed_hours,
                reserved_hours=capacity.reserved_hours,
                availability=availability,
            )
            results.append(
                validate_projection(
                    EmployeeResponse, data, employee.employee_id, issues
                )
            )
        incomplete(issues)
        return results


def list_tasks(session: Session) -> list[TaskResponse]:
    with session.no_autoflush:
        shift = reference_shift(session)
        if shift is None:
            return []
        tasks = list(
            session.scalars(
                select(Task)
                .where(Task.shift_id == shift.shift_id)
                .options(selectinload(Task.required_skills))
                .order_by(Task.task_id)
            )
        )
        issues, results = [], []
        for task in tasks:
            fields = task_publication_issues(task)
            if fields:
                issues.append({"id": task.task_id, "fields": sorted(fields)})
                continue
            data = {
                field: getattr(task, field)
                for field in (
                    "task_id",
                    "title",
                    "assignee_employee_id",
                    "team_id",
                    "priority",
                    "due_at",
                    "estimated_hours",
                    "status",
                    "transfer_allowed",
                    "source_system",
                    "external_id",
                    "updated_at",
                )
            }
            data["required_skills"] = sorted(
                skill.skill_id for skill in task.required_skills
            )
            results.append(
                validate_projection(TaskResponse, data, task.task_id, issues)
            )
        incomplete(issues)
        return results
