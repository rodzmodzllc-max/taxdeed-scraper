"""Per-operation, fail-closed source permission (harvesters/governance/permissions.py).

Three groups:
  1. the decision itself - missing, expired, future, wrong scope, conditions,
     conflicts, unknown source, invalid configuration, interim vs documented;
  2. hard blocks - GovEase and the other blocked vendors cannot be unblocked by
     a data edit, stale evidence, or a review;
  3. every wired entry point refuses BEFORE any request or write, and today's
     production practice is preserved exactly (parity).
"""
from __future__ import annotations

import csv
import importlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harvesters"))

from harvesters.governance import permissions as PERM  # noqa: E402
from harvesters.otc.adapters import expansion as EX  # noqa: E402
from harvesters.governance.county_source_registry import BLOCKED_SOURCE_IDS, load_registry  # noqa: E402
from harvesters.governance.publication import PUBLISHABLE_STATUSES, effective_publication  # noqa: E402
from permission_fixtures import install, permissions_with, record  # noqa: E402

DAY = date(2026, 10, 12)  # the day these records were verified
OWNER_DECISION_DAY = date(2026, 10, 26)  # new-sources sprint: owner-accepted interim records start here


def perms(*rows, base=False, **kw):
    return permissions_with(*rows, base=base, **kw)


def ok_row(**kw):
    return record(source_id="src_a", jurisdiction="FL", operation="fetch", **kw)


# --- 1. the decision ------------------------------------------------------------

def test_the_repository_file_is_valid_and_loads():
    records = PERM.load()
    assert len(records) > 100 and not PERM.validate(records)
    assert PERM.Permissions.from_file().error is None


def test_missing_permission_denies():
    p = perms(ok_row())
    d = p.authorize("src_a", "store", state="FL", today=DAY)
    assert not d.allowed and d.reason_code == "NO_RECORD" and d.basis == "DENIED"


def test_unknown_source_denies():
    d = perms(ok_row()).authorize("never_registered", "fetch", state="FL", today=DAY)
    assert not d.allowed and d.reason_code == "UNKNOWN_SOURCE"
    for bad in ("", None):
        assert perms(ok_row()).authorize(bad, "fetch", state="FL", today=DAY).reason_code == "NO_SOURCE"


def test_unknown_operation_and_missing_state_deny():
    p = perms(ok_row())
    assert p.authorize("src_a", "harvest_everything", state="FL", today=DAY).reason_code == "UNKNOWN_OPERATION"
    assert p.authorize("src_a", "fetch", state="", today=DAY).reason_code == "NO_JURISDICTION"


def test_expired_permission_denies_and_in_date_allows():
    p = perms(ok_row(evidence_date="2026-01-01", effective_on="2026-01-01", expires_on="2026-06-30"))
    assert p.authorize("src_a", "fetch", state="FL", today=date(2026, 6, 30)).allowed
    d = p.authorize("src_a", "fetch", state="FL", today=date(2026, 7, 1))
    assert not d.allowed and d.reason_code == "EXPIRED"


def test_future_effective_permission_denies_until_its_day():
    p = perms(ok_row(evidence_date="2026-01-01", effective_on="2026-11-01", expires_on="2027-04-12"))
    assert p.authorize("src_a", "fetch", state="FL", today=DAY).reason_code == "NOT_YET_EFFECTIVE"
    assert p.authorize("src_a", "fetch", state="FL", today=date(2026, 11, 1)).allowed


