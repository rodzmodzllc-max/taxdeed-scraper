"""Arkansas (COSL Post Auction Sales List) and Louisiana (East Baton Rouge
adjudicated property) adapters, 2026-09-30: registration without
activation, the evidence ledgers, the configurations, deterministic
parsing on SYNTHETIC fixtures, amount / purchase-path / provenance
semantics, outcome classification, the gated flows, the generic harvester
script, the registry rows and the lifecycle's refusal.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import inventory_status as IS  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.governance.states import STATEWIDE_UNIT, StateConfig  # noqa: E402
from harvesters.otc import AmountKind, InventoryType, PurchaseUrlKind  # noqa: E402
from harvesters.otc.adapters import arkansas as AR, common, louisiana as LA  # noqa: E402
from harvesters.otc.gate import evaluate_source  # noqa: E402
import laft_lifecycle as L  # noqa: E402

T = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
FIX_AR = REPO / "tests/python/fixtures/arkansas"
FIX_LA = REPO / "tests/python/fixtures/louisiana"
DALLAS = (FIX_AR / "cosl_post_auction_dallas_SYNTHETIC.html").read_bytes()
EMPTY = (FIX_AR / "cosl_post_auction_empty_SYNTHETIC.html").read_bytes()
EBR = (FIX_LA / "ebr_adjudicated_SYNTHETIC.csv").read_text(encoding="utf-8")
BAD = (FIX_LA / "ebr_adjudicated_badheader_SYNTHETIC.csv").read_text(encoding="utf-8")
SCRIPT = REPO / "scripts/harvest_state_inventory.py"
ROWS = csr.load_registry()


def _activated(code):
    return StateConfig(code=code, name=code, publishing_units=states.get_state(code).publishing_units,
                       production_inventory_types=states.get_state(code).production_inventory_types,
                       lifecycle_inventory_type=None, production=True, activation=states.ALL_REQUIREMENTS)


# ==================== 1. registration and evidence ====================


def test_r01_ar_is_registered_not_production_and_la_is_activated_on_live_evidence():
    # Arkansas: registered, not production, every requirement unmet.
    cfg = states.get_state("AR")
    assert cfg.production is False and not cfg.activated and set(cfg.publishing_units) == {"STATE", "COUNTY"}
    assert cfg.production_inventory_types == {"POST_SALE"} and cfg.lifecycle_inventory_type == "POST_SALE" and "search-index evidence" in cfg.lifecycle_inventory_basis
    assert states.activation_blockers("AR") == list(states.ACTIVATION_REQUIREMENTS)
    with pytest.raises(ValueError, match="not activated"):
        L.lifecycle_inventory("AR")
    # Louisiana: activated 2026-09-30 on the LIVE read + the owner's dated-publication decision.
    cfg = states.get_state("LA")
    assert cfg.production is True and cfg.activated and set(cfg.publishing_units) == {"PARISH", "MUNICIPALITY"}
    assert cfg.production_inventory_types == {"ADJUDICATED_PROPERTY"} and "read live 2026-09-30" in cfg.lifecycle_inventory_basis
    assert states.activation_blockers("LA") == []
    assert L.lifecycle_inventory("LA")[0] == "ADJUDICATED_PROPERTY"
    assert states.PRODUCTION_STATES == frozenset({"FL", "TX", "LA", "MI", "WY", "SC", "CO", "WI"})
    ev = AR.COSL_EVIDENCE
    assert {e.grade for e in ev} == {"SEARCH_INDEX", "AUDIT_NOTE"} and sum(e.grade == "AUDIT_NOTE" for e in ev) == 1
    assert all(e.url == "" or e.url.split("/")[2].endswith("cosl.org") for e in ev)
    notes = AR.requirement_evidence()
    assert list(notes) == list(states.ACTIVATION_REQUIREMENTS) and all("not" in n or "no " in n or "SYNTHETIC" in n for n in notes.values())
    ev = LA.EBR_EVIDENCE
    assert {e.grade for e in ev} == {"SEARCH_INDEX", "AUDIT_NOTE", "LIVE_READ"} and sum(e.grade == "LIVE_READ" for e in ev) == 2
    assert all(e.url == "" or e.url.split("/")[2].endswith("data.brla.gov") for e in ev)
    live = {e.key: e.statement for e in ev if e.grade == "LIVE_READ"}
    assert "PUBLIC_DOMAIN" in live["live_metadata"] and "2024-02-27" in live["live_metadata"] and "36752875012" in live["live_metadata"]
    notes = LA.requirement_evidence()
    assert list(notes) == list(states.ACTIVATION_REQUIREMENTS)
    assert "PUBLIC_DOMAIN" in notes["governance_approved"] and "2024-02-27" in notes["inventory_semantics_established"]
    # Neither module imports a transport; the only hosts named are the agencies'.
    for name, hosts in (("arkansas.py", {"cosl.org", "auction.cosl.org"}), ("louisiana.py", {"data.brla.gov", "gisdata.brla.gov"})):
        src = (REPO / "harvesters/otc/adapters" / name).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for n in [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else []):
                    assert n != "urllib" and not n.startswith(("requests", "urllib.request", "http", "playwright", "socket")), (name, n)
        assert set(re.findall(r"https://([^/\s\"']+)", src)) == hosts, name


def test_c01_ar_is_not_enabled_and_la_is_enabled_only_as_verified():
    from dataclasses import replace
    ar, la = AR.COSL_SOURCE, LA.EBR_SOURCE
    assert ar.tabular.inventory_type is InventoryType.POST_SALE and ar.tabular.amount_kind is AmountKind.OPENING_BID
    assert ar.list_url == AR.COSL_POST_AUCTION_URL and ar.application_url == AR.COSL_BUYERS_URL
    assert ar.application_url_kind is PurchaseUrlKind.PURCHASE_INSTRUCTIONS and ar.auction_platform_url == AR.COSL_AUCTION_URL
    assert ar.observed_county_values == ("DALLAS",) and not ar.tabular.columns_verified
    assert la.inventory_type is InventoryType.ADJUDICATED_PROPERTY and la.publishing_unit == "PARISH" and la.county == "East Baton Rouge"
    assert la.list_url == LA.EBR_DATASET_URL and la.document_url == LA.EBR_CSV_URL and "PROPERTY NUMBER" in la.required_columns
    assert not (ar.enabled or ar.live_verified or ar.identifier_format_established or ar.parser_fixture_validated)
    d = AR.can_run(ar)
    assert not d.allowed and "not activated" in d.reason
    assert la.enabled and la.live_verified and la.identifier_format_established and la.parser_fixture_validated
    assert la.metadata_url == LA.EBR_METADATA_URL and LA.APPROVED_LICENSE_ID == "PUBLIC_DOMAIN"
    assert LA.can_run(la).allowed
    # A disabled copy is still refused even in an activated state.
    assert not LA.can_run(replace(la, enabled=False)).allowed
    with pytest.raises(ValueError, match="cannot be enabled"):
        replace(ar, enabled=True)
    with pytest.raises(ValueError, match="cannot be enabled"):
        replace(la, live_verified=False)
    with pytest.raises(ValueError, match="never a property purchase kind"):
        replace(ar, application_url_kind=PurchaseUrlKind.ONLINE_PURCHASE)
    with pytest.raises(ValueError, match="PARISH or MUNICIPALITY"):
        replace(la, publishing_unit="COUNTY")
    with pytest.raises(ValueError, match="identity column"):
        replace(la, required_columns=("PHYSICAL ADDRESS",))
    assert len(AR.ARKANSAS_COUNTIES) == 75 and "Pulaski" in AR.ARKANSAS_COUNTIES


# ==================== 2. Arkansas ====================


def test_a01_county_url_uses_only_the_observed_shape_and_never_guesses_multi_word_counties():
    cfg = AR.COSL_SOURCE
    assert AR.county_url(cfg, "Dallas") == "https://cosl.org/Home/PostAuctionView?county=DALLAS"
    assert AR.county_url(cfg, "Pulaski") == "https://cosl.org/Home/PostAuctionView?county=PULASKI"
    for multi in ("Hot Spring", "Little River", "St. Francis", "Van Buren"):
        assert AR.county_url(cfg, multi) is None
    with pytest.raises(ValueError, match="75 Arkansas counties"):
        AR.county_url(cfg, "Orleans")


def test_a02_parse_list_html_rows_as_published_gate_amount_and_purchase_semantics():
    url = AR.county_url(AR.COSL_SOURCE, "Dallas")
    recs, out = AR.parse_list_html(AR.COSL_SOURCE, DALLAS, county="Dallas", retrieved_at=T, url=url)
    assert out == {"header_table_found": True, "data_rows": 4, "empty_marker": False, "rejected_identifier": 1}
    assert [r.case_no for r in recs] == ["001-00123-000", "001-00456-000", "001-00789-000"]
    a, b, c = recs
    assert all(r.state == "AR" and r.county == "Dallas" and r.parcel == r.case_no and r.list_url == url for r in recs)
    assert (a.amount, a.amount_kind) == (412.1, AmountKind.OPENING_BID) and (c.amount, c.amount_kind) == (None, AmountKind.NOT_PUBLISHED)
    assert a.legal_desc == "PT SE NW 12-9-15 2.50 AC" and c.source_status_text == "Redeemed"
    assert a.purchase_url == AR.COSL_BUYERS_URL and a.purchase_url_kind is PurchaseUrlKind.PURCHASE_INSTRUCTIONS
    assert a.provenance["auction_platform"] == AR.COSL_AUCTION_URL and a.provenance["amount"].endswith("(COSL: the tax due amount is the minimum bid)")
    assert a.provenance["identifier"].startswith("parcel number as published") and a.provenance["publishing_unit"] == "STATE"
    assert all(r.validate() == [] for r in recs)
    assert a.to_properties_row()["inventory_type"] == "POST_SALE"   # storable since migration 020 (AR itself stays gated)
    row = a.to_harvest_row()
    assert (row["state"], row["county"], row["bid"], row["bid_kind"], row["purchase_url_kind"]) == ("AR", "Dallas", 412.1, "OPENING_BID", "purchase_instructions")
    assert L.identity_key(row) == ("Dallas", "001-00123-000")
    # Outcomes: INCOMPLETE until validated; empty page -> UNCONFIRMED_EMPTY.
    assert AR.classify_outcome(AR.COSL_SOURCE, "Dallas", recs, out).category == "UNKNOWN"
    from dataclasses import replace
    validated = replace(AR.COSL_SOURCE, parser_fixture_validated=True)
    assert AR.classify_outcome(validated, "Dallas", recs, out).status == "COMPLETE"
    recs0, out0 = AR.parse_list_html(AR.COSL_SOURCE, EMPTY, county="Pulaski", retrieved_at=T)
    assert recs0 == [] and out0["empty_marker"] and not out0["header_table_found"]
    assert AR.classify_outcome(AR.COSL_SOURCE, "Pulaski", recs0, out0).category == "UNCONFIRMED_EMPTY"
    assert AR.classify_outcome(validated, "Pulaski", recs0, out0).empty_signal == "empty_marker"
    recs2, _ = AR.parse_list_html(AR.COSL_SOURCE, DALLAS, county="Dallas", retrieved_at=T, url=url)
    assert [r.as_dict() for r in recs2] == [r.as_dict() for r in recs]


def test_a03_harvest_refuses_before_the_first_request_and_runs_only_for_an_activated_fixture_state():
    calls = []

    def fetch(url):
        calls.append(url)
        if "PULASKI" in url:
            raise TimeoutError("must not leak")
        return DALLAS.decode() if "DALLAS" in url else EMPTY.decode()
    with pytest.raises(RuntimeError, match="not activated"):
        AR.harvest(AR.COSL_SOURCE, fetch, retrieved_at=T)
    from dataclasses import replace
    claims = replace(AR.COSL_SOURCE, live_verified=True, identifier_format_established=True, parser_fixture_validated=True, enabled=True)
    with pytest.raises(RuntimeError, match="not activated"):
        AR.harvest(claims, fetch, retrieved_at=T)
    assert calls == []
    with states.registered(_activated("AR")):
        assert not AR.can_run(AR.COSL_SOURCE).allowed          # activated state, disabled source: still refused
        res = AR.harvest(claims, fetch, retrieved_at=T, counties=["Dallas", "Pulaski", "Hot Spring", "Yell", "Nowhere"])
    assert not states.is_activated("AR")
    assert res.units_offered == 4 and res.unresolved_units == ["Hot Spring"] and res.requests == 2
    by = {o.county: o for o in res.outcomes}
    assert (by["Dallas"].status, by["Dallas"].row_count) == ("COMPLETE", 3)
    assert (by["Pulaski"].status, by["Pulaski"].category, by["Pulaski"].reason) == ("FAILED", "TRANSPORT_TIMEOUT", "TimeoutError")
    assert (by["Yell"].status, by["Yell"].empty_signal) == ("EMPTY", "empty_marker")
    assert "leak" not in json.dumps([vars(o) | {"report": None} for o in res.outcomes])


# ==================== 3. Louisiana ====================


def test_l01_parse_csv_reads_the_indexed_columns_and_never_invents_a_price_or_a_link():
    recs, out = LA.parse_csv(LA.EBR_SOURCE, EBR, retrieved_at=T)
    assert out["header_table_found"] and out["data_rows"] == 4 and out["rejected_identifier"] == 1 and out["missing_columns"] == []
    assert out["unmapped_columns"] == [] and out["geolocation_parsed"] == 2
    assert [r.case_no for r in recs] == ["01234567", "07654321", "00999999"]
    a, b, c = recs
    assert a.county == "East Baton Rouge" and a.parcel == "01234567" and a.owner_name == "DOE JOHN" and a.tax_year == "2023"
    assert (a.assessed, a.market, a.address, a.legal_desc) == (2500.0, 25000.0, "1500 NORTH ST", "LOT 4 SQ 12 FAIRFIELDS")
    assert (a.latitude, a.longitude) == (30.4515, -91.1871) and (b.latitude, b.longitude) == (30.521, -91.193)
    assert c.latitude is None and c.longitude is None and b.assessed is None and b.address is None
    for r in recs:
        assert r.amount is None and r.amount_kind is AmountKind.NOT_PUBLISHED and r.purchase_url is None
        assert r.inventory_type is InventoryType.ADJUDICATED_PROPERTY and r.list_url == LA.EBR_DATASET_URL and r.document_url == LA.EBR_CSV_URL
        assert r.provenance["amount"].startswith("NOT_PUBLISHED") and r.provenance["owner_name"].startswith("TAXPAYER NAME")
        assert r.validate() == []
    assert a.provenance["coordinates"].startswith("GEOLOCATION column") and c.provenance["coordinates"].startswith("GEOLOCATION absent")
    stored = a.to_properties_row()     # storable since migration 020
    assert (stored["inventory_type"], stored["purchase_amount"], stored["purchase_amount_kind"], stored["bid"]) == ("ADJUDICATED_PROPERTY", None, "NOT_PUBLISHED", 0)
    assert stored["purchase_url"] is None and stored["list_as_of"] is None      # no metadata passed: no list date is invented
    row = a.to_harvest_row()
    assert (row["assessed"], row["market"], row["latitude"], row["tax_year"], row["bid"], row["bid_kind"]) == (2500.0, 25000.0, 30.4515, "2023", "", "NOT_PUBLISHED")
    assert "purchase_url" not in row
    # Geolocation shapes: WKT (lon lat), (lat, lon); anything else None; out of range None.
    assert LA.parse_geolocation("POINT (-91.1 30.4)") == (30.4, -91.1) and LA.parse_geolocation("(30.4, -91.1)") == (30.4, -91.1)
    assert LA.parse_geolocation("1500 NORTH ST") is None and LA.parse_geolocation("POINT (200 30)") is None and LA.parse_geolocation(None) is None
    # Header spelling is matched after normalization; missing required columns -> PARSE_FORMAT_CHANGE, nothing read.
    recs2, out2 = LA.parse_csv(LA.EBR_SOURCE, EBR.replace("PROPERTY NUMBER", "Property  Number").replace("PHYSICAL ADDRESS", "physical_address"), retrieved_at=T)
    assert [r.case_no for r in recs2] == [r.case_no for r in recs]
    recs3, out3 = LA.parse_csv(LA.EBR_SOURCE, BAD, retrieved_at=T)
    assert recs3 == [] and out3["missing_columns"] == ["PROPERTY NUMBER", "PHYSICAL ADDRESS", "LEGAL DESCRIPTION", "TAX YEAR"]
    oc = LA.classify_outcome(LA.EBR_SOURCE, recs3, out3)
    assert (oc.status, oc.category) == ("INCOMPLETE", "PARSE_FORMAT_CHANGE")
    from dataclasses import replace
    assert LA.classify_outcome(replace(LA.EBR_SOURCE, parser_fixture_validated=False, enabled=False), recs, out).category == "UNKNOWN"
    assert LA.classify_outcome(LA.EBR_SOURCE, recs, out).status == "COMPLETE"
    # Inventory status for a stored LA row: not mapped yet (no LA rule) -> nothing written.
    assert IS.status_for_row({"state": "LA", "source": "laft"}, today=T.date()) is None


def test_l02_harvest_reads_the_metadata_then_one_csv_and_refuses_a_changed_licence():
    meta = (FIX_LA / "ebr_metadata_LIVE_SHAPE.json").read_text(encoding="utf-8")
    live = (FIX_LA / "ebr_adjudicated_LIVE_SHAPE.csv").read_text(encoding="utf-8")
    calls = []

    def fetch(url):
        calls.append(url)
        return meta if url == LA.EBR_METADATA_URL else live
    res = LA.harvest(LA.EBR_SOURCE, fetch, retrieved_at=T)
    assert calls == [LA.EBR_METADATA_URL, LA.EBR_CSV_URL] and res.requests == 2 and res.outcomes[0].status == "COMPLETE"
    # One row per property number: the 2021 row of 012-3456-7 is superseded by 2023; the blank identifier is rejected.
    assert sorted(r.case_no for r in res.records) == ["012-3456-7", "098-7654-3", "123-45678-9"]
    assert {r.case_no: r.tax_year for r in res.records}["012-3456-7"] == "2023"
    assert res.outcomes[0].report["superseded_tax_year_rows"] == 1 and res.outcomes[0].report["rejected_identifier"] == 1
    # The list date is the dataset's own rows-updated date, never the retrieval date.
    for r in res.records:
        assert r.list_as_of == date(2024, 2, 27) and r.source_published_at.date() == date(2024, 2, 27) and r.list_as_of != T.date()
        assert "rowsUpdatedAt" in r.provenance["list_as_of"]
    # A different licence reads nothing and syncs nothing.
    changed = meta.replace("PUBLIC_DOMAIN", "CC_BY_NC")
    calls.clear()
    refused = LA.harvest(LA.EBR_SOURCE, lambda u: (calls.append(u), changed if u == LA.EBR_METADATA_URL else live)[1], retrieved_at=T)
    assert refused.records == [] and refused.outcomes[0].status == "FAILED" and "CC_BY_NC" in refused.outcomes[0].reason
    assert calls == [LA.EBR_METADATA_URL]
    # No rows-updated date: the list date cannot be stated -> nothing read.
    undated = LA.harvest(LA.EBR_SOURCE, lambda u: meta.replace('"rowsUpdatedAt": 1709060068,', "") if u == LA.EBR_METADATA_URL else live, retrieved_at=T)
    assert undated.records == [] and (undated.outcomes[0].status, undated.outcomes[0].category) == ("FAILED", "PARSE_FORMAT_CHANGE")
    failing = LA.harvest(LA.EBR_SOURCE, lambda u: (_ for _ in ()).throw(ConnectionError("x")), retrieved_at=T)
    assert (failing.outcomes[0].status, failing.outcomes[0].category) == ("FAILED", "TRANSPORT_CONNECTION") and failing.records == []
    # A disabled source is refused before any request.
    from dataclasses import replace
    calls.clear()
    with pytest.raises(RuntimeError, match="may not run"):
        LA.harvest(replace(LA.EBR_SOURCE, enabled=False), fetch, retrieved_at=T)
    assert calls == []


# ==================== 4. script, registry, gates ====================


def _run(args):
    env = {"PATH": "/usr/bin:/bin", "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO, env=env)


def test_s01_script_fixture_mode_for_both_states_and_live_refusal(tmp_path):
    out, status, report = tmp_path / "ar.json", tmp_path / "ars.json", tmp_path / "arr.json"
    r = _run(["--state", "AR", "--fixture", f"Dallas={FIX_AR / 'cosl_post_auction_dallas_SYNTHETIC.html'}",
              "--fixture", f"Pulaski={FIX_AR / 'cosl_post_auction_empty_SYNTHETIC.html'}", "--out", str(out), "--status", str(status), "--report", str(report)])
    assert r.returncode == 0, r.stdout + r.stderr
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert len(rows) == 3 and all(row["state"] == "AR" for row in rows)
    entries = json.loads(status.read_text(encoding="utf-8"))
    assert [(e["county"], e["state"], e["status"], e["error_category"], e["harvester"]) for e in entries] == [
        ("Dallas", "AR", "INCOMPLETE", "UNKNOWN", "ar_cosl_post_auction"), ("Pulaski", "AR", "INCOMPLETE", "UNCONFIRMED_EMPTY", "ar_cosl_post_auction")]
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["mode"] == "fixture" and rep["requests"] == 0 and rep["rows"] == 3 and rep["parser_fixture_validated"] is False
    for secret in ("001-00123-000", "PT SE NW"):
        assert secret not in r.stdout + report.read_text(encoding="utf-8")
    out2, status2, report2, props2 = tmp_path / "la.json", tmp_path / "las.json", tmp_path / "lar.json", tmp_path / "lap.json"
    r = _run(["--state", "LA", "--fixture", f"meta={FIX_LA / 'ebr_metadata_LIVE_SHAPE.json'}", "--fixture", str(FIX_LA / "ebr_adjudicated_LIVE_SHAPE.csv"),
              "--out", str(out2), "--status", str(status2), "--report", str(report2), "--properties-out", str(props2)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(json.loads(out2.read_text(encoding="utf-8"))) == 3
    entries = json.loads(status2.read_text(encoding="utf-8"))
    assert [(e["county"], e["state"], e["status"]) for e in entries] == [("East Baton Rouge", "LA", "COMPLETE")]
    props = json.loads(props2.read_text(encoding="utf-8"))
    assert len(props) == 3 and {p["list_as_of"] for p in props} == {"2024-02-27"} and {p["inventory_type"] for p in props} == {"ADJUDICATED_PROPERTY"}
    assert all(p["purchase_amount"] is None and p["purchase_amount_kind"] == "NOT_PUBLISHED" and p["purchase_url"] is None for p in props)
    assert "SAMPLE OWNER" not in r.stdout and "012-3456-7" not in r.stdout
    # Arkansas live mode still refuses before any request.
    r = _run(["--state", "AR", "--out", str(tmp_path / "x.json"), "--status", str(tmp_path / "s.json"), "--report", str(tmp_path / "r.json")])
    assert r.returncode == 2 and "not activated" in r.stdout and "0 requests made" in r.stdout
    assert not (tmp_path / "x.json").exists()
    bad = _run(["--state", "AR", "--fixture", f"Orleans={FIX_AR / 'cosl_post_auction_empty_SYNTHETIC.html'}", "--out", str(out), "--status", str(status), "--report", str(report)])
    assert bad.returncode != 0 and "75 Arkansas counties" in bad.stderr
    src = SCRIPT.read_text(encoding="utf-8")
    assert not any((getattr(n, "module", "") or "").startswith("requests") or any(a.name == "requests" for a in n.names)
                   for n in ast.parse(src).body if isinstance(n, (ast.Import, ast.ImportFrom)))
    # Only Louisiana is wired into a workflow (the laft job); AR / AZ never are.
    for wf in (REPO / ".github/workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        calls = re.findall(r"harvest_state_inventory\.py[^\n]*", text)
        assert all(c.strip() == "harvest_state_inventory.py --state LA" for c in calls), (wf.name, calls)


def test_g01_registry_rows_mirror_the_adapters_ar_refused_la_production():
    ar = csr.lookup(ROWS, "AR", STATEWIDE_UNIT)
    la = csr.lookup(ROWS, "LA", "East Baton Rouge")
    assert ar is not None and la is not None and csr.validate_registry(ROWS) == []
    assert ar.canonical_url == AR.COSL_POST_AUCTION_URL and ar.purchase_url == AR.COSL_BUYERS_URL and ar.purchase_url_kind == "purchase_instructions"
    assert ar.publishing_unit == "STATE" and ar.inventory_type == "POST_SALE" and ar.amount_kind == "OPENING_BID" and ar.machine_format == "UNKNOWN"
    assert la.canonical_url == LA.EBR_DATASET_URL and la.document_url == LA.EBR_CSV_URL and la.purchase_url == ""
    assert la.publishing_unit == "PARISH" and la.inventory_type == "ADJUDICATED_PROPERTY" and la.amount_kind == "NOT_PUBLISHED" and la.machine_format == "CSV"
    row = ar
    assert row.verification_status == "SEARCH_EVIDENCE_ONLY" and row.governance_status == "TERMS_NOT_VERIFIED" and row.harvester == ""
    assert not row.is_production and not row.runnable
    d = evaluate_source(row)
    assert not d.allowed and d.layer == "state_activation"
    assert "WEB SEARCH 2026-09-30" in row.evidence_ref and "not activated" in row.notes
    # Louisiana: PRODUCTION_VERIFIED on the live read, governance APPROVED, publication APPROVED with its dated restriction.
    assert la.verification_status == "PRODUCTION_VERIFIED" and la.governance_status == "APPROVED" and la.harvester == "harvest_state_inventory.py --state LA"
    assert la.is_production and la.runnable and evaluate_source(la).allowed
    assert "LIVE CAPTURE 2026-09-30" in la.evidence_ref and "PUBLIC_DOMAIN" in la.evidence_ref and "2024-02-27" in la.notes
    assert la.publication_status == "APPROVED" and "never as available now" in la.restrictions
    assert "CSV" in {m.value for m in csr.MachineFormat} and "'CSV'" in (REPO / "scripts/migrations/020_state_extensible_vocabulary.sql").read_text(encoding="utf-8")
    # 018's live shape still refuses them; the 020 shape carries them.
    with pytest.raises(ValueError, match="migration 018"):
        csr.to_db_rows([ar])
    with pytest.raises(ValueError, match="migration 018"):
        csr.to_db_rows([la])
    ext = csr.to_db_rows([ar, la], schema="020")
    assert [d["publishing_unit"] for d in ext] == ["STATE", "PARISH"]
    assert L.load_expected_units(csr.REGISTRY_PATH, "AR") == []
    assert L.load_expected_units(csr.REGISTRY_PATH, "LA") == [("la_ebr_adjudicated", "East Baton Rouge")]
    # The generator and the committed CSV agree.
    import importlib.util
    spec = importlib.util.spec_from_file_location("bcsr2", REPO / "scripts/build_county_source_registry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.render(mod.build_rows()) == csr.REGISTRY_PATH.read_text(encoding="utf-8")
    # FL / TX untouched.
    assert len(csr.expected_harvest_units(ROWS, "FL")) == 52 and len(csr.expected_harvest_units(ROWS, "TX")) == 8   # AVAILABLE ledger
    for code in ("FL", "TX"):
        assert states.is_activated(code)


def test_x01_common_gate_and_outcome_rules():
    with states.registered(_activated("AR")):
        assert common.can_run("AR", enabled=False, live_verified=True, identifier_format_established=True, parser_fixture_validated=True, list_url="https://x").reason == "source configuration is not enabled"
        assert common.can_run("AR", enabled=True, live_verified=True, identifier_format_established=True, parser_fixture_validated=True, list_url=None).reason == "no source-of-record URL configured"
        assert common.can_run("AR", enabled=True, live_verified=True, identifier_format_established=True, parser_fixture_validated=True, list_url="https://x").allowed
    assert not common.can_run("AR", enabled=True, live_verified=True, identifier_format_established=True, parser_fixture_validated=True, list_url="https://x").allowed
    k = dict(county="X", records=[], header_found=True, data_rows=2, empty_marker=False)
    assert common.classify(parser_fixture_validated=True, **k).category == "PARSE_FORMAT_CHANGE"
    assert common.classify(parser_fixture_validated=False, county="X", records=[], header_found=False, data_rows=0, empty_marker=False).category == "PARSE_NO_TABLE"
    assert common.error_category(TimeoutError()) == "TRANSPORT_TIMEOUT" and common.error_category(ValueError()) == "UNKNOWN"
