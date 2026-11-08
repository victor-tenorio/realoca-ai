"""A10: writer-serialized, policy-checked provisional capacity reservations."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.enums import AttemptStatus, CaseStatus
from app.errors import APIError
from app.models import Absence, Case, CoverageAttempt, Reservation, Shift
from app.services import audit, capacity, cases, policy


def reserve_attempt_atomic(
    session: Session, attempt_id: str, *, actor: str,
    at: datetime | None = None,
) -> Reservation:
    """Reserve once; caller must supply a fresh Session without active reads.

    SQLite `BEGIN IMMEDIATE` precedes all reads, serializing simultaneous
    reservations against *different* tasks for the same employee. It is safe
    to retry an already reserved attempt; no second capacity is consumed.
    """
    if not actor or not actor.strip():
        raise ValueError("actor is required")
    with session.begin():
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        attempt = session.get(CoverageAttempt, attempt_id)
        if attempt is None:
            raise APIError(404, "ATTEMPT_NOT_FOUND", "Tentativa não encontrada", {})
        previous = session.scalar(select(Reservation).where(
            Reservation.attempt_id == attempt_id
        ))
        if attempt.status == AttemptStatus.RESERVED and previous and previous.released_at is None:
            return previous
        if attempt.status not in {AttemptStatus.PROPOSED, AttemptStatus.PENDING_APPROVAL} or previous:
            raise APIError(409, "ATTEMPT_NOT_RESERVABLE", "Tentativa não pode ser reservada", {
                "attempt_id": attempt_id,
            })
        task, employee, plan_policy = attempt.affected_task, attempt.candidate, attempt.policy
        case = session.get(Case, attempt.case_id)
        shift = session.get(Shift, task.shift_id)
        if employee is None or shift is None:
            raise APIError(409, "INVALID_CANDIDATE", "Candidato sem turno válido", {})
        absent = set(session.scalars(select(Absence.employee_id).where(
            Absence.confirmed.is_(True),
            Absence.starts_at < shift.ends_at,
            Absence.ends_at > shift.starts_at,
        )))
        absent.update(a.employee_id for a in case.absences if a.confirmed)
        current_capacity = capacity.employee_capacity(
            session, employee.employee_id, shift.shift_id,
            max_utilization_pct=plan_policy.max_utilization_pct,
        )
        decision = policy.classify(task, employee, plan_policy, current_capacity,
                                   absent_employee_ids=absent)
        if decision.action == "inviable":
            raise APIError(409, "CAPACITY_OR_POLICY_CONFLICT", decision.reason, {
                "attempt_id": attempt_id, "reason_code": decision.reason_code,
            })
        if decision.action == "needs_approval" and (
            attempt.approval_decision != "approve" or not attempt.approval_actor_id
        ):
            raise APIError(409, "BP_APPROVAL_REQUIRED", "Proposta requer autorização BP", {
                "attempt_id": attempt_id, "reason_code": decision.reason_code,
            })
        timestamp = at or datetime.now(UTC)
        if (timestamp.tzinfo is None or timestamp.utcoffset() is None
                or timestamp < attempt.created_at or timestamp < case.created_at):
            raise ValueError("reservation time must be timezone-aware and after creation")
        attempt.status = AttemptStatus.RESERVED
        attempt.response_deadline_at = timestamp + timedelta(
            minutes=plan_policy.response_timeout_minutes
        )
        session.flush()  # The SQLite reservation trigger requires `reserved` first.
        reservation = Reservation(reservation_id=f"res-{uuid4()}",
                                  attempt_id=attempt.attempt_id,
                                  reserved_hours=task.estimated_hours,
                                  created_at=timestamp)
        session.add(reservation)
        audit.record(session, case_id=case.case_id,
                     attempt_id=attempt.attempt_id, actor=actor,
                     action="reservation.created", timestamp=timestamp,
                     policy_version=plan_policy.policy_version,
                     result={"reserved_hours": float(task.estimated_hours),
                             "reason_code": decision.reason_code})
        cases.recalculate_case_status(session, case, actor=actor,
                                      reason="Capacidade reservada; aguardando convite",
                                      at=timestamp)
        session.flush()
    return reservation
