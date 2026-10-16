"""Failing tests for the Flet ``AppState`` dataclass (TDD red phase — task 10.1).

These tests describe the behaviour of the yet-to-be-implemented
``app.state`` module. They are expected to FAIL at import time
(``app.state`` does not exist yet) until task 10.2 implements it.

The state interface under test (from the design document)::

    @dataclass
    class AppState:
        entries: dict[str, WorkEntry]       # key: ISO date "YYYY-MM-DD"
        selected_month: date
        compliance_summary: ComplianceSummary | None
        is_loading: bool
        error_message: str | None

The in-memory ``AppState`` holds everything the Flet UI renders: the logged
entries keyed by ISO date, the month currently displayed, the latest
compliance summary, a loading flag, and the current error message. These
tests exercise pure dataclass logic only — the Flet runtime is never started.

Requirements: 1.4, 1.5
"""

from __future__ import annotations

from datetime import date

from app.api_client import ComplianceSummary, WorkEntry, WorkLocation
from app.state import AppState

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _entry(
    entry_id: int = 1,
    work_date: str = "2025-06-10",
    location: WorkLocation = WorkLocation.DENMARK,
) -> WorkEntry:
    """Build a ``WorkEntry`` matching the backend response schema."""
    return WorkEntry(
        id=entry_id,
        work_date=date.fromisoformat(work_date),
        location=location,
        created_at="2025-06-10T08:00:00+00:00",
        updated_at="2025-06-10T08:00:00+00:00",
    )


def _summary(year: int = 2025, month: int = 6) -> ComplianceSummary:
    """Build a ``ComplianceSummary`` matching the backend response schema."""
    return ComplianceSummary(
        year=year,
        month=month,
        total_days=20,
        denmark_days=12,
        vacation_days=3,
        sick_days=1,
        home_days=4,
        compliance_pct=80.0,
        is_compliant=True,
    )


# ---------------------------------------------------------------------------
# Initial state (Requirement 1.4)
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_initial_state_has_empty_entries_dict(self) -> None:
        state = AppState(selected_month=date(2025, 6, 1))

        assert state.entries == {}

    def test_initial_state_is_not_loading(self) -> None:
        state = AppState(selected_month=date(2025, 6, 1))

        assert state.is_loading is False

    def test_initial_state_has_no_error_message(self) -> None:
        state = AppState(selected_month=date(2025, 6, 1))

        assert state.error_message is None

    def test_initial_state_has_no_compliance_summary(self) -> None:
        state = AppState(selected_month=date(2025, 6, 1))

        assert state.compliance_summary is None

    def test_each_instance_gets_its_own_entries_dict(self) -> None:
        """A mutable default must not be shared between instances."""
        first = AppState(selected_month=date(2025, 6, 1))
        second = AppState(selected_month=date(2025, 7, 1))

        first.entries["2025-06-10"] = _entry()

        assert second.entries == {}


# ---------------------------------------------------------------------------
# Applying a new entry (Requirement 1.4)
# ---------------------------------------------------------------------------


class TestApplyEntry:
    def test_applying_a_new_entry_updates_entries_by_date(self) -> None:
        state = AppState(selected_month=date(2025, 6, 1))
        entry = _entry(work_date="2025-06-10", location=WorkLocation.DENMARK)

        state.apply_entry(entry)

        assert state.entries["2025-06-10"] == entry

    def test_applying_an_entry_for_an_existing_date_replaces_it(self) -> None:
        state = AppState(selected_month=date(2025, 6, 1))
        original = _entry(work_date="2025-06-10", location=WorkLocation.DENMARK)
        updated = _entry(work_date="2025-06-10", location=WorkLocation.HOME)

        state.apply_entry(original)
        state.apply_entry(updated)

        assert len(state.entries) == 1
        assert state.entries["2025-06-10"] == updated
        assert state.entries["2025-06-10"].location == WorkLocation.HOME


# ---------------------------------------------------------------------------
# Clearing the error (Requirement 1.5)
# ---------------------------------------------------------------------------


class TestClearError:
    def test_clearing_error_resets_error_message_to_none(self) -> None:
        state = AppState(
            selected_month=date(2025, 6, 1),
            error_message="Could not reach the backend",
        )

        state.clear_error()

        assert state.error_message is None

    def test_clearing_error_is_idempotent_when_already_none(self) -> None:
        state = AppState(selected_month=date(2025, 6, 1))

        state.clear_error()

        assert state.error_message is None
