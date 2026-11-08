from datetime import date

from pydantic import BaseModel, ConfigDict


class TeamResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: str
    name: str
    reference_date: date
    employee_count: int
    shift_hours: float | None
    committed_hours: float | None
    reserved_hours: float
    occupied_hours: float | None
    utilization_pct: float | None
    complete: bool
