"""Source-aware AVAILABLE financial terms (data/available_financial_terms.csv
-> public/available-terms.json). Static checks; no network, no database."""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from harvesters.sources import available_terms as T  # noqa: E402

APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
ROWS = T.load()


def by(state, sid, county="", status=""):
    return next(r for r in ROWS if (r["state"], r["source_id"], r["county"], r["status_raw"]) == (state, sid, county, status))


def test_table_is_valid_and_generated():
    assert T.problems() == []
    assert (ROOT / "public/available-terms.json").read_text(encoding="utf-8") == T.render()
    assert (ROOT / "available-terms.json").read_text(encoding="utf-8") == T.render()      # root mirror


def test_every_collected_available_source_has_terms():
    # The AVAILABLE sources collected today (production audit 2026-10-05).
    collected = {("FL", s) for s in ("fl_laft_pioneer", "fl_laft_hillsborough", "fl_laft_leon", "fl_laft_osceola", "fl_laft_stlucie",
                                     "fl_laft_orange", "fl_laft_html", "fl_laft_pdfs", "fl_laft_realtdm")} | {
        ("LA", "la_ebr_adjudicated"), ("TX", "tx_lgbs"), ("MI", "mi_detroit_landbank_lots"), ("MI", "mi_detroit_landbank_programs"),
        ("MI", "mi_oceana_landbank"), ("MO", "mo_stl_lra_inventory"), ("OK", "ok_oklahoma_county_owned"), ("PA", "pa_fayette_repository"),
        ("MN", "mn_ramsey_tax_forfeit"), ("SC", "sc_horry_forfeited_land"), ("SC", "sc_georgetown_forfeited_land")}
    have = {(r["state"], r["source_id"]) for r in ROWS if not r["county"] and not r["status_raw"]}
    assert collected <= have, collected - have


def test_basis_labels_match_the_frontend():
    js = APP[APP.index("var AVAILABLE_BASIS_LABELS = {"):APP.index("};", APP.index("var AVAILABLE_BASIS_LABELS = {"))]
    assert set(re.findall(r"^  ([A-Z_]+): ", js, re.M)) == set(T.BASES)


def test_application_costs_and_deposits_are_never_in_a_price():
    la = by("LA", "la_ebr_adjudicated")
    assert la["basis"] == "OFFER_NEGOTIATED" and la["application_costs"] and la["application_costs_in_price"] == "no"
    assert "advanced costs are not part of the purchase price" in la["quote"]
    gal = by("TX", "tx_lgbs", "Galveston")
    assert gal["deposit"] and gal["deposit_in_price"] in ("no", "unknown")
    # The frontend shows both as their own rows and never adds them.
    rows = APP[APP.index("function acquisitionCostRows(p)"):APP.index("function acquisitionFormsHtml(p)")]
    assert '"Application / advanced costs"' in rows and '"Deposit"' in rows
    body = APP[APP.index("function acquisitionCostBreakdown(p)"):APP.index("function acquisitionForms(p)")]
    assert "application_costs" not in body and "deposit" not in body


def test_program_prices_are_dated_and_restricted():
    side = by("MI", "mi_detroit_landbank_lots", status="Side Lot For Sale")
    assert side["basis"] == "PROGRAM_PRICE" and side["program_price"] == "100"
    assert "2023" in side["program_price_note"] and "confirm" in side["program_price_note"]
    # Conditional program prices carry no bare number.
    for st in ("Neighborhood Lot For Sale", "Oversized Lot For Sale"):
        r = by("MI", "mi_detroit_landbank_lots", status=st)
        assert r["program_price"] == "" and "unless" in r["program_price_note"]


def test_additions_only_on_starting_or_base_figures():
    for r in ROWS:
        if r["additions"]:
            assert r["basis"] in ("OPENING_BID_PLUS_ADDITIONS", "BASE_PRICE_PLUS_ADDITIONS"), r
    assert by("FL", "fl_laft_realtdm")["additions"] == "interest|doc_stamps|recording_fees"
    assert by("FL", "fl_laft_html", "Putnam")["basis"] == "ESTIMATE" and not by("FL", "fl_laft_html", "Putnam")["additions"]


def test_unverified_claims_are_not_recorded():
    # Horry's "minimum bid = taxes + penalties + 15% fee" is search-index only
    # (docs/available-publication-evidence.md) - it must not be in the terms.
    horry = by("SC", "sc_horry_forfeited_land")
    assert "15%" not in json.dumps(horry) and not horry["included_in_figure"] and not horry["additions"]


def test_validator_rejects_unsafe_rows():
    base = {c: "" for c in T.COLUMNS}
    base.update(state="FL", source_id="fl_laft_pioneer", basis="MINIMUM_BID", quote="q", evidence="e", observed_on="2026-10-05")
    bad = dict(base, additions="interest", included_in_figure="x")           # additions on a plain minimum bid
    assert any("additions are only meaningful" in p for p in T.problems([bad]))
    bad = dict(base, basis="OPENING_BID_PLUS_ADDITIONS", additions="delinquent_taxes", included_in_figure="x")
    assert any("unknown addition" in p for p in T.problems([bad]))
    bad = dict(base, application_costs="$50 fee")                             # must say in-price or not
    assert any("application cost must say" in p for p in T.problems([bad]))
    bad = dict(base, basis="OFFICIAL_PRICE", quote="")
    assert any("official price" in p for p in T.problems([bad]))
