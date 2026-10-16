"""Compliance progress-bar component for the work-location-tracker app.

Renders the monthly Denmark-compliance percentage as a ``ft.ProgressBar``:

* ``value`` is ``compliance_pct / 100.0`` clamped to the 0.0–1.0 range the
  control expects,
* the bar is green (:data:`ft.Colors.GREEN_600`) when the month is compliant
  and red (:data:`ft.Colors.RED_700`) otherwise,
* when there is no summary yet (``None``), the bar is drawn in a neutral but
  still-visible colour (:data:`ft.Colors.SURFACE_CONTAINER_HIGHEST`) with
  ``value=0`` and no percentage label.

This module contains pure control-builder logic only; it never starts the
Flet runtime.

Requirements: 8.1, 8.3, 8.4, 8.5
"""

from __future__ import annotations

import flet as ft

from app.api_client import ComplianceSummary


def build_compliance_bar(summary: ComplianceSummary | None) -> ft.ProgressBar:
    """Build a compliance ``ft.ProgressBar`` for ``summary``.

    Args:
        summary: The latest monthly compliance summary, or ``None`` when no
            summary is available (e.g. still loading).

    Returns:
        A configured :class:`ft.ProgressBar`. When ``summary`` is ``None`` the
        bar is neutral (``value=0``, a visible surface-container colour, no
        tooltip label); otherwise it reflects the compliance percentage and
        status.
    """
    if summary is None:
        return ft.ProgressBar(value=0, color=ft.Colors.SURFACE_CONTAINER_HIGHEST)

    value = max(0.0, min(1.0, summary.compliance_pct / 100.0))
    color = ft.Colors.GREEN_600 if summary.is_compliant else ft.Colors.RED_700
    return ft.ProgressBar(
        value=value,
        color=color,
        tooltip=f"{summary.compliance_pct:.1f}%",
    )
