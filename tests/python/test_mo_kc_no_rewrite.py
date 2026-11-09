"""MO-1 (2026-11-09): Kansas City Land Bank rows rewritten as 'changed' on every read.

Production: the MO sync's write plan reported changed=68..74 on three runs in
a row while change detection saw 0 changes for mo_kc_landbank. The stored
rows did not show which column differed, so:

  * the REAL ePropertyPlus parse -> properties row -> sync path, run twice on
    the same synthetic portal read against an in-memory PostgREST table,
    must write nothing the second time - including the shapes the churning
    rows over-represent (a blank legal description, a point shared by several
    parcels whose coordinates are withheld, a parcel listed twice);
  * write_diff.changed_columns() names what differs (names only, never a
    value) and the sync prints one line per source, so the next production
    run names the volatile column.

Synthetic rows only; no parcel number, owner or address from any source.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(1, str(REPO))

import harvest_expansion as HE  # noqa: E402
import sync_state_inventory as SYNC  # noqa: E402
import write_diff as WD  # noqa: E402
from harvesters.otc.adapters import epropertyplus as EPP  # noqa: E402
from harvesters.otc.adapters import expansion as EX  # noqa: E402
from laft_status import StatusRecorder  # noqa: E402

from test_la_no_pingpong import db  # noqa: E402,F401 - the in-memory PostgREST fixture

CFG = EX.MO_KC_LANDBANK


def _portal_row(n: int, **over) -> dict:
    row = {"id": 9000 + n, "parcelNumber": f"JA{n:017d}", "county": "Jackson", "inventoryType": "Land Bank",
           "propertyAddress1": f"{n} SAMPLE ST", "legalDescription": f"LOT {n} SAMPLE ADDITION",
           "askingPrice": 1000 + n, "currentAssessment": 500 + n, "assessmentYear": "2026",
           "propertyClass": "Residential", "parcelSquareFootage": 4000 + n,
           "latitude": 39.0 + n / 1000, "longitude": -94.5 - n / 1000, "currentStatus": "Available", "available": "Y"}
    row.update(over)
    return row


def _portal_read() -> list[dict]:
    rows = [_portal_row(n) for n in range(1, 7)]
    rows.append(_portal_row(7, legalDescription=None))                     # blank legal description
    rows.append(_portal_row(8, legalDescription=""))
    for n in (9, 10, 11):                                                  # one point for three parcels
        rows.append(_portal_row(n, latitude=39.25, longitude=-94.75))
    rows.append(_portal_row(12, legalDescription=None, latitude=39.25, longitude=-94.75))
    rows.append(_portal_row(1, id=9999))                                   # the same parcel listed twice
    return rows


def _run(table, tmp_path: Path) -> int:
    records, _counts = EPP.parse_rows(CFG, _portal_read(), retrieved_at=datetime.now(timezone.utc))
    prows, _paths = HE.attach_purchase_paths("MO", [r.to_properties_row() for r in records],
                                             harvest_date=datetime.now(timezone.utc).date().isoformat())
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    rows_file, status_file = out / "mo_properties_rows.json", out / "harvest_mo_status.json"
    rows_file.write_text(json.dumps(prows, default=str), encoding="utf-8")
    rec = StatusRecorder("expansion_mo", source_class="GOVERNMENT_DIRECT", source_id="expansion_mo",
                         parser_version=1, path=status_file, state="MO")
    rec.complete(CFG.county, len(records), source_url=CFG.list_url, source_id=CFG.source_id)
    rec.write()
    before = table.writes
    assert SYNC.main(["--state", "MO", "--rows", str(rows_file), "--status", str(status_file)]) == 0
    return table.writes - before


def test_a_second_read_of_the_same_kc_list_writes_nothing(db, tmp_path, capsys):  # noqa: F811
    first = _run(db, tmp_path)
    assert first == 12 == len(db.rows)
    capsys.readouterr()
    assert _run(db, tmp_path) == 0
    out = capsys.readouterr().out
    assert "changed=0" in out and "changed columns" not in out
    assert _run(db, tmp_path) == 0


def test_a_changed_column_is_named_by_the_sync_names_only(db, tmp_path, capsys):  # noqa: F811
    _run(db, tmp_path)
    secret = "SECRET-VALUE-NEVER-LOGGED"
    for r in db.rows[:3]:
        r["legal_desc"] = secret
    capsys.readouterr()
    assert _run(db, tmp_path) == 3
    out = capsys.readouterr().out
    assert "MO changed columns [mo_kc_landbank]: legal_desc=3" in out
    assert secret not in out and "JA0" not in out


def test_changed_columns_names_jsonb_keys_and_skips_volatile_stamps():
    stored = {"a": 1, "otc_provenance": {"x": 1, "retrieved_at": "2026-11-01T00:00:00+00:00"},
              "field_provenance": {"legal_desc": {"source": "county_list", "recorded_at": "t1"}}}
    row = {"a": 1, "last_seen_at": "now", "otc_provenance": {"x": 1, "retrieved_at": "2026-11-09T00:00:00+00:00"},
           "field_provenance": {"legal_desc": {"source": "county_list", "recorded_at": "t2"}}}
    assert WD.changed_columns(row, stored) == []
    row["otc_provenance"] = {"x": 2, "y": 0}
    row["b"] = None
    assert WD.changed_columns(row, stored) == ["otc_provenance.x", "otc_provenance.y", "b (not stored)"]
    assert WD.changed_columns(row, None) == []
    counts = WD.changed_column_counts([dict(row, k=1)], {1: stored}, key=lambda r: r["k"], group=lambda r: "s")
    assert counts == {"s": {"otc_provenance.x": 1, "otc_provenance.y": 1, "b (not stored)": 1, "k (not stored)": 1}}
    assert SYNC.changed_columns_lines("MO", {"s": {"a": 1, "b": 3}}) == ["MO changed columns [s]: b=3, a=1"]


# ------------------------------------------------------------ MO-5: the gate's acquisition summary

def test_gate_summary_separates_per_property_links_from_county_level_urls():
    import publication_gate as G  # noqa: PLC0415

    def row(t, scope, url="https://example.gov/x"):
        return {"source": "laft", "status": "active", "county": "St. Louis City", "source_id": "mo_stl_lra_inventory",
                "publication_status": "APPROVED", "purchase_path_type": t, "purchase_path_scope": scope, "purchase_url": url,
                "otc_provenance": {"acquisition": {"steps": ["Submit the offer form"], "phone": "1"}}}

    rows = [row("direct_property_url", "property") for _ in range(3)] + [row("application_download", "source") for _ in range(2)]
    rep = G.acquisition_coverage_report(rows)
    assert rep["with_acquisition_path"] == 5
    assert rep["with_direct_acquisition_url"] == 5          # every URL-type path, as before
    assert rep["with_property_url"] == 3                    # only the per-property links
    assert rep["by_path_type"] == {"direct_property_url/property": 3, "application_download/source": 2}


# ------------------------------------------------------------ MO-4: Missouri copy agrees with the records

def test_missouri_copy_no_longer_contradicts_the_publication_decision_or_the_verified_procedure():
    from harvesters.governance import state_rules as SR  # noqa: PLC0415

    ledger = next(l for l in SR.load_ledgers() if l.state == "MO" and l.ledger == "AVAILABLE")
    assert "awaiting review" not in ledger.note and "unresolved" not in ledger.eligibility_basis.lower()
    rules = {(r.county, r.topic): r for r in SR.load_rules() if r.state == "MO"}
    assert rules[("St. Louis City", "acquisition_procedure_available")].status == "VERIFIED"
    old = rules[("St. Louis City", "acquisition_process")]
    assert old.status != "NOT_VERIFIED" and old.version == "2" and "Superseded" in old.statement
    assert not SR.history_problems(SR.load_rules(), SR.load_history())
