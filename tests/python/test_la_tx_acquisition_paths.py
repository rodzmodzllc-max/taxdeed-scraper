"""Louisiana's newer adjudicated list (production since the owner's 2026-10-26
switch; the older list kept disabled), the dated list's
staleness count, the Texas 2026-10-25 outcome reads and the LGBS refresh's
NOT_READ outcome. Synthetic fixtures only."""
from __future__ import annotations

import csv
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "harvesters"))

from harvesters.otc.adapters import louisiana as LA  # noqa: E402
from harvesters.otc.model import AmountKind  # noqa: E402
from harvesters.sources import acquisition_evidence_status as AES  # noqa: E402

FIX = REPO / "tests/python/fixtures/louisiana"
T = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
PARCEL_CSV = (FIX / "ebr_adjudicated_parcel_LIVE_SHAPE.csv").read_text(encoding="utf-8")
PARCEL_META = (FIX / "ebr_parcel_metadata_LIVE_SHAPE.json").read_text(encoding="utf-8")
OLD_CSV = (FIX / "ebr_adjudicated_LIVE_SHAPE.csv").read_text(encoding="utf-8")


def test_newer_list_is_the_production_source_and_the_older_list_is_disabled():
    # Owner decision 2026-10-26 ("Yes close 6,643"): production reads shrr-fsqq;
    # the a4h4-zi7e config is kept, disabled, and is never requested.
    cfg = LA.EBR_PARCEL_SOURCE
    assert LA.EBR_SOURCE is cfg
    legacy = LA.EBR_LEGACY_SOURCE
    assert cfg.source_id == legacy.source_id == "la_ebr_adjudicated" and cfg.county == legacy.county
    assert cfg.live_verified and cfg.identifier_format_established and cfg.parser_fixture_validated
    assert cfg.enabled and LA.can_run(cfg).allowed
    assert legacy.enabled is False and not LA.can_run(legacy).allowed
    assert legacy.document_url == LA.EBR_CSV_URL and legacy.metadata_url == LA.EBR_METADATA_URL
    assert cfg.document_url == LA.EBR_PARCEL_CSV_URL and cfg.metadata_url == LA.EBR_PARCEL_METADATA_URL
    assert all(u.startswith("https://data.brla.gov/") for u in (cfg.list_url, cfg.document_url, cfg.metadata_url))
    ev = {e.key: e for e in LA.EBR_PARCEL_EVIDENCE}
    assert {e.grade for e in ev.values()} == {"LIVE_READ"} and "2026-05-06" in ev["parcel_metadata"].statement
    assert "6,643" in ev["parcel_csv"].statement and "PUBLIC_DOMAIN" in ev["parcel_metadata"].statement


def test_newer_list_parses_only_adjudicated_rows_with_its_own_columns():
    recs, out = LA.parse_csv(LA.EBR_PARCEL_SOURCE, PARCEL_CSV, retrieved_at=T, list_as_of=date(2026, 5, 6))
    assert out["header_table_found"] and out["data_rows"] == 4 and out["unmapped_columns"] == []
    assert out["other_status_rows"] == 1 and out["rejected_identifier"] == 1      # the 'RD' row and the blank number
    assert sorted(r.case_no for r in recs) == ["012-3456-7", "098-7654-3"]
    r = {x.case_no: x for x in recs}["012-3456-7"]
    assert r.parcel == r.case_no and r.address == "10 FIXTURE AVE" and r.legal_desc.startswith("LOT 4")
    assert r.assessed == 2500 and r.market == 25000 and r.tax_year is None
    assert r.latitude is None and r.longitude is None                              # polygons are not points
    assert r.amount is None and r.amount_kind is AmountKind.NOT_PUBLISHED and r.purchase_url is None
    assert r.list_as_of == date(2026, 5, 6) and "AJ" in r.provenance["status"]
    assert LA.classify_outcome(LA.EBR_PARCEL_SOURCE, recs, out).status == "COMPLETE"


