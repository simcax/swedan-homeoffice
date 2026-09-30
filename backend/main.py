"""FastAPI application factory and ASGI entry point.

This module exposes two things the rest of the system depends on:

* :func:`create_app` — the application factory. Tests build fresh, isolated
  apps with it (overriding ``get_session`` to point at in-memory SQLite).
* ``app`` — a module-level :class:`FastAPI` instance created via
  :func:`create_app`. This is the ASGI target Clever Cloud starts with
  ``CC_PYTHON_UV_RUN_COMMAND`` (``uvicorn backend.main:app --host 0.0.0.0
  --port 8080``).

Import-time safety
------------------
``backend.database`` initializes its engine and session factory *lazily* (on
the first ``get_session`` call), so importing it — and therefore importing this
module and the routers — never requires ``DATABASE_URL`` and has no side
effects. The real environment is validated in the FastAPI *lifespan*, where a
missing ``DATABASE_URL`` aborts startup and Alembic migrations run before any
request is served — never at import, and never during tests.

See :func:`_lifespan` for the guarding rationale.

Requirements: 11.2, 11.3, 11.4, 11.5
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import get_engine
from backend.routers import entries, summary

logger = logging.getLogger(__name__)


def _run_migrations() -> None:
    """Bring the database schema to ``head`` via Alembic (Requirement 11.4).

    Runs the same ``alembic upgrade head`` that ``CC_POST_BUILD_HOOK`` would,
    but from inside the process so requests are only accepted once the schema
    is current. On failure the exception is logged and re-raised so startup
    aborts (Requirement 11.5).

    Note on logging: Alembic's ``env.py`` calls ``fileConfig`` with
    ``disable_existing_loggers=False`` (see ``backend/alembic/env.py``), so this
    module's logger survives the migration environment's logging setup and the
    failure message below is always emitted (Requirement 11.5).
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    ini_path = Path(__file__).resolve().parent / "alembic.ini"
    alembic_cfg = Config(str(ini_path))

    try:
        command.upgrade(alembic_cfg, "head")
    except Exception:
        logger.critical(
            "Alembic migration failed while upgrading to 'head'. The backend "
            "will not accept requests until the database schema is current. "
            "Inspect the traceback above to identify the failing revision.",
            exc_info=True,
        )
        raise


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate configuration and migrate the database before serving.

    On startup, when migrations are enabled (production / real runs):

    * Abort if ``DATABASE_URL`` is absent, logging a clear message
      (Requirement 11.2). This is checked by initializing the database engine,
      which raises :class:`DatabaseConfigError` when the variable is missing.
    * Run Alembic ``upgrade head`` before accepting requests
      (Requirement 11.4); abort on failure (Requirement 11.5).

    Migrations are gated behind ``app.state.run_migrations`` (set by
    :func:`create_app`). Tests construct the app with the flag off, so they
    never run real Alembic against the in-memory SQLite database they wire in
    via ``get_session`` overrides.
    """
    if getattr(app.state, "run_migrations", False):
        # Initializing the engine loads and validates DATABASE_URL from the
        # environment; a missing value raises DatabaseConfigError (already
        # logged clearly by backend.database). Requirement 11.2.
        get_engine()
        # ``_run_migrations`` is synchronous and Alembic's online env
        # (``backend/alembic/env.py``) drives the async engine via
        # ``asyncio.run(...)``. Calling it directly here would raise
        # ``RuntimeError: asyncio.run() cannot be called from a running event
        # loop`` because the lifespan already runs inside the ASGI loop. Run it
        # in a worker thread so Alembic gets its own event loop.
        await asyncio.to_thread(_run_migrations)

    yield


def create_app(run_migrations: bool | None = None) -> FastAPI:
    """Build and configure a :class:`FastAPI` application.

    Args:
        run_migrations: Whether the lifespan should validate ``DATABASE_URL``
            and run Alembic ``upgrade head`` on startup. When ``None`` (the
            default used by tests, which call ``create_app()`` with no args),
            the behaviour is taken from the ``RUN_MIGRATIONS`` environment
            variable — off unless explicitly enabled. The module-level
            production ``app`` passes ``run_migrations=True`` explicitly so the
            schema is migrated before serving regardless of that flag.

    Returns:
        A configured app with the entries and summary routers mounted and CORS
        enabled.
    """
    if run_migrations is None:
        run_migrations = os.environ.get("RUN_MIGRATIONS", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    app = FastAPI(
        title="Work Location Tracker API",
        version="0.1.0",
        lifespan=_lifespan,
    )
    app.state.run_migrations = run_migrations

    # CORS: the Flet web client may be served from a different origin than the
    # API (see the Clever Cloud deployment guide). Wide-open in v1; tighten to
    # specific origins before sharing the app.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(entries.router)
    app.include_router(summary.router)

    return app


# Module-level ASGI app. Started in production via CC_PYTHON_UV_RUN_COMMAND
# (uvicorn backend.main:app --host 0.0.0.0 --port 8080).
#
# Migrations are enabled explicitly rather than relying on the RUN_MIGRATIONS
# env flag: the documented Clever Cloud configuration does not set it, and this
# production instance must always validate DATABASE_URL and run
# ``alembic upgrade head`` before serving (Requirements 11.2, 11.4, 11.5).
# Tests build their own apps via ``create_app()`` (migrations off by default),
# so they are unaffected.
app = create_app(run_migrations=True)
