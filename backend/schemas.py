from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator


class WorkLocation(str, Enum):
    HOME = "home"
    DENMARK = "denmark"
    VACATION = "vacation"
    SICK = "sick"


class WorkEntryCreate(BaseModel):
    work_date: date
    location: WorkLocation

    @field_validator("work_date")
    @classmethod
    def date_not_in_future(cls, v: date) -> date:
        if v > date.today():  # noqa: DTZ011
            raise ValueError("Cannot log a future date")
        return v


class WorkEntryUpdate(BaseModel):
    location: WorkLocation


class WorkEntryResponse(BaseModel):
    id: int
    work_date: date
    location: WorkLocation
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ComplianceSummary(BaseModel):
    year: int
    month: int
    total_days: int
    denmark_days: int
    vacation_days: int
    sick_days: int
    home_days: int
    compliance_pct: float  # 0.0 – 100.0
    is_compliant: bool  # True when compliance_pct >= 50.0


class AnnualSummary(BaseModel):
    year: int
    total_days: int
    denmark_days: int
    vacation_days: int
    sick_days: int
    home_days: int
    compliance_pct: float
    is_compliant: bool
    monthly_breakdown: list[ComplianceSummary]
