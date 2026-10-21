# Requirements Document

## Introduction

The Geofence Check-In API adds a single, mobile-friendly endpoint to the Work Location Tracker backend (FastAPI + async SQLAlchemy + PostgreSQL). It lets a mobile automation app (for example iOS Shortcuts or Tasker) automatically log a work-location entry when the user's phone enters a configured geofence — typically arrival at the Denmark work location.

The endpoint upserts exactly one work entry for a given calendar date. To keep the mobile trigger as simple as possible, the request requires no body: when no date is supplied it defaults to "today" (computed in the Europe/Copenhagen timezone), and when no location is supplied it defaults to `denmark`. The endpoint is authenticated with the existing `X-API-Key` shared-secret scheme and is designed to be safely idempotent for repeated geofence entries on the same day, while protecting manually-logged special days (`vacation`, `sick`) from being overwritten by an automated trigger.

This feature reuses the existing upsert logic (`EntryService.upsert_entry`), the existing `WorkLocation` enum, the existing `WorkEntry` persistence (unique constraint on `work_date`), and the existing authentication dependency (`verify_api_key`) rather than duplicating them. The one new behavior introduced beyond a plain upsert is the special-day protection rule.

## Glossary

- **Check_In_API**: The new geofence check-in HTTP endpoint added to the backend, mounted under `/api/v1/`.
- **Work_Entry**: A persisted record of the user's work location for a single calendar day, as defined by `backend.models.WorkEntry` (one row per `work_date`, enforced by a unique constraint).
- **Work_Location**: One of the four allowed location values defined by `backend.schemas.WorkLocation`: `home`, `denmark`, `vacation`, `sick`.
- **Special_Day**: A Work_Entry whose Work_Location is `vacation` or `sick`. These represent manually-logged, non-working days.
- **Working_Location**: A Work_Location of `home` or `denmark`.
- **Local_Date**: The current calendar date computed in the `Europe/Copenhagen` timezone (CET/CEST, with daylight saving handled automatically).
- **Shared_Secret**: The value configured in the `APP_SHARED_SECRET` environment variable, which the client must send in the `X-API-Key` request header, verified by `backend.auth.verify_api_key`.
- **Upsert_Service**: The existing `backend.services.entry_service.EntryService` upsert logic that creates or updates the single Work_Entry for a given date.
- **Default_Location**: The Work_Location `denmark`, used when the client does not specify a location (the geofence target is the Denmark work location).

## Requirements

### Requirement 1: Geofence check-in endpoint

**User Story:** As a user with a mobile geofence automation, I want a single endpoint that logs my work location for the day, so that arriving at my Denmark work location is recorded automatically without manual input.

#### Acceptance Criteria

1. THE Check_In_API SHALL expose exactly one endpoint accepting the HTTP POST method whose path begins with the `/api/v1/` prefix for recording a geofence check-in.
2. WHEN a check-in request is received with no request body and no query parameters, THE Check_In_API SHALL upsert a Work_Entry for the Local_Date with the Default_Location.
3. WHEN a check-in request supplies a `location` query parameter whose value is a non-empty, case-sensitive exact match of one of the Work_Location values (`home`, `denmark`, `vacation`, `sick`), THE Check_In_API SHALL use that supplied Work_Location instead of the Default_Location.
4. WHEN a check-in request supplies a `date` query parameter that is a valid ISO 8601 `YYYY-MM-DD` date, THE Check_In_API SHALL use that supplied date as the target date instead of the Local_Date.
5. IF a check-in request omits the `location` query parameter or supplies it as an empty string, THEN THE Check_In_API SHALL resolve the request Work_Location to the Default_Location.
6. IF a check-in request omits the `date` query parameter or supplies it as an empty string, THEN THE Check_In_API SHALL resolve the target date to the Local_Date.
7. THE Check_In_API SHALL process the request without requiring a JSON request body, ignoring any request body if one is present.

### Requirement 2: Default date resolution in Europe/Copenhagen timezone

**User Story:** As a user who lives in Sweden and works in Denmark, I want "today" determined in my local timezone, so that a check-in near midnight is logged on the correct calendar day.

#### Acceptance Criteria

