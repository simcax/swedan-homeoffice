# Requirements Document

## Introduction

A cross-platform application (Flet/Python) that allows Swedish residents working in Denmark to log their daily work location — either "Work from Home" (Sweden), "Office/Denmark", "Vacation", or "Sick Leave" — and track compliance with the 50% Denmark work requirement. The system consists of a Flet frontend communicating with a FastAPI backend hosted on Clever Cloud, with data persisted in PostgreSQL.

## Glossary

- **Work_Entry**: A single record associating a calendar date with a work location (`home`, `denmark`, `vacation`, or `sick`)
- **Work_Location**: An enumeration with four values: `home` (working from Sweden), `denmark` (working from the office in Denmark), `vacation` (vacation day), and `sick` (sick leave day)
- **Compliant_Day**: A day that counts toward the 50% Denmark presence requirement; any day with location `denmark`, `vacation`, or `sick` is a compliant day
- **Compliance_Summary**: An aggregated record for a month or year showing total logged days, Denmark days, vacation days, sick days, home days, compliance percentage, and compliance status
- **Annual_Summary**: A yearly aggregation of compliance data including a per-month breakdown
- **API_Client**: The HTTP client component in the Flet frontend that communicates with the FastAPI backend
- **Entry_Service**: The backend service layer component responsible for work entry business logic
- **Compliance_Service**: The backend service layer component responsible for calculating compliance metrics
- **Entry_Repository**: The backend data access component responsible for all database I/O for work entries
- **FastAPI_Backend**: The REST API application deployed on Clever Cloud
- **Flet_App**: The cross-platform frontend application built with Flet
- **AppState**: The in-memory state dataclass maintained by the Flet_App

---

## Requirements

### Requirement 1: Log a Work Day

**User Story:** As a Swedish resident working in Denmark, I want to log my work location for any given day, so that I can track where I am working.

#### Acceptance Criteria

1. WHEN a user selects a work location ("home", "denmark", "vacation", or "sick") for a date, THE Flet_App SHALL send a request to the backend with the date and location.
2. WHEN a valid work entry request is received, THE FastAPI_Backend SHALL create or update exactly one work entry record for that date and confirm success.
3. IF a work entry already exists for the given date, THEN THE Entry_Service SHALL update the existing record's location rather than creating a duplicate.
4. WHEN a work entry is successfully created or updated, THE Flet_App SHALL update the displayed location for that date in the calendar and recalculate the compliance indicator.
5. IF the backend fails to create or update a work entry, THEN THE Flet_App SHALL display an error notification and preserve the previously displayed calendar state.
6. IF a work location value other than "home", "denmark", "vacation", or "sick" is submitted, THEN THE FastAPI_Backend SHALL reject the request with a validation error.

### Requirement 2: Prevent Future Date Entries

**User Story:** As a user, I want to be prevented from logging future dates, so that the compliance data reflects only actual work days.

#### Acceptance Criteria

1. WHEN a work entry request contains a date that is after today's date, THE FastAPI_Backend SHALL reject the request with HTTP 422.
2. IF a `work_date` is strictly after `date.today()`, THEN THE `WorkEntryCreate` validator SHALL raise a validation error preventing the entry from being created.
3. WHEN the backend rejects a future-date request, THE Flet_App SHALL display an error message adjacent to the date field.
4. WHEN the backend rejects a future-date request, THE Flet_App SHALL not add a new entry to the local entry list.
5. WHEN the backend rejects a future-date request, THE Flet_App SHALL preserve the current form field values without resetting them.

### Requirement 3: Edit a Work Entry

**User Story:** As a user, I want to change the logged location for an existing entry, so that I can correct mistakes.

#### Acceptance Criteria

1. WHEN a user requests an update for an existing entry, THE Flet_App SHALL send a PATCH request to the backend with the new location ("home", "denmark", "vacation", or "sick") and the entry identifier.
2. WHEN a valid update request is received for an existing entry, THE FastAPI_Backend SHALL update the entry's location (leaving the work_date unchanged) and return the updated entry record with HTTP 200.
3. IF an update request is received for an entry identifier that does not exist, THEN THE FastAPI_Backend SHALL return an error response indicating the entry was not found.
4. IF a location value other than "home", "denmark", "vacation", or "sick" is submitted in an update request, THEN THE FastAPI_Backend SHALL return a validation error response.
5. WHEN an entry is successfully updated, THE Flet_App SHALL reflect the new location in the calendar within 2 seconds.
6. IF the backend returns an error for an update request, THEN THE Flet_App SHALL display an error notification and preserve the calendar's current state.

