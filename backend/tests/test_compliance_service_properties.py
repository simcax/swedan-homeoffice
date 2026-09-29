"""Property-based tests for ``ComplianceService`` (tasks 4.3–4.7).

Uses ``hypothesis`` to verify universal properties of the pure-function
compliance calculations that should hold across all valid inputs, complementing
the example-based tests in ``test_compliance_service.py``.

``ComplianceService`` has no database dependency — it operates on plain
``WorkEntry`` ORM instances constructed in-memory — so these tests build
entry lists directly with ``hypothesis`` strategies and call the service
synchronously.

Requirements: 6.3, 6.4, 6.5, 6.6, 7.2, 7.3, 13.3, 14.3
"""

import math
from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from backend.models import WorkEntry
from backend.schemas import WorkLocation
from backend.services.compliance_service import ComplianceService

# A fixed, valid work_date is sufficient for monthly calculations: the service
# only inspects the number and location of entries, not the specific date.
_FIXED_DATE = date(2025, 1, 1)

# Reasonable per-location count bounds keep example sizes bounded while still
# exploring the full partition space (all-zero through mixed populations).
_count = st.integers(min_value=0, max_value=100)

# All four location enum values, used to generate arbitrary entry lists.
_locations = st.sampled_from([loc.value for loc in WorkLocation])


def _entry(location: str, work_date: date = _FIXED_DATE) -> WorkEntry:
    """Build an in-memory ``WorkEntry`` with the given location and date."""
    return WorkEntry(work_date=work_date, location=location)


def _build_entries(
    denmark: int, vacation: int, sick: int, home: int
) -> list[WorkEntry]:
    """Build an entry list with the requested count of each location type."""
    return (
        [_entry("denmark") for _ in range(denmark)]
        + [_entry("vacation") for _ in range(vacation)]
        + [_entry("sick") for _ in range(sick)]
        + [_entry("home") for _ in range(home)]
    )


# Arbitrary entry lists (locations only; count/mix left to hypothesis).
_entry_lists = st.lists(
    _locations.map(_entry),
    min_size=0,
    max_size=100,
)


class TestCompliancePartitionProperty:
    @given(denmark=_count, vacation=_count, sick=_count, home=_count)
    @settings(max_examples=100, deadline=None)
    def test_location_counts_partition_total(
        self, denmark: int, vacation: int, sick: int, home: int
    ) -> None:
        """**Validates: Requirements 6.6, 7.3**

        Property 3: Compliance Partition
        For arbitrary non-negative counts of each location type, the returned
        summary always satisfies
        ``denmark_days + vacation_days + sick_days + home_days == total_days ==
        len(entries)``.
        """
        entries = _build_entries(denmark, vacation, sick, home)
        result = ComplianceService().calculate_monthly(entries)

        partition_sum = (
            result.denmark_days
            + result.vacation_days
            + result.sick_days
            + result.home_days
        )
        assert partition_sum == result.total_days
        assert result.total_days == len(entries)


class TestCompliancePercentageFormulaProperty:
    @given(entries=_entry_lists.filter(lambda e: len(e) > 0))
    @settings(max_examples=100, deadline=None)
    def test_percentage_matches_formula_for_non_empty(
        self, entries: list[WorkEntry]
    ) -> None:
        """**Validates: Requirements 6.3, 6.4**

        Property 4: Compliance Percentage Formula
        For any non-empty entry list, ``compliance_pct`` equals
        ``((denmark_days + vacation_days + sick_days) / total_days) * 100.0``.
        """
        result = ComplianceService().calculate_monthly(entries)

        compliant = result.denmark_days + result.vacation_days + result.sick_days
        expected_pct = (compliant / result.total_days) * 100.0
        assert math.isclose(result.compliance_pct, expected_pct, rel_tol=1e-9)

    def test_empty_list_is_zero_and_non_compliant(self) -> None:
        """**Validates: Requirements 6.3, 6.4**

        Property 4: Compliance Percentage Formula (empty case)
        For an empty entry list, ``compliance_pct`` equals ``0.0`` and
        ``is_compliant`` equals ``False``.
        """
        result = ComplianceService().calculate_monthly([])

        assert result.compliance_pct == 0.0
        assert result.is_compliant is False


class TestComplianceThresholdProperty:
    @given(entries=_entry_lists)
    @settings(max_examples=100, deadline=None)
    def test_is_compliant_iff_pct_at_least_threshold(
        self, entries: list[WorkEntry]
    ) -> None:
        """**Validates: Requirements 6.5**

        Property 5: Compliance Threshold
        For any arbitrary entry list, ``is_compliant`` is ``True`` if and only
        if ``compliance_pct >= 50.0``.
        """
        result = ComplianceService().calculate_monthly(entries)

        assert result.is_compliant == (result.compliance_pct >= 50.0)


class TestVacationSickComplianceEquivalenceProperty:
    @given(entries=_entry_lists)
    @settings(max_examples=100, deadline=None)
    def test_vacation_sick_equivalent_to_denmark(
        self, entries: list[WorkEntry]
    ) -> None:
        """**Validates: Requirements 6.3, 6.4, 13.3, 14.3**

        Property 11: Vacation/Sick Compliance Equivalence
        Replacing every ``vacation``/``sick`` entry with a ``denmark`` entry
        (leaving ``home`` untouched) leaves ``compliance_pct`` and
        ``is_compliant`` unchanged, because all three count as compliant days.
        """
        substituted = [
            _entry("denmark", e.work_date)
            if e.location in ("vacation", "sick")
            else _entry(e.location, e.work_date)
            for e in entries
        ]

        service = ComplianceService()
        original = service.calculate_monthly(entries)
        replaced = service.calculate_monthly(substituted)

        assert math.isclose(
            original.compliance_pct, replaced.compliance_pct, rel_tol=1e-9
        )
        assert original.is_compliant == replaced.is_compliant


class TestAnnualBreakdownCompletenessProperty:
    @given(
        month_day_pairs=st.lists(
            st.tuples(
                st.integers(min_value=1, max_value=12),
                _locations,
            ),
            min_size=0,
            max_size=100,
        )
    )
    @settings(max_examples=100, deadline=None)
    def test_annual_breakdown_has_twelve_months(
        self, month_day_pairs: list[tuple[int, str]]
    ) -> None:
        """**Validates: Requirements 7.2, 7.5**

        Property 7: Annual Breakdown Completeness
        For any set of entries spread across a single year, ``calculate_annual``
        returns a ``monthly_breakdown`` of exactly 12 summaries (one per month),
        and any month with no entries has ``total_days == 0``.
        """
        # All entries share year 2025; a valid day-of-month (1) keeps dates
        # legal for every month while still exercising varied months.
        entries = [
            _entry(location, date(2025, month, 1))
            for month, location in month_day_pairs
        ]
        months_with_entries = {month for month, _ in month_day_pairs}

        result = ComplianceService().calculate_annual(entries)

        assert len(result.monthly_breakdown) == 12
        # Breakdown covers months 1–12 exactly once each.
        assert [s.month for s in result.monthly_breakdown] == list(range(1, 13))

        for summary in result.monthly_breakdown:
            if summary.month not in months_with_entries:
                assert summary.total_days == 0
