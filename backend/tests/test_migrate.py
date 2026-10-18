"""Tests for the standalone migration entrypoint (:mod:`backend.migrate`).

Migrations run as a dedicated pre-start step rather than inside the FastAPI
lifespan so a single process applies ``alembic upgrade head`` once, before any
serving process starts — eliminating the multi-worker / ``--reload`` race.
These tests stub the two side-effecting collaborators (``get_engine`` for the
``DATABASE_URL`` validation and ``alembic.command.upgrade`` for the schema
upgrade) so no real database or Alembic run occurs, and assert:

* ``run_migrations`` validates ``DATABASE_URL`` *before* upgrading, in that
  order (Requirements 11.2, 11.4);
* a missing ``DATABASE_URL`` (``DatabaseConfigError`` from ``get_engine``)
  aborts before any upgrade is attempted (Requirement 11.2);
* an Alembic failure propagates out of ``run_migrations`` (Requirement 11.5);
* the ``main`` CLI wrapper returns ``0`` on success and ``1`` on failure, so a
  non-zero exit aborts a pre-start hook.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend import migrate as migrate_module
from backend.database import DatabaseConfigError


class TestRunMigrationsSuccess:
    def test_validates_config_then_upgrades_in_order(self) -> None:
        call_order: list[str] = []

        def record_engine() -> MagicMock:
            call_order.append("get_engine")
            return MagicMock()

        def record_upgrade(_cfg: object, revision: str) -> None:
            call_order.append(f"upgrade:{revision}")

        with (
            patch.object(migrate_module, "get_engine", side_effect=record_engine),
            patch("alembic.command.upgrade", side_effect=record_upgrade),
        ):
            migrate_module.run_migrations()

        assert call_order == ["get_engine", "upgrade:head"]


class TestRunMigrationsConfigFailure:
    def test_missing_database_url_aborts_before_upgrade(self) -> None:
        with (
            patch.object(
                migrate_module,
                "get_engine",
                side_effect=DatabaseConfigError("missing DATABASE_URL"),
            ),
            patch("alembic.command.upgrade") as mock_upgrade,
            pytest.raises(DatabaseConfigError),
        ):
            migrate_module.run_migrations()

        mock_upgrade.assert_not_called()


class TestRunMigrationsAlembicFailure:
    def test_alembic_failure_propagates(self) -> None:
        with (
            patch.object(migrate_module, "get_engine", return_value=MagicMock()),
            patch(
                "alembic.command.upgrade",
                side_effect=RuntimeError("alembic upgrade failed"),
            ),
            pytest.raises(RuntimeError, match="alembic upgrade failed"),
        ):
            migrate_module.run_migrations()


class TestMainCli:
    def test_returns_zero_on_success(self) -> None:
        with patch.object(migrate_module, "run_migrations") as mock_run:
            assert migrate_module.main() == 0
        mock_run.assert_called_once()

    def test_returns_one_on_failure(self) -> None:
        with patch.object(
            migrate_module,
            "run_migrations",
            side_effect=RuntimeError("boom"),
        ):
            assert migrate_module.main() == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
