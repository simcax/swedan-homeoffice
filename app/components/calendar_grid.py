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

An optional ``on_day_tap`` callback can likewise be supplied so a parent view
can open the day-type picker when a tile is tapped. It receives the same
day-of-month number (``int``) and is wired via each tile's ``on_click``
handler, independently of the long-press hook.

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

# Inter-column (and inter-row) spacing between cells, in logical pixels.
_SPACING = 8

# Outer padding applied around the grid, in logical pixels.
_PADDING = 8

# Marker stored on each leading placeholder cell's ``data`` so callers can tell
# blanks apart from day tiles (which carry their integer day-of-month).
BLANK_CELL = "blank"

# Monday-through-Sunday labels for the weekday header row, matching the Mon–Sun
# column order of the calendar grid.
WEEKDAY_LABELS: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _iso_key(year: int, month: int, day: int) -> str:
    """Return the ISO date key ``"YYYY-MM-DD"`` for a day in the month."""
    return f"{year:04d}-{month:02d}-{day:02d}"


def cell_edge(available_width: float) -> float:
    """Square edge length for one column given the grid's available width.

    Accounts for the grid's outer padding and the inter-column spacing so the
    seven columns plus their gutters exactly fill ``available_width``. The
    result is floored at ``0.0`` so a width too small to hold the padding and
    gutters never yields a negative edge.

    Requirements: 4.2
    """
    inner = available_width - 2 * _PADDING - (_COLUMNS - 1) * _SPACING
    return max(0.0, inner / _COLUMNS)


def fit_cell_edge(
    available_width: float, available_height: float, row_count: int
) -> float:
    """Largest square edge that fits the grid in both width and height.

    Returns the largest square edge length such that both constraints hold:

    * seven columns plus their six inter-column gutters (``_SPACING``) plus the
      two outer paddings (``_PADDING``) fit within ``available_width``; and
    * ``row_count`` rows plus their ``row_count - 1`` inter-row gutters
      (``_SPACING``) plus the two outer paddings (``_PADDING``) fit within
      ``available_height``.

    i.e. ``edge = max(0.0, min(width_based_edge, height_based_edge))``. The
    result is floored at ``0.0`` so a width/height too small to hold the padding
    and gutters never yields a negative edge, and a non-positive ``row_count``
    yields ``0.0``. Keeping tiles square satisfies Requirement 4.1 while the
    height constraint keeps all weeks within the viewport (Requirement 4.2).

    Requirements: 4.1, 4.2
    """
    width_inner = available_width - 2 * _PADDING - (_COLUMNS - 1) * _SPACING
    width_edge = width_inner / _COLUMNS

    if row_count <= 0:
        return 0.0

    height_inner = available_height - 2 * _PADDING - (row_count - 1) * _SPACING
    height_edge = height_inner / row_count

    return max(0.0, min(width_edge, height_edge))


