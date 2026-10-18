"""Tests for the summary view (task 12.2).

These tests exercise the summary view's control-builder logic with mocked
``ComplianceSummary`` / ``AnnualSummary`` data; the Flet runtime is never
started. They verify:

* the monthly card renders every count field plus the compliance bar
  (Requirements 6.1, 8.1, 8.3, 8.4),
* the annual breakdown table has exactly one row per month (12) plus a totals
  row with the correct figures (Requirement 7.1),
* ``None`` inputs produce neutral placeholders without raising.

Requirements: 6.1, 7.1, 8.1, 8.3, 8.4
"""

from __future__ import annotations

import flet as ft

from app.api_client import AnnualSummary, ComplianceSummary
from app.views.summary_view import (
    build_annual_table,
    build_monthly_card,
    build_summary_view,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _monthly(
    *,
    month: int = 6,
    total: int = 10,
    denmark: int = 5,
    vacation: int = 1,
    sick: int = 1,
    home: int = 3,
    compliance_pct: float = 70.0,
    is_compliant: bool = True,
) -> ComplianceSummary:
    return ComplianceSummary(
        year=2025,
        month=month,
        total_days=total,
        denmark_days=denmark,
        vacation_days=vacation,
        sick_days=sick,
        home_days=home,
        compliance_pct=compliance_pct,
        is_compliant=is_compliant,
    )


def _annual(
    *, compliance_pct: float = 55.0, is_compliant: bool = True
) -> AnnualSummary:
    breakdown = [
        _monthly(
            month=m,
            total=m,
            denmark=m,
            vacation=0,
            sick=0,
            home=0,
            compliance_pct=100.0,
        )
        for m in range(1, 13)
    ]
    total = sum(s.total_days for s in breakdown)
    return AnnualSummary(
        year=2025,
        total_days=total,
        denmark_days=total,
        vacation_days=0,
        sick_days=0,
        home_days=0,
        compliance_pct=compliance_pct,
        is_compliant=is_compliant,
        monthly_breakdown=breakdown,
    )


def _flatten(control: ft.Control) -> list[ft.Control]:
    """Depth-first flatten of a control tree via ``controls``/``content``."""
    found = [control]
    for child in getattr(control, "controls", None) or []:
        if isinstance(child, ft.Control):
            found.extend(_flatten(child))
    child = getattr(control, "content", None)
    if isinstance(child, ft.Control):
        found.extend(_flatten(child))
    return found


def _texts(control: ft.Control) -> list[str]:
    """Collect all ``ft.Text.value`` strings in the tree."""
    return [c.value for c in _flatten(control) if isinstance(c, ft.Text)]


# ---------------------------------------------------------------------------
# build_monthly_card (Requirements 6.1, 8.1, 8.3, 8.4)
# ---------------------------------------------------------------------------


class TestBuildMonthlyCard:
    def test_returns_card(self) -> None:
        card = build_monthly_card(_monthly())
        assert isinstance(card, ft.Card)

    def test_contains_compliance_bar(self) -> None:
        card = build_monthly_card(_monthly())
        assert any(isinstance(c, ft.ProgressBar) for c in _flatten(card))

    def test_renders_all_count_fields(self) -> None:
        summary = _monthly(
            total=20, denmark=12, vacation=3, sick=1, home=4, compliance_pct=80.0
        )
        card = build_monthly_card(summary)
        texts = _texts(card)
        joined = " ".join(texts)

        # Every labelled count appears, as does the compliance percentage.
        for label in ("Total days", "Denmark", "Vacation", "Sick", "Home"):
            assert label in joined
        assert "20" in texts  # total
        assert "12" in texts  # denmark
        assert "3" in texts  # vacation
        assert "4" in texts  # home
        assert any("80.0%" in t for t in texts)

    def test_compliant_bar_is_green(self) -> None:
        card = build_monthly_card(_monthly(compliance_pct=70.0, is_compliant=True))
        bar = next(c for c in _flatten(card) if isinstance(c, ft.ProgressBar))
        assert bar.color == ft.Colors.GREEN_600
        assert bar.value == 0.7

    def test_non_compliant_bar_is_red(self) -> None:
        card = build_monthly_card(_monthly(compliance_pct=20.0, is_compliant=False))
        bar = next(c for c in _flatten(card) if isinstance(c, ft.ProgressBar))
        assert bar.color == ft.Colors.RED_700

    def test_none_summary_is_neutral_placeholder(self) -> None:
        # The monthly card's neutral bar is produced by ``build_compliance_bar``
        # (see build_monthly_card), so task 4.1's change of the ``summary is
        # None`` neutral colour to the theme-aware ``ft.Colors.SURFACE``
        # (Requirement 4.4) flows through here unchanged.
        card = build_monthly_card(None)
        bar = next(c for c in _flatten(card) if isinstance(c, ft.ProgressBar))
        assert bar.color == ft.Colors.SURFACE
        assert any("No summary" in t for t in _texts(card))


# ---------------------------------------------------------------------------
# build_annual_table (Requirement 7.1)
# ---------------------------------------------------------------------------


class TestBuildAnnualTable:
    def test_contains_a_data_table(self) -> None:
        control = build_annual_table(_annual())
        assert any(isinstance(c, ft.DataTable) for c in _flatten(control))

    def test_has_twelve_month_rows_plus_totals(self) -> None:
        control = build_annual_table(_annual())
        table = next(c for c in _flatten(control) if isinstance(c, ft.DataTable))
        # 12 months + 1 totals row.
        assert len(table.rows) == 13

    def test_has_a_column_per_header(self) -> None:
        control = build_annual_table(_annual())
        table = next(c for c in _flatten(control) if isinstance(c, ft.DataTable))
        assert len(table.columns) == 7

    def test_totals_row_reflects_annual_totals(self) -> None:
        annual = _annual()
        control = build_annual_table(annual)
        table = next(c for c in _flatten(control) if isinstance(c, ft.DataTable))
        totals_row = table.rows[-1]
        totals_texts = [
            cell.content.value
            for cell in totals_row.cells
            if isinstance(cell.content, ft.Text)
        ]
        assert "Total" in totals_texts
        assert str(annual.total_days) in totals_texts

    def test_none_annual_is_neutral_placeholder(self) -> None:
        control = build_annual_table(None)
        assert not any(isinstance(c, ft.DataTable) for c in _flatten(control))
        assert any("No annual summary" in t for t in _texts(control))


# ---------------------------------------------------------------------------
# build_summary_view
# ---------------------------------------------------------------------------


class TestBuildSummaryView:
    def test_returns_container(self) -> None:
        view = build_summary_view(_monthly(), _annual())
        assert isinstance(view, ft.Container)

    def test_contains_card_and_table(self) -> None:
        view = build_summary_view(_monthly(), _annual())
        flat = _flatten(view)
        assert any(isinstance(c, ft.Card) for c in flat)
        assert any(isinstance(c, ft.DataTable) for c in flat)

    def test_handles_all_none_without_error(self) -> None:
        view = build_summary_view(None, None)
        assert isinstance(view, ft.Container)
        # Both placeholders present, no table.
        assert not any(isinstance(c, ft.DataTable) for c in _flatten(view))
