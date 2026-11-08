"""Read-only audit timeline, optionally scoped to one case."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import APIError
from app.services.reporting import audit_timeline

router = APIRouter()


def validate_query(request: Request):
    unexpected = set(request.query_params) - {"case_id"}
    if unexpected:
        raise APIError(400, "INVALID_QUERY_PARAMETERS", "Parâmetros inválidos", {
            "parameters": sorted(unexpected),
        })


@router.get("/audit", tags=["audit"], dependencies=[Depends(validate_query)])
def audit_events(session: Annotated[Session, Depends(get_session)],
                 case_id: Annotated[str | None, Query()] = None) -> dict:
    return audit_timeline(session, case_id=case_id)
