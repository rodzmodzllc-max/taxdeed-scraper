"""Office replies (2026-11-04): what the Orange County Comptroller and the
Palm Beach County Clerk said, recorded as what each reply actually answered.

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
    assert offices == {"Orange County Comptroller", "Palm Beach County Clerk of the Circuit Court & Comptroller"}


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
