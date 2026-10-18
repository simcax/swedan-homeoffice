# Implementation Plan: Work Day Enhancements

## Overview

This plan implements three enhancements against the existing Flet + FastAPI Work Location Tracker:

1. **Day-type picker** — a new `app/components/day_type_picker.py` (pure gate `can_open_picker`, builder `build_day_type_picker`, and runtime-free coroutines `apply_day_type` / `clear_day_type`), wired into the calendar grid tap handler through `home_view`.
2. **Front-page compliance bar** — align the neutral color to `ft.Colors.SURFACE` in `compliance_bar.py` and verify the existing wiring.
3. **Shared-secret auth** — new `backend/auth.py` dependency, `Settings.app_shared_secret` + startup abort, `.env.example` entry, `APIClient` `X-API-Key` + `AuthError`, new `app/views/login_view.py`, `AppState.screen`/`auth_rejected`, and `main.py` bootstrap + `handle_auth_error`.

The work proceeds backend-first for the auth gate (so the client has a real contract to target), in parallel with the frontend-only picker and compliance changes which touch disjoint files. Each coding task builds on the previous and ends wired into `main.py`/`home_view.py` with no orphaned code.

Testing uses `uv run pytest` with `hypothesis` (minimum 100 iterations per property test) and `ruff` for lint/format. Each property test is tagged **Feature: work-day-enhancements, Property N** and references the design property it validates.

## Tasks

- [x] 1. Day-type picker pure core (eligibility, labels, builder)
  - [x] 1.1 Create `app/components/day_type_picker.py` with eligibility gate and labels
    - Implement `can_open_picker(day: date, today: date | None = None) -> bool` returning `day <= (today or date.today())`
    - Define `PICKER_LABELS: dict[WorkLocation, str]` for `DENMARK`/`HOME`/`VACATION`/`SICK`
    - Implement `build_day_type_picker(work_date, current, on_select, on_clear, on_dismiss) -> ft.AlertDialog` presenting the four location choices plus a Clear action; mark the option matching `current.location` as the recorded choice when `current` is not None
    - Reuse the color map/labels already in `entry_tile.py`/`home_view.py` so the dialog matches the calendar's visual language
    - _Requirements: 1.1, 1.2, 1.3, 1.5_

  - [ ]* 1.2 Write property test for the picker eligibility gate
    - **Feature: work-day-enhancements, Property 1: Future dates never open the picker**
    - Generate dates around `date.today()`; assert `can_open_picker` is `False` for dates strictly after today and `True` for dates on or before today
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 1.1, 1.5**

  - [ ]* 1.3 Write property test for recorded-location indication
    - **Feature: work-day-enhancements, Property 2: Picker indicates the recorded location**
    - For any `WorkEntry` with any `WorkLocation` (`st.sampled_from`), assert the built picker marks exactly the matching option as current and no other option as current
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 1.3**

  - [ ]* 1.4 Write example tests for picker composition and dismiss
    - Assert `build_day_type_picker` produces four location options plus a Clear action (1.2)
    - Assert the dismiss callback closes the dialog and triggers no select/clear (1.4)
    - _Requirements: 1.2, 1.4_

