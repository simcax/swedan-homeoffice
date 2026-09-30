"""FastAPI application factory and lifespan.

``create_app()`` builds the application WITHOUT touching ``DATABASE_URL`` or
running migrations — that side-effect-free construction is what the integration
tests rely on (they build the app, then override the ``get_session`` dependency
to talk to an in-memory SQLite database).

The database check and Alembic ``upgrade head`` run inside the app *lifespan*,
so they only execute when the app actually starts serving requests (e.g. under
uvicorn in production / on Clever Cloud), not when ``create_app()`` is called in
a test.

A module-level ``app = create_app()`` is also exposed so the Clever Cloud run
command ``.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8080`` works.

Requirements: 11.2, 11.3, 11.4, 11.5
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import entries, summary

logger = logging.getLogger(__name__)


def _run_migrations() -> None:
    """Run Alembic ``upgrade head`` against the configured database.

    Executed during application startup (lifespan), never at import time.
    """
    from alembic import command
    from alembic.config import Config

    ini_path = os.path.join(os.path.dirname(__file__), "alembic.ini")
    alembic_cfg = Config(ini_path)
    logger.info("Running Alembic migrations (upgrade head)...")
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic migrations complete.")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Verify the database is configured and migrate before serving.

    The ``DATABASE_URL`` requirement is enforced here — not at import time — so
    that ``create_app()`` remains side-effect free for tests.
    """
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "The backend cannot start without a database connection. "
            "Set DATABASE_URL to a valid PostgreSQL connection string."
        )
    _run_migrations()
    yield


def create_app() -> FastAPI:
    """Build and return the FastAPI application.

    Construction is side-effect free: no database connection is opened and no
    migration runs until the app's lifespan starts (i.e. when it actually
    serves requests).
    """
    app = FastAPI(title="Work Location Tracker", lifespan=lifespan)

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


app = create_app()
