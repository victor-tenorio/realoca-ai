"""Append audit rows inside the caller's transaction; never commit independently."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(
    session: Session,
    *,
    case_id: str,
    actor: str,
    action: str,
    timestamp: datetime,
    result: dict,
    reason: str | None = None,
    policy_version: int | None = None,
    attempt_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        audit_event_id=f"audit-{uuid4()}",
        case_id=case_id,
        attempt_id=attempt_id,
        actor=actor,
        action=action,
        timestamp=timestamp,
        policy_version=policy_version,
        reason=reason,
        result=result,
    )
    session.add(event)
    return event
