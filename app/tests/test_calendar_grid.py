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
from app.components.calendar_grid import (
    _COLUMNS,
    _PADDING,
    _SPACING,
    BLANK_CELL,
    build_calendar_grid,
    fit_cell_edge,
    row_count,
)

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


# ---------------------------------------------------------------------------
# Height-aware square sizing (Requirements 4.1, 4.2)
# ---------------------------------------------------------------------------


class TestFitCellEdge:
    def test_returns_min_of_width_and_height_constrained_edges(self) -> None:
        # Wide but short viewport → height is the binding constraint.
        wide_short = fit_cell_edge(10_000.0, 600.0, 6)
        # The height-based edge for 6 rows must bound the result, not width.
        height_edge = (600.0 - 2 * _PADDING - (6 - 1) * _SPACING) / 6
        assert wide_short == height_edge

        # Tall but narrow viewport → width is the binding constraint.
        narrow_tall = fit_cell_edge(400.0, 10_000.0, 6)
        width_edge = (400.0 - 2 * _PADDING - (_COLUMNS - 1) * _SPACING) / _COLUMNS
        assert narrow_tall == width_edge

    def test_edge_is_floored_at_zero(self) -> None:
        # Available dimensions smaller than the padding/gutters must not yield a
        # negative edge.
        assert fit_cell_edge(1.0, 1.0, 6) == 0.0
        assert fit_cell_edge(10.0, 1.0, 6) == 0.0

    def test_non_positive_row_count_yields_zero(self) -> None:
        assert fit_cell_edge(1000.0, 1000.0, 0) == 0.0
        assert fit_cell_edge(1000.0, 1000.0, -3) == 0.0

    def test_result_fits_both_width_and_height(self) -> None:
        # For a range of representative viewports and row counts, the chosen
        # edge must satisfy both the width and height constraints exactly.
        viewports = [
            (400.0, 600.0),
            (1920.0, 1080.0),
            (800.0, 400.0),
            (1200.0, 2000.0),
            (375.0, 812.0),
        ]
        for avail_w, avail_h in viewports:
            for rows in range(1, 7):
                edge = fit_cell_edge(avail_w, avail_h, rows)
                width_used = _COLUMNS * edge + (_COLUMNS - 1) * _SPACING + 2 * _PADDING
                height_used = rows * edge + (rows - 1) * _SPACING + 2 * _PADDING
                # Allow a hair of floating-point slack.
                assert width_used <= avail_w + 1e-9
                assert height_used <= avail_h + 1e-9


class TestRowCount:
    def test_28_day_february_starting_monday_is_four_rows(self) -> None:
        # February 2021: 28 days, 1 Feb 2021 is a Monday → no leading blanks →
        # exactly 4 rows.
        assert calendar.monthrange(2021, 2)[0] == 0
        assert calendar.monthrange(2021, 2)[1] == 28
        assert row_count(2021, 2) == 4

    def test_31_day_month_starting_saturday_needs_six_rows(self) -> None:
        # May 2021: 31 days, 1 May 2021 is a Saturday (Monday-indexed 5) →
        # 5 blanks + 31 days = 36 cells → 6 rows.
        assert calendar.monthrange(2021, 5)[0] == 5
        assert calendar.monthrange(2021, 5)[1] == 31
        assert row_count(2021, 5) == 6

    def test_31_day_month_starting_sunday_needs_six_rows(self) -> None:
        # August 2021: 31 days, 1 Aug 2021 is a Sunday (Monday-indexed 6) →
        # 6 blanks + 31 days = 37 cells → 6 rows.
        assert calendar.monthrange(2021, 8)[0] == 6
        assert row_count(2021, 8) == 6

    def test_matches_grid_cell_count_for_every_month(self) -> None:
        for month in range(1, 13):
            first_weekday, days = calendar.monthrange(2025, month)
            expected = -(-(first_weekday + days) // _COLUMNS)
            assert row_count(2025, month) == expected
