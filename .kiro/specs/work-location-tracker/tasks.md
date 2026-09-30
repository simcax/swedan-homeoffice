# Implementation Plan: Work Location Tracker

## Overview

Implement a Python monorepo with two packages — `backend/` (FastAPI + async SQLAlchemy + PostgreSQL) and `app/` (Flet cross-platform UI) — following strict TDD: write failing tests first (red), implement to pass (green), then refactor. All project management uses `uv`. Property-based tests use `hypothesis`; all other tests use `pytest` with `unittest.mock`.

---

## Tasks

- [x] 1. Bootstrap monorepo structure and shared schemas
  - [x] 1.1 Create monorepo layout with backend and app packages
    - Initialise `backend/` and `app/` as uv-managed packages under a workspace root `pyproject.toml`
    - Create `backend/pyproject.toml` with dependencies: `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `asyncpg`, `pydantic`, `pydantic-settings`, `alembic`; dev deps: `pytest`, `pytest-asyncio`, `httpx`, `hypothesis`, `ruff`
    - Create `app/pyproject.toml` with dependencies: `flet`, `httpx`; dev deps: `pytest`, `pytest-asyncio`, `hypothesis`, `ruff`
    - Add `.python-version` (3.12) and commit `uv.lock`
    - _Requirements: 11.1, 11.3_

  - [x] 1.2 Define shared `WorkLocation` enum and Pydantic schemas in `backend/schemas.py`
    - Write `WorkLocation(str, Enum)` with values `home`, `denmark`, `vacation`, `sick`
    - Write `WorkEntryCreate`, `WorkEntryUpdate`, `WorkEntryResponse`, `ComplianceSummary`, `AnnualSummary` exactly as specified in design
    - Include `date_not_in_future` field validator on `WorkEntryCreate`
    - _Requirements: 1.6, 2.2, 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 1.3 Write unit tests for Pydantic schemas (TDD — write tests first)
    - Test `WorkLocation` rejects unknown values
    - Test `WorkEntryCreate` accepts valid locations and today's date
    - Test `WorkEntryCreate.date_not_in_future` raises `ValidationError` for tomorrow and any future date
    - Test `WorkEntryUpdate` accepts only valid `WorkLocation` values
    - _Requirements: 2.2, 12.1, 12.2, 12.3, 12.5_

  - [x] 1.4 Write property test for future-date rejection (Property 2)
    - **Property 2: Future Date Rejection**
    - Generate arbitrary dates strictly after `date.today()` with `hypothesis`
    - Assert `WorkEntryCreate(work_date=future_date, location=...)` always raises `ValidationError`
    - **Validates: Requirements 2.1, 2.2, 12.3**

- [x] 2. Implement backend database layer
  - [x] 2.1 Configure async SQLAlchemy engine and session in `backend/database.py`
    - Read `DATABASE_URL` from env via `pydantic-settings`; rewrite `postgresql://` → `postgresql+asyncpg://`
    - Create `AsyncEngine`, `async_sessionmaker`, and `get_session` dependency
    - Abort startup with a clear log message if `DATABASE_URL` is absent
    - _Requirements: 10.4, 11.1, 11.2, 11.6_

  - [x] 2.2 Define SQLAlchemy ORM model in `backend/models.py`
    - `WorkEntry` mapped class with `id`, `work_date` (unique), `location` (enum), `created_at`, `updated_at`
    - Add B-tree index on `work_date` for monthly query performance
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 2.3 Set up Alembic and create initial migration
    - `alembic init backend/alembic`; configure `env.py` to import the async engine and `Base.metadata`
    - Generate and review the initial migration creating `work_entries` with the `work_location_enum` DB type
    - Ensure migration runs via `CC_POST_BUILD_HOOK`
    - _Requirements: 10.1, 10.2, 10.3, 11.4, 11.5_

