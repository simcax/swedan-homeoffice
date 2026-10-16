"""Failing tests for the Flet ``APIClient`` (TDD red phase — task 9.1).

These tests describe the behaviour of the yet-to-be-implemented
``app.api_client`` module. They are expected to FAIL at import time
(``app.api_client`` does not exist yet) until task 9.2 implements it.

The client interface under test (from the design document)::

    class APIClient:
        def __init__(self, base_url: str) -> None: ...
        async def get_entries(self, year: int, month: int) -> list[WorkEntry]: ...
        async def post_entry(self, date: str, location: WorkLocation) -> WorkEntry: ...
        async def patch_entry(self, entry_id: int, location: WorkLocation) -> WorkEntry: ...
        async def delete_entry(self, entry_id: int) -> None: ...
        async def get_summary(self, year: int, month: int) -> ComplianceSummary: ...
        async def get_annual_summary(self, year: int) -> AnnualSummary: ...

Endpoints::

    GET    /api/v1/entries?year=&month=
    POST   /api/v1/entries
    PATCH  /api/v1/entries/{entry_id}
    DELETE /api/v1/entries/{entry_id}
    GET    /api/v1/summary/monthly?year=&month=
    GET    /api/v1/summary/annual?year=

Error-handling contract (Requirement 9)::

    httpx.TimeoutException  -> re-raised as a typed APIError
    HTTP 503                -> exponential back-off retry (1 s, 2 s, 4 s; 3 attempts)
    HTTP 409 on POST        -> automatic PATCH retry against the existing entry

The Flet runtime is never started; ``httpx.AsyncClient`` is fully mocked.

Requirements: 9.3, 9.4, 9.6
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest

from app.api_client import (
    AnnualSummary,
    APIClient,
    APIError,
    ComplianceSummary,
    WorkEntry,
    WorkLocation,
)

BASE_URL = "http://test"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _entry_json(
    entry_id: int = 1,
    work_date: str = "2025-06-10",
    location: str = "denmark",
) -> dict:
    """Build a JSON payload matching ``WorkEntryResponse`` from the backend."""
    return {
        "id": entry_id,
        "work_date": work_date,
        "location": location,
        "created_at": "2025-06-10T08:00:00+00:00",
        "updated_at": "2025-06-10T08:00:00+00:00",
    }


def _summary_json(year: int = 2025, month: int = 6) -> dict:
    """Build a JSON payload matching ``ComplianceSummary`` from the backend."""
    return {
        "year": year,
        "month": month,
        "total_days": 20,
        "denmark_days": 12,
        "vacation_days": 3,
        "sick_days": 1,
        "home_days": 4,
        "compliance_pct": 80.0,
        "is_compliant": True,
    }


def _annual_json(year: int = 2025) -> dict:
    """Build a JSON payload matching ``AnnualSummary`` from the backend."""
    return {
        "year": year,
        "total_days": 20,
        "denmark_days": 12,
        "vacation_days": 3,
        "sick_days": 1,
        "home_days": 4,
        "compliance_pct": 80.0,
        "is_compliant": True,
        "monthly_breakdown": [_summary_json(year=year, month=m) for m in range(1, 13)],
    }


def _response(status_code: int, json_body: object | None = None) -> MagicMock:
    """Build a mock ``httpx.Response``.

    ``raise_for_status`` raises ``HTTPStatusError`` for 4xx/5xx so the client
    can branch on ``response.status_code`` the way real httpx does.
    """
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body

    def _raise_for_status() -> None:
        if status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {status_code}",
                request=MagicMock(spec=httpx.Request),
                response=resp,
            )

    resp.raise_for_status.side_effect = _raise_for_status
    return resp


# ---------------------------------------------------------------------------
# get_entries
# ---------------------------------------------------------------------------


class TestGetEntries:
    async def test_returns_list_of_work_entry_objects(self) -> None:
        payload = [
            _entry_json(entry_id=1, work_date="2025-06-02", location="denmark"),
            _entry_json(entry_id=2, work_date="2025-06-03", location="home"),
        ]
        mock_get = AsyncMock(return_value=_response(200, payload))

        with patch("httpx.AsyncClient.get", mock_get):
            client = APIClient(base_url=BASE_URL)
            entries = await client.get_entries(2025, 6)

        assert isinstance(entries, list)
        assert len(entries) == 2
        assert all(isinstance(e, WorkEntry) for e in entries)
        assert entries[0].location == WorkLocation.DENMARK
        assert entries[1].location == WorkLocation.HOME

    async def test_calls_get_with_year_and_month_params(self) -> None:
        mock_get = AsyncMock(return_value=_response(200, []))

        with patch("httpx.AsyncClient.get", mock_get):
            client = APIClient(base_url=BASE_URL)
            await client.get_entries(2025, 6)

        assert mock_get.await_count == 1
        _, kwargs = mock_get.await_args
        assert kwargs.get("params") == {"year": 2025, "month": 6}


# ---------------------------------------------------------------------------
# post_entry
# ---------------------------------------------------------------------------


class TestPostEntry:
    async def test_returns_work_entry(self) -> None:
        mock_post = AsyncMock(
            return_value=_response(201, _entry_json(location="denmark"))
        )

        with patch("httpx.AsyncClient.post", mock_post):
            client = APIClient(base_url=BASE_URL)
            entry = await client.post_entry("2025-06-10", WorkLocation.DENMARK)

        assert isinstance(entry, WorkEntry)
        assert entry.location == WorkLocation.DENMARK

    async def test_posts_correct_payload(self) -> None:
        mock_post = AsyncMock(
            return_value=_response(201, _entry_json(location="vacation"))
        )

        with patch("httpx.AsyncClient.post", mock_post):
            client = APIClient(base_url=BASE_URL)
            await client.post_entry("2025-06-10", WorkLocation.VACATION)

        assert mock_post.await_count == 1
        args, kwargs = mock_post.await_args
        # Endpoint is POST /api/v1/entries.
        url = args[0] if args else kwargs.get("url")
        assert url is not None
        assert str(url).endswith("/api/v1/entries")
        assert kwargs.get("json") == {
            "work_date": "2025-06-10",
            "location": "vacation",
        }


# ---------------------------------------------------------------------------
# patch_entry
# ---------------------------------------------------------------------------


class TestPatchEntry:
    async def test_returns_updated_work_entry(self) -> None:
        mock_patch = AsyncMock(
            return_value=_response(200, _entry_json(entry_id=7, location="home"))
        )

        with patch("httpx.AsyncClient.patch", mock_patch):
            client = APIClient(base_url=BASE_URL)
            entry = await client.patch_entry(7, WorkLocation.HOME)

        assert isinstance(entry, WorkEntry)
        assert entry.id == 7
        assert entry.location == WorkLocation.HOME

    async def test_calls_patch_with_entry_id_and_payload(self) -> None:
        mock_patch = AsyncMock(
            return_value=_response(200, _entry_json(entry_id=7, location="sick"))
        )

        with patch("httpx.AsyncClient.patch", mock_patch):
            client = APIClient(base_url=BASE_URL)
            await client.patch_entry(7, WorkLocation.SICK)

        assert mock_patch.await_count == 1
        args, kwargs = mock_patch.await_args
        url = args[0] if args else kwargs.get("url")
        assert str(url).endswith("/api/v1/entries/7")
        assert kwargs.get("json") == {"location": "sick"}


# ---------------------------------------------------------------------------
# delete_entry
# ---------------------------------------------------------------------------


class TestDeleteEntry:
    async def test_returns_none_on_204(self) -> None:
        mock_delete = AsyncMock(return_value=_response(204, None))

        with patch("httpx.AsyncClient.delete", mock_delete):
            client = APIClient(base_url=BASE_URL)
            result = await client.delete_entry(3)

        assert result is None

    async def test_calls_delete_with_entry_id(self) -> None:
        mock_delete = AsyncMock(return_value=_response(204, None))

        with patch("httpx.AsyncClient.delete", mock_delete):
            client = APIClient(base_url=BASE_URL)
            await client.delete_entry(3)

        assert mock_delete.await_count == 1
        args, kwargs = mock_delete.await_args
        url = args[0] if args else kwargs.get("url")
        assert str(url).endswith("/api/v1/entries/3")


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------


class TestGetSummary:
    async def test_returns_compliance_summary(self) -> None:
        mock_get = AsyncMock(return_value=_response(200, _summary_json()))

        with patch("httpx.AsyncClient.get", mock_get):
            client = APIClient(base_url=BASE_URL)
            summary = await client.get_summary(2025, 6)

        assert isinstance(summary, ComplianceSummary)
        assert summary.total_days == 20
        assert summary.compliance_pct == 80.0
        assert summary.is_compliant is True

    async def test_calls_monthly_endpoint_with_params(self) -> None:
        mock_get = AsyncMock(return_value=_response(200, _summary_json()))

        with patch("httpx.AsyncClient.get", mock_get):
            client = APIClient(base_url=BASE_URL)
            await client.get_summary(2025, 6)

        args, kwargs = mock_get.await_args
        url = args[0] if args else kwargs.get("url")
        assert str(url).endswith("/api/v1/summary/monthly")
        assert kwargs.get("params") == {"year": 2025, "month": 6}


# ---------------------------------------------------------------------------
# get_annual_summary
# ---------------------------------------------------------------------------


class TestGetAnnualSummary:
    async def test_returns_annual_summary(self) -> None:
        mock_get = AsyncMock(return_value=_response(200, _annual_json()))

        with patch("httpx.AsyncClient.get", mock_get):
            client = APIClient(base_url=BASE_URL)
            summary = await client.get_annual_summary(2025)

        assert isinstance(summary, AnnualSummary)
        assert summary.year == 2025
        assert len(summary.monthly_breakdown) == 12

    async def test_calls_annual_endpoint_with_year_param(self) -> None:
        mock_get = AsyncMock(return_value=_response(200, _annual_json()))

        with patch("httpx.AsyncClient.get", mock_get):
            client = APIClient(base_url=BASE_URL)
            await client.get_annual_summary(2025)

        args, kwargs = mock_get.await_args
        url = args[0] if args else kwargs.get("url")
        assert str(url).endswith("/api/v1/summary/annual")
        assert kwargs.get("params") == {"year": 2025}


# ---------------------------------------------------------------------------
# Error handling: timeout -> APIError (Requirement 9.4)
# ---------------------------------------------------------------------------


class TestTimeoutHandling:
    async def test_timeout_is_reraised_as_api_error(self) -> None:
        mock_get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        with patch("httpx.AsyncClient.get", mock_get):
            client = APIClient(base_url=BASE_URL)
            with pytest.raises(APIError):
                await client.get_entries(2025, 6)

    async def test_api_error_is_not_a_timeout_exception(self) -> None:
        """The custom error type must shield callers from raw httpx errors."""
        assert not issubclass(APIError, httpx.TimeoutException)


# ---------------------------------------------------------------------------
# Error handling: 503 -> exponential back-off (Requirement 9.6)
# ---------------------------------------------------------------------------


class TestServiceUnavailableBackoff:
    async def test_retries_three_times_with_exponential_backoff(self) -> None:
        # Always 503: the client should exhaust 3 attempts then raise APIError.
        mock_get = AsyncMock(return_value=_response(503, None))
        mock_sleep = AsyncMock()

        with (
            patch("httpx.AsyncClient.get", mock_get),
            patch("asyncio.sleep", mock_sleep),
        ):
            client = APIClient(base_url=BASE_URL)
            with pytest.raises(APIError):
                await client.get_entries(2025, 6)

        # Three attempts total.
        assert mock_get.await_count == 3
        # Back-off waits of 1 s then 2 s then 4 s between attempts. The final
        # failed attempt does not sleep, so exactly two waits are observed.
        assert mock_sleep.await_args_list == [call(1), call(2)]

    async def test_succeeds_after_transient_503(self) -> None:
        # 503, 503, then a success on the third attempt.
        mock_get = AsyncMock(
            side_effect=[
                _response(503, None),
                _response(503, None),
                _response(200, [_entry_json()]),
            ]
        )
        mock_sleep = AsyncMock()

        with (
            patch("httpx.AsyncClient.get", mock_get),
            patch("asyncio.sleep", mock_sleep),
        ):
            client = APIClient(base_url=BASE_URL)
            entries = await client.get_entries(2025, 6)

        assert mock_get.await_count == 3
        assert len(entries) == 1
        assert mock_sleep.await_args_list == [call(1), call(2)]


# ---------------------------------------------------------------------------
# Error handling: 409 on POST -> automatic PATCH retry (Requirement 9.3)
# ---------------------------------------------------------------------------


class TestConflictPatchRetry:
    async def test_409_on_post_triggers_patch_retry(self) -> None:
        # POST returns 409 Conflict for an existing date; the client then
        # looks up the existing entry and retries as a PATCH.
        mock_post = AsyncMock(return_value=_response(409, {"detail": "exists"}))
        # The existing entry is fetched so the client knows which id to PATCH.
        mock_get = AsyncMock(
            return_value=_response(
                200, [_entry_json(entry_id=42, work_date="2025-06-10")]
            )
        )
        mock_patch = AsyncMock(
            return_value=_response(
                200, _entry_json(entry_id=42, work_date="2025-06-10", location="home")
            )
        )

        with (
            patch("httpx.AsyncClient.post", mock_post),
            patch("httpx.AsyncClient.get", mock_get),
            patch("httpx.AsyncClient.patch", mock_patch),
        ):
            client = APIClient(base_url=BASE_URL)
            entry = await client.post_entry("2025-06-10", WorkLocation.HOME)

        assert mock_post.await_count == 1
        assert mock_patch.await_count == 1
        assert isinstance(entry, WorkEntry)
        assert entry.id == 42
        assert entry.location == WorkLocation.HOME

    async def test_api_error_when_patch_retry_also_fails(self) -> None:
        mock_post = AsyncMock(return_value=_response(409, {"detail": "exists"}))
        mock_get = AsyncMock(
            return_value=_response(
                200, [_entry_json(entry_id=42, work_date="2025-06-10")]
            )
        )
        mock_patch = AsyncMock(return_value=_response(404, {"detail": "not found"}))

        with (
            patch("httpx.AsyncClient.post", mock_post),
            patch("httpx.AsyncClient.get", mock_get),
            patch("httpx.AsyncClient.patch", mock_patch),
        ):
            client = APIClient(base_url=BASE_URL)
            with pytest.raises(APIError):
                await client.post_entry("2025-06-10", WorkLocation.HOME)