def test_wrong_jurisdiction_dataset_or_operation_denies():
    p = perms(ok_row(dataset="sale_calendar"), record(source_id="src_a", jurisdiction="FL:Orange", operation="fetch",
                                                        status="BLOCKED", evidence_type="PROHIBITION_FOUND", reviewer="",
                                                        effective_on="", expires_on=""))
    assert p.authorize("src_a", "fetch", state="FL", dataset="sale_calendar", today=DAY).allowed
    assert p.authorize("src_a", "fetch", state="TX", dataset="sale_calendar", today=DAY).reason_code == "NO_RECORD"
    assert p.authorize("src_a", "fetch", state="FL", dataset="closed_results", today=DAY).reason_code == "NO_RECORD"
    assert p.authorize("src_a", "fetch", state="FL", today=DAY).reason_code == "NO_RECORD"  # named dataset needs a named caller
    assert p.authorize("src_a", "display", state="FL", dataset="sale_calendar", today=DAY).reason_code == "NO_RECORD"
    # A county record beats the state record for that county only.
    assert p.authorize("src_a", "fetch", state="FL", county="Orange", dataset="sale_calendar", today=DAY).reason_code == "BLOCKED"
    assert p.authorize("src_a", "fetch", state="FL", county="Leon", dataset="sale_calendar", today=DAY).allowed


def test_county_record_overrides_state_record():
    p = perms(ok_row(), record(source_id="src_a", jurisdiction="FL:Volusia", operation="fetch", status="BLOCKED",
                               evidence_type="PROHIBITION_FOUND", reviewer="", effective_on="", expires_on=""))
    assert p.authorize("src_a", "fetch", state="FL", county="Leon", today=DAY).allowed
    d = p.authorize("src_a", "fetch", state="FL", county="Volusia", today=DAY)
    assert not d.allowed and d.reason_code == "BLOCKED"


def test_conditional_permission_requires_its_condition():
    row = record(source_id="src_c", jurisdiction="FL", operation="display", status="APPROVED_WITH_CONDITIONS",
                 evidence_type="PUBLISHED_LICENSE", conditions="attribution_text_recorded")
    assert perms({**row, "attribution": "Example County - CC BY 4.0"}).authorize("src_c", "display", state="FL", today=DAY).documented
    d = perms(row).authorize("src_c", "display", state="FL", today=DAY)
    assert not d.allowed and d.reason_code == "CONDITION_UNMET"
    # Conditions are evaluated by the engine's own checkers, never asserted by a caller.
    p = perms(row)
    p.checkers["attribution_text_recorded"] = lambda rec: (_ for _ in ()).throw(RuntimeError("broken"))
    assert p.authorize("src_c", "display", state="FL", today=DAY).reason_code == "CONDITION_UNCHECKABLE"


def test_real_conditions_on_real_sources():
    p = PERM.Permissions.from_file()
    # Colorado OIT parcels: allowed only while no CO source is in the paid tier.
    assert p.authorize("co_oit_public_parcels", "enrich", state="CO", today=DAY).allowed
    p2 = PERM.Permissions.from_file()
    p2.checkers["excluded_from_paid_tier"] = lambda rec: False
    assert p2.authorize("co_oit_public_parcels", "enrich", state="CO", today=DAY).reason_code == "CONDITION_UNMET"
    # East Baton Rouge: display only as a dated list (registry restriction on record).
    assert p.authorize("la_ebr_adjudicated", "display", state="LA", today=DAY).documented
    assert p.authorize("co_oit_public_parcels", "redistribute", state="CO", today=DAY).reason_code == "RESTRICTED"


def test_conflicting_records_deny():
    p = perms(ok_row(), ok_row(reason="a second record for the same scope"))
    d = p.authorize("src_a", "fetch", state="FL", today=DAY)
    assert not d.allowed and d.reason_code == "CONFLICT"


def test_invalid_or_unavailable_configuration_denies_everything(tmp_path):
    missing = PERM.Permissions.from_file(tmp_path / "nope.csv")
    assert missing.error and missing.authorize("fl_realauction", "fetch", state="FL", dataset="sale_calendar").reason_code == "CONFIG_INVALID"
    bad = tmp_path / "bad.csv"
    bad.write_text("source_id,operation\nfl_realauction,fetch\n", encoding="utf-8")
    assert PERM.Permissions.from_file(bad).authorize("fl_realauction", "fetch", state="FL", dataset="sale_calendar").reason_code == "CONFIG_INVALID"
    # One invalid row invalidates the whole file: nothing is allowed from a file nobody can trust.
    rows = list(csv.DictReader(PERM.PERMISSIONS_CSV.open(encoding="utf-8")))
    rows[0]["status"] = "PROBABLY_FINE"
    f = tmp_path / "one_bad.csv"
    with f.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PERM.COLUMNS)
        w.writeheader(); w.writerows(rows)
    p = PERM.Permissions.from_file(f)
    assert p.error and not p.authorize("la_ebr_adjudicated", "fetch", state="LA").allowed


