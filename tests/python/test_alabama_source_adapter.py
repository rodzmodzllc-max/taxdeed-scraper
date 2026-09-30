"""Alabama source adapter (2026-09-30): the ADOR configuration built from
the evidence ledger, the HTML readers, deterministic parsing, amount and
purchase-path semantics, provenance, outcome classification, the gated
live flow, the harvester script, and the lifecycle's state scoping.

Every fixture under tests/python/fixtures/alabama/ is SYNTHETIC (see its
README): the parser's structural assumptions are candidates, not the
source's verified layout. What these tests prove is that the code is
deterministic and honest on that shape - not that the shape is real.
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
from harvesters.governance import states  # noqa: E402
from harvesters.governance.states import STATEWIDE_UNIT, StateConfig  # noqa: E402
from harvesters.otc import AmountKind, InventoryType, PurchaseUrlKind  # noqa: E402
from harvesters.otc.adapters import alabama as ala  # noqa: E402
from harvesters.otc.gate import evaluate_source  # noqa: E402
import laft_lifecycle as L  # noqa: E402
from laft_status import ERROR_CATEGORIES, StatusRecorder, load_status  # noqa: E402

T = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
FIX = REPO / "tests/python/fixtures/alabama"
LANDING = (FIX / "ador_search_landing_SYNTHETIC.html").read_text(encoding="utf-8")
AUTAUGA = (FIX / "ador_search_results_autauga_SYNTHETIC.html").read_text(encoding="utf-8")
STATEWIDE = (FIX / "ador_search_results_statewide_SYNTHETIC.html").read_text(encoding="utf-8")
EMPTY = (FIX / "ador_search_results_empty_SYNTHETIC.html").read_text(encoding="utf-8")
NOTABLE = (FIX / "ador_search_results_notable_SYNTHETIC.html").read_text(encoding="utf-8")
SCRIPT = REPO / "scripts/harvest_alabama_state_land.py"
CFG = ala.ADOR_SOURCE


def _validated(**over):
    """A copy of the ADOR configuration that claims fixture validation -
    only to show what classify_outcome() does once that is true. Never
    enabled, never live-verified."""
    from dataclasses import replace
    return replace(CFG, parser_fixture_validated=True, **over)


# ==================== 1. evidence ledger and configuration ====================


def test_e01_evidence_ledger_names_only_the_agency_and_every_requirement_stays_unmet():
    assert len(ala.ADOR_EVIDENCE) == 6 and {e.grade for e in ala.ADOR_EVIDENCE} == {"SEARCH_INDEX", "AUDIT_NOTE"}
    for e in ala.ADOR_EVIDENCE:
        assert e.url == "" or (e.url.startswith("https://") and e.url.split("/")[2] == ala.ADOR_HOST), e.key
        assert e.statement and e.observed_on in ("2026-09-29", "2026-09-30")
    assert sum(1 for e in ala.ADOR_EVIDENCE if e.grade == "AUDIT_NOTE") == 1
    notes = ala.requirement_evidence()
    assert list(notes) == list(states.ACTIVATION_REQUIREMENTS)
    for req, note in notes.items():
        assert note and ("not" in note or "no " in note or "SYNTHETIC" in note), req   # each says why it is unmet
    # The state: registered, not activated, not production; FL/TX untouched.
    assert not states.is_activated("AL") and states.PRODUCTION_STATES == frozenset({"FL", "TX"})
    assert states.activation_blockers("AL") == list(states.ACTIVATION_REQUIREMENTS)
    assert states.AL.lifecycle_inventory_type == "STATE_HELD_TAX_LAND" and states.AL.production is False


def test_c01_ador_configuration_is_the_evidence_and_is_not_enabled():
    assert CFG.source_id == "al_ador_state_land" and CFG.publishing_unit == "STATE" and CFG.county is None
    assert CFG.inventory_type is InventoryType.STATE_HELD_TAX_LAND and CFG.amount_kind is AmountKind.QUOTED_ON_APPLICATION
    assert CFG.list_url == ala.ADOR_SEARCH_URL and CFG.document_url is None
    assert CFG.application_url == ala.ADOR_LAND_SALES_URL and CFG.application_url_kind is PurchaseUrlKind.PURCHASE_INSTRUCTIONS
    assert CFG.property_url_kind is PurchaseUrlKind.APPLICATION_FORM and CFG.property_url_hosts == (ala.ADOR_HOST,)
    assert CFG.fields.property_url == ala.IDENTIFIER_LINK_KEY and CFG.fields.amount is None and CFG.fields.balance is None
    assert CFG.fields.labels("identifier")[0] == "CS Number" and CFG.fields.labels("parcel")[0] == "Parcel Number"
    assert CFG.fields.labels("county") == ("County",) and CFG.fields.labels("assessed_name")[0] == "Name"
    assert CFG.observed_identifier_shapes == ("d8",)
    assert (CFG.county_query_param, CFG.county_submit_param) == ("ador-delinquent-county", "_ador-delinquent-county-submit")
    assert not (CFG.enabled or CFG.live_verified or CFG.identifier_format_established or CFG.parser_fixture_validated)
    d = ala.can_run(CFG)
    assert not d.allowed and d.reason.startswith("state AL is not activated")
    # The contract's new refusals.
    from dataclasses import replace
    with pytest.raises(ValueError, match="never purchase_instructions"):
        replace(CFG, property_url_kind=PurchaseUrlKind.PURCHASE_INSTRUCTIONS)
    with pytest.raises(ValueError, match="go together"):
        replace(CFG, county_submit_param=None)
    with pytest.raises(ValueError, match="cannot be enabled"):
        replace(CFG, enabled=True)
    with pytest.raises(ValueError, match="map the county column"):
        ala.AlabamaSourceConfig(source_id="x", publishing_unit="STATE", publishing_unit_name="A",
                                fields=ala.AlabamaFieldMap(identifier="CS Number"))
    # A statewide list with a county QUERY instead of a county column is acceptable.
    ala.AlabamaSourceConfig(source_id="x", publishing_unit="STATE", publishing_unit_name="A", fields=ala.AlabamaFieldMap(identifier="CS Number"),
                            county_query_param="c", county_submit_param="s")


def test_c02_identifier_shape_is_a_count_not_a_rewrite():
    assert ala.identifier_shape("01881497") == "d8" and ala.identifier_shape("0123459") == "d7"
    assert ala.identifier_shape("12-34-56-0-000-001.000") == "d2-d2-d2-d1-d3-d3.d3" and ala.identifier_shape("R 12 A") == "A1 d2 A1"
    assert ala.normalize_identifier(" 01881497 ") == "01881497"              # leading zero kept
    assert ala.normalize_identifier("01881497") != "1881497"
    for bad in (None, "", "ABC", "1\n2", "9" * 41):
        assert ala.normalize_identifier(bad) is None


# ==================== 2. HTML readers ====================


def test_h01_county_options_come_from_the_page_and_nothing_is_guessed():
    mapped, unmatched = ala.parse_county_options(LANDING)
    assert mapped == {"Autauga": "01", "Baldwin": "02", "Jefferson": "38", "Mobile": "49", "St. Clair": "59", "Winston": "67"}
    assert unmatched == ["Jefferson - Bessemer Division", "All Counties"]         # a division and an 'all' option are reported, never mapped
    assert ala.OBSERVED_COUNTY_SELECTOR_VALUE not in mapped.values()             # the one observed value has no county in code
    assert ala.parse_county_options("<html><select name='other'><option value='1'>Autauga</option></select></html>") == ({}, [])
    assert ala.parse_county_options(LANDING, param="some-other-select") == ({}, ["Not the county selector"])
    url = ala.county_results_url(CFG, "01")
    assert url == ala.ADOR_SEARCH_URL + "?ador-delinquent-county=01&_ador-delinquent-county-submit=submit"


def test_h02_per_county_results_page_rows_as_published_links_from_the_row_nothing_invented():
    url = ala.county_results_url(CFG, "01")
    recs, rep, out = ala.parse_search_results_html(CFG, AUTAUGA, retrieved_at=T, base_url=url, default_county="Autauga")
    assert out == {"header_table_found": True, "data_rows": 6, "empty_marker": False, "unmapped_columns": ["Year Sold"]}
    assert (rep.accepted, rep.rejected_identifier, rep.parcel_dropped, rep.identifier_shape_unobserved,
            rep.property_links, rep.rejected_property_url, rep.rejected_county, rep.county_mismatch) == (5, 1, 1, 1, 4, 1, 0, 0)
    assert rep.unmapped_columns == ("Year Sold",)                                  # a column the evidence never established: reported, not carried
    a, b, c, d, e = recs
    assert [r.case_no for r in recs] == ["00123456", "00123457", "00123458", "0123459", "00123460"]   # as published, zeros kept
    assert all(r.state == "AL" and r.county == "Autauga" and r.source_id == "al_ador_state_land" for r in recs)
    assert a.parcel == "12-34-56-0-000-001.000" and b.parcel is None and e.parcel is None            # blank / multi-line parcel -> None, row kept
    assert a.owner_name == "DOE JOHN & JANE" and a.provenance["owner_name"].startswith("the name in which the property was assessed")
    assert a.purchase_url == ala.ADOR_DETAIL_URL + "?ador-view-application=00123456" and a.purchase_url_kind is PurchaseUrlKind.APPLICATION_FORM
    assert a.provenance["purchase_url"].startswith("property-specific application_form link published on the row")
    # A link on another host is refused; the row falls back to the agency's instructions page.
    assert c.purchase_url == ala.ADOR_LAND_SALES_URL and c.purchase_url_kind is PurchaseUrlKind.PURCHASE_INSTRUCTIONS
    assert c.provenance["purchase_url"] == "agency application page (purchase_instructions)"
    assert d.provenance["identifier_shape"] == "d7" and a.provenance["identifier_shape"] == "d8"
    for r in recs:
        assert r.amount is None and r.amount_kind is AmountKind.QUOTED_ON_APPLICATION and r.inventory_type is InventoryType.STATE_HELD_TAX_LAND
        assert r.list_url == url and r.document_url is None and r.list_as_of is None and r.source_published_at is None
        assert r.provenance["county"] == "the county the list was queried for" and r.provenance["identifier"].startswith("as published")
        assert r.provenance["amount"].startswith("QUOTED_ON_APPLICATION: no price is published")
        assert r.validate() == []
        with pytest.raises(ValueError, match="not storable"):
            r.to_properties_row()                                                  # until migration 020
    # No row value in any counter, and the same input gives the same output.
    recs2, rep2, _ = ala.parse_search_results_html(CFG, AUTAUGA, retrieved_at=T, base_url=url, default_county="Autauga")
    assert [r.as_dict() for r in recs2] == [r.as_dict() for r in recs] and rep2 == rep
    # Without a page URL the identifier's link cannot be resolved: no link, instructions page instead.
    from dataclasses import replace
    recs3, rep3, _ = ala.parse_search_results_html(replace(CFG, list_url=None, application_url=None, application_url_kind=None),
                                                   AUTAUGA, retrieved_at=T, default_county="Autauga")
    assert all(r.purchase_url is None for r in recs3) and rep3.property_links == 0


def test_h03_statewide_page_the_row_s_own_county_wins_and_non_alabama_rows_are_refused():
    recs, rep, out = ala.parse_search_results_html(CFG, STATEWIDE, retrieved_at=T)
    assert out["header_table_found"] and out["data_rows"] == 4 and out["unmapped_columns"] == []
    assert (rep.accepted, rep.rejected_county, rep.unknown_status) == (2, 2, 0)    # Orleans and a blank county are refused
    assert [(r.county, r.case_no, r.source_status_text, r.provenance["normalized_status"]) for r in recs] == [
        ("Jefferson", "00200001", "Available", "AVAILABLE_FOR_SALE"), ("Mobile", "00200002", "Sold", "SOLD")]
    assert all(r.provenance["county"] == "row's own county column" for r in recs)
    assert recs[0].owner_name == "ALPHA A"                                          # "Name in which assessed" header
    # Queried for Mobile: the blank-county row takes the query; the Jefferson row keeps its own county and is counted.
    recs, rep, _ = ala.parse_search_results_html(CFG, STATEWIDE, retrieved_at=T, default_county="Mobile")
    assert [(r.county, r.case_no) for r in recs] == [("Jefferson", "00200001"), ("Mobile", "00200002"), ("Mobile", "00200004")]
    assert (rep.county_mismatch, rep.rejected_county, rep.unknown_status) == (1, 1, 1)
    assert recs[2].source_status_text == "Pending review" and recs[2].provenance["normalized_status"] == "UNKNOWN"
    with pytest.raises(ValueError, match="67 counties"):
        ala.parse_rows(CFG, [], retrieved_at=T, default_county="Orleans")


def test_h04_outcomes_nothing_is_complete_or_empty_until_the_parser_is_fixture_validated():
    url = ala.county_results_url(CFG, "02")
    # Rows, unverified parser -> INCOMPLETE (observed, not asserted complete).
    recs, rep, out = ala.parse_search_results_html(CFG, AUTAUGA, retrieved_at=T, base_url=url, default_county="Autauga")
    oc = ala.classify_outcome(CFG, "Autauga", recs, rep, out, url=url)
    assert (oc.status, oc.category, oc.row_count, oc.unmapped_columns) == ("INCOMPLETE", "UNKNOWN", 5, ("Year Sold",))
    assert ala.classify_outcome(_validated(), "Autauga", recs, rep, out, url=url).status == "COMPLETE"
    # An empty phrase -> UNCONFIRMED_EMPTY until validated, then EMPTY/empty_marker.
    recs, rep, out = ala.parse_search_results_html(CFG, EMPTY, retrieved_at=T, base_url=url, default_county="Baldwin")
    assert recs == [] and out["empty_marker"] and not out["header_table_found"]
    assert ala.classify_outcome(CFG, "Baldwin", recs, rep, out).category == "UNCONFIRMED_EMPTY"
    v = ala.classify_outcome(_validated(), "Baldwin", recs, rep, out)
    assert (v.status, v.empty_signal) == ("EMPTY", "empty_marker")
    # No table, no phrase -> PARSE_NO_TABLE either way.
    recs, rep, out = ala.parse_search_results_html(CFG, NOTABLE, retrieved_at=T, base_url=url, default_county="Baldwin")
    assert ala.classify_outcome(CFG, "Baldwin", recs, rep, out).category == "PARSE_NO_TABLE"
    assert ala.classify_outcome(_validated(), "Baldwin", recs, rep, out).category == "PARSE_NO_TABLE"
    # A recognised table whose every row is rejected -> PARSE_FORMAT_CHANGE, never EMPTY.
    junk = "<table><tr><th>CS Number</th><th>Name</th></tr><tr><td>PENDING</td><td>X</td></tr></table>"
    recs, rep, out = ala.parse_search_results_html(CFG, junk, retrieved_at=T, base_url=url, default_county="Baldwin")
    assert rep.rejected_identifier == 1 and ala.classify_outcome(_validated(), "Baldwin", recs, rep, out).category == "PARSE_FORMAT_CHANGE"
    # A recognised header with zero rows -> UNCONFIRMED_EMPTY until validated, then EMPTY/empty_table.
    bare = "<table><tr><th>CS Number</th><th>Name</th></tr></table>"
    recs, rep, out = ala.parse_search_results_html(CFG, bare, retrieved_at=T, base_url=url, default_county="Baldwin")
    assert ala.classify_outcome(CFG, "Baldwin", recs, rep, out).category == "UNCONFIRMED_EMPTY"
    assert ala.classify_outcome(_validated(), "Baldwin", recs, rep, out).empty_signal == "empty_table"
    # Every category used is one the status file accepts.
    for cat in ("UNKNOWN", "UNCONFIRMED_EMPTY", "PARSE_NO_TABLE", "PARSE_FORMAT_CHANGE"):
        assert cat in ERROR_CATEGORIES


# ==================== 3. harvest rows, provenance and the lifecycle ====================


def test_l01_harvest_row_shape_and_the_lifecycle_s_reading_of_it():
    url = ala.county_results_url(CFG, "01")
    recs, _, _ = ala.parse_search_results_html(CFG, AUTAUGA, retrieved_at=T, base_url=url, default_county="Autauga")
    row = ala.to_harvest_row(recs[0])
    assert row["state"] == "AL" and row["source"] == "laft" and row["county"] == "Autauga" and row["case_no"] == "00123456"
    assert row["parcel"] == "12-34-56-0-000-001.000" and row["owner_name"] == "DOE JOHN & JANE"
    assert row["bid"] == "" and row["bid_kind"] == "QUOTED_ON_APPLICATION" and row["url_auction"] == url
    assert row["purchase_url_kind"] == "application_form" and row["inventory_type"] == "STATE_HELD_TAX_LAND"
    assert "address" not in row and "legal_desc" not in row and "list_as_of" not in row    # absent stays absent
    assert row["otc_provenance"]["adapter"] == "alabama" and row["otc_provenance"]["identifier_shape"] == "d8"
    assert L.identity_key(row) == ("Autauga", "00123456")
    # Amount: NOT_PUBLISHED is the storable truth until 020; the harvester's reason survives once storable.
    assert L.amount_of(row) == (None, "NOT_PUBLISHED")
    assert L.amount_of(row, storable_kinds=tuple(L.DB_AMOUNT_KINDS) + ("QUOTED_ON_APPLICATION",)) == (None, "QUOTED_ON_APPLICATION")
    assert L.amount_of({"bid": "", "bid_kind": "OPENING_BID"}) == (None, "NOT_PUBLISHED")           # FL rows unchanged
    assert L.amount_of({"bid": "1500", "bid_kind": "FIXED_PURCHASE_PRICE"}) == (1500.0, "FIXED_PURCHASE_PRICE")
    # Purchase path: the row's own application link is taken; the list page never is.
    p_url, p_kind, basis = L.purchase_path_of(row, list_url=url, document_url=None, source_id="al_ador_state_land", county="Autauga", registry_paths={})
    assert p_url == row["purchase_url"] and p_kind == "application_form" and "published by the source for this property" in basis
    # A record with the model's new owner_name round-trips; a record without one adds no key.
    from harvesters.otc.model import OtcRecord
    from harvesters.otc import SourceAuthority
    plain = OtcRecord(state="FL", county="Marion", case_no="1", source_id="s", source_authority=SourceAuthority.GOVERNMENT_DIRECT,
                      inventory_type=InventoryType.POST_SALE_FIXED_PRICE, retrieved_at=T)
    assert "owner_name" not in plain.to_properties_row() and plain.owner_name is None
    named = OtcRecord(state="FL", county="Marion", case_no="1", source_id="s", source_authority=SourceAuthority.GOVERNMENT_DIRECT,
                      inventory_type=InventoryType.POST_SALE_FIXED_PRICE, retrieved_at=T, owner_name="X")
    assert named.to_properties_row()["owner_name"] == "X"


def test_l02_lifecycle_gates_are_scoped_to_the_state_county_names_repeat_across_states():
    fl = {"county": "Escambia", "harvester": "fl_laft_pdfs", "status": "COMPLETE", "checked_at": T.isoformat(), "rowCount": 3, "state": "FL"}
    al = {"county": "Escambia", "harvester": "al_ador_state_land", "status": "FAILED", "checked_at": T.isoformat(), "state": "AL",
          "error_category": "TRANSPORT_HTTP_403_BLOCKED"}
    now = T.timestamp()
    # Unscoped: the weakest status wins (the old behaviour) - Alabama's failure would gate Florida's Escambia.
    # (A TRANSPORT_ failure reads as SOURCE_UNAVAILABLE since 2026-09-30 - the same fail-closed weight as FAILED.)
    assert L.county_gates([fl, al], [], now=now)["Escambia"]["status"] == "SOURCE_UNAVAILABLE"
    # Scoped: each state sees only its own entries; an entry without a state is Florida's.
    assert L.county_gates([fl, al], [], now=now, state="FL")["Escambia"]["status"] == "COMPLETE"
    assert L.county_gates([fl, al], [], now=now, state="AL")["Escambia"]["status"] == "SOURCE_UNAVAILABLE"
    assert "Escambia" not in L.county_gates([al], [], now=now, state="FL")
    # An entry that names no state at all (hand-written fixtures; every recorder writes one) is kept for any state.
    legacy = {"county": "Escambia", "harvester": "x", "status": "EMPTY", "checked_at": T.isoformat(), "empty_signal": "empty_table"}
    assert L.county_gates([legacy], [], now=now, state="AL")["Escambia"]["status"] == "EMPTY"
    # The lifecycle still refuses Alabama outright, before any query.
    with pytest.raises(ValueError, match="not activated"):
        L.lifecycle_inventory("AL")
    assert L.load_expected_units(csr.REGISTRY_PATH, "AL") == [] and L.load_registry_purchase_paths(csr.REGISTRY_PATH, "AL") == {}
    r = subprocess.run([sys.executable, str(REPO / "scripts/laft_lifecycle.py"), "--state", "AL", "--dry-run"],
                       capture_output=True, text=True, cwd=REPO, env={"PATH": "/usr/bin:/bin", "HTTPS_PROXY": "http://127.0.0.1:9"})
    assert r.returncode == 2 and "not activated" in r.stdout


def test_l03_even_an_activated_alabama_cannot_stamp_the_inventory_type_before_migration_020():
    active = StateConfig(code="AL", name="Alabama", publishing_units=("STATE", "COUNTY"), production_inventory_types=frozenset({"STATE_HELD_TAX_LAND"}),
                         lifecycle_inventory_type="STATE_HELD_TAX_LAND", lifecycle_inventory_basis="fixture", production=True,
                         activation=states.ALL_REQUIREMENTS)
    with states.registered(active):
        assert states.is_activated("AL")
        with pytest.raises(ValueError, match="not storable"):
            L.lifecycle_inventory("AL")
    assert not states.is_activated("AL") and states.PRODUCTION_STATES == frozenset({"FL", "TX"})


# ==================== 4. the gated live flow ====================


class _Fetcher:
    def __init__(self, pages: dict[str, str], fail: dict[str, Exception] | None = None) -> None:
        self.pages, self.fail, self.calls = pages, fail or {}, []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        if url in self.fail:
            raise self.fail[url]
        return self.pages[url]


class _Timeout(Exception):
    pass


def test_x01_harvest_refuses_before_the_first_request_whatever_the_configuration_claims():
    f = _Fetcher({})
    with pytest.raises(RuntimeError, match="not activated"):
        ala.harvest(CFG, f, retrieved_at=T)
    from dataclasses import replace
    claims = replace(CFG, live_verified=True, identifier_format_established=True, parser_fixture_validated=True, enabled=True)
    with pytest.raises(RuntimeError, match="not activated"):
        ala.harvest(claims, f, retrieved_at=T)
    assert f.calls == []
    # Activated state but an unverified / disabled source: still refused, still no request.
    active = StateConfig(code="AL", name="Alabama", publishing_units=("STATE", "COUNTY"), production_inventory_types=frozenset({"STATE_HELD_TAX_LAND"}),
                         lifecycle_inventory_type=None, production=True, activation=states.ALL_REQUIREMENTS)
    with states.registered(active):
        assert ala.can_run(CFG).reason == "source configuration is not enabled"
        with pytest.raises(RuntimeError, match="not enabled"):
            ala.harvest(CFG, f, retrieved_at=T)
        assert ala.can_run(replace(claims, list_url=None, application_url=None, application_url_kind=None)).reason == "no source-of-record URL configured"
    assert f.calls == [] and not states.is_activated("AL")


def test_x02_live_flow_on_the_synthetic_pages_one_page_per_county_failures_isolated_messages_dropped():
    from dataclasses import replace
    claims = replace(CFG, live_verified=True, identifier_format_established=True, parser_fixture_validated=True, enabled=True)
    urls = {c: ala.county_results_url(claims, v) for c, v in ala.parse_county_options(LANDING)[0].items()}
    pages = {ala.ADOR_SEARCH_URL: LANDING, urls["Autauga"]: AUTAUGA, urls["Baldwin"]: EMPTY, urls["Jefferson"]: STATEWIDE,
             urls["Mobile"]: NOTABLE, urls["St. Clair"]: AUTAUGA, urls["Winston"]: AUTAUGA}
    f = _Fetcher(pages, fail={urls["Winston"]: _Timeout("secret request body must not leak")})
    active = StateConfig(code="AL", name="Alabama", publishing_units=("STATE", "COUNTY"), production_inventory_types=frozenset({"STATE_HELD_TAX_LAND"}),
                         lifecycle_inventory_type=None, production=True, activation=states.ALL_REQUIREMENTS)
    with states.registered(active):
        assert ala.can_run(claims).allowed
        res = ala.harvest(claims, f, retrieved_at=T)
    assert not states.is_activated("AL")
    assert f.calls[0] == ala.ADOR_SEARCH_URL and len(f.calls) == 7 and res.requests == 6      # the failed fetch is not a completed request
    assert res.counties_offered == 6 and res.unmatched_options == ["Jefferson - Bessemer Division", "All Counties"]
    by = {oc.county: oc for oc in res.outcomes}
    assert list(by) == ["Autauga", "Baldwin", "Jefferson", "Mobile", "St. Clair", "Winston"]
    assert (by["Autauga"].status, by["Autauga"].row_count, by["Autauga"].url) == ("COMPLETE", 5, urls["Autauga"])
    assert (by["Baldwin"].status, by["Baldwin"].empty_signal) == ("EMPTY", "empty_marker")
    assert (by["Mobile"].status, by["Mobile"].category) == ("INCOMPLETE", "PARSE_NO_TABLE")
    assert (by["Winston"].status, by["Winston"].category, by["Winston"].reason) == ("FAILED", "TRANSPORT_TIMEOUT", "_Timeout")
    assert "secret" not in json.dumps([vars(oc) | {"report": None} for oc in res.outcomes])
    # The statewide-shaped page queried for Jefferson: the Mobile row keeps its own county (counted), Orleans refused.
    jef = by["Jefferson"]
    assert jef.status == "COMPLETE" and jef.row_count == 3 and jef.report.county_mismatch == 1 and jef.report.rejected_county == 1
    assert sorted({r.county for r in res.records}) == ["Autauga", "Jefferson", "Mobile", "St. Clair"]
    assert len(res.records) == 5 + 3 + 5 and all(r.validate() == [] for r in res.records)
    # A county subset fetches only those pages.
    f2 = _Fetcher(pages)
    with states.registered(active):
        res2 = ala.harvest(claims, f2, retrieved_at=T, counties=["Baldwin", "Nowhere"])
    assert f2.calls == [ala.ADOR_SEARCH_URL, urls["Baldwin"]] and [oc.county for oc in res2.outcomes] == ["Baldwin"]


# ==================== 5. the harvester script ====================


def _run(args, env_extra=None):
    env = {"PATH": "/usr/bin:/bin", "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=REPO, env=env)


def test_s01_script_fixture_mode_writes_rows_status_and_a_counts_only_report(tmp_path):
    out, status, report = tmp_path / "rows.json", tmp_path / "status.json", tmp_path / "report.json"
    r = _run(["--fixture", f"Autauga={FIX / 'ador_search_results_autauga_SYNTHETIC.html'}",
              "--fixture", f"Baldwin={FIX / 'ador_search_results_empty_SYNTHETIC.html'}",
              "--fixture", str(FIX / "ador_search_results_statewide_SYNTHETIC.html"),
              "--out", str(out), "--status", str(status), "--report", str(report)])
    assert r.returncode == 0, r.stdout + r.stderr
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert len(rows) == 7 and all(row["state"] == "AL" and row["bid_kind"] == "QUOTED_ON_APPLICATION" for row in rows)
    assert sorted({row["county"] for row in rows}) == ["Autauga", "Jefferson", "Mobile"]
    entries = load_status(status)
    assert [(e["county"], e["state"], e["status"], e["error_category"], e["harvester"]) for e in entries] == [
        ("Autauga", "AL", "INCOMPLETE", "UNKNOWN", "al_ador_state_land"),
        ("Baldwin", "AL", "INCOMPLETE", "UNCONFIRMED_EMPTY", "al_ador_state_land"),
        ("Jefferson", "AL", "INCOMPLETE", "UNKNOWN", "al_ador_state_land"),
        ("Mobile", "AL", "INCOMPLETE", "UNKNOWN", "al_ador_state_land")]
    assert all(e["source_url"].startswith("file://") for e in entries)
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["mode"] == "fixture" and rep["rows"] == 7 and rep["requests"] == 0 and rep["parser_fixture_validated"] is False
    assert rep["parse_counters"]["accepted"] == 7 and rep["unmapped_columns"] == ["Year Sold"] and rep["status_counts"] == {"INCOMPLETE": 4}
    # Public log discipline: no CS number, parcel or name in stdout or the report.
    public = r.stdout + report.read_text(encoding="utf-8")
    for secret in ("00123456", "12-34-56-0-000-001.000", "DOE JOHN", "ALPHA A"):
        assert secret not in public
    # Its own status file, never the FL one; a fixture county must be a real county.
    assert ala.STATUS_FILE_NAME != "harvest_laft_status.json"
    bad = _run(["--fixture", f"Orleans={FIX / 'ador_search_results_empty_SYNTHETIC.html'}", "--out", str(out), "--status", str(status), "--report", str(report)])
    assert bad.returncode != 0 and "not one of the 67" in bad.stderr


def test_s02_script_live_mode_refuses_with_zero_requests_and_never_loads_an_http_client(tmp_path):
    r = _run(["--out", str(tmp_path / "x.json"), "--status", str(tmp_path / "s.json"), "--report", str(tmp_path / "r.json")])
    assert r.returncode == 2 and "not activated" in r.stdout and "0 requests made" in r.stdout
    assert not (tmp_path / "x.json").exists() and not (tmp_path / "s.json").exists()
    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any((getattr(n, "module", "") or "").startswith("requests") or any(a.name == "requests" for a in n.names) for n in top)
    assert "import requests" in src                                                # inside live_fetcher() only
    # Not wired anywhere: no workflow names the script or its output.
    for wf in (REPO / ".github/workflows").glob("*.yml"):
        assert "harvest_alabama" not in wf.read_text(encoding="utf-8"), wf.name


# ==================== 6. registry and gates ====================


def test_g01_registry_row_mirrors_the_adapter_and_every_gate_still_refuses_it():
    rows = csr.load_registry()
    al = csr.lookup(rows, "AL", STATEWIDE_UNIT)
    assert al is not None and al.canonical_url == CFG.list_url and al.purchase_url == CFG.application_url
    assert al.purchase_url_kind == CFG.application_url_kind.value and al.publishing_unit_name == CFG.publishing_unit_name
    assert al.amount_kind == CFG.amount_kind.value and al.inventory_type == CFG.inventory_type.value
    assert al.verification_status == "SEARCH_EVIDENCE_ONLY" and al.governance_status == "TERMS_NOT_VERIFIED"
    assert al.access_method == "HTTP_GET_HTML" and al.machine_format == "PORTAL" and al.completeness_status == "UNKNOWN"
    assert al.harvester == "" and not al.is_production and not al.runnable
    d = evaluate_source(al)
    assert not d.allowed and d.layer == "state_activation"
    assert csr.validate_registry(rows) == []
    assert csr.production_rows(rows, "AL") == [] and len([r for r in rows if r.state in ("FL", "TX") and not (r.ledger_set and "AVAILABLE" not in r.ledger_set)]) == 109
    # The generator and the committed CSV agree (the AL row included).
    import importlib.util
    spec = importlib.util.spec_from_file_location("bcsr", REPO / "scripts/build_county_source_registry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.render(mod.build_rows()) == csr.REGISTRY_PATH.read_text(encoding="utf-8")