- [x] 2. Day-type picker upsert / clear coroutines
  - [x] 2.1 Implement `apply_day_type` in `app/components/day_type_picker.py`
    - Runtime-free coroutine that reads `state.entries.get(work_date.isoformat())`: POST via `api_client.post_entry` when no existing entry, PATCH via `api_client.patch_entry(existing.id, location)` when one exists
    - On success call `state.apply_entry`, `state.clear_error`, then refresh the current-month summary (reuse the existing `_refresh_summary`/generation-guard helpers from `home_view`)
    - On `APIError` record the classified error and leave `state.entries` unchanged; honor the stale-generation guard
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_

  - [ ]* 2.2 Write property test for upsert routing
    - **Feature: work-day-enhancements, Property 3: Upsert routing (POST vs PATCH)**
    - With a mocked `APIClient`, assert no-existing-entry triggers POST and existing-entry triggers PATCH to that entry id; in both cases exactly one entry for the date remains in `state.entries` with the chosen location
    - Use `hypothesis` (`st.sampled_from(WorkLocation)`, generated eligible dates) with `max_examples >= 100`
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

  - [ ]* 2.3 Write property test for upsert idempotence
    - **Feature: work-day-enhancements, Property 4: Upsert idempotence**
    - Assert applying `apply_day_type` twice with identical inputs yields exactly one entry whose location equals the chosen location (`apply(apply(s)) == apply(s)`)
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 2.1, 2.3, 2.4**

  - [ ]* 2.4 Write property test for upsert error preserving the tile
    - **Feature: work-day-enhancements, Property 5: Upsert error preserves the tile**
    - For any backend `APIError` raised during `apply_day_type`, assert `state.entries` is unchanged and `state.error_message` is populated
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 2.6**

  - [x] 2.5 Implement `clear_day_type` in `app/components/day_type_picker.py`
    - Short-circuit with no DELETE and unchanged state when no entry exists for the date (3.4)
    - Otherwise delegate to the existing `delete_entry` logic (DELETE by entry id), remove the date from `state.entries` on success, and refresh the summary (3.1, 3.2)
    - On `APIError` keep the entry visible and populate `state.error_message` (3.5)
    - _Requirements: 3.1, 3.2, 3.4, 3.5_

  - [ ]* 2.6 Write property test for clear-deletes-only-when-present
    - **Feature: work-day-enhancements, Property 6: Clear deletes only when an entry exists**
    - Assert existing-entry triggers a DELETE for that id and removes the date on success; no-entry triggers no DELETE and leaves state unchanged
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 3.1, 3.2, 3.4**

  - [ ]* 2.7 Write property test for clear error keeping the entry visible
    - **Feature: work-day-enhancements, Property 7: Clear error keeps the entry visible**
    - For any backend `APIError` during `clear_day_type` on a date with an existing entry, assert the entry remains in `state.entries` and `state.error_message` is populated
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 3.5**

- [x] 3. Wire the picker into the calendar grid and home view
  - [x] 3.1 Add `on_day_tap` to `app/components/calendar_grid.py`
    - Add `on_day_tap: Callable[[int], None] | None = None` to `build_calendar_grid` alongside the existing long-press hook; bind each day tile's `tile.on_click` to a handler carrying its day number
    - Preserve the existing long-press edit/delete behavior unchanged
    - _Requirements: 1.1_

  - [x] 3.2 Wire the tap handler in `app/views/home_view.py`
    - Resolve the tapped day to a `date` in `state.selected_month`; return immediately when `can_open_picker(day)` is `False` (1.5)
    - Open `build_day_type_picker(...)` via `page.show_dialog`, passing `state.entries.get(iso)` as `current`
    - On select → `page.run_task(apply_day_type(...))` then refresh + `page.pop_dialog`; on error reuse the existing `_surface_error` classification (2.6)
    - On clear → `page.run_task(clear_day_type(...))` then refresh + close (3.3); on dismiss → `page.pop_dialog` only (1.4)
    - On success recolor the tile and recalc the compliance bar via the existing `_refresh()` (2.4, 2.5, 3.2)
    - _Requirements: 1.1, 1.4, 1.5, 2.4, 2.5, 2.6, 3.2, 3.3, 3.5_

  - [ ]* 3.3 Write example tests for home-view picker wiring
    - Assert tapping a future day never opens the picker (1.5)
    - Assert successful select/clear close the dialog (2.5, 3.3)
    - _Requirements: 1.5, 2.5, 3.3_

- [x] 4. Front-page compliance bar neutral color
  - [x] 4.1 Align neutral color in `app/components/compliance_bar.py`
    - Change the `summary is None` branch to use `ft.Colors.SURFACE` (replacing `SURFACE_CONTAINER_HIGHEST`), keeping `value=0` and no tooltip/label
    - Verify `build_compliance_bar` already renders `value = clamp(compliance_pct / 100.0)`, `GREEN_600` when compliant and `RED_700` when not
    - Confirm `home_view.build_home_view` places the bar at the top and `_refresh()` rebuilds it after mutations
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 4.2 Write property test for compliance-bar rendering
    - **Feature: work-day-enhancements, Property 8: Compliance bar reflects the summary**
    - For any `ComplianceSummary`, assert `value == clamp(compliance_pct / 100.0, 0.0, 1.0)` and color is `GREEN_600` when `is_compliant` else `RED_700`
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 4.1, 4.2, 4.3**

  - [ ]* 4.3 Write example tests for neutral bar and refresh
    - Assert `build_compliance_bar(None)` is neutral (`ft.Colors.SURFACE`, `value=0`, no tooltip) (4.4)
    - Assert `_refresh()` rebuilds the bar from an updated summary (4.5)
    - _Requirements: 4.4, 4.5_