def test_internal_risk_acceptance_is_never_documented_permission():
    p = perms(ok_row())  # OWNER_PERMISSION_REQUIRED on INTERNAL_RISK_ACCEPTANCE
    d = p.authorize("src_a", "fetch", state="FL", today=DAY)
    assert d.allowed and d.basis == "INTERIM" and not d.documented and "not a grant" in d.reason
    assert d.as_dict()["documented"] is False
    # Recording an internal acceptance as APPROVED is refused by validation.
    upgraded = perms(ok_row(status="APPROVED"))
    assert upgraded.error and "never documented permission" in upgraded.error
    assert not upgraded.authorize("src_a", "fetch", state="FL", today=DAY).allowed
    # WRITTEN_PERMISSION must agree with authorization.py - LienHub's record there is not granted.
    forged = perms(record(source_id="fl_lienhub_certificates", jurisdiction="FL", operation="fetch",
                          status="APPROVED", evidence_type="WRITTEN_PERMISSION"))
    assert forged.error and "contradicts authorization.py" in forged.error


def test_an_open_status_without_an_interim_allowance_denies():
    p = perms(ok_row(evidence_type="NO_EVIDENCE", reviewer="", effective_on="", expires_on=""))
    assert p.authorize("src_a", "fetch", state="FL", today=DAY).reason_code == "NOT_PERMITTED"


def test_link_only_allows_only_the_link():
    p = PERM.Permissions.from_file()
    assert p.authorize("tx_hctax", "link", state="TX", county="Harris", today=DAY).basis == "LINK_ONLY"
    for op in ("fetch", "store", "display"):
        assert not p.authorize("tx_hctax", op, state="TX", county="Harris", today=DAY).allowed


def test_allowances_expire_and_are_reported_before_they_do():
    p = PERM.Permissions.from_file()
    due = p.due_for_review(200, today=DAY)
    assert due and all(r.expires_on <= "2027-04-30" for r in due)
    assert not p.authorize("fl_realauction", "fetch", state="FL", dataset="sale_calendar", today=date(2027, 4, 13)).allowed


# --- 2. hard blocks ---------------------------------------------------------------

def test_hard_blocked_vendors_match_the_registry_constant():
    assert PERM.HARD_BLOCKED_SOURCE_IDS >= set(BLOCKED_SOURCE_IDS) >= {"tx_govease", "tx_pbfcm", "tx_mvba", "tx_ctsa"}


@pytest.mark.parametrize("op", PERM.OPERATIONS)
def test_govease_is_denied_for_every_operation(op):
    d = PERM.Permissions.from_file().authorize("tx_govease", op, state="TX", today=DAY)
    assert not d.allowed and d.reason_code == "HARD_BLOCKED"


def test_govease_cannot_be_unblocked_by_editing_the_record():
    for status, ev in (("APPROVED", "PUBLISHED_LICENSE"), ("OWNER_PERMISSION_REQUIRED", "INTERNAL_RISK_ACCEPTANCE"),
                       ("LINK_ONLY", "NO_EVIDENCE"), ("UNKNOWN", "GRANDFATHERED_PRACTICE")):
        p = perms(record(source_id="tx_govease", jurisdiction="TX", operation="link", status=status, evidence_type=ev))
        assert p.error and "hard-blocked in code" in p.error
        assert not p.authorize("tx_govease", "link", state="TX", today=DAY).allowed


def test_stale_or_missing_evidence_cannot_unblock_govease():
    rows = [r for r in csv.DictReader(PERM.PERMISSIONS_CSV.open(encoding="utf-8")) if r["source_id"] != "tx_govease"]
    p = permissions_with(*rows, base=False)  # GovEase rows removed entirely
    assert p.error is None and not p.authorize("tx_govease", "fetch", state="TX", today=DAY).allowed