### Requirement 4: Delete a Work Entry

**User Story:** As a user, I want to delete a logged work entry, so that I can remove incorrectly recorded days.

#### Acceptance Criteria

1. WHEN a user initiates deletion of an entry, THE Flet_App SHALL display a confirmation dialog before sending the delete request.
2. WHEN a user confirms the deletion, THE Flet_App SHALL send a delete request to the backend with the entry identifier.
3. WHEN a valid delete request is received for an existing entry, THE FastAPI_Backend SHALL remove the entry and confirm success with no content.
4. IF a delete request is received for an entry identifier that does not exist, THEN THE FastAPI_Backend SHALL return an error response indicating the entry was not found.
5. WHEN an entry is successfully deleted, THE Flet_App SHALL display the deleted entry's date cell as unlogged in the calendar.
6. IF the backend returns an error for a delete request, THEN THE Flet_App SHALL display an error notification and keep the entry visible in the calendar.

### Requirement 5: View Monthly Work Entries

**User Story:** As a user, I want to view all my logged work days for a given month, so that I can see my work pattern at a glance.

#### Acceptance Criteria

1. WHEN a user navigates to a month, THE Flet_App SHALL send a GET request to `/api/v1/entries?year=YYYY&month=MM`.
2. WHEN a valid GET request for entries is received with a year >= 2000 and a month between 1 and 12, THE FastAPI_Backend SHALL return all work entry rows for that month ordered ascending by work_date.
3. WHEN no entries exist for the requested month, THE FastAPI_Backend SHALL return an empty list with HTTP 200.
4. IF a request contains a year below 2000, a month below 1, or a month above 12, THEN THE FastAPI_Backend SHALL return HTTP 422 with a message indicating the invalid parameter.
5. IF the Flet_App receives a 4xx response or a network failure when loading a month, THEN THE Flet_App SHALL display an error message and preserve the existing calendar grid state.

### Requirement 6: Calculate Monthly Compliance Summary

**User Story:** As a user, I want to see my compliance percentage for a given month, so that I know whether I am meeting the 50% Denmark requirement.

#### Acceptance Criteria

1. WHEN a user requests a monthly summary for a valid year (2000–2099) and month (1–12), THE Flet_App SHALL send a GET request to `/api/v1/summary/monthly?year=YYYY&month=MM`.
2. IF a monthly summary request contains a year outside 2000–2099 or a month outside 1–12, THEN THE FastAPI_Backend SHALL return HTTP 422 with a message identifying the invalid parameter.
3. WHEN a valid monthly summary request is received, THE FastAPI_Backend SHALL return an object containing the count of logged days in Denmark, the count of vacation days, the count of sick days, the count of logged days at home, the total logged days, a compliance percentage, and a boolean compliance status.
4. IF `total_days` is greater than 0, THEN THE Compliance_Service SHALL compute `compliance_pct` as `((denmark_days + vacation_days + sick_days) / total_days) * 100.0`.
5. IF `total_days` is 0, THEN THE Compliance_Service SHALL return `compliance_pct` of `0.0` and `is_compliant` of `false`.
6. IF `compliance_pct >= 50.0`, THEN THE Compliance_Service SHALL set `is_compliant` to `true`; otherwise THE Compliance_Service SHALL set `is_compliant` to `false`.
7. THE Compliance_Service SHALL ensure `denmark_days + vacation_days + sick_days + home_days == total_days` for every computed summary.

### Requirement 7: Calculate Annual Compliance Summary

**User Story:** As a user, I want to see my compliance percentage for an entire year with a per-month breakdown, so that I can monitor my long-term compliance trend.

#### Acceptance Criteria

1. WHEN a user requests an annual summary for a year between 2000 and 2099, THE Flet_App SHALL send a GET request to `/api/v1/summary/annual?year=YYYY`.
2. WHEN a valid annual summary request is received, THE FastAPI_Backend SHALL return an object containing total_days, denmark_days, vacation_days, sick_days, home_days, compliance_pct, is_compliant, and a monthly_breakdown list containing exactly 12 ComplianceSummary entries (one per month, January through December).
3. THE Compliance_Service SHALL compute annual `total_days` as the sum of `total_days` across all twelve monthly summaries.
4. IF annual `total_days` is greater than 0, THEN THE Compliance_Service SHALL compute annual `compliance_pct` as `((denmark_days + vacation_days + sick_days) / total_days) * 100.0` rounded to 2 decimal places; otherwise `compliance_pct` SHALL be `0.0`.
5. THE Compliance_Service SHALL assign `total_days = 0` for any month in `monthly_breakdown` that has no logged entries, including months that have not yet occurred in the current year.
6. IF the `year` parameter is absent, non-numeric, or outside 2000–2099, THEN THE FastAPI_Backend SHALL return HTTP 422 with a message identifying the invalid parameter.