- [x] 2.4 Set up GitHub Actions CI/CD pipeline
  - Create `.github/workflows/ci.yml` — lint, test, and build on every push and pull request
    - Trigger on `push` and `pull_request` to `main`
    - Job: **lint** — `uv run ruff check .`
    - Job: **test** — spin up a PostgreSQL service container; run `uv run pytest -v --tb=short`; set `DATABASE_URL` from the service container
    - Job: **build** — verify the package builds cleanly with `uv build`
    - Cache the `.venv` and `uv` download cache between runs using `actions/cache`
    - Use `astral-sh/setup-uv` action to install uv
    - Pin Python to `3.12` via `.python-version`
  - Create `.github/workflows/deploy.yml` — deploy to Clever Cloud on push to `main` (after CI passes)
    - Trigger on `push` to `main` with `needs: [lint, test, build]`
    - Use `CleverCloud/clever-tools` action or install `clever-tools` via npm and run `clever deploy`
    - Store `CLEVER_TOKEN` and `CLEVER_SECRET` as GitHub repository secrets
    - Only deploy if all CI jobs pass
  - Add a `README.md` badge for the CI workflow status
  - _Requirements: 11.2, 11.3, 11.4, 11.5_

- [x] 3. Implement `EntryRepository`
  - [x] 3.1 Write failing tests for `EntryRepository` in `backend/tests/test_entry_repository.py` (TDD red phase)
    - Use `pytest-asyncio` with a test `AsyncSession` fixture backed by a real PostgreSQL test database (or in-memory SQLite via `aiosqlite` for speed); roll back after each test
    - Test `get_by_date` returns `None` when no entry exists
    - Test `create` inserts a row and returns the entry with correct `work_date` and `location`
    - Test `get_by_month` returns entries ordered ascending by `work_date`, returns empty list when none exist
    - Test `update` changes `location` and leaves `work_date` unchanged
    - Test `delete` removes the row so a subsequent `get_by_date` returns `None`
    - Test `get_by_year` returns all entries for the year across all months
    - _Requirements: 3.2, 4.2, 4.3, 5.2, 10.1, 10.2_

  - [x] 3.2 Implement `EntryRepository` in `backend/repository.py` to pass the tests (TDD green phase)
    - Implement `get_by_date`, `get_by_month`, `get_by_year`, `create`, `update`, `delete` using async SQLAlchemy queries
    - `get_by_month` must ORDER BY `work_date ASC`
    - `delete` raises `404`-style exception when `entry_id` not found
    - `update` raises `404`-style exception when `entry_id` not found
    - _Requirements: 3.2, 4.2, 4.3, 4.4, 5.2, 10.1_

  - [x] 3.3 Write property test for entry ordering (Property 6)
    - **Property 6: Entry List Ordering**
    - Generate a shuffled list of distinct dates within a month, insert them in random order, assert `get_by_month` always returns them sorted ascending
    - **Validates: Requirements 5.2**

