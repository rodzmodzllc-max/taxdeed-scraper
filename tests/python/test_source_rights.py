"""Source rights enforcement (harvesters/governance/source_rights.py, 2026-10-16).

Covers the register reconciliation, the per-use rights profile (every
condition, county and dataset scope, links-only, hard blocks, documented-only
uses, the circumvention rule), the customer-safe notice, the public
disclosure scan and the field provenance / value-status contract.
Everything here is offline: no network, no database.
"""
from __future__ import annotations

import csv
import glob
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import permissions as P  # noqa: E402
from harvesters.governance import source_rights as R  # noqa: E402
from permission_fixtures import permissions_with, record  # noqa: E402

TODAY = date(2026, 10, 16)
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
PERMS = P.Permissions.from_file()


def _map_rows():
    with R.CODE_MAP_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --- the register reconciliation ---------------------------------------------

def test_reconciliation_report_is_current():
    r = subprocess.run([sys.executable, "scripts/build_source_rights_report.py", "--check"], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_code_map_covers_every_register_row_in_order():
    with R.REGISTER_CSV.open(newline="", encoding="utf-8") as f:
        register = [r["source_id"] for r in csv.DictReader(f)]
    assert len(register) == 84
    assert [r["register_id"] for r in _map_rows()] == register


def test_code_map_values_are_valid():
    known = PERMS.source_ids() | P.HARD_BLOCKED_SOURCE_IDS
    for m in _map_rows():
        assert m["decision_class"] in R.CEILINGS, m
        assert m["match_type"] in R.MATCH_TYPES, m
        for sid in filter(None, m["code_source_ids"].split(";")):
            assert sid in known, (m["register_id"], sid)
        if m["match_type"] in ("NO_CODE_SOURCE", "NO_PERMISSION_RECORD", "CLIENT_SIDE"):
            assert not m["code_source_ids"] and m["scope"] == "none", m


def test_every_permission_source_is_mapped_to_a_register_row():
    out = R.reconcile(today=TODAY, perms=PERMS)
    assert not [f for f in out["findings"] if f["kind"] in ("UNREGISTERED_CODE_SOURCE", "NOT_MAPPED")]


def test_every_mapped_row_is_evaluated_per_place():
    rows = {r["register_id"]: r for r in R.reconcile(today=TODAY, perms=PERMS)["rows"]}
    assert rows["fl_laft_html_proxied"]["places"] == ["FL:Columbia", "FL:Escambia", "FL:Union"]
    direct = rows["fl_laft_html_direct"]["places"]
    assert direct and not {"FL:Escambia", "FL:Columbia", "FL:Union"} & set(direct)
    assert rows["fl_realauction_alachua_volusia"]["places"] == ["FL:Alachua", "FL:Volusia"]
    assert len(rows["fl_realauction_other_44"]["places"]) >= 44


def test_the_reported_discrepancies_are_exactly_these():
    """A new discrepancy (or a fixed one) must change this list on purpose."""
    found = sorted((f["kind"], f["register_id"], f["source_id"], tuple(f["operations"]))
                   for f in R.reconcile(today=TODAY, perms=PERMS)["findings"])
    assert found == sorted([
        ("EXCEEDS_CEILING", "fl_lienhub_certificates", "fl_lienhub_certificates", ("display", "fetch", "parse", "store")),
        ("EXCEEDS_CEILING", "ut_ugrc_lir_saltlake", "ut_ugrc_lir_saltlake", ("enrich", "fetch")),
        ("NO_PERMISSION_RECORD", "sc_spartanburg_forfeited_land", "", ()),
        ("CLIENT_SIDE_NO_RECORD", "google_maps_js_and_static", "", ()),
        ("CLIENT_SIDE_NO_RECORD", "maptiler_cloud", "", ()),
        ("CLIENT_SIDE_NO_RECORD", "openstreetmap_embed", "", ()),
    ])


def test_client_side_providers_are_reported():
    kinds = {f["register_id"]: f["kind"] for f in R.reconcile(today=TODAY, perms=PERMS)["findings"]}
    for rid in ("google_maps_js_and_static", "maptiler_cloud", "openstreetmap_embed"):
        assert kinds[rid] == "CLIENT_SIDE_NO_RECORD"


def test_a_ceiling_breach_is_reported_per_county():
    m = [dict(r) for r in _map_rows()]
    for r in m:
        if r["register_id"] == "fl_laft_html_proxied":
            r["decision_class"] = "LINKS_ONLY"
    out = R.reconcile(today=TODAY, perms=PERMS, code_map=m)
    f = [x for x in out["findings"] if x["register_id"] == "fl_laft_html_proxied"]
    assert len(f) == 1 and f[0]["places"] == ["FL:Columbia", "FL:Escambia", "FL:Union"]
    assert "fetch" in f[0]["operations"] and "display" in f[0]["operations"]


# --- the circumvention rule ------------------------------------------------

def test_proxy_fallback_is_denied_on_interim_permission():
    for county in ("Escambia", "Columbia", "Union", "Leon"):
        d = PERMS.authorize("fl_laft_html", "fetch_via_proxy", state="FL", county=county, dataset="lands_available",
                            today=TODAY)
        assert not d.allowed and d.reason_code == "CIRCUMVENTION_NEEDS_DOCUMENTED", county
    # The direct fetch is unaffected.
    assert PERMS.authorize("fl_laft_html", "fetch", state="FL", county="Escambia", dataset="lands_available",
                           today=TODAY).allowed


def test_circumvention_is_allowed_only_by_documented_permission():
    interim = permissions_with(record(source_id="zz_src", jurisdiction="FL", operation="fetch_via_proxy"), base=False)
    assert interim.authorize("zz_src", "fetch_via_proxy", state="FL", today=TODAY).reason_code == "CIRCUMVENTION_NEEDS_DOCUMENTED"
    documented = permissions_with(record(source_id="zz_src", jurisdiction="FL", operation="fetch_via_proxy",
                                         status="APPROVED", evidence_type="PUBLISHED_LICENSE", expires_on="2099-01-01"),
                                  base=False)
    d = documented.authorize("zz_src", "fetch_via_proxy", state="FL", today=TODAY)
    assert d.allowed and d.basis == "DOCUMENTED"


# --- the policy: conditions, scope, expiry, links-only, blocks ---------------

def _doc(**kw):
    return record(status="APPROVED_WITH_CONDITIONS", evidence_type="PUBLISHED_LICENSE", expires_on="2099-01-01", **kw)


def test_every_condition_must_hold():
    rows = [_doc(source_id="zz_src", jurisdiction="FL", operation="display", conditions="c1|c2")]
    perms = permissions_with(*rows, base=False)
    assert perms.error and "unknown condition" in perms.error           # an unknown condition invalidates the file
    recs = P.parse(csv.DictReader(_csv(rows)))
    both = P.Permissions(recs, checkers={"c1": lambda r: True, "c2": lambda r: True})
    one = P.Permissions(recs, checkers={"c1": lambda r: True, "c2": lambda r: False})
    broken = P.Permissions(recs, checkers={"c1": lambda r: True, "c2": lambda r: 1 / 0})
    missing = P.Permissions(recs, checkers={"c1": lambda r: True})
    assert both.authorize("zz_src", "display", state="FL", today=TODAY).allowed
    assert one.authorize("zz_src", "display", state="FL", today=TODAY).reason_code == "CONDITION_UNMET"
    assert broken.authorize("zz_src", "display", state="FL", today=TODAY).reason_code == "CONDITION_UNCHECKABLE"
    assert missing.authorize("zz_src", "display", state="FL", today=TODAY).reason_code == "UNKNOWN_CONDITION"


def test_approved_with_conditions_needs_a_condition():
    perms = permissions_with(_doc(source_id="zz_src", jurisdiction="FL", operation="display", conditions=""), base=False)
    assert perms.error and "needs at least one condition" in perms.error


def _csv(rows):
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=P.COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    buf.seek(0)
    return buf


def test_a_county_record_never_covers_another_county():
    perms = permissions_with(record(source_id="zz_src", jurisdiction="FL:Volusia", operation="fetch"), base=False)
    assert perms.authorize("zz_src", "fetch", state="FL", county="Volusia", today=TODAY).allowed
    assert perms.authorize("zz_src", "fetch", state="FL", county="Marion", today=TODAY).reason_code == "NO_RECORD"
    assert perms.authorize("zz_src", "fetch", state="FL", today=TODAY).reason_code == "NO_RECORD"
    assert perms.authorize("zz_src", "fetch", state="GA", county="Volusia", today=TODAY).reason_code == "NO_RECORD"


def test_a_provider_approval_never_covers_another_dataset_or_operation():
    perms = permissions_with(record(source_id="zz_src", jurisdiction="FL", operation="fetch", dataset="sale_calendar"),
                             base=False)
    assert perms.authorize("zz_src", "fetch", state="FL", dataset="sale_calendar", today=TODAY).allowed
    assert not perms.authorize("zz_src", "fetch", state="FL", dataset="closed_results", today=TODAY).allowed
    assert not perms.authorize("zz_src", "fetch", state="FL", today=TODAY).allowed
    assert not perms.authorize("zz_src", "display", state="FL", dataset="sale_calendar", today=TODAY).allowed


def test_real_florida_records_are_scoped_by_dataset():
    assert PERMS.authorize("fl_realauction", "display", state="FL", county="Leon", dataset="sale_calendar", today=TODAY).allowed
    assert not PERMS.authorize("fl_realauction", "display", state="FL", county="Leon", today=TODAY).allowed
    assert not PERMS.authorize("fl_realauction", "display", state="FL", county="Leon", dataset="lands_available",
                               today=TODAY).allowed


@pytest.mark.parametrize("kw,code", [
    ({"expires_on": "2026-10-15"}, "EXPIRED"),
    ({"effective_on": "2026-10-20", "evidence_date": "2026-10-20", "expires_on": "2027-04-12"}, "NOT_YET_EFFECTIVE"),
    ({"status": "BLOCKED", "evidence_type": "PROHIBITION_FOUND"}, "BLOCKED"),
    ({"status": "RESTRICTED", "evidence_type": "TERMS_SILENT"}, "RESTRICTED"),
    ({"status": "UNKNOWN", "evidence_type": "NO_EVIDENCE"}, "NOT_PERMITTED"),
])
def test_expired_withdrawn_or_unevidenced_records_fail_closed(kw, code):
    perms = permissions_with(record(source_id="zz_src", jurisdiction="FL", operation="fetch", **kw), base=False)
    d = perms.authorize("zz_src", "fetch", state="FL", today=TODAY)
    assert not d.allowed and d.reason_code == code


def test_an_invalid_file_denies_everything():
    broken = P.Permissions([], error="unreadable")
    assert broken.authorize("la_ebr_adjudicated", "display", state="LA", today=TODAY).reason_code == "CONFIG_INVALID"
    prof = R.rights_profile("la_ebr_adjudicated", state="LA", today=TODAY, perms=broken)
    assert not any(u["allowed"] for u in prof["uses"].values() if u["use"] != "imagery")


def test_link_only_allows_no_copy():
    prof = R.rights_profile("tx_hctax", state="TX", county="Harris", today=TODAY, perms=PERMS)
    allowed = sorted(u for u, d in prof["uses"].items() if d["allowed"])
    assert allowed == ["link"] and prof["uses"]["link"]["basis"] == "LINK_ONLY"
    for op in ("fetch", "parse", "store", "display", "enrich", "redistribute"):
        assert not PERMS.authorize("tx_hctax", op, state="TX", county="Harris", today=TODAY).allowed
    notice = R.customer_source_notice("tx_hctax", state="TX", county="Harris", today=TODAY, perms=PERMS)
    assert notice["shown"] is False and notice["basis"] == R.CUSTOMER_BASIS_LABELS["LINK_ONLY"]


def test_hard_blocked_vendors_allow_nothing():
    for sid in sorted(P.HARD_BLOCKED_SOURCE_IDS):
        for op in P.OPERATIONS:
            d = PERMS.authorize(sid, op, state="TX", county="Denton", today=TODAY)
            assert not d.allowed and d.reason_code == "HARD_BLOCKED", (sid, op)
        assert R.customer_source_notice(sid, state="TX", today=TODAY, perms=PERMS)["shown"] is False


def test_admin_only_sources_never_allow_display():
    rows = R.reconcile(today=TODAY, perms=PERMS)["rows"]
    admin = [r for r in rows if r["decision_class"] == "ADMIN_ONLY"]
    assert len(admin) == 9
    for r in admin:
        assert not any(k.endswith((":display", ":redistribute")) for k in r["allowed"]), r["register_id"]
        for sid in r["code_source_ids"]:
            for place in r["places"]:
                st, _, county = place.partition(":")
                n = R.customer_source_notice(sid, state=st, county=county or None, today=TODAY, perms=PERMS)
                assert n["shown"] is False, (sid, place)


def test_commercial_use_and_export_need_documented_permission():
    interim = R.rights_profile("fl_realauction", state="FL", county="Leon", dataset="sale_calendar", today=TODAY, perms=PERMS)
    assert interim["uses"]["customer_display"]["allowed"] and interim["uses"]["customer_display"]["basis"] == "INTERIM"
    assert not interim["uses"]["commercial_use"]["allowed"]
    assert interim["uses"]["commercial_use"]["reason_code"] == "NEEDS_DOCUMENTED_PERMISSION"
    assert not interim["uses"]["export"]["allowed"]
    documented = R.rights_profile("la_ebr_adjudicated", state="LA", county="East Baton Rouge", today=TODAY, perms=PERMS)
    assert documented["uses"]["commercial_use"]["allowed"] and documented["uses"]["commercial_use"]["basis"] == "DOCUMENTED"
    assert documented["uses"]["refresh"]["allowed"]


def test_no_source_may_be_exported_today():
    for sid in sorted(PERMS.source_ids()):
        for st in sorted({r.state for r in PERMS.records if r.source_id == sid}):
            assert not PERMS.authorize(sid, "redistribute", state=st, today=TODAY).allowed, sid


def test_refresh_needs_every_operation():
    # census_geocoder may fetch and enrich but not store: a refresh (fetch +
    # parse + store) is never implied by a fetch permission.
    prof = R.rights_profile("census_geocoder", state="FL", today=TODAY, perms=PERMS)
    assert prof["uses"]["enrich"]["allowed"] and not prof["uses"]["refresh"]["allowed"]


def test_geometry_is_always_denied_and_imagery_follows_its_terms():
    for sid in ("fl_fdor_cadastral", "co_oit_public_parcels", "la_ebr_tax_parcels"):
        assert R.rights_profile(sid, state=sid[:2].upper(), today=TODAY, perms=PERMS)["uses"]["geometry"]["allowed"] is False
    assert R._imagery_use("usda_naip").allowed and R._imagery_use("usda_naip").basis == "DOCUMENTED"
    assert R._imagery_use("maptiler_static").basis == "LINK_ONLY"
    assert not R._imagery_use("google_street_view").allowed
    assert not R._imagery_use("county_gis_orthoimagery").allowed


# --- what a customer may be told ---------------------------------------------

def test_customer_notice_never_carries_internal_record_fields():
    internal = set()
    for r in PERMS.records:
        for v in (r.reviewer, r.reason, r.evidence_ref, r.evidence_type, r.status):
            if v and len(v) > 3:
                internal.add(v)
    for r in PERMS.records:
        if r.state == "US":
            continue
        n = R.customer_source_notice(r.source_id, state=r.state, county=r.county,
                                     dataset=None if r.dataset == "*" else r.dataset, today=TODAY, perms=PERMS)
        assert set(n) == {"source_id", "shown", "basis", "attribution", "conditions"}
        assert n["basis"] in R.CUSTOMER_BASIS_LABELS.values()
        text = json.dumps(n)
        leaked = [v for v in internal if v in text and v not in (n["attribution"], r.source_id)]
        assert not leaked, (r.source_id, leaked)


def test_public_files_disclose_nothing_internal():
    files = sorted(glob.glob(str(REPO / "public" / "*.json")) + glob.glob(str(REPO / "public" / "*.js"))
                   + glob.glob(str(REPO / "public" / "*.html")) + glob.glob(str(REPO / "*.json"))
                   + [str(REPO / "config.js")])
    assert len(files) > 20
    bad = {Path(f).name: R.public_disclosure_problems(Path(f).read_text(encoding="utf-8", errors="replace"))
           for f in files}
    assert {k: v for k, v in bad.items() if v} == {}


def test_the_disclosure_scan_catches_internal_material():
    assert R.public_disclosure_problems('{"reviewer": "x"}')
    assert R.public_disclosure_problems("interim (GRANDFATHERED_PRACTICE)")
    assert R.public_disclosure_problems("see data/source_permissions.csv")
    assert R.public_disclosure_problems('{"sb_secret_abc123": 1}')
    assert not R.public_disclosure_problems('{"attribution": "Source: East Baton Rouge Parish"}')


# --- field provenance and value status ---------------------------------------

def _row(**kw):
    base = {"id": 1, "state": "LA", "county": "East Baton Rouge", "source": "laft", "source_id": "la_ebr_adjudicated",
            "status": "active", "case_no": "123", "parcel": "000123", "last_seen_at": "2026-10-15T06:00:00+00:00",
            "list_as_of": "2024-02-27", "url_auction": "https://data.brla.gov/x"}
    base.update(kw)
    return base


def test_unknown_amounts_are_never_zero():
    legacy = _row(bid=0, purchase_amount=None, purchase_amount_kind=None)
    v = R.field_provenance_view(legacy, "amount", now=NOW, perms=PERMS, today=TODAY)
    assert v["value_status"] == "NOT_PUBLISHED" and v["value"] is None
    missing = R.field_provenance_view(_row(), "amount", now=NOW, perms=PERMS, today=TODAY)
    assert missing["value_status"] == "NOT_PUBLISHED" and missing["value"] is None
    real = R.field_provenance_view(_row(purchase_amount=1500, purchase_amount_kind="FIXED_PRICE"), "amount",
                                   now=NOW, perms=PERMS, today=TODAY)
    assert real["value_status"] == "CONFIRMED_SOURCE" and real["value"] == 1500 and real["origin"] == "SOURCE_REPORTED"


def test_estimates_and_derived_values_are_named():
    est = _row(purchase_amount=2100.5, purchase_amount_kind="ESTIMATED_PURCHASE_PRICE")
    assert R.value_status(est, "amount") == "ESTIMATED_BY_SOURCE"
    geo = _row(latitude=30.4, longitude=-91.1, field_provenance={"latitude": {"source": "census_geocoder"}})
    v = R.field_provenance_view(geo, "latitude", now=NOW, perms=PERMS, today=TODAY)
    assert v["value_status"] == "DERIVED_BY_TAXACQ" and v["origin"] == "DERIVED_BY_TAXACQ"
    centroid = _row(state="FL", county="Marion", source_id="fl_laft_pdfs", latitude=29.1,
                    field_provenance={"latitude": {"source": "fdor_nal", "dataset": "parcel_centroid"}})
    assert R.value_status(centroid, "latitude") == "DERIVED_BY_TAXACQ"


@pytest.mark.parametrize("fld", ["sold", "redeemed", "winner", "winning_bid", "price_paid", "owner", "title",
                                 "boundary_accuracy", "return", "flood_risk_score"])
def test_untracked_and_never_inferred_facts_are_not_tracked(fld):
    v = R.field_provenance_view(_row(sold=True, owner="X", winner="Y"), fld, now=NOW, perms=PERMS, today=TODAY)
    assert v["value_status"] == "NOT_TRACKED" and v["value"] is None and v["freshness"] == "NOT_TRACKED"


def test_timestamps_are_never_manufactured():
    row = _row(last_seen_at=None, list_as_of=None)
    v = R.field_provenance_view(row, "parcel", now=NOW, perms=PERMS, today=TODAY)
    assert v["last_verified_at"] is None and v["effective_at"] is None and v["retrieved_at"] is None
    assert v["freshness"] == "UNVERIFIED" and v["value_status"] == "UNVERIFIED"
    kept = R.field_provenance_view(_row(), "parcel", now=NOW, perms=PERMS, today=TODAY)
    assert kept["last_verified_at"] == "2026-10-15T06:00:00+00:00" and kept["effective_at"] == "2024-02-27"


def test_freshness_states():
    assert R.freshness(_row(), NOW) == "CURRENT"
    assert R.freshness(_row(last_seen_at="2026-09-01T00:00:00+00:00"), NOW) == "STALE"
    assert R.freshness(_row(status="closed"), NOW) == "WITHDRAWN"
    assert R.freshness(_row(delisted_at="2026-10-01T00:00:00+00:00"), NOW) == "WITHDRAWN"
    assert R.freshness(_row(last_seen_at=None), NOW) == "UNVERIFIED"


def test_a_source_without_display_permission_shows_no_value():
    row = _row(state="MI", county="Oceana", source_id="mi_oceana_landbank", parcel="64-001")
    v = R.field_provenance_view(row, "parcel", now=NOW, perms=PERMS, today=TODAY)
    assert v["value"] is None and v["freshness"] == "WITHDRAWN" and v["attribution"] == ""


def test_an_enrichment_value_needs_its_own_sources_permission_in_that_place():
    entry = {"latitude": {"source": "statewide_parcel", "source_id": "co_oit_public_parcels", "recorded_at": "2026-10-01"}}
    ok = _row(state="CO", county="Morgan", source_id="co_morgan_county_held_certificates", source="certificate",
              latitude=40.2, field_provenance=entry)
    assert R.field_provenance_view(ok, "latitude", now=NOW, perms=PERMS, today=TODAY)["value"] == 40.2
    elsewhere = dict(ok, state="WY", county="Albany", source_id="wy_albany_tax_sale", source="auction")
    assert R.field_provenance_view(elsewhere, "latitude", now=NOW, perms=PERMS, today=TODAY)["value"] is None


def test_attribution_rides_with_a_documented_source():
    row = _row(state="CO", county="Douglas", source_id="co_douglas_tax_sale_list", source="auction")
    v = R.field_provenance_view(row, "parcel", now=NOW, perms=PERMS, today=TODAY)
    assert v["attribution"] == "Douglas County, Colorado - CC BY-SA 4.0"
    assert set(v) == {"field", "value", "value_status", "value_status_label", "source_id", "provenance_source",
                      "source_url", "origin", "retrieved_at", "effective_at", "last_verified_at", "freshness",
                      "attribution", "conditions"}
    # A value another source attached carries THAT source's attribution.
    enriched = _row(land_use="Residential", field_provenance={"land_use": {
        "source": "statewide_parcel", "source_id": "la_ebr_tax_roll", "recorded_at": "2026-10-02T00:00:00+00:00"}})
    e = R.field_provenance_view(enriched, "land_use", now=NOW, perms=PERMS, today=TODAY)
    assert e["attribution"] == "EBR Parish Assessor" and e["retrieved_at"] == "2026-10-02T00:00:00+00:00"
    assert e["value"] == "Residential" and e["value_status"] == "CONFIRMED_SOURCE"


# --- a failed retrieval never refreshes verification -------------------------

@pytest.mark.parametrize("status", ["FAILED", "INCOMPLETE", "SOURCE_UNAVAILABLE", "STALE", "NOT_RUN", "", None])
def test_stamp_seen_never_stamps_a_county_whose_read_failed(status):
    import stamp_seen as S
    assert S.eligible_counties([{"county": "Leon", "status": status}]) == set()
    assert S.eligible_counties([{"county": "Leon", "status": "COMPLETE"}]) == {"Leon"}
