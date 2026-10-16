"""Color-coded day tile component for the monthly calendar grid.

Each tile represents a single calendar day. Its background colour encodes the
logged work location, so a user can read a whole month's pattern at a glance:

* ``denmark``  → red    (office day in Denmark)
* ``home``     → blue   (worked from home in Sweden)
* ``vacation`` → orange
* ``sick``     → purple
* unlogged     → a theme-aware surface-container colour (no entry yet) so the
  tile stays distinguishable from the page surface behind it

The builder is a pure function returning an :class:`ft.Container`; it never
starts the Flet runtime and performs no I/O.

Requirements: 8.2, 13.5, 14.5
"""

from __future__ import annotations

import flet as ft

from app.api_client import WorkEntry, WorkLocation

# Background colour per logged location (Requirements 8.2, 13.5, 14.5).
_LOCATION_COLORS: dict[WorkLocation, str] = {
    WorkLocation.DENMARK: ft.Colors.RED_700,
    WorkLocation.HOME: ft.Colors.BLUE_700,
    WorkLocation.VACATION: ft.Colors.ORANGE_700,
    WorkLocation.SICK: ft.Colors.PURPLE_700,
}

# Colour used for days that have no logged entry yet. A surface-container
# colour keeps the tile visible against the SURFACE-coloured page behind it.
_UNLOGGED_COLOR: str = ft.Colors.SURFACE_CONTAINER_HIGHEST


def tile_color(entry: WorkEntry | None) -> str:
    """Return the background colour for a tile given its ``entry``.

    ``None`` (an unlogged day) maps to the theme-aware surface-container
    colour; any logged entry maps to the colour for its :class:`WorkLocation`.
    """
    if entry is None:
        return _UNLOGGED_COLOR
    return _LOCATION_COLORS[entry.location]


def build_entry_tile(day: int, entry: WorkEntry | None) -> ft.Container:
    """Build a color-coded calendar tile for a single day.

    Args:
        day: The day-of-month number shown on the tile (1–31).
        entry: The logged :class:`WorkEntry` for that day, or ``None`` when the
            day has not been logged yet.

    Returns:
        An :class:`ft.Container` displaying the day number, with a background
        colour determined by the entry's location (or the surface colour when
        unlogged).
    """
    bgcolor = tile_color(entry)
    # Unlogged days use theme-aware on-surface text; logged (coloured) days
    # use white for legible contrast against the saturated backgrounds.
    text_color = ft.Colors.ON_SURFACE if entry is None else ft.Colors.WHITE

    return ft.Container(
        content=ft.Text(
            str(day),
            color=text_color,
            weight=ft.FontWeight.BOLD,
            text_align=ft.TextAlign.CENTER,
        ),
        bgcolor=bgcolor,
        alignment=ft.Alignment.CENTER,
        border_radius=8,
        padding=8,
        data=day,
    )
