"""Application configuration via ``pydantic-settings``.

The backend reads its configuration *exclusively* from the process environment
(Requirement 11.1): there is no ``.env`` fallback, so a missing required value
aborts startup instead of being silently defaulted (Requirement 11.2).

The only required setting is ``database_url`` (``DATABASE_URL``). It is exposed
*verbatim* — the ``postgresql://`` → ``postgresql+asyncpg://`` scheme rewrite
needed by the async driver happens in the engine factory
(:mod:`backend.database`), not here (Requirement 11.6), so the raw operator-
provided value stays observable at the configuration boundary.

This module is the single source of truth for settings; ``backend.database``
builds on top of it to construct the async engine.

Requirements: 11.1, 11.2, 11.6
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings.

    Attributes:
        database_url: PostgreSQL connection string, read from the
            ``DATABASE_URL`` environment variable. Required — constructing
            ``Settings`` without it raises a ``pydantic.ValidationError``, which
            the startup path turns into a fail-fast abort with a clear log
            message (Requirement 11.2).
    """

    database_url: str

    model_config = SettingsConfigDict(
        # Read from the process environment only (no ``.env`` fallback) so a
        # missing DATABASE_URL aborts startup rather than being defaulted
        # (Requirements 11.1, 11.2). Ignore unrelated environment variables
        # (e.g. GITHUB_TOKEN) so only declared settings are consumed.
        extra="ignore",
    )
