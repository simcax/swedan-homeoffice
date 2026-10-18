"""Tests for the pydantic-settings ``Settings`` class (``backend.config``).

The application resolves its database connection string *exclusively* from the
process environment (Requirement 11.1) and must fail fast when no usable source
is present (Requirement 11.2). The connection string comes from either an
explicit ``DATABASE_URL`` or the ``POSTGRESQL_ADDON_*`` variables injected by a
linked Clever Cloud PostgreSQL add-on. These tests pin that contract on the
canonical :class:`~backend.config.Settings` object:

* ``effective_database_url`` prefers ``DATABASE_URL`` when set;
* it falls back to ``POSTGRESQL_ADDON_URI`` and then to a URL assembled from the
  discrete ``POSTGRESQL_ADDON_*`` parts;
* it raises :class:`~backend.config.DatabaseConfigurationError` when no source
  yields a connection string;
* the chosen value is returned verbatim (scheme rewriting for asyncpg happens
  later, in the engine factory, Requirement 11.6);
* unrelated environment variables are ignored.

Environment variables are manipulated via ``monkeypatch`` so the real process
environment is restored after every test and nothing leaks between tests. The
add-on variables are cleared in every test so the local environment's own
``POSTGRESQL_ADDON_*`` values (if any) cannot influence the outcome.
"""

import pytest

from backend.config import DatabaseConfigurationError, Settings

ADDON_VARS = (
    "POSTGRESQL_ADDON_URI",
    "POSTGRESQL_ADDON_HOST",
    "POSTGRESQL_ADDON_PORT",
    "POSTGRESQL_ADDON_USER",
    "POSTGRESQL_ADDON_PASSWORD",
    "POSTGRESQL_ADDON_DB",
)


@pytest.fixture(autouse=True)
def _clear_db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear every database-related env var so each test starts from a clean slate."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name in ADDON_VARS:
        monkeypatch.delenv(name, raising=False)


class TestDatabaseUrlSource:
    def test_explicit_database_url_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host:5432/db")

        assert Settings().effective_database_url == "postgresql://user:pw@host:5432/db"

    def test_value_is_read_verbatim_without_scheme_rewrite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The asyncpg scheme rewrite (postgresql:// -> postgresql+asyncpg://)
        # belongs to the engine factory (Requirement 11.6), not Settings.
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")

        assert Settings().effective_database_url == "postgresql://u:p@h/db"

    def test_blank_database_url_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Clever Cloud's DATABASE_URL="${POSTGRESQL_ADDON_URI}" expands to an
        # empty string at build time; a blank value must not be used.
        monkeypatch.setenv("DATABASE_URL", "")
        monkeypatch.setenv(
            "POSTGRESQL_ADDON_URI", "postgresql://u:p@addon-host:5796/addon-db"
        )

        assert (
            Settings().effective_database_url
            == "postgresql://u:p@addon-host:5796/addon-db"
        )


class TestAddonFallback:
    def test_addon_uri_used_when_database_url_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "POSTGRESQL_ADDON_URI", "postgresql://u:p@addon-host:5796/addon-db"
        )

        assert (
            Settings().effective_database_url
            == "postgresql://u:p@addon-host:5796/addon-db"
        )

    def test_assembled_from_discrete_addon_parts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("POSTGRESQL_ADDON_HOST", "addon-host")
        monkeypatch.setenv("POSTGRESQL_ADDON_PORT", "5796")
        monkeypatch.setenv("POSTGRESQL_ADDON_USER", "addon_user")
        monkeypatch.setenv("POSTGRESQL_ADDON_PASSWORD", "secret")
        monkeypatch.setenv("POSTGRESQL_ADDON_DB", "addon_db")

        assert (
            Settings().effective_database_url
            == "postgresql://addon_user:secret@addon-host:5796/addon_db"
        )

    def test_assembled_url_defaults_port_when_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("POSTGRESQL_ADDON_HOST", "addon-host")
        monkeypatch.setenv("POSTGRESQL_ADDON_USER", "addon_user")
        monkeypatch.setenv("POSTGRESQL_ADDON_PASSWORD", "secret")
        monkeypatch.setenv("POSTGRESQL_ADDON_DB", "addon_db")

        assert (
            Settings().effective_database_url
            == "postgresql://addon_user:secret@addon-host:5432/addon_db"
        )

    def test_uri_preferred_over_discrete_parts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("POSTGRESQL_ADDON_URI", "postgresql://u:p@from-uri:5796/db")
        monkeypatch.setenv("POSTGRESQL_ADDON_HOST", "from-parts")
        monkeypatch.setenv("POSTGRESQL_ADDON_USER", "u")
        monkeypatch.setenv("POSTGRESQL_ADDON_PASSWORD", "p")
        monkeypatch.setenv("POSTGRESQL_ADDON_DB", "db")

        assert Settings().effective_database_url == "postgresql://u:p@from-uri:5796/db"


class TestNoConfiguration:
    def test_raises_when_no_source_present(self) -> None:
        with pytest.raises(DatabaseConfigurationError):
            Settings().effective_database_url

    def test_raises_when_addon_parts_incomplete(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Host present but user/password/db missing -> not enough to assemble.
        monkeypatch.setenv("POSTGRESQL_ADDON_HOST", "addon-host")

        with pytest.raises(DatabaseConfigurationError):
            Settings().effective_database_url


class TestUnrelatedEnvIgnored:
    def test_extra_env_vars_do_not_break_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
        monkeypatch.setenv("GITHUB_TOKEN", "should-be-ignored")

        settings = Settings()

        assert settings.effective_database_url == "postgresql://u:p@h/db"
        assert not hasattr(settings, "github_token")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
