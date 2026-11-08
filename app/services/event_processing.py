"""A14/A15: apply durable n8n callbacks to authoritative task/case state."""

import logging
import os
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, text

from app.enums import AttemptStatus, IntegrationEventType, TaskStatus
from app.errors import APIError
from app.models import (
    Absence, Case, CoverageAttempt, MessageDelivery, OutboundMessage,
    ProcessedEvent, Reservation, Shift, TaskAssignment,
)
from app.services import audit, capacity, cases, policy
from app.services.deadlines import expiry_timestamp_reaches_deadline

logger = logging.getLogger(__name__)


def _apply_accepted(session, event, attempt, now):
    """Swap a real reservation for committed hours; never accept a mere invite."""
    reservation = attempt.reservation
    task, employee = attempt.affected_task, attempt.candidate
    case = session.get(Case, attempt.case_id)
    if (attempt.status not in {AttemptStatus.RESERVED, AttemptStatus.NOTIFIED}
            or reservation is None or reservation.released_at is not None
            or employee is None or task.status == TaskStatus.DONE):
        raise APIError(409, "OFFER_NOT_ACTIVE", "Oferta sem reserva ativa", {})
    if (event.occurred_at >= attempt.response_deadline_at
            or event.received_at >= attempt.response_deadline_at):
        raise APIError(409, "OFFER_EXPIRED", "Resposta recebida após o prazo", {})
    shift = session.get(Shift, task.shift_id)
    if shift is None:
        raise APIError(409, "SHIFT_MISSING", "Turno não encontrado", {})
    absent = set(session.scalars(select(Absence.employee_id).where(
        Absence.confirmed.is_(True),
        Absence.starts_at < shift.ends_at,
        Absence.ends_at > shift.starts_at,
    )))
    absent.update(absence.employee_id for absence in case.absences if absence.confirmed)
    live = capacity.employee_capacity(session, employee.employee_id, task.shift_id,
                                      max_utilization_pct=attempt.policy.max_utilization_pct)
    # The employee's own reserved hours are converted to committed hours, not
    # demanded a second time. Other outstanding reservations remain counted.
    if live.reserved_hours < reservation.reserved_hours:
        raise APIError(409, "RESERVATION_INCONSISTENT", "Reserva inconsistente", {})
    without_own = capacity.calculate_capacity(
        live.shift_hours, live.committed_hours,
        live.reserved_hours - reservation.reserved_hours,
        attempt.policy.max_utilization_pct,
    )
    decision = policy.classify(task, employee, attempt.policy, without_own,
                               absent_employee_ids=absent)
    if decision.action == "inviable":
        raise APIError(409, "ACCEPTANCE_CONFLICT", decision.reason,
                       {"reason_code": decision.reason_code})
    if decision.action == "needs_approval" and attempt.approval_decision != "approve":
        raise APIError(409, "BP_APPROVAL_REQUIRED", "Falta autorização do BP", {})
    original_owner = {absence.employee_id for absence in case.absences}
    if task.assignee_employee_id not in original_owner:
        raise APIError(409, "SOURCE_TASK_CHANGED", "Atribuição na origem mudou", {})
    old_owner = task.assignee_employee_id
    reservation.released_at = now
    session.flush()  # SQLite trigger requires releasing before source reassignment.
    task.assignee_employee_id = employee.employee_id
    task.status = TaskStatus.IN_PROGRESS
    task.updated_at = now
    session.add(TaskAssignment(
        assignment_id=f"assign-{uuid4()}", task_id=task.task_id,
        from_employee_id=old_owner, to_employee_id=employee.employee_id,
        occurred_at=now, reason=f"Aceite registrado: {event.event_id}",
    ))
    attempt.status = AttemptStatus.ACCEPTED
    attempt.responded_at = now
    attempt.decision_actor_id = f"n8n:{event.channel.value}"
    audit.record(session, case_id=case.case_id, attempt_id=attempt.attempt_id,
                 actor="integration:n8n", action="offer.accepted",
                 timestamp=now, policy_version=attempt.policy_version,
                 result={"from_employee_id": old_owner,
                         "to_employee_id": employee.employee_id,
                         "task_id": task.task_id, "event_id": event.event_id})
    cases.recalculate_case_status(session, case, actor="integration:n8n",
                                  reason="Aceite confirmado e tarefa redistribuída", at=now)
    return {"status": "accepted", "task_id": task.task_id,
            "assignee_employee_id": employee.employee_id}


