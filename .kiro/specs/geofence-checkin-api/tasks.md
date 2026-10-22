# Implementation Plan: Geofence Check-In API

## Overview

This plan implements the single authenticated `POST /api/v1/checkin` endpoint by building up from a pure, property-testable resolver/validation core, then configuring the engine connection timeout for fast-fail 503, then wiring the router into `create_app` reusing `EntryService.upsert_entry`, `WorkEntryResponse`, `get_session`, and `verify_api_key`. Property-based tests (hypothesis, >=100 iterations) validate the 14 correctness properties; example/integration/smoke tests cover auth, 409, 503, endpoint wiring, and the upsert-only write assertion.

All package management uses `uv`; lint/format with `uv run ruff`; tests run with `uv run pytest`.

## Tasks

- [x] 1. Add timezone data dependency and confirm tooling
  - [x] 1.1 Add tzdata and sync dev dependencies
    - Run `uv add tzdata` so `Europe/Copenhagen` is resolvable via stdlib `zoneinfo` in CI/runtime even when the base image lacks system tz data
    - Run `uv sync` and confirm `hypothesis` is available as a dev dependency (add via `uv add --dev hypothesis` only if missing)
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 2. Implement the pure resolver/validation core
  - [x] 2.1 Create `backend/services/checkin_resolver.py` with the pure helpers and value object
    - Define `ResolvedCheckIn` value object (`work_date: date`, `location: WorkLocation`)
    - Implement `local_date(now: datetime | None = None) -> date` using `datetime.now(ZoneInfo("Europe/Copenhagen"))` (or converting an injected aware `now`) and returning `.date()`
    - Implement `is_special_day(location: WorkLocation) -> bool` returning `location in {WorkLocation.VACATION, WorkLocation.SICK}`
    - Reuse the existing `WorkLocation` enum from `backend/schemas.py`; do not redefine location values
    - _Requirements: 2.1, 2.2, 2.3, 4.2, 4.4_

  - [x] 2.2 Implement `resolve_location` with defaulting and validation
    - Return the exact-match `WorkLocation` for a non-empty, case-sensitive exact enum string
    - Return `WorkLocation.DENMARK` (Default_Location) when input is `None` or empty string
    - Raise `HTTPException(status_code=422, detail=...)` with a location-not-allowed message for any non-empty, non-matching value
    - _Requirements: 1.3, 1.5, 5.6_

  - [ ]* 2.3 Write property test for location resolution and defaulting
    - **Property 1: Location resolution and defaulting**
    - **Validates: Requirements 1.3, 1.5**
    - Tag with `# Feature: geofence-checkin-api, Property 1: ...`; `@settings(max_examples=100, deadline=None)`; locations via `st.sampled_from(list(WorkLocation))`
    - Place in `backend/tests/test_checkin_resolver_properties.py`

  - [ ]* 2.4 Write property test for invalid location rejection
    - **Property 13: Invalid location values are rejected**
    - **Validates: Requirements 5.6**
    - Generate non-empty strings not equal to any `WorkLocation` value; assert `HTTPException(422)` raised and no write occurs (pure helper, no DB)

  - [x] 2.5 Implement `resolve_date` with strict parsing, defaulting, and range/future validation
    - Parse strictly against `YYYY-MM-DD` (four-digit year, two-digit month/day); default to the passed `today` when input is `None` or empty
    - Raise `HTTPException(422)` with distinct `detail` messages for: malformed/non-ISO text, pattern-valid but non-real calendar dates (e.g. `2025-02-30`, `2025-13-01`), dates `< 2000-01-01` (out-of-range), and dates strictly `> today` (future); accept `date == today`
    - _Requirements: 1.4, 1.6, 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ]* 2.6 Write property test for valid date resolution and defaulting
    - **Property 2: Valid date resolution and defaulting**
    - **Validates: Requirements 1.4, 1.6**
    - Valid in-range dates via `st.dates(min_value=date(2000,1,1), max_value=today)`; assert parsed value returned and `today` returned for `None`/empty

  - [ ]* 2.7 Write property test for Local_Date zone conversion
    - **Property 3: Local_Date is the Europe/Copenhagen calendar date**
    - **Validates: Requirements 2.1, 2.2, 2.3**
    - Aware UTC instants via `st.datetimes(timezones=st.just(timezone.utc))`, biased toward late-March/late-October DST transitions and local midnight; assert `local_date(now) == now.astimezone(ZoneInfo("Europe/Copenhagen")).date()`

  - [ ]* 2.8 Write property test for future-date rejection
    - **Property 10: Future dates are rejected**
    - **Validates: Requirements 5.1, 5.2**
    - Future dates via `st.dates(min_value=today + 1 day)` assert 422; `date == today` accepted (boundary edge)

  - [ ]* 2.9 Write property test for malformed and non-real date rejection
    - **Property 11: Malformed and non-real dates are rejected**
    - **Validates: Requirements 5.3, 5.4**
    - `st.text()` filtered to non-ISO plus explicit impossible-but-pattern-valid generators (`YYYY-MM-DD` with month/day out of range); assert 422 and no write

  - [ ]* 2.10 Write property test for pre-2000 date rejection
    - **Property 12: Dates before 2000-01-01 are rejected**
    - **Validates: Requirements 5.5**
    - Real dates via `st.dates(max_value=date(1999,12,31))`; assert out-of-range 422 and no write

