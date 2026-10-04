"""AVAILABLE expansion (2026-10-04): St. Louis LRA (MO), Oklahoma County
county-owned list (OK), Fayette County repository (PA), Ramsey County
tax-forfeited land (MN).

Every source states availability itself and is collected UNREVIEWED (admins
see it labelled; customers do not until an admin review approves it). All
fixtures under tests/python/fixtures/available_five/ carry the LIVE column
names with SYNTHETIC values in the live shapes."""
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import harvest_expansion as HE  # noqa: E402
import source_publication as SP  # noqa: E402
import sync_state_inventory as SY  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.ledgers import SOURCE_LEDGERS, Ledger  # noqa: E402
from harvesters.otc.adapters import arcgis as AG, expansion as EX  # noqa: E402
from harvesters.otc.adapters.tabular import TabularListAdapter, pdf_table_rows  # noqa: E402
from harvesters.otc.model import AmountKind, InventoryType  # noqa: E402

AT = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
FX = ROOT / "tests/python/fixtures/available_five"
FIXTURE = {"MO": ("mo_stl_lra_inventory", "mo_stl_lra_inventory.csv"),
           "OK": ("ok_oklahoma_county_owned", "ok_oklahoma_county_owned.html"),
           "PA": ("pa_fayette_repository", "pa_fayette_repository.pdf"),
           "MN": ("mn_ramsey_tax_forfeit", "mn_ramsey_tax_forfeit.json")}
NEW = set(FIXTURE)


def _src(st):
    (src,) = EX.SOURCES[st]
    return src


def _reg(st):
    return SP.registry_with_reviews(st, reviews={})[0]


def _run(st, tmp_path, fixture=None):
    sid, name = FIXTURE[st]
    out = tmp_path / st
    rc = HE.main(["--state", st, "--fixture", f"{sid}={fixture or FX / name}", "--out-dir", str(out)])
    assert rc == 0
    rows = json.loads((out / f"{st.lower()}_properties_rows.json").read_text())
    units = SY.status_units(out / f"harvest_{st.lower()}_status.json")
    return rows, units


def _outcome(st, fixture=None, **kw):
    sid, name = FIXTURE[st]
    return HE.run_source(_src(st), None, None, retrieved_at=AT, fixture=str(fixture or FX / name), **kw)


# ==================== registration / governance ====================

def test_states_are_activated_county_level_available_states():
    for st in NEW:
        cfg = states.get_state(st)
        assert states.is_activated(st) and st in states.PRODUCTION_STATES
        assert cfg.production_inventory_types == frozenset({"", "POST_SALE"}) and cfg.lifecycle_inventory_type is None
        ev = states.EXPANSION_EVIDENCE[st]
        assert list(ev) == list(states.ACTIVATION_REQUIREMENTS)
        assert "UNREVIEWED" in ev["governance_approved"] and "never customer-published" in ev["governance_approved"]
    assert not states.is_supported("MS")          # evaluated and deferred: no deterministic public source


def test_every_source_is_available_ledger_unreviewed_and_collected_not_published():
    assert EX.AVAILABLE_FIVE_SOURCE_IDS == {sid for sid, _ in FIXTURE.values()}
    for st in NEW:
        cfg = _src(st).config
        assert cfg.record_source == "laft" and cfg.inventory_type is InventoryType.POST_SALE and cfg.columns_verified
        assert SOURCE_LEDGERS[cfg.source_id] == {Ledger.AVAILABLE}
        assert EX.PUBLICATION[cfg.source_id] == ("UNREVIEWED", EX.HELD_AVAILABLE)
        row = _reg(st)[cfg.source_id]
        assert row.is_production and row.publication_status == "UNREVIEWED" and row.ledgers == "AVAILABLE"
        assert SP.collectable(row, "laft") and not SP.publishable(row)        # admin collection, no customer release
        assert HE.gate(st, reg=_reg(st)) == []
        run, gated = HE.runnable_sources(st, _reg(st))
        assert [s.config.source_id for s in run] == [cfg.source_id] and gated == []