### Requirement 8: Display Compliance in the UI

**User Story:** As a user, I want a visual compliance indicator in the app, so that I can quickly see my compliance status without reading numbers.

#### Acceptance Criteria

1. WHEN the AppState contains a `compliance_summary`, THE Flet_App SHALL render a `ft.ProgressBar` whose value equals `compliance_pct / 100.0` (range 0.0–1.0) showing the Denmark compliance percentage.
2. WHEN the calendar view is displayed, THE Flet_App SHALL render each logged day tile using `ft.Colors.RED_700` for `denmark` entries, `ft.Colors.BLUE_700` for `home` entries, `ft.Colors.ORANGE_700` for `vacation` entries, `ft.Colors.PURPLE_700` for `sick` entries, and `ft.Colors.SURFACE` for unlogged days.
3. WHEN `is_compliant` is `true`, THE Flet_App SHALL render the compliance bar using `ft.Colors.GREEN_600`.
4. WHEN `is_compliant` is `false`, THE Flet_App SHALL render the compliance bar using `ft.Colors.RED_700`.
5. WHEN the AppState contains no `compliance_summary` (null or loading), THE Flet_App SHALL render the compliance bar in a neutral style using `ft.Colors.SURFACE` with no percentage label.

### Requirement 9: Handle API Errors Gracefully

**User Story:** As a user, I want the app to handle connectivity problems without crashing, so that I can continue using it and retry when the connection is restored.

#### Acceptance Criteria

1. IF the Flet_App receives an HTTP 422 response, THEN THE Flet_App SHALL display an inline validation error message and retain all current form field values without navigating away.
2. IF the Flet_App receives an HTTP 404 response, THEN THE Flet_App SHALL display a toast notification and refresh the entry list.
3. IF the Flet_App receives an HTTP 409 response, THEN THE API_Client SHALL automatically retry the request as a PATCH; IF that PATCH also fails, THEN THE Flet_App SHALL display an error notification and make no state change.
4. IF the API_Client encounters a network timeout (exceeding 10 seconds) or connection error, THEN THE Flet_App SHALL display a banner message indicating the connection failed and retain all current form field values without navigating away.
5. IF THE FastAPI_Backend cannot reach PostgreSQL, THEN THE FastAPI_Backend SHALL return HTTP 503.
6. IF the API_Client receives HTTP 503, THEN THE API_Client SHALL retry the request with exponential back-off (1 s, 2 s, 4 s) for up to 3 attempts; IF all attempts fail, THEN THE Flet_App SHALL display an error notification and make no state change.

### Requirement 10: Persist Data in PostgreSQL

**User Story:** As a user, I want my work entries to be stored reliably in a database, so that my data is not lost between sessions.

#### Acceptance Criteria

1. THE FastAPI_Backend SHALL persist all work entries in a PostgreSQL `work_entries` table with columns `id`, `work_date`, `location`, `created_at`, and `updated_at`.
2. THE `work_entries` table SHALL enforce a unique constraint on `work_date`; IF a duplicate `work_date` is inserted, THEN THE FastAPI_Backend SHALL return a conflict error and not insert a second row.
3. THE `location` column SHALL only accept the values `"home"`, `"denmark"`, `"vacation"`, and `"sick"` enforced by a database enum type; IF an invalid location value is submitted, THEN THE FastAPI_Backend SHALL return a validation error at the API layer before the data reaches the database.
4. THE FastAPI_Backend SHALL use async SQLAlchemy with the `asyncpg` driver for all database operations.
5. IF PostgreSQL is unreachable, THEN THE FastAPI_Backend SHALL return an error response without performing a partial insert.

### Requirement 11: Configure and Deploy the Backend on Clever Cloud

**User Story:** As a developer, I want the backend deployed on Clever Cloud with configuration via environment variables, so that secrets are never stored in code.

#### Acceptance Criteria

