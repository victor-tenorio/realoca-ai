"""Contracted HTTP case operations."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
import os

from app.api.v1.query_parameters import reject_uncontracted_parameters
from app.db import get_session
from app.services.planning import ESCALATION_OPTIONS, plan_and_authorize
from app.services.dispatch import dispatch_pending
from app.enums import AttemptStatus
from app.errors import APIError
from app.models import Case, CoverageAttempt

router = APIRouter(dependencies=[Depends(reject_uncontracted_parameters)])


@router.get("/cases", tags=["cases"])
def list_cases(session: Annotated[Session, Depends(get_session)]) -> dict:
    """Authoritative summary, including the real pending-BP count."""
    items = []
    for case in session.scalars(select(Case).order_by(Case.created_at.desc(), Case.case_id)):
        pending = session.scalars(select(CoverageAttempt).where(
            CoverageAttempt.case_id == case.case_id,
            CoverageAttempt.status.in_({AttemptStatus.PENDING_APPROVAL,
                                        AttemptStatus.ESCALATED}),
        )).all()
        escalated = sum(item.status == AttemptStatus.ESCALATED for item in pending)
        items.append({
            "case_id": case.case_id, "status": case.status.value,
            "plan_version": case.plan_version,
            "created_at": case.created_at.isoformat(),
            "task_count": len(case.tasks),
            "pending_approval_count": len(pending) - escalated,
            "escalation_count": escalated,
            "requires_bp_review": bool(pending),
        })
    return {"cases": items, "total": len(items)}


@router.get("/cases/{case_id}", tags=["cases"])
def get_case(case_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    case = session.get(Case, case_id)
    if case is None:
        raise APIError(404, "CASE_NOT_FOUND", "Caso não encontrado", {})
    proposals = list(session.scalars(select(CoverageAttempt).where(
        CoverageAttempt.case_id == case_id,
    ).order_by(CoverageAttempt.plan_version, CoverageAttempt.created_at)))
    return {
        "case_id": case.case_id, "status": case.status.value,
        "plan_version": case.plan_version,
        "created_at": case.created_at.isoformat(),
        "absences": [{"absence_id": absence.absence_id,
                      "employee_id": absence.employee_id}
                     for absence in case.absences],
        "tasks": [{"task_id": task.task_id, "title": task.title,
                   "status": task.status.value,
                   "assignee_employee_id": task.assignee_employee_id}
                  for task in case.tasks],
        "proposals": [{
            "attempt_id": item.attempt_id, "task_id": item.task_id,
            "candidate_employee_id": item.candidate_employee_id,
            "status": item.status.value, "reason": item.reason,
            "plan_version": item.plan_version,
            "approval_decision": item.approval_decision,
            "approval_actor_id": item.approval_actor_id,
            "response_deadline_at": (item.response_deadline_at.isoformat()
                                     if item.response_deadline_at else None),
        } for item in proposals],
        "pending_approvals": [item.attempt_id for item in proposals
                              if item.status == AttemptStatus.PENDING_APPROVAL],
        "escalations": [{
            "attempt_id": item.attempt_id,
            "task_id": item.task_id,
            "reason_code": item.reason,
            "alternatives": ESCALATION_OPTIONS.get(
                item.reason, ["Revisão manual do BP", "Rever prazo"]),
        } for item in proposals if item.status == AttemptStatus.ESCALATED],
    }


@router.post("/cases/{case_id}/plan", tags=["cases"])
def plan_case(case_id: str, background_tasks: BackgroundTasks,
              session: Annotated[Session, Depends(get_session)]) -> dict:
    result = plan_and_authorize(session, case_id, actor="api:cases")
    if os.getenv("N8N_DISPATCH_URL") and os.getenv("N8N_DISPATCH_TOKEN"):
        background_tasks.add_task(dispatch_pending,
                                  sessionmaker(bind=session.get_bind()),
                                  case_id=case_id)
    return result
