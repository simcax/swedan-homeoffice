"""Standalone database-migration entrypoint (pre-start hook).

Running Alembic from inside the FastAPI lifespan races when more than one
process starts at once — multiple uvicorn workers, or ``--reload``'s reloader
plus worker, each call ``alembic upgrade head`` against the same database
concurrently. Alembic is not designed to be run that way and the result is
non-deterministic (duplicate-apply errors, partially applied revisions, or a
lock contention stall).

Migrations therefore run **once, before serving**, through this module rather
than in the lifespan:

* locally / in CI via ``uv run python -m backend.migrate`` (also what
  ``scripts/dev.sh`` does before starting uvicorn);
* on Clever Cloud via ``CC_POST_BUILD_HOOK`` (see the README deployment notes),
  which runs a single time after the build and before any instance serves.

The FastAPI lifespan still validates ``DATABASE_URL`` on startup (see
:func:`backend.main._lifespan`), so a mis-configured deployment still fails
fast — it just no longer tries to migrate from inside the request-serving
processes.

Requirements: 11.2, 11.4, 11.5
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from backend.database import get_engine

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """Bring the database schema to ``head`` via Alembic (Requirement 11.4).

    Validates ``DATABASE_URL`` first (by initializing the database engine, which
    raises :class:`~backend.database.DatabaseConfigError` when the variable is
    missing — Requirement 11.2), then runs the same ``alembic upgrade head``
    that ``CC_POST_BUILD_HOOK`` would. On failure the exception is logged and
    re-raised so the pre-start step aborts and the deployment never serves on an
    out-of-date schema (Requirement 11.5).

    Unlike the previous in-lifespan version, this runs in its own process with
    its own event loop, so Alembic's online ``env.py`` (which calls
    ``asyncio.run(...)``) needs no worker-thread hop.

    Note on logging: Alembic's ``env.py`` calls ``fileConfig`` with
    ``disable_existing_loggers=False`` (see ``backend/alembic/env.py``), so this
    module's logger survives the migration environment's logging setup and the
    failure message below is always emitted (Requirement 11.5).
    """
    from alembic import command
    from alembic.config import Config

    # Validate DATABASE_URL up front: a missing value raises DatabaseConfigError
    # (already logged clearly by backend.database). Requirement 11.2.
    get_engine()

    ini_path = Path(__file__).resolve().parent / "alembic.ini"
    alembic_cfg = Config(str(ini_path))

    try:
        command.upgrade(alembic_cfg, "head")
    except Exception:
        logger.critical(
            "Alembic migration failed while upgrading to 'head'. The backend "
            "must not be served until the database schema is current. Inspect "
            "the traceback above to identify the failing revision.",
            exc_info=True,
        )
        raise


def main() -> int:
    """CLI entry point: run migrations, returning a process exit code.

    Returns ``0`` on success. On failure the error is already logged by
    :func:`run_migrations`; this returns ``1`` so a non-zero exit aborts a
    pre-start hook (``CC_POST_BUILD_HOOK`` / ``scripts/dev.sh``).
    """
    logging.basicConfig(level=logging.INFO)
    try:
        run_migrations()
    except Exception:  # noqa: BLE001 — CLI boundary: any failure maps to exit 1
        logger.critical("Database migration failed; aborting pre-start.")
        return 1
    logger.info("Database schema is up to date.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