def test_a_blocked_review_makes_zero_requests():
    for st in NEW:
        sid = _src(st).config.source_id
        reg = dict(_reg(st))
        reg[sid] = dataclasses.replace(reg[sid], publication_status="BLOCKED")
        run, gated = HE.runnable_sources(st, reg)
        assert run == [] and gated == [(sid, "BLOCKED")]


def test_registry_rows_carry_the_source_urls_and_formats():
    reg = {st: _reg(st)[_src(st).config.source_id] for st in NEW}
    assert reg["MO"].machine_format == "CSV" and reg["MO"].document_url.endswith("LRA_INVENTORY.csv")
    assert reg["MO"].publishing_unit_name == "St. Louis City"
    assert reg["OK"].machine_format == "HTML_TABLE" and reg["OK"].purchase_url.endswith("BidForm.pdf")
    assert reg["OK"].purchase_url_kind == "bid_form"
    assert reg["PA"].machine_format == "PDF" and reg["PA"].access_method == "HTTP_GET_PDF"
    assert reg["MN"].machine_format == "JSON" and reg["MN"].purchase_url == ""
    for st in ("MO", "PA", "MN"):
        assert reg[st].purchase_url == ""          # none verified: never invented


# ==================== MO: St. Louis LRA ====================

def test_mo_reads_only_the_sources_own_available_status(tmp_path, capsys):
    rows, units = _run("MO", tmp_path)
    assert units == {"St. Louis City": "COMPLETE"}
    assert [r["case_no"] for r in rows] == ["10000100010", "10000100030"]          # Unavailable / blank / non-id dropped
    r = rows[0]
    assert r["parcel"] == r["case_no"] and r["state"] == "MO" and r["source"] == "laft"
    assert r["inventory_status_raw"] == "Available" and r["land_use"] == "Lot" and r["address"] == "100 TEST ST"
    assert r["purchase_amount"] is None and r["purchase_amount_kind"] == "NOT_PUBLISHED"
    assert r["purchase_url"] is None and r["purchase_path_type"] is None   # no path invented
    out = capsys.readouterr().out
    assert "1 non-identifier row(s), 2 row(s) whose own status is not an offer" in out
    assert "1 duplicate identifier(s) dropped" in out
    assert "10000100010" not in out and "TEST ST" not in out                 # shapes / counts only


def test_mo_all_unavailable_is_the_sources_own_empty(tmp_path):
    f = tmp_path / "all_unavailable.csv"
    f.write_text("ParcelId,Parcel_Status,Address,LegalDescription,PropertyType\n"
                 "10000100020,Unavailable,102 TEST ST,C.B. 1,Lot\n")
    status, recs, cat, _, empty = _outcome("MO", f)
    assert (status, recs, cat, empty) == ("EMPTY", [], None, "no_offered_status")


def test_mo_missing_status_column_is_a_format_change_never_empty(tmp_path):
    f = tmp_path / "no_status.csv"
    f.write_text("ParcelId,Address\n10000100010,100 TEST ST\n")
    status, recs, cat, _, _ = _outcome("MO", f)
    assert status == "FAILED" and recs == [] and cat == "PARSE_NO_TABLE"


# ==================== OK: Oklahoma County ====================

def test_ok_reads_the_county_owned_table_with_suggested_bid_as_unspecified(tmp_path):
    rows, units = _run("OK", tmp_path)
    assert units == {"Oklahoma": "COMPLETE"}
    by = {r["case_no"]: r for r in rows}
    assert set(by) == {"1234-56-789-0001", "1234-56-789-0002"}                    # 'Total' row and the other table ignored
    r = by["1234-56-789-0001"]
    assert r["purchase_amount"] == 1500.0 and r["purchase_amount_kind"] == "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"
    assert r.get("min_bid") is None                                                    # a suggestion is never a minimum
    assert by["1234-56-789-0002"]["purchase_amount"] is None                       # 'N/A' is no value
    assert by["1234-56-789-0002"]["purchase_amount_kind"] == "NOT_PUBLISHED"
    # The combined address / legal column is kept as the legal description, never as a street address.
    assert r["legal_desc"].startswith("100 SYNTHETIC ST") and not (r["address"] or "").startswith("100 SYNTHETIC")
    # The bid form is an offline document: county-wide, never "online", never a property link.
    assert r["purchase_url_kind"] == "bid_form" and r["purchase_path_type"] == "application_download"
    assert r["purchase_path_scope"] == "source" and r["otc_provenance"]["acquisition"]["mode"] == "bid"


