"""Monthly calendar grid component.

``build_calendar_grid`` renders one color-coded tile per day of a month inside
an :class:`ft.GridView`. Each day is looked up in the ``entries`` mapping (keyed
by ISO date string ``"YYYY-MM-DD"`` — the same convention used by
:class:`app.state.AppState`); days without a logged entry render as unlogged.

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
_RUNS_COUNT = 7


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
        An :class:`ft.GridView` containing one tile per day of the month,
        ordered from day 1 to the last day of the month.
    """
    _, days_in_month = calendar.monthrange(year, month)

    tiles: list[ft.Container] = []
    for day in range(1, days_in_month + 1):
        entry = entries.get(_iso_key(year, month, day))
        tile = build_entry_tile(day, entry)

        if on_day_long_press is not None:
            tile.on_long_press = _make_long_press_handler(day, on_day_long_press)

        tiles.append(tile)

    return ft.GridView(
        controls=tiles,
        runs_count=_RUNS_COUNT,
        spacing=8,
        run_spacing=8,
        padding=8,
        expand=True,
    )


def _make_long_press_handler(
    day: int, callback: Callable[[int], None]
) -> Callable[[ft.ControlEvent], None]:
    """Bind ``day`` to ``callback`` for a single tile's long-press event."""

    def _handler(_event: ft.ControlEvent) -> None:
        callback(day)

    return _handler
