from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer

from app.enums import Availability

# JSON hours are numbers as required by the contract, not Decimal strings.
NonnegativeHours = Annotated[
    Decimal,
    Field(ge=0, allow_inf_nan=False),
    PlainSerializer(float, return_type=float, when_used="json"),
]


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: str
    name: str
    team_id: str
    skills: list[str]
    shift_hours: NonnegativeHours
    committed_hours: NonnegativeHours
    reserved_hours: NonnegativeHours
    availability: Availability
    preferred_channel: Literal["slack"]
    channel_user_id: str
    source_system: str
    external_id: str
    updated_at: AwareDatetime