def test_ok_page_without_the_table_fails(tmp_path):
    p = tmp_path / "missing.html"
    p.write_text("<html><p>Maintenance</p></html>")
    status, recs, cat, _, _ = _outcome("OK", p)
    assert status == "FAILED" and recs == [] and cat == "PARSE_NO_TABLE"


# ==================== PA: Fayette repository PDF ====================

def test_pa_pdf_rows_are_read_and_owner_is_never(tmp_path, capsys):
    raw = pdf_table_rows((FX / "pa_fayette_repository.pdf").read_bytes())
    assert raw[0][2] == "OWNER" and any("SYNTHETIC OWNER" in c for r in raw for c in r)   # the fixture does carry owners
    rows, units = _run("PA", tmp_path)
    assert units == {"Fayette": "COMPLETE"}
    assert [r["case_no"] for r in rows] == ["01-02-0003", "11-22-3333", "22-33-4444-002"]   # 'Bid Received' + repeated header out
    blob = json.dumps(rows)
    assert "SYNTHETIC OWNER" not in blob and all(r.get("owner_name") is None for r in rows)
    r = rows[0]
    assert r["purchase_amount"] == 1250.0 and r["purchase_amount_kind"] == "OPENING_BID"
    assert r["list_as_of"] == "2025-10-07"                                          # the document's own date, never today
    assert r["legal_desc"] == "LOT 1 TEST PLAN" and r["purchase_url"] is None
    out = capsys.readouterr().out
    assert "SYNTHETIC" not in out and "01-02-0003" not in out


def test_pa_bid_received_rows_are_pending_not_available():
    adapter = TabularListAdapter(EX.PA_FAYETTE_REPOSITORY)
    recs = adapter.parse_rows(pdf_table_rows((FX / "pa_fayette_repository.pdf").read_bytes()), retrieved_at=AT,
                              document_name="Repository-Update-10-7-2025")
    assert "01-02-0004-01" not in {r.case_no for r in recs} and adapter.excluded_status == 1
    assert adapter.rejected_ids == 0                     # a repeated page header is skipped, not counted as a bad id


def test_pa_non_pdf_is_a_format_change(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"<html>moved</html>")
    status, recs, cat, _, _ = _outcome("PA", f)
    assert status == "FAILED" and recs == [] and cat == "PARSE_FORMAT_CHANGE"


def test_pa_transport_failure_is_failed_never_zero():
    def boom(url):
        raise ConnectionError("synthetic")
    status, recs, cat, _, _ = HE.run_source(_src("PA"), None, None, retrieved_at=AT, fetch_bytes=boom)
    assert status == "FAILED" and recs == [] and cat == "TRANSPORT_CONNECTION"


# ==================== MN: Ramsey County layer ====================

def test_mn_queries_only_available_for_purchase_with_point_coordinates(tmp_path):
    params = AG.query_params(EX.MN_RAMSEY_TAX_FORFEIT)
    assert params["where"] == "Status = 'Available for purchase'" and params["outSR"] == "4326"
    rows, units = _run("MN", tmp_path)
    assert units == {"Ramsey": "COMPLETE"}
    r = rows[0]
    assert r["case_no"] == r["parcel"] == "012345678901" and r["inventory_status_raw"] == "Available for purchase"
    assert (r["latitude"], r["longitude"]) == (44.95, -93.10)
    assert r["purchase_amount"] == 12500.0 and r["purchase_amount_kind"] == "OPENING_BID" and r["purchase_url"] is None


def test_mn_a_feature_outside_the_filter_fails_the_read(tmp_path):
    payload = json.loads((FX / "mn_ramsey_tax_forfeit.json").read_text())
    payload["features"][1]["attributes"]["Status"] = "Sold at auction"         # the server ignored the where
    f = tmp_path / "leak.json"
    f.write_text(json.dumps(payload))
    status, recs, _, _, _ = _outcome("MN", f)
    assert status == "FAILED" and recs == []


