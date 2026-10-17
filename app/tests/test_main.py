"""Tests for the Flet app entry point and routing (task 13).

These tests exercise the runtime-free helpers in :mod:`app.main` — base-URL
resolution, initial-route resolution, and per-route view building — with mocked
storage and a mocked :class:`ft.Page`; the Flet runtime is never started.

They verify:

* ``resolve_base_url`` honours the env → storage → default precedence and
  normalises trailing slashes (Requirement 11.1 convention),
* ``resolve_initial_route`` maps known routes through and falls back to home
  for unknown/``None`` routes,
* ``build_view`` returns an ``ft.View`` carrying the correct route and the home
  / summary / settings body for each known route (Requirements 1.4, 5.1, 6.1,
  7.1).

Requirements: 1.4, 5.1, 6.1, 7.1
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import flet as ft

from app.api_client import APIClient
from app.main import (
    DEFAULT_API_BASE_URL,
    KNOWN_ROUTES,
    ROUTE_HOME,
    ROUTE_SETTINGS,
    ROUTE_SUMMARY,
    build_view,
    resolve_base_url,
    resolve_initial_route,
)
from app.state import AppState


def _fake_storage(*, get_return: object = None) -> MagicMock:
    """Build a mock exposing async ``get`` / ``set`` like ``SharedPreferences``."""
    storage = MagicMock()
    storage.get = AsyncMock(return_value=get_return)
    storage.set = AsyncMock(return_value=True)
    return storage


def _app_state() -> AppState:
    return AppState(selected_month=date(2025, 6, 1))


# ---------------------------------------------------------------------------
# resolve_base_url (env -> storage -> default precedence)
# ---------------------------------------------------------------------------


async def test_resolve_base_url_prefers_env():
    storage = _fake_storage(get_return="https://stored.example.com")

    result = await resolve_base_url(
        env={"API_BASE_URL": "https://env.example.com"},
        storage=storage,
    )

    assert result == "https://env.example.com"
    # Env wins, so storage must not be consulted.
    storage.get.assert_not_awaited()


async def test_resolve_base_url_strips_trailing_slash_from_env():
    result = await resolve_base_url(
        env={"API_BASE_URL": "https://env.example.com/"},
        storage=None,
    )

    assert result == "https://env.example.com"


async def test_resolve_base_url_falls_back_to_storage_when_env_absent():
    storage = _fake_storage(get_return="https://stored.example.com")

    result = await resolve_base_url(env={}, storage=storage)

    assert result == "https://stored.example.com"
    storage.get.assert_awaited_once()


async def test_resolve_base_url_ignores_blank_env():
    storage = _fake_storage(get_return="https://stored.example.com")

    result = await resolve_base_url(env={"API_BASE_URL": "   "}, storage=storage)

    assert result == "https://stored.example.com"


async def test_resolve_base_url_defaults_when_no_source():
    result = await resolve_base_url(env={}, storage=None)

    assert result == DEFAULT_API_BASE_URL


async def test_resolve_base_url_uses_storage_default_when_key_missing():
    storage = _fake_storage(get_return=None)

    result = await resolve_base_url(env={}, storage=storage)

    assert result == DEFAULT_API_BASE_URL


# ---------------------------------------------------------------------------
# resolve_initial_route
# ---------------------------------------------------------------------------


def test_resolve_initial_route_passes_known_routes_through():
    for route in KNOWN_ROUTES:
        assert resolve_initial_route(route) == route


def test_resolve_initial_route_defaults_none_to_home():
    assert resolve_initial_route(None) == ROUTE_HOME


def test_resolve_initial_route_defaults_unknown_to_home():
    assert resolve_initial_route("/does-not-exist") == ROUTE_HOME


# ---------------------------------------------------------------------------
# build_view
# ---------------------------------------------------------------------------


def _build(route: str) -> ft.View:
    page = MagicMock(spec=ft.Page)
    page.route = route
    return build_view(
        page,
        route,
        _app_state(),
        APIClient("http://127.0.0.1:8080"),
        _fake_storage(),
    )


def test_build_view_home_route():
    view = _build(ROUTE_HOME)

    assert isinstance(view, ft.View)
    assert view.route == ROUTE_HOME
    assert view.navigation_bar is not None
    assert len(view.controls) == 1


def test_build_view_summary_route():
    view = _build(ROUTE_SUMMARY)

    assert isinstance(view, ft.View)
    assert view.route == ROUTE_SUMMARY


def test_build_view_settings_route():
    view = _build(ROUTE_SETTINGS)

    assert isinstance(view, ft.View)
    assert view.route == ROUTE_SETTINGS


def test_build_view_unknown_route_falls_back_to_home():
    view = _build("/nope")

    assert view.route == ROUTE_HOME


def test_build_view_settings_prefills_api_client_base_url():
    page = MagicMock(spec=ft.Page)
    page.route = ROUTE_SETTINGS
    view = build_view(
        page,
        ROUTE_SETTINGS,
        _app_state(),
        APIClient("https://configured.example.com/"),
        _fake_storage(),
    )

    # The settings view TextField should be pre-filled with the client's URL.
    fields: list[ft.TextField] = []

    def _walk(node: object) -> None:
        if isinstance(node, ft.TextField):
            fields.append(node)
        content = getattr(node, "content", None)
        if content is not None:
            _walk(content)
        for child in getattr(node, "controls", []) or []:
            _walk(child)

    for control in view.controls:
        _walk(control)

    assert fields, "expected a TextField in the settings view"
    assert fields[0].value == "https://configured.example.com"


def test_build_view_mounts_services():
    page = MagicMock(spec=ft.Page)
    page.route = ROUTE_SETTINGS
    storage = ft.SharedPreferences()
    view = build_view(
        page,
        ROUTE_SETTINGS,
        _app_state(),
        APIClient("http://127.0.0.1:8080"),
        storage,
        services=[storage],
    )

    assert storage in view.services
