from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer

from app.enums import Priority, TaskStatus


class TaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    title: str
    assignee_employee_id: str
    team_id: str
    priority: Priority
    due_at: AwareDatetime
    estimated_hours: Annotated[
        Decimal,
        Field(gt=0, allow_inf_nan=False),
        PlainSerializer(float, return_type=float, when_used="json"),
    ]
    required_skills: list[str]
    status: TaskStatus
    transfer_allowed: bool
    source_system: str
    external_id: str
    updated_at: AwareDatetime
