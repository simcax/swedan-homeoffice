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
