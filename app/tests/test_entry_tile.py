"""Unit tests for the color-coded day tile component (task 11.1).

These tests exercise the pure builder logic in ``app.components.entry_tile``
without starting the Flet runtime. They verify the colour mapping required by
Requirements 8.2, 13.5 and 14.5 and that the tile renders the day number.
"""

from __future__ import annotations

from datetime import date

import flet as ft

from app.api_client import WorkEntry, WorkLocation
from app.components.entry_tile import build_entry_tile, tile_color

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _entry(location: WorkLocation, day: int = 10) -> WorkEntry:
    return WorkEntry(
        id=1,
        work_date=date(2025, 6, day),
        location=location,
        created_at="2025-06-10T08:00:00+00:00",
        updated_at="2025-06-10T08:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Colour mapping (Requirements 8.2, 13.5, 14.5)
# ---------------------------------------------------------------------------


class TestTileColor:
    def test_denmark_maps_to_red(self) -> None:
        assert tile_color(_entry(WorkLocation.DENMARK)) == ft.Colors.RED_700

    def test_home_maps_to_blue(self) -> None:
        assert tile_color(_entry(WorkLocation.HOME)) == ft.Colors.BLUE_700

    def test_vacation_maps_to_orange(self) -> None:
        assert tile_color(_entry(WorkLocation.VACATION)) == ft.Colors.ORANGE_700

    def test_sick_maps_to_purple(self) -> None:
        assert tile_color(_entry(WorkLocation.SICK)) == ft.Colors.PURPLE_700

    def test_unlogged_maps_to_surface_container(self) -> None:
        assert tile_color(None) == ft.Colors.SURFACE_CONTAINER_HIGHEST


# ---------------------------------------------------------------------------
# Tile construction
# ---------------------------------------------------------------------------


class TestBuildEntryTile:
    def test_returns_a_container(self) -> None:
        tile = build_entry_tile(10, _entry(WorkLocation.DENMARK))

        assert isinstance(tile, ft.Container)

    def test_displays_the_day_number(self) -> None:
        tile = build_entry_tile(17, None)

        assert isinstance(tile.content, ft.Text)
        assert tile.content.value == "17"

    def test_logged_tile_uses_location_color(self) -> None:
        tile = build_entry_tile(10, _entry(WorkLocation.VACATION))

        assert tile.bgcolor == ft.Colors.ORANGE_700

    def test_unlogged_tile_uses_surface_container_color(self) -> None:
        tile = build_entry_tile(10, None)

        assert tile.bgcolor == ft.Colors.SURFACE_CONTAINER_HIGHEST

    def test_logged_tile_text_is_white_for_contrast(self) -> None:
        tile = build_entry_tile(10, _entry(WorkLocation.HOME))

        assert tile.content.color == ft.Colors.WHITE

    def test_unlogged_tile_text_uses_on_surface(self) -> None:
        tile = build_entry_tile(10, None)

        assert tile.content.color == ft.Colors.ON_SURFACE
