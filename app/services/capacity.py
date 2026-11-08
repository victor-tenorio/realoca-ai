"""Read-only shift capacity calculations. No planner or reservation orchestration."""
from dataclasses import dataclass
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.enums import TaskStatus
from app.models import CoverageAttempt, Employee, EmployeeShift, Reservation, Task

ZERO = Decimal("0")

@dataclass(frozen=True)
class Capacity:
    shift_hours: Decimal | None
    committed_hours: Decimal | None
    reserved_hours: Decimal
    occupied_hours: Decimal | None
    utilization_pct: Decimal | None
    physical_slack_hours: Decimal | None
    reassignment_margin_hours: Decimal | None
    complete: bool
    reservations_supported: bool = True

def committed_hours(session: Session, shift_id: str, employee_ids: list[str] | None = None) -> Decimal | None:
    query = select(Task.estimated_hours).where(Task.shift_id == shift_id, Task.status != TaskStatus.DONE)
    if employee_ids is not None:
        query = query.where(Task.assignee_employee_id.in_(employee_ids))
    hours = list(session.scalars(query))
    return None if any(value is None for value in hours) else sum(hours, ZERO)

def employee_capacity(session: Session, employee_id: str, shift_id: str,
                      max_utilization_pct: Decimal = Decimal("90")) -> Capacity:
    if not ZERO <= max_utilization_pct <= 100:
        raise ValueError("max_utilization_pct must be between 0 and 100")
    if session.get(Employee, employee_id) is None:
        raise LookupError(employee_id)
    row = session.get(EmployeeShift, (employee_id, shift_id))
    shift_hours = row.shift_hours if row else None
    committed = committed_hours(session, shift_id, [employee_id])
    reserved = reserved_hours(session, shift_id, [employee_id])
    occupied = committed + reserved if committed is not None else None
    complete = shift_hours is not None and committed is not None
    utilization = occupied / shift_hours * 100 if complete and shift_hours > 0 else None
    slack = shift_hours - occupied if complete else None
    margin = max(ZERO, shift_hours * max_utilization_pct / 100 - occupied) if complete else None
    return Capacity(shift_hours, committed, reserved, occupied, utilization, slack, margin, complete)


def reserved_hours(session: Session, shift_id: str, employee_ids: list[str] | None = None) -> Decimal:
    query = (select(Reservation.reserved_hours)
             .join(CoverageAttempt, CoverageAttempt.attempt_id == Reservation.attempt_id)
             .join(Task, Task.task_id == CoverageAttempt.task_id)
             .where(Task.shift_id == shift_id, Reservation.released_at.is_(None)))
    if employee_ids is not None:
        query = query.where(CoverageAttempt.candidate_employee_id.in_(employee_ids))
    return sum(session.scalars(query), ZERO)

def team_capacity(session: Session, team_id: str, shift_id: str) -> dict:
    ids = list(session.scalars(select(Employee.employee_id).where(Employee.team_id == team_id)))
    capacities = [session.get(EmployeeShift, (employee_id, shift_id)) for employee_id in ids]
    nominal = (None if any(row is None or row.shift_hours is None for row in capacities)
               else sum((row.shift_hours for row in capacities), ZERO))
    # Attribute load to CURRENT employee's team, independently of task origin.
    committed = committed_hours(session, shift_id, ids)
    unknown_owners = session.scalar(select(Task.task_id).where(
        Task.shift_id == shift_id, Task.team_id == team_id,
        Task.assignee_employee_id.is_(None), Task.status != TaskStatus.DONE).limit(1))
    if unknown_owners is not None:
        committed = None
    return {"shift_hours": nominal, "committed_hours": committed,
            "complete": nominal is not None and committed is not None}
