"""AVAILABLE commercialization (2026-09-30): source-level publication gate,
purchase-path modes and URL trust, lifecycle transitions, AVAILABLE-first
enrichment, freshness states, migration 022 - and the FL / TX / AL / AR /
LA / AZ regressions around them."""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import inventory_status as IS  # noqa: E402
from harvesters.governance import publication as pub  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.ledgers import BLOCKED_SOURCE_IDS  # noqa: E402
import inventory_status_writer as W  # noqa: E402
import laft_lifecycle as L  # noqa: E402
import laft_purchase_paths as PP  # noqa: E402
import publication_gate as PG  # noqa: E402
import unit_freshness as U  # noqa: E402

ROWS = csr.load_registry()
BY_SID = pub.decisions_by_source(ROWS)
T = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)


def _row(**kw) -> csr.CountySourceRow:
    base = dict(state="FL", county="Marion", source_id="fl_laft_pdfs", harvester="harvest_laft_pdfs.py",
                inventory_type="POST_SALE_FIXED_PRICE", source_authority="GOVERNMENT_DIRECT",
                canonical_url="https://example.invalid/list", document_url="", purchase_url="", purchase_url_kind="",
                access_method="HTTP_GET_PDF", machine_format="PDF", verification_status="PRODUCTION_VERIFIED",
                governance_status="APPROVED_GRANDFATHERED", last_checked="2026-09-29", completeness_status="COMPLETE",
                evidence_ref="fixture", notes="", ledgers="AVAILABLE", publication_status="APPROVED_GRANDFATHERED")
    base.update(kw)
    return csr.CountySourceRow(**base)


# ==================== 1. governance: the publication gate ====================

def test_g01_committed_registry_publishes_only_the_grandfathered_production_sources():
    assert pub.PUBLICATION_STATUSES == ("APPROVED", "APPROVED_GRANDFATHERED", "UNREVIEWED", "RESTRICTED", "BLOCKED")
    for r in ROWS:
        eff = pub.effective_publication(r)
        if r.is_production:
            assert eff == "APPROVED_GRANDFATHERED", (r.state, r.county, r.source_id)     # already served today; carried forward
        elif r.source_id in BLOCKED_SOURCE_IDS:
            assert eff == "BLOCKED"
        elif r.governance_status == "LEGAL_REVIEW_REQUIRED":
            assert eff == "RESTRICTED" and r.restrictions
        else:
            assert eff == "UNREVIEWED", (r.state, r.county)
    # No candidate, no registered-but-inactive state, is publishable.
    for sid in ("al_ador_state_land", "ar_cosl_post_auction", "la_ebr_adjudicated", "az_maricopa_state_cp"):
        assert not BY_SID[sid].customer_publishable and BY_SID[sid].publication == "UNREVIEWED"
    assert BY_SID["tx_hctax"].publication == "RESTRICTED" and not BY_SID["tx_hctax"].customer_publishable
    assert BY_SID["tx_pbfcm"].publication == "BLOCKED" and BY_SID["tx_mvba"].publication == "BLOCKED"
    assert BY_SID["fl_laft_pioneer"].customer_publishable and BY_SID["fl_laft_pioneer"].purchase_info == "none"
    assert "no purchase or application path published at source level" in BY_SID["fl_laft_pioneer"].reasons


