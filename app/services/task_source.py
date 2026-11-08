"""Read the simulated task source. This activity never changes ownership."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import DEMO_REFERENCE_DATE
from app.enums import TaskStatus
from app.models import Shift, Task


def reference_shift(session: Session) -> Shift | None:
    return session.scalar(
        select(Shift).where(Shift.reference_date == DEMO_REFERENCE_DATE)
    )


def open_tasks_for_absence(
    session: Session, employee_id: str, starts_at: datetime, ends_at: datetime
) -> list[Task]:
    # Remaining effort belongs to the configured operational shift. Due dates
    # are deadlines, not task execution intervals, so they are not an overlap filter.
    return list(
        session.scalars(
            select(Task)
            .options(selectinload(Task.required_skills), joinedload(Task.assignee))
            .join(Shift)
            .where(
                Task.assignee_employee_id == employee_id,
                Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
                Shift.reference_date == DEMO_REFERENCE_DATE,
                Shift.starts_at < ends_at,
                Shift.ends_at > starts_at,
            )
            .order_by(Task.task_id)
        )
    )


def tasks_by_ids(session: Session, task_ids: list[str]) -> list[Task]:
    """Read historical tasks even after completion or reassignment."""
    if not task_ids:
        return []
    return list(
        session.scalars(
            select(Task)
            .where(Task.task_id.in_(task_ids))
            .options(selectinload(Task.required_skills), joinedload(Task.assignee))
            .order_by(Task.task_id)
        )
    )
