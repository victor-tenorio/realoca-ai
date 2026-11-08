"""Read-only shift capacity calculations. No planner or reservation orchestration."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import TaskStatus
from app.models import CoverageAttempt, Employee, EmployeeShift, Reservation, Task

ZERO = Decimal(0)


def sum_known_hours(hours) -> Decimal | None:
    values = list(hours)
    return None if any(value is None for value in values) else sum(values, ZERO)


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


def committed_hours(
    session: Session, shift_id: str, employee_ids: list[str] | None = None
) -> Decimal | None:
    query = select(Task.estimated_hours).where(
        Task.shift_id == shift_id, Task.status != TaskStatus.DONE
    )
    if employee_ids is not None:
        query = query.where(Task.assignee_employee_id.in_(employee_ids))
    return sum_known_hours(session.scalars(query))


def employee_capacity(
    session: Session,
    employee_id: str,
    shift_id: str,
    max_utilization_pct: Decimal = Decimal(90),
) -> Capacity:
    if not ZERO <= max_utilization_pct <= 100:
        raise ValueError("max_utilization_pct must be between 0 and 100")
    if session.get(Employee, employee_id) is None:
        raise LookupError(employee_id)
    row = session.get(EmployeeShift, (employee_id, shift_id))
    shift_hours = row.shift_hours if row else None
    committed = committed_hours(session, shift_id, [employee_id])
    reserved = reserved_hours(session, shift_id, [employee_id])
    return calculate_capacity(shift_hours, committed, reserved, max_utilization_pct)


def calculate_capacity(
    shift_hours: Decimal | None,
    committed: Decimal | None,
    reserved: Decimal,
    max_utilization_pct: Decimal = Decimal(90),
) -> Capacity:
    occupied = committed + reserved if committed is not None else None
    complete = shift_hours is not None and committed is not None
    utilization = occupied / shift_hours * 100 if complete and shift_hours > 0 else None
    slack = shift_hours - occupied if complete else None
    margin = (
        max(ZERO, shift_hours * max_utilization_pct / 100 - occupied)
        if complete
        else None
    )
    return Capacity(
        shift_hours, committed, reserved, occupied, utilization, slack, margin, complete
    )


def employee_capacities(
    session: Session, employee_ids: list[str], shift_id: str
) -> dict[str, Capacity]:
    """Batch equivalent of employee_capacity: three queries, no per-person selects."""
    if not employee_ids:
        return {}
    capacities = dict(
        session.execute(
            select(EmployeeShift.employee_id, EmployeeShift.shift_hours).where(
                EmployeeShift.shift_id == shift_id
            )
        ).all()
    )
    tasks: dict[str, list] = {}
    for employee_id, hours in session.execute(
        select(Task.assignee_employee_id, Task.estimated_hours).where(
            Task.shift_id == shift_id, Task.status != TaskStatus.DONE
        )
    ):
        tasks.setdefault(employee_id, []).append(hours)
    reservations: dict[str, Decimal] = {}
    for employee_id, hours in session.execute(
        select(CoverageAttempt.candidate_employee_id, Reservation.reserved_hours)
        .join(Reservation, Reservation.attempt_id == CoverageAttempt.attempt_id)
        .join(Task, Task.task_id == CoverageAttempt.task_id)
        .where(Task.shift_id == shift_id, Reservation.released_at.is_(None))
    ):
        reservations[employee_id] = reservations.get(employee_id, ZERO) + hours
    return {
        employee_id: calculate_capacity(
            capacities.get(employee_id),
            sum_known_hours(tasks.get(employee_id, [])),
            reservations.get(employee_id, ZERO),
        )
        for employee_id in employee_ids
    }


def reserved_hours(
    session: Session, shift_id: str, employee_ids: list[str] | None = None
) -> Decimal:
    query = (
        select(Reservation.reserved_hours)
        .join(CoverageAttempt, CoverageAttempt.attempt_id == Reservation.attempt_id)
        .join(Task, Task.task_id == CoverageAttempt.task_id)
        .where(Task.shift_id == shift_id, Reservation.released_at.is_(None))
    )
    if employee_ids is not None:
        query = query.where(CoverageAttempt.candidate_employee_id.in_(employee_ids))
    return sum(session.scalars(query), ZERO)


def team_capacity(session: Session, team_id: str, shift_id: str) -> dict:
    ids = list(
        session.scalars(select(Employee.employee_id).where(Employee.team_id == team_id))
    )
    capacities = [
        session.get(EmployeeShift, (employee_id, shift_id)) for employee_id in ids
    ]
    nominal = (
        None
        if any(row is None or row.shift_hours is None for row in capacities)
        else sum((row.shift_hours for row in capacities), ZERO)
    )
    # Attribute load to CURRENT employee's team, independently of task origin.
    committed = committed_hours(session, shift_id, ids)
    unknown_owners = session.scalar(
        select(Task.task_id)
        .where(
            Task.shift_id == shift_id,
            Task.team_id == team_id,
            Task.assignee_employee_id.is_(None),
            Task.status != TaskStatus.DONE,
        )
        .limit(1)
    )
    if unknown_owners is not None:
        committed = None
    return {
        "shift_hours": nominal,
        "committed_hours": committed,
        "complete": nominal is not None and committed is not None,
    }