def test_newer_list_harvest_reads_metadata_date_and_a_disabled_copy_is_refused():
    with pytest.raises(RuntimeError):
        LA.harvest(replace(LA.EBR_PARCEL_SOURCE, enabled=False), lambda u: "", retrieved_at=T)
    with pytest.raises(RuntimeError):
        LA.harvest(LA.EBR_LEGACY_SOURCE, lambda u: "", retrieved_at=T)
    calls = []
    res = LA.harvest(LA.EBR_SOURCE, lambda u: (calls.append(u), PARCEL_META if u == LA.EBR_PARCEL_METADATA_URL else PARCEL_CSV)[1],
                     retrieved_at=T)
    assert calls == [LA.EBR_PARCEL_METADATA_URL, LA.EBR_PARCEL_CSV_URL]
    assert res.outcomes[0].status == "COMPLETE" and {r.list_as_of for r in res.records} == {date(2026, 5, 6)}


def test_old_list_header_fails_the_newer_config_and_vice_versa():
    _, out = LA.parse_csv(LA.EBR_PARCEL_SOURCE, OLD_CSV, retrieved_at=T)
    assert out["missing_columns"] and LA.classify_outcome(LA.EBR_PARCEL_SOURCE, [], out).category == "PARSE_FORMAT_CHANGE"
    _, out2 = LA.parse_csv(LA.EBR_LEGACY_SOURCE, PARCEL_CSV, retrieved_at=T)
    assert "PROPERTY NUMBER" in out2["missing_columns"]


def test_status_column_must_be_required_with_named_statuses():
    with pytest.raises(ValueError):
        replace(LA.EBR_PARCEL_SOURCE, status_include=())
    with pytest.raises(ValueError):
        replace(LA.EBR_PARCEL_SOURCE, required_columns=("ASSESSMENT NO.", "PHYSICAL ADDRESS"))


def test_dated_list_counts_numbers_not_on_its_latest_tax_year_without_dropping_them():
    head = OLD_CSV.splitlines()[0]
    body = "\n".join([head,
                      "2023,111-1111-1,SAMPLE,,,1 FIXTURE ST,,,,,LOT 1,1000,100,,,",
                      "2019,222-2222-2,SAMPLE,,,2 FIXTURE ST,,,,,LOT 2,1000,100,,,",
                      "2012,333-3333-3,SAMPLE,,,3 FIXTURE ST,,,,,LOT 3,1000,100,,,",
                      "2023,333-3333-3,SAMPLE,,,3 FIXTURE ST,,,,,LOT 3,1000,100,,,"])
    recs, out = LA.parse_csv(LA.EBR_LEGACY_SOURCE, body, retrieved_at=T)
    assert len(recs) == 3 and out["not_on_latest_tax_year"] == 1 and out["superseded_tax_year_rows"] == 1


def test_texas_outcomes_record_the_2026_10_25_reads_and_never_verify():
    rows = [r for r in csv.DictReader(open(REPO / "data/acquisition_evidence_outcomes.csv", encoding="utf-8"))
            if r["state"] == "TX" and r["source_id"] == "tx_lgbs"]
    counties = {r["county"] for r in rows}
    assert counties == {"Goliad", "Hardin", "Jim Wells", "Leon", "Liberty", "Maverick", "Van Zandt"}
    for r in rows:
        o = AES.Outcome(**{k: r[k] for k in ("state", "source_id", "county", "status", "basis", "reason", "attempted_on",
                                             "run_id", "document_url")})
        assert AES.outcome_problems(o) == [] and o.status == "NOT_FOUND" and o.basis == "document_read"
        assert o.attempted_on == "2026-10-25"
        assert o.document_url == ""     # a county page is not a policy document; the pages read are candidates
    # Galveston keeps its verified evidence row; no other TX county gained one.
    ev = [r for r in csv.DictReader(open(REPO / "data/purchase_path_evidence.csv", encoding="utf-8")) if r["state"] == "TX"]
    assert [r["county"] for r in ev] == ["Galveston"]


def test_lgbs_refresh_unseen_rows_in_a_truncated_walk_are_not_read():
    import lgbs_available_refresh as L
    idx = L.index_feed([])
    row = {"id": "x", "county": "Leon", "case_no": "12345", "field_provenance": None}
    assert L.plan_row(row, idx, now="2026-10-25T00:00:00Z", walk_complete=False) == ("NOT_READ", {})
    assert L.plan_row(row, idx, now="2026-10-25T00:00:00Z", walk_complete=True) == ("NOT_IN_FEED", {})