- [x] 4. Implement `ComplianceService`
  - [x] 4.1 Write failing tests for `ComplianceService` in `backend/tests/test_compliance_service.py` (TDD red phase)
    - Test `calculate_monthly` with empty list returns `total_days=0`, `compliance_pct=0.0`, `is_compliant=False`
    - Test with 2 entries (1 denmark, 1 home) returns `compliance_pct=50.0`, `is_compliant=True`
    - Test with only home entries returns `is_compliant=False`
    - Test vacation and sick days each count as compliant (same as denmark)
    - Test `calculate_annual` returns exactly 12 monthly summaries
    - Test `calculate_annual` months with no entries have `total_days=0`
    - Test annual rollup totals equal sum of monthly breakdown fields
    - _Requirements: 6.3, 6.4, 6.5, 6.6, 7.2, 7.3, 7.4, 7.5, 13.3, 14.3_

  - [x] 4.2 Implement `ComplianceService` in `backend/services/compliance_service.py` to pass tests (TDD green phase)
    - Implement `calculate_monthly` following the Pascal pseudocode in design (loop invariant counting)
    - Implement `calculate_annual` grouping by month, computing per-month summaries, then rolling up
    - `compliance_pct` formula: `((denmark_days + vacation_days + sick_days) / total_days) * 100.0`
    - `is_compliant` iff `compliance_pct >= 50.0`
    - _Requirements: 6.3, 6.4, 6.5, 6.6, 7.2, 7.3, 7.4, 7.5_

  - [x] 4.3 Write property test for compliance partition (Property 3)
    - **Property 3: Compliance Partition**
    - Generate arbitrary non-negative counts for each location type; build entry list; assert `denmark_days + vacation_days + sick_days + home_days == total_days == len(entries)`
    - **Validates: Requirements 6.6, 7.3**

  - [x] 4.4 Write property test for compliance percentage formula (Property 4)
    - **Property 4: Compliance Percentage Formula**
    - For any non-empty entry list assert `compliance_pct == ((denmark + vacation + sick) / total) * 100.0`; for empty list assert `compliance_pct == 0.0` and `is_compliant == False`
    - **Validates: Requirements 6.3, 6.4**

  - [x] 4.5 Write property test for compliance threshold (Property 5)
    - **Property 5: Compliance Threshold**
    - For any arbitrary entry list assert `is_compliant == (compliance_pct >= 50.0)`
    - **Validates: Requirements 6.5**

  - [x] 4.6 Write property test for vacation/sick compliance equivalence (Property 11)
    - **Property 11: Vacation/Sick Compliance Equivalence**
    - Generate entry list; replace each vacation/sick entry with a denmark entry; assert `compliance_pct` and `is_compliant` are unchanged
    - **Validates: Requirements 6.3, 6.4, 13.3, 14.3**

  - [x] 4.7 Write property test for annual breakdown completeness (Property 7)
    - **Property 7: Annual Breakdown Completeness**
    - For any arbitrary set of entries across a year assert `len(monthly_breakdown) == 12` and months with no entries have `total_days == 0`
    - **Validates: Requirements 7.2, 7.5**

  - [ ]* 4.8 Write property test for annual rollup consistency (Property 8)
    - **Property 8: Annual Rollup Consistency**
    - Assert annual `total_days`, `denmark_days`, `vacation_days`, `sick_days`, `home_days` equal sums over `monthly_breakdown`
    - **Validates: Requirements 7.3, 7.4**

- [ ] 5. Implement `EntryService`
  - [x] 5.1 Write failing tests for `EntryService` in `backend/tests/test_entry_service.py` (TDD red phase)
    - Mock `EntryRepository`; test `upsert_entry` calls `repo.update` when `get_by_date` returns an existing entry
    - Test `upsert_entry` calls `repo.create` when `get_by_date` returns `None`
    - Test returned entry has correct `work_date` and `location` in both paths
    - Test `delete_entry` delegates to `repo.delete`
    - Test `get_entries_for_month` delegates to `repo.get_by_month`
    - _Requirements: 1.2, 1.3, 4.2_

  - [x] 5.2 Implement `EntryService` in `backend/services/entry_service.py` to pass tests (TDD green phase)
    - Implement `upsert_entry` following the upsert pseudocode in design
    - Implement `get_entries_for_month` and `delete_entry` as thin delegation methods
    - _Requirements: 1.2, 1.3, 4.2_

  - [ ] 5.3 Write property test for upsert uniqueness (Property 1)
    - **Property 1: Upsert Uniqueness**
    - Generate arbitrary `(work_date, location)` pairs; call `upsert_entry` one or more times for the same date; assert exactly one DB row exists for that date and its location matches the last call
    - **Validates: Requirements 1.2, 1.3, 1.5**

  - [ ] 5.4 Write property test for PATCH updates location (Property 10)
    - **Property 10: PATCH Updates Location**
    - For any existing entry and any valid `WorkLocation`, call `update_entry`; assert returned entry has the new location and unchanged `work_date`
    - **Validates: Requirements 3.2**

  - [ ] 5.5 Write property test for delete removes entry (Property 9)
    - **Property 9: Delete Removes Entry**
    - For any existing entry call `delete_entry`; assert `get_by_date` returns `None` and row count for that date is zero
    - **Validates: Requirements 4.2**

- [ ] 6. Checkpoint — backend services
  - Ensure all backend unit and property tests pass: `uv run pytest backend/tests/ -v`
  - Fix any ruff lint issues: `uv run ruff check backend/ && uv run ruff format backend/`
  - Ask the user if any questions arise before proceeding to routers.

