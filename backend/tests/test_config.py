"""Tests for the pydantic-settings ``Settings`` class (``backend.config``).

The application reads its database connection string *exclusively* from the
``DATABASE_URL`` process environment variable (Requirement 11.1) and must abort
startup when it is absent (Requirement 11.2). These tests pin that contract on
the canonical :class:`~backend.config.Settings` object:

* ``database_url`` is a required field — constructing ``Settings`` with no
  ``DATABASE_URL`` in the environment raises a ``ValidationError``;
* when ``DATABASE_URL`` is present, ``Settings().database_url`` returns exactly
  that value (verbatim — scheme rewriting for asyncpg happens later, in the
  engine factory, Requirement 11.6);
* unrelated environment variables are ignored.

``DATABASE_URL`` is manipulated via ``monkeypatch`` so the real process
environment is restored after every test and nothing leaks between tests.
"""

import pytest
from pydantic import ValidationError

from backend.config import Settings


class TestDatabaseUrlRequired:
    def test_missing_database_url_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(ValidationError):
            Settings()

    def test_present_database_url_is_read_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host:5432/db")

        settings = Settings()

        assert settings.database_url == "postgresql://user:pw@host:5432/db"

    def test_value_is_read_verbatim_without_scheme_rewrite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The asyncpg scheme rewrite (postgresql:// -> postgresql+asyncpg://)
        # belongs to the engine factory (Requirement 11.6), not Settings. The
        # Settings object must expose the raw environment value unchanged.
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")

        assert Settings().database_url == "postgresql://u:p@h/db"


class TestUnrelatedEnvIgnored:
    def test_extra_env_vars_do_not_break_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
        monkeypatch.setenv("GITHUB_TOKEN", "should-be-ignored")

        settings = Settings()

        assert settings.database_url == "postgresql://u:p@h/db"
        assert not hasattr(settings, "github_token")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
