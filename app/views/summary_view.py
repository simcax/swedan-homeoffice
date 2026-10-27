"""Monthly and annual compliance summary screen (task 12.2).

``build_summary_view`` assembles a read-only screen that presents two things:

* a **monthly summary card** rendering every field of a
  :class:`app.api_client.ComplianceSummary` (total, denmark, travel, vacation,
  sick, home day counts and the compliance percentage), topped by the shared
  compliance progress bar (Requirements 6.1, 8.1, 8.3, 8.4), and
* an **annual summary** with a 12-row breakdown table (one row per month,
  January through December) plus a totals row (Requirement 7.1).

Both pieces are rendered independently: either ``monthly`` or ``annual`` may be
``None`` (e.g. still loading), in which case a neutral placeholder is shown.

The view-building logic is kept pure of the Flet runtime so it can be tested by
inspecting the returned control tree with mocked data — the module never calls
``ft.app`` or ``page.update``.

Requirements: 6.1, 7.1, 8.1, 8.3, 8.4
"""

from __future__ import annotations

import calendar

import flet as ft

from app.api_client import AnnualSummary, ComplianceSummary
from app.components.compliance_bar import build_compliance_bar

# Column headers for the annual breakdown table (Requirement 7.1).
_ANNUAL_COLUMNS: tuple[str, ...] = (
    "Month",
    "Total",
    "Denmark",
    "Travel",
    "Vacation",
    "Sick",
    "Home",
    "Compliance %",
)


# ---------------------------------------------------------------------------
# monthly summary card
# ---------------------------------------------------------------------------


def build_monthly_card(summary: ComplianceSummary | None) -> ft.Card:
    """Build the monthly compliance summary card.

    Renders the compliance progress bar followed by every count field of
    ``summary``. When ``summary`` is ``None`` a neutral placeholder is shown
    (the bar is drawn in its neutral style and a "no data" notice replaces the
    figures).

    Args:
        summary: The monthly compliance summary, or ``None`` when unavailable.

    Returns:
        A configured :class:`ft.Card`.
    """
    bar = build_compliance_bar(summary)

    if summary is None:
        body: list[ft.Control] = [
            ft.Text("Monthly summary", weight=ft.FontWeight.BOLD, size=18),
            bar,
            ft.Text("No summary available yet.", italic=True),
        ]
    else:
        title = f"{calendar.month_name[summary.month]} {summary.year}"
        body = [
            ft.Text(title, weight=ft.FontWeight.BOLD, size=18),
            bar,
            ft.Text(f"Compliance: {summary.compliance_pct:.1f}%"),
            _stat_row("Total days", summary.total_days),
            _stat_row("Denmark", summary.denmark_days),
            _stat_row("Travel", summary.travel_days),
            _stat_row("Vacation", summary.vacation_days),
            _stat_row("Sick", summary.sick_days),
            _stat_row("Home", summary.home_days),
        ]

    return ft.Card(
        content=ft.Container(
            content=ft.Column(controls=body, spacing=8),
            padding=16,
        ),
    )


# ---------------------------------------------------------------------------
# annual summary table
# ---------------------------------------------------------------------------


def build_annual_table(annual: AnnualSummary | None) -> ft.Control:
    """Build the annual summary with a 12-month breakdown table.

    Produces a :class:`ft.DataTable` with one row per month (January through
    December) plus a totals row, wrapped in a :class:`ft.Column` with a header.
    When ``annual`` is ``None`` a neutral placeholder is returned instead.

    Args:
        annual: The annual summary with a ``monthly_breakdown`` list, or
            ``None`` when unavailable.

    Returns:
        A Flet control (a :class:`ft.Column`) holding the heading and table.
    """
    if annual is None:
        return ft.Column(
            controls=[
                ft.Text("Annual summary", weight=ft.FontWeight.BOLD, size=18),
                ft.Text("No annual summary available yet.", italic=True),
            ],
            spacing=8,
        )

    rows = [_month_row(month_summary) for month_summary in annual.monthly_breakdown]
    rows.append(_totals_row(annual))

    table = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(label)) for label in _ANNUAL_COLUMNS],
        rows=rows,
    )

    return ft.Column(
        controls=[
            ft.Text(
                f"Annual summary {annual.year}", weight=ft.FontWeight.BOLD, size=18
            ),
            ft.Text(f"Compliance: {annual.compliance_pct:.1f}%"),
            ft.Row(
                controls=[table],
                scroll=ft.ScrollMode.AUTO,
            ),
        ],
        spacing=8,
    )


# ---------------------------------------------------------------------------
# view builder
# ---------------------------------------------------------------------------


def build_summary_view(
    monthly: ComplianceSummary | None,
    annual: AnnualSummary | None,
) -> ft.Container:
    """Build the summary screen holding the monthly card and annual table.

    Args:
        monthly: The monthly compliance summary, or ``None`` when unavailable.
        annual: The annual summary, or ``None`` when unavailable.

    Returns:
        An :class:`ft.Container` holding a scrollable column with the monthly
        card and the annual breakdown table.
    """
    return ft.Container(
        content=ft.Column(
            controls=[
                build_monthly_card(monthly),
                build_annual_table(annual),
            ],
            spacing=24,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
        padding=16,
        expand=True,
    )


# ---------------------------------------------------------------------------
# small builders
# ---------------------------------------------------------------------------


def _stat_row(label: str, value: int) -> ft.Row:
    """Build a label/value row for a single count in the monthly card."""
    return ft.Row(
        controls=[ft.Text(label), ft.Text(str(value), weight=ft.FontWeight.BOLD)],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )


def _month_row(summary: ComplianceSummary) -> ft.DataRow:
    """Build a single month row for the annual breakdown table."""
    return ft.DataRow(
        cells=[
            ft.DataCell(ft.Text(calendar.month_name[summary.month])),
            ft.DataCell(ft.Text(str(summary.total_days))),
            ft.DataCell(ft.Text(str(summary.denmark_days))),
            ft.DataCell(ft.Text(str(summary.travel_days))),
            ft.DataCell(ft.Text(str(summary.vacation_days))),
            ft.DataCell(ft.Text(str(summary.sick_days))),
            ft.DataCell(ft.Text(str(summary.home_days))),
            ft.DataCell(ft.Text(f"{summary.compliance_pct:.1f}%")),
        ],
    )


def _totals_row(annual: AnnualSummary) -> ft.DataRow:
    """Build the totals row summarising the whole year."""
    return ft.DataRow(
        cells=[
            ft.DataCell(ft.Text("Total", weight=ft.FontWeight.BOLD)),
            ft.DataCell(ft.Text(str(annual.total_days), weight=ft.FontWeight.BOLD)),
            ft.DataCell(ft.Text(str(annual.denmark_days), weight=ft.FontWeight.BOLD)),
            ft.DataCell(ft.Text(str(annual.travel_days), weight=ft.FontWeight.BOLD)),
            ft.DataCell(ft.Text(str(annual.vacation_days), weight=ft.FontWeight.BOLD)),
            ft.DataCell(ft.Text(str(annual.sick_days), weight=ft.FontWeight.BOLD)),
            ft.DataCell(ft.Text(str(annual.home_days), weight=ft.FontWeight.BOLD)),
            ft.DataCell(
                ft.Text(f"{annual.compliance_pct:.1f}%", weight=ft.FontWeight.BOLD)
            ),
        ],
    )
