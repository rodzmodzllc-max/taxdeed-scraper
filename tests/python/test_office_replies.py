"""Office replies (2026-11-04): what the Orange County Comptroller and the
Palm Beach County Clerk said, recorded as what each reply actually answered.
Second round (2026-11-05): RealAuction, the Volusia / Indian River / Citrus
Clerks, Oklahoma OGI, Wisconsin SCO, the Tennessee Comptroller and the
routing / technical answers - see the tests at the end of this file.

- A link permission, or a routing / technical answer, is never permission to
  collect or to reuse the records commercially.
- Orange: links are written permission; fetch / parse / store / display are
  RESTRICTED (automated collection and commercial incorporation prohibited
  without prior written authorization), and the daily job no longer reads it.
- Palm Beach: a technical answer only; a link-only row, nothing documented,
  and court-case deep links are refused as customer links.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import authorization as A  # noqa: E402
from harvesters.governance import office_replies as O  # noqa: E402
from harvesters.governance import permissions as P  # noqa: E402

import laft_purchase_paths as LPP  # noqa: E402


def test_register_agrees_with_permissions_and_authorizations():
    assert O.problems() == []
    offices = {r.office for r in O.load()}
    assert {"Orange County Comptroller", "Palm Beach County Clerk of the Circuit Court & Comptroller",
            "RealAuction.com (vendor)", "Volusia County Clerk of the Circuit Court",
            "Indian River County Clerk of Court & Comptroller", "Citrus County Clerk of the Circuit Court & Comptroller",
            "Wisconsin State Cartographer's Office (V12 statewide parcels)"} <= offices


def test_orange_links_allowed_and_reuse_denied():
    d = P.authorize("fl_laft_orange", "link", state="FL", county="Orange", dataset="lands_available")
    assert d.allowed and d.basis == "DOCUMENTED"
    for op in ("fetch", "parse", "store", "display"):
        d = P.authorize("fl_laft_orange", op, state="FL", county="Orange", dataset="lands_available")
        assert not d.allowed and d.reason_code == "RESTRICTED", (op, d.reason_code)
    a = A.PROVIDER_AUTHORIZATIONS["fl_laft_orange__county__orange_comptroller"]
    assert not any(getattr(a.scope, dim).authorized for dim in A.ALL_USE_DIMENSIONS)
    assert a.contact_email is None and a.request_date is None          # never invented


def test_orange_reader_is_not_scheduled_and_refuses_before_any_request():
    wf = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
    assert "run: python3 scripts/harvest_laft_orange.py" not in wf
    import laft_status as LS  # noqa: PLC0415
    assert LS.permission_gate("fl_laft_orange") == LS.PERMISSION_DENIED_EXIT


def test_palm_beach_is_link_only_and_nothing_documented():
    d = P.authorize("fl_laft_pioneer", "link", state="FL", county="Palm Beach", dataset="lands_available")
    assert d.allowed and d.basis == "LINK_ONLY" and not d.documented
    a = A.PROVIDER_AUTHORIZATIONS["fl_laft_pioneer__county__palm_beach_clerk"]
    assert a.authorization_status == A.AuthorizationStatus.RECEIVED
    assert not any(getattr(a.scope, dim).authorized for dim in A.ALL_USE_DIMENSIONS)
    # The other Pioneer counties are untouched by the Palm Beach reply.
    other = P.authorize("fl_laft_pioneer", "link", state="FL", county="Leon", dataset="lands_available")
    assert not other.allowed


def test_court_case_deep_links_are_refused_as_customer_links():
    assert O.restricted_link_reason("https://appsgp.mypalmbeachclerk.com/eCaseView/landingpage.aspx")
    assert LPP.untrusted_reason("https://appsgp.mypalmbeachclerk.com/eCaseView/search.aspx?x=1")
    # The Clerk's tax deed site and other clerks' pages stay acceptable.
    assert O.restricted_link_reason("https://taxdeed.mypalmbeachclerk.com/") is None
    assert O.restricted_link_reason("https://occompt.com/158/Land-Available-For-Taxes") is None


def test_a_non_commercial_reply_can_never_back_documented_reuse():
    replies = O.load()
    records = P.load()
    # Pretend someone records Palm Beach display as APPROVED on the strength of the technical reply.
    base = next(r for r in records if r.source_id == "fl_laft_pioneer" and r.operation == "display")
    forged = replace(base, jurisdiction="FL:Palm Beach", status="APPROVED", evidence_type="WRITTEN_PERMISSION")
    assert any("did not permit commercial use" in p for p in O.problems(replies, records + [forged]))
    # And an Orange reuse row that is not RESTRICTED is caught.
    orange = next(r for r in records if r.source_id == "fl_laft_orange" and r.operation == "fetch")
    lax = [replace(r, status="LEGAL_REVIEW_REQUIRED", evidence_type="GRANDFATHERED_PRACTICE") if r is orange else r
           for r in records]
    assert any("must be RESTRICTED" in p for p in O.problems(replies, lax))
    # A routing or technical reply cannot claim to settle commercial use.
    bad = replace(replies[1], commercial_use="PERMITTED")
    assert any("cannot settle commercial use" in p for p in O.problems([bad], records))


def test_orange_rows_are_withheld_from_every_customer_view_including_preview():
    from harvesters.governance import commercial_scope as CS  # noqa: PLC0415
    from harvesters.governance import publication as PUB  # noqa: PLC0415
    decisions = {"fl_laft_orange": type("D", (), {"publication": "RESTRICTED"})(),
                 "fl_laft_pioneer": type("D", (), {"publication": "APPROVED_GRANDFATHERED"})()}
    assert PUB.row_publication({"source_id": "fl_laft_orange", "state": "FL", "county": "Orange"}, decisions) == "BLOCKED"
    # Palm Beach's technical reply withholds nothing on its own.
    assert PUB.row_publication({"source_id": "fl_laft_pioneer", "state": "FL", "county": "Palm Beach"},
                               decisions) == "APPROVED_GRANDFATHERED"
    orange = next(x for x in CS.classify() if x["source_id"] == "fl_laft_orange")
    assert orange["commercial_scope"] == "BLOCKED" and orange["tester_preview"] is False
    # A prohibition whose owner decision is PENDING withholds nothing by itself.
    for sid in ("fl_laft_pdfs", "fl_laft_html", "fl_realauction", "tx_realauction"):
        x = next((x for x in CS.classify() if x["source_id"] == sid), None)
        assert x is None or x["commercial_scope"] != "BLOCKED", sid


# --- Second round (2026-11-05) ------------------------------------------------

def _reply(office, state=None):
    return next(r for r in O.load() if r.office == office and (state is None or r.state == state))


def test_no_personal_data_in_the_register():
    import re  # noqa: PLC0415
    text = (REPO / "data" / "office_replies.csv").read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)                 # no e-mail address
    assert not re.search(r"\(?\d{3}\)?[ .-]\d{3}-\d{4}", text)               # no phone number


def test_realauction_refusal_is_recorded_and_left_to_the_owner():
    for state, sources in (("FL", {"fl_realauction", "fl_laft_realtdm"}), ("TX", {"tx_realauction"})):
        r = _reply("RealAuction.com (vendor)", state)
        assert set(r.source_ids) == sources
        assert r.question_answered == "COMMERCIAL_USE" and r.commercial_use == "NOT_ANSWERED"
        assert r.automated_collection == "PROHIBITED" and r.pending
        assert "will not be providing any form of written permission" in r.restricts
        assert not r.authorization_id                                    # grants nothing
        for src in sources:
            assert not O.prohibits_reuse(src, state, None) and not O.prohibits_reuse(src, state, "Volusia")
    # The interim records are unchanged: still allowed, never documented.
    d = P.authorize("fl_realauction", "fetch", state="FL", county="Volusia", dataset="sale_calendar")
    assert d.allowed and not d.documented
    d = P.authorize("tx_realauction", "fetch", state="TX", county="Harris")
    assert d.allowed and not d.documented
    # Every pending prohibition is listed as an open owner decision.
    docs = (REPO / "docs" / "source-permissions.md").read_text(encoding="utf-8")
    assert {r.office for r in O.pending_decisions()} == {
        "RealAuction.com (vendor)", "Volusia County Clerk of the Circuit Court",
        "Indian River County Clerk of Court & Comptroller"}
    for r in O.pending_decisions():
        assert r.office in docs


def test_a_settled_refusal_would_require_restricted_collection():
    replies = O.load()
    settled = [replace(r, owner_decision="") if r.office == "RealAuction.com (vendor)" else r for r in replies]
    assert any("prohibits automated collection, so it must be RESTRICTED" in p for p in O.problems(settled))
    # A refused automated collection can never back a documented fetch record.
    base = next(x for x in P.load() if x.source_id == "tx_realauction" and x.operation == "fetch")
    forged = replace(base, status="APPROVED", evidence_type="WRITTEN_PERMISSION")
    assert any("refused automated collection" in p for p in O.problems(replies, P.load() + [forged]))
    # PENDING is for prohibitions only, and must be listed in the docs.
    bad = replace(_reply("Lee County Clerk of Court (Tax Deed Surplus)"), owner_decision="PENDING")
    assert any("PENDING only on a prohibition" in p for p in O.problems([bad]))
    volusia = _reply("Volusia County Clerk of the Circuit Court")
    assert any("must be listed" in p for p in O.problems([volusia], docs_text=""))


def test_volusia_prohibition_pending_and_deep_links_refused():
    r = _reply("Volusia County Clerk of the Circuit Court")
    assert r.commercial_use == "PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION" and r.pending
    assert not O.prohibits_reuse("fl_laft_pdfs", "FL", "Volusia")      # the owner decides; nothing withheld yet
    for deep in ("https://app02.clerk.org/cm_rpt/lands/LandsAvailableForTaxes.pdf",
                 "https://app02.clerk.org/cm_rpt/?id=lat", "https://app02.clerk.org/or_td/Search.aspx?x=1",
                 "https://app02.clerk.org/ccms/"):
        assert O.restricted_link_reason(deep), deep
        assert LPP.untrusted_reason(deep)
        assert O.entry_link(deep) == "https://app02.clerk.org/or_td/"
    for entry in ("https://app02.clerk.org/or_td/", "https://app02.clerk.org/or_td", "https://app02.clerk.org/or_m/"):
        assert O.restricted_link_reason(entry) is None, entry
        assert O.entry_link(entry) is None
    assert O.restricted_link_reason("https://www.clerk.org/") is None


def test_app_js_office_link_entries_match_the_register():
    import json  # noqa: PLC0415
    import re  # noqa: PLC0415
    js = (REPO / "public" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"var OFFICE_LINK_ENTRIES = \[\s*(\{.*?\})\s*\];", js, re.S)
    assert m
    entry = json.loads(re.sub(r"(\{\s*|,\s*)(\w+):", r'\1"\2":', m.group(1)))
    want = []
    for r in O.load():
        ent = [p[1:].rstrip("/") for p in r.restricted_link_patterns if p.startswith("!")]
        if ent:
            plain = [p for p in r.restricted_link_patterns if not p.startswith("!")]
            want.append({"match": plain[0], "entries": ent, "to": O.entry_link("https://" + plain[0] + "/x")})
    assert [entry] == want
    assert 'return s && !isDataServiceUrl(s) ? officeEntryLink(s) : "";' in js


def test_indian_river_prohibition_recorded_pending():
    r = _reply("Indian River County Clerk of Court & Comptroller")
    assert r.commercial_use == "PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION" and r.pending
    assert "we do not grant permission for any commercial activities" in r.restricts
    assert not O.prohibits_reuse("fl_laft_html", "FL", "Indian River")


def test_okmaps_links_always_carry_the_requested_credit():
    r = _reply("Oklahoma Office of Geographic Information (Oklahoma Conservation Commission)")
    assert '"OKMaps and iProplogic"' in r.permits and not r.source_ids
    files = [*(REPO / "public").glob("*.js"), *(REPO / "public").glob("*.html"), *(REPO / "data").glob("*.csv")]
    for path in files:
        if path.name == "office_replies.csv":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "okmaps.org" in text.lower():
            assert "OKMaps and iProplogic" in text, path


def test_permitted_replies_without_an_authorization_grant_nothing():
    for office in ("Wisconsin State Cartographer's Office (V12 statewide parcels)",
                   "Tennessee Comptroller of the Treasury, Division of Property Assessments (GIS)"):
        r = _reply(office)
        assert r.commercial_use == "PERMITTED" and not r.authorization_id
    # The WI V12 permission records are unchanged (nothing added on the reply alone).
    assert not P.authorize("wi_sco_v12_parcels", "fetch", state="WI", county="Dane").documented
    base = next(x for x in P.load() if x.source_id == "wi_sco_v12_parcels" and x.operation == "fetch")
    forged = replace(base, status="APPROVED", evidence_type="PUBLISHED_LICENSE")
    assert any("grants nothing" in p for p in O.problems(O.load(), P.load() + [forged]))


def test_routing_and_technical_replies_settle_nothing():
    rows = [r for r in O.load() if r.question_answered in ("ROUTING_ONLY", "TECHNICAL_ONLY")]
    assert len(rows) >= 30
    for r in rows:
        assert r.commercial_use == "NOT_ANSWERED" and not r.owner_decision


def test_citrus_limits_are_read_from_the_register_and_enforced(tmp_path):
    import json  # noqa: PLC0415
    import host_limits as HL  # noqa: PLC0415
    import harvest_laft_pioneer as pioneer  # noqa: PLC0415
    assert O.collection_limits_for("search.citrusclerk.org") == (2000, 60.0)
    assert O.collection_limits_for("taxdeed.mypalmbeachclerk.com") is None

    clock = {"t": 1_800_000_000.0}
    slept = []

    def sleep(s):
        slept.append(s)
        clock["t"] += s

    state = tmp_path / "counts.json"

    def make():
        return HL.HostLimiter(state, clock=lambda: clock["t"], sleep=sleep)

    url = "https://search.citrusclerk.org/TaxSmartWeb/Home/GridSearchData"
    lim = make()
    lim.before_request(url)
    lim.before_request(url)
    assert slept == [60.0]                                       # the second request waited 60 s
    clock["t"] += 5
    make().before_request(url)                                   # a later process shares the state
    assert slept[-1] == 55.0
    lim.before_request("https://taxdeed.mypalmbeachclerk.com/Home/GridSearchData")
    assert len(slept) == 2                                       # unlimited hosts pass straight through
    st = json.loads(state.read_text())
    assert st["search.citrusclerk.org"]["count"] == 3
    st["search.citrusclerk.org"]["count"] = 2000
    state.write_text(json.dumps(st))
    with pytest.raises(HL.DailyLimitReached):
        make().before_request(url)
    clock["t"] += 86_400                                         # next UTC day: a new budget
    make().before_request(url)
    # The Pioneer harvester calls the limiter before every request, retries included.
    assert "LIMITER.before_request(_grid_url(base_url))" in (REPO / "scripts" / "harvest_laft_pioneer.py").read_text()
    assert isinstance(pioneer.LIMITER, HL.HostLimiter)
