"""A12: durable Slack offer outbox and safe delivery to the n8n webhook."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy import select, text, exists
from sqlalchemy.orm import Session

from app.enums import AttemptStatus, Channel
from app.errors import APIError
from app.models import CoverageAttempt, MessageDelivery, OutboundMessage
from app.services import audit

MAX_DELIVERY_ATTEMPTS = 3


def offer_payload(message: OutboundMessage) -> dict:
    """Exact outgoing offer.created contract; no internal credential included."""
    attempt = message.attempt
    task, candidate = attempt.affected_task, attempt.candidate
    return {
        "event_id": message.event_id, "event_type": "offer.created",
        "case_id": attempt.case_id, "attempt_id": attempt.attempt_id,
        "task_id": task.task_id, "task_title": task.title,
        "estimated_hours": float(task.estimated_hours),
        "due_at": task.due_at.isoformat(),
        "candidate_employee_id": candidate.employee_id,
        "candidate_name": candidate.name, "channel": message.channel.value,
        "channel_user_id": message.channel_user_id,
        "response_deadline_at": attempt.response_deadline_at.isoformat(),
        "message": message.message,
    }


def queue_offer(
    session: Session, attempt: CoverageAttempt, *, actor: str,
    at: datetime | None = None,
) -> OutboundMessage:
    """Insert exactly one immutable offer; caller commits with reservation.

    A queued offer is not yet notified; the network sender changes the attempt
    only after a successful response from n8n.
    """
    if attempt.status not in {AttemptStatus.RESERVED, AttemptStatus.NOTIFIED}:
        raise APIError(409, "OFFER_NOT_AUTHORIZED", "Proposta não está reservada", {})
    previous = session.scalar(select(OutboundMessage).where(
        OutboundMessage.attempt_id == attempt.attempt_id,
    ).limit(1))
    if previous is not None:
        return previous
    employee, task = attempt.candidate, attempt.affected_task
    if (employee is None or employee.preferred_channel != Channel.SLACK
            or not employee.channel_user_id or not employee.channel_user_id.strip()):
        raise APIError(409, "SLACK_RECIPIENT_MISSING", "Destinatário Slack ausente", {})
    if attempt.response_deadline_at is None or task.due_at is None:
        raise APIError(409, "OFFER_DATA_MISSING", "Prazo de proposta ou tarefa ausente", {})
    timestamp = at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None or timestamp < attempt.created_at:
        raise ValueError("outbox time must be aware and after attempt creation")
    message = OutboundMessage(
        message_id=f"msg-{uuid4()}", event_id=f"evt-out-{uuid4()}",
        event_type="offer.created", attempt_id=attempt.attempt_id,
        channel=Channel.SLACK, channel_user_id=employee.channel_user_id,
        message=(f"{employee.name}, você pode assumir temporariamente a tarefa "
                 f"{task.title} ({task.estimated_hours}h), com prazo "
                 f"{task.due_at.isoformat()}? Aceitar / Recusar."),
        simulated=False, created_at=timestamp,
    )
    session.add(message)
    audit.record(session, case_id=attempt.case_id,
                 attempt_id=attempt.attempt_id, actor=actor,
                 action="offer.queued", timestamp=timestamp,
                 policy_version=attempt.policy_version,
                 result={"event_id": message.event_id, "channel": "slack"})
    session.flush()
    return message


def send_queued_offer(
    session_factory,
    message_id: str,
    *,
    actor: str = "api:dispatch",
    url: str | None = None,
    token: str | None = None,
    post=None,
) -> dict:
    """Send once or retry a failed delivery; never replay a successful send.

    The claim and finalization are separate short transactions; no SQLite lock
    is held during HTTP. Only environment/server arguments supply secrets.
    """
    destination = url or os.getenv("N8N_DISPATCH_URL")
    secret = token or os.getenv("N8N_DISPATCH_TOKEN")
    if not destination or not secret:
        raise APIError(503, "DISPATCH_NOT_CONFIGURED", "Webhook n8n não configurado", {})
    if not actor or not actor.strip():
        raise ValueError("actor is required")

    with session_factory() as session:
        with session.begin():
            if session.get_bind().dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            message = session.get(OutboundMessage, message_id)
            if message is None:
                raise APIError(404, "MESSAGE_NOT_FOUND", "Oferta não encontrada", {})
            previous = list(session.scalars(select(MessageDelivery).where(
                MessageDelivery.message_id == message_id
            ).order_by(MessageDelivery.delivery_number)))
            if any(item.sent_at is not None for item in previous):
                return {"event_id": message.event_id, "status": "sent", "duplicate": True}
            if len(previous) >= MAX_DELIVERY_ATTEMPTS:
                raise APIError(409, "DELIVERY_RETRY_EXHAUSTED",
                               "Limite de tentativas de envio excedido", {
                                   "attempt_id": message.attempt_id,
                               })
            if any(item.failed_at is None for item in previous):
                raise APIError(409, "DISPATCH_IN_PROGRESS", "Oferta em envio", {})
            if message.attempt.status != AttemptStatus.RESERVED:
                raise APIError(409, "OFFER_NOT_AUTHORIZED", "Oferta não está reservada", {})
            payload = offer_payload(message)
            now = datetime.now(UTC)
            delivery = MessageDelivery(
                delivery_id=f"delivery-{uuid4()}", message_id=message_id,
                delivery_number=len(previous) + 1,
                started_at=max(now, message.created_at),
            )
            session.add(delivery)
            delivery_id = delivery.delivery_id

    transport = post or httpx.post
    error_code = None
    try:
        response = transport(destination, json=payload,
                             headers={"X-Internal-Token": secret}, timeout=7)
        if not 200 <= response.status_code < 300:
            error_code = "N8N_NON_2XX"
    except (httpx.HTTPError, OSError, TimeoutError):
        error_code = "N8N_UNREACHABLE"

    with session_factory() as session:
        with session.begin():
            if session.get_bind().dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            delivery = session.get(MessageDelivery, delivery_id)
            message = session.get(OutboundMessage, message_id)
            now = max(datetime.now(UTC), delivery.started_at)
            if error_code:
                delivery.failed_at = now
                delivery.error_code = error_code
                audit.record(session, case_id=message.attempt.case_id,
                             attempt_id=message.attempt_id, actor=actor,
                             action="offer.send_failed", timestamp=now,
                             policy_version=message.attempt.policy_version,
                             result={"event_id": message.event_id, "error_code": error_code})
                if delivery.delivery_number >= MAX_DELIVERY_ATTEMPTS:
                    audit.record(session, case_id=message.attempt.case_id,
                                 attempt_id=message.attempt_id, actor=actor,
                                 action="offer.delivery_escalated",
                                 timestamp=now,
                                 policy_version=message.attempt.policy_version,
                                 reason="Limite de 3 tentativas de entrega",
                                 result={"event_id": message.event_id,
                                         "error_code": error_code,
                                         "attempts": delivery.delivery_number})
            else:
                delivery.sent_at = now
                message.attempt.status = AttemptStatus.NOTIFIED
                audit.record(session, case_id=message.attempt.case_id,
                             attempt_id=message.attempt_id, actor=actor,
                             action="offer.dispatched", timestamp=now,
                             policy_version=message.attempt.policy_version,
                             result={"event_id": message.event_id})
            session.flush()
    if error_code:
        raise APIError(503, "N8N_DISPATCH_FAILED", "Falha ao enviar proposta", {
            "event_id": payload["event_id"], "error_code": error_code,
        })
    return {"event_id": payload["event_id"], "status": "sent", "duplicate": False}


def dispatch_pending(session_factory, *, case_id: str | None = None) -> dict:
    """Deliver outstanding authorized offers; safe to run after a process restart.

    This is an explicit worker entry point, not a request for an n8n execution
    during tests. The network sender's claim prevents concurrent duplicates.
    """
    with session_factory() as session:
        query = select(OutboundMessage.message_id).join(
            CoverageAttempt, CoverageAttempt.attempt_id == OutboundMessage.attempt_id
        ).where(
            CoverageAttempt.status == AttemptStatus.RESERVED,
            ~exists().where(
                MessageDelivery.message_id == OutboundMessage.message_id,
                MessageDelivery.sent_at.is_not(None),
            ),
            ~exists().where(
                MessageDelivery.message_id == OutboundMessage.message_id,
                MessageDelivery.delivery_number >= MAX_DELIVERY_ATTEMPTS,
            ),
        ).order_by(OutboundMessage.created_at, OutboundMessage.message_id)
        if case_id is not None:
            query = query.where(CoverageAttempt.case_id == case_id)
        ids = list(session.scalars(query.limit(50)))
    result = {"sent": 0, "failed": 0}
    for message_id in ids:
        try:
            reply = send_queued_offer(session_factory, message_id)
            if not reply["duplicate"]:
                result["sent"] += 1
        except APIError:
            result["failed"] += 1
    return result


if __name__ == "__main__":
    from app.db import SessionLocal

    print(dispatch_pending(SessionLocal))
