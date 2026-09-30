"""Aggregation / compliance endpoints.

Exposes the ``/api/v1/summary`` router. Each handler fetches the relevant
entries through an :class:`EntryRepository` (bound to the request-scoped
``AsyncSession``) and delegates the compliance calculation to the pure-function
:class:`ComplianceService`.

The requested ``year``/``month`` are passed explicitly into the service so that
empty periods still carry the requested labels (rather than defaulting to 0).

Validation: ``year`` must be in ``2000-2099`` and ``month`` in ``1-12``;
FastAPI returns ``422`` with an identifying message otherwise.

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

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/monthly", response_model=ComplianceSummary)
async def monthly_summary(
    db: SessionDep,
    year: Annotated[
        int, Query(ge=2000, le=2099, description="Year in range 2000-2099")
    ],
    month: Annotated[int, Query(ge=1, le=12, description="Month in range 1-12")],
) -> ComplianceSummary:
    """Return the compliance summary for a single month."""
    repo = EntryRepository(db)
    entries = await repo.get_by_month(year, month)
    service = ComplianceService()
    return service.calculate_monthly(entries, year=year, month=month)


@router.get("/annual", response_model=AnnualSummary)
async def annual_summary(
    db: SessionDep,
    year: Annotated[
        int, Query(ge=2000, le=2099, description="Year in range 2000-2099")
    ],
) -> AnnualSummary:
    """Return the annual compliance summary with a 12-month breakdown."""
    repo = EntryRepository(db)
    entries = await repo.get_by_year(year)
    service = ComplianceService()
    return service.calculate_annual(entries, year=year)
