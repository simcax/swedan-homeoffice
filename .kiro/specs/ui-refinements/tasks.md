# Implementation Plan: UI Refinements

## Overview

Frontend-only Flet (Python) changes across four component/view files. Pure
functions (`fill_fraction`, `display_percent`, `days_missing`, `cell_edge`) are
implemented first and verified with Hypothesis property-based tests, then the
Flet builder wrappers (circular indicator, weekday header, square grid) are
built on top, and finally the home view is wired to drop quick-log buttons and
render the new indicator and header. Each step builds on the previous and ends
with the view integration so there is no orphaned code.

All code is Python (Flet 1.0.2) matching the existing codebase. Tests run
runtime-free (no Flet app started), using `pytest` and `hypothesis`, run via
`uv run pytest`.

## Tasks

- [x] 1. Add compliance threshold constant and pure derivation functions
  - [x] 1.1 Add `COMPLIANCE_THRESHOLD`, `fill_fraction`, `display_percent`, and `days_missing` to `app/components/compliance_bar.py`
    - Add module-level `COMPLIANCE_THRESHOLD: float = 60.0` with an explanatory comment
    - Implement `fill_fraction(summary)` clamped to `[0.0, 1.0]` with a non-positive-threshold guard
    - Implement `display_percent(summary)` returning an int clamped to `[1, 100]`
    - Implement `days_missing(summary)` using only `compliance_pct`, `denmark_days`, `total_days`; `max(0, ceil(threshold/100 * total_days) - denmark_days)`; return 0 when already compliant; handle `total_days == 0`
    - Import `math` and `ComplianceSummary` from `app.api_client`
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4_

  - [ ]* 1.2 Write property test for fill fraction proportional and bounded
    - **Property 1: Fill fraction is proportional and bounded**
    - **Validates: Requirements 1.1**
    - Add to `app/tests/test_compliance_bar.py`; generate random `ComplianceSummary`; assert `fill_fraction` equals the clamped ratio and lies in `[0.0, 1.0]`

  - [ ]* 1.3 Write property test for fill saturation at/above threshold
    - **Property 2: Fill saturates at or above threshold**
    - **Validates: Requirements 1.2**
    - Generate summaries with `compliance_pct >= COMPLIANCE_THRESHOLD`; assert `fill_fraction == 1.0`

  - [ ]* 1.4 Write property test for displayed percent clamp
    - **Property 3: Displayed percent is clamped to 1..100**
    - **Validates: Requirements 1.3**
    - Assert `display_percent` is an int in the inclusive range `1..100`

  - [ ]* 1.5 Write property test for days-missing derivation
    - **Property 5: Days-missing derivation uses only existing fields and is non-negative**
    - **Validates: Requirements 2.1, 2.3**
    - Assert `days_missing` is non-negative and equals `max(0, ceil(threshold/100 * total_days) - denmark_days)`; no client/request needed

  - [ ]* 1.6 Write property test for days-missing zero when compliant
    - **Property 6: Days-missing is zero when compliant**
    - **Validates: Requirements 2.2**
    - Generate summaries with `compliance_pct >= COMPLIANCE_THRESHOLD`; assert `days_missing == 0`

  - [ ]* 1.7 Write property test for days-missing rounding up
    - **Property 7: Days-missing rounds up partial days**
    - **Validates: Requirements 2.4**
    - For non-compliant summaries, assert the result equals the ceiling of the real-valued shortfall (partial day counts as one whole day)

- [x] 2. Build the circular compliance indicator
  - [x] 2.1 Implement `build_compliance_indicator` in `app/components/compliance_bar.py`
    - Return an `ft.Stack` layering an `ft.ProgressRing` under a centred `ft.Column` (percent label + days-missing caption)
    - Use `fill_fraction` for ring value, `display_percent` for the label, `days_missing` for the caption
    - Select compliant vs non-compliant colour from `summary.is_compliant`
    - Render a neutral empty ring (no fill, no caption) when `summary is None`
    - Keep/replace the old `build_compliance_bar` per design (indicator supersedes the ProgressBar)
    - _Requirements: 1.1, 1.4, 1.5_

  - [ ]* 2.2 Write property test for ring colour tracking compliance
    - **Property 4: Ring colour tracks compliance**
    - **Validates: Requirements 1.5**
    - Generate random summaries; assert the ring uses the compliant colour iff `is_compliant` is true

  - [ ]* 2.3 Write example test for neutral empty state
    - `build_compliance_indicator(None)` renders a neutral ring with no fill and no days-missing caption
    - _Requirements: 1.4_