def _apply_declined(session, event, attempt, now):
    if attempt.status not in {AttemptStatus.RESERVED, AttemptStatus.NOTIFIED}:
        raise APIError(409, "OFFER_NOT_ACTIVE", "Tentativa já finalizada", {})
    if attempt.reservation is None or attempt.reservation.released_at is not None:
        raise APIError(409, "RESERVATION_MISSING", "Sem reserva ativa", {})
    if event.event_type == IntegrationEventType.EXPIRED:
        if (not expiry_timestamp_reaches_deadline(
                event.occurred_at, attempt.response_deadline_at)
                or event.received_at < attempt.response_deadline_at):
            raise APIError(409, "NOT_YET_EXPIRED", "Tentativa ainda no prazo", {})
        next_status = AttemptStatus.EXPIRED
    else:
        if (event.occurred_at >= attempt.response_deadline_at
                or event.received_at >= attempt.response_deadline_at):
            raise APIError(409, "OFFER_EXPIRED", "Recusa recebida após prazo", {})
        next_status = AttemptStatus.REFUSED
    attempt.reservation.released_at = now
    session.flush()  # SQLite trigger requires release before terminal status.
    attempt.status = next_status
    attempt.responded_at = now
    attempt.decision_actor_id = f"n8n:{event.channel.value}"
    case = session.get(Case, attempt.case_id)
    audit.record(session, case_id=attempt.case_id, attempt_id=attempt.attempt_id,
                 actor="integration:n8n", action=f"offer.{attempt.status.value}",
                 timestamp=now, policy_version=attempt.policy_version,
                 reason=event.reason,
                 result={"event_id": event.event_id, "released_hours":
                         float(attempt.reservation.reserved_hours)})
    cases.recalculate_case_status(session, case, actor="integration:n8n",
                                  reason="Resposta negativa: reserva liberada", at=now)
    return {"status": attempt.status.value, "task_id": attempt.task_id,
            "replan_needed": True}


def _apply_delivery(session, event, attempt, now):
    if event.event_type == IntegrationEventType.DELIVERED:
        message = session.scalar(select(OutboundMessage).where(
            OutboundMessage.attempt_id == attempt.attempt_id,
        ).limit(1))
        delivery = (session.scalar(select(MessageDelivery).where(
            MessageDelivery.message_id == message.message_id,
            MessageDelivery.sent_at.is_not(None),
        ).order_by(MessageDelivery.delivery_number.desc()).limit(1)) if message else None)
        if delivery is not None and delivery.delivered_at is None:
            delivery.delivered_at = max(now, delivery.sent_at)
    audit.record(session, case_id=attempt.case_id, attempt_id=attempt.attempt_id,
                 actor="integration:n8n", action=event.event_type.value,
                 timestamp=now, policy_version=attempt.policy_version,
                 reason=event.reason, result={"event_id": event.event_id})
    return {"status": "recorded", "task_id": attempt.task_id}


def _mark_rejected(session_factory, event_id: str, error: APIError):
    with session_factory() as session:
        with session.begin():
            if session.get_bind().dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            event = session.get(ProcessedEvent, event_id)
            if event is None or event.processed_at is not None:
                return
            attempt = session.get(CoverageAttempt, event.attempt_id)
            now = max(datetime.now(UTC), event.received_at)
            event.processed_at = now
            event.response_status = error.status_code
            event.result = {"status": "rejected", "error_code": error.code}
            audit.record(session, case_id=attempt.case_id,
                         attempt_id=attempt.attempt_id,
                         actor="integration:n8n", action="offer.event_rejected",
                         timestamp=now, policy_version=attempt.policy_version,
                         reason=error.message,
                         result={"event_id": event_id, "error_code": error.code})