1. WHEN a check-in request does not supply a `date` query parameter, THE Check_In_API SHALL set the target date to the Local_Date, computed as the calendar date in the `Europe/Copenhagen` timezone at the instant the request is received.
2. WHILE the `Europe/Copenhagen` timezone is observing daylight saving time, THE Check_In_API SHALL compute the Local_Date using the CET or CEST offset in effect at the instant the request is received, and SHALL resolve to exactly one calendar date even during a spring-forward or fall-back transition.
3. WHEN a check-in request is received at an instant whose `Europe/Copenhagen` local time is before 00:00:00 of a given calendar day, THE Check_In_API SHALL set the Local_Date to the preceding calendar day, and WHEN received at or after 00:00:00 local time it SHALL set the Local_Date to the new calendar day.

### Requirement 3: Authentication

**User Story:** As the owner of a publicly reachable API, I want every check-in authenticated, so that only my mobile device can log entries.

#### Acceptance Criteria

1. THE Check_In_API SHALL require every check-in request to carry an `X-API-Key` request header whose value is byte-for-byte equal to the Shared_Secret, verified using the existing `verify_api_key` dependency with a constant-time comparison.
2. IF a check-in request omits the `X-API-Key` header, THEN THE Check_In_API SHALL reject the request with HTTP status 401, SHALL return a response body indicating an authentication failure, and SHALL NOT create or modify any Work_Entry.
3. IF a check-in request supplies an `X-API-Key` header whose value is not byte-for-byte equal to the Shared_Secret, THEN THE Check_In_API SHALL reject the request with HTTP status 401, SHALL return a response body indicating an authentication failure, and SHALL NOT create or modify any Work_Entry.
4. IF a check-in request supplies an `X-API-Key` header with an empty string value, THEN THE Check_In_API SHALL reject the request with HTTP status 401, SHALL return a response body indicating an authentication failure, and SHALL NOT create or modify any Work_Entry.

### Requirement 4: Special-day protection and idempotency

**User Story:** As a user who manually logs vacation and sick days, I want an automated geofence check-in to never overwrite those days, so that a stray geofence trigger cannot erase a manually-recorded absence.

#### Acceptance Criteria

1. WHEN a check-in resolves to a target date that has no existing Work_Entry, THE Check_In_API SHALL create exactly one Work_Entry for that date whose Work_Location equals the resolved request Work_Location.
2. IF a check-in resolves to a target date whose existing Work_Entry is a Special_Day, THEN THE Check_In_API SHALL leave that Work_Entry's Work_Location, `work_date`, and `created_at` unchanged and SHALL NOT create any additional Work_Entry for that date.
3. WHEN a check-in resolves to a target date whose existing Work_Entry has a Working_Location, THE Check_In_API SHALL set that Work_Entry's Work_Location to the resolved request Work_Location.
4. WHILE a target date's existing Work_Entry is a Special_Day, THE Check_In_API SHALL preserve that Special_Day regardless of whether the resolved request Work_Location is a Working_Location or a Special_Day.
5. WHEN two or more check-ins resolve to the same target date with the same resolved request Work_Location before any intervening change to that date's Work_Entry, THE Check_In_API SHALL leave exactly one Work_Entry persisted for that date, with the same Work_Location and `work_date` that a single such check-in produces, and SHALL NOT create a duplicate Work_Entry row for that date.

### Requirement 5: Date validation

**User Story:** As a user, I want invalid or future dates rejected, so that my records stay accurate.

#### Acceptance Criteria

1. IF a check-in resolves to a target date strictly later than the Local_Date, THEN THE Check_In_API SHALL reject the request with HTTP status 422, SHALL return a machine-readable error indicating that the target date is in the future, and SHALL NOT create or modify any Work_Entry.
2. WHEN a check-in resolves to a target date equal to the Local_Date, THE Check_In_API SHALL treat the date as valid and SHALL NOT reject it as a future date.
3. IF a check-in supplies a `date` query parameter whose text does not match the ISO 8601 `YYYY-MM-DD` pattern (four-digit year, two-digit month, two-digit day separated by hyphens), THEN THE Check_In_API SHALL reject the request with HTTP status 422, SHALL return a machine-readable error indicating the date format is invalid, and SHALL NOT create or modify any Work_Entry.
4. IF a check-in supplies a `date` query parameter that matches the `YYYY-MM-DD` pattern but does not denote a real calendar date (for example `2025-02-30` or a month outside 01–12), THEN THE Check_In_API SHALL reject the request with HTTP status 422, SHALL return a machine-readable error indicating the date is not a valid calendar date, and SHALL NOT create or modify any Work_Entry.
5. IF a check-in resolves to a target date earlier than 2000-01-01, THEN THE Check_In_API SHALL reject the request with HTTP status 422, SHALL return a machine-readable error indicating the date is out of the accepted range, and SHALL NOT create or modify any Work_Entry.
6. IF a check-in supplies a `location` query parameter whose value is not exactly one of the Work_Location values (`home`, `denmark`, `vacation`, `sick`), THEN THE Check_In_API SHALL reject the request with HTTP status 422, SHALL return a machine-readable error indicating the location value is not allowed, and SHALL NOT create or modify any Work_Entry.