- [x] 3. Checkpoint - compliance indicator
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Add responsive square cells and cell-sizing helper
  - [x] 4.1 Add `cell_edge` helper and `child_aspect_ratio=1.0` to `app/components/calendar_grid.py`
    - Add module constants `_COLUMNS = 7`, `_SPACING = 8`, `_PADDING = 8` (reuse existing if present)
    - Implement pure `cell_edge(available_width)` accounting for outer padding and inter-column spacing; floor at `0.0`
    - Set `child_aspect_ratio=1.0` on the `ft.GridView`; keep `runs_count=_COLUMNS`, spacing, padding, `expand=True`
    - Preserve leading blank-placeholder logic and Mon–Sun layout
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 4.2 Update `build_entry_tile` in `app/components/entry_tile.py` for square-fill cells
    - Accept an optional edge size; drop fixed padding that fights the square ratio
    - Fill the grid cell via `expand=True` / centred alignment so the grid's 1:1 ratio governs size
    - _Requirements: 4.1_

  - [ ]* 4.3 Write property test for square cells
    - **Property 8: Day cells are square**
    - **Validates: Requirements 4.1**
    - Add to `app/tests/test_entry_tile.py` or `test_calendar_grid.py`; assert the grid cell aspect ratio is `1.0` (width equals height)

  - [ ]* 4.4 Write property test for seven columns filling width
    - **Property 9: Seven columns fill the available width**
    - **Validates: Requirements 4.2**
    - Add to `app/tests/test_calendar_grid.py`; assert `7*cell_edge(w) + 6*spacing + 2*padding == w` (within tolerance) and `cell_edge` scales monotonically with width

  - [ ]* 4.5 Write property/example test for Mon–Sun layout and leading blanks
    - **Property 10: Grid preserves the Mon–Sun layout and leading blanks**
    - **Validates: Requirements 4.3**
    - Assert exactly seven columns and leading blank count equals `calendar.monthrange(year, month)[0]`; spot-check a month starting Monday and one starting Sunday

- [x] 5. Add the weekday-name header row
  - [x] 5.1 Implement `WEEKDAY_LABELS` and `build_weekday_header` in `app/components/calendar_grid.py`
    - Add `WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")`
    - Return an `ft.Row` of seven `expand=True` centred label containers using the same `_SPACING` as the grid
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ]* 5.2 Write example test for weekday header labels
    - `build_weekday_header` returns exactly seven labels in `Mon..Sun` order
    - _Requirements: 5.1_

  - [ ]* 5.3 Write property test for weekday header alignment/scaling
    - **Property 11: Weekday header aligns and scales with the grid**
    - **Validates: Requirements 5.2, 5.3**
    - Assert seven labels in Mon–Sun order with equal-expand sizing so per-column width matches the grid's (shared seven-column spacing)

- [x] 6. Checkpoint - calendar grid and header
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Wire the home view
  - [x] 7.1 Render the circular indicator and remove quick-log buttons in `app/views/home_view.py`
    - Wrap the indicator in a `ft.Container` holder; `_refresh` rebuilds the indicator via `build_compliance_indicator(state.compliance_summary)` and swaps `holder.content`
    - Replace the former `build_compliance_bar` usage in the home `ft.Column`
    - Delete the `log_buttons` `ft.Row` and remove it from the column; delete `_log_button`, `_on_log_click`, and unused `_BUTTON_*` constants
    - Add no floating action button / FAB
    - Keep `log_entry` in the module but unreferenced by the view; keep the tap path (`_on_day_tap` → picker) as the sole logging path
    - _Requirements: 1.1, 1.4, 1.5, 3.1, 3.2, 3.3, 3.4_

  - [x] 7.2 Place the weekday header above the calendar holder in `app/views/home_view.py`
    - Insert `build_weekday_header()` directly above `calendar_holder`, padding-matched so columns align
    - _Requirements: 5.1, 5.2_

  - [ ]* 7.3 Write structural tests for the home view control tree
    - Walk `build_home_view` tree: assert no quick-log buttons and no logging FAB (3.1, 3.2)
    - Assert tapping a past/today cell opens the picker, a future cell does not, and the picker is the only logging/edit/clear control (3.3, 3.4)
    - Assert the weekday header appears above the calendar grid (5.1)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 5.1_

- [x] 8. Final checkpoint - full suite and lint
  - Run `uv run pytest` and `uv run ruff check .` / `uv run ruff format .`; ensure all tests pass and no warnings. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (tests) and can be skipped for a faster MVP.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation.
- Property tests validate the universal correctness properties from the design;
  tag each with `Feature: ui-refinements, Property N: <text>` and run ≥100
  iterations with Hypothesis.
- Example/structural tests cover single-case behaviours (empty state, control
  tree, label order).
- All changes are frontend-only; no backend/API/model changes.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "4.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "2.1", "4.2", "4.4", "4.5", "5.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "4.3", "5.2", "5.3", "7.1"] },
    { "id": 3, "tasks": ["7.2"] },
    { "id": 4, "tasks": ["7.3"] }
  ]
}
```
