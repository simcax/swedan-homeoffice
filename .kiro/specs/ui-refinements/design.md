# Design Document

## Overview

This feature refines the home screen of the work-location-tracker Flet app with
four frontend-only changes. No backend endpoint, schema, or `APIClient` method
changes. The `ComplianceSummary` model (`compliance_pct`, `denmark_days`,
`total_days`, `is_compliant`, …) is consumed exactly as it exists today.

The four changes are:

1. **Circular compliance indicator** — replace `build_compliance_bar`'s
   `ft.ProgressBar` with a circular `ft.ProgressRing` wrapped in a `ft.Stack`
   that centres a numeric fill label and a "days missing" caption.
2. **Days-missing derivation** — a pure, frontend-only function that derives how
   many office/Denmark days are still required to reach the pinned
   `COMPLIANCE_THRESHOLD`, using only fields already on `ComplianceSummary`.
3. **Remove quick-log buttons** — delete the quick-log `ft.Row` (and add no
   replacement FAB) so the day-type picker is the sole logging path.
4. **Responsive square cells + weekday header** — size calendar cells as squares
   that scale to the available width, and add a Monday–Sunday header row aligned
   to the same seven columns.

All logic that can be tested without the Flet runtime (fill fraction, displayed
percent, days-missing derivation, cell sizing, blank-cell count) is extracted
into pure functions in the component modules, following the existing
"runtime-free builders + thin Flet wrappers" pattern used throughout `app/`.

## Architecture

```
app/
├── views/
│   └── home_view.py          # MODIFIED: drop quick-log Row; add weekday header
│                             #           + responsive grid holder; render the
│                             #           new circular indicator
└── components/
    ├── compliance_bar.py     # MODIFIED: ProgressBar -> circular indicator;
    │                         #           add COMPLIANCE_THRESHOLD, fill_fraction,
    │                         #           display_percent, days_missing
    ├── calendar_grid.py      # MODIFIED: responsive square cells; weekday header
    │                         #           + cell_edge sizing helper
    └── entry_tile.py         # MODIFIED: accept an optional edge size; keep
                              #           square aspect
```

Data flow (unchanged shape, new presentation):

```
APIClient.get_summary() -> ComplianceSummary
        -> build_compliance_indicator(summary)
             -> fill_fraction(summary)      (ring value, clamped 0..1)
             -> display_percent(summary)    (centre label, clamped 1..100)
             -> days_missing(summary)        (caption, ceil, >= 0)
```

The language for all code examples is **Python (Flet 1.0.2)**, matching the
existing codebase.

## Components and Interfaces

### 1. Circular compliance indicator (`compliance_bar.py`)

The existing `build_compliance_bar` returns an `ft.ProgressBar`. It is replaced
by `build_compliance_indicator`, which returns an `ft.Stack` layering a circular
`ft.ProgressRing` under a centred `ft.Column` showing the fill percent and the
days-missing caption. The module keeps the "pure builder, no runtime, no I/O"
contract.

A single frontend constant pins the compliance target. No backend field carries
a required-Denmark-days target, so the threshold is a frontend-known constant
representing 100% of the ring's fill.

