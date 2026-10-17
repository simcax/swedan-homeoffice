"""Tests for API error handling in the home view (task 12.4).

These tests exercise the runtime-free error classifier (``classify_error`` /
``ClassifiedError`` / ``ErrorAction``) and the way the business-logic
coroutines record a classified error on :class:`AppState`. Every one of the
five error cases from Requirement 9 is covered:

* 422 -> inline validation message, values retained, no navigation (9.1).
* 404 -> snack bar toast + refresh the entry list (9.2).
* 409 -> client auto-retries as PATCH; if that also fails show an error
  notification and make no state change (9.3).
* Network timeout / connection error -> banner message, values retained (9.4).
* 503 -> client backs off; if all attempts fail show an error notification and
  make no state change (9.6).

The Flet runtime is never started: the classifier is a pure function and the
coroutines are driven with a mocked :class:`APIClient`.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

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
    ClassifiedError,
    ErrorAction,
    classify_error,
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


def _summary(month: int = 6) -> ComplianceSummary:
    return ComplianceSummary(
        year=2025,
        month=month,
        total_days=10,
        denmark_days=6,
        vacation_days=0,
        sick_days=0,
        home_days=4,
        compliance_pct=60.0,
        is_compliant=True,
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


def _status_error(status: int) -> APIError:
    """Build an ``APIError`` whose ``__cause__`` is an HTTP status error."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status
    cause = httpx.HTTPStatusError(
        f"HTTP {status}", request=MagicMock(spec=httpx.Request), response=response
    )
    error = APIError(f"Request failed with status {status}")
    error.__cause__ = cause
    return error


def _timeout_error() -> APIError:
    """Build an ``APIError`` wrapping an ``httpx.TimeoutException``."""
    cause = httpx.TimeoutException("timed out")
    error = APIError("Request to http://test timed out")
    error.__cause__ = cause
    return error


def _connection_error() -> APIError:
    """Build an ``APIError`` wrapping a transport-level connection fault."""
    cause = httpx.ConnectError("connection refused")
    error = APIError("Request to http://test failed")
    error.__cause__ = cause
    return error


# ---------------------------------------------------------------------------
# classify_error — the pure classification (Requirement 9.1–9.6)
# ---------------------------------------------------------------------------


class TestClassifyError:
    def test_422_is_inline(self) -> None:
        result = classify_error(_status_error(422))
        assert result.action is ErrorAction.INLINE

    def test_422_with_context_mentions_the_date(self) -> None:
        result = classify_error(_status_error(422), context="2030-01-01")
        assert result.action is ErrorAction.INLINE
        assert "2030-01-01" in result.message

    def test_404_is_snackbar_refresh(self) -> None:
        result = classify_error(_status_error(404))
        assert result.action is ErrorAction.SNACKBAR_REFRESH
        assert result.message

    def test_timeout_is_banner(self) -> None:
        result = classify_error(_timeout_error())
        assert result.action is ErrorAction.BANNER
        assert result.message

    def test_connection_error_is_banner(self) -> None:
        result = classify_error(_connection_error())
        assert result.action is ErrorAction.BANNER

    def test_409_is_notification(self) -> None:
        # By the time the view sees a 409 the APIClient has already attempted
        # the automatic PATCH retry and it, too, failed (Requirement 9.3).
        result = classify_error(_status_error(409))
        assert result.action is ErrorAction.NOTIFICATION

    def test_503_is_notification(self) -> None:
        # The APIClient has already exhausted its back-off retries (9.6).
        result = classify_error(_status_error(503))
        assert result.action is ErrorAction.NOTIFICATION

    def test_unknown_status_is_notification(self) -> None:
        result = classify_error(_status_error(500))
        assert result.action is ErrorAction.NOTIFICATION

    def test_result_is_frozen_dataclass(self) -> None:
        result = classify_error(_status_error(404))
        assert isinstance(result, ClassifiedError)
        with pytest.raises(AttributeError):
            result.action = ErrorAction.INLINE  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 422 — inline, values retained, no navigation (Requirement 9.1)
# ---------------------------------------------------------------------------


