from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.query_parameters import reject_uncontracted_parameters
from app.db import get_session
from app.schemas.errors import QUERY_ERROR_RESPONSES
from app.schemas.teams import TeamResponse
from app.services.queries import list_teams

router = APIRouter(
    dependencies=[Depends(reject_uncontracted_parameters)],
    responses=QUERY_ERROR_RESPONSES,
)


@router.get("/teams", response_model=list[TeamResponse], tags=["teams"])
def teams(session: Annotated[Session, Depends(get_session)]) -> list[TeamResponse]:
    return list_teams(session)