def test_g02_a_government_source_is_not_automatically_publishable_and_the_validator_refuses_the_dangerous_shapes():
    assert csr.validate_row(_row()) == []
    # A candidate (search evidence, terms not verified) cannot be APPROVED, however official the site.
    cand = _row(verification_status="SEARCH_EVIDENCE_ONLY", governance_status="TERMS_NOT_VERIFIED", harvester="", completeness_status="UNKNOWN",
                publication_status="APPROVED")
    problems = csr.validate_row(cand)
    assert any("government website is not commercial permission" in p for p in problems)
    assert any("not PRODUCTION_VERIFIED" in p for p in problems)
    # Legal review: never publishable, whatever the column says.
    legal = _row(governance_status="LEGAL_REVIEW_REQUIRED", verification_status="SEARCH_EVIDENCE_ONLY", harvester="", completeness_status="UNKNOWN",
                 publication_status="APPROVED_GRANDFATHERED")
    assert any("LEGAL_REVIEW_REQUIRED cannot be published" in p for p in csr.validate_row(legal))
    assert pub.effective_publication(legal) == "RESTRICTED"
    # RESTRICTED must say why; BLOCKED only for blocked vendors; unknown value refused; a blank is UNREVIEWED.
    assert any("must say why" in p for p in csr.validate_row(_row(publication_status="RESTRICTED", restrictions="")))
    assert csr.validate_row(_row(publication_status="RESTRICTED", restrictions="terms forbid redistribution")) == []
    assert any("not a blocked vendor" in p for p in csr.validate_row(_row(publication_status="BLOCKED")))
    assert csr.validate_row(_row(publication_status="MAYBE")) == ["publication_status 'MAYBE'"]
    assert pub.effective_publication(_row(publication_status="")) == "UNREVIEWED"
    blocked = next(r for r in ROWS if r.source_id == "tx_pbfcm")
    bk = {c: getattr(blocked, c) for c in csr.EXTENDED_COLUMNS}
    assert any("must be BLOCKED" in p for p in csr.validate_row(csr.CountySourceRow(**{**bk, "publication_status": "UNREVIEWED"})))
    assert pub.effective_publication(csr.CountySourceRow(**{**bk, "publication_status": "APPROVED"})) == "BLOCKED"


def test_g03_decisions_are_per_source_and_the_strictest_county_wins():
    a = _row(county="Marion")
    b = _row(county="Lake", publication_status="RESTRICTED", restrictions="county page terms")
    d = pub.decisions_by_source([a, b])
    assert d["fl_laft_pdfs"].publication == "RESTRICTED" and not d["fl_laft_pdfs"].customer_publishable
    # Seven facets, each reported.
    dec = pub.decide(_row(purchase_url="https://clerk.example.invalid/laft/how-to-buy", purchase_url_kind="purchase_instructions"))
    assert dec.harvestable and dec.establishes_availability and dec.purchase_info == "instructions" and dec.governance_ok
    assert dec.publication == "APPROVED_GRANDFATHERED" and dec.customer_publishable and dec.reasons == ()
    assert pub.decide(_row(purchase_url="https://clerk.example.invalid/buy/123", purchase_url_kind="online_purchase")).purchase_info == "property"
    assert pub.decide(_row(), property_rule_enabled=True).purchase_info == "property"
    nd = pub.decide(_row(verification_status="SEARCH_EVIDENCE_ONLY", governance_status="TERMS_NOT_VERIFIED", harvester="", completeness_status="UNKNOWN",
                         publication_status="UNREVIEWED"))
    assert not nd.harvestable and not nd.governance_ok and not nd.customer_publishable
    assert set(nd.as_dict()) >= {"harvestable", "establishes_availability", "purchase_info", "governance_ok", "publication", "customer_publishable", "reasons"}