class Test422Inline:
    async def test_log_entry_records_inline_action(self) -> None:
        state = _state()
        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_status_error(422))
        client.get_summary = AsyncMock()

        ok = await log_entry(
            state, client, WorkLocation.DENMARK, work_date=date(2030, 1, 1)
        )

        assert ok is False
        assert state.error_action is ErrorAction.INLINE
        assert "2030-01-01" in state.error_message

    async def test_values_and_calendar_are_retained(self) -> None:
        state = _state()
        existing = _entry(5, WorkLocation.HOME)
        state.apply_entry(existing)
        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_status_error(422))
        client.get_summary = AsyncMock()

        await log_entry(state, client, WorkLocation.DENMARK, work_date=date(2030, 1, 1))

        # No navigation (selected_month unchanged) and nothing added/removed.
        assert state.selected_month == date(2025, 6, 1)
        assert state.entries == {"2025-06-05": existing}
        client.get_summary.assert_not_awaited()

    async def test_future_date_422_uses_date_adjacent_message(self) -> None:
        # A 422 for a date strictly in the future keeps the future-date wording
        # (the resolved target date is woven into the message).
        state = _state()
        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_status_error(422))
        client.get_summary = AsyncMock()

        ok = await log_entry(
            state, client, WorkLocation.DENMARK, work_date=date(2030, 1, 1)
        )

        assert ok is False
        assert state.error_action is ErrorAction.INLINE
        assert "future" in state.error_message.lower()
        assert "2030-01-01" in state.error_message

    async def test_non_future_date_422_uses_generic_message(self) -> None:
        # A 422 for a date that is NOT in the future must fall back to the
        # generic validation message, not the misleading future-date wording.
        state = _state()
        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_status_error(422))
        client.get_summary = AsyncMock()

        ok = await log_entry(
            state, client, WorkLocation.DENMARK, work_date=date(2024, 1, 1)
        )

        assert ok is False
        assert state.error_action is ErrorAction.INLINE
        assert "future" not in state.error_message.lower()
        assert "2024-01-01" not in state.error_message
        assert "not valid" in state.error_message


# ---------------------------------------------------------------------------
# 404 — snackbar + refresh (Requirement 9.2)
# ---------------------------------------------------------------------------


class Test404SnackbarRefresh:
    async def test_edit_entry_records_snackbar_refresh_action(self) -> None:
        state = _state()
        original = _entry(10, WorkLocation.HOME)
        state.apply_entry(original)
        client = MagicMock()
        client.patch_entry = AsyncMock(side_effect=_status_error(404))
        client.get_summary = AsyncMock()

        ok = await edit_entry(state, client, original, WorkLocation.DENMARK)

        assert ok is False
        assert state.error_action is ErrorAction.SNACKBAR_REFRESH

    async def test_delete_entry_records_snackbar_refresh_action(self) -> None:
        state = _state()
        entry = _entry(10, WorkLocation.DENMARK)
        state.apply_entry(entry)
        client = MagicMock()
        client.delete_entry = AsyncMock(side_effect=_status_error(404))
        client.get_summary = AsyncMock()

        ok = await delete_entry(state, client, entry)

        assert ok is False
        assert state.error_action is ErrorAction.SNACKBAR_REFRESH
        # No state change on failure (the tile is kept until the refresh).
        assert state.entries["2025-06-10"] is entry


# ---------------------------------------------------------------------------
# 409 — client retried as PATCH; final failure is a notification (Req 9.3)
# ---------------------------------------------------------------------------


class Test409Notification:
    async def test_delegation_succeeds_when_client_patch_retry_works(self) -> None:
        # The APIClient transparently converts a 409-on-POST into a PATCH, so a
        # successful post_entry means the retry worked and no error is recorded.
        state = _state()
        client = MagicMock()
        patched = _entry(10, WorkLocation.DENMARK)
        client.post_entry = AsyncMock(return_value=patched)
        client.get_summary = AsyncMock(return_value=_summary())
        client.get_annual_summary = AsyncMock(return_value=_annual())

        ok = await log_entry(
            state, client, WorkLocation.DENMARK, work_date=date(2025, 6, 10)
        )

        assert ok is True
        assert state.error_action is None
        assert state.entries["2025-06-10"] is patched

    async def test_notification_when_client_patch_retry_also_fails(self) -> None:
        # The client surfaces the exhausted 409 retry as an APIError wrapping a
        # 409 status; the view must show a notification and make no change.
        state = _state()
        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_status_error(409))
        client.get_summary = AsyncMock()

        ok = await log_entry(
            state, client, WorkLocation.DENMARK, work_date=date(2025, 6, 10)
        )

        assert ok is False
        assert state.error_action is ErrorAction.NOTIFICATION
        assert state.entries == {}
        client.get_summary.assert_not_awaited()


