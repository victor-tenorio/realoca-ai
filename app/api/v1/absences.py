from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.v1.query_parameters import reject_uncontracted_parameters
from app.db import get_session
from app.schemas.absences import AbsenceCreate, AbsenceCreated
from app.schemas.errors import ErrorResponse
from app.services.cases import register_confirmed_absence

router = APIRouter(dependencies=[Depends(reject_uncontracted_parameters)])


@router.post(
    "/absences",
    status_code=201,
    response_model=AbsenceCreated,
    tags=["absences"],
    responses={
        200: {"model": AbsenceCreated, "description": "Reenvio idêntico"},
        **{
            status: {"model": ErrorResponse}
            for status in (400, 404, 409, 422, 500, 503)
        },
    },
)
def create_absence(
    payload: AbsenceCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> AbsenceCreated:
    result, response.status_code = register_confirmed_absence(session, payload)
    return result
