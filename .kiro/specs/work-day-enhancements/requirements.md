# Requirements Document

## Introduction

This feature set adds three enhancements to the existing Work Location Tracker, a Flet frontend and FastAPI backend application that lets a Swedish resident working in Denmark log daily work locations and track compliance with the 50% Denmark presence requirement.

The three enhancements are:

1. **Day-type picker** — Tapping any calendar day (past or today) opens a dialog that lets the user assign one of the four existing location types (office/denmark, home, sick, vacation) or clear the day. This reuses the existing upsert and delete endpoints and is primarily a frontend change.
2. **Compliance score on the front page** — The home screen shows the current month's compliance percentage using the existing colored progress bar, driven by the already-loaded monthly summary.
3. **Shared-secret access** — A login screen gates the Flet app. The app sends a shared secret as an `X-API-Key` header, the backend verifies the header on every request against the `APP_SHARED_SECRET` environment variable, and the secret is remembered across sessions via local storage. A backend 401 clears the stored secret and returns the user to the login screen.

The four location types already exist end-to-end in the backend and frontend. No authentication exists today; the shared-secret access feature is net new.

## Glossary

- **Work_Entry**: A single record associating a calendar date with a work location (`home`, `denmark`, `vacation`, or `sick`).
- **Work_Location**: An enumeration with four values: `home`, `denmark`, `vacation`, and `sick`.
- **Day_Type_Picker**: An `ft.AlertDialog` presented by the Flet_App when a calendar day is tapped, offering the four Work_Location choices and a clear option.
- **Clear_Action**: The option within the Day_Type_Picker that removes any existing Work_Entry for the selected date.
- **Compliance_Summary**: An aggregated record for a month showing total logged days, Denmark days, vacation days, sick days, home days, compliance percentage, and compliance status, as defined by the existing Work Location Tracker spec.
- **Compliance_Bar**: The existing `ft.ProgressBar` control that renders a compliance percentage, colored green when compliant and red when not compliant.
- **Front_Page**: The home view of the Flet_App that displays the calendar grid.
- **Login_Screen**: The view presented by the Flet_App that collects the shared secret before access to the Front_Page is granted.
- **Shared_Secret**: A string value the user enters at the Login_Screen that the Flet_App sends to the FastAPI_Backend as an `X-API-Key` header.
- **APP_SHARED_SECRET**: The environment variable read by the FastAPI_Backend that holds the expected value of the Shared_Secret.
- **Local_Storage**: The persistent client-side key-value store accessed through Flet's `page.client_storage` (SharedPreferences), used to remember the Shared_Secret across sessions.
- **Auth_Middleware**: The FastAPI_Backend component that verifies the `X-API-Key` header on every request.
- **API_Client**: The HTTP client component in the Flet frontend that communicates with the FastAPI_Backend.
- **Flet_App**: The cross-platform frontend application built with Flet.
- **FastAPI_Backend**: The REST API application deployed on Clever Cloud.
- **AppState**: The in-memory state dataclass maintained by the Flet_App.

---

## Requirements

### Requirement 1: Open the Day-Type Picker from a Calendar Day

**User Story:** As a user, I want to tap any past or current calendar day to open a picker, so that I can choose how that day is recorded without using a separate form.

#### Acceptance Criteria

1. WHEN a user taps a calendar day whose date is on or before today's date, THE Flet_App SHALL open the Day_Type_Picker for that date.
2. WHEN the Day_Type_Picker opens, THE Flet_App SHALL present four location choices labelled for `denmark`, `home`, `sick`, and `vacation`, plus a Clear_Action.
3. WHEN the Day_Type_Picker opens for a date that already has a Work_Entry, THE Flet_App SHALL indicate the currently recorded Work_Location.
4. WHEN a user dismisses the Day_Type_Picker without selecting a choice, THE Flet_App SHALL close the Day_Type_Picker and leave the selected date's Work_Entry unchanged.
5. WHEN a user taps a calendar day whose date is after today's date, THE Flet_App SHALL leave the Day_Type_Picker closed and the calendar state unchanged.

### Requirement 2: Assign a Location Through the Day-Type Picker

**User Story:** As a user, I want to pick a location type in the picker, so that the selected day is created or updated with that location.

#### Acceptance Criteria

1. WHEN a user selects one of the four location choices in the Day_Type_Picker, THE Flet_App SHALL send an upsert request to the FastAPI_Backend containing the selected date and the chosen Work_Location.
2. WHEN the upsert request for a date without an existing Work_Entry is sent, THE API_Client SHALL issue a POST request to the entries endpoint.
3. WHEN the upsert request for a date with an existing Work_Entry is sent, THE API_Client SHALL issue a PATCH request to the entries endpoint for that Work_Entry.
4. WHEN the FastAPI_Backend confirms the upsert succeeded, THE Flet_App SHALL update the selected date's calendar tile to the chosen Work_Location color and recalculate the displayed Compliance_Summary.
5. WHEN the upsert succeeds, THE Flet_App SHALL close the Day_Type_Picker.
6. IF the FastAPI_Backend returns an error response for the upsert request, THEN THE Flet_App SHALL display an error notification and leave the selected date's calendar tile unchanged.

### Requirement 3: Clear a Day Through the Day-Type Picker

