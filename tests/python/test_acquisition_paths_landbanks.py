"""Per-property acquisition links for the land-bank AVAILABLE sources, and the
acquisition-evidence records/status invariant (2026-10-25 / 26).

Synthetic fixtures only: every identifier below is invented ("FIXTURE...",
"0000000000x") and no request is made. What is pinned:

* A per-property page (harvesters/otc/adapters/property_page.py) is built only
  from the source's own published identifier, never for a malformed one, and
  is typed by the purchase-path engine as a property-scope direct path that
  still carries the source's verified process record.
* St. Louis LRA links only the parcels the City's own For-Sale file lists;
  an unreadable file links nothing and drops nothing.
* public/acquisition-evidence.json: every VERIFIED status has the record the
  acquisition gate looks up, with a path type and a URL to act on.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from harvesters.otc.adapters import epropertyplus as EPP  # noqa: E402
from harvesters.otc.adapters import expansion as EX  # noqa: E402
from harvesters.otc.adapters.property_page import PropertyPage  # noqa: E402
from harvesters.otc.adapters.tabular import TabularListAdapter, attach_property_pages, listed_ids  # noqa: E402
from harvesters.otc.model import PurchaseUrlKind  # noqa: E402
from harvesters.sources import acquisition_evidence_status as AES  # noqa: E402
from harvesters.sources.acquisition_gate import find_record  # noqa: E402
import build_acquisition_evidence as BAE  # noqa: E402
import harvest_expansion as H  # noqa: E402
import purchase_path_engine as PE  # noqa: E402

AT = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
EVIDENCE = json.loads((REPO / "public" / "acquisition-evidence.json").read_text(encoding="utf-8"))
EXPANSION = PE.load_evidence(REPO / "data" / "purchase_path_evidence_expansion.csv")


# ---- the per-property page value object -----------------------------------
def test_property_page_refuses_a_non_https_or_placeholder_free_template():
    kw = dict(kind=PurchaseUrlKind.ONLINE_PURCHASE, id_pattern=r"\d+", verified_on="2026-10-25",
              verification="v", pattern_source="p")
    with pytest.raises(ValueError):
        PropertyPage(template="http://x.gov/p/{id}", **kw)
    with pytest.raises(ValueError):
        PropertyPage(template="https://x.gov/p/", **kw)
    with pytest.raises(ValueError):
        PropertyPage(template="https://x.gov/p/{id}", **{**kw, "kind": PurchaseUrlKind.PURCHASE_INSTRUCTIONS})
    with pytest.raises(ValueError):
        PropertyPage(template="https://x.gov/p/{id}", **{**kw, "verified_on": ""})


def test_property_page_only_for_the_published_identifier_shape():
    page = EX.TN_SHELBY_LANDBANK.property_page
    assert page.url_for("FIXTURE0000001") == "https://public-sctn.epropertyplus.com/property/FIXTURE0000001"
    for bad in ("", None, "FIXTURE", "FIXTURE0000001X", "../FIXTURE00001", "fixture0000001"):
        assert page.url_for(bad) is None
    lra = EX.MO_STL_LRA.property_page
    assert lra.url_for("00000000001").endswith("city-owned-property-search.cfm?action=detail&parcelId=00000000001")
    assert lra.url_for("0000000001") is None
    assert "verified 20" in page.basis() and "verified 20" in lra.basis()


def test_configured_pages_are_on_the_sources_own_hosts():
    assert EX.TN_SHELBY_LANDBANK.property_page.template.startswith(EX.TN_SHELBY_LANDBANK.portal + "/")
    assert EX.MO_STL_LRA.property_page.template.startswith("https://www.stlouis-mo.gov/")
    assert EX.MO_STL_LRA.property_page_listed_url.startswith("https://static.stlouis-mo.gov/open-data/SLDC/REAL-ESTATE/")
    # Sources with no verified per-property page carry none (never guessed).
    for cfg in (EX.MI_DETROIT_LANDBANK_LOTS, EX.MI_DETROIT_LANDBANK_PROGRAMS, EX.PA_FAYETTE_REPOSITORY,
                EX.MN_RAMSEY_TAX_FORFEIT):
        assert getattr(cfg, "property_page", None) is None
        assert cfg.purchase_url is None


# ---- Shelby (ePropertyPlus) -------------------------------------------------
def _epp_row(pid, status="FOR SALE", available="Y"):
    return {"id": 1, "parcelNumber": pid, "currentStatus": status, "available": available,
            "propertyAddress1": "1 FIXTURE ST", "askingPrice": 0}


def test_shelby_offered_rows_carry_the_portal_property_page():
    recs, counts = EPP.parse_rows(EX.TN_SHELBY_LANDBANK, [_epp_row("FIXTURE0000001"), _epp_row("FIXTURE0000002", "SOLD"),
                                                          _epp_row("BAD")], retrieved_at=AT)
    assert counts == {"excluded_status": 1, "rejected_ids": 1, "duplicates": 0}
    (r,) = recs
    assert r.purchase_url == "https://public-sctn.epropertyplus.com/property/FIXTURE0000001"
    assert r.purchase_url_kind is PurchaseUrlKind.ONLINE_PURCHASE
    assert "Apply For this Property" in r.provenance["purchase_url_basis"]


def test_shelby_row_resolves_to_a_property_scope_direct_path():
    row = EPP.parse_rows(EX.TN_SHELBY_LANDBANK, [_epp_row("FIXTURE0000001")], retrieved_at=AT)[0][0].to_properties_row()
    rows, n = H.attach_purchase_paths("TN", [row], harvest_date="2026-10-26")
    assert n == 1
    r = rows[0]
    assert (r["purchase_path_type"], r["purchase_path_scope"]) == ("direct_property_url", "property")
    assert r["purchase_url"].endswith("/property/FIXTURE0000001")
    assert r["purchase_path_observed_on"] == EX.TN_SHELBY_LANDBANK.property_page.verified_on
    assert r["otc_provenance"]["acquisition"]["mode"] == "online"


# ---- St. Louis LRA (tabular CSV + the City's For-Sale file) -----------------
LRA_CSV = ("ParcelId,Parcel_Status,Address,LegalDescription,PropertyType\n"
           "00000000001,Available,1 FIXTURE ST,FIXTURE LOT 1,Lot\n"
           "00000000002,Available,2 FIXTURE ST,FIXTURE LOT 2,Building\n"
           "00000000003,Unavailable,3 FIXTURE ST,FIXTURE LOT 3,Lot\n")
FOR_SALE_CSV = "ParcelId,Address\n00000000001,1 FIXTURE ST\n"


def _lra_records():
    return TabularListAdapter(EX.MO_STL_LRA).parse_csv(LRA_CSV, retrieved_at=AT, document_name="LRA_INVENTORY.csv")


def test_lra_links_only_parcels_on_the_citys_for_sale_file():
    recs = _lra_records()
    assert [r.case_no for r in recs] == ["00000000001", "00000000002"]
    assert attach_property_pages(recs, EX.MO_STL_LRA, listed_ids(FOR_SALE_CSV, "ParcelId")) == 1
    linked, unlinked = recs
    assert linked.purchase_url.endswith("parcelId=00000000001")
    assert linked.purchase_url_kind is PurchaseUrlKind.OFFER_FORM
    assert linked.provenance["purchase_url_listed_in"] == EX.MO_STL_LRA.property_page_listed_url
    assert unlinked.purchase_url is None and "purchase_url_basis" not in unlinked.provenance


def test_lra_unreadable_for_sale_file_links_nothing_and_drops_nothing(capsys):
    recs = _lra_records()

    def boom(url):
        raise OSError("fixture transport failure")

    assert H.link_property_pages(EX.MO_STL_LRA, recs, boom, offline=False) == 0
    assert len(recs) == 2 and all(r.purchase_url is None for r in recs)
    assert H.link_property_pages(EX.MO_STL_LRA, recs, lambda u: "Other\n1\n", offline=False) == 0   # no ParcelId column
    assert H.link_property_pages(EX.MO_STL_LRA, recs, lambda u: FOR_SALE_CSV, offline=True) == 0     # fixture runs make no request
    assert H.link_property_pages(EX.MO_STL_LRA, recs, lambda u: FOR_SALE_CSV, offline=False) == 1
    out = capsys.readouterr().out
    assert "00000000001" not in out          # counts only


def test_listed_ids_refuses_a_file_without_the_column():
    with pytest.raises(ValueError):
        listed_ids("Parcel\n00000000001\n", "ParcelId")
    assert listed_ids("﻿ParcelId\n00000000001\n \n", "ParcelId") == {"00000000001"}


def test_lra_paths_property_link_first_process_for_every_row():
    recs = _lra_records()
    attach_property_pages(recs, EX.MO_STL_LRA, {"00000000001"})
    rows, n = H.attach_purchase_paths("MO", [r.to_properties_row() for r in recs], harvest_date="2026-10-26")
    assert n == 2
    linked, unlinked = rows
    assert (linked["purchase_path_type"], linked["purchase_path_scope"]) == ("direct_property_url", "property")
    # The property link keeps the LRA's verified process (steps, office, form) from the evidence table.
    acq = linked["otc_provenance"]["acquisition"]
    assert acq["application_url"] == "https://www.lrastl.org/s/LRA-Offer-Submission-Form-5224.pdf" and acq["steps"]
    assert (unlinked["purchase_path_type"], unlinked["purchase_path_scope"]) == ("application_download", "source")
    assert unlinked["purchase_url"] == "https://www.lrastl.org/s/LRA-Offer-Submission-Form-5224.pdf"


# ---- process evidence rows --------------------------------------------------
@pytest.mark.parametrize("state,sid,county,ptype", [
    ("MI", "mi_detroit_landbank_lots", "Wayne", "county_instructions"),
    ("MO", "mo_stl_lra_inventory", "St. Louis City", "application_download"),
    ("MN", "mn_ramsey_tax_forfeit", "Ramsey", "county_instructions"),
    ("PA", "pa_fayette_repository", "Fayette", "application_download"),
])
def test_landbank_process_rows_resolve_through_the_engine(state, sid, county, ptype):
    rows = [e for e in EXPANSION if (e.state, e.source_id, e.county) == (state, sid, county)]
    assert len(rows) == 1 and rows[0].applicable and rows[0].path_type == ptype
    assert rows[0].steps and rows[0].evidence_url.startswith("https://")
    rec = find_record(EVIDENCE["records"], state, sid, county)
    assert rec and rec["path_type"] == ptype and AES.record_url(rec)


def test_detroit_row_cites_the_current_vacant_land_policy():
    (e,) = [e for e in EXPANSION if e.source_id == "mi_detroit_landbank_lots"]
    assert "SECOND-AMENDED-AND-RESTATED-VACANT-LAND-POLICY" in e.url
    assert "Oct+2023" not in e.url and e.observed_on == "2026-10-26"


# ---- records and status agree -----------------------------------------------
def test_every_verified_status_has_a_usable_record():
    for u in EVIDENCE["status"]:
        if u["status"] != "VERIFIED":
            continue
        rec = find_record(EVIDENCE["records"], u["state"], u["source_id"], u["county"])
        key = (u["state"], u["source_id"], u["county"])
        assert rec is not None, f"VERIFIED without a record: {key}"
        assert rec.get("path_type"), f"record without a path type: {key}"
        assert AES.record_url(rec).startswith("https://"), f"record without a URL to act on: {key}"
        assert u.get("path_type") == rec["path_type"], key


def test_registry_documents_become_engine_typed_records():
    for sid, county in (("mi_oceana_landbank", "Oceana"), ("ok_oklahoma_county_owned", "Oklahoma"),
                        ("sc_georgetown_forfeited_land", "Georgetown"), ("sc_horry_forfeited_land", "Horry")):
        st = {"mi": "MI", "ok": "OK", "sc": "SC"}[sid[:2]]
        rec = find_record(EVIDENCE["records"], st, sid, county)
        assert rec and rec["path_type"] == "application_download", sid   # a PDF form is never a per-parcel link
        assert rec["process_url"].startswith("https://")


class _Ev:
    applicable, state, source_id, county, observed_on, path_type, source_title = True, "XX", "s", "A", "2026-10-26", "county_instructions", "t"


def test_unit_status_downgrades_evidence_the_engine_did_not_build():
    u = AES.unit_status("XX", "s", "A", evidence=[_Ev()], records_known=True, record=None, refusal="a third-party host")
    assert u.status == "NEEDS_REVIEW" and "a third-party host" in u.reason
    ok = AES.unit_status("XX", "s", "A", evidence=[_Ev()], records_known=True,
                         record={"path_type": "county_instructions", "process_url": "https://x.gov/p"})
    assert ok.status == "VERIFIED" and ok.path_type == "county_instructions"
    # Without records (legacy callers) the evidence row alone still decides.
    assert AES.unit_status("XX", "s", "A", evidence=[_Ev()]).status == "VERIFIED"


def test_the_generated_file_is_current():
    assert (REPO / "public" / "acquisition-evidence.json").read_text(encoding="utf-8") == BAE.render()