- [x] 3. Configure engine connection timeout for fast-fail 503
  - [x] 3.1 Add 5-second timeouts to `get_engine` in `backend/database.py`
    - Pass `pool_timeout=5` and `connect_args={"timeout": 5}` to `create_async_engine` (keep existing `pool_pre_ping=True`, `echo=False`)
    - Ensure an unreachable database surfaces as `DatabaseUnavailableError` -> 503 within ~5s rather than hanging
    - _Requirements: 8.1_

  - [ ]* 3.2 Write smoke test asserting the engine is constructed with the 5s timeout
    - Assert `create_async_engine` is called with `pool_timeout=5` and `connect_args={"timeout": 5}` (patch/spy construction as in existing config/DB tests)
    - _Requirements: 8.1_

- [x] 4. Implement the check-in router
  - [x] 4.1 Create `backend/routers/checkin.py` with the POST `/api/v1/checkin` endpoint
    - Define `router = APIRouter(prefix="/api/v1", tags=["checkin"])` and `@router.post("/checkin", response_model=WorkEntryResponse)`
    - Accept optional `location` and `date` (aliased) query params and no request body; ignore any body if present
    - Resolve via `resolve_location` and `resolve_date(raw, local_date())`; read the existing entry via `EntryRepository.get_by_date` first for special-day protection
    - If existing entry is a Special_Day, return it unchanged with status 200; otherwise call `EntryService.upsert_entry(date, location)` as the sole write path
    - Set status dynamically via the `Response` object: 201 when a new row is created, 200 when an existing row is updated or left unchanged
    - Catch `IntegrityError`, `await db.rollback()`, raise `HTTPException(409, "Entry already exists for this date")` (mirror `entries.create_entry`)
    - Depend on `get_session` so connectivity failures become 503 automatically; serialize via `WorkEntryResponse`
    - _Requirements: 1.1, 1.2, 1.7, 4.1, 4.2, 4.3, 4.4, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 8.2, 8.3, 8.4_

  - [x] 4.2 Register the router in `create_app` guarded by the shared secret
    - Add `app.include_router(checkin.router, dependencies=[Depends(verify_api_key)])` in `backend/main.py` (same pattern as other routers)
    - Confirm the existing `DatabaseUnavailableError`/`OperationalError`/`InterfaceError` -> 503 handlers cover the new route
    - _Requirements: 3.1, 8.1, 8.2, 8.3_