- [x] 5. Checkpoint - frontend picker + compliance
  - Run `uv run ruff check .` and `uv run ruff format .`, then `uv run pytest`. Ensure all tests pass, ask the user if questions arise.

- [x] 6. Backend shared-secret configuration and auth dependency
  - [x] 6.1 Add `app_shared_secret` to `backend/config.py`
    - Add `app_shared_secret: str | None = None` (from `APP_SHARED_SECRET`), a `SharedSecretConfigurationError`, and a `required_shared_secret` property that raises with a clear message when blank/missing
    - Add/confirm a `get_settings` provider for dependency injection
    - _Requirements: 7.1_

  - [x] 6.2 Create `backend/auth.py` with the verify dependency
    - Define `API_KEY_HEADER = "X-API-Key"`, `AuthError(HTTPException)` (401), and `verify_api_key(x_api_key: Annotated[str | None, Header(alias=API_KEY_HEADER)] = None, settings = Depends(get_settings))`
    - Allow the request only when the header equals the expected secret, using `secrets.compare_digest` for constant-time comparison; otherwise raise `AuthError`
    - _Requirements: 7.2, 7.3_

  - [ ]* 6.3 Write property test for backend secret verification
    - **Feature: work-day-enhancements, Property 13: The backend accepts only the exact secret**
    - Build an app via `create_app()` with a `get_settings` override supplying a known secret and an in-memory SQLite session override; drive a guarded route with generated header/secret pairs (equal and unequal, plus absent)
    - Assert the handler is reached when `H == S` and HTTP 401 is returned otherwise
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 7.2, 7.3**

  - [ ]* 6.4 Write example test for config sourcing
    - Assert `Settings` reads `APP_SHARED_SECRET` only from the environment (7.1)
    - _Requirements: 7.1_

- [x] 7. Guard routers and abort startup when the secret is missing
  - [x] 7.1 Attach the dependency and startup check in `backend/main.py`
    - Include the entries and summary routers with `dependencies=[Depends(verify_api_key)]` so every API route is guarded uniformly
    - In the lifespan, when `validate_config` is on, read `settings.required_shared_secret` so a missing `APP_SHARED_SECRET` raises `SharedSecretConfigurationError`, logs the variable name, and aborts startup; keep tests on `validate_config=False`
    - _Requirements: 7.2, 7.3, 7.4_

  - [x] 7.2 Add `APP_SHARED_SECRET` to `.env.example`
    - Add an `APP_SHARED_SECRET=` entry with a documenting comment (empty placeholder, no real secret)
    - _Requirements: 7.5_

  - [ ]* 7.3 Write integration test for the guarded route
    - Through `create_app()` + dependency override, assert `GET /api/v1/summary/monthly` returns 401 with no/wrong header and 200 with the correct header, end-to-end through dependency and router
    - _Requirements: 7.2, 7.3_

  - [ ]* 7.4 Write smoke tests for startup abort and `.env.example`
    - Assert building/starting the app with `APP_SHARED_SECRET` unset (and `validate_config=True`) aborts startup and logs the variable name (7.4)
    - Assert `.env.example` contains an `APP_SHARED_SECRET` entry (7.5)
    - _Requirements: 7.4, 7.5_

- [x] 8. Checkpoint - backend auth
  - Run `uv run ruff check .` and `uv run ruff format .`, then `uv run pytest`. Ensure all tests pass, ask the user if questions arise.

- [x] 9. API client secret handling and AuthError
  - [x] 9.1 Add mutable secret + `X-API-Key` header to `app/api_client.py`
    - Add `secret` constructor arg, `set_secret`, `has_secret`, and `_headers()` returning `{"X-API-Key": secret}` when set; merge `_headers()` into every outgoing request in `_request` (6.1)
    - Add `AuthError(APIError)` and detect HTTP 401 in `_request` before generic status handling so callers can distinguish rejection; the 401 branch takes precedence over 503 back-off and 409 PATCH-retry (8.1)
    - _Requirements: 6.1, 8.1_

  - [ ]* 9.2 Write property test for header on every request
    - **Feature: work-day-enhancements, Property 12: Every request carries the configured secret**
    - With a mocked `httpx.AsyncClient` capturing outgoing requests, for any configured secret `S` and any public `APIClient` method, assert the `X-API-Key` header equals `S`
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 6.1**

  - [ ]* 9.3 Write example test for no-secret client
    - Assert a client with no secret sends no `X-API-Key` header (6.2)
    - _Requirements: 6.2_

