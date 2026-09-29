"""Unit tests for backend Pydantic schemas (TDD red phase — task 1.3).

Requirements: 2.2, 12.1, 12.2, 12.3, 12.5
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from backend.schemas import WorkEntryCreate, WorkEntryUpdate, WorkLocation

# ---------------------------------------------------------------------------
# WorkLocation
# ---------------------------------------------------------------------------


class TestWorkLocation:
    def test_valid_values_accepted(self):
        assert WorkLocation("home") is WorkLocation.HOME
        assert WorkLocation("denmark") is WorkLocation.DENMARK
        assert WorkLocation("vacation") is WorkLocation.VACATION
        assert WorkLocation("sick") is WorkLocation.SICK

    def test_unknown_value_rejected(self):
        with pytest.raises(ValueError):
            WorkLocation("office")

    def test_unknown_value_rejected_empty_string(self):
        with pytest.raises(ValueError):
            WorkLocation("")

    def test_unknown_value_rejected_mixed_case(self):
        """Enum values are lower-case only; mixed case must not match."""
        with pytest.raises(ValueError):
            WorkLocation("Home")


# ---------------------------------------------------------------------------
# WorkEntryCreate
# ---------------------------------------------------------------------------


class TestWorkEntryCreate:
    def test_accepts_valid_location_and_today(self):
        today = date.today()  # noqa: DTZ011
        entry = WorkEntryCreate(work_date=today, location=WorkLocation.HOME)
        assert entry.location is WorkLocation.HOME
        assert entry.work_date == today

    def test_accepts_all_valid_locations(self):
        today = date.today()  # noqa: DTZ011
        for loc in WorkLocation:
            entry = WorkEntryCreate(work_date=today, location=loc)
            assert entry.location is loc

    def test_accepts_past_date(self):
        past = date.today() - timedelta(days=30)  # noqa: DTZ011
        entry = WorkEntryCreate(work_date=past, location=WorkLocation.DENMARK)
        assert entry.work_date == past

    def test_rejects_tomorrow(self):
        tomorrow = date.today() + timedelta(days=1)  # noqa: DTZ011
        with pytest.raises(ValidationError) as exc_info:
            WorkEntryCreate(work_date=tomorrow, location=WorkLocation.HOME)
        error_text = str(exc_info.value)
        assert "future" in error_text.lower() or "Cannot log" in error_text

    def test_rejects_date_far_in_future(self):
        far_future = date.today() + timedelta(days=365)  # noqa: DTZ011
        with pytest.raises(ValidationError):
            WorkEntryCreate(work_date=far_future, location=WorkLocation.HOME)

    def test_rejects_invalid_location(self):
        today = date.today()  # noqa: DTZ011
        with pytest.raises(ValidationError):
            WorkEntryCreate(work_date=today, location="office")  # type: ignore[arg-type]

    def test_rejects_missing_work_date(self):
        with pytest.raises(ValidationError):
            WorkEntryCreate(location=WorkLocation.HOME)  # type: ignore[call-arg]

    def test_rejects_missing_location(self):
        today = date.today()  # noqa: DTZ011
        with pytest.raises(ValidationError):
            WorkEntryCreate(work_date=today)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# WorkEntryUpdate
# ---------------------------------------------------------------------------


class TestWorkEntryUpdate:
    def test_accepts_all_valid_locations(self):
        for loc in WorkLocation:
            update = WorkEntryUpdate(location=loc)
            assert update.location is loc

    def test_rejects_invalid_location(self):
        with pytest.raises(ValidationError):
            WorkEntryUpdate(location="remote")  # type: ignore[arg-type]

    def test_rejects_missing_location(self):
        with pytest.raises(ValidationError):
            WorkEntryUpdate()  # type: ignore[call-arg]

    def test_rejects_empty_string_location(self):
        with pytest.raises(ValidationError):
            WorkEntryUpdate(location="")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------


# Strategy: generate dates strictly after today.
# hypothesis `dates()` lower bound is set to tomorrow so every generated date
# is always in the future relative to the test run.
_today = datetime.now(tz=timezone.utc).date()
_future_dates = st.dates(min_value=_today + timedelta(days=1))


class TestWorkEntryCreateProperties:
    @given(future_date=_future_dates, location=st.sampled_from(list(WorkLocation)))
    @settings(max_examples=200)
    def test_future_date_always_raises_validation_error(
        self, future_date: date, location: WorkLocation
    ) -> None:
        """**Validates: Requirements 2.1, 2.2, 12.3**

        Property 2: Future Date Rejection
        For any date strictly after date.today() and any valid WorkLocation,
        constructing WorkEntryCreate must always raise ValidationError.
        """
        with pytest.raises(ValidationError):
            WorkEntryCreate(work_date=future_date, location=location)
