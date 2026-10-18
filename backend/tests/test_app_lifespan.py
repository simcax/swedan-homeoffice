"""Tests for the FastAPI application lifespan (``backend.main._lifespan``).

The HTTPX router integration tests drive requests through ``ASGITransport``
*without* running the ASGI lifespan, so the production-critical startup path —
``DATABASE_URL`` validation before serving — would otherwise be untested. These
tests exercise the lifespan directly, stubbing the side-effecting ``get_engine``
collaborator so no real database connection is needed, and assert:

* validation-disabled startup never touches ``get_engine``;
* validation-enabled startup validates config (``get_engine``) before serving
  (Requirement 11.2);
* a configuration failure (``DatabaseConfigError`` from ``get_engine``)
  propagates out of the lifespan, aborting startup (Requirement 11.2).

Migrations are no longer run in the lifespan: ``alembic upgrade head`` runs as a
dedicated pre-start step (:mod:`backend.migrate`) so it cannot race across
serving processes. Those migration semantics are covered by
``test_migrate.py``.

``get_engine`` is patched on the ``backend.main`` module namespace (where the
lifespan looks it up), so the real function is never invoked.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend import main as main_module
from backend.config import get_settings
from backend.database import DatabaseConfigError
from backend.main import create_app

from .conftest import TEST_SHARED_SECRET


def _app_with_validation(enabled: bool):
    """Return an app whose lifespan will (or won't) validate ``DATABASE_URL``."""
    return create_app(validate_config=enabled)


class TestLifespanValidationDisabled:
    async def test_startup_skips_engine(self) -> None:
        app = _app_with_validation(False)

        with patch.object(main_module, "get_engine") as mock_engine:
            async with main_module._lifespan(app):
                pass

        mock_engine.assert_not_called()


class TestLifespanValidationEnabledSuccess:
    async def test_validates_config_before_serving(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _app_with_validation(True)

        # Startup also validates APP_SHARED_SECRET (Requirement 7.4); supply it
        # via the environment and clear the cached settings so the lifespan
        # reads the known value instead of aborting.
        monkeypatch.setenv("APP_SHARED_SECRET", TEST_SHARED_SECRET)
        get_settings.cache_clear()

        call_order: list[str] = []

        def record_engine() -> MagicMock:
            call_order.append("get_engine")
            return MagicMock()

        with patch.object(main_module, "get_engine", side_effect=record_engine):
            async with main_module._lifespan(app):
                # Reaching here means startup completed and the app is serving.
                call_order.append("serving")

        get_settings.cache_clear()
        assert call_order == ["get_engine", "serving"]


class TestLifespanConfigFailure:
    async def test_database_config_error_propagates(self) -> None:
        app = _app_with_validation(True)

        with (
            patch.object(
                main_module,
                "get_engine",
                side_effect=DatabaseConfigError("missing DATABASE_URL"),
            ),
            pytest.raises(DatabaseConfigError),
        ):
            async with main_module._lifespan(app):
                pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
