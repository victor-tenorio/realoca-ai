"""Contracted BP decision endpoint; changes happen in the service transaction."""

from typing import Annotated, Literal
import os

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.query_parameters import reject_uncontracted_parameters
from app.db import get_session
from app.services.approvals import decide_atomic
from app.services.dispatch import dispatch_pending

router = APIRouter(dependencies=[Depends(reject_uncontracted_parameters)])


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    actor_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


@router.post("/proposals/{attempt_id}/approval", tags=["proposals"])
def decide_approval(attempt_id: str, request: ApprovalRequest,
                    background_tasks: BackgroundTasks,
                    session: Annotated[Session, Depends(get_session)]) -> dict:
    result = decide_atomic(session, attempt_id, decision=request.decision,
                           actor_id=request.actor_id, reason=request.reason)
    if (request.decision == "approve" and not result.get("duplicate")
            and os.getenv("N8N_DISPATCH_URL") and os.getenv("N8N_DISPATCH_TOKEN")):
        background_tasks.add_task(dispatch_pending, sessionmaker(bind=session.get_bind()),
                                  case_id=result["case_id"])
    return result
