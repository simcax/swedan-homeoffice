"""In-memory UI state for the Flet work-location-tracker app.

``AppState`` holds everything the Flet UI renders:

* ``entries`` — logged work entries keyed by ISO date (``"YYYY-MM-DD"``),
* ``selected_month`` — the month currently displayed in the calendar,
* ``compliance_summary`` — the latest compliance summary for that month,
* ``annual_summary`` — the latest annual summary for the selected year,
* ``is_loading`` — whether a backend request is in flight,
* ``error_message`` — the current user-facing error, if any,
* ``backend_generation`` — a monotonic counter identifying the current
  backend "era", bumped whenever the configured backend changes so results
  from requests started under an earlier backend can be discarded.
* ``month_load_generation`` — a request counter that prevents older month
  loads from replacing newer navigation results.
* ``annual_summary_generation`` — a request counter that prevents older
  overlapping annual-summary responses from replacing newer results.

This module contains pure dataclass logic only; it never starts the Flet
runtime. Mutations are applied in place and the view layer is responsible for
calling ``page.update()`` afterwards.

Requirements: 1.4, 1.5, 5.1, 8.3, 8.5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum, auto
from typing import TYPE_CHECKING

from app.api_client import AnnualSummary, ComplianceSummary, WorkEntry

if TYPE_CHECKING:
    from app.views.home_view import ErrorAction


class Screen(Enum):
    """The gated screen currently shown by the Flet app.

    ``LOGIN`` withholds the front page until a shared secret is supplied;
    ``HOME`` shows the calendar front page once a secret is configured.

    Requirements: 5.1, 8.3
    """

    LOGIN = auto()
    HOME = auto()


@dataclass
class AppState:
    """Mutable in-memory state backing the Flet UI."""

    selected_month: date
    entries: dict[str, WorkEntry] = field(default_factory=dict)
    compliance_summary: ComplianceSummary | None = None
    annual_summary: AnnualSummary | None = None
    is_loading: bool = False
    error_message: str | None = None
    # The surface the latest error should be shown on (inline / banner /
    # snackbar+refresh / notification). ``None`` when there is no active error.
    # Populated by the view layer's error classifier (see
    # ``app.views.home_view.classify_error``).
    error_action: ErrorAction | None = None
    # Identifies the current backend "era". It starts at 0 and is bumped by
    # ``reset_for_new_backend`` whenever the configured backend changes. Load
    # and mutation coroutines capture it when they start and re-check it before
    # writing results, so a request started under an earlier backend that
    # completes after a switch is discarded instead of writing stale IDs.
    backend_generation: int = 0
    # Ensures the latest month-load request wins when navigation overlaps.
    month_load_generation: int = 0
    # Ensures the latest annual-summary request wins when refreshes overlap.
    annual_summary_generation: int = 0
    # The gated screen currently shown by the app. Starts at ``LOGIN`` so the
    # front page is withheld until a shared secret is supplied (Req 5.1).
    screen: Screen = Screen.LOGIN
    # Drives the "secret rejected" message on the login screen after a backend
    # 401 sends the user back to login (Req 8.3).
    auth_rejected: bool = False

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
