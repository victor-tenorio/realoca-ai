"""A11: BP approval is auditable and never bypasses capacity revalidation."""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.enums import AttemptStatus
from app.errors import APIError
from app.models import Case, CoverageAttempt
from app.services import audit, cases, dispatch, reservations


def decide_atomic(
    session: Session, attempt_id: str, *, decision: str,
    actor_id: str, reason: str, at: datetime | None = None,
) -> dict:
    """Approve+reserve+outbox, or reject, within one writer-locked transaction."""
    if decision not in {"approve", "reject"}:
        raise APIError(400, "INVALID_APPROVAL", "Decisão BP inválida", {})
    if not actor_id or not actor_id.strip() or not reason or not reason.strip():
        raise APIError(400, "APPROVAL_DETAILS_REQUIRED", "Ator e motivo obrigatórios", {})
    actor = f"bp:{actor_id}"
    with session.begin():
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        attempt = session.get(CoverageAttempt, attempt_id)
        if attempt is None:
            raise APIError(404, "ATTEMPT_NOT_FOUND", "Tentativa não encontrada", {})
        if attempt.approval_decision is not None:
            if (attempt.approval_decision == decision
                    and attempt.approval_actor_id == actor_id
                    and attempt.approval_reason == reason):
                return {"case_id": attempt.case_id, "attempt_id": attempt_id, "decision": decision,
                        "status": attempt.status.value, "duplicate": True}
            raise APIError(409, "APPROVAL_ALREADY_DECIDED", "Decisão BP já registrada", {})
        if attempt.status != AttemptStatus.PENDING_APPROVAL:
            raise APIError(409, "ATTEMPT_NOT_AWAITING_BP", "Proposta não aguarda BP", {})
        timestamp = at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None or timestamp < attempt.created_at:
            raise ValueError("approval time must be timezone-aware and after proposal")
        attempt.approval_decision = decision
        attempt.approval_actor_id = actor_id
        attempt.approval_reason = reason
        attempt.approval_decided_at = timestamp
        case = session.get(Case, attempt.case_id)
        audit.record(session, case_id=attempt.case_id, attempt_id=attempt_id,
                     actor=actor, action="proposal.approval_decided",
                     timestamp=timestamp, reason=reason,
                     policy_version=attempt.policy_version,
                     result={"decision": decision})
        if decision == "reject":
            attempt.status = AttemptStatus.REJECTED_BY_BP
            cases.recalculate_case_status(session, case, actor=actor,
                                          reason="Proposta rejeitada pelo BP", at=timestamp)
        else:
            reservations.reserve_locked(session, attempt, actor=actor, at=timestamp)
            dispatch.queue_offer(session, attempt, actor=actor, at=timestamp)
        session.flush()
        result = {"case_id": attempt.case_id, "attempt_id": attempt_id, "decision": decision,
                  "status": attempt.status.value, "duplicate": False}
    return result