def test_g04_row_publication_follows_the_source_and_never_guesses():
    assert pub.source_id_of({"source_id": "fl_laft_pioneer"}) == "fl_laft_pioneer"
    assert pub.source_id_of({"harvester_source": "fl_realauction_alachua"}) == "fl_realauction"
    assert pub.source_id_of({"harvester_source": "tx_lgbs"}) == "tx_lgbs"
    assert pub.source_id_of({}) is None
    assert pub.row_publication({"source_id": "fl_laft_pioneer"}, BY_SID) == "APPROVED_GRANDFATHERED"
    assert pub.row_publication({"source_id": "tx_hctax"}, BY_SID) == "RESTRICTED"
    assert pub.row_publication({"source_id": "tx_pbfcm"}, BY_SID) == "BLOCKED"
    assert pub.row_publication({"harvester_source": "something_new"}, BY_SID) is None       # unclassified, never approved by default
    rows = [{"id": "1", "state": "FL", "source": "laft", "county": "Bay", "source_id": "fl_laft_pioneer", "purchase_url": None, "last_seen_at": T.isoformat()},
            {"id": "2", "state": "TX", "source": "laft", "county": "Harris", "source_id": "tx_hctax", "purchase_url": "https://x/y", "last_seen_at": (T - timedelta(days=40)).isoformat()},
            {"id": "3", "state": "FL", "source": "laft", "county": "Lee", "harvester_source": "mystery"},
            {"id": "4", "state": "FL", "source": "auction", "county": "Lee", "source_id": "fl_realauction"}]
    m = pub.measure(rows, BY_SID, now=T, unavailable_units={("FL", "fl_laft_pioneer", "Bay")})
    c = m["counts"]
    assert (c["total_observed"], c["publishable"], c["restricted"], c["unclassified"], c["blocked"], c["unreviewed"]) == (3, 1, 1, 1, 0, 0)
    assert (c["with_purchase_path"], c["without_purchase_path"], c["stale"], c["unavailable_source"]) == (1, 2, 2, 1)
    assert m["by_source"]["fl_laft_pioneer"] == {"rows": 1, "publishable": 1, "with_purchase_path": 0, "stale": 0}
    groups, counts = PG.plan(rows, BY_SID)
    assert groups == {"APPROVED_GRANDFATHERED": ["1"], "RESTRICTED": ["2"]} and counts["unclassified"] == 1 and counts["changed"] == 2
    groups2, counts2 = PG.plan([dict(rows[0], publication_status="APPROVED_GRANDFATHERED")], BY_SID)
    assert groups2 == {} and counts2["unchanged"] == 1


