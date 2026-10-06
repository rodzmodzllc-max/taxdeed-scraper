"""Acquisition-evidence status per AVAILABLE unit (2026-10-06)."""
import json
import re
from pathlib import Path

import pytest

from harvesters.sources import acquisition_evidence_status as AES

REPO = Path(__file__).resolve().parents[2]
APP = (REPO / "public/app.js").read_text(encoding="utf-8")
STATUS = json.loads((REPO / "public/acquisition-evidence.json").read_text(encoding="utf-8"))["status"]


def _js_obj(name):
    body = re.search(r"var " + name + r" = \{(.*?)\n\};", APP, re.S).group(1)
    return dict(re.findall(r"(\w+):\s*\"([^\"]*)\"", body))


def test_js_labels_mirror_python():
    assert _js_obj("ACQ_EVIDENCE_STATUS_LABELS") == AES.STATUS_LABELS
    assert _js_obj("ACQ_DOC_KIND_LABELS") == AES.DOC_KIND_LABELS


def test_outcomes_are_valid_and_never_verified():
    outs = AES.load_outcomes()
    assert outs
    for o in outs:
        assert AES.outcome_problems(o) == [], (o, AES.outcome_problems(o))
        # No parcel number, amount or other long digit run in a public reason.
        assert not re.search(r"\d{5,}", o.reason), o.reason


def test_outcome_units_are_registered_available_sources():
    from harvesters.governance.county_source_registry import load_registry
    reg = {(r.state, r.source_id, r.county) for r in load_registry() if "AVAILABLE" in (r.ledgers or "")}
    for o in AES.load_outcomes():
        assert (o.state, o.source_id, o.county) in reg, o


def test_candidates_are_official_https_and_typed():
    banned = ("google.", "bing.", "bid4assets", "govease", "lgbs.com", "realauction", "medium.com", "zillow", "redfin",
              "wikipedia", "1degree", "govire", "equatorstudios", "acres.com", "dynamospatial")
    for c in AES.load_candidates():
        assert c["url"].startswith("https://")
        assert c["doc_kind"] in AES.DOC_KINDS, c
        assert not any(b in c["url"] for b in banned), c["url"]


class _Ev:
    def __init__(self, **kw):
        self.__dict__.update(dict(applicable=True, state="FL", source_id="s", county="A", observed_on="2026-10-01",
                                  path_type="phone_mail", source_title="Clerk page"), **kw)


class _Reg:
    def __init__(self, **kw):
        self.__dict__.update(dict(purchase_url="", verification_status="PRODUCTION_VERIFIED", last_checked="2026-10-02"), **kw)


def test_precedence_evidence_then_registry_then_outcome_then_candidates():
    o = AES.Outcome("FL", "s", "A", "UNAVAILABLE", "capture", "HTTP 403", "2026-10-01", "1")
    cand = [{"state": "FL", "county": "A", "source_id": "", "url": "https://clerk.example.gov/p", "doc_kind": "SOURCE_PAGE"}]
    assert AES.unit_status("FL", "s", "A", evidence=[_Ev()], outcomes=[o], candidates=cand).status == "VERIFIED"
    assert AES.unit_status("FL", "s", "A", evidence=[], registry_row=_Reg(purchase_url="https://c.gov/form.pdf"),
                           outcomes=[o]).basis == "registry"
    u = AES.unit_status("FL", "s", "A", evidence=[], outcomes=[o], candidates=cand)
    assert (u.status, u.basis, len(u.candidates)) == ("UNAVAILABLE", "capture", 1)
    assert AES.unit_status("FL", "s", "A", evidence=[], candidates=cand).status == "NEEDS_REVIEW"
    assert AES.unit_status("FL", "s", "A", evidence=[]).status == "NOT_FOUND"


def test_unreachable_or_disabled_evidence_is_never_verified():
    assert AES.unit_status("FL", "s", "A", evidence=[_Ev(applicable=False)]).status != "VERIFIED"
    # A registry row whose source is not production-verified, or whose URL is not https, is not evidence.
    assert AES.unit_status("FL", "s", "A", evidence=[], registry_row=_Reg(purchase_url="https://c.gov/f.pdf",
                           verification_status="CANDIDATE")).status != "VERIFIED"
    assert AES.unit_status("FL", "s", "A", evidence=[], registry_row=_Reg(purchase_url="http://c.gov/f.pdf")).status != "VERIFIED"


@pytest.mark.parametrize("bad", [
    AES.Outcome("FL", "s", "A", "VERIFIED", "capture", "x", "2026-10-01", "1"),
    AES.Outcome("FL", "s", "A", "UNAVAILABLE", "capture", "x", "2026-10-01", ""),
    AES.Outcome("FL", "s", "A", "NOT_FOUND", "search_index", "x", "2026-10-01"),
    AES.Outcome("FL", "s", "A", "NEEDS_REVIEW", "document_read", "x", "2026-10-01", document_url="http://x"),
])
def test_invalid_outcomes_are_refused(bad):
    assert AES.outcome_problems(bad)


def test_generated_status_is_county_wide_and_complete():
    by = {(u["state"], u["source_id"], u["county"]): u for u in STATUS}
    for u in STATUS:
        assert u["status"] in AES.STATUSES and u["scope"] == "source"
        if u["status"] != "VERIFIED":
            assert u.get("reason")
    # Every current AVAILABLE source in production has a unit.
    for key in [("MO", "mo_stl_lra_inventory", "St. Louis City"), ("PA", "pa_fayette_repository", "Fayette"),
                ("MN", "mn_ramsey_tax_forfeit", "Ramsey"), ("OK", "ok_oklahoma_county_owned", "Oklahoma"),
                ("SC", "sc_horry_forfeited_land", "Horry"), ("SC", "sc_georgetown_forfeited_land", "Georgetown"),
                ("MI", "mi_detroit_landbank_lots", "Wayne"), ("MI", "mi_oceana_landbank", "Oceana"),
                ("LA", "la_ebr_adjudicated", "East Baton Rouge"), ("TX", "tx_lgbs", "Liberty"), ("FL", "fl_laft_html", "Putnam")]:
        assert key in by, key
    assert by[("MO", "mo_stl_lra_inventory", "St. Louis City")]["status"] == "NEEDS_REVIEW"
    assert by[("FL", "fl_laft_realtdm", "Sarasota")]["status"] == "UNAVAILABLE"
    assert by[("LA", "la_ebr_adjudicated", "East Baton Rouge")]["status"] == "VERIFIED"
    # County-wide evidence is one record per unit, never per property.
    assert len(by) == len(STATUS)


def test_authorities_named_for_every_current_available_source():
    for sid in ("fl_laft_html", "la_ebr_adjudicated", "tx_lgbs", "mi_detroit_landbank_lots", "mi_oceana_landbank",
                "mo_stl_lra_inventory", "ok_oklahoma_county_owned", "pa_fayette_repository", "mn_ramsey_tax_forfeit",
                "sc_horry_forfeited_land", "sc_georgetown_forfeited_land"):
        t, name = AES.authority_for(sid)
        assert t in AES.AUTHORITY_TYPES and name, sid
    assert AES.authority_for("tx_lgbs", "Galveston")[1] == "Galveston County Sheriff's Office"
