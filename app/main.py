"""Flet app entry point and route-based navigation (task 13).

This module wires the three screens of the work-location-tracker app together
behind Flet 1.0.2's route-based navigation and bootstraps the shared
:class:`app.state.AppState` and :class:`app.api_client.APIClient` from the
configured API base URL.

Routes
------

===========  ======================================================
Route        Screen
===========  ======================================================
``"/"``      Home calendar + quick-log buttons (``build_home_view``)
``"/summary"``  Monthly / annual compliance summary (``build_summary_view``)
``"/settings"`` API base URL configuration (``build_settings_view``)
===========  ======================================================

Base URL resolution (startup)
-----------------------------

The API base URL is resolved with the following precedence so operators can
override it per environment without touching code (Requirement 11.1 mirrors
this on the backend; the frontend follows the same env-first convention):

1. the ``API_BASE_URL`` environment variable, when set and non-blank;
2. the value previously persisted to local storage (Flet
   ``SharedPreferences``) under :data:`~app.views.settings_view.API_BASE_URL_KEY`;
3. a sensible local-development default
   (:data:`~app.views.settings_view.DEFAULT_API_BASE_URL`,
   ``http://127.0.0.1:8080``).

Flet 1.0.2 routing model
------------------------

Unlike the older ``page.go`` / ``page.views`` API, Flet 1.0.2 drives navigation
through ``page.route`` + ``page.on_route_change`` and the async
``page.push_route`` (with the sync ``page.navigate`` wrapper). The route-change
handler rebuilds ``page.views`` from scratch for the active route so each screen
always reflects the current :class:`AppState`.

Testability
-----------

The pure routing/bootstrapping logic lives in runtime-free helpers
(:func:`resolve_base_url`, :func:`resolve_initial_route`, :func:`build_view`)
so it can be unit-tested without starting the Flet runtime. ``main`` and
``run`` are thin wrappers that only perform Flet side effects.

Requirements: 1.4, 5.1, 6.1, 7.1
"""

from __future__ import annotations

import os

import flet as ft

from app.api_client import APIClient
from app.state import AppState
from app.views.home_view import build_home_view
from app.views.settings_view import (
    DEFAULT_API_BASE_URL,
    KeyValueStorage,
    build_settings_view,
    load_api_base_url,
)
from app.views.summary_view import build_summary_view

# Environment variable the API base URL may be supplied through.
API_BASE_URL_ENV = "API_BASE_URL"

# The route each screen is mounted under.
ROUTE_HOME = "/"
ROUTE_SUMMARY = "/summary"
ROUTE_SETTINGS = "/settings"

# Known routes, in display order (used for the navigation bar and validation).
KNOWN_ROUTES: tuple[str, ...] = (ROUTE_HOME, ROUTE_SUMMARY, ROUTE_SETTINGS)


# ---------------------------------------------------------------------------
# pure bootstrapping / routing helpers (no Flet runtime, directly testable)
# ---------------------------------------------------------------------------


async def resolve_base_url(
    env: dict[str, str] | None = None,
    storage: KeyValueStorage | None = None,
    default: str = DEFAULT_API_BASE_URL,
) -> str:
    """Resolve the API base URL using env → storage → default precedence.

    The ``API_BASE_URL`` environment variable wins when present and non-blank.
    Otherwise, when a ``storage`` service is supplied, the value persisted by
    the settings screen is used (via :func:`load_api_base_url`). When neither
    source yields a usable value, ``default`` is returned.

    The returned URL always has any trailing slash stripped so it composes
    cleanly with the ``/api/v1/...`` paths used by :class:`APIClient`.

    Args:
        env: Environment mapping to read from (defaults to ``os.environ``).
        storage: Optional async key-value storage service to fall back to.
        default: The URL to return when no other source yields one.

    Returns:
        The resolved, normalised API base URL.
    """
    environment = os.environ if env is None else env

    env_value = (environment.get(API_BASE_URL_ENV) or "").strip()
    if env_value:
        return env_value.rstrip("/")

    if storage is not None:
        stored = await load_api_base_url(storage, default=default)
        return stored.rstrip("/")

    return default.rstrip("/")


def resolve_initial_route(route: str | None) -> str:
    """Return a valid starting route, defaulting unknown values to home.

    Flet reports the current route via ``page.route``; on a fresh launch this
    is usually ``"/"`` but may be ``None`` or an unrecognised deep link. Any
    value outside :data:`KNOWN_ROUTES` resolves to :data:`ROUTE_HOME` so the
    app always has a renderable screen.

    Args:
        route: The incoming route (e.g. ``page.route``), possibly ``None``.

    Returns:
        A route guaranteed to be one of :data:`KNOWN_ROUTES`.
    """
    if route in KNOWN_ROUTES:
        return route  # type: ignore[return-value]
    return ROUTE_HOME


