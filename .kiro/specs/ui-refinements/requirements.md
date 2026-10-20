# Requirements Document

## Introduction

This feature refines the home (front page) UI of the work-location-tracker Flet
app with four focused changes:

1. Replace the linear compliance progress bar with a circular progress
   indicator that communicates how many office/Denmark days are still missing
   to reach compliance, derived entirely from the existing
   `compliance_pct` field (no backend or API changes).
2. Remove the top quick-log buttons so the calendar day-type picker becomes the
   sole logging path.
3. Make the calendar day cells responsive: square cells that scale to the
   available screen width.
4. Add a Monday–Sunday weekday-name header row aligned above the 7-column
   calendar grid.

All changes are confined to the frontend presentation layer. The backend
contract (`ComplianceSummary`, `WorkEntry`, the `/api/v1/...` endpoints) is
unchanged, and the day-type picker upsert/clear logging logic is reused as-is.

## Glossary

- **Home_View**: The front-page screen built by `build_home_view` in
  `app/views/home_view.py`, composed of the compliance indicator, month
  navigation, and the calendar grid.
- **Compliance_Indicator**: The replacement circular progress control built by
  the component in `app/components/compliance_bar.py`, superseding the previous
  `ft.ProgressBar`.
- **Compliance_Summary**: The `ComplianceSummary` model returned by the backend,
  carrying `compliance_pct`, `denmark_days`, `total_days`, and `is_compliant`
  (among others). No field names change.
- **Compliance_Pct**: The `compliance_pct` field of Compliance_Summary, a
  percentage value in the range 0.0–100.0.
- **Compliance_Threshold**: The compliance percentage at which a month is
  considered compliant, treated as a frontend-known constant used to derive the
  days-still-missing value from Compliance_Pct. It represents 100% of the
  circular indicator's fill.
- **Days_Missing**: The number of office/Denmark days still required to reach
  Compliance_Threshold, computed frontend-side from Compliance_Pct and the
  known threshold. No backend field supplies this value.
- **Calendar_Grid**: The monthly calendar control built by
  `build_calendar_grid` in `app/components/calendar_grid.py`, laid out as a
  7-column Monday–Sunday grid of day tiles.
- **Day_Cell**: A single day tile rendered inside Calendar_Grid.
- **Weekday_Header**: A new row of seven weekday-name labels (Mon–Sun) rendered
  above Calendar_Grid and aligned to the grid's seven columns.
- **Day_Type_Picker**: The dialog built by `build_day_type_picker` in
  `app/components/day_type_picker.py`, opened by tapping a Day_Cell, which is
  the sole path for logging a day type.

## Requirements

### Requirement 1: Circular compliance indicator

**User Story:** As a user, I want the front page to show a circular progress
indicator of my compliance, so that I can see at a glance how close I am to
meeting the office/Denmark requirement.

#### Acceptance Criteria

1. WHEN the Home_View is rendered with a Compliance_Summary, THE Compliance_Indicator SHALL display a circular progress control filled in proportion to Compliance_Pct relative to Compliance_Threshold.
2. WHERE Compliance_Pct is greater than or equal to Compliance_Threshold, THE Compliance_Indicator SHALL display a full (100%) circular fill.
3. WHEN the Home_View is rendered with a Compliance_Summary, THE Compliance_Indicator SHALL display a numeric fill value constrained to the inclusive range 1 to 100 percent.
4. IF no Compliance_Summary is available, THEN THE Compliance_Indicator SHALL render a neutral empty state with no fill and no Days_Missing value.
5. WHEN Compliance_Pct indicates the month is compliant, THE Compliance_Indicator SHALL use the compliant color, and WHEN Compliance_Pct indicates the month is not compliant, THE Compliance_Indicator SHALL use the non-compliant color.

### Requirement 2: Days-still-missing derivation

**User Story:** As a user, I want the indicator to tell me how many office/Denmark
days I am still missing, so that I know exactly how much more I need to log to
become compliant.

#### Acceptance Criteria

1. WHEN the Home_View is rendered with a Compliance_Summary, THE Compliance_Indicator SHALL display Days_Missing computed frontend-side from Compliance_Pct and Compliance_Threshold using only fields already present on Compliance_Summary.
2. WHERE Compliance_Pct is greater than or equal to Compliance_Threshold, THE Compliance_Indicator SHALL display Days_Missing as zero.
3. THE Compliance_Indicator SHALL compute Days_Missing without issuing any additional backend request or requiring any new backend field.
4. WHEN Days_Missing is displayed, THE Compliance_Indicator SHALL round Days_Missing up to the next whole day so a partial remaining day is shown as one day.

### Requirement 3: Remove quick-log buttons

**User Story:** As a user, I want to log a day only by tapping it on the
calendar, so that the front page stays uncluttered without redundant quick-log
buttons.

#### Acceptance Criteria

1. THE Home_View SHALL render without the Office/Denmark, Work From Home, Vacation, and Sick Day quick-log buttons.
2. THE Home_View SHALL render without a replacement floating action button for logging.
3. WHEN a user taps a Day_Cell that is eligible for editing, THE Home_View SHALL open the Day_Type_Picker for that date.
4. THE Day_Type_Picker SHALL remain the only control through which a day type is logged, edited, or cleared on the Home_View.

### Requirement 4: Responsive square day cells

**User Story:** As a user, I want calendar day boxes to scale to my screen, so
that the calendar looks balanced on any device width.

#### Acceptance Criteria

1. WHEN the Calendar_Grid is rendered, THE Calendar_Grid SHALL size each Day_Cell as a square whose width equals its height.
2. WHEN the available width of the Home_View changes, THE Calendar_Grid SHALL scale each Day_Cell so the seven columns fill the available width.
3. THE Calendar_Grid SHALL preserve the Monday–Sunday 7-column layout and the leading blank placeholder cells before day one of the month.

### Requirement 5: Weekday-name header row

**User Story:** As a user, I want weekday names across the top of the calendar,
so that I can tell which column each day falls under.

#### Acceptance Criteria

1. WHEN the Home_View is rendered, THE Home_View SHALL display a Weekday_Header row containing seven labels in Monday-through-Sunday order above the Calendar_Grid.
2. THE Weekday_Header SHALL align each of its seven labels to the corresponding column of the Calendar_Grid.
3. WHEN the Calendar_Grid scales to the available width, THE Weekday_Header SHALL scale with the Calendar_Grid so each label stays aligned above its column.
