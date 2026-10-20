"""Compliance indicator components for the work-location-tracker app.

Provides two control builders plus the pure derivations they share:

* :func:`build_compliance_indicator` renders the monthly compliance as a
  circular :class:`ft.ProgressRing` wrapped in a :class:`ft.Stack` that centres
  a numeric fill label and a days-missing caption. The ring fill is proportional
  to :data:`COMPLIANCE_THRESHOLD`, green when compliant and red otherwise, and a
  neutral empty ring when no summary is available. This supersedes the linear
  bar on the home view (Requirements 1.1, 1.4, 1.5, 2.1).
* :func:`build_compliance_bar` renders the same percentage as a
  ``ft.ProgressBar`` and is retained for the summary cards.

The pure helpers (:func:`fill_fraction`, :func:`display_percent`,
:func:`days_missing`) derive everything from the fields already on
:class:`ComplianceSummary`, so no backend request or new field is needed.

This module contains pure control-builder logic only; it never starts the
Flet runtime.

Requirements: 1.1, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4
"""

from __future__ import annotations

import math

import flet as ft

from app.api_client import ComplianceSummary

# The compliance percentage at which a month is considered compliant. Pinned
# frontend-side because no backend field supplies a required-days target. It
# represents 100% of the circular indicator's fill (Requirements 1.1, 1.2, 2.1).
COMPLIANCE_THRESHOLD: float = 60.0

# Theme-aware colours for the circular indicator's ring.
_COMPLIANT_COLOR = ft.Colors.GREEN_600
_NON_COMPLIANT_COLOR = ft.Colors.RED_700
_NEUTRAL_COLOR = ft.Colors.SURFACE

# Fixed edge of the circular indicator so the ring and the centred label stack
# share the same bounding box.
_INDICATOR_SIZE = 120


def fill_fraction(summary: ComplianceSummary) -> float:
    """Ring fill in ``[0.0, 1.0]``: ``compliance_pct`` relative to the threshold.

    Guards against a non-positive threshold (which would otherwise divide by
    zero) by treating it as a fully filled ring.

    Requirements: 1.1, 1.2
    """
    if COMPLIANCE_THRESHOLD <= 0:
        return 1.0
    return max(0.0, min(1.0, summary.compliance_pct / COMPLIANCE_THRESHOLD))


def display_percent(summary: ComplianceSummary) -> int:
    """Centre-label percent, clamped to the inclusive range ``1..100``.

    Requirements: 1.3
    """
    raw = round(fill_fraction(summary) * 100)
    return max(1, min(100, raw))


def days_missing(summary: ComplianceSummary) -> int:
    """Office/Denmark days still needed to reach the threshold.

    Derived only from fields already on :class:`ComplianceSummary`
    (``compliance_pct``, ``denmark_days``, ``total_days``) with no backend
    request or new field. When the month is already compliant the result is 0;
    otherwise the real-valued shortfall is rounded UP so any partial remaining
    day counts as one whole day. A ``total_days`` of 0 yields ``required == 0``
    and therefore a result of 0 rather than raising.

    Requirements: 2.1, 2.2, 2.3, 2.4
    """
    if summary.compliance_pct >= COMPLIANCE_THRESHOLD:
        return 0

    # required = ceil(threshold/100 * total_days); shortfall floored at 0.
    required = math.ceil((COMPLIANCE_THRESHOLD / 100.0) * summary.total_days)
    shortfall = required - summary.denmark_days
    return max(0, shortfall)


def build_compliance_bar(summary: ComplianceSummary | None) -> ft.ProgressBar:
    """Build a compliance ``ft.ProgressBar`` for ``summary``.

    Args:
        summary: The latest monthly compliance summary, or ``None`` when no
            summary is available (e.g. still loading).

    Returns:
        A configured :class:`ft.ProgressBar`. When ``summary`` is ``None`` the
        bar is neutral (``value=0``, the theme-aware ``ft.Colors.SURFACE``
        colour, no tooltip label); otherwise it reflects the compliance
        percentage and status.
    """
    if summary is None:
        return ft.ProgressBar(value=0, color=ft.Colors.SURFACE)

    value = max(0.0, min(1.0, summary.compliance_pct / 100.0))
    color = ft.Colors.GREEN_600 if summary.is_compliant else ft.Colors.RED_700
    return ft.ProgressBar(
        value=value,
        color=color,
        tooltip=f"{summary.compliance_pct:.1f}%",
    )


def build_compliance_indicator(summary: ComplianceSummary | None) -> ft.Stack:
    """Build the circular compliance indicator for ``summary``.

    Returns an :class:`ft.Stack` layering a circular :class:`ft.ProgressRing`
    under a centred :class:`ft.Column` that shows the fill percent and a
    days-missing caption. The ring fill comes from :func:`fill_fraction`, the
    centre label from :func:`display_percent`, and the caption from
    :func:`days_missing`. The ring is green when the month is compliant and red
    otherwise.

    Args:
        summary: The latest monthly compliance summary, or ``None`` when no
            summary is available (e.g. still loading).

    Returns:
        A configured :class:`ft.Stack`. When ``summary`` is ``None`` the stack
        holds a single neutral, empty ring (``value=0``, the theme-aware
        ``ft.Colors.SURFACE`` colour) with no centre label and no days-missing
        caption (Requirement 1.4).

    Requirements: 1.1, 1.4, 1.5
    """
    if summary is None:
        ring = ft.ProgressRing(
            value=0,
            color=_NEUTRAL_COLOR,
            width=_INDICATOR_SIZE,
            height=_INDICATOR_SIZE,
        )
        return ft.Stack(
            controls=[ring],
            width=_INDICATOR_SIZE,
            height=_INDICATOR_SIZE,
        )

    color = _COMPLIANT_COLOR if summary.is_compliant else _NON_COMPLIANT_COLOR
    ring = ft.ProgressRing(
        value=fill_fraction(summary),
        color=color,
        width=_INDICATOR_SIZE,
        height=_INDICATOR_SIZE,
    )

    missing = days_missing(summary)
    caption = "Compliant" if missing == 0 else f"{missing} day(s) to go"
    label = ft.Column(
        controls=[
            ft.Text(f"{display_percent(summary)}%", weight=ft.FontWeight.BOLD),
            ft.Text(caption, size=11),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=2,
    )
    centre = ft.Container(
        content=label,
        alignment=ft.Alignment.CENTER,
        width=_INDICATOR_SIZE,
        height=_INDICATOR_SIZE,
    )
    return ft.Stack(
        controls=[ring, centre],
        width=_INDICATOR_SIZE,
        height=_INDICATOR_SIZE,
    )