- [x] 7. Implement FastAPI routers and app factory
  - [x] 7.1 Write failing integration tests for the entries router in `backend/tests/test_entries_router.py` (TDD red phase)
    - Use `httpx.AsyncClient` with `ASGITransport` and a test `AsyncSession` that rolls back per test
    - Test `POST /api/v1/entries` with valid body returns 201 and correct JSON
    - Test `POST /api/v1/entries` with future date returns 422
    - Test `POST /api/v1/entries` with invalid location returns 422
    - Test `GET /api/v1/entries?year=&month=` returns list ordered by date
    - Test `PATCH /api/v1/entries/{id}` with valid body returns 200 and updated location, `work_date` unchanged
    - Test `PATCH /api/v1/entries/{id}` for nonexistent id returns 404
    - Test `DELETE /api/v1/entries/{id}` for existing entry returns 204
    - Test `DELETE /api/v1/entries/{id}` for nonexistent entry returns 404
    - Test `GET /api/v1/entries` with month < 1 or > 12, or year < 2000 returns 422
    - _Requirements: 1.1, 1.2, 1.6, 2.1, 3.1, 3.2, 3.3, 3.4, 4.2, 4.3, 4.4, 5.1, 5.2, 5.4_

  - [x] 7.2 Write failing integration tests for the summary router in `backend/tests/test_summary_router.py` (TDD red phase)
    - Test `GET /api/v1/summary/monthly?year=&month=` returns all required fields with correct counts
    - Test `GET /api/v1/summary/monthly` with out-of-range year/month returns 422
    - Test `GET /api/v1/summary/monthly` with no entries returns `total_days=0`, `compliance_pct=0.0`, `is_compliant=false`
    - Test `GET /api/v1/summary/annual?year=` returns `monthly_breakdown` with exactly 12 items
    - Test `GET /api/v1/summary/annual` with invalid year returns 422
    - _Requirements: 6.1, 6.2, 6.3, 6.5, 7.1, 7.2, 7.5, 7.6_

  - [x] 7.3 Implement entries router in `backend/routers/entries.py` (TDD green phase)
    - Implement `GET /`, `POST /`, `PATCH /{entry_id}`, `DELETE /{entry_id}` endpoints
    - Wire `EntryRepository` → `EntryService` inside each handler via `Depends(get_session)`
    - Return 404 with `{"detail": "Entry not found"}` for missing ids
    - Return 409 on unique constraint violation
    - _Requirements: 1.1, 1.2, 1.6, 3.1, 3.2, 3.3, 3.4, 4.2, 4.3, 4.4, 5.1, 5.4_

  - [x] 7.4 Implement summary router in `backend/routers/summary.py` (TDD green phase)
    - Implement `GET /monthly` and `GET /annual` endpoints
    - Wire `EntryRepository` → `ComplianceService` via `Depends(get_session)`
    - Validate year range 2000–2099 and month range 1–12; return 422 with identifying message otherwise
    - _Requirements: 6.1, 6.2, 6.3, 7.1, 7.2, 7.5, 7.6_

  - [x] 7.5 Implement FastAPI app factory in `backend/main.py`
    - Create `FastAPI` app with lifespan that checks `DATABASE_URL` and runs Alembic `upgrade head` before accepting requests
    - Register entries and summary routers; add CORS middleware
    - Bind to `0.0.0.0:8080` when started via `CC_PYTHON_UV_RUN_COMMAND`
    - _Requirements: 11.2, 11.3, 11.4, 11.5_

- [ ] 8. Checkpoint — full backend integration
  - Run all backend tests including integration: `uv run pytest backend/ -v`
  - Verify 204 and 409 error paths work correctly
  - Ask the user if any questions arise before proceeding to the frontend.

