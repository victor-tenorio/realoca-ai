"""Metrics derived from persisted cases, attempts and source tasks."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.query_parameters import reject_uncontracted_parameters
from app.db import get_session
from app.services.reporting import dashboard

router = APIRouter(dependencies=[Depends(reject_uncontracted_parameters)])


@router.get("/dashboard", tags=["dashboard"])
def get_dashboard(session: Annotated[Session, Depends(get_session)]) -> dict:
    return dashboard(session)