def row_count(year: int, month: int) -> int:
    """Number of calendar rows (weeks) a month occupies in the Mon–Sun grid.

    A month's grid is laid out as ``first_weekday`` leading blank cells (Monday
    = 0 … Sunday = 6, from :func:`calendar.monthrange`) followed by one cell per
    day. The number of rows is therefore
    ``ceil((first_weekday + days_in_month) / 7)`` — the total cell count divided
    by the seven columns, rounded up. This drives the height constraint in
    :func:`fit_cell_edge` so every week fits the viewport (Requirement 4.2).

    Requirements: 4.2
    """
    first_weekday, days_in_month = calendar.monthrange(year, month)
    total_cells = first_weekday + days_in_month
    return -(-total_cells // _COLUMNS)


def build_weekday_header() -> ft.Row:
    """Build the Monday–Sunday weekday-name header row for the calendar grid.

    Returns an :class:`ft.Row` of seven ``expand=True`` centred label
    containers in Mon–Sun order, using the same ``_SPACING`` as the grid. Each
    cell expands equally, so the seven labels occupy equal fractions of the row
    width exactly as the grid's seven columns do — alignment above each column
    is preserved for any width without measuring it.

    The builder is a pure function; it never starts the Flet runtime and
    performs no I/O.

    Requirements: 5.1, 5.2, 5.3
    """
    return ft.Row(
        controls=[
            ft.Container(
                content=ft.Text(
                    label,
                    text_align=ft.TextAlign.CENTER,
                    weight=ft.FontWeight.BOLD,
                ),
                alignment=ft.Alignment.CENTER,
                expand=True,
            )
            for label in WEEKDAY_LABELS
        ],
        spacing=_SPACING,
    )


def build_calendar_grid(
    year: int,
    month: int,
    entries: dict[str, WorkEntry],
    on_day_long_press: Callable[[int], None] | None = None,
    on_day_tap: Callable[[int], None] | None = None,
    *,
    cell_edge: float | None = None,
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
        on_day_tap: Optional callback invoked with the day-of-month (``int``)
            when a tile is tapped. Lets the home view open the day-type picker.
            When ``None``, tiles have no tap handler.
        cell_edge: Optional explicit square edge length (logical px) for every
            cell. When provided, each day tile (and each leading blank cell) is
            pinned to a ``cell_edge`` × ``cell_edge`` square and the grid is
            laid out with ``max_extent = cell_edge + _SPACING`` so exactly seven
            fixed-size squares fit per row. This lets the home view size the
            grid so all weeks fit the viewport height without clipping
            (Requirement 4.2). When ``None`` (the default), tiles ``expand`` to
            fill their grid cell and the grid ``expand``\\s to fill its parent,
            preserving the original behaviour.

    Returns:
        An :class:`ft.GridView` laid out Mon–Sun. The controls are
        ``first_weekday`` blank placeholder cells (so day 1 lands under its
        real weekday) followed by one tile per day, ordered from day 1 to the
        last day of the month.
    """
    first_weekday, days_in_month = calendar.monthrange(year, month)

    # ``calendar.monthrange`` returns Monday=0 … Sunday=6 for day 1, which maps
    # directly onto a Mon–Sun column layout.
    controls: list[ft.Control] = [
        _blank_cell(edge=cell_edge) for _ in range(first_weekday)
    ]

    for day in range(1, days_in_month + 1):
        entry = entries.get(_iso_key(year, month, day))
        tile = build_entry_tile(day, entry, edge=cell_edge)

        if on_day_long_press is not None:
            tile.on_long_press = _make_long_press_handler(day, on_day_long_press)

        if on_day_tap is not None:
            tile.on_click = _make_tap_handler(day, on_day_tap)

        controls.append(tile)

    if cell_edge is None:
        # Fill-the-parent behaviour: the grid expands and its 1:1 aspect ratio
        # keeps the expand=True tiles square.
        return ft.GridView(
            controls=controls,
            runs_count=_COLUMNS,
            child_aspect_ratio=1.0,
            spacing=_SPACING,
            run_spacing=_SPACING,
            padding=_PADDING,
            expand=True,
        )

    # Explicit edge: size cells to exact squares. ``max_extent`` bounds each
    # child's cross-axis extent to one cell plus a gutter, so seven fixed
    # ``cell_edge`` squares (with ``_SPACING`` gutters) fit per row. The grid
    # expands to fill the height its holder gives it and scrolls vertically
    # (``scroll=AUTO``) as a safety net, so the final week is always reachable
    # even if the computed edge leaves the last row slightly below the fold
    # (Requirement 4.2).
    return ft.GridView(
        controls=controls,
        runs_count=_COLUMNS,
        child_aspect_ratio=1.0,
        spacing=_SPACING,
        run_spacing=_SPACING,
        padding=_PADDING,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def _blank_cell(edge: float | None = None) -> ft.Container:
    """Return an empty placeholder cell used to pad the grid before day 1.

    The cell is marked with ``data=BLANK_CELL`` so it is explicitly
    distinguishable from day tiles (which carry an integer day-of-month). When
    ``edge`` is supplied the blank is pinned to the same ``edge`` × ``edge``
    square as the day tiles so the grid stays aligned under an explicit size.
    """
    cell = ft.Container(data=BLANK_CELL)
    if edge is not None:
        cell.width = edge
        cell.height = edge
    return cell


def _make_long_press_handler(
    day: int, callback: Callable[[int], None]
) -> Callable[[ft.ControlEvent], None]:
    """Bind ``day`` to ``callback`` for a single tile's long-press event."""

    def _handler(_event: ft.ControlEvent) -> None:
        callback(day)

    return _handler


def _make_tap_handler(
    day: int, callback: Callable[[int], None]
) -> Callable[[ft.ControlEvent], None]:
    """Bind ``day`` to ``callback`` for a single tile's tap (click) event."""

    def _handler(_event: ft.ControlEvent) -> None:
        callback(day)

    return _handler
