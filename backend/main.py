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
missing ``DATABASE_URL`` aborts startup — never at import, and never during
tests.

Migrations do **not** run here. ``alembic upgrade head`` is a pre-start step
(:mod:`backend.migrate`, invoked via ``CC_POST_BUILD_HOOK`` or
``scripts/dev.sh``) so it executes exactly once before serving, rather than
racing across multiple uvicorn workers / the ``--reload`` reloader. The
lifespan keeps only the fail-fast ``DATABASE_URL`` validation.

See :func:`_lifespan` for the guarding rationale.

Requirements: 11.2, 11.3, 11.4, 11.5
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE

from backend.database import DatabaseUnavailableError, get_engine
from backend.routers import entries, summary

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate database configuration before serving.

    On startup, when configuration validation is enabled (production / real
    runs), abort if ``DATABASE_URL`` is absent, logging a clear message
    (Requirement 11.2). This is checked by initializing the database engine,
    which raises :class:`~backend.database.DatabaseConfigError` when the
    variable is missing.

    Migrations are **not** run here. ``alembic upgrade head`` runs once as a
    dedicated pre-start step (:mod:`backend.migrate`) so it cannot race across
    multiple serving processes (Requirement 11.4). Validation is gated behind
    ``app.state.validate_config`` (set by :func:`create_app`); tests construct
    the app with the flag off, so they never touch the real environment and
    wire in in-memory SQLite via ``get_session`` overrides.
    """
    if getattr(app.state, "validate_config", False):
        # Initializing the engine loads and validates DATABASE_URL from the
        # environment; a missing value raises DatabaseConfigError (already
        # logged clearly by backend.database). Requirement 11.2.
        get_engine()

    yield


def create_app(validate_config: bool | None = None) -> FastAPI:
    """Build and configure a :class:`FastAPI` application.

    Args:
        validate_config: Whether the lifespan should validate ``DATABASE_URL``
            on startup. When ``None`` (the default used by tests, which call
            ``create_app()`` with no args), the behaviour is taken from the
            ``RUN_MIGRATIONS`` environment variable — off unless explicitly
            enabled. The module-level production ``app`` passes
            ``validate_config=True`` explicitly so ``DATABASE_URL`` is always
            validated before serving. Migrations themselves run separately via
            :mod:`backend.migrate` as a pre-start step.

    Returns:
        A configured app with the entries and summary routers mounted and CORS
        enabled.
    """
    if validate_config is None:
        validate_config = os.environ.get("RUN_MIGRATIONS", "").lower() in {
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
    app.state.validate_config = validate_config

    # CORS: the Flet web client may be served from a different origin than the
    # API (see the Clever Cloud deployment guide). Wide-open origins are safe in
    # v1 because this is a single-user API with no auth: there are no cookies or
    # Authorization headers to protect. ``allow_credentials`` is therefore False
    # — browsers reject the ``Access-Control-Allow-Origin: *`` wildcard when
    # credentials are enabled. If an auth mechanism (cookies/tokens) is added
    # later, credentials must be re-enabled together with an explicit origin
    # allowlist (``allow_origins=[...]``); the wildcard cannot be used with
    # credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(entries.router)
    app.include_router(summary.router)

    # Optionally serve the Flet web UI from this same instance so a single
    # Clever Cloud app (and one PostgreSQL add-on) hosts both the API and the
    # frontend — no second scaler to pay for. Enabled by setting SERVE_FRONTEND
    # to a truthy value (the production app sets it; tests leave it off so they
    # neither import Flet nor mount the UI). The API routers above are
    # registered first and live under ``/api/v1/...``; mounting the Flet app at
    # ``/`` is safe because explicit routes take precedence over a mount.
    if _serve_frontend_enabled():
        _mount_frontend(app)

    # Database connectivity failures must surface as HTTP 503, not 500
    # (Requirements 9.5 and 10.5; design "Database Unavailable" contract).
    # SQLAlchemy raises ``OperationalError`` when the server is unreachable, and
    # ``InterfaceError`` or raw network errors can surface for asyncpg connection
    # failures. Translate these database-specific errors into a 503 so clients can
    # distinguish an outage from a server bug.
    async def _database_unavailable_handler(
        request: Request,
        exc: DatabaseUnavailableError | OperationalError | InterfaceError,
    ) -> JSONResponse:
        logger.warning(
            "Database connectivity error handling %s %s: %s",
            request.method,
            request.url.path,
            exc.__class__.__name__,
        )
        return JSONResponse(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Database unavailable"},
        )

    app.add_exception_handler(DatabaseUnavailableError, _database_unavailable_handler)  # type: ignore[arg-type]
    app.add_exception_handler(OperationalError, _database_unavailable_handler)  # type: ignore[arg-type]
    app.add_exception_handler(InterfaceError, _database_unavailable_handler)  # type: ignore[arg-type]

    return app


def _serve_frontend_enabled() -> bool:
    """Return whether the Flet web UI should be mounted on this app.

    Controlled by the ``SERVE_FRONTEND`` environment variable so a single
    deployment can host both the API and the frontend. Off by default (tests
    and API-only deployments), so importing Flet is avoided unless requested.
    """
    return os.environ.get("SERVE_FRONTEND", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _mount_frontend(app: FastAPI) -> None:
    """Mount the Flet web UI at ``/`` using Flet's FastAPI integration.

    ``flet.fastapi.app(main)`` builds a FastAPI sub-app that serves the Flet
    web client (its Flutter assets ship with the ``flet`` package, so no
    Flutter SDK build step is needed) and the websocket/session endpoints the
    client talks to. Importing ``app.main`` here — rather than at module top
    level — keeps the heavy Flet import out of the API-only path and out of the
    test suite.

    The Flet app resolves its backend URL from ``API_BASE_URL`` (see
    ``app.main.resolve_base_url``); when co-hosted it should point at this same
    origin.
    """
    import flet.fastapi as flet_fastapi

    from app.main import main as flet_main

    app.mount("/", flet_fastapi.app(flet_main))


# Module-level ASGI app. Started in production via CC_PYTHON_UV_RUN_COMMAND
# (uvicorn backend.main:app --host 0.0.0.0 --port 8080).
#
# Config validation is enabled explicitly rather than relying on the
# RUN_MIGRATIONS env flag: the documented Clever Cloud configuration does not
# set it, and this production instance must always validate DATABASE_URL before
# serving (Requirement 11.2). Migrations run as a pre-start step via
# ``backend.migrate`` (CC_POST_BUILD_HOOK), not here, so they cannot race across
# serving processes (Requirements 11.4, 11.5). Tests build their own apps via
# ``create_app()`` (validation off by default), so they are unaffected.
app = create_app(validate_config=True)