def process_event(session_factory, event_id: str) -> dict:
    """Process once after durable inbox commit; preserve rejected event evidence."""
    try:
        with session_factory() as session:
            with session.begin():
                if session.get_bind().dialect.name == "sqlite":
                    session.execute(text("BEGIN IMMEDIATE"))
                event = session.get(ProcessedEvent, event_id)
                if event is None:
                    raise APIError(404, "EVENT_NOT_FOUND", "Evento não encontrado", {})
                if event.processed_at is not None:
                    return event.result
                attempt = session.get(CoverageAttempt, event.attempt_id)
                if attempt is None:
                    raise APIError(409, "ATTEMPT_NOT_FOUND", "Tentativa ausente", {})
                now = max(datetime.now(UTC), event.received_at, attempt.created_at)
                if event.event_type == IntegrationEventType.ACCEPTED:
                    result = _apply_accepted(session, event, attempt, now)
                elif event.event_type in {IntegrationEventType.REFUSED, IntegrationEventType.EXPIRED}:
                    result = _apply_declined(session, event, attempt, now)
                else:
                    result = _apply_delivery(session, event, attempt, now)
                event.processed_at = now
                event.response_status = 200
                event.result = result
                task_attempt_id = event.attempt_id
                task_case_id = attempt.case_id
    except APIError as error:
        _mark_rejected(session_factory, event_id, error)
        return {"status": "rejected", "error_code": error.code}
    except Exception:
        # Background responses were already acknowledged 202. Preserve the
        # unprocessed inbox row for explicit replay instead of losing the event.
        logger.exception("Could not process callback %s; inbox retained", event_id)
        return {"status": "queued", "error_code": "RETRY_REQUIRED"}
    if result.get("replan_needed"):
        from app.services.planning import replan_failed_task

        try:
            replan_failed_task(session_factory, task_attempt_id,
                               actor="integration:n8n")
            if os.getenv("N8N_DISPATCH_URL") and os.getenv("N8N_DISPATCH_TOKEN"):
                from app.services.dispatch import dispatch_pending

                dispatch_pending(session_factory, case_id=task_case_id)
        except Exception:
            # Refusal and capacity release are already durable; retry the
            # replan separately after investigating the source inconsistency.
            logger.exception("Replanning after callback %s requires retry", event_id)
    return result


def process_pending(session_factory):
    """Safe manual catch-up after a restart; used by the backend worker."""
    with session_factory() as session:
        ids = list(session.scalars(select(ProcessedEvent.event_id).where(
            ProcessedEvent.processed_at.is_(None),
        ).order_by(ProcessedEvent.received_at).limit(50)))
    return [process_event(session_factory, event_id) for event_id in ids]


def retry_unplanned_failures(session_factory):
    """Retry A15 if a crash happened after releasing a reservation."""
    with session_factory() as session:
        failures = list(session.scalars(select(CoverageAttempt.attempt_id).where(
            CoverageAttempt.status.in_({AttemptStatus.REFUSED, AttemptStatus.EXPIRED}),
        ).order_by(CoverageAttempt.responded_at).limit(50)))
    from app.services.planning import replan_failed_task

    results = []
    for attempt_id in failures:
        try:
            results.append(replan_failed_task(session_factory, attempt_id,
                                              actor="worker:recovery"))
        except APIError:
            logger.exception("Could not replan failed attempt %s", attempt_id)
    return results


if __name__ == "__main__":
    from app.db import SessionLocal

    print({"callbacks": process_pending(SessionLocal),
           "replans": retry_unplanned_failures(SessionLocal)})