**User Story:** As a user, I want to clear a recorded day from the picker, so that I can mark it as unlogged again.

#### Acceptance Criteria

1. WHEN a user selects the Clear_Action for a date that has an existing Work_Entry, THE API_Client SHALL issue a DELETE request to the entries endpoint for that Work_Entry.
2. WHEN the FastAPI_Backend confirms the deletion succeeded, THE Flet_App SHALL render the selected date's calendar tile as unlogged and recalculate the displayed Compliance_Summary.
3. WHEN the deletion succeeds, THE Flet_App SHALL close the Day_Type_Picker.
4. WHEN a user selects the Clear_Action for a date that has no existing Work_Entry, THE Flet_App SHALL close the Day_Type_Picker and leave the calendar state unchanged without sending a DELETE request.
5. IF the FastAPI_Backend returns an error response for the DELETE request, THEN THE Flet_App SHALL display an error notification and keep the selected date's Work_Entry visible in the calendar.

### Requirement 4: Display Current-Month Compliance on the Front Page

**User Story:** As a user, I want to see my current month's compliance percentage on the front page, so that I know my compliance status at a glance without navigating to the summary view.

#### Acceptance Criteria

1. WHEN the Front_Page is displayed and the AppState contains a Compliance_Summary for the current month, THE Flet_App SHALL render the Compliance_Bar with a value equal to `compliance_pct / 100.0`.
2. WHILE the current month's Compliance_Summary reports `is_compliant` as `true`, THE Flet_App SHALL render the Compliance_Bar using the compliant color `ft.Colors.GREEN_600`.
3. WHILE the current month's Compliance_Summary reports `is_compliant` as `false`, THE Flet_App SHALL render the Compliance_Bar using the non-compliant color `ft.Colors.RED_700`.
4. WHEN the Front_Page is displayed and the AppState contains no Compliance_Summary, THE Flet_App SHALL render the Compliance_Bar in a neutral style using `ft.Colors.SURFACE` with no percentage label.
5. WHEN the current month's Compliance_Summary is updated after a Work_Entry change, THE Flet_App SHALL re-render the Compliance_Bar to reflect the updated compliance percentage and status.

### Requirement 5: Gate the Flet App with a Login Screen

**User Story:** As a user, I want to enter a shared secret before using the app, so that only authorized people can access the work data.

#### Acceptance Criteria

1. WHEN the Flet_App starts and no Shared_Secret is present in Local_Storage, THE Flet_App SHALL display the Login_Screen and withhold the Front_Page.
2. WHEN the Flet_App starts and a Shared_Secret is present in Local_Storage, THE Flet_App SHALL load the stored Shared_Secret into the API_Client and display the Front_Page.
3. WHEN a user submits a non-empty Shared_Secret on the Login_Screen, THE Flet_App SHALL store the Shared_Secret in Local_Storage, configure the API_Client to send the Shared_Secret, and display the Front_Page.
4. IF a user submits an empty Shared_Secret on the Login_Screen, THEN THE Flet_App SHALL display a validation message and remain on the Login_Screen.

### Requirement 6: Send the Shared Secret on Every Request

**User Story:** As a developer, I want the app to attach the shared secret to every backend call, so that the backend can authorize each request.

#### Acceptance Criteria

1. WHEN the API_Client sends any request to the FastAPI_Backend while a Shared_Secret is configured, THE API_Client SHALL include the Shared_Secret in an `X-API-Key` request header.
2. WHERE no Shared_Secret is configured in the API_Client, THE Flet_App SHALL remain on the Login_Screen and send no entry or summary requests.

### Requirement 7: Verify the Shared Secret on the Backend

**User Story:** As a developer, I want the backend to verify the shared secret on every request, so that unauthorized requests are rejected.

#### Acceptance Criteria

1. THE FastAPI_Backend SHALL read the expected Shared_Secret value exclusively from the `APP_SHARED_SECRET` environment variable.
2. WHEN the FastAPI_Backend receives a request whose `X-API-Key` header equals the value of `APP_SHARED_SECRET`, THE Auth_Middleware SHALL allow the request to proceed to its route handler.
3. IF the FastAPI_Backend receives a request whose `X-API-Key` header is missing or does not equal the value of `APP_SHARED_SECRET`, THEN THE Auth_Middleware SHALL reject the request with HTTP 401.
4. IF the `APP_SHARED_SECRET` environment variable is absent at startup, THEN THE FastAPI_Backend SHALL abort startup and log an error message identifying the missing variable.
5. THE `.env.example` file SHALL include an `APP_SHARED_SECRET` entry documenting the required environment variable.

### Requirement 8: Recover from an Unauthorized Response

**User Story:** As a user, I want the app to send me back to the login screen when my secret is rejected, so that I can re-enter a valid secret.

#### Acceptance Criteria

1. IF the API_Client receives an HTTP 401 response from the FastAPI_Backend, THEN THE Flet_App SHALL remove the Shared_Secret from Local_Storage.
2. WHEN the Flet_App removes the Shared_Secret after an HTTP 401 response, THE Flet_App SHALL clear the Shared_Secret from the API_Client and display the Login_Screen.
3. WHEN the Flet_App returns to the Login_Screen after an HTTP 401 response, THE Flet_App SHALL display a message indicating that the Shared_Secret was rejected.
