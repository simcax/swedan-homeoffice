"""Tests for the stale-write guard helper (:mod:`app.concurrency`).

These exercise the generation-guard logic that was previously open-coded across
``app.main`` and ``app.views.home_view``. The guard snapshots the relevant
generation counters at request start and reports staleness before a write, so
no call path can forget the check. The Flet runtime is never started — the
tests drive a plain :class:`AppState` directly.

Covered:

* :func:`backend_superseded` — the read-side early-out for the backend counter;
* :meth:`WriteGuard.capture` — the per-kind snapshot (and counter bump) at
  request start, including the ``generation=None`` opt-out;
* :meth:`WriteGuard.is_stale` — the write-time check for each
  :class:`GuardKind` (backend switch, newer request, year change).

Requirements: 1.4, 1.5, 8.5
"""

from __future__ import annotations

from datetime import date

from app.concurrency import GuardKind, WriteGuard, backend_superseded
from app.state import AppState


def _state(**kwargs: object) -> AppState:
    state = AppState(selected_month=date(2025, 6, 1))
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


# ---------------------------------------------------------------------------
# backend_superseded
# ---------------------------------------------------------------------------


def test_backend_superseded_none_generation_is_never_stale():
    state = _state(backend_generation=7)

    assert backend_superseded(state, None) is False


def test_backend_superseded_matching_generation_is_not_stale():
    state = _state(backend_generation=3)

    assert backend_superseded(state, 3) is False


def test_backend_superseded_changed_generation_is_stale():
    state = _state(backend_generation=4)

    assert backend_superseded(state, 3) is True


# ---------------------------------------------------------------------------
# WriteGuard.capture — snapshot semantics per kind
# ---------------------------------------------------------------------------


def test_capture_backend_only_does_not_bump_any_counter():
    state = _state(month_load_generation=5, annual_summary_generation=9)

    guard = WriteGuard.capture(state, kind=GuardKind.BACKEND_ONLY, generation=2)

    assert guard.kind is GuardKind.BACKEND_ONLY
    assert guard.backend_generation == 2
    assert guard.request_generation is None
    assert guard.year is None
    # BACKEND_ONLY owns no per-request counter, so nothing is bumped.
    assert state.month_load_generation == 5
    assert state.annual_summary_generation == 9


def test_capture_backend_only_default_kind_and_generation():
    state = _state()

    guard = WriteGuard.capture(state)

    assert guard.kind is GuardKind.BACKEND_ONLY
    assert guard.backend_generation is None


def test_capture_month_bumps_and_records_month_counter():
    state = _state(month_load_generation=4)

    guard = WriteGuard.capture(state, kind=GuardKind.MONTH, generation=1)

    assert guard.kind is GuardKind.MONTH
    assert state.month_load_generation == 5
    assert guard.request_generation == 5
    assert guard.backend_generation == 1


def test_capture_annual_bumps_counter_and_records_year():
    state = _state(annual_summary_generation=2, selected_month=date(2027, 3, 1))

    guard = WriteGuard.capture(state, kind=GuardKind.ANNUAL, generation=0)

    assert guard.kind is GuardKind.ANNUAL
    assert state.annual_summary_generation == 3
    assert guard.request_generation == 3
    assert guard.year == 2027


# ---------------------------------------------------------------------------
# WriteGuard.is_stale — BACKEND_ONLY
# ---------------------------------------------------------------------------


def test_backend_only_guard_fresh_is_not_stale():
    state = _state(backend_generation=1)
    guard = WriteGuard.capture(state, kind=GuardKind.BACKEND_ONLY, generation=1)

    assert guard.is_stale(state) is False


def test_backend_only_guard_detects_backend_switch():
    state = _state(backend_generation=1)
    guard = WriteGuard.capture(state, kind=GuardKind.BACKEND_ONLY, generation=1)

    state.backend_generation = 2

    assert guard.is_stale(state) is True


def test_backend_only_guard_with_none_generation_never_stale():
    state = _state(backend_generation=1)
    guard = WriteGuard.capture(state, kind=GuardKind.BACKEND_ONLY, generation=None)

    state.backend_generation = 99

    assert guard.is_stale(state) is False


# ---------------------------------------------------------------------------
# WriteGuard.is_stale — MONTH
# ---------------------------------------------------------------------------


def test_month_guard_fresh_is_not_stale():
    state = _state(backend_generation=1)
    guard = WriteGuard.capture(state, kind=GuardKind.MONTH, generation=1)

    assert guard.is_stale(state) is False


def test_month_guard_detects_newer_month_load():
    state = _state(backend_generation=1)
    guard = WriteGuard.capture(state, kind=GuardKind.MONTH, generation=1)

    # A newer month load starts (bumps the counter), superseding this request.
    WriteGuard.capture(state, kind=GuardKind.MONTH, generation=1)

    assert guard.is_stale(state) is True


def test_month_guard_detects_backend_switch():
    state = _state(backend_generation=1)
    guard = WriteGuard.capture(state, kind=GuardKind.MONTH, generation=1)

    state.backend_generation = 2

    assert guard.is_stale(state) is True


# ---------------------------------------------------------------------------
# WriteGuard.is_stale — ANNUAL
# ---------------------------------------------------------------------------


def test_annual_guard_fresh_is_not_stale():
    state = _state(backend_generation=1)
    guard = WriteGuard.capture(state, kind=GuardKind.ANNUAL, generation=1)

    assert guard.is_stale(state) is False


def test_annual_guard_detects_newer_annual_refresh():
    state = _state(backend_generation=1)
    guard = WriteGuard.capture(state, kind=GuardKind.ANNUAL, generation=1)

    WriteGuard.capture(state, kind=GuardKind.ANNUAL, generation=1)

    assert guard.is_stale(state) is True


def test_annual_guard_detects_year_change():
    state = _state(backend_generation=1, selected_month=date(2025, 6, 1))
    guard = WriteGuard.capture(state, kind=GuardKind.ANNUAL, generation=1)

    # User navigated to a different year while the request was in flight.
    state.selected_month = date(2026, 1, 1)

    assert guard.is_stale(state) is True


def test_annual_guard_same_year_different_month_is_not_stale():
    state = _state(backend_generation=1, selected_month=date(2025, 6, 1))
    guard = WriteGuard.capture(state, kind=GuardKind.ANNUAL, generation=1)

    # Navigating within the same year does not invalidate the annual summary.
    state.selected_month = date(2025, 11, 1)

    assert guard.is_stale(state) is False


def test_annual_guard_detects_backend_switch():
    state = _state(backend_generation=1)
    guard = WriteGuard.capture(state, kind=GuardKind.ANNUAL, generation=1)

    state.backend_generation = 2

    assert guard.is_stale(state) is True
