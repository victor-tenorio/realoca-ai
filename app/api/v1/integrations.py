"""Authenticated, durable inbox for n8n callbacks (business effects run separately)."""

import os
from datetime import datetime, timedelta, timezone
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.enums import AttemptStatus, Channel, IntegrationEventType
from app.models import CoverageAttempt, OutboundMessage, ProcessedEvent

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])

RESPONSE_EVENTS = {
    IntegrationEventType.ACCEPTED,
    IntegrationEventType.REFUSED,
    IntegrationEventType.EXPIRED,
}
PENDING_STATES = {AttemptStatus.RESERVED, AttemptStatus.NOTIFIED}


class AttemptEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=200)
    event_type: IntegrationEventType
    attempt_id: str = Field(min_length=1, max_length=200)
    channel: Channel
    occurred_at: datetime
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(timezone.utc)


def _same_event(stored: ProcessedEvent, data: AttemptEvent) -> bool:
    return (
        stored.event_type == data.event_type
        and stored.attempt_id == data.attempt_id
        and stored.channel == data.channel
        and stored.occurred_at == data.occurred_at
        and stored.reason == data.reason
    )


def _replay(stored: ProcessedEvent, data: AttemptEvent) -> dict[str, str | bool]:
    if not _same_event(stored, data):
        raise HTTPException(status.HTTP_409_CONFLICT, "event_id already belongs to another payload")
    return {"event_id": data.event_id, "status": "queued" if stored.processed_at is None else "processed", "duplicate": True}


def _validate_event(session: Session, data: AttemptEvent, now: datetime) -> None:
    attempt = session.get(CoverageAttempt, data.attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown attempt_id")
    if data.occurred_at > now + timedelta(seconds=60) or data.occurred_at < attempt.created_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "callback time outside attempt window")

    # A callback must refer to an actual, non-simulated offer on this channel.
    offer = session.scalar(select(OutboundMessage.message_id).where(
        OutboundMessage.attempt_id == data.attempt_id,
        OutboundMessage.channel == data.channel,
        OutboundMessage.simulated.is_(False),
    ).limit(1))
    if offer is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no real offer for attempt/channel")

    if attempt.status not in PENDING_STATES:
        raise HTTPException(status.HTTP_409_CONFLICT, "attempt is not awaiting a response")
    if attempt.response_deadline_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "attempt has no response deadline")

    if data.event_type in {IntegrationEventType.ACCEPTED, IntegrationEventType.REFUSED}:
        if now >= attempt.response_deadline_at or data.occurred_at >= attempt.response_deadline_at:
            raise HTTPException(status.HTTP_409_CONFLICT, "response deadline has passed")
    elif data.event_type == IntegrationEventType.EXPIRED:
        if now < attempt.response_deadline_at or data.occurred_at < attempt.response_deadline_at:
            raise HTTPException(status.HTTP_409_CONFLICT, "attempt has not expired")

    if data.event_type in RESPONSE_EVENTS:
        competing = session.scalar(select(ProcessedEvent.event_id).where(
            ProcessedEvent.attempt_id == data.attempt_id,
            ProcessedEvent.event_type.in_(RESPONSE_EVENTS),
        ).limit(1))
        if competing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "response for this attempt already received")


@router.post("/attempt-events", status_code=status.HTTP_202_ACCEPTED)
def receive_attempt_event(
    data: AttemptEvent,
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
    session: Session = Depends(get_session),
) -> dict[str, str | bool]:
    """Acknowledge durable receipt, NOT task reassignment or employee acceptance.

    Events stay unprocessed in the inbox until a separate transition worker applies
    policy, capacity, reservation release and assignment atomically.
    """
    expected = os.getenv("INTEGRATIONS_INTERNAL_TOKEN")
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "integration authentication not configured")
    if not x_internal_token or not compare_digest(x_internal_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal token")

    existing = session.get(ProcessedEvent, data.event_id)
    if existing is not None:
        return _replay(existing, data)

    now = datetime.now(timezone.utc)
    _validate_event(session, data, now)
    session.add(ProcessedEvent(
        event_id=data.event_id, event_type=data.event_type, attempt_id=data.attempt_id,
        channel=data.channel, occurred_at=data.occurred_at, reason=data.reason,
        received_at=now, processed_at=None, result=None, response_status=None,
    ))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.get(ProcessedEvent, data.event_id)
        if existing is not None:
            return _replay(existing, data)
        raise HTTPException(status.HTTP_409_CONFLICT, "conflicting callback") from None

    return {"event_id": data.event_id, "status": "queued", "duplicate": False}
