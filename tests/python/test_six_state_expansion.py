"""Six-state expansion (2026-09-30): MI, WY, SC, CO, WI activated on live-read
evidence and the owner's publication decision; WV and UT registered, gated.

Every fixture under tests/python/fixtures/expansion/ is SYNTHETIC: the live
column names and identifier shapes (read value-free by the evidence job),
never a live value.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "scripts"))

from harvesters.governance import states  # noqa: E402
from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import publication as pub  # noqa: E402
from harvesters.ledgers import ledgers_for_source_id  # noqa: E402
from harvesters.otc.adapters import arcgis as AG, expansion as EX  # noqa: E402
from harvesters.otc.adapters.tabular import TabularListAdapter  # noqa: E402
import harvest_expansion as HX  # noqa: E402
import sync_state_inventory as SY  # noqa: E402

FIX = REPO / "tests/python/fixtures/expansion"
T = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
NEW = {"MI", "WY", "SC", "CO", "WI"}
FIXTURES = {
    "MI": {"mi_eaton_treasurer_sale": "mi_eaton_page.json", "mi_lenawee_tax_sale": "mi_lenawee_page.json"},
    "WY": {"wy_albany_tax_sale": "wy_albany_page.json"},
    "SC": {"sc_york_tax_sale": "sc_york_page.json"},
    "CO": {"co_morgan_county_held_certificates": "co_morgan.html"},
    "WI": {"wi_green_tax_deed_sales": "wi_green.html"},
}
HOSTS = {
    "mi_eaton_treasurer_sale": "https://services2.arcgis.com/c9l1e4fKpsCnqD7H/",
    "mi_lenawee_tax_sale": "https://services6.arcgis.com/mjEvhc9AE3ceAXtG/",
    "wy_albany_tax_sale": "https://services1.arcgis.com/EmwrhKkmuQhTATzU/",
    "sc_york_tax_sale": "https://services1.arcgis.com/2AGLxyiJoNiVHKwq/",
    "co_morgan_county_held_certificates": "https://morgancounty.colorado.gov/",
    "wi_green_tax_deed_sales": "https://www.greencountywi.org/",
}


def run(state: str, tmp_path: Path) -> dict:
    args = ["--state", state, "--out-dir", str(tmp_path)]
    for sid, name in FIXTURES[state].items():
        args += ["--fixture", f"{sid}={FIX / name}"]
    assert HX.main(args) == 0
    st = state.lower()
    return {
        "rows": json.loads((tmp_path / f"{st}_properties_rows.json").read_text()),
        "status": json.loads((tmp_path / f"harvest_{st}_status.json").read_text()),
    }


def units(status) -> dict:
    entries = status.get("counties") if isinstance(status, dict) else status
    if isinstance(entries, dict):
        return {k: v["status"] for k, v in entries.items()}
    return {e["county"]: e["status"] for e in entries}


# ==================== 1. states ====================

def test_s01_five_states_are_production_and_activated_two_stay_gated():
    assert NEW <= states.PRODUCTION_STATES
    for code in NEW:
        cfg = states.get_state(code)
        assert cfg.production and states.is_activated(code) and states.activation_blockers(code) == [], code
    # WV: the Auditor's statewide list needs a client-script flow no parser reads, and its
    # terms grant no reuse right. UT: no current inventory until the May 2027 sale.
    for code in ("WV", "UT"):
        assert code in states.supported_states() and not states.is_activated(code)
        assert code not in states.PRODUCTION_STATES and states.activation_blockers(code), code
    # The earlier gated states are untouched.
    for code in ("AL", "AR", "AZ"):
        assert not states.is_activated(code)


# ==================== 2. registry / governance ====================

def test_r01_one_production_row_per_source_with_the_owner_decision():
    rows = [r for r in csr.load_registry() if r.state in NEW]
    assert sorted(r.source_id for r in rows) == sorted(HOSTS)
    for r in rows:
        assert r.is_production and r.runnable and r.governance_status == "APPROVED", r.source_id
        assert pub.effective_publication(r) == "APPROVED" and pub.publication_problems(r) == []
        assert "No explicit reuse licence" in r.restrictions and "owner on 2026-09-30" in r.restrictions
        assert r.publishing_unit == "COUNTY" and r.source_authority == "GOVERNMENT_DIRECT"
        assert r.ledger_set == {l.value for l in ledgers_for_source_id(r.source_id)}
        assert (r.document_url or r.canonical_url).startswith(HOSTS[r.source_id]) or r.canonical_url.startswith("https://www.arcgis.com/home/item.html?id=")
    assert csr.validate_registry(csr.load_registry()) == []


def test_r02_every_config_is_column_verified_and_pinned_to_its_host():
    for st, srcs in EX.SOURCES.items():
        assert st in NEW
        for src in srcs:
            cfg = src.config
            assert cfg.columns_verified and cfg.state == st
            url = getattr(cfg, "layer_url", None) or src.url
            assert url.startswith(HOSTS[cfg.source_id]), (cfg.source_id, url)
    # Certificates only where the county itself publishes certificates.
    kinds = {src.config.source_id: src.config.record_source for srcs in EX.SOURCES.values() for src in srcs}
    assert kinds["co_morgan_county_held_certificates"] == "certificate"
    assert {v for k, v in kinds.items() if k != "co_morgan_county_held_certificates"} == {"auction"}


# ==================== 3. adapters through the runner ====================

def test_a01_michigan_layers_parse_and_eaton_sold_flag_closes_only_that_row(tmp_path):
    out = run("MI", tmp_path)
    assert units(out["status"]) == {"Eaton": "COMPLETE", "Lenawee": "COMPLETE"}
    rows = {r["case_no"]: r for r in out["rows"]}
    assert len(rows) == 4 and all(r["source"] == "auction" and r["ledger_type"] == "auctions" for r in rows.values())
    sold = [r for r in rows.values() if r.get("inventory_status_raw") == "Sold: Yes"]
    assert len(sold) == 1 and sold[0]["status"] == "closed"
    # The flag closes the listing; it is not a published price or buyer.
    assert sold[0].get("result_amount") is None and "result_party" not in sold[0]
    for r in rows.values():
        assert r["min_bid"] == r["bid"] and r["url_auction_kind"] == "county"
        assert r["parcel"] == r["case_no"]                     # the published identifier, verbatim


def test_a02_wyoming_and_south_carolina_carry_only_published_fields(tmp_path):
    wy = run("WY", tmp_path / "wy")["rows"]
    assert len(wy) == 1 and wy[0]["case_no"] == "R0001234" and wy[0]["parcel"] == "12345678900000"
    assert wy[0]["market"] == 188000.0 and wy[0]["owner_name"] and wy[0]["tax_year"] == "2025"
    sc = run("SC", tmp_path / "sc")["rows"]
    assert len(sc) == 2
    geo = [r for r in sc if r.get("latitude") is not None]
    assert len(geo) == 1 and (geo[0]["latitude"], geo[0]["longitude"]) == (34.99, -81.24)
    # York publishes no amount: nothing is invented.
    assert all(not r.get("min_bid") and r.get("purchase_amount") is None for r in sc)


def test_a03_colorado_certificates_keep_the_published_purchase_amount_and_as_of_date(tmp_path):
    rows = run("CO", tmp_path)["rows"]
    assert len(rows) == 2
    for r in rows:
        assert r["source"] == "certificate" and r["certificate_no"] == r["case_no"]
        assert r["purchase_amount_kind"] == "FIXED_PURCHASE_PRICE" and r["purchase_amount"] > 0
        assert r["list_as_of"] == "2026-10-31" and r["parcel"].startswith("R")


def test_a04_wisconsin_current_empty_statement_and_previous_published_sales(tmp_path):
    out = run("WI", tmp_path)
    assert units(out["status"]) == {"Green": "COMPLETE"}
    rows = out["rows"]
    assert len(rows) == 2 and all(r["status"] == "closed" for r in rows)
    assert all(r["result_amount"] and r["result_date"] == r["sale_date"] for r in rows)
    assert all(r["address"] != "N/A" for r in rows)                 # a "N/A" cell is no value
    # The current table alone: the county's own "no current sales" statement -> EMPTY.
    html = (FIX / "wi_green.html").read_text()
    a = TabularListAdapter(EX.WI_GREEN_CURRENT)
    assert a.parse_html_table(html, retrieved_at=T) == [] and a.empty_statement


# ==================== 4. failures ====================

def test_f01_error_payload_transport_failure_and_missing_table_are_failed_never_empty():
    arc = next(s for s in EX.SOURCES["WY"])
    status, recs, cat, _, _ = HX.run_source(arc, lambda url: {"error": {"code": 500, "message": "x"}}, None, retrieved_at=T)
    assert status == "FAILED" and recs == []

    def boom(url):
        raise OSError("reset")
    status, _, cat, _, _ = HX.run_source(arc, boom, None, retrieved_at=T)
    assert status == "FAILED" and cat == "TRANSPORT_CONNECTION"
    tab = next(s for s in EX.SOURCES["CO"])
    status, _, cat, _, _ = HX.run_source(tab, None, lambda url: "<html><p>moved</p></html>", retrieved_at=T)
    assert (status, cat) == ("FAILED", "PARSE_NO_TABLE")
    status, _, cat, _, _ = HX.run_source(tab, None, boom, retrieved_at=T)
    assert (status, cat) == ("FAILED", "TRANSPORT_CONNECTION")


def test_f02_duplicate_identifiers_keep_the_first_listing():
    tab = next(s for s in EX.SOURCES["CO"])
    _, recs, _, _, _ = HX.run_source(tab, None, None, retrieved_at=T, fixture=str(FIX / "co_morgan.html"))
    out, dropped = HX.dedupe(recs + recs[:1])
    assert dropped == 1 and [r.case_no for r in out] == [r.case_no for r in recs]
    # Across ArcGIS pages a repeated identifier means unstable paging: FAILED, not deduped.
    cfg = EX.WY_ALBANY
    page = json.loads((FIX / "wy_albany_page.json").read_text())
    pages = [dict(page, exceededTransferLimit=True), dict(page, exceededTransferLimit=False)]
    res = AG.fetch_all(cfg, lambda url: pages.pop(0), retrieved_at=T)
    assert res.outcome == "FAILED" and res.error_category == "PARSE_FORMAT_CHANGE"


# ==================== 5. gates ====================

def test_g01_a_gated_state_is_refused_before_any_request(capsys):
    assert HX.gate("WV") and HX.gate("UT")
    assert HX.main(["--state", "WV"]) == 2
    assert "0 requests made" in capsys.readouterr().out
    for st in NEW:
        assert HX.gate(st) == [], st


def test_g02_a_missing_or_demoted_registry_row_blocks_the_state(tmp_path):
    rows = csr.load_registry()
    reg = tmp_path / "reg.csv"
    import csv
    with open(csr.REGISTRY_PATH, newline="", encoding="utf-8") as fh:
        data = list(csv.DictReader(fh))
    for d in data:
        if d["source_id"] == "sc_york_tax_sale":
            d["verification_status"] = "SEARCH_EVIDENCE_ONLY"
    with open(reg, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=csr.EXTENDED_COLUMNS)
        w.writeheader()
        w.writerows(data)
    assert any("sc_york_tax_sale" in p for p in HX.gate("SC", reg))
    assert rows  # the committed registry is untouched


def test_g03_sync_plan_stamps_publication_and_ledger_and_skips_unread_units(tmp_path):
    out = run("MI", tmp_path)
    reg = SY.registry_rows("MI")
    sent, counts = SY.plan("MI", out["rows"], reg, {"Eaton": "COMPLETE", "Lenawee": "FAILED"})
    assert counts["upsert"] == 2 and counts["skipped_unit_not_read"] == 2
    assert all(r["publication_status"] == "APPROVED" and r["ledger_type"] == "auctions" for r in sent)
    assert {r["harvester_source"] for r in sent} == {"mi_eaton_treasurer_sale"}
    co = run("CO", tmp_path / "co")["rows"]
    sent, _ = SY.plan("CO", co, SY.registry_rows("CO"), {"Morgan": "COMPLETE"})
    assert {r["ledger_type"] for r in sent} == {"lien"}
    with pytest.raises(ValueError, match="not activated"):
        SY.plan("WV", [], {}, {})
    # A row claiming a source that is not its state's production row is refused outright.
    bad = [dict(out["rows"][0], source_id="tx_lgbs")]
    with pytest.raises(ValueError, match="not a production"):
        SY.plan("MI", bad, reg, {"Eaton": "COMPLETE"})


# ==================== 6. the frontend follows the backend ====================

def test_u01_each_new_state_has_a_page_basemap_and_state_tables():
    import re
    app = (REPO / "public/app.js").read_text(encoding="utf-8")
    meta = re.search(r"const STATE_META = \{(.*?)\n\};", app, re.S).group(1)
    for code in NEW:
        page = re.search(r'%s: \{ name: "[A-Za-z ]+", page: "([a-z]+\.html)"' % code, meta).group(1)
        assert (REPO / "public" / page).exists() and (REPO / page).exists(), page
        html = (REPO / "public" / page).read_text(encoding="utf-8")
        assert f'data-state="{code}"' in html
        svg = f"{code.lower()}-counties.svg"
        assert (REPO / "public" / svg).exists()
        for mod in ("public/explore.js", "public/satellite-map.js"):
            assert re.search(r"\b%s:\s*\{" % code, (REPO / mod).read_text(encoding="utf-8")), (mod, code)
        assert f'"{page}"' in (REPO / "public/sw.js").read_text(encoding="utf-8") or f"/{page}" in (REPO / "public/sw.js").read_text(encoding="utf-8")
    cents = json.loads((REPO / "public/county-centroids.json").read_text())
    for code, county in (("MI", "Eaton"), ("MI", "Lenawee"), ("WY", "Albany"), ("SC", "York"), ("CO", "Morgan"), ("WI", "Green")):
        assert county in cents[code], (code, county)
