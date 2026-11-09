"""Data-accuracy pass, Minnesota (2026-11-09). Synthetic fixtures only.

MN-D1  Wright County's tax-forfeit layer (an AUCTIONS ArcGIS source with a
       mapped Status column) - the sync stores the status word 'Open' in
       inventory_status_raw; the inventory-status writer must then see the row
       unchanged. Before, its observation carried raw=None, so every run
       cleared raw, re-wrote 'active' and appended a status_changed row, and
       the next sync wrote 'Open' back (836 spurious observations).
MN-D2  a gone auction row is 'sold' only from a sold-flag wording the adapters
       build ("<sold_flag>: Yes", "SOLD") - a status column's availability word
       ('Open') on a row that left the list reads 'closed'.
MN-D3  the state ledger copy no longer says the sources the owner approved on
       2026-10-26 are awaiting review.
MN-D4  unit freshness drops persisted units no current registry row names.
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
TODAY = date(2026, 11, 10)


def _wright_payload(*pids: str) -> dict:
    return {"objectIdFieldName": "OBJECTID",
            "features": [{"attributes": {"OBJECTID": i + 1, "PID": pid, "Status": "Open", "LEGAL": "SYNTHETIC LEGAL",
                                         "Auction_Starting_Price": 1000.0}}
                         for i, pid in enumerate(pids)]}


def _synced_row(rec, *, row_id: str, stored: dict | None = None) -> dict:
    """What the sync leaves in `properties`: the adapter's row merged over the
    stored lifecycle columns (the sync never writes inventory_status)."""
    row = rec.to_properties_row()
    row.update({"id": row_id, "last_seen_at": NOW.isoformat(), "source_id": rec.source_id,
                "harvester_source": rec.source_id})
    for k, v in (stored or {}).items():
        row.setdefault(k, v)
    if stored and "inventory_status" in stored:
        row["inventory_status"] = stored["inventory_status"]
    return row


def _apply(row: dict, changes: list[dict]) -> dict:
    """Apply the writer's PATCH payload to the row, as PostgREST would."""
    for payload, ids in W.group_changes(changes):
        if row["id"] in ids:
            row = {**row, **payload}
    return row


# --- MN-D1 ----------------------------------------------------------------

def test_wright_sync_stores_the_status_word_verbatim():
    page = A.parse_page(X.MN_WRIGHT_TAX_FORFEIT, _wright_payload("SYN-1"), retrieved_at=NOW)
    row = page.records[0].to_properties_row()
    assert row["source"] == "auction" and row["inventory_status_raw"] == "Open"


def test_wright_sync_then_writer_twice_gives_no_change_on_the_second_run():
    rec = A.parse_page(X.MN_WRIGHT_TAX_FORFEIT, _wright_payload("SYN-1"), retrieved_at=NOW).records[0]
    # Run 1: a new row - the writer records its first status.
    row = _synced_row(rec, row_id="w1")
    changes, counts = W.plan([row], today=TODAY, now=NOW)
    assert counts["changed"] == 1 and changes[0]["transition"] == "newly_observed"
    assert changes[0]["raw"] == "Open"
    row = _apply(row, changes)
    assert row["inventory_status_raw"] == "Open"         # the writer never clears the sync's wording
    # Run 2 and 3: the sync writes 'Open' again; the writer sees no change.
    for _ in range(2):
        row = _synced_row(rec, row_id="w1", stored={"inventory_status": row["inventory_status"],
                                                    "inventory_status_basis": row["inventory_status_basis"]})
        changes, counts = W.plan([row], today=TODAY, now=NOW)
        assert changes == [] and counts["unchanged"] == 1 and counts["changed"] == 0


def test_every_on_list_auction_branch_carries_the_stored_wording():
    base = {"id": "x", "state": "MN", "county": "Wright", "case_no": "SYN-1", "source": "auction",
            "source_id": "mn_wright_tax_forfeit", "status": "active", "inventory_status_raw": "Open",
            "otc_provenance": {"adapter": "arcgis"}}
    cases = [
        {},                                                   # no sale date -> active
        {"sale_date": "2026-12-01"},                          # upcoming
        {"sale_date": "2026-10-01"},                          # past -> unknown
        {"otc_provenance": {"adapter": "arcgis", "list_superseded": "a newer list exists"}},
    ]
    for extra in cases:
        obs = IS.adapter_record_status({**base, **extra}, today=TODAY)
        assert obs is not None and obs.raw == "Open", extra
        assert obs.status not in IS.RESULT_STATUSES


