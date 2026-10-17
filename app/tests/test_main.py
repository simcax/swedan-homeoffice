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

import app.main as app_main
from app.api_client import (
    AnnualSummary,
    APIClient,
    APIError,
    ComplianceSummary,
    WorkEntry,
    WorkLocation,
)
from app.main import (
    DEFAULT_API_BASE_URL,
    KNOWN_ROUTES,
    ROUTE_HOME,
    ROUTE_SETTINGS,
    ROUTE_SUMMARY,
    build_view,
    load_annual_summary,
    reset_for_new_backend,
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


def _entry(day: int, location: WorkLocation = WorkLocation.DENMARK) -> WorkEntry:
    return WorkEntry(
        id=day,
        work_date=date(2025, 6, day),
        location=location,
        created_at="2025-06-10T08:00:00+00:00",
        updated_at="2025-06-10T08:00:00+00:00",
    )


def _summary() -> ComplianceSummary:
    return ComplianceSummary(
        year=2025,
        month=6,
        total_days=10,
        denmark_days=6,
        vacation_days=0,
        sick_days=0,
        home_days=4,
        compliance_pct=60.0,
        is_compliant=True,
    )


def _annual() -> AnnualSummary:
    return AnnualSummary(
        year=2025,
        total_days=100,
        denmark_days=60,
        vacation_days=10,
        sick_days=5,
        home_days=25,
        compliance_pct=60.0,
        is_compliant=True,
        monthly_breakdown=[],
    )


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


async def test_main_mounts_storage_before_resolving_base_url(monkeypatch):
    storage = ft.SharedPreferences()
    page = MagicMock(spec=ft.Page)
    page.route = ROUTE_HOME
    page.services = []
    events = []

    monkeypatch.setattr(app_main.ft, "SharedPreferences", lambda: storage)

    async def _resolve(*, storage):
        assert page.services == [storage]
        assert page.update.call_count == 1
        events.append("resolve")
        return DEFAULT_API_BASE_URL

    monkeypatch.setattr(app_main, "resolve_base_url", _resolve)
    monkeypatch.setattr(app_main, "_load_initial_data", AsyncMock())

    await app_main.main(page)

    assert events == ["resolve"]
    page.on_route_change(MagicMock(route=ROUTE_HOME))
    home_view = page.views.append.call_args.args[0]
    assert storage in home_view.services

    page.on_route_change(MagicMock(route=ROUTE_SUMMARY))
    summary_view = page.views.append.call_args.args[0]
    assert storage in page.services
    assert storage in summary_view.services


async def test_pending_home_update_rebuilds_the_active_summary_route(monkeypatch):
    page = MagicMock(spec=ft.Page)
    page.route = ROUTE_HOME
    page.services = []
    storage = ft.SharedPreferences()
    client = MagicMock()
    client.base_url = DEFAULT_API_BASE_URL
    client.post_entry = AsyncMock(return_value=_entry(10))
    client.get_summary = AsyncMock(return_value=_summary())
    client.get_annual_summary = AsyncMock(return_value=_annual())

    monkeypatch.setattr(app_main.ft, "SharedPreferences", lambda: storage)
    monkeypatch.setattr(app_main, "resolve_base_url", AsyncMock(
        return_value=DEFAULT_API_BASE_URL
    ))
    monkeypatch.setattr(app_main, "APIClient", lambda _url: client)
    monkeypatch.setattr(app_main, "_load_initial_data", AsyncMock())
    monkeypatch.setattr(
        app_main, "_first_of_this_month", lambda: date(2025, 6, 1)
    )

    await app_main.main(page)
    page.on_route_change(MagicMock(route=ROUTE_HOME))
    home_view = page.views.append.call_args.args[0]

    buttons: list[ft.Button] = []

    def _walk(control: object) -> None:
        if isinstance(control, ft.Button):
            buttons.append(control)
        content = getattr(control, "content", None)
        if content is not None:
            _walk(content)
        for child in getattr(control, "controls", []) or []:
            _walk(child)

    for control in home_view.controls:
        _walk(control)
    next(
        button
        for button in buttons
        if button.data is WorkLocation.DENMARK
    ).on_click(MagicMock())
    operation = page.run_task.call_args.args[0]

    page.route = ROUTE_SUMMARY
    page.on_route_change(MagicMock(route=ROUTE_SUMMARY))
    old_summary_view = page.views.append.call_args.args[0]
    await operation()

    updated_view = page.views.append.call_args.args[0]
    assert updated_view.route == ROUTE_SUMMARY
    assert updated_view is not old_summary_view


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


# ---------------------------------------------------------------------------
# build_view — summary route passes the annual summary through (Fix 2)
# ---------------------------------------------------------------------------


def test_build_view_summary_renders_annual_table_when_set():
    state = _app_state()
    state.compliance_summary = _summary()
    state.annual_summary = _annual()
    page = MagicMock(spec=ft.Page)
    page.route = ROUTE_SUMMARY

    view = build_view(
        page,
        ROUTE_SUMMARY,
        state,
        APIClient("http://127.0.0.1:8080"),
        _fake_storage(),
    )

    # When the annual summary is present, the summary view renders a data table
    # (the annual breakdown) rather than the "no annual summary" placeholder.
    tables: list[ft.DataTable] = []

    def _walk(node: object) -> None:
        if isinstance(node, ft.DataTable):
            tables.append(node)
        content = getattr(node, "content", None)
        if content is not None:
            _walk(content)
        for child in getattr(node, "controls", []) or []:
            _walk(child)

    for control in view.controls:
        _walk(control)

    assert tables, "expected an annual DataTable when state.annual_summary is set"


def test_build_view_summary_no_annual_table_when_unset():
    state = _app_state()
    state.compliance_summary = _summary()
    page = MagicMock(spec=ft.Page)
    page.route = ROUTE_SUMMARY

    view = build_view(
        page,
        ROUTE_SUMMARY,
        state,
        APIClient("http://127.0.0.1:8080"),
        _fake_storage(),
    )

    tables: list[ft.DataTable] = []

    def _walk(node: object) -> None:
        if isinstance(node, ft.DataTable):
            tables.append(node)
        content = getattr(node, "content", None)
        if content is not None:
            _walk(content)
        for child in getattr(node, "controls", []) or []:
            _walk(child)

    for control in view.controls:
        _walk(control)

    assert not tables


# ---------------------------------------------------------------------------
# load_annual_summary (Fix 2)
# ---------------------------------------------------------------------------


async def test_load_annual_summary_populates_state():
    state = _app_state()
    annual = _annual()
    client = MagicMock()
    client.get_annual_summary = AsyncMock(return_value=annual)

    ok = await load_annual_summary(state, client)

    assert ok is True
    assert state.annual_summary is annual
    client.get_annual_summary.assert_awaited_once_with(2025)


async def test_load_annual_summary_swallows_api_error():
    state = _app_state()
    client = MagicMock()
    client.get_annual_summary = AsyncMock(side_effect=APIError("down"))

    ok = await load_annual_summary(state, client)

    assert ok is False
    assert state.annual_summary is None


async def test_load_annual_summary_ignores_superseded_backend_before_request():
    state = _app_state()
    state.backend_generation = 2
    state.annual_summary_generation = 4
    client = MagicMock()
    client.get_annual_summary = AsyncMock()

    ok = await load_annual_summary(state, client, generation=1)

    assert ok is False
    assert state.annual_summary_generation == 4
    client.get_annual_summary.assert_not_awaited()


# ---------------------------------------------------------------------------
# reset_for_new_backend (Fix 1)
# ---------------------------------------------------------------------------


async def test_reset_clears_stale_state_then_reloads_from_new_client():
    # State was fetched from the OLD backend: a stale entry with id 999 and
    # summaries. After reset the entries must come solely from the NEW client.
    state = _app_state()
    state.apply_entry(_entry(5, WorkLocation.HOME))
    state.compliance_summary = _summary()
    state.annual_summary = _annual()

    new_entry = _entry(10, WorkLocation.DENMARK)
    new_summary = _summary()
    new_annual = _annual()
    client = MagicMock()
    client.get_entries = AsyncMock(return_value=[new_entry])
    client.get_summary = AsyncMock(return_value=new_summary)
    client.get_annual_summary = AsyncMock(return_value=new_annual)

    await reset_for_new_backend(state, client)

    # Stale entry gone; only the new backend's entry remains.
    assert "2025-06-05" not in state.entries
    assert state.entries == {"2025-06-10": new_entry}
    assert state.compliance_summary is new_summary
    assert state.annual_summary is new_annual
    client.get_entries.assert_awaited_once_with(2025, 6)
    client.get_annual_summary.assert_awaited_once_with(2025)


async def test_reset_bumps_generation_and_reloads_under_it():
    # reset_for_new_backend opens a new backend era and threads that generation
    # through the reload so late-arriving writes from the old era are dropped.
    state = _app_state()
    assert state.backend_generation == 0

    new_entry = _entry(10, WorkLocation.DENMARK)
    client = MagicMock()
    client.get_entries = AsyncMock(return_value=[new_entry])
    client.get_summary = AsyncMock(return_value=_summary())
    client.get_annual_summary = AsyncMock(return_value=_annual())

    await reset_for_new_backend(state, client)

    # The generation was bumped exactly once and the reload populated state.
    assert state.backend_generation == 1
    assert state.entries == {"2025-06-10": new_entry}
    assert state.annual_summary is not None


async def test_reset_drops_stale_write_from_previous_generation():
    # Simulate the temporal race: an OLD in-flight request finishes AFTER the
    # reset bumped the generation and tries to write a stale entry. The guard
    # must drop it so the stale ID never lands in state.
    from app.views.home_view import load_month

    state = _app_state()
    captured_gen = state.backend_generation  # old era (0)

    # New backend reload for the reset itself.
    client = MagicMock()
    client.get_entries = AsyncMock(return_value=[])
    client.get_summary = AsyncMock(return_value=_summary())
    client.get_annual_summary = AsyncMock(return_value=_annual())

    await reset_for_new_backend(state, client)
    assert state.backend_generation == 1
    assert state.entries == {}

    # Now the OLD request (started under generation 0) completes and tries to
    # write a stale entry with an old ID.
    stale = _entry(5, WorkLocation.HOME)
    old_client = MagicMock()
    old_client.get_entries = AsyncMock(return_value=[stale])
    old_client.get_summary = AsyncMock(return_value=_summary())

    ok = await load_month(state, old_client, 2025, 6, generation=captured_gen)

    assert ok is False
    # The stale entry from the previous generation was discarded.
    assert state.entries == {}


async def test_reset_clears_stale_state_even_when_new_backend_down():
    # If the new backend is unreachable, stale state must still be discarded so
    # no edit/delete can send an old ID to the new backend.
    state = _app_state()
    state.apply_entry(_entry(5, WorkLocation.HOME))
    state.compliance_summary = _summary()
    state.annual_summary = _annual()

    client = MagicMock()
    client.get_entries = AsyncMock(side_effect=APIError("down"))
    client.get_summary = AsyncMock(side_effect=APIError("down"))
    client.get_annual_summary = AsyncMock(side_effect=APIError("down"))

    await reset_for_new_backend(state, client)

    # load_month preserves selected_month on failure but the stale entries were
    # cleared before the fetch, so nothing from the old backend survives.
    assert state.entries == {}
    assert state.annual_summary is None