def build_view(
    page: ft.Page,
    route: str,
    state: AppState,
    api_client: APIClient,
    storage: KeyValueStorage,
    *,
    services: list[ft.Service] | None = None,
    on_settings_saved=None,
) -> ft.View:
    """Build the :class:`ft.View` for ``route`` from the current state.

    The unknown-route fallback goes through :func:`resolve_initial_route`, so
    this never raises for a bad route — it renders the home screen instead.
    Each view carries a bottom :class:`ft.NavigationBar` so the user can move
    between the three screens, and (when supplied) the ``services`` list so the
    ``SharedPreferences`` storage service is mounted for the settings screen.

    Args:
        page: The active Flet page.
        route: The route to render; unknown routes fall back to home.
        state: The shared in-memory :class:`AppState`.
        api_client: The backend :class:`APIClient`.
        storage: The async key-value storage service for the settings screen.
        services: Optional Flet services to mount on the view (e.g.
            ``SharedPreferences``).
        on_settings_saved: Optional callback forwarded to the settings view and
            invoked with the normalised URL after a successful save.

    Returns:
        A configured :class:`ft.View` for the resolved route.
    """
    resolved = resolve_initial_route(route)

    if resolved == ROUTE_SUMMARY:
        body: ft.Control = build_summary_view(
            state.compliance_summary,
            None,
        )
    elif resolved == ROUTE_SETTINGS:
        body = build_settings_view(
            page,
            storage,
            current_value=api_client.base_url,
            on_saved=on_settings_saved,
        )
    else:
        body = build_home_view(page, state, api_client)

    return ft.View(
        route=resolved,
        controls=[body],
        navigation_bar=_build_navigation_bar(page, resolved),
        services=list(services) if services else [],
    )


def _build_navigation_bar(page: ft.Page, active_route: str) -> ft.NavigationBar:
    """Build the bottom navigation bar for switching between screens."""
    labels = (
        (ROUTE_HOME, "Home", ft.Icons.CALENDAR_MONTH),
        (ROUTE_SUMMARY, "Summary", ft.Icons.INSIGHTS),
        (ROUTE_SETTINGS, "Settings", ft.Icons.SETTINGS),
    )

    selected = next(
        (i for i, (route, _, _) in enumerate(labels) if route == active_route),
        0,
    )

    def _on_change(e: ft.ControlEvent) -> None:
        index = int(e.control.selected_index)
        target = labels[index][0]
        if target != active_route:
            page.navigate(target)

    return ft.NavigationBar(
        selected_index=selected,
        on_change=_on_change,
        destinations=[
            ft.NavigationBarDestination(icon=icon, label=label)
            for _route, label, icon in labels
        ],
    )


# ---------------------------------------------------------------------------
# Flet entry point (runtime side effects only)
# ---------------------------------------------------------------------------


async def main(page: ft.Page) -> None:
    """Flet entry point: bootstrap state and wire route-based navigation.

    Initialises the shared :class:`AppState` and :class:`APIClient` from the
    resolved base URL, then installs an ``on_route_change`` handler that
    rebuilds ``page.views`` for the active route. ``page.navigate`` /
    ``page.push_route`` drive navigation between the home, summary and settings
    screens.
    """
    page.title = "Work Location Tracker"
    page.theme_mode = ft.ThemeMode.SYSTEM

    storage = ft.SharedPreferences()

    base_url = await resolve_base_url(storage=storage)
    state = AppState(selected_month=_first_of_this_month())
    api_client = APIClient(base_url)

    def _on_settings_saved(new_url: str) -> None:
        # Rebuild the client against the newly saved URL so later requests use
        # it immediately, then repaint the active screen.
        nonlocal api_client
        api_client = APIClient(new_url)
        _render(page.route)

    def _render(route: str | None) -> None:
        page.views.clear()
        page.views.append(
            build_view(
                page,
                resolve_initial_route(route),
                state,
                api_client,
                storage,
                services=[storage],
                on_settings_saved=_on_settings_saved,
            )
        )
        page.update()

    def _on_route_change(e: ft.RouteChangeEvent) -> None:
        _render(e.route)

    page.on_route_change = _on_route_change

    # Load the initial month's data before the first render so the home screen
    # opens populated (Requirements 1.4, 5.1, 6.1).
    await _load_initial_data(state, api_client)

    # Trigger the initial render for whatever route the app launched on.
    page.navigate(resolve_initial_route(page.route))


async def _load_initial_data(state: AppState, api_client: APIClient) -> None:
    """Best-effort load of the current month's entries and summary.

    Failures are swallowed so the UI still renders (an empty calendar) when the
    backend is unreachable at launch; the home screen's own error handling
    surfaces subsequent failures.
    """
    from app.views.home_view import load_month

    await load_month(
        state,
        api_client,
        state.selected_month.year,
        state.selected_month.month,
    )


def _first_of_this_month():
    """Return the first day of the current month."""
    from datetime import date

    today = date.today()  # noqa: DTZ011
    return date(today.year, today.month, 1)


def run() -> None:
    """Start the Flet runtime with :func:`main` as the entry point."""
    ft.run(main)


if __name__ == "__main__":
    run()
