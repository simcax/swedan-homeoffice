"""In-memory UI state for the Flet work-location-tracker app.

``AppState`` holds everything the Flet UI renders:

* ``entries`` — logged work entries keyed by ISO date (``"YYYY-MM-DD"``),
* ``selected_month`` — the month currently displayed in the calendar,
* ``compliance_summary`` — the latest compliance summary for that month,
* ``is_loading`` — whether a backend request is in flight,
* ``error_message`` — the current user-facing error, if any.

This module contains pure dataclass logic only; it never starts the Flet
runtime. Mutations are applied in place and the view layer is responsible for
calling ``page.update()`` afterwards.

Requirements: 1.4, 1.5, 8.5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from app.api_client import ComplianceSummary, WorkEntry

if TYPE_CHECKING:
    from app.views.home_view import ErrorAction


@dataclass
class AppState:
    """Mutable in-memory state backing the Flet UI."""

    selected_month: date
    entries: dict[str, WorkEntry] = field(default_factory=dict)
    compliance_summary: ComplianceSummary | None = None
    is_loading: bool = False
    error_message: str | None = None
    # The surface the latest error should be shown on (inline / banner /
    # snackbar+refresh / notification). ``None`` when there is no active error.
    # Populated by the view layer's error classifier (see
    # ``app.views.home_view.classify_error``).
    error_action: ErrorAction | None = None

    def apply_entry(self, entry: WorkEntry) -> None:
        """Insert or replace ``entry`` keyed by its ISO date string.

        Re-applying an entry for a date that already exists overwrites the
        previous value, keeping exactly one entry per date.
        """
        self.entries[entry.work_date.isoformat()] = entry

    def clear_error(self) -> None:
        """Reset ``error_message`` and ``error_action`` to ``None`` (idempotent)."""
        self.error_message = None
        self.error_action = None