- [x] 10. Login view, screen state, and secret storage helpers
  - [x] 10.1 Add screen/auth state to `app/state.py`
    - Add `Screen(Enum)` with `LOGIN`/`HOME`, `AppState.screen: Screen = Screen.LOGIN`, and `AppState.auth_rejected: bool = False`
    - _Requirements: 5.1, 8.3_

  - [x] 10.2 Create `app/views/login_view.py` with pure helpers and view builder
    - Implement `validate_secret`, `load_secret`, `save_secret`, `clear_secret`, `resolve_initial_screen`, and `APP_SECRET_KEY`; extend the `KeyValueStorage` protocol with `remove(key)`
    - Build a thin login view that shows a validation message when `auth_rejected` or on empty submit
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 8.3_

  - [ ]* 10.3 Write property test for the initial screen gate
    - **Feature: work-day-enhancements, Property 9: Initial screen gate**
    - For any stored-secret value, assert `resolve_initial_screen` returns `HOME` for a non-blank string and `LOGIN` for `None`/empty/whitespace-only
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 5.1, 5.2**

  - [ ]* 10.4 Write property test for empty-secret rejection
    - **Feature: work-day-enhancements, Property 10: Empty secret is rejected**
    - For whitespace-only/empty strings assert `validate_secret` returns a non-null message; for strings with a non-whitespace char assert it returns `None`
    - Use `hypothesis` (`st.text()`) with `max_examples >= 100`
    - **Validates: Requirements 5.4**

  - [ ]* 10.5 Write example test for the rejected-secret message
    - Assert the login view shows the "secret rejected" message when `state.auth_rejected` is set (8.3)
    - _Requirements: 8.3_

- [x] 11. Wire auth into the app bootstrap
  - [x] 11.1 Bootstrap initial screen in `app/main.py`
    - On startup `await load_secret(storage)`; when present `api_client.set_secret(secret)` and render HOME, otherwise render LOGIN and skip `_load_initial_data` (5.1, 5.2, 6.2)
    - Implement the login submit handler: validate, persist via `save_secret`, `api_client.set_secret`, load initial data, navigate to HOME; empty input stays on LOGIN with a validation message (5.3, 5.4)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.2_

  - [x] 11.2 Implement `handle_auth_error` in `app/main.py`
    - Central handler invoked when any `page.run_task` coroutine raises `AuthError`: `await clear_secret(storage)`, `api_client.set_secret(None)`, set `state.auth_rejected = True`, `state.screen = Screen.LOGIN`, repaint showing the rejected message
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ]* 11.3 Write property test for successful-login persistence
    - **Feature: work-day-enhancements, Property 11: Non-empty secret is persisted and sent**
    - For any non-empty secret `S`, after a successful login submit assert storage holds trimmed `S`, `api_client.has_secret` is true, and the resolved screen is HOME
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 5.3**

  - [ ]* 11.4 Write property test for 401 clearing the secret
    - **Feature: work-day-enhancements, Property 14: A 401 clears the stored and in-memory secret**
    - For any `APIClient` method receiving a 401, assert the stored secret is removed, `has_secret` becomes false, and the resolved screen becomes LOGIN
    - Use `hypothesis` with `max_examples >= 100`
    - **Validates: Requirements 8.1, 8.2**

- [x] 12. Final checkpoint - full suite
  - Run `uv run ruff check .` and `uv run ruff format .`, then `uv run pytest`. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific requirements for traceability; every property-based test references its design property number.
- Property tests use `hypothesis` with a minimum of 100 iterations and are tagged **Feature: work-day-enhancements, Property N**.
- Pure UI-presence, config-sourcing, and startup-abort criteria (1.2, 1.4, 2.5, 3.3, 4.4, 4.5, 6.2, 7.1, 7.4, 7.5, 8.3) are covered by example/smoke/integration tests rather than properties, per the design.
- All tests run with `uv run pytest`; lint/format with `uv run ruff check .` / `uv run ruff format .`.
- Checkpoints provide incremental validation after each feature slice.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1", "4.1", "6.1", "9.1", "10.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "2.1", "4.2", "4.3", "6.2", "9.2", "9.3", "10.2"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "2.5", "6.3", "6.4", "7.1", "7.2", "10.3", "10.4", "10.5", "11.1"] },
    { "id": 3, "tasks": ["2.6", "2.7", "3.2", "7.3", "7.4", "11.2"] },
    { "id": 4, "tasks": ["3.3", "11.3", "11.4"] }
  ]
}
```
