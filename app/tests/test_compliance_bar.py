"""Tests for the ``build_compliance_bar`` Flet component (task 11.2).

These tests exercise pure control-builder logic only; the Flet runtime is
never started. They verify the mapping from a ``ComplianceSummary`` (or
``None``) onto a configured ``ft.ProgressBar``.

Requirements: 8.1, 8.3, 8.4, 8.5
"""

from __future__ import annotations

import flet as ft
from hypothesis import given
from hypothesis import strategies as st

from app.api_client import ComplianceSummary
from app.components.compliance_bar import build_compliance_bar

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _summary(
    *,
    compliance_pct: float,
    is_compliant: bool,
    total_days: int = 10,
) -> ComplianceSummary:
    """Build a ``ComplianceSummary`` with the fields the bar reads."""
    return ComplianceSummary(
        year=2025,
        month=6,
        total_days=total_days,
        denmark_days=total_days,
        vacation_days=0,
        sick_days=0,
        home_days=0,
        compliance_pct=compliance_pct,
        is_compliant=is_compliant,
    )


# ---------------------------------------------------------------------------
# unit tests
# ---------------------------------------------------------------------------


def test_returns_progress_bar() -> None:
    bar = build_compliance_bar(_summary(compliance_pct=50.0, is_compliant=True))
    assert isinstance(bar, ft.ProgressBar)


def test_value_is_percentage_over_100() -> None:
    """Requirement 8.1: value == compliance_pct / 100.0."""
    bar = build_compliance_bar(_summary(compliance_pct=75.0, is_compliant=True))
    assert bar.value == 0.75


def test_compliant_bar_is_green() -> None:
    """Requirement 8.3: is_compliant true -> GREEN_600."""
    bar = build_compliance_bar(_summary(compliance_pct=60.0, is_compliant=True))
    assert bar.color == ft.Colors.GREEN_600


def test_non_compliant_bar_is_red() -> None:
    """Requirement 8.4: is_compliant false -> RED_700."""
    bar = build_compliance_bar(_summary(compliance_pct=20.0, is_compliant=False))
    assert bar.color == ft.Colors.RED_700


def test_none_summary_is_neutral_with_no_label() -> None:
    """Requirement 8.5: None -> value 0, visible neutral colour, no label.

    Per Requirement 4.4 (design.md Feature 2) the neutral colour is the
    theme-aware ``ft.Colors.SURFACE`` (task 4.1 changed it from
    ``SURFACE_CONTAINER_HIGHEST``).
    """
    bar = build_compliance_bar(None)
    assert bar.value == 0
    assert bar.color == ft.Colors.SURFACE
    assert bar.tooltip is None


def test_zero_compliance_bar() -> None:
    bar = build_compliance_bar(_summary(compliance_pct=0.0, is_compliant=False))
    assert bar.value == 0.0
    assert bar.color == ft.Colors.RED_700


def test_full_compliance_bar() -> None:
    bar = build_compliance_bar(_summary(compliance_pct=100.0, is_compliant=True))
    assert bar.value == 1.0
    assert bar.color == ft.Colors.GREEN_600


def test_value_clamped_above_100() -> None:
    """A pct above 100 is clamped to 1.0 (matches the module docstring)."""
    bar = build_compliance_bar(_summary(compliance_pct=120.0, is_compliant=True))
    assert bar.value == 1.0


def test_value_clamped_below_0() -> None:
    """A negative pct is clamped to 0.0 (matches the module docstring)."""
    bar = build_compliance_bar(_summary(compliance_pct=-5.0, is_compliant=False))
    assert bar.value == 0.0


# ---------------------------------------------------------------------------
# property-based tests
# ---------------------------------------------------------------------------


@given(
    compliance_pct=st.floats(min_value=0.0, max_value=100.0),
    is_compliant=st.booleans(),
)
def test_value_always_equals_pct_over_100(
    compliance_pct: float, is_compliant: bool
) -> None:
    """For an in-range summary, value == compliance_pct / 100.0 (Req 8.1)."""
    bar = build_compliance_bar(
        _summary(compliance_pct=compliance_pct, is_compliant=is_compliant)
    )
    assert bar.value == compliance_pct / 100.0


@given(
    compliance_pct=st.floats(
        min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
    is_compliant=st.booleans(),
)
def test_value_always_within_unit_range(
    compliance_pct: float, is_compliant: bool
) -> None:
    """For any pct, value stays within the 0.0–1.0 range the control expects."""
    bar = build_compliance_bar(
        _summary(compliance_pct=compliance_pct, is_compliant=is_compliant)
    )
    assert 0.0 <= bar.value <= 1.0


@given(
    compliance_pct=st.floats(min_value=0.0, max_value=100.0),
    is_compliant=st.booleans(),
)
def test_color_follows_is_compliant(compliance_pct: float, is_compliant: bool) -> None:
    """Colour is GREEN_600 iff compliant, RED_700 otherwise (Req 8.3, 8.4)."""
    bar = build_compliance_bar(
        _summary(compliance_pct=compliance_pct, is_compliant=is_compliant)
    )
    expected = ft.Colors.GREEN_600 if is_compliant else ft.Colors.RED_700
    assert bar.color == expected
