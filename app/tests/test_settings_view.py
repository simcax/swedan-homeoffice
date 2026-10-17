"""Tests for the settings view (task 12.5).

These tests exercise the API-base-URL persistence helpers and the settings
view's control-builder logic with a mocked storage service; the Flet runtime is
never started. They verify:

* ``load_api_base_url`` reads the stored value, and falls back to the default
  when the key is missing or blank (Requirement 11.1),
* ``save_api_base_url`` normalises and persists the value through the async
  ``SharedPreferences.set`` API (Requirement 11.1),
* ``build_settings_view`` returns a container whose ``ft.TextField`` is
  pre-filled with the supplied current value.

Requirements: 11.1
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import flet as ft

from app.views.settings_view import (
    API_BASE_URL_KEY,
    DEFAULT_API_BASE_URL,
    build_settings_view,
    load_api_base_url,
    save_api_base_url,
    validate_api_base_url,
    warn_insecure_api_base_url,
)


def _fake_storage(*, get_return: object = None) -> MagicMock:
    """Build a mock exposing async ``get`` / ``set`` like ``SharedPreferences``."""
    storage = MagicMock()
    storage.get = AsyncMock(return_value=get_return)
    storage.set = AsyncMock(return_value=True)
    return storage


def _find_textfields(control: ft.Control) -> list[ft.TextField]:
    """Recursively collect every ``ft.TextField`` in a control tree."""
    found: list[ft.TextField] = []

    def _walk(node: object) -> None:
        if isinstance(node, ft.TextField):
            found.append(node)
        content = getattr(node, "content", None)
        if content is not None:
            _walk(content)
        for child in getattr(node, "controls", []) or []:
            _walk(child)

    _walk(control)
    return found


# ---------------------------------------------------------------------------
# load_api_base_url
# ---------------------------------------------------------------------------


async def test_load_returns_stored_value():
    storage = _fake_storage(get_return="https://api.example.com")

    result = await load_api_base_url(storage)

    assert result == "https://api.example.com"
    storage.get.assert_awaited_once_with(API_BASE_URL_KEY)


async def test_load_falls_back_to_default_when_missing():
    storage = _fake_storage(get_return=None)

    result = await load_api_base_url(storage)

    assert result == DEFAULT_API_BASE_URL


async def test_load_falls_back_to_default_when_blank():
    storage = _fake_storage(get_return="   ")

    result = await load_api_base_url(storage)

    assert result == DEFAULT_API_BASE_URL


async def test_load_uses_supplied_default():
    storage = _fake_storage(get_return=None)

    result = await load_api_base_url(storage, default="http://localhost:9000")

    assert result == "http://localhost:9000"


# ---------------------------------------------------------------------------
# save_api_base_url
# ---------------------------------------------------------------------------


async def test_save_persists_value_under_key():
    storage = _fake_storage()

    returned = await save_api_base_url(storage, "https://api.example.com")

    assert returned == "https://api.example.com"
    storage.set.assert_awaited_once_with(API_BASE_URL_KEY, "https://api.example.com")


async def test_save_normalises_whitespace_and_trailing_slash():
    storage = _fake_storage()

    returned = await save_api_base_url(storage, "  https://api.example.com/  ")

    assert returned == "https://api.example.com"
    storage.set.assert_awaited_once_with(API_BASE_URL_KEY, "https://api.example.com")


# ---------------------------------------------------------------------------
# build_settings_view
# ---------------------------------------------------------------------------


def test_build_settings_view_prefills_current_value():
    page = MagicMock()

    container = build_settings_view(
        page, _fake_storage(), current_value="https://stored.example.com"
    )

    assert isinstance(container, ft.Container)
    fields = _find_textfields(container)
    assert len(fields) == 1
    assert fields[0].value == "https://stored.example.com"


def test_build_settings_view_defaults_to_default_url():
    page = MagicMock()

    container = build_settings_view(page, _fake_storage())

    fields = _find_textfields(container)
    assert fields[0].value == DEFAULT_API_BASE_URL


# ---------------------------------------------------------------------------
# validate_api_base_url (Requirement: URL validation)
# ---------------------------------------------------------------------------


def test_validate_accepts_http():
    assert validate_api_base_url("http://127.0.0.1:8080") is None


def test_validate_accepts_https():
    assert validate_api_base_url("https://api.example.com") is None


def test_validate_rejects_blank():
    assert validate_api_base_url("") is not None
    assert validate_api_base_url("   ") is not None


def test_validate_rejects_missing_scheme():
    # "example.com" has no scheme -> urlparse treats it as a path, so it is
    # rejected.
    assert validate_api_base_url("example.com") is not None


def test_validate_rejects_non_http_scheme():
    assert validate_api_base_url("ftp://x") is not None


def test_validate_rejects_missing_host():
    assert validate_api_base_url("http://") is not None


# ---------------------------------------------------------------------------
# warn_insecure_api_base_url (Fix 3 — plain-http security warning)
# ---------------------------------------------------------------------------


def test_settings_view_warns_for_active_remote_http_url():
    page = MagicMock(spec=ft.Page)
    container = build_settings_view(
        page, _fake_storage(), current_value="http://example.com"
    )

    field = _find_textfields(container)[0]

    assert field.helper_text == warn_insecure_api_base_url("http://example.com")


def test_warn_flags_remote_http_host():
    assert warn_insecure_api_base_url("http://example.com") is not None


def test_warn_flags_remote_http_host_with_port():
    assert warn_insecure_api_base_url("http://api.example.com:8080") is not None


def test_warn_allows_https_remote_host():
    assert warn_insecure_api_base_url("https://example.com") is None


def test_warn_allows_http_localhost():
    assert warn_insecure_api_base_url("http://localhost:8080") is None


def test_warn_allows_http_loopback_ipv4():
    assert warn_insecure_api_base_url("http://127.0.0.1:8080") is None


def test_warn_allows_http_loopback_ipv4_block():
    # Any address in 127.0.0.0/8 is loopback.
    assert warn_insecure_api_base_url("http://127.0.0.5:8080") is None


def test_warn_allows_http_loopback_ipv6():
    assert warn_insecure_api_base_url("http://[::1]:8080") is None


def test_warn_ignores_invalid_url():
    # Invalid URLs are the hard validator's job; the warner stays quiet.
    assert warn_insecure_api_base_url("not-a-url") is None


# ---------------------------------------------------------------------------
# save handler — non-blocking insecure-http warning (Fix 3)
# ---------------------------------------------------------------------------


async def test_save_handler_warns_but_saves_remote_http():
    # A remote plain-http URL is valid, so it must still be persisted and
    # on_saved invoked, but the user is warned via an amber snack bar and a
    # helper text under the field.
    page = MagicMock(spec=ft.Page)
    storage = _fake_storage()
    saved: list[str] = []
    container = build_settings_view(
        page,
        storage,
        current_value="http://example.com",
        on_saved=saved.append,
    )
    field = _find_textfields(container)[0]
    button = _find_save_button(container)

    button.on_click(MagicMock())
    await _run_captured_task(page)

    storage.set.assert_awaited_once_with(API_BASE_URL_KEY, "http://example.com")
    assert saved == ["http://example.com"]
    assert field.error_text is None
    assert field.helper_text is not None
    page.show_dialog.assert_called_once()
    snack = page.show_dialog.call_args.args[0]
    assert isinstance(snack, ft.SnackBar)
    # Distinct from the green success toast.
    assert snack.bgcolor == ft.Colors.AMBER_700


async def test_save_handler_no_warning_for_https():
    page = MagicMock(spec=ft.Page)
    storage = _fake_storage()
    container = build_settings_view(
        page, storage, current_value="https://api.example.com"
    )
    field = _find_textfields(container)[0]
    button = _find_save_button(container)

    button.on_click(MagicMock())
    await _run_captured_task(page)

    storage.set.assert_awaited_once()
    assert field.helper_text is None
    snack = page.show_dialog.call_args.args[0]
    assert snack.bgcolor == ft.Colors.GREEN_700


# ---------------------------------------------------------------------------
# save handler smoke tests against a spec'd ft.Page (Flet 1.0.2 API + reject)
# ---------------------------------------------------------------------------


def _find_save_button(container: ft.Container) -> ft.Button:
    """Locate the single ``ft.Button`` (the Save button) in the view tree."""
    found: list[ft.Button] = []

    def _walk(node: object) -> None:
        if isinstance(node, ft.Button):
            found.append(node)
        content = getattr(node, "content", None)
        if content is not None:
            _walk(content)
        for child in getattr(node, "controls", []) or []:
            _walk(child)

    _walk(container)
    assert len(found) == 1
    return found[0]


async def _run_captured_task(page: MagicMock) -> None:
    """Await the coroutine passed to ``page.run_task`` by the save handler."""
    assert page.run_task.call_count == 1
    coro = page.run_task.call_args.args[0]
    await coro()


async def test_save_handler_persists_valid_url_and_shows_dialog():
    # A valid URL must be persisted and surfaced via show_dialog (the Flet
    # 1.0.2 API). A spec'd ft.Page mock would raise AttributeError if the
    # handler reached for the removed page.open.
    page = MagicMock(spec=ft.Page)
    storage = _fake_storage()
    container = build_settings_view(
        page, storage, current_value="https://api.example.com"
    )
    field = _find_textfields(container)[0]
    button = _find_save_button(container)

    button.on_click(MagicMock())
    await _run_captured_task(page)

    storage.set.assert_awaited_once_with(API_BASE_URL_KEY, "https://api.example.com")
    page.show_dialog.assert_called_once()
    assert isinstance(page.show_dialog.call_args.args[0], ft.SnackBar)
    assert field.error_text is None


async def test_save_handler_rejects_invalid_url_without_persisting():
    # An invalid URL must NOT be persisted; the handler sets error_text and
    # shows a red snack bar via show_dialog.
    page = MagicMock(spec=ft.Page)
    storage = _fake_storage()
    container = build_settings_view(page, storage, current_value="not-a-url")
    field = _find_textfields(container)[0]
    button = _find_save_button(container)

    button.on_click(MagicMock())
    await _run_captured_task(page)

    storage.set.assert_not_awaited()
    assert field.error_text is not None
    page.show_dialog.assert_called_once()
    assert isinstance(page.show_dialog.call_args.args[0], ft.SnackBar)


def test_ft_page_has_no_open_or_close():
    # Guard the premise behind these smoke tests.
    assert not hasattr(ft.Page, "open")
    assert not hasattr(ft.Page, "close")
    assert hasattr(ft.Page, "show_dialog")
    assert hasattr(ft.Page, "pop_dialog")
