"""Compliance calculation service.

``ComplianceService`` is a pure-function service — it takes lists of
``WorkEntry`` records and computes :class:`ComplianceSummary` /
:class:`AnnualSummary` values. It has no database dependency.

A **compliant day** is any day logged as ``denmark``, ``vacation`` or ``sick``;
those days count toward the 50 % Denmark-presence requirement. ``home`` days do
not. A summary ``is_compliant`` when its ``compliance_pct >= 50.0``.

Requirements: 6.3, 6.4, 6.5, 6.6, 7.2, 7.3, 7.4, 7.5
"""

from collections import defaultdict

from backend.models import WorkEntry
from backend.schemas import AnnualSummary, ComplianceSummary

# Threshold (percentage) at or above which a period is considered compliant.
_COMPLIANCE_THRESHOLD = 50.0


class ComplianceService:
    """Pure-function service for computing compliance summaries."""

    def calculate_monthly(
        self,
        entries: list[WorkEntry],
        year: int | None = None,
        month: int | None = None,
    ) -> ComplianceSummary:
        """Compute a :class:`ComplianceSummary` for a single period.

        Follows the ``calculate_compliance`` pseudocode: count locations with a
        loop maintaining the invariant
        ``denmark + vacation + sick + home == entries_processed`` and derive the
        compliance percentage.

        ``compliance_pct`` is ``0.0`` when there are no entries. The summary's
        ``year``/``month`` labels come from the explicit ``year``/``month``
        arguments when supplied — which is what callers should do so the
        requested period is preserved even for empty results. When an argument
        is ``None`` the value is inferred from the first entry, falling back to
        ``0`` only when there are no entries and no explicit value.
        """
        total = len(entries)
        denmark = 0
        vacation = 0
        sick = 0
        home = 0

        for entry in entries:
            # Loop invariant: counts sum to the number of entries processed.
            if entry.location == "denmark":
                denmark += 1
            elif entry.location == "vacation":
                vacation += 1
            elif entry.location == "sick":
                sick += 1
            elif entry.location == "home":
                home += 1

        compliant = denmark + vacation + sick
        pct = (compliant / total) * 100.0 if total > 0 else 0.0

        # Explicit period labels win; otherwise infer from entries, then 0.
        if year is None:
            year = entries[0].work_date.year if entries else 0
        if month is None:
            month = entries[0].work_date.month if entries else 0

        return ComplianceSummary(
            year=year,
            month=month,
            total_days=total,
            denmark_days=denmark,
            vacation_days=vacation,
            sick_days=sick,
            home_days=home,
            compliance_pct=pct,
            is_compliant=pct >= _COMPLIANCE_THRESHOLD,
        )

    def calculate_annual(
        self, entries: list[WorkEntry], year: int | None = None
    ) -> AnnualSummary:
        """Compute an :class:`AnnualSummary` with a 12-month breakdown.

        Groups entries by calendar month, produces exactly 12
        :class:`ComplianceSummary` items (months 1–12; empty months have
        ``total_days == 0``), then rolls the per-month totals up into the annual
        summary. Annual ``compliance_pct`` is rounded to 2 decimal places
        (requirement 7.4).

        The requested ``year`` is preserved on the annual summary and on every
        monthly breakdown item — including empty months and years with no
        entries at all. Callers should pass ``year`` explicitly; when it is
        ``None`` the value is inferred from the first entry, falling back to
        ``0`` only for an empty input with no explicit year.
        """
        if year is None:
            year = entries[0].work_date.year if entries else 0

        # Group entries by month (1–12).
        monthly_map: dict[int, list[WorkEntry]] = defaultdict(list)
        for entry in entries:
            monthly_map[entry.work_date.month].append(entry)

        monthly_breakdown: list[ComplianceSummary] = []
        for month in range(1, 13):
            # Pass the period labels explicitly so empty months are labeled
            # with the requested year/month rather than 0.
            summary = self.calculate_monthly(
                monthly_map.get(month, []), year=year, month=month
            )
            monthly_breakdown.append(summary)

        total = sum(s.total_days for s in monthly_breakdown)
        denmark = sum(s.denmark_days for s in monthly_breakdown)
        vacation = sum(s.vacation_days for s in monthly_breakdown)
        sick = sum(s.sick_days for s in monthly_breakdown)
        home = sum(s.home_days for s in monthly_breakdown)

        compliant = denmark + vacation + sick
        pct = round((compliant / total) * 100.0, 2) if total > 0 else 0.0

        return AnnualSummary(
            year=year,
            total_days=total,
            denmark_days=denmark,
            vacation_days=vacation,
            sick_days=sick,
            home_days=home,
            compliance_pct=pct,
            is_compliant=pct >= _COMPLIANCE_THRESHOLD,
            monthly_breakdown=monthly_breakdown,
        )