def test_govease_block_holds_on_every_other_layer():
    from harvesters.governance.gate import check_ingestion_gate
    from harvesters.governance.registry import SOURCE_REGISTRY, SourceStatus
    from harvesters.sources import acquisition_gate as AG
    assert SOURCE_REGISTRY["tx_govease"].legal_status == SourceStatus.BLOCKED
    assert not check_ingestion_gate("tx_govease").allowed
    assert "govease.com" in AG.UNTRUSTED_HOSTS if hasattr(AG, "UNTRUSTED_HOSTS") else "govease.com" in Path(AG.__file__).read_text()
    import texas_harvester as TH
    with pytest.raises(NotImplementedError):
        TH.harvest_govease()


def test_a_publication_review_cannot_publish_a_blocked_vendor(monkeypatch):
    import source_publication as SP
    bad = {("TX", "tx_govease"): {"id": 9, "state": "TX", "source_id": "tx_govease", "publication_status": "APPROVED",
                                  "restrictions": "", "decided_at": "2026-10-12T00:00:00Z"}}
    reg, _ = SP.registry_with_reviews("TX", reviews=bad)
    assert not SP.publishable(reg.get("tx_govease")) and not SP.collectable(reg.get("tx_govease"), "auction")


# --- 3. parity and wired entry points ------------------------------------------------

def _publication_rule(row) -> bool:
    pub = effective_publication(row)
    return pub in PUBLISHABLE_STATUSES or ("AVAILABLE" in (row.ledgers or "") and pub != "BLOCKED")


def test_parity_every_currently_collected_registry_source_keeps_fetch_and_store():
    p = PERM.Permissions.from_file()
    for row in load_registry():
        if not row.source_id or not row.is_production or not _publication_rule(row):
            continue
        if row.source_id in ("tx_lgbs", "tx_realauction"):
            ds = None
        elif row.source_id == "fl_realauction":
            ds = "sale_calendar"
        elif row.source_id == "fl_lienhub_certificates":
            ds = "county_held_certificates"
        elif row.source_id.startswith("fl_laft_"):
            ds = "lands_available"
        elif row.source_id == "fl_bid4assets_okaloosa":
            ds = "sale_calendar"
        else:
            ds = None
        # The new-sources sprint's records start on the owner's decision day (2026-10-26).
        day = OWNER_DECISION_DAY if row.source_id in EX.NEW_SOURCE_IDS else DAY
        for op in ("fetch", "store"):
            d = p.authorize(row.source_id, op, state=row.state, county=row.county, dataset=ds, today=day)
            assert d.allowed, (row.source_id, row.county, op, d.reason_code)


def test_parity_every_currently_publishable_source_keeps_display():
    p = PERM.Permissions.from_file()
    for row in load_registry():
        if row.source_id and effective_publication(row) in PUBLISHABLE_STATUSES:
            d = p.authorize(row.source_id, "display", state=row.state, county=row.county, today=DAY)
            ds_d = p.authorize(row.source_id, "display", state=row.state, county=row.county,
                               dataset={"fl_realauction": "sale_calendar", "fl_lienhub_certificates": "county_held_certificates",
                                        "fl_bid4assets_okaloosa": "sale_calendar"}.get(row.source_id,
                                        "lands_available" if row.source_id.startswith("fl_laft_") else None), today=DAY)
            assert d.allowed or ds_d.allowed, (row.source_id, row.county)


def test_admin_only_sources_have_no_display_permission():
    p = PERM.Permissions.from_file()
    for sid, st in (("mi_detroit_landbank_lots", "MI"), ("tn_shelby_landbank", "TN"), ("mo_stl_lra_inventory", "MO"),
                    ("ok_oklahoma_county_owned", "OK"), ("pa_fayette_repository", "PA")):
        assert p.authorize(sid, "fetch", state=st, today=DAY).basis == "INTERIM"
        assert p.authorize(sid, "display", state=st, today=DAY).reason_code == "NO_RECORD"


