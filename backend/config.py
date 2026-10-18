"""Application configuration via ``pydantic-settings``.

The backend reads its configuration *exclusively* from the process environment
(Requirement 11.1): there is no ``.env`` fallback, so a missing required value
aborts startup instead of being silently defaulted (Requirement 11.2).

Connection string sources
--------------------------

The effective PostgreSQL connection string is resolved from two possible
sources, in order:

1. ``DATABASE_URL`` — an explicit, operator-provided connection string. Used
   for local development (``postgresql://wlt:wlt@127.0.0.1:5432/wlt``) and CI.
2. The ``POSTGRESQL_ADDON_*`` variables injected automatically by a linked
   Clever Cloud PostgreSQL add-on. On Clever Cloud these are populated natively
   at **run time** — ``POSTGRESQL_ADDON_URI`` is a ready-made
   ``postgresql://user:password@host:port/db`` string, with the individual
   ``POSTGRESQL_ADDON_HOST`` / ``_PORT`` / ``_USER`` / ``_PASSWORD`` / ``_DB``
   parts also available.

Reading the add-on variables directly (rather than relying on a manual
``DATABASE_URL="${POSTGRESQL_ADDON_URI}"`` indirection) avoids a fragile
expansion that resolves to an empty string whenever the add-on variables are
not yet present — which is exactly what happens during Clever Cloud's build
phase, where the add-on connection details are not injected.

The chosen value is exposed *verbatim* via :attr:`Settings.effective_database_url`
— the ``postgresql://`` → ``postgresql+asyncpg://`` scheme rewrite needed by the
async driver happens in the engine factory (:mod:`backend.database`), not here
(Requirement 11.6), so the raw value stays observable at the configuration
boundary.

This module is the single source of truth for settings; ``backend.database``
builds on top of it to construct the async engine.

Requirements: 11.1, 11.2, 11.6
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfigurationError(ValueError):
    """Raised when no usable database connection string can be resolved.

    Carries a clear message naming the environment variables that would satisfy
    the requirement, so startup validation and logs point operators at the fix.
    """


class SharedSecretConfigurationError(ValueError):
    """Raised when the required shared secret is missing or blank.

    Carries a clear message naming the ``APP_SHARED_SECRET`` environment
    variable so startup validation and logs point operators at the fix
    (Requirement 7.1, 7.4).
    """


class Settings(BaseSettings):
    """Environment-backed application settings.

    The database connection string is resolved from ``DATABASE_URL`` when set,
    otherwise from the ``POSTGRESQL_ADDON_*`` variables injected by a linked
    Clever Cloud PostgreSQL add-on. Read :attr:`effective_database_url` to get
    the resolved value; it raises :class:`DatabaseConfigurationError` when
    neither source yields a usable connection string (Requirement 11.2).

    Attributes:
        database_url: Explicit PostgreSQL connection string from the
            ``DATABASE_URL`` environment variable. Optional — when it is unset
            or blank, the ``POSTGRESQL_ADDON_*`` variables are used instead.
        postgresql_addon_uri: Ready-made connection string injected by a Clever
            Cloud PostgreSQL add-on (``POSTGRESQL_ADDON_URI``).
        postgresql_addon_host: Database host (``POSTGRESQL_ADDON_HOST``).
        postgresql_addon_port: Database port (``POSTGRESQL_ADDON_PORT``).
        postgresql_addon_user: Database user (``POSTGRESQL_ADDON_USER``).
        postgresql_addon_password: Database password
            (``POSTGRESQL_ADDON_PASSWORD``).
        postgresql_addon_db: Database name (``POSTGRESQL_ADDON_DB``).
        app_shared_secret: Expected value of the shared secret the Flet app
            sends in the ``X-API-Key`` header, read from the
            ``APP_SHARED_SECRET`` environment variable. Optional at the field
            level so configuration can be inspected without raising; read
            :attr:`required_shared_secret` to get a validated non-blank value
            (Requirement 7.1).
    """

    database_url: str | None = None

    # Shared secret the Flet app sends in the ``X-API-Key`` header. Read from
    # the ``APP_SHARED_SECRET`` environment variable (Requirement 7.1).
    app_shared_secret: str | None = None

    # Clever Cloud PostgreSQL add-on variables (injected at run time). The
    # field names map case-insensitively to the uppercase env var names.
    postgresql_addon_uri: str | None = None
    postgresql_addon_host: str | None = None
    postgresql_addon_port: str | None = None
    postgresql_addon_user: str | None = None
    postgresql_addon_password: str | None = None
    postgresql_addon_db: str | None = None

    model_config = SettingsConfigDict(
        # Read from the process environment only (no ``.env`` fallback) so a
        # missing configuration aborts startup rather than being defaulted
        # (Requirements 11.1, 11.2). Ignore unrelated environment variables
        # (e.g. GITHUB_TOKEN) so only declared settings are consumed.
        extra="ignore",
    )

    @property
    def effective_database_url(self) -> str:
        """Return the resolved PostgreSQL connection string (verbatim scheme).

        Resolution order:

        1. ``DATABASE_URL`` when set and non-blank.
        2. ``POSTGRESQL_ADDON_URI`` when set and non-blank.
        3. A string assembled from the individual ``POSTGRESQL_ADDON_HOST`` /
           ``_PORT`` / ``_USER`` / ``_PASSWORD`` / ``_DB`` parts, when all the
           required parts are present.

        The returned value keeps its original ``postgresql://`` scheme; the
        asyncpg rewrite happens in the engine factory (Requirement 11.6).

        Raises:
            DatabaseConfigurationError: When no source yields a usable
                connection string (Requirement 11.2).
        """
        explicit = (self.database_url or "").strip()
        if explicit:
            return explicit

        addon_uri = (self.postgresql_addon_uri or "").strip()
        if addon_uri:
            return addon_uri

        assembled = self._assemble_addon_url()
        if assembled:
            return assembled

        raise DatabaseConfigurationError(
            "No database configuration found. Set DATABASE_URL to a PostgreSQL "
            "connection string, e.g. postgresql://user:password@host:5432/dbname, "
            "or link a Clever Cloud PostgreSQL add-on so the POSTGRESQL_ADDON_* "
            "variables are injected."
        )

    @property
    def required_shared_secret(self) -> str:
        """Return the configured shared secret, or raise when it is missing.

        The value comes from the ``APP_SHARED_SECRET`` environment variable
        (via :attr:`app_shared_secret`). Surrounding whitespace is stripped and
        a blank value is treated as absent.

        Raises:
            SharedSecretConfigurationError: When ``APP_SHARED_SECRET`` is unset
                or blank (Requirement 7.1, 7.4).
        """
        value = (self.app_shared_secret or "").strip()
        if not value:
            raise SharedSecretConfigurationError(
                "APP_SHARED_SECRET is not set. Set it to the shared secret the "
                "Flet app sends in the X-API-Key header."
            )
        return value

    def _assemble_addon_url(self) -> str | None:
        """Build a ``postgresql://`` URL from the discrete add-on parts.

        Returns ``None`` unless host, user, password and database name are all
        present. The port falls back to PostgreSQL's default (5432) when the
        add-on does not provide one.
        """
        host = (self.postgresql_addon_host or "").strip()
        user = (self.postgresql_addon_user or "").strip()
        password = (self.postgresql_addon_password or "").strip()
        db = (self.postgresql_addon_db or "").strip()
        port = (self.postgresql_addon_port or "").strip() or "5432"

        if not (host and user and password and db):
            return None

        return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@lru_cache
def get_settings() -> Settings:
    """Return the application settings for dependency injection.

    Cached so a single :class:`Settings` instance is shared across requests.
    FastAPI dependencies (e.g. the ``X-API-Key`` verification dependency) and
    tests can override this provider to supply known configuration without
    touching the process environment.
    """
    return Settings()  # type: ignore[call-arg]