### Requirement 6: Response contract for the mobile client

**User Story:** As a mobile automation author, I want a clear, machine-readable response, so that my shortcut can confirm the check-in succeeded.

#### Acceptance Criteria

1. WHEN a check-in creates a new Work_Entry, THE Check_In_API SHALL respond with HTTP status 201 and a JSON body containing exactly these fields and no others: `id`, `work_date`, `location`, `created_at`, and `updated_at`.
2. WHEN a check-in updates an existing Work_Entry, THE Check_In_API SHALL respond with HTTP status 200 and a JSON body containing exactly these fields and no others: `id`, `work_date`, `location`, `created_at`, and `updated_at`.
3. WHEN a check-in leaves an existing Special_Day unchanged, THE Check_In_API SHALL respond with HTTP status 200 and a JSON body containing exactly these fields and no others, with values equal to the stored Work_Entry: `id`, `work_date`, `location`, `created_at`, and `updated_at`.
4. THE Check_In_API SHALL represent the `location` field in the response as one of the Work_Location string values (`home`, `denmark`, `vacation`, or `sick`).
5. THE Check_In_API SHALL serialize the response body with the `application/json` media type, representing `id` as a positive integer, `work_date` as an ISO 8601 `YYYY-MM-DD` date string, and both `created_at` and `updated_at` as ISO 8601 date-time strings.

### Requirement 7: Service and persistence reuse

**User Story:** As the maintainer, I want the check-in endpoint to reuse existing logic, so that behavior stays consistent and duplication is avoided.

#### Acceptance Criteria

1. WHEN the Check_In_API creates or updates a Work_Entry, THE Check_In_API SHALL perform every create and update write exclusively through the existing Upsert_Service, and SHALL NOT issue any direct Work_Entry data-access write that bypasses the Upsert_Service.
2. WHEN a write would cause a second Work_Entry to exist for a `work_date` that already has a Work_Entry, THE Check_In_API SHALL rely on the existing unique constraint on `work_date` to prevent it, so that at most one Work_Entry exists per calendar date.
3. IF two check-in writes for the same `work_date` are processed concurrently and the second write violates the `work_date` unique constraint, THEN THE Check_In_API SHALL reject the conflicting request with HTTP status 409, SHALL return no status code other than 409 for that constraint violation, SHALL return a response body indicating the request conflicted with an existing entry for that date, SHALL NOT create a duplicate Work_Entry, and SHALL leave the already-persisted Work_Entry for that date unchanged.

### Requirement 8: Database availability error handling

**User Story:** As a mobile automation author, I want a distinct response when the backend's database is down, so that my shortcut can tell an outage apart from a bad request.

#### Acceptance Criteria

1. IF the Check_In_API cannot obtain or use a database connection to process a check-in within a connection timeout of 5 seconds, THEN THE Check_In_API SHALL treat the database as unreachable and SHALL respond with HTTP status 503.
2. IF the database is unreachable while processing a check-in, THEN THE Check_In_API SHALL NOT respond with any 2xx status and SHALL NOT create or modify any Work_Entry.
3. WHEN the Check_In_API responds with HTTP status 503 due to the database being unreachable, THE Check_In_API SHALL return a JSON body containing a machine-readable error indication that distinguishes a database-availability failure from a client request error (HTTP 401, 409, or 422).
4. IF a write to a Work_Entry fails partway because the database becomes unreachable during the write, THEN THE Check_In_API SHALL leave persisted Work_Entry data unchanged, so that no partial Work_Entry is persisted.
