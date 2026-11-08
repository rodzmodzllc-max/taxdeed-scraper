"""Data-accuracy pass, South Carolina (2026-11-08). Synthetic fixtures only.

SC-1  a county tax-sale list row whose sale day has passed and which the
      county still lists reads `unknown` (no result published), never
      `sold` and never `upcoming` - through the same writer the expansion
      job runs after every sync.
SC-2  York's layer publishes YearBuilt / FinishedSQFT: both are read; a 0 is
      not published; YRBUILT (empty on every feature) is never requested.
SC-4  the registry pins no Horry workbook file (the county replaces it as
      taxes are paid; the harvester follows the newest one).
SC-5  the registry evidence of the sources the owner approved on 2026-10-26
      names that decision, never "UNREVIEWED".
"""
from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from harvesters.governance import inventory_status as IS  # noqa: E402
from harvesters.otc.adapters import arcgis as A  # noqa: E402
from harvesters.otc.adapters import expansion as X  # noqa: E402
import inventory_status_writer as W  # noqa: E402

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
REGISTRY = ROOT / "data" / "county_source_registry.csv"


def _oconee_row(sale_date: str, **kw) -> dict:
    return {"id": "r1", "state": "SC", "county": "Oconee", "case_no": "000-00-00-000", "source": "auction",
            "source_id": "sc_oconee_tax_sale_list", "harvester_source": "sc_oconee_tax_sale_list", "status": "active",
            "sale_date": sale_date, "inventory_status": "upcoming", "last_seen_at": NOW.isoformat(),
            "otc_provenance": {"adapter": "tabular"}, **kw}


# --- SC-1 -----------------------------------------------------------------

def test_listed_row_before_and_on_its_sale_day_is_upcoming():
    for today in (date(2026, 11, 8), date(2026, 11, 9)):
        assert IS.status_for_row(_oconee_row("2026-11-09"), today=today).status == "upcoming"


def test_listed_row_after_its_sale_day_is_unknown_never_sold():
    obs = IS.status_for_row(_oconee_row("2026-11-09"), today=date(2026, 11, 10))
    assert (obs.status, obs.basis) == ("unknown", "SCHEDULED_DATE")
    assert "has passed" in obs.note and obs.status not in IS.RESULT_STATUSES


def test_writer_moves_the_stored_upcoming_row_out_of_upcoming():
    changes, counts = W.plan([_oconee_row("2026-11-09")], today=date(2026, 11, 10), now=NOW)
    assert [c["status"] for c in changes] == ["unknown"] and counts["changed"] == 1


# --- SC-2 -----------------------------------------------------------------

def _payload(*features: dict) -> dict:
    return {"objectIdFieldName": "OBJECTID",
            "features": [{"attributes": {"OBJECTID": i + 1, **f}} for i, f in enumerate(features)]}


def test_york_reads_year_built_and_finished_square_feet():
    page = A.parse_page(X.SC_YORK, _payload(
        {"TAXMAPID": "1", "YearBuilt": 1987, "FinishedSQFT": 1450.0, "YRBUILT": 1900},
        {"TAXMAPID": "2", "YearBuilt": 0, "FinishedSQFT": 0},
        {"TAXMAPID": "3", "YearBuilt": None, "FinishedSQFT": None},
        {"TAXMAPID": "4", "YearBuilt": 12, "FinishedSQFT": 900}), retrieved_at=NOW)
    got = {r.case_no: (r.year_built, r.living_area) for r in page.records}
    assert got == {"1": (1987, 1450), "2": (None, None), "3": (None, None), "4": (None, 900)}
    row = page.records[0].to_properties_row()
    assert (row["year_built"], row["living_area"]) == (1987, 1450)


def test_york_requests_the_filled_columns_never_yrbuilt():
    fields = A._out_fields(X.SC_YORK)
    assert "YearBuilt" in fields and "FinishedSQFT" in fields and "YRBUILT" not in fields


# --- SC-4 / SC-5 ------------------------------------------------------------

def _registry(source_id: str) -> list[dict]:
    with open(REGISTRY, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r["source_id"] == source_id]


def test_horry_registry_row_pins_no_workbook_file():
    (row,) = _registry("sc_horry_tax_sale")
    assert row["document_url"] == "" and row["canonical_url"].startswith("https://www.horrycountysc.gov/")
    assert not hasattr(X, "SC_HORRY_LATEST_READ")


def test_owner_approved_sources_cite_the_decision_not_unreviewed():
    for sid in ("sc_oconee_tax_sale_list", "co_morgan_treasurer_deed_auctions", "wi_dane_tax_deed_auction"):
        rows = _registry(sid)
        assert rows
        for r in rows:
            assert r["publication_status"] == "APPROVED"
            assert "UNREVIEWED" not in r["evidence_ref"] and "2026-10-26" in r["evidence_ref"]
