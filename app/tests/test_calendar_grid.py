"""Unit tests for the monthly calendar grid component (task 11.3).

These tests exercise the pure builder logic in ``app.components.calendar_grid``
without starting the Flet runtime. They verify the grid renders one tile per
day of a month, color-codes days with a matching entry, renders days without an
entry as unlogged, and wires the optional long-press callback.

Requirements: 5.1, 8.2
"""

from __future__ import annotations

import calendar
from datetime import date

import flet as ft

from app.api_client import WorkEntry, WorkLocation
from app.components.calendar_grid import BLANK_CELL, build_calendar_grid

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _entry(year: int, month: int, day: int, location: WorkLocation) -> WorkEntry:
    return WorkEntry(
        id=day,
        work_date=date(year, month, day),
        location=location,
        created_at="2025-06-10T08:00:00+00:00",
        updated_at="2025-06-10T08:00:00+00:00",
    )


def _tiles(grid: ft.GridView) -> list[ft.Container]:
    """Return only the real day tiles (leading blank placeholders excluded)."""
    return [c for c in grid.controls if c.data != BLANK_CELL]


def _blanks(grid: ft.GridView) -> list[ft.Container]:
    """Return the leading blank placeholder cells (``data == BLANK_CELL``)."""
    return [c for c in grid.controls if c.data == BLANK_CELL]


# ---------------------------------------------------------------------------
# Grid structure (Requirement 5.1)
# ---------------------------------------------------------------------------


class TestGridStructure:
    def test_returns_a_grid_view(self) -> None:
        grid = build_calendar_grid(2025, 6, {})

        assert isinstance(grid, ft.GridView)

    def test_has_one_tile_per_day_in_a_31_day_month(self) -> None:
        # July 2025 has 31 days.
        grid = build_calendar_grid(2025, 7, {})

        assert len(_tiles(grid)) == 31

    def test_has_one_tile_per_day_in_a_30_day_month(self) -> None:
        # June 2025 has 30 days.
        grid = build_calendar_grid(2025, 6, {})

        assert len(_tiles(grid)) == 30

    def test_has_one_tile_per_day_in_february_leap_year(self) -> None:
        # February 2024 is a leap year → 29 days.
        grid = build_calendar_grid(2024, 2, {})

        assert len(_tiles(grid)) == 29

    def test_tile_count_matches_calendar_monthrange(self) -> None:
        for month in range(1, 13):
            _, days = calendar.monthrange(2025, month)
            grid = build_calendar_grid(2025, month, {})
            assert len(_tiles(grid)) == days

    def test_tiles_are_ordered_from_day_one(self) -> None:
        grid = build_calendar_grid(2025, 6, {})

        days = [tile.data for tile in _tiles(grid)]
        assert days == list(range(1, 31))


# ---------------------------------------------------------------------------
# Weekday alignment (Mon–Sun layout)
# ---------------------------------------------------------------------------


class TestWeekdayAlignment:
    def test_leading_blanks_match_first_weekday(self) -> None:
        # June 2025 starts on a Sunday → Monday-indexed weekday 6 → 6 blanks.
        first_weekday, _ = calendar.monthrange(2025, 6)
        grid = build_calendar_grid(2025, 6, {})

        assert len(_blanks(grid)) == first_weekday

    def test_month_starting_on_monday_has_no_blanks(self) -> None:
        # September 2025 starts on a Monday → no leading blanks.
        assert calendar.monthrange(2025, 9)[0] == 0
        grid = build_calendar_grid(2025, 9, {})

        assert _blanks(grid) == []

    def test_blanks_precede_the_day_tiles(self) -> None:
        grid = build_calendar_grid(2025, 6, {})
        first_weekday, _ = calendar.monthrange(2025, 6)

        leading = grid.controls[:first_weekday]
        assert all(cell.data == BLANK_CELL for cell in leading)
        assert grid.controls[first_weekday].data == 1

    def test_blanks_count_for_every_month(self) -> None:
        for month in range(1, 13):
            first_weekday, _ = calendar.monthrange(2025, month)
            grid = build_calendar_grid(2025, month, {})
            assert len(_blanks(grid)) == first_weekday
            assert _tiles(grid)[0].data == 1


# ---------------------------------------------------------------------------
# Entry lookup and color coding (Requirement 8.2)
# ---------------------------------------------------------------------------


class TestColorCoding:
    def test_day_with_matching_entry_is_color_coded(self) -> None:
        entries = {"2025-06-10": _entry(2025, 6, 10, WorkLocation.DENMARK)}
        grid = build_calendar_grid(2025, 6, entries)

        tile = _tiles(grid)[9]  # day 10 → index 9
        assert tile.data == 10
        assert tile.bgcolor == ft.Colors.RED_700

    def test_each_location_uses_its_distinct_color(self) -> None:
        entries = {
            "2025-06-01": _entry(2025, 6, 1, WorkLocation.DENMARK),
            "2025-06-02": _entry(2025, 6, 2, WorkLocation.HOME),
            "2025-06-03": _entry(2025, 6, 3, WorkLocation.VACATION),
            "2025-06-04": _entry(2025, 6, 4, WorkLocation.SICK),
        }
        grid = build_calendar_grid(2025, 6, entries)
        tiles = _tiles(grid)

        assert tiles[0].bgcolor == ft.Colors.RED_700
        assert tiles[1].bgcolor == ft.Colors.BLUE_700
        assert tiles[2].bgcolor == ft.Colors.ORANGE_700
        assert tiles[3].bgcolor == ft.Colors.PURPLE_700

    def test_days_without_entries_render_as_unlogged(self) -> None:
        entries = {"2025-06-10": _entry(2025, 6, 10, WorkLocation.DENMARK)}
        grid = build_calendar_grid(2025, 6, entries)

        # Every day other than the 10th has no entry → unlogged surface colour.
        for tile in _tiles(grid):
            if tile.data == 10:
                continue
            assert tile.bgcolor == ft.Colors.SURFACE_CONTAINER_HIGHEST

    def test_empty_entries_renders_all_days_unlogged(self) -> None:
        grid = build_calendar_grid(2025, 6, {})

        assert all(
            tile.bgcolor == ft.Colors.SURFACE_CONTAINER_HIGHEST for tile in _tiles(grid)
        )

    def test_entry_from_another_month_is_ignored(self) -> None:
        # An entry keyed to a different month must not colour any June tile.
        entries = {"2025-07-10": _entry(2025, 7, 10, WorkLocation.DENMARK)}
        grid = build_calendar_grid(2025, 6, entries)

        assert all(
            tile.bgcolor == ft.Colors.SURFACE_CONTAINER_HIGHEST for tile in _tiles(grid)
        )


# ---------------------------------------------------------------------------
# Long-press wiring (edit/delete hook)
# ---------------------------------------------------------------------------


class TestLongPress:
    def test_no_handler_wired_when_callback_omitted(self) -> None:
        grid = build_calendar_grid(2025, 6, {})

        assert all(tile.on_long_press is None for tile in _tiles(grid))

    def test_handler_wired_on_every_tile_when_callback_given(self) -> None:
        grid = build_calendar_grid(2025, 6, {}, on_day_long_press=lambda day: None)

        assert all(tile.on_long_press is not None for tile in _tiles(grid))

    def test_long_press_handler_receives_the_day(self) -> None:
        received: list[int] = []
        grid = build_calendar_grid(2025, 6, {}, on_day_long_press=received.append)

        # Fire the handler for the tile representing day 15 (index 14).
        tile = _tiles(grid)[14]
        assert tile.data == 15
        tile.on_long_press(None)

        assert received == [15]
