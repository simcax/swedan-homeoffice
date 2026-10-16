"""Monthly calendar grid component.

``build_calendar_grid`` renders one color-coded tile per day of a month inside
an :class:`ft.GridView`. Each day is looked up in the ``entries`` mapping (keyed
by ISO date string ``"YYYY-MM-DD"`` — the same convention used by
:class:`app.state.AppState`); days without a logged entry render as unlogged.

The grid is laid out as a real Mon–Sun calendar: blank placeholder cells are
inserted before day 1 so that each day falls under its correct weekday column.

An optional ``on_day_long_press`` callback can be supplied so a parent view can
later wire edit/delete behaviour. The callback receives the day-of-month number
(``int``) of the long-pressed tile. Long-press is wired via each tile's
:class:`ft.Container` ``on_long_press`` handler, available in the installed Flet
1.0.2.

The builder is a pure function; it never starts the Flet runtime and performs
no I/O.

Requirements: 5.1, 8.2
"""

from __future__ import annotations

import calendar
from collections.abc import Callable

import flet as ft

from app.api_client import WorkEntry
from app.components.entry_tile import build_entry_tile

# Number of weekday columns in the grid (Mon–Sun).
_COLUMNS = 7


def _iso_key(year: int, month: int, day: int) -> str:
    """Return the ISO date key ``"YYYY-MM-DD"`` for a day in the month."""
    return f"{year:04d}-{month:02d}-{day:02d}"


def build_calendar_grid(
    year: int,
    month: int,
    entries: dict[str, WorkEntry],
    on_day_long_press: Callable[[int], None] | None = None,
) -> ft.GridView:
    """Build a monthly calendar grid of color-coded day tiles.

    Args:
        year: Four-digit calendar year (e.g. ``2025``).
        month: Month number, ``1``–``12``.
        entries: Logged work entries keyed by ISO date string ``"YYYY-MM-DD"``
            (the :class:`app.state.AppState` convention). Days absent from the
            mapping render as unlogged.
        on_day_long_press: Optional callback invoked with the day-of-month
            (``int``) when a tile is long-pressed. Lets the home view wire
            edit/delete later. When ``None``, tiles have no long-press handler.

    Returns:
        An :class:`ft.GridView` laid out Mon–Sun. The controls are
        ``first_weekday`` blank placeholder cells (so day 1 lands under its
        real weekday) followed by one tile per day, ordered from day 1 to the
        last day of the month.
    """
    first_weekday, days_in_month = calendar.monthrange(year, month)

    # ``calendar.monthrange`` returns Monday=0 … Sunday=6 for day 1, which maps
    # directly onto a Mon–Sun column layout.
    controls: list[ft.Control] = [_blank_cell() for _ in range(first_weekday)]

    for day in range(1, days_in_month + 1):
        entry = entries.get(_iso_key(year, month, day))
        tile = build_entry_tile(day, entry)

        if on_day_long_press is not None:
            tile.on_long_press = _make_long_press_handler(day, on_day_long_press)

        controls.append(tile)

    return ft.GridView(
        controls=controls,
        runs_count=_COLUMNS,
        spacing=8,
        run_spacing=8,
        padding=8,
        expand=True,
    )


def _blank_cell() -> ft.Container:
    """Return an empty placeholder cell used to pad the grid before day 1."""
    return ft.Container(data=None)


def _make_long_press_handler(
    day: int, callback: Callable[[int], None]
) -> Callable[[ft.ControlEvent], None]:
    """Bind ``day`` to ``callback`` for a single tile's long-press event."""

    def _handler(_event: ft.ControlEvent) -> None:
        callback(day)

    return _handler
