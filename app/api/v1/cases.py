"""Contracted HTTP case operations."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session, sessionmaker
import os

from app.api.v1.query_parameters import reject_uncontracted_parameters
from app.db import get_session
from app.services.planning import plan_and_authorize
from app.services.dispatch import dispatch_pending

router = APIRouter(dependencies=[Depends(reject_uncontracted_parameters)])


@router.post("/cases/{case_id}/plan", tags=["cases"])
def plan_case(case_id: str, background_tasks: BackgroundTasks,
              session: Annotated[Session, Depends(get_session)]) -> dict:
    result = plan_and_authorize(session, case_id, actor="api:cases")
    if os.getenv("N8N_DISPATCH_URL") and os.getenv("N8N_DISPATCH_TOKEN"):
        background_tasks.add_task(dispatch_pending,
                                  sessionmaker(bind=session.get_bind()),
                                  case_id=case_id)
    return result
