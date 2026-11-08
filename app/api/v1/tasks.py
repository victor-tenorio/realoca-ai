from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.query_parameters import reject_uncontracted_parameters
from app.db import get_session
from app.schemas.errors import QUERY_ERROR_RESPONSES
from app.schemas.tasks import TaskResponse
from app.services.queries import list_tasks
from app.services.task_completion import complete_task

router = APIRouter(
    dependencies=[Depends(reject_uncontracted_parameters)],
    responses=QUERY_ERROR_RESPONSES,
)


@router.get("/tasks", response_model=list[TaskResponse], tags=["tasks"])
def tasks(session: Annotated[Session, Depends(get_session)]) -> list[TaskResponse]:
    return list_tasks(session)


@router.post("/tasks/{task_id}/complete", tags=["tasks"])
def complete_source_task(task_id: str, session: Annotated[Session, Depends(get_session)]) -> dict:
    return complete_task(session, task_id)