```python
# compliance_bar.py

import math
import flet as ft
from app.api_client import ComplianceSummary

# The compliance percentage at which a month is considered compliant. Pinned
# frontend-side because no backend field supplies a required-days target. It
# represents 100% of the circular indicator's fill (Requirement 1, 2).
COMPLIANCE_THRESHOLD: float = 60.0

# Theme-aware colours for the ring.
_COMPLIANT_COLOR = ft.Colors.GREEN_600
_NON_COMPLIANT_COLOR = ft.Colors.RED_700
_NEUTRAL_COLOR = ft.Colors.SURFACE


def fill_fraction(summary: ComplianceSummary) -> float:
    """Ring fill in [0.0, 1.0]: compliance_pct relative to the threshold."""
    if COMPLIANCE_THRESHOLD <= 0:
        return 1.0
    return max(0.0, min(1.0, summary.compliance_pct / COMPLIANCE_THRESHOLD))


def display_percent(summary: ComplianceSummary) -> int:
    """Centre-label percent, clamped to the inclusive range 1..100."""
    raw = round(fill_fraction(summary) * 100)
    return max(1, min(100, raw))


def days_missing(summary: ComplianceSummary) -> int:
    """Office/Denmark days still needed to reach the threshold.

    Derived only from fields already on ``ComplianceSummary``
    (``compliance_pct``, ``denmark_days``, ``total_days``). When the month is
    already compliant the result is 0; otherwise the real-valued shortfall is
    rounded UP so any partial remaining day counts as one whole day.
    """
    if summary.compliance_pct >= COMPLIANCE_THRESHOLD:
        return 0

    # compliance_pct == 100 * denmark_days / total_days, so the current
    # denmark_days implied by the percentage is recoverable without any new
    # field. The number of denmark_days required for the threshold is:
    #     required = ceil(threshold/100 * total_days)
    # and the shortfall is required - current denmark_days, floored at 0.
    required = math.ceil((COMPLIANCE_THRESHOLD / 100.0) * summary.total_days)
    shortfall = required - summary.denmark_days
    return max(0, shortfall)


def build_compliance_indicator(summary: ComplianceSummary | None) -> ft.Stack:
    """Circular compliance indicator; neutral empty state when summary is None."""
    if summary is None:
        ring = ft.ProgressRing(value=0, color=_NEUTRAL_COLOR, width=120, height=120)
        return ft.Stack(controls=[ring], width=120, height=120)

    color = _COMPLIANT_COLOR if summary.is_compliant else _NON_COMPLIANT_COLOR
    ring = ft.ProgressRing(
        value=fill_fraction(summary), color=color, width=120, height=120
    )
    missing = days_missing(summary)
    caption = "Compliant" if missing == 0 else f"{missing} day(s) to go"
    label = ft.Column(
        controls=[
            ft.Text(f"{display_percent(summary)}%", weight=ft.FontWeight.BOLD),
            ft.Text(caption, size=11),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=2,
    )
    return ft.Stack(
        controls=[
            ring,
            ft.Container(
                content=label, alignment=ft.Alignment.CENTER, width=120, height=120
            ),
        ],
        width=120,
        height=120,
    )
```

**Backward-compatible rename.** `home_view.py` imports `build_compliance_bar`
and `_refresh` reads `.value`, `.color`, `.tooltip` off the returned control. The
indicator is now a `ft.Stack`, so `_refresh` is updated to rebuild the whole
indicator control rather than poking individual attributes:

```python
# home_view.py (inside _refresh)
new_indicator = build_compliance_indicator(state.compliance_summary)
compliance_holder.content = new_indicator
```

The indicator is wrapped in a `ft.Container` holder (like `calendar_holder`) so a
repaint swaps the content rather than mutating `ProgressBar` fields.

### 2. Remove quick-log buttons (`home_view.py`)

The quick-log row and its wiring are removed:

- Delete the `log_buttons = ft.Row(...)` block and remove `log_buttons` from the
  home `ft.Column`.
- Delete `_log_button`, `_on_log_click`, and the now-unused `_BUTTON_COLORS` /
  `_BUTTON_LABELS` / `_BUTTON_ORDER` constants (the picker owns its own
  `PICKER_LABELS`).
- `log_entry` remains in the module (still used by tests and reachable logic) but
  is no longer wired to any button; it is not referenced by the view.
- No `floatingActionButton` / FAB is added anywhere in the view.

The tap path (`_on_day_tap` → `_handle_tap` → `can_open_picker` →
`build_day_type_picker`) is untouched and becomes the sole logging path.

### 3. Responsive square day cells (`calendar_grid.py`, `entry_tile.py`)

Flet's `ft.GridView` with `runs_count=7` already distributes seven columns
across the available width, but it does not force a square aspect — tiles stretch
to the `child_aspect_ratio` default. Two changes make cells square and
width-driven:

- Set `child_aspect_ratio=1.0` on the `ft.GridView` so each cell's width equals
  its height regardless of the available width. This is the responsive mechanism:
  Flet recomputes the column width from the live viewport, and the 1:1 ratio
  keeps every cell square as the width changes.
- Expose a pure `cell_edge(available_width)` helper used by the weekday header
  (and available to tests) so the header can mirror the grid's column width. The
  grid itself relies on `GridView`'s own layout, but the header is a `ft.Row` that
  needs explicit per-column widths to line up, so both read the same formula.

```python
# calendar_grid.py

_COLUMNS = 7
_SPACING = 8
_PADDING = 8


def cell_edge(available_width: float) -> float:
    """Square edge length for one column given the grid's available width.

    Accounts for the grid's outer padding and the inter-column spacing so the
    seven columns plus their gutters exactly fill ``available_width``.
    """
    inner = available_width - 2 * _PADDING - (_COLUMNS - 1) * _SPACING
    return max(0.0, inner / _COLUMNS)
```

