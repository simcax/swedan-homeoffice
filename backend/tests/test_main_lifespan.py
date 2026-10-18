"""ASGI-lifespan tests for startup configuration validation.

These tests drive the FastAPI application's *ASGI lifespan* — the real startup
path uvicorn runs — rather than calling ``backend.main._lifespan`` directly.
They enter ``app.router.lifespan_context(app)`` as an async context manager
(no ``asgi-lifespan`` dependency needed) so the production-critical startup
validation is exercised end-to-end through Starlette's lifespan machinery.

Migrations no longer run in the lifespan — ``alembic upgrade head`` is a
dedicated pre-start step (:mod:`backend.migrate`) so it cannot race across
multiple uvicorn workers / the ``--reload`` reloader. The lifespan keeps only
the fail-fast ``DATABASE_URL`` validation, so these tests assert:

* on successful startup with validation enabled, ``get_engine`` is called
  (validating ``DATABASE_URL``) before requests are served (Requirement 11.2);
* when ``get_engine`` raises :class:`DatabaseConfigError` (missing
  ``DATABASE_URL``), startup aborts — entering the lifespan context raises
  (Requirement 11.2).

``get_engine`` is patched on the ``backend.main`` module namespace (where the
lifespan looks it up), so no real database connection occurs and the tests stay
isolated.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend import main as main_module
from backend.database import DatabaseConfigError
from backend.main import create_app


class TestLifespanContextSuccess:
    async def test_validates_config_before_serving(self) -> None:
        app = create_app(validate_config=True)

        call_order: list[str] = []

        def record_engine() -> MagicMock:
            call_order.append("get_engine")
            return MagicMock()

        with patch.object(main_module, "get_engine", side_effect=record_engine):
            async with app.router.lifespan_context(app):
                # Inside the context the app is "serving": config was validated.
                call_order.append("serving")

        assert call_order == ["get_engine", "serving"]


class TestLifespanContextConfigFailure:
    async def test_missing_database_url_aborts_startup(self) -> None:
        app = create_app(validate_config=True)

        with (
            patch.object(
                main_module,
                "get_engine",
                side_effect=DatabaseConfigError("missing DATABASE_URL"),
            ),
            pytest.raises(DatabaseConfigError),
        ):
            async with app.router.lifespan_context(app):
                pass


class TestLifespanContextValidationDisabled:
    async def test_validation_disabled_skips_engine(self) -> None:
        app = create_app(validate_config=False)

        with patch.object(main_module, "get_engine") as mock_engine:
            async with app.router.lifespan_context(app):
                pass

        mock_engine.assert_not_called()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