def test_every_guarded_source_id_has_a_record():
    known = PERM.Permissions.from_file().source_ids()
    named = set()
    for f in (ROOT / "scripts").glob("harvest_laft_*.py"):
        named |= {f"fl_laft_{f.stem.split('harvest_laft_')[1]}"}
    from ps1_permission_guard import GUARDED, guard_args
    for name in GUARDED:
        a = guard_args((ROOT / "scripts" / name).read_text(encoding="utf-8"))
        named |= {a[i + 1] for i, x in enumerate(a) if x == "--source"}
    named |= {"fl_fdor_cadastral", "fl_santa_rosa_parcels", "fl_palm_coast_flagler_parcels", "census_geocoder",
              "fema_nfhl", "usda_naip", "google_street_view", "tx_lgbs", "tx_realauction", "la_ebr_adjudicated"}
    assert named <= known, named - known


@pytest.mark.parametrize("name", ["harvest_all_counties.ps1", "harvest_okaloosa_bid4assets.ps1", "harvest_lienhub_certificates.ps1",
                                  "sync-harvest-to-supabase.ps1", "sync-certificates-to-supabase.ps1", "sync-laft-to-supabase.ps1"])
def test_powershell_guard_command_allows_today_and_fails_closed(name, tmp_path):
    from ps1_permission_guard import guard_args
    args = guard_args((ROOT / "scripts" / name).read_text(encoding="utf-8"))
    cli = [sys.executable, str(ROOT / "scripts" / "source_permission_check.py"), *args]
    ok = subprocess.run(cli, capture_output=True, text=True, cwd=str(ROOT))
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert all(json.loads(l)["allowed"] for l in ok.stdout.splitlines())
    broken = tmp_path / "broken.csv"
    broken.write_text("not,a,permission,file\n", encoding="utf-8")
    denied = subprocess.run([*cli, "--permissions", str(broken)], capture_output=True, text=True, cwd=str(ROOT))
    assert denied.returncode == 3 and '"CONFIG_INVALID"' in denied.stdout


