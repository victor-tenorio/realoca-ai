"""Publication gates for future API serializers; internal nulls stay internal."""

from decimal import Decimal
from typing import Protocol

from app.models import Employee, Task


class ShiftCapacity(Protocol):
    shift_hours: Decimal | None


def employee_publication_issues(
    employee: Employee, capacity: ShiftCapacity | None
) -> list[str]:
    issues = [
        field
        for field in ("team_id", "preferred_channel", "channel_user_id")
        if getattr(employee, field) is None
    ]
    if not employee.skills_known:
        issues.append("skills")
    if capacity is None or capacity.shift_hours is None:
        issues.append("shift_hours")
    return issues


def task_publication_issues(task: Task) -> list[str]:
    issues = [
        field
        for field in (
            "team_id",
            "assignee_employee_id",
            "priority",
            "due_at",
            "estimated_hours",
            "transfer_allowed",
        )
        if getattr(task, field) is None
    ]
    if not task.required_skills_known:
        issues.append("required_skills")
    return issues
