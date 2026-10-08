"""Summary / compliance aggregation endpoints.

Exposes read-only aggregation endpoints mounted at ``/api/v1/summary``:

* ``GET /monthly?year=&month=`` — a :class:`ComplianceSummary` for one month.
* ``GET /annual?year=`` — an :class:`AnnualSummary` with a 12-month breakdown.

Each handler wires an :class:`EntryRepository` (built from the request-scoped
:class:`AsyncSession`) into the pure-function :class:`ComplianceService`.

``year`` is constrained to 2000–2099 and ``month`` to 1–12 via FastAPI
``Query`` bounds, so out-of-range values yield an HTTP ``422`` response with an
identifying message naming the offending parameter.

Requirements: 6.1, 6.2, 6.3, 7.1, 7.2, 7.5, 7.6
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.repository import EntryRepository
from backend.schemas import AnnualSummary, ComplianceSummary
from backend.services.compliance_service import ComplianceService

router = APIRouter(prefix="/api/v1/summary", tags=["summary"])

# Query-parameter constraints. Out-of-range values produce a 422 whose error
# message identifies the parameter by name (via the ``description``).
_YearParam = Annotated[
    int,
    Query(ge=2000, le=2099, description="Calendar year in the range 2000-2099"),
]
_MonthParam = Annotated[
    int,
    Query(ge=1, le=12, description="Calendar month in the range 1-12"),
]


@router.get("/monthly", response_model=ComplianceSummary)
async def monthly_summary(
    year: _YearParam,
    month: _MonthParam,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ComplianceSummary:
    """Return the compliance summary for the given ``year``/``month``."""
    repository = EntryRepository(db)
    entries = await repository.get_by_month(year, month)
    service = ComplianceService()
    return service.calculate_monthly(entries, year=year, month=month)


@router.get("/annual", response_model=AnnualSummary)
async def annual_summary(
    year: _YearParam,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AnnualSummary:
    """Return the annual summary (12-month breakdown) for the given ``year``."""
    repository = EntryRepository(db)
    entries = await repository.get_by_year(year)
    service = ComplianceService()
    return service.calculate_annual(entries, year=year)