def test_cli_due_report_and_usage():
    out = subprocess.run([sys.executable, str(ROOT / "scripts/source_permission_check.py"), "--due", "400"],
                         capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0 and "fl_realauction" in out.stdout


DENY_ALL = PERM.Permissions([], error="test: governance configuration withheld")


@pytest.fixture
def deny_all(monkeypatch):
    monkeypatch.setattr(PERM, "_DEFAULT", DENY_ALL)


def _boom(*a, **k):
    raise AssertionError("a request or write was attempted after a denial")


@pytest.mark.parametrize("mod", ["harvest_laft_pdfs", "harvest_laft_html", "harvest_laft_realtdm", "harvest_laft_pioneer",
                                 "harvest_laft_orange", "harvest_laft_stlucie", "harvest_laft_osceola",
                                 "harvest_laft_hillsborough", "harvest_laft_leon"])
def test_laft_harvesters_stop_before_any_request(mod, deny_all, monkeypatch):
    import types
    import requests
    if mod in ("harvest_laft_stlucie", "harvest_laft_hillsborough"):
        # These two drive a headless browser; a stand-in Playwright whose launch
        # fails the test proves the gate stops them before a browser starts.
        pw = types.ModuleType("playwright"); api = types.ModuleType("playwright.sync_api")
        api.sync_playwright = _boom
        api.TimeoutError = TimeoutError
        api.Error = RuntimeError
        monkeypatch.setitem(sys.modules, "playwright", pw)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
        sys.modules.pop(mod, None)
    m = importlib.import_module(mod)
    monkeypatch.setattr(requests.Session, "request", _boom)
    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(m, "OUT_DIR", Path("/nonexistent/should/not/be/created"), raising=False)
    assert m.main() == 3


def test_laft_pdfs_county_record_applies_to_that_county(monkeypatch):
    import laft_status as LS
    install(monkeypatch, record(source_id="fl_laft_pdfs", jurisdiction="FL:Glades", operation="fetch", dataset="lands_available",
                                status="BLOCKED", evidence_type="PROHIBITION_FOUND", reviewer="", effective_on="", expires_on=""),
            base=True)
    assert LS.permission("fl_laft_pdfs", "fetch", county="Bradford").allowed
    assert LS.permission("fl_laft_pdfs", "fetch", county="Glades").reason_code == "BLOCKED"


def test_laft_html_proxy_fallback_needs_its_own_permission(monkeypatch):
    import harvest_laft_html as H
    from laft_status import CategorizedError
    calls = []

    class Resp:
        status_code = 403

    class S:
        def get(self, url, **kw):
            calls.append(url)
            return Resp()

    rows = [r for r in csv.DictReader(PERM.PERMISSIONS_CSV.open(encoding="utf-8"))
            if not (r["source_id"] == "fl_laft_html" and r["operation"] == "fetch_via_proxy")]
    monkeypatch.setattr(PERM, "_DEFAULT", permissions_with(*rows, base=False))
    monkeypatch.setattr(H, "SCRAPERAPI_KEY", "configured")
    with pytest.raises(CategorizedError) as e:
        H.fetch(S(), "https://clerk.example.gov/list")
    assert e.value.status_category == "PERMISSION_DENIED" and calls == ["https://clerk.example.gov/list"]  # never the proxy


def test_texas_harvester_never_calls_a_denied_vendor(deny_all, monkeypatch, tmp_path):
    import texas_harvester as TH
    called = []
    monkeypatch.setattr(TH, "SOURCES", {"tx_lgbs": lambda **k: called.append("lgbs") or [],
                                        "tx_realauction": lambda **k: called.append("ra") or []})
    monkeypatch.setattr(TH, "HERE", tmp_path / "h")
    (tmp_path / "h").mkdir()
    try:
        TH.main()
    except SystemExit:
        pass
    assert called == []


def test_texas_sync_store_permission(deny_all):
    spec = importlib.util.spec_from_file_location("sync_texas", ROOT / "scripts" / "sync-texas-to-supabase.py")
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pytest.skip("module exits at import without credentials")
    assert m._store_permitted("tx_lgbs") is False


def test_lgbs_refresh_makes_no_request_when_denied(deny_all, monkeypatch):
    import lgbs_available_refresh as L
    monkeypatch.setattr(L, "http_json", _boom)
    records, stats = L.walk_feed()
    assert records == [] and stats["gate_allowed"] is False and stats["permission"] == "CONFIG_INVALID"


def test_auction_outcomes_refuses_before_reading(deny_all, monkeypatch):
    import auction_outcomes as AO
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "x")
    monkeypatch.setattr(AO, "Api", _boom)
    assert AO.main([]) == 3


def test_state_inventory_harvest_refuses_before_fetching(deny_all, monkeypatch, tmp_path):
    import harvest_state_inventory as HSI
    monkeypatch.setattr(HSI, "live_fetcher", _boom)
    rc = HSI.main(["--state", "LA", "--status", str(tmp_path / "s.json"), "--out", str(tmp_path / "o.json"),
                   "--report", str(tmp_path / "r.json")])
    assert rc in (2, 3)  # 2 = refused earlier by can_run; 3 = refused by the permission gate; never a fetch


def test_expansion_harvest_and_sync_require_fetch_and_store(monkeypatch):
    import harvest_expansion as HE
    import source_publication as SP
    reg, _ = SP.registry_with_reviews("MI", reviews={})
    run, gated = HE.runnable_sources("MI", reg)
    assert {s.config.source_id for s in run} >= {"mi_eaton_treasurer_sale", "mi_detroit_landbank_lots"}
    monkeypatch.setattr(PERM, "_DEFAULT", DENY_ALL)
    run2, gated2 = HE.runnable_sources("MI", reg)
    assert run2 == [] and all(why.startswith("PERMISSION_") or why in ("UNREVIEWED", "BLOCKED", "RESTRICTED", "UNREGISTERED")
                              for _, why in gated2)
    assert not SP.collectable(reg["mi_eaton_treasurer_sale"], "auction", "store")
    assert not SP.publishable(reg["mi_eaton_treasurer_sale"])