- [x] 5. Checkpoint - Ensure all tests pass
  - Run `uv run ruff check .`, `uv run ruff format .`, and `uv run pytest`
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Write write-path property tests (service + DB)
  - [x]* 6.1 Write property test for bare check-in creating a Local_Date denmark entry
    - **Property 4: Bare check-in creates a Local_Date denmark entry**
    - **Validates: Requirements 1.2**
    - Fresh in-memory SQLite per example (mirror `test_entry_repository_properties.py`); drive endpoint via `AsyncClient` or service directly; assert one row with `work_date == local_date()` and `location == denmark`
    - Place write-path properties in `backend/tests/test_checkin_properties.py`

  - [x]* 6.2 Write property test for create on an empty date
    - **Property 5: Check-in on an empty date creates the resolved entry**
    - **Validates: Requirements 4.1**
    - Resolved `(date, location)` with no existing row; assert exactly one row created with the resolved location

  - [x]* 6.3 Write property test for special-day protection
    - **Property 6: Special-day protection preserves the stored entry**
    - **Validates: Requirements 4.2, 4.4**
    - Seed a `vacation`/`sick` entry; range incoming `location` over all four `WorkLocation` values; assert `location`, `work_date`, `created_at` unchanged and exactly one row

  - [x]* 6.4 Write property test for working-location overwrite
    - **Property 7: Working-location entries are overwritten**
    - **Validates: Requirements 4.3**
    - Seed a `home`/`denmark` entry; assert `location` set to resolved value and exactly one row

  - [x]* 6.5 Write property test for idempotence
    - **Property 8: Check-in idempotence**
    - **Validates: Requirements 4.5**
    - Apply check-in twice with no intervening change; assert identical persisted `work_date`/`location` and exactly one row

  - [x]* 6.6 Write property test for the at-most-one-entry-per-date invariant
    - **Property 9: At-most-one entry per calendar date**
    - **Validates: Requirements 7.2**
    - Apply a generated sequence of resolved check-ins to an initially empty DB; assert at most one row per `work_date`

  - [x]* 6.7 Write property test for the response contract
    - **Property 14: Response contract**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
    - Drive the endpoint via `AsyncClient`; assert exact field set `{id, work_date, location, created_at, updated_at}`, types (positive int id, ISO date/date-times, enum-string location), and 201-on-create / 200-on-update-or-unchanged

- [x] 7. Write example, integration, and smoke tests
  - [x]* 7.1 Write endpoint-existence and no-body tests
    - Assert the route exists and accepts POST; a request with no body and a request with an arbitrary JSON body succeed identically
    - _Requirements: 1.1, 1.7_

  - [x] 7.2 Write authentication tests
    - Valid `X-API-Key` reaches the handler; missing, wrong, and empty-string keys each return 401 with no DB change (empty key is an explicit edge case)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x]* 7.3 Write upsert-only write assertion test
    - Spy/mock asserting the handler performs writes exclusively through `EntryService.upsert_entry` and issues no other write path
    - _Requirements: 7.1_

  - [x]* 7.4 Write 409 conflict integration test
    - Force an `IntegrityError` on write; assert 409, no duplicate row, and the already-persisted entry unchanged (mirror entries-router conflict handling)
    - _Requirements: 7.3_

  - [x]* 7.5 Write 503 availability integration tests
    - Simulate a connectivity failure at the session boundary (as in `test_db_errors.py`); assert 503 with body `{"detail": "Database unavailable"}`, a non-2xx status, and no persisted/partial change
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x]* 7.6 Write explicit non-real-date example tests
    - Assert `2025-02-30` and `2025-13-01` return 422; assert `date == Local_Date` is accepted
    - _Requirements: 5.2, 5.4_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Run `uv run ruff check .`, `uv run ruff format .`, and `uv run pytest` (confirm each property test runs >=100 iterations with the required tag comment)
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP, but they provide the correctness coverage described in the design.
- Each task references specific granular requirements for traceability.
- Property tests validate the 14 universal correctness properties; each property is its own sub-task, tagged `# Feature: geofence-checkin-api, Property N: ...` and configured for a minimum of 100 iterations.
- Pure-logic properties (1, 2, 3, 10-13) test the resolver/validation helpers directly without a database; write-path properties (4-9, 14) use a fresh in-memory SQLite DB per example.
- The endpoint reuses `EntryService.upsert_entry`, `WorkEntryResponse`, `WorkLocation`, `get_session`, and `verify_api_key`; the only new behavior is query-driven defaulting, Local_Date resolution, and special-day protection.
- Checkpoints ensure incremental validation with ruff + pytest via `uv`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "3.1"] },
    { "id": 1, "tasks": ["2.2", "2.5", "3.2"] },
    { "id": 2, "tasks": ["2.3", "2.4", "2.6", "2.7", "2.8", "2.9", "2.10", "4.1"] },
    { "id": 3, "tasks": ["4.2"] },
    { "id": 4, "tasks": ["6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7", "7.1", "7.2", "7.3", "7.4", "7.5", "7.6"] }
  ]
}
```
