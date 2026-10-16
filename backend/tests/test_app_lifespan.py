"""Tests for the FastAPI application lifespan (``backend.main._lifespan``).

The HTTPX router integration tests drive requests through ``ASGITransport``
*without* running the ASGI lifespan, so the production-critical startup path —
``DATABASE_URL`` validation and ``alembic upgrade head`` before serving — would
otherwise be untested. These tests exercise the lifespan directly, stubbing the
two side-effecting collaborators (``get_engine`` and ``_run_migrations``) so no
real database or Alembic run is needed, and assert:

* migrations-disabled startup touches neither collaborator;
* migrations-enabled startup validates config then migrates, in that order;
* a configuration failure (``DatabaseConfigError`` from ``get_engine``) and a
  migration failure (any exception from ``_run_migrations``) both propagate out
  of the lifespan, aborting startup (Requirements 11.2, 11.4, 11.5);
* the synchronous Alembic migration runs in a worker thread, not the ASGI
  event-loop thread (guards the ``asyncio.run()``-in-a-running-loop fix).

Collaborators are patched on the ``backend.main`` module namespace (where the
lifespan looks them up), so the real functions are never invoked.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from backend import main as main_module
from backend.database import DatabaseConfigError
from backend.main import create_app


def _app_with_migrations(enabled: bool):
    """Return an app whose lifespan will (or won't) run migrations."""
    return create_app(run_migrations=enabled)


class TestLifespanMigrationsDisabled:
    async def test_startup_skips_engine_and_migrations(self) -> None:
        app = _app_with_migrations(False)

        with (
            patch.object(main_module, "get_engine") as mock_engine,
            patch.object(main_module, "_run_migrations") as mock_migrate,
        ):
            async with main_module._lifespan(app):
                pass

        mock_engine.assert_not_called()
        mock_migrate.assert_not_called()


class TestLifespanMigrationsEnabledSuccess:
    async def test_validates_config_then_migrates_in_order(self) -> None:
        app = _app_with_migrations(True)

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
            async with main_module._lifespan(app):
                # Reaching here means startup completed and the app is serving.
                call_order.append("serving")

        assert call_order == ["get_engine", "_run_migrations", "serving"]

    async def test_migration_runs_in_worker_thread_not_event_loop(self) -> None:
        """Alembic's env.py calls ``asyncio.run``; it must not run on the loop."""
        app = _app_with_migrations(True)
        main_thread = threading.current_thread()
        migration_thread: list[threading.Thread] = []

        def capture_thread() -> None:
            migration_thread.append(threading.current_thread())

        with (
            patch.object(main_module, "get_engine", return_value=MagicMock()),
            patch.object(main_module, "_run_migrations", side_effect=capture_thread),
        ):
            async with main_module._lifespan(app):
                pass

        assert migration_thread, "_run_migrations was never called"
        # asyncio.to_thread offloads to a worker thread, so Alembic's internal
        # asyncio.run() gets a fresh loop instead of clashing with this one.
        assert migration_thread[0] is not main_thread


class TestLifespanConfigFailure:
    async def test_database_config_error_propagates(self) -> None:
        app = _app_with_migrations(True)

        with (
            patch.object(
                main_module,
                "get_engine",
                side_effect=DatabaseConfigError("missing DATABASE_URL"),
            ),
            patch.object(main_module, "_run_migrations") as mock_migrate,
            pytest.raises(DatabaseConfigError),
        ):
            async with main_module._lifespan(app):
                pass

        # Config validation failed, so migrations must not have been attempted.
        mock_migrate.assert_not_called()


class TestLifespanMigrationFailure:
    async def test_migration_error_propagates(self) -> None:
        app = _app_with_migrations(True)

        with (
            patch.object(main_module, "get_engine", return_value=MagicMock()),
            patch.object(
                main_module,
                "_run_migrations",
                side_effect=RuntimeError("alembic upgrade failed"),
            ),
            pytest.raises(RuntimeError, match="alembic upgrade failed"),
        ):
            async with main_module._lifespan(app):
                pass


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