The `ft.GridView` gains `child_aspect_ratio=1.0`; `max_extent` is left to
`runs_count` so Flet keeps exactly seven columns:

```python
return ft.GridView(
    controls=controls,
    runs_count=_COLUMNS,
    child_aspect_ratio=1.0,  # square cells (Requirement 4.1)
    spacing=_SPACING,
    run_spacing=_SPACING,
    padding=_PADDING,
    expand=True,
)
```

`build_entry_tile` keeps its container but drops fixed padding that would fight
the square ratio; it fills its grid cell via `expand=True` / `alignment=CENTER`
so the 1:1 ratio from the grid governs its size. The leading blank-placeholder
logic (`first_weekday` blanks before day 1) is unchanged, preserving the Mon–Sun
layout.

### 4. Weekday-name header row (`calendar_grid.py`, `home_view.py`)

A new pure builder renders seven Monday–Sunday labels. To stay aligned above the
grid's columns it uses the same column count and spacing as the grid. Two layout
strategies keep it aligned as the width changes:

- **Primary (self-sizing):** a `ft.Row` of seven `expand=True` cells with the
  same horizontal spacing/padding as the grid. Each cell expands equally, so the
  seven labels occupy equal thirds-of-sevenths of the row width exactly as the
  grid's columns do — alignment is preserved for any width without measuring it.
- `cell_edge` is provided for tests and for any width-pinned fallback, but the
  shipping header uses `expand=True` so it needs no live width.

```python
# calendar_grid.py

WEEKDAY_LABELS: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def build_weekday_header() -> ft.Row:
    """Seven Mon–Sun labels aligned to the 7-column calendar grid."""
    return ft.Row(
        controls=[
            ft.Container(
                content=ft.Text(
                    label, text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD
                ),
                alignment=ft.Alignment.CENTER,
                expand=True,
            )
            for label in WEEKDAY_LABELS
        ],
        spacing=_SPACING,
        # Match the grid's outer padding so column centres line up.
        # (Applied via the holder container in home_view.)
    )
```

In `home_view.build_home_view`, the header is placed directly above the calendar
holder, both inside a padding-matched container so their columns align:

```python
calendar_holder = ft.Container(content=_build_grid(...))
weekday_header = build_weekday_header()

ft.Column(
    controls=[
        compliance_holder,  # circular indicator (was compliance_bar)
        error_text,
        nav_row,  # quick-log Row removed
        weekday_header,  # new
        calendar_holder,
    ],
    spacing=16,
    expand=True,
)
```

## Data Models

No new or changed data models. `ComplianceSummary` is consumed as-is:

| Field            | Type    | Use in this feature                              |
|------------------|---------|--------------------------------------------------|
| `compliance_pct` | `float` | Drives `fill_fraction`, `display_percent`, gate  |
| `total_days`     | `int`   | Scales the required-days target in `days_missing` |
| `denmark_days`   | `int`   | Current office/Denmark days in `days_missing`     |
| `is_compliant`   | `bool`  | Selects compliant vs non-compliant ring colour    |

`COMPLIANCE_THRESHOLD` is a module-level `float` constant in `compliance_bar.py`;
it is the only new value introduced and is frontend-only.

## Error Handling

This is a presentation-only change and introduces no new I/O or failure modes.

- **Missing summary (`None`)**: `build_compliance_indicator(None)` renders a
  neutral empty ring with no fill and no days-missing caption (Requirement 1.4).
- **Degenerate inputs**: `fill_fraction` clamps to `[0, 1]`; `display_percent`
  clamps to `[1, 100]`; `days_missing` floors the shortfall at `0`. A
  `total_days` of `0` yields `required = 0`, so `days_missing` returns `0` rather
  than raising.
- **Threshold guard**: `fill_fraction` guards against a non-positive threshold to
  avoid division by zero (defensive; the shipping constant is positive).
- The existing day-type-picker error handling (classified `APIError` surfaces,
  generation guards) is reused unchanged for all logging.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Fill fraction is proportional and bounded

For any `ComplianceSummary`, `fill_fraction(summary)` equals
`min(1.0, max(0.0, compliance_pct / COMPLIANCE_THRESHOLD))` and always lies in
the inclusive range `[0.0, 1.0]`.

**Validates: Requirements 1.1**

### Property 2: Fill saturates at or above threshold

