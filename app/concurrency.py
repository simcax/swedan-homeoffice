"""Stale-write guard for the Flet app's asynchronous load/mutation coroutines.

Several coroutines in :mod:`app.main` and :mod:`app.views.home_view` fetch data
over the network and then write the result back into the shared
:class:`app.state.AppState`. Because those awaits interleave, a result can
arrive *after* the state it was fetched for has moved on — a newer month-load
started, the backend was switched, or the selected year changed. Writing such a
stale result would resurrect data that no longer matches the UI (and, after a
backend switch, could even send stale record IDs to the new backend).

Historically each coroutine captured the relevant counters by hand and repeated
the same ``if ... : return`` checks inline, so a new call path could easily
forget one. :class:`WriteGuard` centralises that logic: it snapshots the
relevant generation counters at request start and exposes a single
:meth:`WriteGuard.is_stale` check the coroutine runs before committing.

Three counters live on :class:`~app.state.AppState`:

* ``backend_generation`` — bumped when the configured backend changes;
* ``month_load_generation`` — bumped by each month load;
* ``annual_summary_generation`` — bumped by each annual-summary load.

A guard always watches ``backend_generation`` (unless disabled with
``generation=None``) and, depending on its :class:`GuardKind`, one per-request
counter plus — for the annual kind — the selected year.

This module is pure of the Flet runtime so it can be unit-tested directly with a
plain :class:`AppState`.

Requirements: 1.4, 1.5, 8.5
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.state import AppState


def backend_superseded(state: AppState, generation: int | None) -> bool:
    """Return ``True`` when a captured backend ``generation`` is already stale.

    This is the read-side counterpart to :meth:`WriteGuard.is_stale` for the
    backend counter alone. Callers use it as an early-out *before* starting a
    network request (and before :meth:`WriteGuard.capture` bumps any per-request
    counter) so a request against a backend that has already been switched away
    is never issued. ``generation=None`` disables the check, reproducing the
    legacy opt-out behaviour.

    Keeping this comparison in one place means no call path open-codes
    ``state.backend_generation != generation`` and later drifts from the guard.

    Args:
        state: The shared in-memory :class:`AppState`.
        generation: The backend generation captured at request start, or
            ``None`` to disable the check.

    Returns:
        ``True`` when ``generation`` was captured and no longer matches
        ``state.backend_generation``.
    """
    return generation is not None and state.backend_generation != generation


class GuardKind(Enum):
    """Which per-request counter (if any) a :class:`WriteGuard` also watches.

    * ``BACKEND_ONLY`` — only ``backend_generation`` is watched. Used by the
      mutation coroutines (log / delete / edit) that do not own a per-request
      counter.
    * ``MONTH`` — additionally watches ``month_load_generation`` (bumped and
      captured by :func:`app.views.home_view.load_month`).
    * ``ANNUAL`` — additionally watches ``annual_summary_generation`` *and* the
      selected year, so an annual-summary result for a year the user has since
      navigated away from is discarded.
    """

    BACKEND_ONLY = auto()
    MONTH = auto()
    ANNUAL = auto()


@dataclass(frozen=True)
class WriteGuard:
    """Snapshot of the generation counters relevant to a single async write.

    Create one with :meth:`capture` at the start of a load/mutation coroutine,
    then call :meth:`is_stale` immediately before writing the result back into
    state. When the guard reports staleness the coroutine must discard its
    result and return without mutating state.

    Attributes:
        kind: Which per-request counter (and, for ``ANNUAL``, the year) the
            guard watches in addition to ``backend_generation``.
        backend_generation: The ``backend_generation`` captured at request
            start, or ``None`` to disable the backend-generation check (legacy
            behaviour for callers that did not opt in).
        request_generation: The per-request counter captured at request start
            (``month_load_generation`` for ``MONTH``, ``annual_summary_generation``
            for ``ANNUAL``), or ``None`` for ``BACKEND_ONLY``.
        year: The ``selected_month.year`` captured at request start, used only
            by the ``ANNUAL`` kind.
    """

    kind: GuardKind
    backend_generation: int | None
    request_generation: int | None = None
    year: int | None = None

    @classmethod
    def capture(
        cls,
        state: AppState,
        *,
        kind: GuardKind = GuardKind.BACKEND_ONLY,
        generation: int | None = None,
    ) -> WriteGuard:
        """Snapshot the counters a write of ``kind`` must re-check.

        For the ``MONTH`` and ``ANNUAL`` kinds this *bumps* the matching
        per-request counter first (so this request becomes the newest in
        flight) and captures the bumped value, mirroring the per-request counter
        semantics the coroutines relied on before this guard existed. The
        ``ANNUAL`` kind additionally captures ``state.selected_month.year``.

        Args:
            state: The shared in-memory :class:`AppState` to snapshot.
            kind: Which per-request counter (and year) to watch alongside
                ``backend_generation``.
            generation: The backend generation to guard against. When ``None``
                the backend-generation portion of the guard is disabled, exactly
                reproducing the legacy ``generation=None`` behaviour.

        Returns:
            A frozen :class:`WriteGuard` carrying the captured snapshot.
        """
        request_generation: int | None = None
        year: int | None = None

        if kind is GuardKind.MONTH:
            state.month_load_generation += 1
            request_generation = state.month_load_generation
        elif kind is GuardKind.ANNUAL:
            state.annual_summary_generation += 1
            request_generation = state.annual_summary_generation
            year = state.selected_month.year

        return cls(
            kind=kind,
            backend_generation=generation,
            request_generation=request_generation,
            year=year,
        )

    def is_stale(self, state: AppState) -> bool:
        """Return ``True`` when any captured counter no longer matches ``state``.

        The write must be skipped when:

        * the backend generation was captured (not ``None``) and has since
          changed — a backend switch happened mid-request; or
        * a per-request counter was captured (``MONTH`` / ``ANNUAL``) and a
          newer request has since bumped it; or
        * for the ``ANNUAL`` kind, the selected year has changed since capture.

        Args:
            state: The shared in-memory :class:`AppState` to compare against.

        Returns:
            ``True`` when the result is stale and must be discarded.
        """
        if (
            self.backend_generation is not None
            and state.backend_generation != self.backend_generation
        ):
            return True

        if self.kind is GuardKind.MONTH:
            return state.month_load_generation != self.request_generation

        if self.kind is GuardKind.ANNUAL:
            return (
                state.annual_summary_generation != self.request_generation
                or state.selected_month.year != self.year
            )

        return False
