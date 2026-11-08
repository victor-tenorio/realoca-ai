"""V11/V13/V14: opt-in alerts for due offers, BP review, and delivery failure.

Run in the demo terminal: python -m app.services.operational_alerts
Requires N8N_ALERT_URL plus N8N_DISPATCH_TOKEN; never reassigns tasks.
The backend remains authoritative for status, approval and audit.
"""
import os
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select, text

from app.db import SessionLocal
from app.enums import AttemptStatus, Channel
from app.models import AuditEvent, CoverageAttempt, MessageDelivery, OutboundMessage
from app.services.audit import record

SUCCESS_ACTIONS = {
    "offer.reminder": "alert.reminder_sent",
    "bp.approval_requested": "alert.bp_sent",
    "offer.delivery_escalated": "alert.delivery_escalation_sent",
}
MAX_DELIVERY_TRIES = 3


def _event_for_attempt(session, attempt, now):
    """Decide a single next pending operational alert without changing state."""
    events = set(session.scalars(select(AuditEvent.action).where(
        AuditEvent.attempt_id == attempt.attempt_id,
        AuditEvent.action.in_(SUCCESS_ACTIONS.values()),
    )))
    if attempt.status == AttemptStatus.PENDING_APPROVAL:
        if SUCCESS_ACTIONS["bp.approval_requested"] in events:
            return None
        return "bp.approval_requested", (
            f"BP: proposta {attempt.attempt_id} do caso {attempt.case_id} requer "
            f"aprovacao antes de qualquer convite. Analise a politica/motivo "
            f"e decida em POST /api/v1/proposals/{attempt.attempt_id}/approval."
        )
    if attempt.status == AttemptStatus.RESERVED:
        failed = session.scalar(select(func.count(MessageDelivery.delivery_id)).join(
            OutboundMessage, MessageDelivery.message_id == OutboundMessage.message_id,
        ).where(
            OutboundMessage.attempt_id == attempt.attempt_id,
            MessageDelivery.failed_at.is_not(None),
        ))
        if failed >= MAX_DELIVERY_TRIES and SUCCESS_ACTIONS["offer.delivery_escalated"] not in events:
            return "offer.delivery_escalated", (
                f"BP: falha de entrega Slack na proposta {attempt.attempt_id} "
                f"do caso {attempt.case_id} apos {failed} tentativas. "
                "Nao confundir falha de entrega com recusa do funcionario."
            )
    if attempt.status == AttemptStatus.NOTIFIED and attempt.response_deadline_at is not None:
        threshold = attempt.response_deadline_at - timedelta(
            minutes=attempt.policy.reminder_before_expiry_minutes
        )
        if threshold <= now < attempt.response_deadline_at and SUCCESS_ACTIONS["offer.reminder"] not in events:
            return "offer.reminder", (
                f"Lembrete: proposta {attempt.attempt_id} aguardando resposta "
                f"ate {attempt.response_deadline_at.isoformat()}. "
                "Use os botoes da proposta original para Aceitar ou Recusar."
            )
    return None


def pending_alerts(session, now=None):
    """Read-only selection; no alerts for accepted/refused/expired or unqueued work."""
    now = now or datetime.now(UTC)
    rows = session.scalars(select(CoverageAttempt).where(
        CoverageAttempt.status.in_({
            AttemptStatus.PENDING_APPROVAL, AttemptStatus.RESERVED, AttemptStatus.NOTIFIED
        })
    ).order_by(CoverageAttempt.created_at, CoverageAttempt.attempt_id)).all()
    result = []
    for attempt in rows:
        data = _event_for_attempt(session, attempt, now)
        if data:
            event_type, message = data
            result.append({
                "event_type": event_type,
                "event_id": f"evt-operational-{attempt.attempt_id}-{event_type.replace('.', '-')}",
                "case_id": attempt.case_id,
                "attempt_id": attempt.attempt_id,
                "channel": Channel.SLACK.value,
                "message": message,
            })
    return result


def send_once(session_factory=SessionLocal, *, now=None, post=None):
    """One demo worker pass, audited; never changes assignments or approves BP.

    Serialized on SQLite via BEGIN IMMEDIATE through the HTTP send to avoid
    duplicate reminders from two concurrent workers. Keep timeout short.
    """
    now = now or datetime.now(UTC)
    url, token = os.getenv("N8N_ALERT_URL"), os.getenv("N8N_DISPATCH_TOKEN")
    if not url or not token:
        return {"configured": False, "sent": 0, "failed": 0, "skipped": 0}
    with session_factory() as session:
        ids = [entry["attempt_id"] for entry in pending_alerts(session, now)]
    result = {"configured": True, "sent": 0, "failed": 0, "skipped": 0}
    transport = post or httpx.post
    for attempt_id in ids:
        with session_factory() as session:
            with session.begin():
                if session.get_bind().dialect.name == "sqlite":
                    session.execute(text("BEGIN IMMEDIATE"))
                attempt = session.get(CoverageAttempt, attempt_id)
                if attempt is None:
                    result["skipped"] += 1
                    continue
                selected = _event_for_attempt(session, attempt, now)
                if not selected:
                    result["skipped"] += 1
                    continue
                event_type, message = selected
                payload = {
                    "event_type": event_type,
                    "event_id": f"evt-operational-{attempt.attempt_id}-{event_type.replace('.', '-')}",
                    "case_id": attempt.case_id,
                    "attempt_id": attempt.attempt_id,
                    "channel": "slack",
                    "message": message,
                }
                success, error = False, None
                try:
                    response = transport(url, json=payload,
                                         headers={"X-Internal-Token": token}, timeout=5)
                    success = 200 <= response.status_code < 300
                    if not success:
                        error = f"HTTP_{response.status_code}"
                except (httpx.HTTPError, OSError, TimeoutError):
                    error = "TRANSPORT_UNREACHABLE"
                # Never log the secret, raw transport errors, or employee PII.
                record(session, case_id=attempt.case_id,
                       attempt_id=attempt.attempt_id, actor="worker:operational",
                       action=SUCCESS_ACTIONS[event_type] if success else "alert.send_failed",
                       timestamp=max(now, attempt.created_at),
                       policy_version=attempt.policy_version,
                       reason=error,
                       result={"event_id": payload["event_id"],
                               "event_type": event_type, "channel": "slack",
                               "status": "sent" if success else "failed"})
                result["sent" if success else "failed"] += 1
    return result


def main():
    watch = "--watch" in __import__("sys").argv
    if not watch:
        print(send_once())
        return
    print("Operational alert worker active (30-second polling). Ctrl+C to stop.")
    try:
        while True:
            print(send_once(), flush=True)
            time.sleep(30)
    except KeyboardInterrupt:
        print("Worker stopped")


if __name__ == "__main__":
    main()
