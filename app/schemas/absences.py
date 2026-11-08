from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from app.enums import CaseStatus

Identifier = Annotated[str, Field(min_length=1, pattern=r"\S")]


class AbsenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: Identifier
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    confirmed: StrictBool
    source_system: Identifier
    external_id: Identifier

    @field_validator("starts_at", "ends_at", mode="before")
    @classmethod
    def iso_string_required(cls, value):
        if not isinstance(value, str):
            # Pydantic v2 propagates TypeError instead of reporting invalid input.
            raise ValueError("ISO 8601 string with timezone required")  # noqa: TRY004
        return value

    @model_validator(mode="after")
    def valid_period(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class AbsenceCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    absence_id: str
    case_id: str
    status: CaseStatus