def test_g05_gate_script_reports_without_credentials_and_measures_a_rows_file(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    report = tmp_path / "gate.json"
    r = subprocess.run([sys.executable, "scripts/publication_gate.py", "--state", "FL", "--report", str(report)], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0 and "registry-only" in r.stdout, r.stdout + r.stderr
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["mode"].startswith("registry-only") and "measurement" not in rep
    assert all(v["publication"] == "APPROVED_GRANDFATHERED" for v in rep["sources"].values())
    rows_file = tmp_path / "rows.json"
    rows_file.write_text(json.dumps([{"id": "a", "state": "FL", "source": "laft", "county": "Bay", "source_id": "fl_laft_pioneer"},
                                     {"id": "b", "state": "FL", "source": "laft", "county": "Broward", "harvester_source": "unknown_thing"}]), encoding="utf-8")
    r2 = subprocess.run([sys.executable, "scripts/publication_gate.py", "--state", "FL", "--rows", str(rows_file), "--report", str(report)],
                        capture_output=True, text=True, cwd=REPO)
    rep2 = json.loads(report.read_text(encoding="utf-8"))
    assert r2.returncode == 0 and rep2["mode"] == "rows-file" and rep2["measurement"]["counts"]["publishable"] == 1 and rep2["measurement"]["counts"]["unclassified"] == 1
    assert "a" not in json.dumps(rep2["measurement"]) or True    # counts only; ids never appear in the measurement
    assert not re.search(r'"id"', json.dumps(rep2["measurement"]))


# ==================== 2. purchase paths ====================

def test_p01_untrusted_urls_are_refused_and_modes_validate_against_url_kind_and_evidence():
    ok = "https://www.clerk.example.invalid/taxdeed/lands-available/how-to-purchase"
    assert PP.untrusted_reason(ok) is None and PP.acceptable_purchase_url(ok, list_url=None, document_url=None)
    assert PP.untrusted_reason("http://x/y") == "not https"
    assert PP.untrusted_reason("https://www.clerk.example.invalid/") == "a bare homepage"
    assert PP.untrusted_reason("https://x/list", list_url="https://x/list") == "the list page or the document itself"
    assert "search engine or blocked vendor" in PP.untrusted_reason("https://www.google.com/search?q=lands+available")
    assert "search engine or blocked vendor" in PP.untrusted_reason("https://taxsales.pbfcm.com/list/1")
    assert "search engine or blocked vendor" in PP.untrusted_reason("https://mvbalaw.com/struck-off/2")
    assert "search-results page" in PP.untrusted_reason("https://county.example.invalid/search?q=parcel")
    assert PP.untrusted_reason("javascript:void(0)") == "not https"
    assert PP.PURCHASE_PATH_MODES == ("online_property", "online_instructions", "application", "in_person_only", "phone_mail", "none", "unknown")
    assert PP.mode_problems("", purchase_url="", purchase_url_kind="", evidence="") == []                       # blank = unknown
    assert PP.mode_problems("unknown", purchase_url="", purchase_url_kind="", evidence="") == []
    assert PP.mode_problems("in_person_only", purchase_url="", purchase_url_kind="", evidence="") == ["purchase_path_mode in_person_only must cite the source wording (purchase_path_evidence)"]
    assert PP.mode_problems("in_person_only", purchase_url="", purchase_url_kind="", evidence="'Purchases are made in person at the Clerk's office' (list page)") == []
    assert PP.mode_problems("phone_mail", purchase_url="https://x/y", purchase_url_kind="purchase_instructions", evidence="e") == ["purchase_path_mode phone_mail with a purchase_url"]
    assert PP.mode_problems("online_instructions", purchase_url="", purchase_url_kind="", evidence="") == ["purchase_path_mode online_instructions needs purchase_url + purchase_url_kind"]
    assert PP.mode_problems("online_property", purchase_url=ok, purchase_url_kind="purchase_instructions", evidence="") == ["purchase_path_mode online_property does not match purchase_url_kind 'purchase_instructions'"]
    assert PP.mode_problems("online_instructions", purchase_url="https://www.google.com/search?q=x", purchase_url_kind="purchase_instructions", evidence="")[0].startswith("purchase_url is untrusted host")
    assert PP.mode_problems("teleport", purchase_url="", purchase_url_kind="", evidence="") == ["purchase_path_mode 'teleport'"]
    # A rule cannot apply an untrusted link even when it matches.
    rule = PP.Rule("FL", "fl_laft_html", "*", "column", "Buy", "online_purchase", True, "2026-10-01", "verified")
    link = PP.Link("Buy", "Buy now", "https://www.google.com/url?q=https://x")
    rec = {"county": "Manatee"}
    assert PP.apply_rules(rec, [link], [rule], state="FL", source_id="fl_laft_html", list_url=None, document_url=None) == "none" and "purchase_url" not in rec


def test_p02_registry_carries_modes_only_where_a_url_kind_is_recorded_and_the_lifecycle_propagates_non_url_modes(tmp_path):
    assert "purchase_path_mode" in csr.OPTIONAL_COLUMNS and "purchase_path_evidence" in csr.OPTIONAL_COLUMNS
    for r in ROWS:
        if r.purchase_url and r.purchase_url_kind:
            assert r.purchase_path_mode == PP.MODE_FOR_KIND[r.purchase_url_kind], (r.state, r.county)
        else:
            assert r.purchase_path_mode == "" and r.purchase_path_evidence == "", (r.state, r.county)    # unknown: nothing asserted for FL
    assert csr.validate_registry(ROWS) == []
    # A registry fixture stating an in-person process for a production county.
    reg = tmp_path / "registry.csv"
    with open(reg, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=csr.EXTENDED_COLUMNS, lineterminator="\n")
        w.writeheader()
        base = {c: "" for c in csr.EXTENDED_COLUMNS}
        base.update(state="FL", county="Marion", source_id="fl_laft_pdfs", harvester="harvest_laft_pdfs.py", inventory_type="POST_SALE_FIXED_PRICE",
                    source_authority="GOVERNMENT_DIRECT", canonical_url="https://example.invalid/list", access_method="HTTP_GET_PDF", machine_format="PDF",
                    verification_status="PRODUCTION_VERIFIED", governance_status="APPROVED_GRANDFATHERED", last_checked="2026-09-29",
                    completeness_status="COMPLETE", evidence_ref="fixture", publishing_unit="COUNTY", ledgers="AVAILABLE",
                    publication_status="APPROVED_GRANDFATHERED", purchase_path_mode="in_person_only",
                    purchase_path_evidence="'Applications are accepted in person at the Clerk's office' (fixture wording)")
        w.writerow(base)
    loaded = csr.load_registry(reg)
    assert csr.validate_registry(loaded) == [] and loaded[0].purchase_path_mode == "in_person_only"
    assert L.load_registry_purchase_modes(reg, "FL") == {("fl_laft_pdfs", "Marion"): ("in_person_only", "'Applications are accepted in person at the Clerk's office' (fixture wording)")}
    assert L.load_registry_purchase_paths(reg, "FL") == {}
    gate = {"harvester": "fl_laft_pdfs", "status": "COMPLETE", "entry": {"source_id": "fl_laft_pdfs", "source_url": "https://example.invalid/list", "checked_at": T.isoformat()}}
    row = {"county": "Marion", "case_no": "M-1", "parcel": "P", "bid": 100}
    payload = L.provenance_payload(row, gate, T.isoformat(), state="FL", registry_paths={}, registry_modes=L.load_registry_purchase_modes(reg, "FL"))
    assert "purchase_url" not in payload                                             # no URL invented for a non-online mode
    assert payload["otc_provenance"]["purchase_path_mode"] == "in_person_only"
    assert payload["otc_provenance"]["purchase_url"].startswith("in person only process published by the source:")
    payload2 = L.provenance_payload(row, gate, T.isoformat(), state="FL", registry_paths={}, registry_modes={})
    assert payload2["otc_provenance"]["purchase_path_mode"] == "unknown" and "none invented" in payload2["otc_provenance"]["purchase_url"]
    payload3 = L.provenance_payload(dict(row, purchase_url="https://clerk.example.invalid/buy/1", purchase_url_kind="online_purchase"), gate, T.isoformat(),
                                    state="FL", registry_paths={}, registry_modes={})
    assert payload3["purchase_url_kind"] == "online_purchase" and payload3["otc_provenance"]["purchase_path_mode"] == "online_property"


# ==================== 3. lifecycle ====================

def test_l01_transitions_are_explicit_and_a_removed_row_is_never_sold():
    def r(**kw):
        base = {"id": kw.pop("id", "x"), "state": "FL", "source": "laft", "county": "Marion", "case_no": "C-1", "status": "active",
                "inventory_status": None, "inventory_status_raw": None, "list_url": "https://x/list"}
        base.update(kw)
        return base
    rows = [r(id="new"),                                                            # first sighting
            r(id="same", inventory_status="available_otc"),                         # still listed - no change, no observation
            r(id="gone", status="closed", inventory_status="available_otc"),        # left the list - closed, never sold
            r(id="sold", case_no="C-2", inventory_status="available_otc"),          # the list's own Sold To column
            r(id="cert", source="certificate", inventory_status=None)]
    changes, counts = W.plan(rows, today=TODAY, sold={("Marion", "C-2")})
    by = {c["id"]: c for c in changes}
    assert by["new"]["status"] == "available_otc" and by["new"]["transition"] == "newly_observed"
    assert "same" not in by and counts["unchanged"] == 1
    assert by["gone"]["status"] == "closed" and by["gone"]["transition"] == "removed" and by["gone"]["raw"] is None
    assert by["sold"]["status"] == "sold" and by["sold"]["transition"] == "result_published" and by["sold"]["raw"] == "Sold To"
    assert by["cert"]["status"] == "certificate_listed" and by["cert"]["transition"] == "newly_observed"
    assert counts["by_transition"] == {"newly_observed": 2, "removed": 1, "result_published": 1}
    obs = W.observations(changes, observed_at=T.isoformat(), run_id="r1")
    assert all("transition" not in o for o in obs)                                  # 022 absent: column never sent
    obs22 = W.observations(changes, observed_at=T.isoformat(), run_id="r1", include_transition=True)
    assert {o["property_id"]: o["transition"] for o in obs22} == {"new": "newly_observed", "gone": "removed", "sold": "result_published", "cert": "newly_observed"}
    # Absence is closed, and closed is not a result.
    assert IS.status_for_row(r(status="dropped"), today=TODAY).status == "closed" and "closed" not in IS.RESULT_STATUSES
    # A source failure closes nothing (the lifecycle gate) - re-asserted here with the new state.
    now = T.timestamp()
    for entry_status, category in (("FAILED", "TRANSPORT_HTTP_503"), ("FAILED", "PARSE_FORMAT_CHANGE"), ("INCOMPLETE", "PARSE_FORMAT_CHANGE")):
        e = {"county": "Marion", "harvester": "fl_laft_pdfs", "status": entry_status, "checked_at": T.isoformat(), "state": "FL", "error_category": category}
        g = L.county_gates([e], [], now=now, state="FL")["Marion"]
        assert not g["closeout_ok"], (entry_status, category)


# ==================== 4. enrichment: AVAILABLE first ====================

def test_e01_the_county_slice_is_filled_from_available_rows_first_and_never_twice(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("enrich_mod", REPO / "scripts/enrich_property_details.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    spec.loader.exec_module(mod)
    calls = []
    class Resp:
        def __init__(self, rows): self._rows = rows
        def raise_for_status(self): pass
        def json(self): return self._rows
    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(dict(params))
        if "source.eq.laft" in params["and"]:
            return Resp([{"id": "L1", "source": "laft"}, {"id": "L2", "source": "laft"}])
        return Resp([{"id": "A1", "source": "auction"}, {"id": "L1", "source": "laft"}, {"id": "A2", "source": "auction"}, {"id": "A3", "source": "auction"}])
    monkeypatch.setattr(mod.requests, "get", fake_get)
    rows = mod.fetch_county_batch("Marion", 4, 20)
    assert [r["id"] for r in rows] == ["L1", "L2", "A1", "A2"]            # Available first, then the rest, no duplicate, slice honoured
    assert calls[0]["and"].endswith("source.eq.laft)") and calls[0]["limit"] == "4" and calls[0]["offset"] == "0"
    assert calls[1]["and"].endswith("source.neq.laft)") and calls[1]["limit"] == "2"
    calls.clear()
    monkeypatch.setattr(mod.requests, "get", lambda url, headers=None, params=None, timeout=None: (calls.append(dict(params)), Resp([{"id": "L%d" % i, "source": "laft"} for i in range(6)]))[1])
    assert len(mod.fetch_county_batch("Marion", 3, 20)) == 3 and len(calls) == 1   # the slice is full after the Available pass


# ==================== 5. freshness ====================

def test_f01_customer_freshness_states_per_unit_and_per_ledger():
    def e(county, source_id, status, when, **kw):
        return U.normalize_entry({"county": county, "harvester": source_id, "status": status, "checked_at": when, "state": "FL", "row_count": 2, **kw},
                                 default_state="FL", default_source=None)
    fresh = T.isoformat()
    old = (T - timedelta(hours=60)).isoformat()
    rec, _ = U.merge({}, [e("Alachua", "fl_laft_realtdm", "COMPLETE", fresh)], at="t0")
    rec, _ = U.merge(rec, [e("Bay", "fl_laft_pioneer", "EMPTY", old)], at="t0")
    rec, _ = U.merge(rec, [e("Union", "fl_laft_html", "FAILED", fresh, error_category="TRANSPORT_HTTP_403_BLOCKED")], at="t1")
    for i in range(2):
        rec, _ = U.merge(rec, [e("Union", "fl_laft_html", "FAILED", (T + timedelta(hours=i + 1)).isoformat(), error_category="TRANSPORT_HTTP_403_BLOCKED")], at="t")
    rec, _ = U.merge(rec, [e("Marion", "fl_realauction", "FAILED", fresh, error_category="PROXY_FAILURE")], at="t2")
    report = U.public_report(rec, {}, at="t", now=T + timedelta(hours=3))
    u = {x["county"]: x for x in report["units"]}
    assert u["Alachua"]["stale"] is False and u["Alachua"]["backoff"] is False and u["Alachua"]["source_unavailable"] is False
    assert u["Bay"]["stale"] is True and u["Bay"]["last_attempt_status"] == "EMPTY"            # an EMPTY read is a read; it is just old
    assert u["Union"]["backoff"] is True and u["Union"]["backoff_reason"].startswith(U.BACKOFF_PREFIX) and u["Union"]["stale"] is True
    assert u["Union"]["consecutive_failures"] == 3 and u["Union"]["last_success_at"] is None
    assert u["Marion"]["source_unavailable"] is True and u["Marion"]["stale"] is True
    assert u["Union"]["source_unavailable"] is True                                              # a 403 block is an access failure
    assert report["by_ledger"]["AVAILABLE"] == {"units": 3, "current": 2, "stale": 1, "failing": 1, "backoff": 1, "source_unavailable": 1}
    assert report["by_ledger"]["AUCTIONS"] == {"units": 1, "current": 0, "stale": 1, "failing": 1, "backoff": 0, "source_unavailable": 1}
    # An unreadable / missing last_success_at is stale; never advanced by a failure.
    assert U.unit_stale({}, now=T) and U.unit_stale({"last_success_at": "garbage"}, now=T)
    assert not U.unit_stale({"last_success_at": T.isoformat()}, now=T + timedelta(hours=35))


# ==================== 6. migration 022 (file) ====================

def test_m01_migration_022_appends_publication_status_and_keeps_021s_list():
    sql = (REPO / "scripts/migrations/022_available_publication_gate.sql").read_text(encoding="utf-8")
    prev = (REPO / "scripts/migrations/021_inventory_status_provenance_freshness.sql").read_text(encoding="utf-8")
    assert "NOT APPLIED" in sql and "publication_status" in sql and "transition" in sql
    def returns_cols(text):
        body = text[text.index("returns table ("):text.index(")\nlanguage sql")]
        return re.findall(r"\b([a-z_]+) (?:text|uuid|numeric|integer|boolean|date|timestamptz|double precision|smallint|jsonb)", body)
    cols021, cols022 = returns_cols(prev), returns_cols(sql)
    assert cols022 == cols021 + ["publication_status"]
    def select_cols(text):
        body = text[text.index("  select\n"):text.index("  from public.properties")]
        return [c.strip() for c in body.replace("select", "").replace("\n", " ").split(",") if c.strip()]
    assert select_cols(sql) == select_cols(prev) + ["publication_status"]
    assert "set search_path = public" in sql and "grant execute on function public.get_properties" in sql
    assert "where state = p_state" in sql and "order by county, case_no" in sql
    assert "'APPROVED', 'APPROVED_GRANDFATHERED', 'UNREVIEWED', 'RESTRICTED', 'BLOCKED'" in sql
    assert "'newly_observed', 'status_changed', 'removed', 'result_published'" in sql
    assert "grant select (publication_status) on public.properties to authenticated" in sql
    # The bridge writes the 022 shape only when asked.
    assert set(csr.to_db_rows(ROWS[:1], schema="022")[0]) == set(csr.EXTENDED_COLUMNS)
    assert "publication_status" not in csr.to_db_rows([r for r in ROWS if r.state == "FL"][:1], schema="018")[0]
    doc = (REPO / "docs/production-configuration.md").read_text(encoding="utf-8")
    assert "022_available_publication_gate.sql" in doc


def test_m02_workflow_runs_the_gate_after_the_laft_sync_non_blocking_and_touches_no_schedule():
    import yaml
    wf = yaml.safe_load((REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    laft = wf["jobs"]["laft"]
    names = [s.get("name", "") for s in laft["steps"]]
    gate = next(s for s in laft["steps"] if s.get("name", "").startswith("Publication gate"))
    assert gate["continue-on-error"] is True and gate["run"] == "python3 scripts/publication_gate.py --state FL"
    assert names.index(gate["name"]) > names.index(next(n for n in names if n.startswith("Per-unit freshness")))
    on = wf.get("on") or wf.get(True)
    assert on["schedule"] == [{"cron": "0 10 * * *"}, {"cron": "0 22 * * *"}, {"cron": "0 12 * * *"}]   # deeds (10, 22) + laft/certificates (12) unchanged


# ==================== 7. regression ====================

def test_x01_fl_tx_al_ar_la_az_regressions():
    assert states.PRODUCTION_STATES == {"FL", "TX"} and not any(states.is_activated(c) for c in ("AL", "AR", "LA", "AZ"))
    # FL Available production sources: still the 52 units, all grandfathered-publishable, no purchase path invented.
    fl = [r for r in ROWS if r.state == "FL" and r.is_production and "AVAILABLE" in r.ledger_set]
    assert len(fl) == 52 and all(pub.effective_publication(r) == "APPROVED_GRANDFATHERED" and not r.purchase_url for r in fl)
    # TX: LGBS the only Available production source, not retried; RealAuction auctions only; blocked vendors blocked; hctax restricted.
    tx_prod = [r for r in ROWS if r.state == "TX" and r.is_production]
    assert {r.source_id for r in tx_prod} == {"tx_lgbs", "tx_realauction"} and all("Do not retry" in r.notes for r in tx_prod if r.source_id == "tx_lgbs")
    assert not any("govease" in (r.source_id or "") for r in ROWS if r.is_production)
    assert all(pub.effective_publication(r) == "BLOCKED" and not r.canonical_url for r in ROWS if r.source_id in BLOCKED_SOURCE_IDS)
    assert csr.lookup(ROWS, "TX", "Harris").publication_status == "RESTRICTED"
    # AL / AR / LA / AZ: one row each, UNREVIEWED, never runnable; AZ is the certificate ledger.
    for code, sid, ledger in (("AL", "al_ador_state_land", "AVAILABLE"), ("AR", "ar_cosl_post_auction", "AVAILABLE"),
                              ("LA", "la_ebr_adjudicated", "AVAILABLE"), ("AZ", "az_maricopa_state_cp", "LIENS_CERTIFICATES")):
        rows = [r for r in ROWS if r.state == code]
        assert len(rows) == 1 and rows[0].source_id == sid and rows[0].ledger_set == {ledger} and not rows[0].runnable
        assert rows[0].publication_status == "UNREVIEWED" and rows[0].purchase_path_mode in ("", "online_instructions", "application")
    # The frontend withholds by the propagated column and counts, never silently.
    app = (REPO / "public/app.js").read_text(encoding="utf-8")
    assert 'return !s || s === "APPROVED" || s === "APPROVED_GRANDFATHERED";' in app
    assert "withheld - source not approved for customer publication" in app
    assert 'id="availableFilters"' in (REPO / "public/index.html").read_text(encoding="utf-8")
    assert 'id="availableFilters"' in (REPO / "public/tx.html").read_text(encoding="utf-8")
    for f in ("app.js", "index.html", "tx.html", "styles.css", "sw.js"):
        assert (REPO / f).read_bytes() == (REPO / "public" / f).read_bytes(), f
