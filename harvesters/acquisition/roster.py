"""Observed source rosters - Phase 40 (Real-Network Acquisition Activation).

Repository audit finding (Phase 40 Sections 5-8): the Phase 33/35 county
coverage matrix named `tx_lgbs` for **8** Texas counties, with its own note
saying the "full 45+ county roster [was] not re-extracted this phase." Phase
39 measured the live API at 6,309 rows for `area=TX` and flagged the
understatement. Phase 40 measured the actual footprint: **95 Texas
counties**.

An "observed roster" is a fundamentally different kind of record from the
coverage matrix, and this module keeps them separate rather than editing the
matrix in place:

  - `data/*_county_coverage_matrix.csv` (Phase 33/35) records what RESEARCH
    established about which sources serve a county. It is a governance-
    adjacent research artifact, hand-curated, with its own evidence trail.
  - `data/tx_lgbs_observed_county_roster.csv` (this module) records what a
    SOURCE ACTUALLY RETURNED when measured, with a date and a measurement
    method. It is an empirical observation, and it can change every time the
    source publishes a new sale calendar.

Conflating the two would let an empirical observation silently rewrite a
researched governance record - exactly the kind of drift Phase 37/38's
five-layer model exists to prevent. The matrix is left untouched; this
roster is additive, and `config.py` consults both.

**Measurement method, and why it is trustworthy** (Phase 40 Sections 6, 45):
every count is the API's own top-level `count` for a per-county filtered
query. Before any count was trusted, the `county=` filter was validated as
genuinely honored by querying a deliberately bogus county name - it returned
`count=0` rather than the unfiltered total. That check mattered: this API
SILENTLY IGNORES unknown query parameters (`county__icontains=` and
`search=` both returned the full unfiltered 6,309), so an unvalidated filter
would have produced 95 identical, meaningless numbers.

The roster's arithmetic is self-validating: `?state=TX` = 4,205 and
`?state=PA` = 2,104 sum exactly to the 6,309 total, and the 95 measured
counties sum to 4,197 - leaving an explicitly recorded 8-record (0.19%)
residual rather than a distributed or hidden one.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TX_LGBS_ROSTER_PATH = REPO_ROOT / "data" / "tx_lgbs_observed_county_roster.csv"

# The sentinel county name used for records the scan could not attribute to a
# named county. Never a real jurisdiction; callers must exclude it from any
# county list (see `observed_counties()`).
UNATTRIBUTED_RESIDUAL = "(UNATTRIBUTED RESIDUAL)"


@dataclass(frozen=True)
class ObservedCountyRecord:
    """One measured (source, state, county) observation."""

    state: str
    county: str
    source_id: str
    records_observed: int
    first_observed_at: str
    last_observed_at: str
    measurement_method: str
    sale_statuses_observed: str = ""
    notes: str = ""

    @property
    def is_residual(self) -> bool:
        return self.county == UNATTRIBUTED_RESIDUAL

    @property
    def jurisdiction(self) -> str:
        return f"{self.state}/{self.county}"


def load_tx_lgbs_roster() -> list[ObservedCountyRecord]:
    """Read the roster live from disk - never cached into a second copy that
    could drift from the CSV (the same discipline `source_catalog.load_fl_matrix()`
    already uses)."""
    if not TX_LGBS_ROSTER_PATH.exists():
        return []
    with open(TX_LGBS_ROSTER_PATH, newline="", encoding="utf-8") as f:
        return [
            ObservedCountyRecord(
                state=row["state"],
                county=row["county"],
                source_id=row["source_id"],
                records_observed=int(row["records_observed"]),
                first_observed_at=row["first_observed_at"],
                last_observed_at=row["last_observed_at"],
                measurement_method=row["measurement_method"],
                sale_statuses_observed=row.get("sale_statuses_observed", ""),
                notes=row.get("notes", ""),
            )
            for row in csv.DictReader(f)
        ]


def observed_counties(source_id: str = "tx_lgbs", *, state: str = "TX") -> list[str]:
    """The real county footprint for a source, excluding the residual
    sentinel and any out-of-state county. This is what `config.py` uses to
    expand county coverage."""
    return sorted(
        r.county
        for r in load_tx_lgbs_roster()
        if r.source_id == source_id and r.state == state and not r.is_residual
    )


def observed_record_count(county: str, source_id: str = "tx_lgbs", *, state: str = "TX") -> int | None:
    """Measured record count for one county, or None if never measured.
    `None` is deliberately distinct from `0`: never-measured is not the same
    finding as measured-and-empty (Phase 40 Section 30)."""
    for record in load_tx_lgbs_roster():
        if record.source_id == source_id and record.state == state and record.county == county:
            return record.records_observed
    return None


def roster_totals(source_id: str = "tx_lgbs") -> dict:
    """Measured totals plus the residual, so any consumer can see the
    attribution completeness rather than assuming the roster is exhaustive."""
    records = [r for r in load_tx_lgbs_roster() if r.source_id == source_id]
    in_state = [r for r in records if r.state == "TX" and not r.is_residual]
    residual = next((r.records_observed for r in records if r.is_residual), 0)
    out_of_state = [r for r in records if r.state != "TX"]
    measured = sum(r.records_observed for r in in_state)
    return {
        "counties_measured": len(in_state),
        "records_measured": measured,
        "unattributed_residual": residual,
        "authoritative_state_total": measured + residual,
        "attribution_completeness_pct": (
            round(100.0 * measured / (measured + residual), 2) if (measured + residual) else None
        ),
        "out_of_state_records": sum(r.records_observed for r in out_of_state),
        "out_of_state_counties": [r.jurisdiction for r in out_of_state],
    }
