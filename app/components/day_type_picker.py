"""Day-type picker dialog for the monthly calendar grid.

Tapping any past-or-today calendar day opens an :class:`ft.AlertDialog` that
offers the four existing :class:`WorkLocation` choices (Denmark / Home /
Vacation / Sick) plus a Clear action. Future dates never open the picker; the
pure :func:`can_open_picker` gate decides eligibility before the dialog is ever
built, so the view layer can short-circuit a tap on a future day.

The builder is a pure function returning an :class:`ft.AlertDialog`; it never
starts the Flet runtime and performs no I/O. The upsert / clear coroutines that
wire the dialog to the backend (:func:`apply_day_type` / ``clear_day_type``)
live alongside this builder and are themselves runtime-free: they take an
:class:`~app.state.AppState` and an :class:`~app.api_client.APIClient`, mutate
state in place, and never touch Flet, so they can be unit-tested with a mocked
client.

The dialog reuses the colour map already used by the calendar tiles
(``entry_tile._LOCATION_COLORS``) together with its own :data:`PICKER_LABELS`
so it reads in the same visual language as the rest of the home screen.

Requirements: 1.1, 1.2, 1.3, 1.5
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import flet as ft

from app.api_client import APIClient, APIError, WorkEntry, WorkLocation
from app.components.entry_tile import _LOCATION_COLORS
from app.state import AppState

# Human-readable labels for the four location choices (Requirement 1.2).
PICKER_LABELS: dict[WorkLocation, str] = {
    WorkLocation.DENMARK: "Office / Denmark",
    WorkLocation.HOME: "Work from Home",
    WorkLocation.VACATION: "Vacation",
    WorkLocation.SICK: "Sick Day",
}

# Order the four choices are rendered in.
_PICKER_ORDER: tuple[WorkLocation, ...] = (
    WorkLocation.DENMARK,
    WorkLocation.HOME,
    WorkLocation.VACATION,
    WorkLocation.SICK,
)


def can_open_picker(day: date, today: date | None = None) -> bool:
    """Return ``True`` iff ``day`` is on or before ``today``.

    This is the eligibility gate for the day-type picker: a day may only be
    edited once it has arrived. ``today`` defaults to :meth:`date.today` and is
    injectable so the gate can be tested deterministically.

    Args:
        day: The calendar day that was tapped.
        today: The reference "today" date; defaults to the system date.

    Returns:
        ``True`` when ``day`` is today or in the past (picker may open),
        ``False`` when ``day`` is in the future (Requirements 1.1, 1.5).
    """
    return day <= (today or date.today())  # noqa: DTZ011


def _picker_option(
    location: WorkLocation,
    *,
    is_current: bool,
    on_select: Callable[[WorkLocation], None],
) -> ft.Button:
    """Build a single colour-coded choice button for ``location``.

    When ``is_current`` is ``True`` the button is marked as the currently
    recorded choice (Requirement 1.3): a check icon is shown and the button is
    flagged via its ``selected`` attribute and a ``data`` payload the view /
    tests can read back.
    """
    label = PICKER_LABELS[location]
    text = f"{label} (current)" if is_current else label

    content: ft.Control
    if is_current:
        content = ft.Row(
            controls=[
                ft.Icon(ft.Icons.CHECK, color=ft.Colors.WHITE, size=18),
                ft.Text(text, color=ft.Colors.WHITE),
            ],
            tight=True,
            spacing=6,
            alignment=ft.MainAxisAlignment.CENTER,
        )
    else:
        content = ft.Text(text, color=ft.Colors.WHITE)

    button = ft.Button(
        content=content,
        color=ft.Colors.WHITE,
        bgcolor=_LOCATION_COLORS[location],
        on_click=lambda _e, loc=location: on_select(loc),
        data=location,
    )
    # Flag the recorded choice so the view layer and tests can identify exactly
    # which option matches ``current.location`` (Requirement 1.3).
    button.selected = is_current
    return button


def build_day_type_picker(
    work_date: date,
    current: WorkEntry | None,
    on_select: Callable[[WorkLocation], None],
    on_clear: Callable[[], None],
    on_dismiss: Callable[[], None],
) -> ft.AlertDialog:
    """Build the day-type picker dialog for ``work_date``.

    The dialog presents the four :class:`WorkLocation` choices plus a Clear
    action and a Cancel action. When ``current`` is not ``None`` the option
    whose location matches ``current.location`` is marked as the currently
    recorded choice, and no other option is marked (Requirement 1.3).

    Args:
        work_date: The date the picker is being opened for (shown in the title).
        current: The existing :class:`WorkEntry` for ``work_date``, or ``None``
            when the day has no logged entry yet.
        on_select: Called with the chosen :class:`WorkLocation` when the user
            picks one of the four location choices.
        on_clear: Called with no arguments when the user chooses Clear.
        on_dismiss: Called with no arguments when the user cancels/dismisses the
            dialog without choosing (Requirement 1.4).

    Returns:
        A configured :class:`ft.AlertDialog`. The caller is responsible for
        opening it (e.g. via ``page.show_dialog``).
    """
    current_location = current.location if current is not None else None

    options = ft.Column(
        controls=[
            _picker_option(
                location,
                is_current=location == current_location,
                on_select=on_select,
            )
            for location in _PICKER_ORDER
        ],
        tight=True,
        spacing=8,
    )

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(f"Record {work_date.isoformat()}"),
        content=options,
        actions=[
            ft.TextButton("Cancel", on_click=lambda _e: on_dismiss()),
            ft.TextButton("Clear", on_click=lambda _e: on_clear()),
        ],
    )
    return dialog


# ---------------------------------------------------------------------------
# upsert coroutine (runtime-free, so it is directly testable)
# ---------------------------------------------------------------------------


async def apply_day_type(
    state: AppState,
    api_client: APIClient,
    work_date: date,
    location: WorkLocation,
    *,
    generation: int | None = None,
) -> bool:
    """Upsert ``location`` for ``work_date`` from the day-type picker.

    This is the "assign a location through the picker" logic (Requirement 2).
    It decides POST vs PATCH from the current in-memory state, matching the
    backend's upsert semantics and the existing edit/log flow in
    ``home_view``:

    * when ``state.entries`` has no entry for ``work_date``, it issues a POST
      via :meth:`APIClient.post_entry` (Requirements 2.1, 2.2);
    * when an entry already exists, it issues a PATCH via
      :meth:`APIClient.patch_entry` for that entry's id (Requirements 2.1,
      2.3).

    On success the returned entry is applied to ``state.entries``, the previous
    error is cleared, the current-month compliance summary is refreshed, and
    the annual summary is refreshed best-effort so the summary screen stays
    accurate; the method returns ``True`` (Requirement 2.4).

    On :class:`APIError` the selected date's entry is left unchanged (the
    calendar tile is preserved, Requirement 2.6) and ``state.error_message`` is
    populated via the shared classifier; the method returns ``False``.

    When ``generation`` is given it is re-checked against
    ``state.backend_generation`` immediately before writing results; a mismatch
    means the backend changed mid-request, so the write is skipped and the
    method returns ``False``. ``generation=None`` disables the guard. The
    guard, error classifier and annual-summary refresh are imported from
    ``home_view`` at call time to reuse the exact behaviour of the existing
    edit/delete flow while avoiding a ``home_view <-> day_type_picker`` import
    cycle.

    Args:
        state: The shared in-memory :class:`AppState`.
        api_client: The backend :class:`APIClient`.
        work_date: The date the picker was opened for.
        location: The chosen :class:`WorkLocation`.
        generation: Optional backend generation guarding the write.

    Returns:
        ``True`` when the upsert succeeded and state was updated, ``False`` on
        a stale-generation skip or a backend error.
    """
    # Imported lazily to avoid a module-level ``home_view <-> day_type_picker``
    # import cycle: ``home_view`` imports this module to wire the picker.
    from app.views.home_view import (
        _backend_guard,
        _record_error,
        _refresh_annual,
        classify_error,
    )

    existing = state.entries.get(work_date.isoformat())
    guard = _backend_guard(state, generation)

    try:
        if existing is None:
            entry = await api_client.post_entry(work_date.isoformat(), location)
        else:
            entry = await api_client.patch_entry(existing.id, location)
    except APIError as exc:
        if guard.is_stale(state):
            return False
        # Tile unchanged; surface the classified error (Requirement 2.6).
        _record_error(state, classify_error(exc))
        return False

    # Guard the write: a backend switch during the request invalidates results.
    if guard.is_stale(state):
        return False

    # Success: apply the entry and refresh the compliance indicators.
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
        if not guard.is_stale(state):
            state.compliance_summary = summary

    await _refresh_annual(state, api_client, generation=generation)

    return True


# ---------------------------------------------------------------------------
# clear coroutine (runtime-free, so it is directly testable)
# ---------------------------------------------------------------------------


async def clear_day_type(
    state: AppState,
    api_client: APIClient,
    work_date: date,
    *,
    generation: int | None = None,
) -> bool:
    """Clear any logged entry for ``work_date`` from the day-type picker.

    This is the "clear a day through the picker" logic (Requirement 3). It
    reuses the existing delete flow from ``home_view`` rather than
    reimplementing the DELETE, so the backend contract, generation guard, error
    classification and summary refresh behave identically to the long-press
    delete menu:

    * when ``state.entries`` has no entry for ``work_date``, it short-circuits
      with no DELETE request and leaves ``state.entries`` unchanged, returning
      ``True`` so the picker simply closes (Requirement 3.4);
    * when an entry exists, it delegates to ``delete_entry`` which issues a
      DELETE for that entry's id, removes the date from ``state.entries`` on
      success and refreshes the current-month compliance summary
      (Requirements 3.1, 3.2).

    On :class:`APIError` ``delete_entry`` keeps the entry in ``state.entries``
    so its calendar tile stays visible and populates ``state.error_message``;
    this method then returns ``False`` (Requirement 3.5).

    When ``generation`` is given it is forwarded to ``delete_entry`` and
    re-checked against ``state.backend_generation`` before the write; a
    mismatch means the backend changed mid-request, so the write is skipped and
    the method returns ``False``. ``generation=None`` disables the guard.
    ``delete_entry`` is imported lazily to avoid a module-level
    ``home_view <-> day_type_picker`` import cycle, mirroring
    :func:`apply_day_type`.

    Args:
        state: The shared in-memory :class:`AppState`.
        api_client: The backend :class:`APIClient`.
        work_date: The date the picker was opened for.
        generation: Optional backend generation guarding the write.

    Returns:
        ``True`` when the day was cleared (or there was nothing to clear),
        ``False`` on a stale-generation skip or a backend error.
    """
    existing = state.entries.get(work_date.isoformat())
    if existing is None:
        # Nothing logged for this date: close with no DELETE and no state
        # change (Requirement 3.4).
        return True

    # Imported lazily to avoid a module-level ``home_view <-> day_type_picker``
    # import cycle: ``home_view`` imports this module to wire the picker.
    from app.views.home_view import delete_entry

    return await delete_entry(state, api_client, existing, generation=generation)