def test_mn_empty_layer_is_the_sources_own_empty(tmp_path):
    f = tmp_path / "empty.json"
    f.write_text(json.dumps({"objectIdFieldName": "OBJECTID", "features": []}))
    status, recs, _, _, empty = _outcome("MN", f)
    assert (status, recs, empty) == ("EMPTY", [], "empty_layer")


# ==================== shared: lifecycle, sync, isolation ====================

@pytest.mark.parametrize("st", sorted(NEW))
def test_rows_sync_labelled_unreviewed_and_close_only_after_a_trusted_read(st, tmp_path):
    rows, units = _run(st, tmp_path)
    sent, counts = SY.plan(st, rows, _reg(st), units)
    assert counts["upsert"] == len(rows) and counts["written_review_pending"] == len(rows)
    assert {r["publication_status"] for r in sent} == {"UNREVIEWED"} and {r["ledger_type"] for r in sent} == {"buy"}
    assert all(r.get("owner_name") is None for r in sent)
    county = next(iter(units))
    sid = FIXTURE[st][0]
    gone = {"id": "x", "state": st, "status": "active", "harvester_source": sid, "source": "laft", "county": county,
            "case_no": "NO-LONGER-LISTED"}
    assert [c["status"] for c in SY.plan_close(st, rows, [gone], {county: "COMPLETE"}, {sid})] == ["closed"]
    assert SY.plan_close(st, rows, [gone], {county: "FAILED"}, {sid}) == []      # a failed read never closes a row
    still = dict(gone, case_no=rows[0]["case_no"])
    assert SY.plan_close(st, rows, [still], {county: "COMPLETE"}, {sid}) == []   # still listed: kept


def test_dedupe_identity_is_county_source_case_no(tmp_path):
    rows, _ = _run("MO", tmp_path)
    assert len({(r["county"], r["source"], r["case_no"]) for r in rows}) == len(rows)


def test_one_failing_source_does_not_stop_another_state(tmp_path, monkeypatch):
    real = HE.run_source

    def flaky(src, *a, **kw):
        if src.config.source_id == "ok_oklahoma_county_owned":
            raise RuntimeError("synthetic")
        return real(src, *a, **kw)

    monkeypatch.setattr(HE, "run_source", flaky)
    out = tmp_path / "ok"
    assert HE.main(["--state", "OK", "--fixture", f"ok_oklahoma_county_owned={FX / FIXTURE['OK'][1]}", "--out-dir", str(out)]) == 0
    assert SY.status_units(out / "harvest_ok_status.json") == {"Oklahoma": "FAILED"}
    rows, units = _run("MO", tmp_path)
    assert units == {"St. Louis City": "COMPLETE"} and rows


def test_existing_states_sources_are_unchanged():
    assert [s.config.source_id for s in EX.SOURCES["MI"]] == [
        "mi_eaton_treasurer_sale", "mi_lenawee_tax_sale", "mi_detroit_landbank_lots", "mi_detroit_landbank_programs",
        "mi_oceana_landbank"]                                                     # no Michigan inventory added
    assert EX.AVAILABLE_FIVE_SOURCE_IDS.isdisjoint(EX.AVAILABLE_SPRINT_SOURCE_IDS | EX.SIX_STATE_SOURCE_IDS)


def test_status_filters_are_generic_tabular_options():
    assert EX.MO_STL_LRA.status_include == ("Available",)
    assert EX.PA_FAYETTE_REPOSITORY.status_exclude == ("Bid Received",)
    for cfg in (EX.MO_STL_LRA, EX.OK_OKLAHOMA_COUNTY_OWNED, EX.PA_FAYETTE_REPOSITORY):
        assert not cfg.columns.owner_name                                       # never mapped
    assert EX.MN_RAMSEY_TAX_FORFEIT.fields.owner_name is None
    assert EX.OK_OKLAHOMA_COUNTY_OWNED.amount_kind is AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED
