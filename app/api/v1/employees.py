from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.query_parameters import reject_uncontracted_parameters
from app.db import get_session
from app.schemas.employees import EmployeeResponse
from app.schemas.errors import QUERY_ERROR_RESPONSES
from app.services.queries import list_employees

router = APIRouter(
    dependencies=[Depends(reject_uncontracted_parameters)],
    responses=QUERY_ERROR_RESPONSES,
)


@router.get("/employees", response_model=list[EmployeeResponse], tags=["employees"])
def employees(
    session: Annotated[Session, Depends(get_session)],
) -> list[EmployeeResponse]:
    return list_employees(session)
