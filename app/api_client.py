"""Async HTTP client for the work-location-tracker backend.

Wraps ``httpx.AsyncClient`` with the resilience behaviour required by
Requirement 9:

* a 10-second request timeout,
* exponential back-off on ``503 Service Unavailable`` (1 s, 2 s, 4 s; three
  attempts total),
* automatic PATCH retry when a ``POST`` conflicts with an existing entry
  (``409 Conflict``),
* a typed :class:`APIError` raised for every unrecoverable failure so callers
  never see raw ``httpx`` exceptions.

The data models mirror the backend schemas in ``backend/schemas.py``.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from enum import Enum

import httpx
from pydantic import BaseModel, ConfigDict

# Request configuration -----------------------------------------------------

TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3
# Back-off waits applied *before* a retry attempt. The final failed attempt
# does not sleep, so only the first two values are ever awaited.
BACKOFF_SECONDS = (1, 2, 4)


# Data models (mirrors ``backend/schemas.py``) ------------------------------


class WorkLocation(str, Enum):
    HOME = "home"
    DENMARK = "denmark"
    VACATION = "vacation"
    SICK = "sick"


class WorkEntry(BaseModel):
    id: int
    work_date: date
    location: WorkLocation
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ComplianceSummary(BaseModel):
    year: int
    month: int
    total_days: int
    denmark_days: int
    vacation_days: int
    sick_days: int
    home_days: int
    compliance_pct: float
    is_compliant: bool


class AnnualSummary(BaseModel):
    year: int
    total_days: int
    denmark_days: int
    vacation_days: int
    sick_days: int
    home_days: int
    compliance_pct: float
    is_compliant: bool
    monthly_breakdown: list[ComplianceSummary]


# Errors --------------------------------------------------------------------


class APIError(Exception):
    """Raised for any unrecoverable failure talking to the backend.

    Deliberately *not* a subclass of any ``httpx`` exception so that callers
    can catch a single, transport-agnostic error type.
    """


class AuthError(APIError):
    """Raised when the backend rejects the shared secret with HTTP 401.

    A subclass of :class:`APIError` so existing ``except APIError`` handlers
    keep working, while callers that need to distinguish a rejected secret
    from other failures can catch :class:`AuthError` specifically and return
    the user to the login screen (Requirement 8.1).
    """


# Client --------------------------------------------------------------------


class APIClient:
    """Thin async wrapper around the backend REST API."""

    def __init__(self, base_url: str, secret: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = secret or None

    @property
    def base_url(self) -> str:
        """The normalised base URL this client issues requests against."""
        return self._base_url

    # -- shared secret -----------------------------------------------------

    def set_secret(self, secret: str | None) -> None:
        """Set (or clear) the shared secret sent as the ``X-API-Key`` header."""
        self._secret = secret or None

    @property
    def has_secret(self) -> bool:
        """True when a non-empty shared secret is configured."""
        return bool(self._secret)

    def _headers(self) -> dict[str, str]:
        """Return the auth headers to merge into every outgoing request."""
        return {"X-API-Key": self._secret} if self._secret else {}

    # -- public API --------------------------------------------------------

    async def get_entries(self, year: int, month: int) -> list[WorkEntry]:
        response = await self._request(
            "get",
            "/api/v1/entries",
            params={"year": year, "month": month},
        )
        payload = response.json() or []
        return [WorkEntry.model_validate(item) for item in payload]

    async def post_entry(self, date: str, location: WorkLocation) -> WorkEntry:
        location_value = _location_value(location)
        response = await self._request(
            "post",
            "/api/v1/entries",
            expected_status=201,
            raise_for_status=False,
            json={"work_date": date, "location": location_value},
        )

        if response.status_code == 409:
            # Entry already exists for this date — look it up and PATCH it.
            return await self._patch_existing(date, location)

        self._check_status(response)
        return WorkEntry.model_validate(response.json())

    async def patch_entry(self, entry_id: int, location: WorkLocation) -> WorkEntry:
        response = await self._request(
            "patch",
            f"/api/v1/entries/{entry_id}",
            json={"location": _location_value(location)},
        )
        return WorkEntry.model_validate(response.json())

    async def delete_entry(self, entry_id: int) -> None:
        await self._request("delete", f"/api/v1/entries/{entry_id}")

    async def get_summary(self, year: int, month: int) -> ComplianceSummary:
        response = await self._request(
            "get",
            "/api/v1/summary/monthly",
            params={"year": year, "month": month},
        )
        return ComplianceSummary.model_validate(response.json())

    async def get_annual_summary(self, year: int) -> AnnualSummary:
        response = await self._request(
            "get",
            "/api/v1/summary/annual",
            params={"year": year},
        )
        return AnnualSummary.model_validate(response.json())

    # -- internals ---------------------------------------------------------

    async def _patch_existing(
        self, work_date: str, location: WorkLocation
    ) -> WorkEntry:
        """Resolve the id for ``work_date`` and PATCH it with ``location``."""
        target = date.fromisoformat(work_date)
        entries = await self.get_entries(target.year, target.month)
        existing = next((e for e in entries if e.work_date == target), None)
        if existing is None:
            raise APIError(
                f"Conflict on {work_date} but no existing entry was found to update"
            )
        return await self.patch_entry(existing.id, location)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int | None = None,
        raise_for_status: bool = True,
        **kwargs: object,
    ) -> httpx.Response:
        """Issue a request with timeout, 503 back-off and typed errors.

        When ``raise_for_status`` is False the raw response is returned so the
        caller can branch on the status code (used by the 409 PATCH-retry
        flow). ``503`` is always retried internally regardless of that flag.
        """
        url = f"{self._base_url}{path}"
        last_error: Exception | None = None

        # Merge the shared-secret header into any caller-supplied headers.
        headers = {**self._headers(), **(kwargs.pop("headers", None) or {})}

        for attempt in range(MAX_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                    http_method = getattr(client, method)
                    response = await http_method(url, headers=headers, **kwargs)
            except httpx.TimeoutException as exc:
                raise APIError(f"Request to {url} timed out") from exc
            except httpx.HTTPError as exc:
                raise APIError(f"Request to {url} failed: {exc}") from exc

            # A rejected secret is terminal and takes precedence over the 503
            # back-off and the caller's 409 PATCH-retry: never retry a 401.
            if response.status_code == 401:
                raise AuthError(f"Shared secret rejected by {url}")

            if response.status_code == 503:
                last_error = APIError(f"Service unavailable for {url}")
                if attempt < MAX_ATTEMPTS - 1:
                    await asyncio.sleep(BACKOFF_SECONDS[attempt])
                    continue
                raise last_error

            if raise_for_status:
                self._check_status(response)
            return response

        # Loop only exits via return/raise above, but guard defensively.
        raise last_error or APIError(f"Request to {url} failed")

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise APIError(
                f"Request failed with status {response.status_code}"
            ) from exc


def _location_value(location: WorkLocation) -> str:
    """Return the wire value for a ``WorkLocation`` or a plain string."""
    return location.value if isinstance(location, WorkLocation) else str(location)