def test_publication_state_withholds_without_display_permission():
    from harvesters.governance import publication_state as PS
    ctx = PS.Context()
    ctx.source_publication = {"src_x": "APPROVED"}
    ctx.ledger_eligibility = {("FL", "AVAILABLE"): "OFFERED"}
    d = PS.decide({"state": "FL", "county": "Leon", "ledger_type": "buy", "source": "laft", "source_id": "src_x",
                   "case_no": "1", "status": "active"}, ctx)
    assert d.state == "ADMIN_ONLY_SOURCE_REVIEW" and "SOURCE_RESTRICTED" in d.reasons


def test_parcel_enrichment_requires_recorded_permission(monkeypatch):
    from harvesters.enrichment import parcels as P
    from harvesters.enrichment.sources import all_sources
    cfgs = {c.source_id: c for c in all_sources()}
    assert P.enrichment_allowed(cfgs["la_ebr_tax_roll"])[0]
    assert not P.enrichment_allowed(cfgs["wi_sco_v12_parcels"])[0]
    monkeypatch.setattr(PERM, "_DEFAULT", DENY_ALL)
    ok, why = P.enrichment_allowed(cfgs["la_ebr_tax_roll"])
    assert not ok and "CONFIG_INVALID" in why


def test_fdor_coordinate_source_is_not_marked_licensed():
    from harvesters.enrichment import geocode as G
    assert G.FDOR_SOURCE.publication_status == "APPROVED_GRANDFATHERED"
    assert G.SANTA_ROSA_SOURCE.publication_status == "APPROVED_GRANDFATHERED"
    p = PERM.Permissions.from_file()
    d = p.authorize("fl_fdor_cadastral", "enrich", state="FL", dataset="parcel_centroid", today=DAY)
    assert d.allowed and d.basis == "INTERIM" and not d.documented
    for op in ("display", "redistribute", "store"):
        assert not p.authorize("fl_fdor_cadastral", op, state="FL", dataset="parcel_centroid", today=DAY).allowed


def test_fdor_coordinate_source_denied_when_permission_withdrawn(deny_all):
    from harvesters.enrichment import geocode as G
    assert G.FDOR_SOURCE.usable() == (False, "PERMISSION_DENIED")


def _script_env():
    return {**os.environ, "SUPABASE_URL": "https://example.invalid", "SUPABASE_SERVICE_KEY": "x"}


@pytest.mark.parametrize("mod,first_io", [("geocode_properties", "read_pool"), ("enrich_flood_zone", "schema_is_ready"),
                                          ("enrich_property_photos_naip", "storage_used_bytes")])
def test_enrichment_scripts_exit_3_before_any_request(mod, first_io, deny_all, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "x")
    m = importlib.import_module(mod)
    monkeypatch.setattr(m, first_io, _boom)
    with pytest.raises(SystemExit) as e:
        m.main()
    assert e.value.code == 3


def test_fdor_enricher_stops_before_reading(deny_all, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "x")
    m = importlib.import_module("enrich_property_details")
    monkeypatch.setattr(m, "fetch_needing_enrichment_counties", _boom)
    assert m.main() is None


def test_street_view_stays_blocked_even_with_a_key():
    env = {**_script_env(), "GOOGLE_MAPS_API_KEY": "configured-for-test"}
    out = subprocess.run([sys.executable, str(ROOT / "scripts/fetch_property_photos.py")], capture_output=True, text=True,
                         cwd=str(ROOT), env=env, timeout=60)
    assert out.returncode == 0 and "google_street_view fetch not permitted [BLOCKED]" in out.stdout


def test_cli_runs_on_a_bare_python_with_no_site_packages():
    """The deeds and certificates jobs call the PowerShell guard before any
    setup-python step, so the CLI must work on the runner's system Python with
    the standard library only (python -S: no site-packages)."""
    out = subprocess.run([sys.executable, "-S", str(ROOT / "scripts/source_permission_check.py"), "--source", "fl_realauction",
                          "--operation", "fetch", "--state", "FL", "--dataset", "sale_calendar"],
                         capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0 and json.loads(out.stdout.splitlines()[0])["allowed"] is True, out.stderr