- [ ] 9. Implement Flet `APIClient`
  - [ ] 9.1 Write failing tests for `APIClient` in `app/tests/test_api_client.py` (TDD red phase)
    - Mock `httpx.AsyncClient` responses for each method
    - Test `get_entries` returns a list of `WorkEntry` objects
    - Test `post_entry` returns a `WorkEntry` and calls POST with correct payload
    - Test `patch_entry` returns an updated `WorkEntry` and calls PATCH
    - Test `delete_entry` calls DELETE and returns None on 204
    - Test `get_summary` returns a `ComplianceSummary`
    - Test `get_annual_summary` returns an `AnnualSummary`
    - Test that an `httpx.TimeoutException` is caught and re-raised as a custom `APIError`
    - Test that 503 triggers exponential back-off retry (up to 3 attempts: 1 s, 2 s, 4 s)
    - Test that 409 on POST triggers an automatic PATCH retry
    - _Requirements: 9.3, 9.4, 9.6_

  - [ ] 9.2 Implement `APIClient` in `app/api_client.py` (TDD green phase)
    - Implement all methods using `httpx.AsyncClient` with a 10-second timeout
    - Implement exponential back-off for 503 (1 s, 2 s, 4 s, 3 attempts max)
    - Implement 409 → automatic PATCH retry
    - Raise a typed `APIError` on unrecoverable failures
    - _Requirements: 9.3, 9.4, 9.6_

- [ ] 10. Implement `AppState` and state management
  - [ ] 10.1 Write failing tests for `AppState` in `app/tests/test_state.py` (TDD red phase)
    - Test initial state has empty entries dict, `is_loading=False`, `error_message=None`
    - Test applying a new entry updates `entries[date]`
    - Test clearing error resets `error_message` to None
    - _Requirements: 1.4, 1.5_

  - [ ] 10.2 Implement `AppState` dataclass in `app/state.py` (TDD green phase)
    - Implement `AppState` with `entries: dict[str, WorkEntry]`, `selected_month`, `compliance_summary`, `is_loading`, `error_message`
    - _Requirements: 1.4, 1.5, 8.5_

- [ ] 11. Implement Flet UI components
  - [ ] 11.1 Implement `entry_tile.py` — color-coded day tile component
    - Build `build_entry_tile(day: int, entry: WorkEntry | None) -> ft.Container`
    - Color mapping: `denmark` → `RED_700`, `home` → `BLUE_700`, `vacation` → `ORANGE_700`, `sick` → `PURPLE_700`, unlogged → `SURFACE`
    - _Requirements: 8.2, 13.5, 14.5_

  - [ ] 11.2 Implement `compliance_bar.py` — compliance progress bar component
    - Build `build_compliance_bar(summary: ComplianceSummary | None) -> ft.ProgressBar`
    - `value = compliance_pct / 100.0`; color `GREEN_600` when `is_compliant`, `RED_700` otherwise
    - When `summary` is None render bar with `value=0`, `color=SURFACE`, no label
    - _Requirements: 8.1, 8.3, 8.4, 8.5_

  - [ ] 11.3 Implement `calendar_grid.py` — monthly calendar grid
    - Build `build_calendar_grid(year: int, month: int, entries: dict[str, WorkEntry]) -> ft.GridView`
    - Render one `entry_tile` per day in the month; wire long-press handler for edit/delete
    - _Requirements: 5.1, 8.2_

- [ ] 12. Implement Flet views and event handlers
  - [ ] 12.1 Implement `home_view.py` — main calendar screen
    - Four `ft.ElevatedButton` controls for logging (Denmark/Home/Vacation/Sick) with correct `bgcolor` values
    - On button click: call `api_client.post_entry`, update `state.entries`, refresh `compliance_summary`, call `page.update()`
    - On error: display inline error message; preserve calendar state
    - On future-date 422: display error adjacent to the date; do not add entry to state
    - Month navigation arrows call `api_client.get_entries` for the new month
    - _Requirements: 1.1, 1.4, 1.5, 2.3, 2.4, 2.5, 8.1, 8.2, 13.1, 13.5, 13.6, 14.1, 14.5, 14.6_

  - [ ] 12.2 Implement `summary_view.py` — monthly and annual summary screen
    - Render `ComplianceSummary` fields (total, denmark, vacation, sick, home, compliance %) in a card
    - Render annual summary with 12-month breakdown table
    - _Requirements: 6.1, 7.1, 8.1, 8.3, 8.4_

  - [ ] 12.3 Implement edit/delete flow in `home_view.py`
    - Long-press on a calendar tile opens `ft.AlertDialog` with Edit and Delete options
    - Delete path: show confirmation dialog before sending DELETE; on success clear tile; on error show snack bar and keep tile
    - Edit path: show location picker dialog; on confirm send PATCH; on success update tile within 2 seconds; on error show snack bar
    - _Requirements: 3.1, 3.5, 3.6, 4.1, 4.2, 4.5, 4.6_

  - [ ] 12.4 Implement API error handling in views
    - 422 → inline validation message, retain form values, no navigation
    - 404 → `ft.SnackBar` toast, refresh entry list
    - 409 → delegate to `APIClient` retry; if PATCH also fails show error notification
    - Network timeout → banner message, retain form values
    - 503 → delegate to `APIClient` back-off; if all fail show error notification
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ] 12.5 Implement `settings_view.py` — API URL configuration
    - `ft.TextField` for `API_BASE_URL`; persist to local storage via `page.client_storage`
    - _Requirements: 11.1_