def test_switch_keeps_identity_so_only_numbers_absent_from_the_newer_list_close(tmp_path):
    """The 2026-10-26 switch (owner: "Yes close 6,643"). The old list's PROPERTY
    NUMBER and the new list's ASSESSMENT NO. land in the SAME column (case_no,
    and parcel) in the SAME published format, so a number on both lists keeps
    its stored row (same upsert key (state, source, county, case_no)) and only
    a number absent from a COMPLETE read of the newer list is closed - never
    every row closed and re-inserted."""
    import json as _json
    import harvest_state_inventory as HSI
    import laft_lifecycle as LL
    import sync_state_inventory as SY
    old, _ = LA.parse_csv(LA.EBR_LEGACY_SOURCE, OLD_CSV, retrieved_at=T)
    out = tmp_path / "la"
    assert HSI.main(["--state", "LA", "--fixture", f"meta={FIX / 'ebr_parcel_metadata_LIVE_SHAPE.json'}",
                     "--fixture", str(FIX / "ebr_adjudicated_parcel_LIVE_SHAPE.csv"),
                     "--out", str(out / "harvest_louisiana.json"), "--status", str(out / "status.json"),
                     "--report", str(out / "report.json"), "--properties-out", str(out / "props.json")]) == 0
    harvested = _json.loads((out / "harvest_louisiana.json").read_text())
    props = _json.loads((out / "props.json").read_text())
    # Same column, same format: the overlap is exact string equality on case_no (and parcel).
    old_keys = {(r.county, r.case_no) for r in old}
    new_keys = {(r["county"], r["case_no"]) for r in harvested}
    assert {k[1] for k in old_keys & new_keys} == {"012-3456-7", "098-7654-3"}
    assert all(r["parcel"] == r["case_no"] for r in harvested) and all(r.parcel == r.case_no for r in old)
    assert {r["source_id"] for r in harvested} == {r.source_id for r in old} == {"la_ebr_adjudicated"}
    assert {r["list_as_of"] for r in props} == {"2026-05-06"}
    # The laft lifecycle (the LA close-out step) on the real status file this run wrote.
    entries = LL.load_status(out / "status.json")
    assert [e["status"] for e in entries] == ["COMPLETE"]
    gates = LL.county_gates(entries, [("la_ebr_adjudicated", "East Baton Rouge")], state="LA",
                            now=datetime.now(timezone.utc).timestamp())
    for with_source in (True, False):
        db_rows = [{"id": i, "county": r.county, "case_no": r.case_no, "status": "active",
                    **({"source_id": r.source_id} if with_source else {})} for i, r in enumerate(old)]
        plan = LL.plan_lifecycle(gates, LL.observed_by_county(harvested), db_rows)
        assert [c["case_no"] for c in plan.close] == ["123-45678-9"]            # only the number not on the newer list
        assert sorted(k[1] for k in plan.observe) == ["012-3456-7", "098-7654-3"] and plan.reactivate == []
    # The sync's own close planner agrees (same identity, same COMPLETE gate).
    stored = [{"id": i, "state": "LA", "source": "laft", "county": r.county, "case_no": r.case_no, "status": "active",
               "harvester_source": "la_ebr_adjudicated"} for i, r in enumerate(old)]
    closes = SY.plan_close("LA", props, stored, SY.units_for(out / "status.json"), {"la_ebr_adjudicated"})
    assert [stored[c["id"]]["case_no"] for c in closes] == ["123-45678-9"]
    # A failed read closes nothing.
    failed = [{**entries[0], "status": "FAILED", "error_category": "TRANSPORT_CONNECTION"}]
    gates_f = LL.county_gates(failed, [("la_ebr_adjudicated", "East Baton Rouge")], state="LA",
                              now=datetime.now(timezone.utc).timestamp())
    assert LL.plan_lifecycle(gates_f, {}, db_rows).close == []