1. THE FastAPI_Backend SHALL read its database connection string exclusively from the `DATABASE_URL` environment variable and SHALL NOT accept database credentials from any other source.
2. IF the `DATABASE_URL` environment variable is absent at startup, THEN THE FastAPI_Backend SHALL abort startup and log a clear error message.
3. WHEN the FastAPI_Backend is started on Clever Cloud, THE FastAPI_Backend SHALL bind to host `0.0.0.0` and port `8080`.
4. WHEN the FastAPI_Backend starts up, THE FastAPI_Backend SHALL run Alembic migrations to bring the database schema to the latest version before accepting requests.
5. IF a database migration fails at startup, THEN THE FastAPI_Backend SHALL abort startup and log a clear error message identifying the failed migration.
6. THE FastAPI_Backend SHALL rewrite the `DATABASE_URL` scheme from `postgresql://` to `postgresql+asyncpg://` when constructing the async SQLAlchemy engine.

### Requirement 12: Input Validation

**User Story:** As a developer, I want all API inputs validated by Pydantic, so that the backend rejects malformed requests before they reach the service layer.

#### Acceptance Criteria

1. WHEN a request body contains an unrecognised `location` value, THE FastAPI_Backend SHALL return HTTP 422 with a validation error identifying the field name and stating the accepted values ("home", "denmark", "vacation", "sick").
2. WHEN a request body contains a `work_date` that is not a valid ISO 8601 date (YYYY-MM-DD), THE FastAPI_Backend SHALL return HTTP 422 with a validation error identifying the field name and the expected format.
3. THE `WorkEntryCreate` schema SHALL reject any `work_date` that is strictly after `date.today()`, returning a validation error.
4. THE `WorkEntryUpdate` schema SHALL accept only a `location` field with a valid `WorkLocation` enum value ("home", "denmark", "vacation", or "sick").
5. IF a `WorkEntryUpdate` request body contains a `location` value that is not "home", "denmark", "vacation", or "sick", THEN THE FastAPI_Backend SHALL return HTTP 422 with a validation error identifying the field name and the accepted values.

### Requirement 13: Log a Vacation Day

**User Story:** As a user, I want to log a day as vacation, so that it counts toward my Denmark presence without being recorded as an office day.

#### Acceptance Criteria

1. WHEN a user selects "vacation" as the work location for a date in ISO 8601 format (YYYY-MM-DD), THE Flet_App SHALL send a request to the backend with the date and location `"vacation"`.
2. WHEN a work entry request with a well-formed ISO 8601 date and location `"vacation"` is received, THE FastAPI_Backend SHALL create or update exactly one work entry record for that date with location `"vacation"` and return the saved work entry record in the response.
3. WHEN a monthly or annual compliance summary is computed and a day is logged as `"vacation"`, THE Compliance_Service SHALL count that day as a compliant day toward the 50% Denmark requirement, equivalent to a `"denmark"` day.
4. WHEN a monthly summary is requested, THE FastAPI_Backend SHALL include a `vacation_days` field containing the count of days logged as `"vacation"` for the requested month; WHEN no vacation days exist for that month, THE FastAPI_Backend SHALL return `vacation_days` as `0`.
5. WHEN a vacation entry is successfully created or updated, THE Flet_App SHALL display that date tile in a distinct color that visually differentiates it from `"denmark"`, `"home"`, and `"sick"` tiles.
6. IF the backend returns an error when creating or updating a vacation entry, THEN THE Flet_App SHALL display an error message and leave the date tile unchanged.

### Requirement 14: Log a Sick Day

**User Story:** As a user, I want to log a day as sick leave, so that it counts toward my Denmark presence without being recorded as an office day.

#### Acceptance Criteria

1. WHEN a user selects "sick" as the work location for a date in ISO 8601 format (YYYY-MM-DD), THE Flet_App SHALL send a request to the backend with the date and location `"sick"`.
2. WHEN a work entry request with a well-formed ISO 8601 date and location `"sick"` is received, THE FastAPI_Backend SHALL create or update exactly one work entry record for that date with location `"sick"` and return the saved work entry record in the response.
3. WHEN a monthly or annual compliance summary is computed and a day is logged as `"sick"`, THE Compliance_Service SHALL count that day as a compliant day toward the 50% Denmark requirement, equivalent to a `"denmark"` day.
4. WHEN a monthly summary is requested, THE FastAPI_Backend SHALL include a `sick_days` field containing the count of days logged as `"sick"` for the requested month; WHEN no sick days exist for that month, THE FastAPI_Backend SHALL return `sick_days` as `0`.
5. WHEN a sick entry is successfully created or updated, THE Flet_App SHALL display that date tile in a distinct color that visually differentiates it from `"denmark"`, `"home"`, and `"vacation"` tiles.
6. IF the backend returns an error when creating or updating a sick entry, THEN THE Flet_App SHALL display an error message and leave the date tile unchanged.