For any `ComplianceSummary` whose `compliance_pct` is greater than or equal to
`COMPLIANCE_THRESHOLD`, `fill_fraction(summary)` equals `1.0` (a full circular
fill).

**Validates: Requirements 1.2**

### Property 3: Displayed percent is clamped to 1..100

For any `ComplianceSummary`, `display_percent(summary)` is an integer in the
inclusive range `1` to `100`.

**Validates: Requirements 1.3**

### Property 4: Ring colour tracks compliance

For any `ComplianceSummary`, `build_compliance_indicator(summary)` uses the
compliant colour when `is_compliant` is true and the non-compliant colour when it
is false.

**Validates: Requirements 1.5**

### Property 5: Days-missing derivation uses only existing fields and is non-negative

For any `ComplianceSummary`, `days_missing(summary)` is computed purely from
`compliance_pct`, `denmark_days`, and `total_days` (no backend request, no new
field), returns a non-negative integer, and equals
`max(0, ceil(COMPLIANCE_THRESHOLD/100 * total_days) - denmark_days)`.

**Validates: Requirements 2.1, 2.3**

### Property 6: Days-missing is zero when compliant

For any `ComplianceSummary` whose `compliance_pct` is greater than or equal to
`COMPLIANCE_THRESHOLD`, `days_missing(summary)` equals `0`.

**Validates: Requirements 2.2**

### Property 7: Days-missing rounds up partial days

For any `ComplianceSummary` with a non-compliant `compliance_pct`, the result of
`days_missing(summary)` is the ceiling of the real-valued day shortfall, so any
non-zero fractional remaining day is reported as at least one whole day.

**Validates: Requirements 2.4**

### Property 8: Day cells are square

For any available width, each `Day_Cell` produced for the grid has equal width
and height (a `child_aspect_ratio` of `1.0`), so the cell is square.

**Validates: Requirements 4.1**

### Property 9: Seven columns fill the available width

For any available width, `cell_edge(width)` yields a per-column edge such that
seven columns plus their inter-column spacing and outer padding exactly fill the
available width, and the edge scales monotonically with the width.

**Validates: Requirements 4.2**

### Property 10: Grid preserves the Mon–Sun layout and leading blanks

For any year and month, the built grid uses exactly seven columns and is preceded
by a number of leading blank placeholder cells equal to
`calendar.monthrange(year, month)[0]` before day one.

**Validates: Requirements 4.3**

### Property 11: Weekday header aligns and scales with the grid

For any available width, the weekday header exposes exactly seven labels in
Monday-through-Sunday order whose per-column width equals the grid's per-column
width (via the shared seven-column, equal-expand sizing), so each label stays
aligned above its column as the width changes.

**Validates: Requirements 5.2, 5.3**

## Testing Strategy

**Dual approach.** Pure functions (`fill_fraction`, `display_percent`,
`days_missing`, `cell_edge`) are covered by property-based tests with Hypothesis
(the project already uses it — see `.hypothesis/`), while structural and
single-case behaviours are covered by example-based `pytest` tests. All tests run
runtime-free: no Flet app is started.

**Property tests (Hypothesis, ≥100 iterations each):**

- Properties 1–3, 5–9 generate random `ComplianceSummary` values and widths and
  assert the stated invariants. Each test is tagged
  `Feature: ui-refinements, Property N: <text>`.
- Generators cover edge inputs: `compliance_pct` across `[0, 100]` (including the
  threshold boundary), `total_days` including `0`, `denmark_days` in
  `[0, total_days]`, and widths from very small to large.

**Example / structural tests (pytest):**

- Requirement 1.4: `build_compliance_indicator(None)` renders a neutral ring with
  no fill and no caption.
- Requirement 2.3: `days_missing` is a synchronous pure call requiring no client.
- Requirement 3.1 / 3.2: walking the `build_home_view` control tree finds no
  quick-log buttons and no logging FAB.
- Requirement 3.3 / 3.4: tapping a past/today cell opens the picker; a future
  cell does not; the picker is the only logging/edit/clear control.
- Requirement 5.1: `build_weekday_header` returns exactly seven labels in
  `Mon..Sun` order.
- Property 10 is also spot-checked with representative months (a month starting
  Monday, a month starting Sunday).

**Unit-test balance.** Example tests stay focused on specific scenarios and edge
cases; the property tests carry the burden of broad input coverage, so the suite
avoids redundant per-value unit tests.
