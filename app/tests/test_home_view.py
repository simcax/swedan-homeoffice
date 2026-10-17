"""Tests for the home calendar view (task 12.1).

These tests exercise the home view's business logic (``log_entry``,
``load_month``, ``_shift_month``) with a mocked :class:`APIClient`, and verify
the quick-log buttons are built with the colours required by Requirement 8.2 /
13.5 / 14.5. The Flet runtime is never started.

Requirements: 1.1, 1.4, 1.5, 2.3, 2.4, 2.5, 8.1, 8.2, 13.1, 13.5, 13.6, 14.1,
14.5, 14.6
"""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import flet as ft
import httpx
import pytest

from app.api_client import (
    AnnualSummary,
    APIError,
    ComplianceSummary,
    WorkEntry,
    WorkLocation,
)
from app.state import AppState
from app.views.home_view import (
    _BUTTON_COLORS,
    _handle_long_press,
    _shift_month,
    build_home_view,
    delete_entry,
    edit_entry,
    load_month,
    log_entry,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _entry(day: int, location: WorkLocation, month: int = 6) -> WorkEntry:
    return WorkEntry(
        id=day,
        work_date=date(2025, month, day),
        location=location,
        created_at="2025-06-10T08:00:00+00:00",
        updated_at="2025-06-10T08:00:00+00:00",
    )


def _summary(
    *, compliance_pct: float = 60.0, is_compliant: bool = True, month: int = 6
) -> ComplianceSummary:
    return ComplianceSummary(
        year=2025,
        month=month,
        total_days=10,
        denmark_days=6,
        vacation_days=0,
        sick_days=0,
        home_days=4,
        compliance_pct=compliance_pct,
        is_compliant=is_compliant,
    )


def _annual(year: int = 2025) -> AnnualSummary:
    return AnnualSummary(
        year=year,
        total_days=100,
        denmark_days=60,
        vacation_days=10,
        sick_days=5,
        home_days=25,
        compliance_pct=60.0,
        is_compliant=True,
        monthly_breakdown=[],
    )


def _state(month: int = 6) -> AppState:
    return AppState(selected_month=date(2025, month, 1))


def _api_error(status: int) -> APIError:
    """Build an ``APIError`` whose ``__cause__`` carries ``status``."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status
    cause = httpx.HTTPStatusError(
        f"HTTP {status}", request=MagicMock(spec=httpx.Request), response=response
    )
    error = APIError(f"Request failed with status {status}")
    error.__cause__ = cause
    return error


# ---------------------------------------------------------------------------
# log_entry — success path (Requirements 1.1, 1.4, 13.1, 14.1)
# ---------------------------------------------------------------------------


class TestLogEntrySuccess:
    async def test_applies_entry_to_state(self) -> None:
        state = _state()
        posted = _entry(10, WorkLocation.DENMARK)
        client = MagicMock()
        client.post_entry = AsyncMock(return_value=posted)
        client.get_summary = AsyncMock(return_value=_summary())
        client.get_annual_summary = AsyncMock(return_value=_annual())

        ok = await log_entry(
            state, client, WorkLocation.DENMARK, work_date=date(2025, 6, 10)
        )

        assert ok is True
        assert state.entries["2025-06-10"] is posted

    async def test_refreshes_compliance_summary(self) -> None:
        state = _state()
        client = MagicMock()
        client.post_entry = AsyncMock(return_value=_entry(10, WorkLocation.HOME))
        summary = _summary(compliance_pct=50.0)
        client.get_summary = AsyncMock(return_value=summary)
        client.get_annual_summary = AsyncMock(return_value=_annual())

        await log_entry(state, client, WorkLocation.HOME, work_date=date(2025, 6, 10))

        assert state.compliance_summary is summary
        client.get_summary.assert_awaited_once_with(2025, 6)

    async def test_posts_today_when_no_date_given(self) -> None:
        state = _state()
        today = date.today()  # noqa: DTZ011
        client = MagicMock()
        client.post_entry = AsyncMock(
            return_value=WorkEntry(
                id=1,
                work_date=today,
                location=WorkLocation.VACATION,
                created_at="2025-06-10T08:00:00+00:00",
                updated_at="2025-06-10T08:00:00+00:00",
            )
        )
        client.get_summary = AsyncMock(return_value=_summary())
        client.get_annual_summary = AsyncMock(return_value=_annual())

        await log_entry(state, client, WorkLocation.VACATION)

        client.post_entry.assert_awaited_once_with(
            today.isoformat(), WorkLocation.VACATION
        )

    async def test_clears_previous_error_on_success(self) -> None:
        state = _state()
        state.error_message = "stale error"
        client = MagicMock()
        client.post_entry = AsyncMock(return_value=_entry(10, WorkLocation.SICK))
        client.get_summary = AsyncMock(return_value=_summary())
        client.get_annual_summary = AsyncMock(return_value=_annual())

        await log_entry(state, client, WorkLocation.SICK, work_date=date(2025, 6, 10))

        assert state.error_message is None


# ---------------------------------------------------------------------------
# log_entry — failure path (Requirements 1.5, 13.6, 14.6)
# ---------------------------------------------------------------------------


class TestLogEntryFailure:
    async def test_generic_error_preserves_calendar_state(self) -> None:
        state = _state()
        existing = _entry(5, WorkLocation.DENMARK)
        state.apply_entry(existing)
        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_api_error(500))
        client.get_summary = AsyncMock()

        ok = await log_entry(
            state, client, WorkLocation.HOME, work_date=date(2025, 6, 10)
        )

        assert ok is False
        assert state.error_message is not None
        # The failed entry is NOT added; the pre-existing entry is preserved.
        assert "2025-06-10" not in state.entries
        assert state.entries["2025-06-05"] is existing
        client.get_summary.assert_not_awaited()


# ---------------------------------------------------------------------------
# log_entry — future-date rejection (Requirements 2.3, 2.4, 2.5)
# ---------------------------------------------------------------------------


class TestLogEntryFutureDate:
    async def test_future_date_422_shows_date_adjacent_error(self) -> None:
        state = _state()
        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_api_error(422))
        client.get_summary = AsyncMock()

        ok = await log_entry(
            state, client, WorkLocation.DENMARK, work_date=date(2030, 1, 1)
        )

        assert ok is False
        assert "2030-01-01" in state.error_message

    async def test_future_date_422_adds_nothing_to_state(self) -> None:
        state = _state()
        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_api_error(422))
        client.get_summary = AsyncMock()

        await log_entry(state, client, WorkLocation.DENMARK, work_date=date(2030, 1, 1))

        assert state.entries == {}
        client.get_summary.assert_not_awaited()


# ---------------------------------------------------------------------------
# load_month — month navigation (Requirement 1.4, 5.5)
# ---------------------------------------------------------------------------


class TestLoadMonth:
    async def test_fetches_entries_for_new_month(self) -> None:
        state = _state(month=6)
        client = MagicMock()
        client.get_entries = AsyncMock(
            return_value=[_entry(3, WorkLocation.DENMARK, month=7)]
        )
        client.get_summary = AsyncMock(return_value=_summary(month=7))

        ok = await load_month(state, client, 2025, 7)

        assert ok is True
        client.get_entries.assert_awaited_once_with(2025, 7)
        assert state.selected_month == date(2025, 7, 1)
        assert "2025-07-03" in state.entries

    async def test_replaces_previous_month_entries(self) -> None:
        state = _state(month=6)
        state.apply_entry(_entry(5, WorkLocation.HOME, month=6))
        client = MagicMock()
        client.get_entries = AsyncMock(return_value=[])
        client.get_summary = AsyncMock(return_value=_summary(month=7))

        await load_month(state, client, 2025, 7)

        assert "2025-06-05" not in state.entries
        assert state.entries == {}

    async def test_failure_preserves_existing_grid(self) -> None:
        state = _state(month=6)
        existing = _entry(5, WorkLocation.HOME, month=6)
        state.apply_entry(existing)
        client = MagicMock()
        client.get_entries = AsyncMock(side_effect=_api_error(503))
        client.get_summary = AsyncMock()

        ok = await load_month(state, client, 2025, 7)

        assert ok is False
        assert state.selected_month == date(2025, 6, 1)
        assert state.entries["2025-06-05"] is existing
        assert state.error_message is not None


# ---------------------------------------------------------------------------
# _shift_month
# ---------------------------------------------------------------------------


class TestShiftMonth:
    def test_forward_within_year(self) -> None:
        assert _shift_month(date(2025, 6, 1), 1) == (2025, 7)

    def test_backward_within_year(self) -> None:
        assert _shift_month(date(2025, 6, 1), -1) == (2025, 5)

    def test_wraps_forward_across_year_boundary(self) -> None:
        assert _shift_month(date(2025, 12, 1), 1) == (2026, 1)

    def test_wraps_backward_across_year_boundary(self) -> None:
        assert _shift_month(date(2025, 1, 1), -1) == (2024, 12)


# ---------------------------------------------------------------------------
# build_home_view — structure and button colours (Requirement 8.2, 13.5, 14.5)
# ---------------------------------------------------------------------------


class TestBuildHomeView:
    def _flatten(self, control: ft.Control) -> list[ft.Control]:
        """Depth-first flatten of a control tree via ``controls``/``content``."""
        found = [control]
        for child in getattr(control, "controls", None) or []:
            found.extend(self._flatten(child))
        child = getattr(control, "content", None)
        if isinstance(child, ft.Control):
            found.extend(self._flatten(child))
        return found

    def _buttons(self, view: ft.Container) -> list[ft.Button]:
        return [c for c in self._flatten(view) if isinstance(c, ft.Button)]

    def test_returns_container(self) -> None:
        view = build_home_view(MagicMock(spec=ft.Page), _state(), MagicMock())
        assert isinstance(view, ft.Container)

    def test_has_four_log_buttons(self) -> None:
        view = build_home_view(MagicMock(spec=ft.Page), _state(), MagicMock())
        assert len(self._buttons(view)) == 4

    def test_each_button_has_correct_bgcolor(self) -> None:
        view = build_home_view(MagicMock(spec=ft.Page), _state(), MagicMock())
        by_location = {b.data: b for b in self._buttons(view)}

        assert by_location[WorkLocation.DENMARK].bgcolor == ft.Colors.RED_700
        assert by_location[WorkLocation.HOME].bgcolor == ft.Colors.BLUE_700
        assert by_location[WorkLocation.VACATION].bgcolor == ft.Colors.ORANGE_700
        assert by_location[WorkLocation.SICK].bgcolor == ft.Colors.PURPLE_700

    def test_button_colors_mapping_matches_requirement(self) -> None:
        assert _BUTTON_COLORS == {
            WorkLocation.DENMARK: ft.Colors.RED_700,
            WorkLocation.HOME: ft.Colors.BLUE_700,
            WorkLocation.VACATION: ft.Colors.ORANGE_700,
            WorkLocation.SICK: ft.Colors.PURPLE_700,
        }

    def test_contains_a_compliance_bar(self) -> None:
        state = _state()
        state.compliance_summary = _summary()
        view = build_home_view(MagicMock(spec=ft.Page), state, MagicMock())
        assert any(isinstance(c, ft.ProgressBar) for c in self._flatten(view))

    def test_contains_a_calendar_grid(self) -> None:
        view = build_home_view(MagicMock(spec=ft.Page), _state(), MagicMock())
        assert any(isinstance(c, ft.GridView) for c in self._flatten(view))


# ---------------------------------------------------------------------------
# delete_entry (task 12.3 — Requirements 4.2, 4.5, 4.6)
# ---------------------------------------------------------------------------


class TestDeleteEntry:
    async def test_success_clears_tile_from_state(self) -> None:
        state = _state()
        entry = _entry(10, WorkLocation.DENMARK)
        state.apply_entry(entry)
        client = MagicMock()
        client.delete_entry = AsyncMock(return_value=None)
        client.get_summary = AsyncMock(return_value=_summary())
        client.get_annual_summary = AsyncMock(return_value=_annual())

        ok = await delete_entry(state, client, entry)

        assert ok is True
        assert "2025-06-10" not in state.entries
        client.delete_entry.assert_awaited_once_with(entry.id)

    async def test_success_refreshes_compliance_summary(self) -> None:
        state = _state()
        entry = _entry(10, WorkLocation.HOME)
        state.apply_entry(entry)
        client = MagicMock()
        client.delete_entry = AsyncMock(return_value=None)
        summary = _summary(compliance_pct=40.0, is_compliant=False)
        client.get_summary = AsyncMock(return_value=summary)
        client.get_annual_summary = AsyncMock(return_value=_annual())

        await delete_entry(state, client, entry)

        assert state.compliance_summary is summary
        client.get_summary.assert_awaited_once_with(2025, 6)

    async def test_failure_keeps_tile_and_sets_error(self) -> None:
        state = _state()
        entry = _entry(10, WorkLocation.DENMARK)
        state.apply_entry(entry)
        client = MagicMock()
        client.delete_entry = AsyncMock(side_effect=_api_error(500))
        client.get_summary = AsyncMock()

        ok = await delete_entry(state, client, entry)

        assert ok is False
        assert state.entries["2025-06-10"] is entry
        assert state.error_message is not None
        client.get_summary.assert_not_awaited()


# ---------------------------------------------------------------------------
# edit_entry (task 12.3 — Requirements 3.2, 3.5, 3.6)
# ---------------------------------------------------------------------------


class TestEditEntry:
    async def test_success_updates_tile_in_state(self) -> None:
        state = _state()
        original = _entry(10, WorkLocation.HOME)
        state.apply_entry(original)
        updated = _entry(10, WorkLocation.DENMARK)
        client = MagicMock()
        client.patch_entry = AsyncMock(return_value=updated)
        client.get_summary = AsyncMock(return_value=_summary())
        client.get_annual_summary = AsyncMock(return_value=_annual())

        ok = await edit_entry(state, client, original, WorkLocation.DENMARK)

        assert ok is True
        assert state.entries["2025-06-10"] is updated
        client.patch_entry.assert_awaited_once_with(original.id, WorkLocation.DENMARK)

    async def test_success_refreshes_compliance_summary(self) -> None:
        state = _state()
        original = _entry(10, WorkLocation.HOME)
        state.apply_entry(original)
        client = MagicMock()
        client.patch_entry = AsyncMock(return_value=_entry(10, WorkLocation.VACATION))
        summary = _summary(compliance_pct=70.0)
        client.get_summary = AsyncMock(return_value=summary)
        client.get_annual_summary = AsyncMock(return_value=_annual())

        await edit_entry(state, client, original, WorkLocation.VACATION)

        assert state.compliance_summary is summary
        client.get_summary.assert_awaited_once_with(2025, 6)

    async def test_failure_preserves_state_and_sets_error(self) -> None:
        state = _state()
        original = _entry(10, WorkLocation.HOME)
        state.apply_entry(original)
        client = MagicMock()
        client.patch_entry = AsyncMock(side_effect=_api_error(404))
        client.get_summary = AsyncMock()

        ok = await edit_entry(state, client, original, WorkLocation.DENMARK)

        assert ok is False
        assert state.entries["2025-06-10"] is original
        assert state.error_message is not None
        client.get_summary.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_long_press (task 12.3 — Requirement 3.1, 4.1)
# ---------------------------------------------------------------------------


class TestHandleLongPress:
    def test_opens_dialog_for_logged_day(self) -> None:
        state = _state()
        state.apply_entry(_entry(10, WorkLocation.DENMARK))
        page = MagicMock(spec=ft.Page)
        refresh = MagicMock()

        _handle_long_press(page, state, MagicMock(), 10, refresh)

        page.show_dialog.assert_called_once()
        opened = page.show_dialog.call_args.args[0]
        assert isinstance(opened, ft.AlertDialog)

    def test_ignores_unlogged_day(self) -> None:
        state = _state()
        page = MagicMock(spec=ft.Page)
        refresh = MagicMock()

        _handle_long_press(page, state, MagicMock(), 15, refresh)

        page.show_dialog.assert_not_called()


# ---------------------------------------------------------------------------
# Flet 1.0.2 Page API smoke tests (regression for page.open/page.close).
#
# These drive the dialog/snackbar/banner helpers against a ``MagicMock`` that
# is *spec'd* to ``ft.Page``. Because Flet 1.0.2's ``ft.Page`` exposes
# ``show_dialog``/``pop_dialog`` but NOT ``open``/``close``, a spec'd mock would
# raise ``AttributeError`` the moment a helper tried to call the removed API —
# so these tests fail loudly if the old API ever creeps back in.
# ---------------------------------------------------------------------------


class TestPageApiSmoke:
    def test_ft_page_has_no_open_or_close(self) -> None:
        # Guard the premise: the Flet 1.0.2 Page really has no open/close.
        assert not hasattr(ft.Page, "open")
        assert not hasattr(ft.Page, "close")
        assert hasattr(ft.Page, "show_dialog")
        assert hasattr(ft.Page, "pop_dialog")

    def test_open_action_dialog_uses_show_dialog(self) -> None:
        from app.views.home_view import _open_action_dialog

        state = _state()
        entry = _entry(10, WorkLocation.DENMARK)
        page = MagicMock(spec=ft.Page)

        _open_action_dialog(page, state, MagicMock(), entry, MagicMock())

        page.show_dialog.assert_called_once()
        assert isinstance(page.show_dialog.call_args.args[0], ft.AlertDialog)

    def test_open_delete_confirm_uses_show_dialog(self) -> None:
        from app.views.home_view import _open_delete_confirm

        state = _state()
        entry = _entry(10, WorkLocation.DENMARK)
        page = MagicMock(spec=ft.Page)

        _open_delete_confirm(page, state, MagicMock(), entry, MagicMock())

        page.show_dialog.assert_called_once()
        assert isinstance(page.show_dialog.call_args.args[0], ft.AlertDialog)

    def test_dispatch_error_surface_banner_uses_show_dialog(self) -> None:
        from app.views.home_view import ErrorAction, _dispatch_error_surface

        state = _state()
        state.error_action = ErrorAction.BANNER
        state.error_message = "Could not connect."
        page = MagicMock(spec=ft.Page)

        _dispatch_error_surface(page, state, MagicMock(), MagicMock())

        page.show_dialog.assert_called_once()
        assert isinstance(page.show_dialog.call_args.args[0], ft.Banner)

    def test_dialog_cancel_action_pops_dialog(self) -> None:
        # The Cancel button handler must call pop_dialog() (no args), not the
        # removed page.close(dialog) API.
        from app.views.home_view import _open_action_dialog

        state = _state()
        entry = _entry(10, WorkLocation.DENMARK)
        page = MagicMock(spec=ft.Page)

        _open_action_dialog(page, state, MagicMock(), entry, MagicMock())
        dialog = page.show_dialog.call_args.args[0]
        cancel = dialog.actions[0]
        cancel.on_click(MagicMock())

        page.pop_dialog.assert_called_once_with()


# ---------------------------------------------------------------------------
# Fix A — backend-generation guard against a superseded backend
#
# A request started under one backend "era" must not write its result into
# state after a backend switch bumped ``state.backend_generation``. These tests
# simulate the temporal race by having a mocked client method bump the
# generation *before* returning, so the awaited result arrives already stale.
# ---------------------------------------------------------------------------


class TestBackendGenerationGuard:
    async def test_error_refresh_discards_result_after_backend_switch(self) -> None:
        from app.views.home_view import ErrorAction, _dispatch_error_surface

        state = _state()
        state.error_action = ErrorAction.SNACKBAR_REFRESH
        state.error_message = "Entry no longer exists."
        generation = state.backend_generation
        stale_entry = _entry(5, WorkLocation.HOME)

        async def _entries(_year: int, _month: int):
            state.backend_generation += 1
            state.entries.clear()
            return [stale_entry]

        client = MagicMock()
        client.get_entries = AsyncMock(side_effect=_entries)
        client.get_summary = AsyncMock(return_value=_summary())
        page = MagicMock(spec=ft.Page)
        refresh = MagicMock()

        _dispatch_error_surface(
            page, state, client, refresh, generation=generation
        )
        await page.run_task.call_args.args[0]()

        assert state.entries == {}
        refresh.assert_not_called()

    async def test_error_refresh_discards_result_after_month_navigation(self) -> None:
        from app.views.home_view import ErrorAction, _dispatch_error_surface

        state = _state()
        state.error_action = ErrorAction.SNACKBAR_REFRESH
        state.error_message = "Entry no longer exists."
        state.entries.clear()

        async def _entries(_year: int, _month: int):
            state.selected_month = date(2025, 7, 1)
            return [_entry(5, WorkLocation.HOME)]

        client = MagicMock()
        client.get_entries = AsyncMock(side_effect=_entries)
        client.get_summary = AsyncMock(return_value=_summary())
        page = MagicMock(spec=ft.Page)
        refresh = MagicMock()

        _dispatch_error_surface(page, state, client, refresh)
        await page.run_task.call_args.args[0]()

        assert state.selected_month == date(2025, 7, 1)
        assert state.entries == {}
        refresh.assert_not_called()

    async def test_load_month_discards_result_when_generation_bumped(self) -> None:
        state = _state(month=6)
        existing = _entry(5, WorkLocation.HOME, month=6)
        state.apply_entry(existing)
        gen = state.backend_generation

        async def _entries(_year: int, _month: int):
            # A backend switch happens while this request is in flight.
            state.backend_generation += 1
            return [_entry(3, WorkLocation.DENMARK, month=7)]

        client = MagicMock()
        client.get_entries = AsyncMock(side_effect=_entries)
        client.get_summary = AsyncMock(return_value=_summary(month=7))

        ok = await load_month(state, client, 2025, 7, generation=gen)

        assert ok is False
        # The stale result must NOT overwrite the current month/entries.
        assert state.selected_month == date(2025, 6, 1)
        assert state.entries == {"2025-06-05": existing}

    async def test_log_entry_discards_result_when_generation_bumped(self) -> None:
        state = _state()
        gen = state.backend_generation

        async def _post(_iso: str, _loc: WorkLocation):
            state.backend_generation += 1
            return _entry(10, WorkLocation.DENMARK)

        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_post)
        client.get_summary = AsyncMock(return_value=_summary())
        client.get_annual_summary = AsyncMock(return_value=_annual())

        ok = await log_entry(
            state,
            client,
            WorkLocation.DENMARK,
            work_date=date(2025, 6, 10),
            generation=gen,
        )

        assert ok is False
        # Stale entry must not land, and the summary must not be refreshed.
        assert state.entries == {}
        client.get_summary.assert_not_awaited()

    async def test_matching_generation_allows_the_write(self) -> None:
        state = _state()
        posted = _entry(10, WorkLocation.DENMARK)
        client = MagicMock()
        client.post_entry = AsyncMock(return_value=posted)
        client.get_summary = AsyncMock(return_value=_summary())
        client.get_annual_summary = AsyncMock(return_value=_annual())

        ok = await log_entry(
            state,
            client,
            WorkLocation.DENMARK,
            work_date=date(2025, 6, 10),
            generation=state.backend_generation,
        )

        assert ok is True
        assert state.entries["2025-06-10"] is posted

    async def test_generation_none_keeps_legacy_behaviour(self) -> None:
        state = _state(month=6)
        client = MagicMock()
        client.get_entries = AsyncMock(
            return_value=[_entry(3, WorkLocation.DENMARK, month=7)]
        )
        client.get_summary = AsyncMock(return_value=_summary(month=7))
        client.get_annual_summary = AsyncMock(return_value=_annual())

        # No generation passed: writes happen unconditionally even if the
        # counter changes (the guard is disabled).
        state.backend_generation = 99
        ok = await load_month(state, client, 2025, 7)

        assert ok is True
        assert state.selected_month == date(2025, 7, 1)
        assert "2025-07-03" in state.entries


# ---------------------------------------------------------------------------
# Fix B — annual-summary refresh after mutations and on year change
# ---------------------------------------------------------------------------


class TestAnnualRefreshOnMutation:
    async def test_log_entry_refreshes_annual_summary(self) -> None:
        state = _state()
        client = MagicMock()
        client.post_entry = AsyncMock(return_value=_entry(10, WorkLocation.DENMARK))
        client.get_summary = AsyncMock(return_value=_summary())
        annual = _annual()
        client.get_annual_summary = AsyncMock(return_value=annual)

        await log_entry(
            state, client, WorkLocation.DENMARK, work_date=date(2025, 6, 10)
        )

        assert state.annual_summary is annual
        client.get_annual_summary.assert_awaited_once_with(2025)

    async def test_delete_entry_refreshes_annual_summary(self) -> None:
        state = _state()
        entry = _entry(10, WorkLocation.DENMARK)
        state.apply_entry(entry)
        client = MagicMock()
        client.delete_entry = AsyncMock(return_value=None)
        client.get_summary = AsyncMock(return_value=_summary())
        annual = _annual()
        client.get_annual_summary = AsyncMock(return_value=annual)

        await delete_entry(state, client, entry)

        assert state.annual_summary is annual
        client.get_annual_summary.assert_awaited_once_with(2025)

    async def test_edit_entry_refreshes_annual_summary(self) -> None:
        state = _state()
        original = _entry(10, WorkLocation.HOME)
        state.apply_entry(original)
        client = MagicMock()
        client.patch_entry = AsyncMock(return_value=_entry(10, WorkLocation.DENMARK))
        client.get_summary = AsyncMock(return_value=_summary())
        annual = _annual()
        client.get_annual_summary = AsyncMock(return_value=annual)

        await edit_entry(state, client, original, WorkLocation.DENMARK)

        assert state.annual_summary is annual
        client.get_annual_summary.assert_awaited_once_with(2025)

    async def test_failed_annual_refresh_does_not_fail_the_mutation(self) -> None:
        state = _state()
        previous = _annual()
        state.annual_summary = previous
        client = MagicMock()
        client.post_entry = AsyncMock(return_value=_entry(10, WorkLocation.DENMARK))
        client.get_summary = AsyncMock(return_value=_summary())
        client.get_annual_summary = AsyncMock(side_effect=_api_error(503))

        ok = await log_entry(
            state, client, WorkLocation.DENMARK, work_date=date(2025, 6, 10)
        )

        # The mutation still succeeds and the previous annual summary is kept.
        assert ok is True
        assert state.annual_summary is previous


class TestAnnualRefreshOnYearChange:
    async def test_out_of_order_annual_result_for_previous_year_is_discarded(
        self,
    ) -> None:
        from app.views.home_view import _refresh_annual

        state = _state()
        previous = _annual(year=2024)
        state.annual_summary = previous

        async def _annual_for_year(year: int):
            assert year == 2025
            state.selected_month = date(2026, 1, 1)
            return _annual(year=year)

        client = MagicMock()
        client.get_annual_summary = AsyncMock(side_effect=_annual_for_year)

        await _refresh_annual(
            state, client, generation=state.backend_generation
        )

        assert state.annual_summary is previous

    async def test_older_same_year_refresh_cannot_overwrite_newer_result(self) -> None:
        from app.views.home_view import _refresh_annual

        state = _state()
        started = [asyncio.Event(), asyncio.Event()]
        release = [asyncio.Event(), asyncio.Event()]
        results = [_annual(), _annual()]
        request_count = 0

        async def _annual_for_year(_year: int):
            nonlocal request_count
            request_index = request_count
            request_count += 1
            started[request_index].set()
            await release[request_index].wait()
            return results[request_index]

        client = MagicMock()
        client.get_annual_summary = AsyncMock(side_effect=_annual_for_year)

        old_request = asyncio.create_task(
            _refresh_annual(
                state, client, generation=state.backend_generation
            )
        )
        await started[0].wait()
        new_request = asyncio.create_task(
            _refresh_annual(
                state, client, generation=state.backend_generation
            )
        )
        await started[1].wait()

        release[1].set()
        await new_request
        release[0].set()
        await old_request

        assert state.annual_summary is results[1]

    async def test_cross_year_navigation_refreshes_annual_summary(self) -> None:
        # Navigate from Dec 2025 into Jan 2026: the year changes, so the annual
        # summary must be refreshed for the new year.
        state = _state(month=12)
        state.selected_month = date(2025, 12, 1)
        client = MagicMock()
        client.get_entries = AsyncMock(return_value=[])
        client.get_summary = AsyncMock(return_value=_summary(month=1))
        annual_2026 = _annual(year=2026)
        client.get_annual_summary = AsyncMock(return_value=annual_2026)

        ok = await load_month(state, client, 2026, 1)

        assert ok is True
        assert state.selected_month == date(2026, 1, 1)
        client.get_annual_summary.assert_awaited_once_with(2026)
        assert state.annual_summary is annual_2026

    async def test_same_year_navigation_does_not_refresh_annual_summary(self) -> None:
        state = _state(month=6)
        client = MagicMock()
        client.get_entries = AsyncMock(return_value=[])
        client.get_summary = AsyncMock(return_value=_summary(month=7))
        client.get_annual_summary = AsyncMock(return_value=_annual())

        ok = await load_month(state, client, 2025, 7)

        assert ok is True
        client.get_annual_summary.assert_not_awaited()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