# --- MN-D2 ----------------------------------------------------------------

def _gone(raw, **kw) -> dict:
    return {"id": "g", "state": "MN", "county": "Wright", "case_no": "SYN-1", "source": "auction",
            "source_id": "mn_wright_tax_forfeit", "status": "closed", "inventory_status_raw": raw,
            "otc_provenance": {"adapter": "arcgis"}, **kw}


def test_wright_row_that_leaves_the_open_list_reads_closed_never_sold():
    obs = IS.adapter_record_status(_gone("Open"), today=TODAY)
    assert (obs.status, obs.basis) == ("closed", "LIST_PRESENCE")
    assert obs.status not in IS.RESULT_STATUSES


def test_writer_records_a_removal_not_a_sale_for_wright():
    row = _gone("Open", inventory_status="active", last_seen_at=NOW.isoformat())
    changes, _ = W.plan([row], today=TODAY, now=NOW)
    assert [(c["status"], c["transition"]) for c in changes] == [("closed", "removed")]


def test_a_sold_flag_wording_still_reads_sold():
    for raw in ("Sold: Yes", "Sold: Y", "SOLD"):
        obs = IS.adapter_record_status(_gone(raw), today=TODAY)
        assert (obs.status, obs.basis, obs.raw) == ("sold", "SOURCE_STATUS", raw)


def test_eaton_style_sold_flag_round_trips_through_the_adapter():
    # arcgis._sold builds the wording the status rule recognises.
    fm = A.ArcGisFieldMap(case_no="PID", sold_flag="Sold")
    built = A._sold({"Sold": "Yes"}, fm)["source_status_text"]
    assert IS.is_published_sold_flag(built)
    assert not A._sold({"Sold": "No"}, fm)


def test_other_status_words_are_not_sold_flags():
    for raw in ("Open", "Closed", "Available", "OTC", "Sold: No", ": Yes", "Status: Open", ""):
        assert not IS.is_published_sold_flag(raw), raw


def test_sold_flag_values_match_the_arcgis_adapter():
    assert IS.SOLD_FLAG_VALUES == frozenset(A.SOLD_YES)


# --- MN-D3 ----------------------------------------------------------------

def test_state_ledger_copy_no_longer_calls_approved_sources_awaiting_review():
    with open(ROOT / "data" / "state_ledgers.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    mn = next(r for r in rows if r["state"] == "MN" and r["ledger"] == "AVAILABLE")
    assert "approved for customer publication 2026-10-26; legal review pending" in mn["note"]
    for r in rows:
        assert "awaiting review" not in (r["note"] + r["eligibility_basis"]), (r["state"], r["ledger"])
    assert "awaiting review" not in (ROOT / "public" / "state-rules.json").read_text(encoding="utf-8")


# --- MN-D4 ----------------------------------------------------------------

def test_unit_freshness_prunes_units_no_registry_row_names():
    import unit_freshness as UF
    entries = [UF.normalize_entry({"county": "Ramsey", "status": "COMPLETE", "source_id": "mn_ramsey_tax_forfeit",
                                   "row_count": 2}, default_state="MN", default_source=None)]
    stale_key = UF.unit_key("MN", "mn_old_bare_source", "Ramsey")
    previous = {stale_key: {"state": "MN", "source_id": "mn_old_bare_source", "county": "Ramsey"}}
    record, _ = UF.merge(previous, entries, at=NOW.isoformat())
    registry = UF.registry_units()
    assert UF.unit_key("MN", "mn_ramsey_tax_forfeit", "Ramsey") in registry
    kept, dropped = UF.prune(record, entries, registry)
    assert dropped == [stale_key] and set(kept) == {UF.unit_key("MN", "mn_ramsey_tax_forfeit", "Ramsey")}


def test_unit_freshness_keeps_units_emitted_this_run_and_prunes_nothing_without_a_registry():
    import unit_freshness as UF
    entries = [UF.normalize_entry({"county": "Nowhere", "status": "FAILED", "source_id": "not_in_registry"},
                                  default_state="MN", default_source=None)]
    record, _ = UF.merge({}, entries, at=NOW.isoformat())
    kept, dropped = UF.prune(record, entries, UF.registry_units())
    assert dropped == [] and len(kept) == 1
    kept, dropped = UF.prune({"MN|x|Y": {}}, [], {})
    assert dropped == [] and kept == {"MN|x|Y": {}}
