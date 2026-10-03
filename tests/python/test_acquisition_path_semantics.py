"""Acquisition-path semantics (evidence review 2026-10-03).

A county's downloadable application or bid-form PDF is an offline process:
it must never be typed as a direct_property_url (a per-parcel link), never
be property scope, and never resolve to the "online" acquisition mode
("Purchase or apply online"). Run through the real expansion adapters'
configurations and registry rows, exactly as scripts/harvest_expansion.py
attaches paths before the sync - the normalized representation the app
stores and renders, not display strings.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from harvesters.otc.adapters import expansion as EX  # noqa: E402
from harvesters.otc.adapters import sc_flc  # noqa: E402
import harvest_expansion as H  # noqa: E402
import laft_purchase_paths as PP  # noqa: E402
import purchase_path_engine as PE  # noqa: E402

OCEANA_PDF = EX.MI_OCEANA_LANDBANK.purchase_url
HORRY_PDF = EX.SC_HORRY_FLC.purchase_url
GEORGETOWN_PDF = sc_flc.GEORGETOWN.application_url
APP = (REPO / "public" / "app.js").read_text(encoding="utf-8")

# (state, source_id, county, url, kind) - the URL and kind each adapter
# puts on its rows, unchanged by this fix.
SOURCES = {
    "oceana": ("MI", "mi_oceana_landbank", "Oceana", OCEANA_PDF, "application_form"),
    "georgetown": ("SC", "sc_georgetown_forfeited_land", "Georgetown", GEORGETOWN_PDF, "application_form"),
    "horry": ("SC", "sc_horry_forfeited_land", "Horry", HORRY_PDF, "bid_form"),
}


def _attached(name: str, **extra) -> dict:
    state, sid, county, url, kind = SOURCES[name]
    row = {"source_id": sid, "county": county, "state": state, "status": "active", "case_no": "FIXTURE-1",
           "purchase_url": url, "purchase_url_kind": kind, "list_url": "https://example.invalid/list",
           "document_url": None, "otc_provenance": {}, **extra}
    rows, n = H.attach_purchase_paths(state, [row], harvest_date="2026-10-03")
    assert n == 1
    return rows[0]


def test_the_adapters_still_publish_the_same_source_urls_and_kinds():
    assert OCEANA_PDF == "https://oceana.mi.us/wp-content/uploads/2022/12/Purchase-Application-Land-Bank.pdf"
    assert GEORGETOWN_PDF == "https://www.gtcountysc.gov/DocumentCenter/View/1587/FLC-Procedures-and-Bid-Apps-PDF"
    assert HORRY_PDF == "https://horrycountysc.gov/media/sinbmsz5/horrycountyflcguidelines.pdf"
    assert EX.MI_OCEANA_LANDBANK.purchase_url_kind.value == "application_form"
    assert EX.SC_HORRY_FLC.purchase_url_kind.value == "bid_form"
    assert sc_flc.GEORGETOWN.application_kind.value == "application_form"


@pytest.mark.parametrize("name,mode", [("oceana", "application"), ("georgetown", "application"), ("horry", "bid")])
def test_offline_forms_are_source_level_application_downloads_never_online(name, mode):
    _, _, _, url, kind = SOURCES[name]
    r = _attached(name)
    assert r["purchase_path_type"] == "application_download"
    assert r["purchase_path_scope"] == "source"
    assert r["purchase_url"] == url and r["purchase_url_kind"] == kind      # the source URL and its kind are kept
    acq = r["otc_provenance"]["acquisition"]
    assert acq["mode"] == mode
    assert acq["mode"] != "online" and "online" not in acq["channels"]
    assert acq["channels"] == ["application"]


def test_horry_bid_form_is_never_a_direct_property_url_and_keeps_its_minimum_bid():
    r = _attached("horry", purchase_amount=1500, purchase_amount_kind="OPENING_BID", bid=1500)
    assert r["purchase_path_type"] != "direct_property_url"
    assert r["purchase_path_scope"] != "property"
    assert r["purchase_url"] == HORRY_PDF                                    # still offered as the process document
    assert (r["purchase_amount"], r["purchase_amount_kind"], r["bid"]) == (1500, "OPENING_BID", 1500)
    assert PE.ACQUISITION_MODE_LABELS[r["otc_provenance"]["acquisition"]["mode"]] == (
        "Bid application required - purchase process not online")


def test_row_link_resolution_for_a_county_wide_pdf_is_source_scope_even_with_a_property_kind():
    for kind in ("bid_form", "offer_form", "online_purchase"):
        path, why = PE.from_row_link({"purchase_url": HORRY_PDF, "purchase_url_kind": kind}, canonical_url=None,
                                     list_url=None, document_url=None, harvest_date="2026-10-03")
        assert why is None and path is not None
        assert (path.path_type, path.scope) == ("application_download", "source"), kind
        assert path.acquisition_mode != "online"


def test_a_genuine_online_purchase_page_is_still_online_and_property_scope():
    """The fix narrows only forms: a real per-parcel checkout page stays what it was."""
    url = "https://county.example.gov/tax-deeds/buy?parcel=1"
    path, why = PE.from_row_link({"purchase_url": url, "purchase_url_kind": "online_purchase",
                                  "purchase_url_basis": "rule verified 2026-10-03"},
                                 canonical_url=None, list_url=None, document_url=None, harvest_date="2026-10-03")
    assert why is None
    assert (path.path_type, path.scope, path.acquisition_mode) == ("direct_property_url", "property", "online")


@pytest.mark.parametrize("ptype", ["direct_property_url", "application_page", "application_download"])
def test_acquisition_mode_never_says_online_for_a_bid_kind_or_a_document(ptype):
    assert PE.acquisition_mode(ptype, (), (), url_kind="bid_form", url="https://x.example.gov/form") == "bid"
    assert PE.acquisition_mode(ptype, (), (), url_kind="offer_form", url=None) == "bid"
    assert PE.acquisition_mode(ptype, (), (), url_kind="application_form", url=OCEANA_PDF) == "application"


def test_document_url_detection():
    for u in (OCEANA_PDF, HORRY_PDF, GEORGETOWN_PDF, "https://x.gov/a/form.DOCX", "https://x.gov/f.pdf?v=2",
              "https://www.douglasco.gov/documents/request-for-assignment-of-county-held.pdf/"):
        assert PP.is_document_url(u), u
    for u in ("https://x.gov/purchase", "https://x.gov/pdf-guide", "", None):
        assert not PP.is_document_url(u), u
    assert PP.mode_for_kind("bid_form", HORRY_PDF) == "application"
    assert PP.mode_for_kind("bid_form", "https://x.gov/bid") == "online_property"


def test_registry_no_downloadable_form_is_recorded_as_an_online_mode():
    rows = list(csv.DictReader((REPO / "data" / "county_source_registry.csv").open(encoding="utf-8")))
    for r in rows:
        if r["purchase_url"] and PP.is_document_url(r["purchase_url"]):
            assert r["purchase_path_mode"] == "application", r["source_id"]
    horry = next(r for r in rows if r["source_id"] == "sc_horry_forfeited_land")
    assert (horry["purchase_url"], horry["purchase_url_kind"], horry["purchase_path_mode"]) == (HORRY_PDF, "bid_form", "application")


def test_publication_status_of_the_five_sources_is_unchanged():
    ids = ("mi_detroit_landbank_lots", "mi_detroit_landbank_programs", "mi_oceana_landbank",
           "sc_horry_forfeited_land", "sc_georgetown_forfeited_land")
    rows = {r["source_id"]: r for r in csv.DictReader((REPO / "data" / "county_source_registry.csv").open(encoding="utf-8"))}
    for sid in ids:
        assert EX.PUBLICATION[sid][0] == "UNREVIEWED", sid
        assert rows[sid]["publication_status"] == "UNREVIEWED", sid


def test_frontend_mirrors_the_offline_form_rule():
    m = re.search(r"const ACQUISITION_MODE_LABELS = \{(.*?)\n\};", APP, re.S).group(1)
    assert 'bid: "Bid application required - purchase process not online"' in m
    pp = APP[APP.index("function purchasePathOf"):APP.index("function inventoryCardHtml")]
    # a property-action kind at source scope, or on a downloadable form, is the county's process
    assert 'p.purchase_path_scope === "source" || isDocumentUrl(p.purchase_url)' in pp
    assert "function isDocumentUrl(u)" in APP                               # hoisted: safe on the first render
    acq = APP[APP.index("function acquisitionOf"):APP.index("function acquisitionContactHtml")]
    assert '"bid" : "application"' in acq
