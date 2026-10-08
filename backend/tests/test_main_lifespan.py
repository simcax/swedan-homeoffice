"""ASGI-lifespan tests for migration and configuration validation.

These tests drive the FastAPI application's *ASGI lifespan* — the real startup
path uvicorn runs — rather than calling ``backend.main._lifespan`` directly.
They enter ``app.router.lifespan_context(app)`` as an async context manager
(no ``asgi-lifespan`` dependency needed) so the production-critical startup
validation is exercised end-to-end through Starlette's lifespan machinery:

* on successful startup with migrations enabled, ``get_engine`` is called
  (validating ``DATABASE_URL``) and ``_run_migrations`` runs *before* requests
  are served, in that order (Requirements 11.2, 11.4);
* when ``get_engine`` raises :class:`DatabaseConfigError` (missing
  ``DATABASE_URL``), startup aborts — entering the lifespan context raises
  (Requirement 11.2);
* when ``_run_migrations`` raises, startup aborts (Requirement 11.5).

Collaborators are patched on the ``backend.main`` module namespace (where the
lifespan looks them up), so no real database or Alembic run occurs and the
tests stay isolated.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend import main as main_module
from backend.database import DatabaseConfigError
from backend.main import create_app


class TestLifespanContextSuccess:
    async def test_get_engine_then_migrations_run_before_serving(self) -> None:
        app = create_app(run_migrations=True)

        call_order: list[str] = []

        def record_engine() -> MagicMock:
            call_order.append("get_engine")
            return MagicMock()

        def record_migrate() -> None:
            call_order.append("_run_migrations")

        with (
            patch.object(main_module, "get_engine", side_effect=record_engine),
            patch.object(main_module, "_run_migrations", side_effect=record_migrate),
        ):
            async with app.router.lifespan_context(app):
                # Inside the context the app is "serving": config was validated
                # and migrations have already run.
                call_order.append("serving")

        assert call_order == ["get_engine", "_run_migrations", "serving"]


class TestLifespanContextConfigFailure:
    async def test_missing_database_url_aborts_startup(self) -> None:
        app = create_app(run_migrations=True)

        with (
            patch.object(
                main_module,
                "get_engine",
                side_effect=DatabaseConfigError("missing DATABASE_URL"),
            ),
            patch.object(main_module, "_run_migrations") as mock_migrate,
            pytest.raises(DatabaseConfigError),
        ):
            async with app.router.lifespan_context(app):
                pass

        # Startup aborted during config validation; migrations never ran.
        mock_migrate.assert_not_called()


class TestLifespanContextMigrationFailure:
    async def test_migration_failure_aborts_startup(self) -> None:
        app = create_app(run_migrations=True)

        with (
            patch.object(main_module, "get_engine", return_value=MagicMock()),
            patch.object(
                main_module,
                "_run_migrations",
                side_effect=RuntimeError("alembic upgrade failed"),
            ),
            pytest.raises(RuntimeError, match="alembic upgrade failed"),
        ):
            async with app.router.lifespan_context(app):
                pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