- [ ] 13. Implement `main.py` — Flet app entry point and routing
  - Wire `ft.app(main)` with route-based navigation between home, summary, and settings views
  - Initialise `AppState` and `APIClient` from `API_BASE_URL` env/storage on startup
  - _Requirements: 1.4, 5.1, 6.1, 7.1_

- [ ] 14. Checkpoint — full stack integration
  - Run all tests: `uv run pytest -v`
  - Fix any remaining ruff issues in both packages: `uv run ruff check . && uv run ruff format .`
  - Ask the user if any questions arise before finalising deployment config.

- [ ] 15. Deployment configuration
  - [ ] 15.1 Verify Clever Cloud deployment config in `backend/pyproject.toml` and root files
    - Confirm `CC_PYTHON_UV_RUN_COMMAND` is set to `.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8080`
    - Confirm `CC_POST_BUILD_HOOK` is set to `uv run alembic upgrade head`
    - Confirm `CC_PYTHON_UV_SYNC_FLAGS` is `--locked --no-progress`
    - Confirm `.python-version` contains `3.12`
    - Confirm `uv.lock` is committed
    - _Requirements: 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ] 15.2 Write `backend/config.py` with `pydantic-settings` `Settings` class
    - `database_url: str` (required — missing value aborts startup)
    - Rewrite `postgresql://` → `postgresql+asyncpg://` in the engine factory
    - _Requirements: 11.1, 11.2, 11.6_

- [ ] 16. Final checkpoint — all tests pass
  - Run complete test suite: `uv run pytest -v --tb=short`
  - Ensure zero failures and zero warnings
  - Ask the user if any questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; the implementation remains correct without them
- All test tasks follow strict TDD: write the failing test first, then implement the minimum code to pass, then refactor
- Each property-based test maps directly to a named Correctness Property from the design document
- `hypothesis` is used for all property tests; `unittest.mock.AsyncMock` / `MagicMock` for unit test isolation
- Checkpoints ensure incremental validation at key seams (service layer, router layer, full stack)
- Alembic migrations must be idempotent (`upgrade head` is safe to re-run on Clever Cloud)
- Never store `DATABASE_URL` or any credentials in committed files

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "2.2"] },
    { "id": 2, "tasks": ["1.3", "1.4", "2.3", "2.4", "10.1"] },
    { "id": 3, "tasks": ["3.1", "4.1", "10.2"] },
    { "id": 4, "tasks": ["3.2", "4.2", "5.1"] },
    { "id": 5, "tasks": ["3.3", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "5.2"] },
    { "id": 6, "tasks": ["5.3", "5.4", "5.5", "7.1", "7.2"] },
    { "id": 7, "tasks": ["7.3", "7.4"] },
    { "id": 8, "tasks": ["7.5", "9.1", "11.1", "11.2"] },
    { "id": 9, "tasks": ["9.2", "11.3"] },
    { "id": 10, "tasks": ["12.1", "12.2"] },
    { "id": 11, "tasks": ["12.3", "12.4", "12.5"] },
    { "id": 12, "tasks": ["13", "15.1", "15.2"] }
  ]
}
```
