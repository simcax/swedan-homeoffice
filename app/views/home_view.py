"""Main calendar screen for the work-location-tracker app (task 12.1).

``build_home_view`` assembles the home screen: a compliance progress bar, the
four quick-log buttons (Denmark / Home / Vacation / Sick), month-navigation
arrows, and the monthly calendar grid. The screen reads everything it renders
from an :class:`app.state.AppState` instance and talks to the backend through
an :class:`app.api_client.APIClient`.

Business logic is kept out of the Flet event handlers so it can be tested
without starting the Flet runtime (see ``log_entry`` and ``load_month``). The
event handlers are thin wrappers that run the coroutine, rebuild the affected
controls, and call ``page.update()``.

Behaviour summary (Requirements 1.1, 1.4, 1.5, 2.3, 2.4, 2.5, 8.1, 8.2, 13.1,
13.5, 13.6, 14.1, 14.5, 14.6):

* Tapping a log button POSTs the entry for *today*, applies it to
  ``state.entries``, refreshes ``state.compliance_summary``, and repaints.
* A backend failure leaves ``state.entries`` untouched and surfaces an inline
  error message (the calendar state is preserved).
* A future-date rejection (HTTP 422) shows an error adjacent to the date and
  adds nothing to ``state.entries``.
* The month-navigation arrows reload entries (and the summary) for the newly
  selected month via ``api_client.get_entries`` / ``get_summary``.

Edit/delete flow (task 12.3, Requirements 3.1, 3.5, 3.6, 4.1, 4.2, 4.5, 4.6):

* Long-pressing a *logged* calendar tile opens an ``ft.AlertDialog`` offering
  Edit and Delete.
* Delete first shows a confirmation dialog; confirming sends a DELETE. On
  success the tile is cleared and the summary refreshed; on error a snack bar
  is shown and the tile/state is kept.
* Edit shows a location-picker dialog; confirming sends a PATCH. On success the
  tile is updated and the summary refreshed; on error a snack bar is shown and
  the state is kept.

As with ``log_entry`` / ``load_month``, the delete/edit business logic lives in
runtime-free coroutines (``delete_entry`` / ``edit_entry``) so it can be tested
with a mocked ``api_client``; the dialog builders are thin Flet wrappers.

Requirements: 1.1, 1.4, 1.5, 2.3, 2.4, 2.5, 3.1, 3.5, 3.6, 4.1, 4.2, 4.5, 4.6,
8.1, 8.2, 13.1, 13.5, 13.6, 14.1, 14.5, 14.6
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import Enum, auto

import flet as ft
import httpx

from app.api_client import APIClient, APIError, WorkEntry, WorkLocation
from app.components.calendar_grid import build_calendar_grid
from app.components.compliance_bar import build_compliance_bar
from app.state import AppState

# Button background colour per location (Requirements 8.2, 13.5, 14.5). These
# mirror the calendar tile colours so the quick-log buttons read as the same
# "language" as the grid.
_BUTTON_COLORS: dict[WorkLocation, str] = {
    WorkLocation.DENMARK: ft.Colors.RED_700,
    WorkLocation.HOME: ft.Colors.BLUE_700,
    WorkLocation.VACATION: ft.Colors.ORANGE_700,
    WorkLocation.SICK: ft.Colors.PURPLE_700,
}

# Human-readable labels for the quick-log buttons.
_BUTTON_LABELS: dict[WorkLocation, str] = {
    WorkLocation.DENMARK: "Office / Denmark",
    WorkLocation.HOME: "Work from Home",
    WorkLocation.VACATION: "Vacation",
    WorkLocation.SICK: "Sick Day",
}

# Order the buttons are rendered in.
_BUTTON_ORDER: tuple[WorkLocation, ...] = (
    WorkLocation.DENMARK,
    WorkLocation.HOME,
    WorkLocation.VACATION,
    WorkLocation.SICK,
)


# ---------------------------------------------------------------------------
# status-code detection
# ---------------------------------------------------------------------------


def _status_code(error: APIError) -> int | None:
    """Return the HTTP status wrapped by ``error``, if any.

    ``APIClient`` raises :class:`APIError` from an underlying
    ``httpx.HTTPStatusError`` whenever the backend returns a 4xx/5xx. The
    original response (and therefore its status code) is reachable through the
    exception's ``__cause__`` chain.
    """
    cause = error.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        return cause.response.status_code
    return None


def _is_timeout_or_network(error: APIError) -> bool:
    """Return ``True`` when ``error`` was caused by a timeout/connection fault.

    ``APIClient`` wraps ``httpx.TimeoutException`` and other transport-level
    ``httpx.HTTPError`` failures (connection refused, DNS, etc.) in an
    :class:`APIError`. These have no HTTP status code — the request never got a
    response — so they are distinguished from status-coded failures by the type
    of the wrapped cause.
    """
    cause = error.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        return False
    return isinstance(cause, httpx.HTTPError)


# ---------------------------------------------------------------------------
# API error classification (Requirement 9.1-9.6)
# ---------------------------------------------------------------------------


class ErrorAction(Enum):
    """The user-facing reaction an :class:`APIError` should trigger.

    Each value maps a backend/transport failure onto exactly one UI behaviour,
    keeping the mapping in one testable place (Requirement 9.1-9.6):

    * ``INLINE`` - a validation message shown inline next to the form; form and
      calendar values are retained and no navigation occurs (HTTP 422,
      Requirement 9.1).
    * ``SNACKBAR_REFRESH`` - a transient ``ft.SnackBar`` toast *and* a reload of
      the current month's entry list (HTTP 404, Requirement 9.2).
    * ``BANNER`` - a persistent connection banner; form values are retained and
      no navigation occurs (network timeout / connection error,
      Requirement 9.4).
    * ``NOTIFICATION`` - an error notification with no state change, used when
      the ``APIClient`` has already exhausted its own retries (409 PATCH retry
      failed, Requirement 9.3; 503 back-off exhausted, Requirement 9.6; and any
      other unhandled status).
    """

    INLINE = auto()
    SNACKBAR_REFRESH = auto()
    BANNER = auto()
    NOTIFICATION = auto()


@dataclass(frozen=True)
class ClassifiedError:
    """The result of classifying an :class:`APIError`.

    Attributes:
        action: The :class:`ErrorAction` the view should perform.
        message: A ready-to-display, user-facing message.
    """

    action: ErrorAction
    message: str


def classify_error(error: APIError, *, context: str | None = None) -> ClassifiedError:
    """Map an :class:`APIError` to the UI reaction required by Requirement 9.

    The classification is a pure function of the error (and an optional
    human-readable ``context`` string folded into some messages) so it can be
    unit-tested without the Flet runtime. Status detection reuses
    :func:`_status_code`, and timeout/connection faults are detected via
    :func:`_is_timeout_or_network`.

    Args:
        error: The :class:`APIError` raised by the :class:`APIClient`.
        context: Optional context (e.g. an ISO date) woven into the message.

    Returns:
        A :class:`ClassifiedError` carrying the action and message.
    """
    status = _status_code(error)

    # 422 - inline validation message; retain values, no navigation (9.1).
    if status == 422:
        if context:
            return ClassifiedError(
                ErrorAction.INLINE,
                f"Cannot log a future date ({context}).",
            )
        return ClassifiedError(
            ErrorAction.INLINE,
            "That value is not valid. Please check the entry and try again.",
        )

    # 404 - toast + refresh the entry list (9.2).
    if status == 404:
        return ClassifiedError(
            ErrorAction.SNACKBAR_REFRESH,
            "That entry no longer exists. Refreshing the calendar.",
        )

    # Network timeout / connection error - banner, retain values (9.4).
    if _is_timeout_or_network(error):
        return ClassifiedError(
            ErrorAction.BANNER,
            "Could not connect. Check your connection and try again.",
        )

    # 409 PATCH-retry exhausted (9.3), 503 back-off exhausted (9.6), or any
    # other unhandled status - error notification, no state change.
    return ClassifiedError(
        ErrorAction.NOTIFICATION,
        "Something went wrong talking to the server. Please try again.",
    )


def _record_error(state: AppState, classified: ClassifiedError) -> None:
    """Store ``classified`` on ``state`` for the view layer to surface.

    The message is written to ``state.error_message`` (used by the inline error
    text) and the chosen surface to ``state.error_action`` so the Flet wrapper
    can decide whether to render the message inline, as a banner, as a snack
    bar, or as a notification.
    """
    state.error_message = classified.message
    state.error_action = classified.action


# ---------------------------------------------------------------------------
# business logic (pure of the Flet runtime, so it is directly testable)
# ---------------------------------------------------------------------------


def _is_superseded(state: AppState, generation: int | None) -> bool:
    """Return ``True`` when ``generation`` no longer matches the current backend.

    Load and mutation coroutines capture ``state.backend_generation`` when they
    start and pass it here as ``generation`` immediately before committing
    results. When a backend switch bumped ``state.backend_generation`` while the
    network request was in flight, the captured value no longer matches and the
    write must be skipped so results fetched from the old backend never land in
    state (closing the temporal race in :func:`app.main.reset_for_new_backend`).

    When ``generation`` is ``None`` the guard is disabled and this always
    returns ``False``, so existing call sites that do not opt in keep their
    previous behaviour.

    Args:
        state: The shared in-memory :class:`AppState`.
        generation: The backend generation captured at the start of the request,
            or ``None`` to disable the guard.

    Returns:
        ``True`` when the write should be skipped, ``False`` otherwise.
    """
    return generation is not None and state.backend_generation != generation


async def _refresh_annual(
    state: AppState,
    api_client: APIClient,
    *,
    generation: int | None = None,
) -> None:
    """Best-effort refresh of the annual summary for the selected year.

    Fetches ``api_client.get_annual_summary`` for ``state.selected_month.year``
    and stores it on ``state.annual_summary`` so the summary screen stays fresh
    after mutations and cross-year navigation (Fix 2). Any :class:`APIError` is
    swallowed and the previous value is kept, mirroring the monthly summary
    refresh, so a failed annual refresh never fails the triggering operation.

    The write is guarded by :func:`_is_superseded`: when ``generation`` is given
    and no longer matches ``state.backend_generation`` the result is discarded.
    A local helper (rather than importing :func:`app.main.load_annual_summary`)
    keeps ``home_view`` free of a ``home_view → main`` import cycle.

    Args:
        state: The shared in-memory :class:`AppState` to populate.
        api_client: The backend :class:`APIClient` to fetch from.
        generation: Optional backend generation guarding the write.
    """
    try:
        annual = await api_client.get_annual_summary(state.selected_month.year)
    except APIError:
        return

    if _is_superseded(state, generation):
        return

    state.annual_summary = annual


async def log_entry(
    state: AppState,
    api_client: APIClient,
    location: WorkLocation,
    work_date: date | None = None,
    *,
    generation: int | None = None,
) -> bool:
    """Log ``location`` for ``work_date`` (defaults to today) and update state.

    On success the new entry is applied to ``state.entries``, the compliance
    summary for the selected month is refreshed, the annual summary is refreshed
    best-effort (Fix 2), and any previous error is cleared; the method returns
    ``True``.

    On failure ``state.entries`` is left untouched (the calendar state is
    preserved, Requirements 1.5 / 13.6 / 14.6) and ``state.error_message`` is
    populated; the method returns ``False``. A future-date rejection (HTTP 422,
    Requirements 2.3 / 2.4 / 2.5) is reported with a date-adjacent message and,
    like every failure, adds nothing to ``state.entries``.

    When ``generation`` is given it is re-checked against
    ``state.backend_generation`` immediately before writing results; a mismatch
    means the backend changed mid-request, so the write is skipped and the
    method returns ``False`` (Fix A). ``generation=None`` disables the guard.
    """
    target = work_date or date.today()  # noqa: DTZ011
    iso_date = target.isoformat()

    try:
        entry = await api_client.post_entry(iso_date, location)
    except APIError as exc:
        # Only report a 422 as a future-date rejection when the resolved target
        # date is actually in the future; otherwise the context would make
        # every validation error read as "Cannot log a future date". For any
        # other 422 fall back to the generic validation message.
        is_future = target > date.today()  # noqa: DTZ011
        context = iso_date if is_future else None
        if _is_superseded(state, generation):
            return False
        _record_error(state, classify_error(exc, context=context))
        return False

    # Guard the write: a backend switch during the request invalidates results.
    if _is_superseded(state, generation):
        return False

    # Success: apply the entry and refresh the compliance indicator.
    state.apply_entry(entry)
    state.clear_error()

    try:
        summary = await api_client.get_summary(
            state.selected_month.year,
            state.selected_month.month,
        )
    except APIError:
        # The entry was saved; only the summary refresh failed. Keep the entry
        # and surface a non-destructive notice.
        state.error_message = "Entry saved, but the compliance summary is stale."
    else:
        if not _is_superseded(state, generation):
            state.compliance_summary = summary

    await _refresh_annual(state, api_client, generation=generation)

    return True


async def delete_entry(
    state: AppState,
    api_client: APIClient,
    entry: WorkEntry,
    *,
    generation: int | None = None,
) -> bool:
    """Delete ``entry`` from the backend and clear its tile from state.

    On success the entry is removed from ``state.entries`` so its calendar tile
    renders as unlogged (Requirements 4.2, 4.5), the compliance summary for the
    selected month is refreshed, the annual summary is refreshed best-effort
    (Fix 2), and any previous error is cleared; the method returns ``True``.

    On failure the entry is left in ``state.entries`` so the tile stays visible
    (Requirement 4.6) and ``state.error_message`` is populated; the method
    returns ``False``.

    When ``generation`` is given it is re-checked against
    ``state.backend_generation`` immediately before writing results; a mismatch
    means the backend changed mid-request, so the write is skipped and the
    method returns ``False`` (Fix A). ``generation=None`` disables the guard.
    """
    try:
        await api_client.delete_entry(entry.id)
    except APIError as exc:
        if _is_superseded(state, generation):
            return False
        _record_error(state, classify_error(exc))
        return False

    # Guard the write: a backend switch during the request invalidates results.
    if _is_superseded(state, generation):
        return False

    # Success: clear the tile and refresh the compliance indicator.
    state.entries.pop(entry.work_date.isoformat(), None)
    state.clear_error()

    try:
        summary = await api_client.get_summary(
            state.selected_month.year,
            state.selected_month.month,
        )
    except APIError:
        state.error_message = "Entry deleted, but the compliance summary is stale."
    else:
        if not _is_superseded(state, generation):
            state.compliance_summary = summary

    await _refresh_annual(state, api_client, generation=generation)

    return True


async def edit_entry(
    state: AppState,
    api_client: APIClient,
    entry: WorkEntry,
    location: WorkLocation,
    *,
    generation: int | None = None,
) -> bool:
    """Change ``entry``'s location to ``location`` via PATCH and update state.

    On success the updated entry replaces the previous one in ``state.entries``
    (its ``work_date`` is unchanged, Requirements 3.2, 3.5), the compliance
    summary for the selected month is refreshed, the annual summary is refreshed
    best-effort (Fix 2), and any previous error is cleared; the method returns
    ``True``.

    On failure ``state.entries`` is left untouched so the calendar state is
    preserved (Requirement 3.6) and ``state.error_message`` is populated; the
    method returns ``False``.

    When ``generation`` is given it is re-checked against
    ``state.backend_generation`` immediately before writing results; a mismatch
    means the backend changed mid-request, so the write is skipped and the
    method returns ``False`` (Fix A). ``generation=None`` disables the guard.
    """
    try:
        updated = await api_client.patch_entry(entry.id, location)
    except APIError as exc:
        if _is_superseded(state, generation):
            return False
        _record_error(state, classify_error(exc))
        return False

    # Guard the write: a backend switch during the request invalidates results.
    if _is_superseded(state, generation):
        return False

    # Success: apply the updated entry and refresh the compliance indicator.
    state.apply_entry(updated)
    state.clear_error()

    try:
        summary = await api_client.get_summary(
            state.selected_month.year,
            state.selected_month.month,
        )
    except APIError:
        state.error_message = "Entry updated, but the compliance summary is stale."
    else:
        if not _is_superseded(state, generation):
            state.compliance_summary = summary

    await _refresh_annual(state, api_client, generation=generation)

    return True


async def load_month(
    state: AppState,
    api_client: APIClient,
    year: int,
    month: int,
    *,
    generation: int | None = None,
) -> bool:
    """Load entries and the compliance summary for ``year``/``month``.

    Updates ``state.selected_month`` and replaces ``state.entries`` with the
    freshly fetched month on success (Requirement 1.4). On failure the existing
    calendar grid is preserved (Requirement 5.5) and ``state.error_message`` is
    populated; the method returns ``False``.

    When navigation crosses into a different year the annual summary is
    refreshed best-effort for the new year so the summary screen stays accurate
    (Fix 2). That refresh never affects the ``True`` returned on the primary
    (entries + monthly summary) success.

    When ``generation`` is given it is re-checked against
    ``state.backend_generation`` immediately before writing results; a mismatch
    means the backend changed mid-request, so the write is skipped and the
    method returns ``False`` (Fix A). ``generation=None`` disables the guard.
    """
    try:
        entries = await api_client.get_entries(year, month)
        summary = await api_client.get_summary(year, month)
    except APIError as exc:
        if _is_superseded(state, generation):
            return False
        _record_error(state, classify_error(exc))
        return False

    # Guard the write: a backend switch during the request invalidates results.
    if _is_superseded(state, generation):
        return False

    year_changed = year != state.selected_month.year

    state.selected_month = date(year, month, 1)
    state.entries = {entry.work_date.isoformat(): entry for entry in entries}
    state.compliance_summary = summary
    state.clear_error()

    # Crossing into a different year makes the cached annual summary stale;
    # refresh it best-effort for the newly selected year (Fix 2).
    if year_changed:
        await _refresh_annual(state, api_client, generation=generation)

    return True


def _shift_month(selected: date, delta: int) -> tuple[int, int]:
    """Return the ``(year, month)`` ``delta`` months away from ``selected``."""
    # Convert to a zero-based month index, shift, then convert back.
    index = (selected.year * 12 + (selected.month - 1)) + delta
    return index // 12, index % 12 + 1


# ---------------------------------------------------------------------------
# view builder
# ---------------------------------------------------------------------------


def build_home_view(
    page: ft.Page,
    state: AppState,
    api_client: APIClient,
) -> ft.Container:
    """Build the home calendar screen.

    Args:
        page: The active Flet page; used to schedule async work and repaint.
        state: The shared in-memory :class:`AppState`.
        api_client: The backend :class:`APIClient`.

    Returns:
        An :class:`ft.Container` holding the compliance bar, quick-log buttons,
        month navigation, and the calendar grid.
    """
    compliance_bar = build_compliance_bar(state.compliance_summary)
    error_text = ft.Text(
        state.error_message or "",
        color=ft.Colors.RED_700,
        visible=bool(state.error_message),
    )
    month_label = ft.Text(_month_title(state.selected_month), weight=ft.FontWeight.BOLD)

    def _on_day_long_press(day: int) -> None:
        _handle_long_press(page, state, api_client, day, _refresh)

    calendar_holder = ft.Container(content=_build_grid(state, _on_day_long_press))

    def _refresh() -> None:
        """Rebuild every stateful control from ``state`` and repaint."""
        new_bar = build_compliance_bar(state.compliance_summary)
        compliance_bar.value = new_bar.value
        compliance_bar.color = new_bar.color
        compliance_bar.tooltip = new_bar.tooltip

        # The inline error text only carries INLINE (422) validation messages;
        # banners, toasts and notifications use their own surfaces so they do
        # not duplicate the message in the form area (Requirement 9.1).
        inline = bool(state.error_message) and state.error_action in (
            None,
            ErrorAction.INLINE,
        )
        error_text.value = state.error_message if inline else ""
        error_text.visible = inline

        month_label.value = _month_title(state.selected_month)
        calendar_holder.content = _build_grid(state, _on_day_long_press)
        page.update()

    def _surface_error(ok: bool) -> None:
        """Show the right UI surface for the latest error after an operation.

        No-op when the operation succeeded or there is no classified error.
        ``INLINE`` errors are already drawn by ``_refresh`` via ``error_text``,
        so only banner / snackbar+refresh / notification surfaces are handled
        here (Requirement 9.2, 9.3, 9.4, 9.6).
        """
        if ok or state.error_action is None:
            return
        _dispatch_error_surface(page, state, api_client, _refresh)

    def _on_log_click(location: WorkLocation) -> None:
        async def _task() -> None:
            # Capture the backend era at task start so a mid-request backend
            # switch invalidates this write (Fix A).
            gen = state.backend_generation
            ok = await log_entry(state, api_client, location, generation=gen)
            _refresh()
            _surface_error(ok)

        page.run_task(_task)

    def _on_navigate(delta: int) -> None:
        async def _task() -> None:
            gen = state.backend_generation
            year, month = _shift_month(state.selected_month, delta)
            ok = await load_month(state, api_client, year, month, generation=gen)
            _refresh()
            _surface_error(ok)

        page.run_task(_task)

    log_buttons = ft.Row(
        controls=[_log_button(loc, _on_log_click) for loc in _BUTTON_ORDER],
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=10,
        wrap=True,
    )

    nav_row = ft.Row(
        controls=[
            ft.IconButton(
                icon=ft.Icons.CHEVRON_LEFT,
                tooltip="Previous month",
                on_click=lambda _e: _on_navigate(-1),
            ),
            month_label,
            ft.IconButton(
                icon=ft.Icons.CHEVRON_RIGHT,
                tooltip="Next month",
                on_click=lambda _e: _on_navigate(1),
            ),
        ],
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=16,
    )

    return ft.Container(
        content=ft.Column(
            controls=[
                compliance_bar,
                error_text,
                log_buttons,
                nav_row,
                calendar_holder,
            ],
            spacing=16,
            expand=True,
        ),
        padding=16,
        expand=True,
    )


# ---------------------------------------------------------------------------
# small builders
# ---------------------------------------------------------------------------


def _month_title(selected: date) -> str:
    """Return a human-readable ``"Month YYYY"`` title for the header."""
    return f"{calendar.month_name[selected.month]} {selected.year}"


def _build_grid(
    state: AppState,
    on_day_long_press: Callable[[int], None] | None = None,
) -> ft.GridView:
    """Build the calendar grid for the currently selected month.

    ``on_day_long_press`` is forwarded to :func:`build_calendar_grid` so each
    logged tile can open the edit/delete menu on long-press.
    """
    return build_calendar_grid(
        state.selected_month.year,
        state.selected_month.month,
        state.entries,
        on_day_long_press,
    )


def _log_button(location: WorkLocation, on_click) -> ft.Button:
    """Build a single colour-coded quick-log button for ``location``."""
    return ft.Button(
        content=ft.Text(_BUTTON_LABELS[location]),
        color=ft.Colors.WHITE,
        bgcolor=_BUTTON_COLORS[location],
        on_click=lambda _e, loc=location: on_click(loc),
        data=location,
    )


# ---------------------------------------------------------------------------
# edit / delete flow (task 12.3)
# ---------------------------------------------------------------------------


def _show_snack(page: ft.Page, message: str, *, color: str) -> None:
    """Show a snack bar with ``message`` (Flet 1.0.2 ``page.show_dialog`` API)."""
    page.show_dialog(
        ft.SnackBar(content=ft.Text(message, color=ft.Colors.WHITE), bgcolor=color)
    )


def _build_banner(page: ft.Page, message: str) -> ft.Banner:
    """Build a connection-failure banner with a Dismiss action.

    Used for network timeout / connection errors (Requirement 9.4). The banner
    is a persistent surface (distinct from the transient snack bar) that keeps
    the message visible until the user dismisses it, while the underlying form
    values and calendar state are retained.
    """
    return ft.Banner(
        bgcolor=ft.Colors.RED_100,
        leading=ft.Icon(ft.Icons.WIFI_OFF, color=ft.Colors.RED_700),
        content=ft.Text(message, color=ft.Colors.RED_900),
        actions=[ft.TextButton("Dismiss", on_click=lambda _e: page.pop_dialog())],
    )


def _dispatch_error_surface(
    page: ft.Page,
    state: AppState,
    api_client: APIClient,
    refresh: Callable[[], None],
) -> None:
    """Render the UI surface matching ``state.error_action``.

    Maps the classified error onto its surface (Requirement 9.2, 9.3, 9.4,
    9.6):

    * ``SNACKBAR_REFRESH`` - show a toast and reload the current month so the
      stale entry list is refreshed (404).
    * ``BANNER`` - open a persistent connection banner (timeout / network).
    * ``NOTIFICATION`` - open an error snack bar with no state change
      (409/503 after the client exhausted its retries, or any other status).

    ``INLINE`` is intentionally not handled here; it is drawn by the inline
    error text during ``refresh``.
    """
    action = state.error_action
    message = state.error_message or "Something went wrong. Please try again."

    if action is ErrorAction.SNACKBAR_REFRESH:
        _show_snack(page, message, color=ft.Colors.RED_700)

        async def _reload() -> None:
            await load_month(
                state,
                api_client,
                state.selected_month.year,
                state.selected_month.month,
            )
            refresh()

        page.run_task(_reload)
    elif action is ErrorAction.BANNER:
        page.show_dialog(_build_banner(page, message))
    elif action is ErrorAction.NOTIFICATION:
        _show_snack(page, message, color=ft.Colors.RED_700)


def _handle_long_press(
    page: ft.Page,
    state: AppState,
    api_client: APIClient,
    day: int,
    refresh: Callable[[], None],
) -> None:
    """Open the edit/delete menu for the logged entry on ``day``.

    When the long-pressed tile has no logged entry there is nothing to edit or
    delete, so the menu is not shown.
    """
    iso_date = date(
        state.selected_month.year, state.selected_month.month, day
    ).isoformat()
    entry = state.entries.get(iso_date)
    if entry is None:
        return

    _open_action_dialog(page, state, api_client, entry, refresh)


def _open_action_dialog(
    page: ft.Page,
    state: AppState,
    api_client: APIClient,
    entry: WorkEntry,
    refresh: Callable[[], None],
) -> None:
    """Show the ``Edit`` / ``Delete`` chooser for ``entry`` (Requirement 3.1)."""
    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(f"Entry for {entry.work_date.isoformat()}"),
        content=ft.Text("What would you like to do with this entry?"),
    )

    def _edit(_e: ft.ControlEvent) -> None:
        page.pop_dialog()
        _open_edit_dialog(page, state, api_client, entry, refresh)

    def _delete(_e: ft.ControlEvent) -> None:
        page.pop_dialog()
        _open_delete_confirm(page, state, api_client, entry, refresh)

    dialog.actions = [
        ft.TextButton("Cancel", on_click=lambda _e: page.pop_dialog()),
        ft.TextButton("Edit", on_click=_edit),
        ft.TextButton("Delete", on_click=_delete),
    ]
    page.show_dialog(dialog)


def _open_delete_confirm(
    page: ft.Page,
    state: AppState,
    api_client: APIClient,
    entry: WorkEntry,
    refresh: Callable[[], None],
) -> None:
    """Confirm deletion before sending DELETE (Requirement 4.1)."""
    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Delete entry?"),
        content=ft.Text(
            f"Delete the entry for {entry.work_date.isoformat()}? "
            "This cannot be undone."
        ),
    )

    def _confirm(_e: ft.ControlEvent) -> None:
        page.pop_dialog()

        async def _task() -> None:
            # Capture the backend era so a mid-request switch is dropped (Fix A).
            gen = state.backend_generation
            ok = await delete_entry(state, api_client, entry, generation=gen)
            refresh()
            if ok:
                _show_snack(page, "Entry deleted.", color=ft.Colors.GREEN_700)
            else:
                _dispatch_error_surface(page, state, api_client, refresh)

        page.run_task(_task)

    dialog.actions = [
        ft.TextButton("Cancel", on_click=lambda _e: page.pop_dialog()),
        ft.TextButton("Delete", on_click=_confirm),
    ]
    page.show_dialog(dialog)


def _open_edit_dialog(
    page: ft.Page,
    state: AppState,
    api_client: APIClient,
    entry: WorkEntry,
    refresh: Callable[[], None],
) -> None:
    """Show a location picker and PATCH the chosen value (Requirement 3.1)."""

    def _pick(location: WorkLocation) -> None:
        page.pop_dialog()

        async def _task() -> None:
            # Capture the backend era so a mid-request switch is dropped (Fix A).
            gen = state.backend_generation
            ok = await edit_entry(state, api_client, entry, location, generation=gen)
            refresh()
            if ok:
                _show_snack(page, "Entry updated.", color=ft.Colors.GREEN_700)
            else:
                _dispatch_error_surface(page, state, api_client, refresh)

        page.run_task(_task)

    options = ft.Column(
        controls=[_picker_button(loc, _pick) for loc in _BUTTON_ORDER],
        tight=True,
        spacing=8,
    )

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Change location"),
        content=options,
        actions=[],
    )
    dialog.actions = [ft.TextButton("Cancel", on_click=lambda _e: page.pop_dialog())]
    page.show_dialog(dialog)


def _picker_button(location: WorkLocation, on_pick: Callable[[WorkLocation], None]):
    """Build a colour-coded picker button for the edit dialog."""
    return ft.Button(
        content=ft.Text(_BUTTON_LABELS[location]),
        color=ft.Colors.WHITE,
        bgcolor=_BUTTON_COLORS[location],
        on_click=lambda _e, loc=location: on_pick(loc),
        data=location,
    )
