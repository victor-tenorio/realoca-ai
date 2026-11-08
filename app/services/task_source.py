"""Read the simulated task source. This activity never changes ownership."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEMO_REFERENCE_DATE
from app.enums import TaskStatus
from app.models import Shift, Task


def open_tasks_for_absence(
    session: Session, employee_id: str, starts_at: datetime, ends_at: datetime
) -> list[Task]:
    # Remaining effort belongs to the configured operational shift. Due dates
    # are deadlines, not task execution intervals, so they are not an overlap filter.
    return list(
        session.scalars(
            select(Task)
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
