from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.query_parameters import reject_uncontracted_parameters
from app.db import get_session
from app.schemas.errors import QUERY_ERROR_RESPONSES
from app.schemas.tasks import TaskResponse
from app.services.queries import list_tasks

router = APIRouter(
    dependencies=[Depends(reject_uncontracted_parameters)],
    responses=QUERY_ERROR_RESPONSES,
)


@router.get("/tasks", response_model=list[TaskResponse], tags=["tasks"])
def tasks(session: Annotated[Session, Depends(get_session)]) -> list[TaskResponse]:
    return list_tasks(session)