# ---------------------------------------------------------------------------
# Network timeout / connection error — banner, values retained (Req 9.4)
# ---------------------------------------------------------------------------


class TestNetworkBanner:
    async def test_timeout_records_banner_action(self) -> None:
        state = _state()
        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_timeout_error())
        client.get_summary = AsyncMock()

        ok = await log_entry(
            state, client, WorkLocation.HOME, work_date=date(2025, 6, 10)
        )

        assert ok is False
        assert state.error_action is ErrorAction.BANNER

    async def test_timeout_retains_values_and_does_not_navigate(self) -> None:
        state = _state()
        existing = _entry(5, WorkLocation.HOME)
        state.apply_entry(existing)
        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_connection_error())
        client.get_summary = AsyncMock()

        await log_entry(state, client, WorkLocation.DENMARK, work_date=date(2025, 6, 7))

        assert state.selected_month == date(2025, 6, 1)
        assert state.entries == {"2025-06-05": existing}

    async def test_load_month_timeout_preserves_grid(self) -> None:
        state = _state(month=6)
        existing = _entry(5, WorkLocation.HOME, month=6)
        state.apply_entry(existing)
        client = MagicMock()
        client.get_entries = AsyncMock(side_effect=_timeout_error())
        client.get_summary = AsyncMock()

        ok = await load_month(state, client, 2025, 7)

        assert ok is False
        assert state.error_action is ErrorAction.BANNER
        assert state.selected_month == date(2025, 6, 1)
        assert state.entries["2025-06-05"] is existing


# ---------------------------------------------------------------------------
# 503 — client backed off; final failure is a notification (Req 9.6)
# ---------------------------------------------------------------------------


class Test503Notification:
    async def test_notification_when_backoff_exhausted(self) -> None:
        # The APIClient does the 1s/2s/4s back-off internally; when every
        # attempt fails it raises an APIError wrapping a 503 status.
        state = _state()
        client = MagicMock()
        client.post_entry = AsyncMock(side_effect=_status_error(503))
        client.get_summary = AsyncMock()

        ok = await log_entry(
            state, client, WorkLocation.DENMARK, work_date=date(2025, 6, 10)
        )

        assert ok is False
        assert state.error_action is ErrorAction.NOTIFICATION
        assert state.entries == {}
        client.get_summary.assert_not_awaited()

    async def test_delete_503_keeps_entry_and_notifies(self) -> None:
        state = _state()
        entry = _entry(10, WorkLocation.DENMARK)
        state.apply_entry(entry)
        client = MagicMock()
        client.delete_entry = AsyncMock(side_effect=_status_error(503))
        client.get_summary = AsyncMock()

        ok = await delete_entry(state, client, entry)

        assert ok is False
        assert state.error_action is ErrorAction.NOTIFICATION
        assert state.entries["2025-06-10"] is entry


# ---------------------------------------------------------------------------
# clear_error resets both message and action
# ---------------------------------------------------------------------------


class TestClearErrorResetsAction:
    async def test_success_clears_action_from_prior_error(self) -> None:
        state = _state()
        state.error_message = "stale"
        state.error_action = ErrorAction.NOTIFICATION
        client = MagicMock()
        client.post_entry = AsyncMock(return_value=_entry(10, WorkLocation.DENMARK))
        client.get_summary = AsyncMock(return_value=_summary())
        client.get_annual_summary = AsyncMock(return_value=_annual())

        await log_entry(
            state, client, WorkLocation.DENMARK, work_date=date(2025, 6, 10)
        )

        assert state.error_message is None
        assert state.error_action is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
