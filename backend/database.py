"""Async SQLAlchemy engine and session configuration.

Reads DATABASE_URL from the environment via pydantic-settings.
Rewrites postgresql:// → postgresql+asyncpg:// automatically.
Aborts at import time with a clear log message if DATABASE_URL is absent.
"""

import logging

from pydantic import field_validator
from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)


class _DatabaseSettings(BaseSettings):
    """Load and validate DATABASE_URL from the environment."""

    database_url: str

    @field_validator("database_url")
    @classmethod
    def rewrite_scheme(cls, v: str) -> str:
        """Rewrite postgresql:// to postgresql+asyncpg:// for the async driver."""
        return v.replace("postgresql://", "postgresql+asyncpg://", 1)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # Ignore unrelated keys in the local .env (e.g. GITHUB_TOKEN); only
        # DATABASE_URL is consumed. CI/production inject DATABASE_URL directly.
        "extra": "ignore",
    }


try:
    _settings = _DatabaseSettings()  # type: ignore[call-arg]
except Exception as exc:  # pydantic ValidationError when DATABASE_URL is missing
    logger.critical(
        "DATABASE_URL environment variable is not set. "
        "The backend cannot start without a database connection. "
        "Set DATABASE_URL to a valid PostgreSQL connection string and try again."
    )
    raise SystemExit(
        "Missing required environment variable DATABASE_URL. "
        "Set it to a PostgreSQL connection string, e.g. "
        "postgresql://user:password@host:5432/dbname"
    ) from exc

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_session() -> AsyncSession:  # type: ignore[return]
    """Yield an AsyncSession for use as a FastAPI dependency.

    Usage::

        @router.get("/")
        async def list_entries(db: AsyncSession = Depends(get_session)):
            ...
    """
    async with AsyncSessionLocal() as session:
        yield session
