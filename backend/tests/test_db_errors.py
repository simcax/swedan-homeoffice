"""Integration tests for centralized database-connectivity error handling.

When PostgreSQL is unreachable, SQLAlchemy raises ``OperationalError`` (and
asyncpg connection failures surface as ``InterfaceError``). The application
factory (``backend.main.create_app``) registers an exception handler that
translates both into an HTTP ``503 Service Unavailable`` response rather than a
generic ``500`` (Requirements 9.5 and 10.5; design "Database Unavailable"
contract).

Testing approach
----------------
* The app is built via ``create_app()`` (app factory pattern), matching the
  other router integration tests.
* ``backend.database.get_session`` is overridden with a dependency that yields
  a session whose first query raises the connectivity error, so no real
  PostgreSQL is required.
* Requests go through ``httpx.AsyncClient`` over ``ASGITransport`` — no network,
  no running server.
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import InterfaceError, OperationalError

from backend.database import get_session
from backend.main import create_app

API = "/api/v1/entries"


class _FailingSession:
    """A stand-in ``AsyncSession`` whose ``execute`` raises a DB error.

    Only ``execute`` is needed: the entries list endpoint reaches the database
    through ``EntryRepository`` → ``session.execute`` first, which is where a
    connectivity failure would surface.
    """

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def execute(self, *args: object, **kwargs: object) -> object:
        raise self._error


def _client_raising(error: Exception) -> AsyncClient:
    """Build an ``AsyncClient`` whose DB session raises ``error`` on use."""
    app = create_app()

    async def _override_get_session() -> AsyncGenerator[_FailingSession, None]:
        yield _FailingSession(error)

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _operational_error() -> OperationalError:
    return OperationalError(
        "SELECT ...", params=None, orig=Exception("connection refused")
    )


def _interface_error() -> InterfaceError:
    return InterfaceError("SELECT ...", params=None, orig=Exception("connection reset"))


class TestDatabaseUnavailableReturns503:
    async def test_operational_error_returns_503(self) -> None:
        async with _client_raising(_operational_error()) as client:
            response = await client.get(API, params={"year": 2025, "month": 6})

        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}

    async def test_interface_error_returns_503(self) -> None:
        async with _client_raising(_interface_error()) as client:
            response = await client.get(API, params={"year": 2025, "month": 6})

        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
