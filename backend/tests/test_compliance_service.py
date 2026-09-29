"""Failing tests for ``ComplianceService`` (TDD red phase — task 4.1).

These tests describe the behaviour of the yet-to-be-implemented
``backend.services.compliance_service.ComplianceService``. They are expected to
FAIL at import time (``backend.services.compliance_service`` does not exist yet)
until task 4.2 implements it.

The service interface under test (from the design document)::

    class ComplianceService:
        def calculate_monthly(self, entries: list[WorkEntry]) -> ComplianceSummary: ...
        def calculate_annual(self, entries: list[WorkEntry]) -> AnnualSummary: ...

``ComplianceService`` is a pure-function service — no database or mocks are
needed. ``WorkEntry`` is constructed directly with a ``work_date`` and a string
``location`` (matching the ORM column type).

Requirements: 6.3, 6.4, 6.5, 6.6, 7.2, 7.3, 7.4, 7.5, 13.3, 14.3
"""

from datetime import date

import pytest

from backend.models import WorkEntry
from backend.services.compliance_service import ComplianceService


def _entry(work_date: date, location: str) -> WorkEntry:
    """Build a transient ``WorkEntry`` for a pure-function calculation."""
    return WorkEntry(work_date=work_date, location=location)


# ---------------------------------------------------------------------------
# calculate_monthly
# ---------------------------------------------------------------------------


class TestCalculateMonthly:
    def test_empty_list_returns_zeroed_non_compliant_summary(self) -> None:
        svc = ComplianceService()

        result = svc.calculate_monthly([])

        assert result.total_days == 0
        assert result.compliance_pct == 0.0
        assert result.is_compliant is False

    def test_one_denmark_one_home_is_fifty_percent_and_compliant(self) -> None:
        svc = ComplianceService()
        entries = [
            _entry(date(2025, 6, 2), "denmark"),
            _entry(date(2025, 6, 3), "home"),
        ]

        result = svc.calculate_monthly(entries)

        assert result.total_days == 2
        assert result.denmark_days == 1
        assert result.home_days == 1
        assert result.compliance_pct == 50.0
        assert result.is_compliant is True

    def test_empty_list_preserves_requested_year_and_month(self) -> None:
        # Regression for #2: an empty period must keep the requested labels
        # instead of defaulting to year/month 0.
        svc = ComplianceService()

        result = svc.calculate_monthly([], year=2025, month=3)

        assert result.year == 2025
        assert result.month == 3
        assert result.total_days == 0
        assert result.is_compliant is False

    def test_only_home_entries_is_not_compliant(self) -> None:
        svc = ComplianceService()
        entries = [
            _entry(date(2025, 6, 2), "home"),
            _entry(date(2025, 6, 3), "home"),
            _entry(date(2025, 6, 4), "home"),
        ]

        result = svc.calculate_monthly(entries)

        assert result.total_days == 3
        assert result.home_days == 3
        assert result.compliance_pct == 0.0
        assert result.is_compliant is False

    def test_vacation_counts_as_compliant_like_denmark(self) -> None:
        svc = ComplianceService()
        entries = [
            _entry(date(2025, 6, 2), "vacation"),
            _entry(date(2025, 6, 3), "home"),
        ]

        result = svc.calculate_monthly(entries)

        assert result.total_days == 2
        assert result.vacation_days == 1
        assert result.compliance_pct == 50.0
        assert result.is_compliant is True

    def test_sick_counts_as_compliant_like_denmark(self) -> None:
        svc = ComplianceService()
        entries = [
            _entry(date(2025, 6, 2), "sick"),
            _entry(date(2025, 6, 3), "home"),
        ]

        result = svc.calculate_monthly(entries)

        assert result.total_days == 2
        assert result.sick_days == 1
        assert result.compliance_pct == 50.0
        assert result.is_compliant is True

    def test_mixed_compliant_locations_all_count_together(self) -> None:
        svc = ComplianceService()
        entries = [
            _entry(date(2025, 6, 2), "denmark"),
            _entry(date(2025, 6, 3), "vacation"),
            _entry(date(2025, 6, 4), "sick"),
            _entry(date(2025, 6, 5), "home"),
        ]

        result = svc.calculate_monthly(entries)

        assert result.total_days == 4
        assert result.denmark_days == 1
        assert result.vacation_days == 1
        assert result.sick_days == 1
        assert result.home_days == 1
        # 3 of 4 compliant days -> 75%
        assert result.compliance_pct == 75.0
        assert result.is_compliant is True


# ---------------------------------------------------------------------------
# calculate_annual
# ---------------------------------------------------------------------------


class TestCalculateAnnual:
    def test_returns_exactly_twelve_monthly_summaries(self) -> None:
        svc = ComplianceService()
        entries = [
            _entry(date(2025, 1, 10), "denmark"),
            _entry(date(2025, 6, 15), "home"),
            _entry(date(2025, 12, 31), "vacation"),
        ]

        result = svc.calculate_annual(entries)

        assert len(result.monthly_breakdown) == 12

    def test_months_with_no_entries_have_zero_total_days(self) -> None:
        svc = ComplianceService()
        # Only January and December have entries.
        entries = [
            _entry(date(2025, 1, 10), "denmark"),
            _entry(date(2025, 12, 31), "home"),
        ]

        result = svc.calculate_annual(entries)

        by_month = {s.month: s for s in result.monthly_breakdown}
        # Months 2 through 11 have no entries.
        for month in range(2, 12):
            assert by_month[month].total_days == 0

    def test_empty_year_preserves_requested_year_on_summary_and_breakdown(
        self,
    ) -> None:
        # Regression for #2: a year with no entries must retain the requested
        # year on the annual summary and on all 12 monthly breakdown items.
        svc = ComplianceService()

        result = svc.calculate_annual([], year=2025)

        assert result.year == 2025
        assert len(result.monthly_breakdown) == 12
        for month, summary in enumerate(result.monthly_breakdown, start=1):
            assert summary.year == 2025
            assert summary.month == month
            assert summary.total_days == 0

    def test_populated_year_labels_empty_months_with_requested_year(self) -> None:
        # Regression for #2: even when some months have entries, empty months
        # must be labeled with the requested year (not inferred/0).
        svc = ComplianceService()
        entries = [
            _entry(date(2025, 1, 10), "denmark"),
            _entry(date(2025, 12, 31), "home"),
        ]

        result = svc.calculate_annual(entries, year=2025)

        for month, summary in enumerate(result.monthly_breakdown, start=1):
            assert summary.year == 2025
            assert summary.month == month

    def test_annual_rollup_totals_equal_sum_of_monthly_breakdown(self) -> None:
        svc = ComplianceService()
        entries = [
            _entry(date(2025, 1, 10), "denmark"),
            _entry(date(2025, 1, 11), "home"),
            _entry(date(2025, 3, 5), "vacation"),
            _entry(date(2025, 6, 15), "sick"),
            _entry(date(2025, 6, 16), "denmark"),
            _entry(date(2025, 12, 31), "home"),
        ]

        result = svc.calculate_annual(entries)

        assert result.total_days == sum(s.total_days for s in result.monthly_breakdown)
        assert result.denmark_days == sum(
            s.denmark_days for s in result.monthly_breakdown
        )
        assert result.vacation_days == sum(
            s.vacation_days for s in result.monthly_breakdown
        )
        assert result.sick_days == sum(s.sick_days for s in result.monthly_breakdown)
        assert result.home_days == sum(s.home_days for s in result.monthly_breakdown)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
