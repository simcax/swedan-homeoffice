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

Shared-secret gate (startup)
----------------------------

Before the first paint, ``main`` resolves the gated :class:`~app.state.Screen`
from the shared secret persisted in ``SharedPreferences``
(:func:`~app.views.login_view.load_secret` +
:func:`~app.views.login_view.resolve_initial_screen`). When a usable secret is
remembered, the :class:`APIClient` is configured to attach it as the
``X-API-Key`` header and the initial month's data is loaded; otherwise the
login screen is shown and no entry/summary requests are issued until the user
submits a secret (Requirements 5.1, 5.2, 6.2). The login submit handler
persists the secret, configures the client, loads initial data and navigates
to the front page (Requirements 5.3, 5.4).

Shared-secret recovery (401)
----------------------------

Every background coroutine is scheduled through ``page.run_task``, which
``main`` wraps so any :class:`~app.api_client.AuthError` raised by a rejected
secret is caught centrally. The wrapper invokes :func:`handle_auth_error`,
which forgets the stored and in-memory secret and flips the gated screen back
to login, then repaints the login view with the "secret rejected" message
(Requirements 8.1, 8.2, 8.3).

Requirements: 1.4, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 7.1, 8.1, 8.2, 8.3
"""

from __future__ import annotations

import os

import flet as ft

from app.api_client import APIClient, APIError, AuthError
from app.concurrency import GuardKind, WriteGuard, backend_superseded
from app.state import AppState, Screen
from app.views.home_view import build_home_view
from app.views.login_view import (
    build_login_view,
    clear_secret,
    load_secret,
    resolve_initial_screen,
    save_secret,
)
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


async def load_annual_summary(
    state: AppState,
    api_client: APIClient,
    *,
    generation: int | None = None,
) -> bool:
    """Best-effort load of the annual summary for the selected year.

    Fetches ``api_client.get_annual_summary`` for ``state.selected_month.year``
    and stores the result on ``state.annual_summary``. Any :class:`APIError` is
    swallowed (the field is left unchanged) so the UI still renders when the
    backend is unreachable, mirroring :func:`_load_initial_data`'s best-effort
    behaviour.

    Before storing the response, this checks that the requested year is still
    selected, that no newer annual-summary request has started, and (when
    ``generation`` is supplied) that the backend has not changed in flight.
    Superseded results are discarded and the method returns ``False``.

    Args:
        state: The shared in-memory :class:`AppState` to populate.
        api_client: The backend :class:`APIClient` to fetch from.
        generation: Optional backend generation guarding the write.

    Returns:
        ``True`` when the annual summary was fetched and stored, ``False`` when
        the request failed (or was superseded) and the previous value was kept.
    """
    if backend_superseded(state, generation):
        return False

    guard = WriteGuard.capture(state, kind=GuardKind.ANNUAL, generation=generation)
    try:
        annual = await api_client.get_annual_summary(guard.year)
    except APIError:
        return False

    if guard.is_stale(state):
        return False

    state.annual_summary = annual
    return True


async def reset_for_new_backend(state: AppState, api_client: APIClient) -> None:
    """Discard state fetched from a previous backend and reload against ``api_client``.

    When the configured API base URL changes, entries, summaries and IDs
    fetched from the *old* backend become unsafe to reuse: an edit/delete would
    send a stale ID to the new backend and could mutate an unrelated record
    with a colliding ID. This helper clears that stale state up front, then
    reloads the currently selected month (entries + monthly summary via
    :func:`app.views.home_view.load_month`) and the annual summary (via
    :func:`load_annual_summary`) against the new ``api_client``.

    To close the *temporal* race a bare URL comparison cannot — a request
    already in flight against the old client may finish *after* this reset and
    write old entries (with old IDs) back into state — the backend generation
    counter is bumped first. The captured ``gen`` is threaded through the
    reloads, and every guarded load/mutation coroutine re-checks it before
    committing, so any late-arriving write from the previous generation is
    dropped instead of resurrecting stale IDs (Fix A).

    The reload is best-effort: ``load_month`` records any error on ``state`` and
    the annual fetch is swallowed, so the UI still renders if the new backend is
    unreachable. The helper is pure of the Flet runtime so it can be unit-tested
    with a mocked ``api_client`` and a plain :class:`AppState`.

    Args:
        state: The shared in-memory :class:`AppState` to reset and repopulate.
        api_client: The newly configured backend :class:`APIClient`.
    """
    from app.views.home_view import load_month

    # Open a new backend era: any in-flight request from the previous
    # generation will fail its guard check and have its write discarded.
    state.backend_generation += 1
    state.annual_summary_generation += 1
    gen = state.backend_generation

    # Drop everything fetched from the old backend before any edit/delete can
    # target the new one with a stale ID.
    state.entries = {}
    state.compliance_summary = None
    state.annual_summary = None

    await load_month(
        state,
        api_client,
        state.selected_month.year,
        state.selected_month.month,
        generation=gen,
    )
    await load_annual_summary(state, api_client, generation=gen)


async def handle_auth_error(
    state: AppState,
    api_client: APIClient,
    storage: KeyValueStorage,
) -> None:
    """Return the app to the login screen after the backend rejects the secret.

    Invoked centrally whenever any ``page.run_task`` coroutine raises
    :class:`~app.api_client.AuthError` (the backend answered an entry/summary
    request with HTTP ``401``). It forgets the rejected secret everywhere it is
    held and flips the gated screen back to login so the user is prompted to
    re-enter a valid secret:

    * removes the stored secret from local storage via
      :func:`~app.views.login_view.clear_secret` (Requirement 8.1);
    * clears the client's in-memory secret with ``api_client.set_secret(None)``
      so no further request carries the rejected key (Requirement 8.2);
    * sets ``state.auth_rejected = True`` so the login view shows the
      "secret rejected" message (Requirement 8.3);
    * sets ``state.screen = Screen.LOGIN`` so the front page is withheld
      (Requirement 8.2).

    This mutates ``state`` and ``api_client`` and persists the storage change,
    but performs no Flet rendering itself — the caller repaints after awaiting
    it (see the ``page.run_task`` wrapper installed in :func:`main`). Keeping it
    free of the Flet runtime makes it directly unit-testable with a plain
    :class:`AppState`, a mocked ``api_client`` and a mock storage.

    Args:
        state: The shared in-memory :class:`AppState` to flip back to login.
        api_client: The backend :class:`APIClient` whose secret is cleared.
        storage: The async key-value storage the secret is removed from.
    """
    await clear_secret(storage)
    api_client.set_secret(None)
    state.auth_rejected = True
    state.screen = Screen.LOGIN


def build_view(
    page: ft.Page,
    route: str,
    state: AppState,
    api_client: APIClient,
    storage: KeyValueStorage,
    *,
    services: list[ft.Service] | None = None,
    on_settings_saved=None,
    on_state_change=None,
    on_login_submit=None,
) -> ft.View:
    """Build the :class:`ft.View` for ``route`` from the current state.

    When ``state.screen`` is :attr:`Screen.LOGIN` the app is gated: the login
    screen is rendered instead of the routed home/summary/settings view and the
    bottom navigation bar is withheld, so the front page stays inaccessible
    until a shared secret is supplied (Requirements 5.1, 6.2). ``on_login_submit``
    is wired to the login form's submit callback.

    Otherwise the unknown-route fallback goes through
    :func:`resolve_initial_route`, so this never raises for a bad route — it
    renders the home screen instead. Each routed view carries a bottom
    :class:`ft.NavigationBar` so the user can move between the three screens,
    and (when supplied) the ``services`` list for view-scoped Flet services.

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
        on_state_change: Optional callback invoked after asynchronous home
            operations update state, allowing the active route to be rebuilt.
        on_login_submit: Callback invoked with the raw secret when the login
            form is submitted (used only while ``state.screen`` is ``LOGIN``).

    Returns:
        A configured :class:`ft.View` for the resolved screen/route.
    """
    # Gate the app behind the login screen until a shared secret is configured
    # (Requirements 5.1, 6.2). No navigation bar is shown so the front page and
    # its sibling screens stay withheld.
    if state.screen is Screen.LOGIN:
        return ft.View(
            route=route if route is not None else ROUTE_HOME,
            controls=[
                build_login_view(
                    page,
                    on_login_submit
                    if on_login_submit is not None
                    else (lambda _s: None),
                    auth_rejected=state.auth_rejected,
                )
            ],
            services=list(services) if services else [],
        )

    resolved = resolve_initial_route(route)

    if resolved == ROUTE_SUMMARY:
        body: ft.Control = build_summary_view(
            state.compliance_summary,
            state.annual_summary,
        )
    elif resolved == ROUTE_SETTINGS:
        body = build_settings_view(
            page,
            storage,
            current_value=api_client.base_url,
            on_saved=on_settings_saved,
        )
    else:
        body = build_home_view(page, state, api_client, on_state_change=on_state_change)

    return ft.View(
        route=resolved,
        controls=[body],
        navigation_bar=_build_navigation_bar(page, resolved),
        services=list(services) if services else [],
    )


def initial_render(
    page: ft.Page,
    state: AppState,
    api_client: APIClient,
    storage: KeyValueStorage,
    *,
    route: str | None = None,
    services: list[ft.Service] | None = None,
    on_settings_saved=None,
    on_state_change=None,
    on_login_submit=None,
) -> None:
    """Render the view for ``route`` directly into ``page.views``.

    This is the single, runtime-free rendering primitive used for both the
    startup paint and every subsequent route change. It clears ``page.views``,
    appends exactly one :func:`build_view` for
    ``resolve_initial_route(route or page.route)``, and calls ``page.update()``.

    Calling this directly at startup (rather than relying on
    ``page.navigate`` / ``page.push_route``) guarantees the first view is built
    and shown even when the target route equals the current route — the usual
    launch case (``"/"``) in which Flet 1.0.2 may not fire ``on_route_change``,
    leaving the window blank. Flet 1.0.2 ``Page`` instances expose a ``views``
    list (a dataclass field) even though ``hasattr(ft.Page, "views")`` is
    ``False`` at the class level, so ``page.views`` is safe to mutate here.

    Args:
        page: The active Flet page (or a test double exposing ``views`` and
            ``update``).
        state: The shared in-memory :class:`AppState`.
        api_client: The backend :class:`APIClient`.
        storage: The async key-value storage service for the settings screen.
        route: The route to render; defaults to ``page.route`` when ``None``.
        services: Optional Flet services to mount on the view.
        on_settings_saved: Optional callback forwarded to the settings view.
        on_state_change: Optional callback forwarded to the home view and
            invoked after asynchronous home-view state changes so the active
            route can be repainted.
        on_login_submit: Optional callback forwarded to the login view and
            invoked with the raw secret on submit while the app is gated.
    """
    target = route if route is not None else page.route
    page.views.clear()
    page.views.append(
        build_view(
            page,
            resolve_initial_route(target),
            state,
            api_client,
            storage,
            services=services,
            on_settings_saved=on_settings_saved,
            on_state_change=on_state_change,
            on_login_submit=on_login_submit,
        )
    )
    page.update()


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
    rebuilds ``page.views`` for the active route.

    The first paint is performed **directly** by calling :func:`initial_render`
    once at startup, rather than via ``page.navigate`` / ``page.push_route``. In
    Flet 1.0.2 ``page.navigate(route)`` only schedules
    ``asyncio.create_task(page.push_route(route))``, which round-trips to the
    client; when the target route equals the current route (the usual launch
    case, ``"/"``) ``on_route_change`` may never fire, so the view is never
    built and the window stays blank. Rendering directly guarantees the first
    view is shown. ``on_route_change`` then handles every subsequent navigation
    (NavigationBar taps call ``page.navigate(target)`` to a *different* route).
    """
    page.title = "Work Location Tracker"
    page.theme_mode = ft.ThemeMode.SYSTEM

    storage = ft.SharedPreferences()
    page.services = [storage]
    page.update()

    base_url = await resolve_base_url(storage=storage)
    state = AppState(selected_month=_first_of_this_month())
    api_client = APIClient(base_url)

    # Centralise shared-secret recovery (Requirements 8.1, 8.2, 8.3). Every
    # background coroutine in the app is scheduled through ``page.run_task``
    # (home-view log/navigate/edit/delete, settings reset, login unlock). Rather
    # than teach each call site to catch ``AuthError``, wrap ``page.run_task``
    # once here so any coroutine it schedules is guarded: when the backend
    # rejects the secret with a ``401`` the client raises ``AuthError``, which
    # bubbles out of the task and is caught by the wrapper, which clears the
    # secret, flips to the login screen (:func:`handle_auth_error`) and
    # repaints. The wrapper preserves ``run_task``'s contract — the handler must
    # be a coroutine function, called with the forwarded args — so existing call
    # sites are unaffected. ``api_client`` is read at call time so a backend
    # switch (settings save rebinds it) uses the live client.
    _page_run_task = page.run_task

    def _guarded_run_task(handler, *args, **kwargs):
        async def _guarded() -> None:
            try:
                await handler(*args, **kwargs)
            except AuthError:
                await handle_auth_error(state, api_client, storage)
                _render(ROUTE_HOME)

        return _page_run_task(_guarded)

    page.run_task = _guarded_run_task  # type: ignore[method-assign]

    def _on_settings_saved(new_url: str) -> None:
        # Rebuild the client against the newly saved URL so later requests use
        # it immediately. When the URL genuinely changed, discard state fetched
        # from the old backend and reload the selected month against the new
        # client before any edit/delete can target it with a stale ID (Fix 1).
        nonlocal api_client
        normalised_new = new_url.rstrip("/")
        url_changed = normalised_new != api_client.base_url
        api_client = APIClient(new_url)

        if not url_changed:
            # Same backend: nothing stale to discard, just repaint.
            _render(page.route)
            return

        async def _reset_and_render() -> None:
            await reset_for_new_backend(state, api_client)
            _render(page.route)

        page.run_task(_reset_and_render)

    def _on_login_submit(raw_secret: str) -> None:
        # Login submit handler (Requirements 5.3, 5.4). ``build_login_view``
        # has already validated the input is non-empty before calling this, so
        # here we persist the (trimmed) secret, configure the client to attach
        # it as the ``X-API-Key`` header on every request, load the initial
        # month's data, flip to the HOME screen, and repaint. Empty/blank input
        # never reaches this callback — the login view keeps the user on the
        # login screen with a validation message instead (Requirement 5.4).
        async def _unlock() -> None:
            secret = await save_secret(storage, raw_secret)
            api_client.set_secret(secret)
            state.auth_rejected = False
            await _load_initial_data(state, api_client)
            state.screen = Screen.HOME
            _render(ROUTE_HOME)

        page.run_task(_unlock)

    def _render(route: str | None) -> None:
        # Delegate to the shared, runtime-free rendering primitive, forwarding
        # the explicit route so same-URL repaints (settings save) and route
        # changes render exactly the route they were given. ``on_state_change``
        # repaints the active route after asynchronous home-view updates.
        initial_render(
            page,
            state,
            api_client,
            storage,
            route=route,
            services=[storage],
            on_settings_saved=_on_settings_saved,
            on_state_change=lambda: _render(page.route),
            on_login_submit=_on_login_submit,
        )

    # Idempotency guard for the initial paint. Startup renders the first view
    # DIRECTLY (see below), but in some Flet versions ``on_route_change`` *also*
    # fires at launch for that same route. Without a guard the first view would
    # build twice — harmless to display, but it kicks off a duplicate set of
    # initial data loads.
    #
    # The guard makes the *first* initial-route paint happen exactly once,
    # whichever path reaches it first (a launch-time ``on_route_change`` during
    # the ``_load_initial_data`` await, or the direct render afterwards), and
    # suppresses the other. Every genuine navigation (any other route, or a
    # change after the initial paint) renders normally.
    initial_route = resolve_initial_route(page.route)
    initial_render_done = False

    def _render_initial(route: str) -> None:
        # Paint the initial view at most once. The first caller wins; a second
        # launch-time call for the same startup route is a no-op.
        nonlocal initial_render_done
        if initial_render_done:
            return
        initial_render_done = True
        _render(route)

    def _on_route_change(e: ft.RouteChangeEvent) -> None:
        nonlocal initial_render_done
        if not initial_render_done and e.route == initial_route:
            # Launch-time echo of the initial route: perform the one initial
            # paint through the guarded path rather than re-rendering.
            _render_initial(e.route)
            return
        initial_render_done = True
        _render(e.route)

    page.on_route_change = _on_route_change

    # Resolve the gated screen from the stored shared secret before the first
    # paint (Requirements 5.1, 5.2, 6.2). When a usable secret is remembered,
    # configure the client to attach it as the ``X-API-Key`` header and load
    # the initial month's data so the home screen opens populated. When none is
    # stored, stay on the login screen and skip the initial load entirely so no
    # entry/summary requests are issued without a secret (Requirement 6.2).
    stored_secret = await load_secret(storage)
    state.screen = resolve_initial_screen(stored_secret)
    if state.screen is Screen.HOME:
        api_client.set_secret(stored_secret)
        await _load_initial_data(state, api_client)

    # Perform the initial render DIRECTLY (not via page.navigate). This builds
    # and shows the first view regardless of whether on_route_change fires,
    # which it may not when the launch route already equals the current route
    # ("/"). The guard ensures the first view is built exactly once even if a
    # launch-time on_route_change for the same route also arrives.
    _render_initial(initial_route)


async def _load_initial_data(state: AppState, api_client: APIClient) -> None:
    """Best-effort load of the current month's entries, summary and annual summary.

    Failures are swallowed so the UI still renders (an empty calendar) when the
    backend is unreachable at launch; the home screen's own error handling
    surfaces subsequent failures. The annual summary is loaded via
    :func:`load_annual_summary` so the summary screen opens populated too.
    """
    from app.views.home_view import load_month

    await load_month(
        state,
        api_client,
        state.selected_month.year,
        state.selected_month.month,
    )
    await load_annual_summary(state, api_client)


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
