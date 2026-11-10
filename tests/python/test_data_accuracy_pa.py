"""Pennsylvania data-accuracy regressions (2026-11-09).

PA-1: the State rules ledger copy said "awaiting review" for sources the owner
approved for customer publication on 2026-10-26, and its eligibility link was a
superseded dated file. PA-3: the City of Pittsburgh's own portal was registered
as published by Allegheny County.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from harvesters.governance.county_source_registry import load_registry, validate_registry
from harvesters.governance.states import PublishingUnit, get_state

ROOT = Path(__file__).resolve().parents[2]
APPROVED = {"APPROVED", "APPROVED_GRANDFATHERED"}


def _ledgers():
    return list(csv.DictReader((ROOT / "data/state_ledgers.csv").open(encoding="utf-8")))


def test_ledger_copy_never_says_awaiting_review_for_approved_available_sources():
    rows = load_registry()
    for led in _ledgers():
        if led["ledger"] != "AVAILABLE":
            continue
        avail = [r for r in rows if r.state == led["state"] and "AVAILABLE" in (r.ledgers or "AVAILABLE").split("|")]
        if avail and all(r.publication_status in APPROVED for r in avail):
            text = " ".join(led[k] for k in ("note", "eligibility_basis", "meaning"))
            assert "awaiting review" not in text.lower(), led["state"]


def test_pa_available_copy_names_both_sources_as_published_and_links_the_sale_page():
    pa = next(r for r in _ledgers() if r["state"] == "PA" and r["ledger"] == "AVAILABLE")
    assert "City of Pittsburgh" in pa["note"] and "Fayette" in pa["note"]
    assert "approved for customer publication 2026-10-26; legal review pending" in pa["note"]
    # The Repository Sale page (the harvester's own page), never a dated file that is replaced.
    assert pa["eligibility_source_url"] == "https://www.fayettecountypa.org/930/Repository-Sale"
    assert "DocumentCenter" not in pa["eligibility_source_url"]
    page = json.loads((ROOT / "public/state-rules.json").read_text(encoding="utf-8"))
    ledger = json.dumps(page["states"]["PA"]["ledgers"]["AVAILABLE"])
    assert "awaiting review" not in ledger.lower()
    assert "Repository-Update-10-7-2025" not in ledger


def test_pittsburgh_is_published_by_the_city_not_the_county():
    rows = [r for r in load_registry() if r.source_id == "pa_pittsburgh_city_property"]
    assert rows, "the Pittsburgh source is registered"
    for r in rows:
        assert r.publishing_unit == PublishingUnit.MUNICIPALITY.value
        assert r.publishing_unit_name == "City of Pittsburgh"
        assert "Allegheny County" not in r.publishing_unit_name
    # Fayette stays a county publisher.
    fay = [r for r in load_registry() if r.source_id == "pa_fayette_repository"]
    assert fay and all(r.publishing_unit == "COUNTY" and r.publishing_unit_name == "Fayette County" for r in fay)
    assert PublishingUnit.MUNICIPALITY.value in get_state("PA").publishing_units
    assert not [p for p in validate_registry(load_registry()) if "pa_pittsburgh" in str(p)]


def test_pittsburgh_has_an_official_candidate_page_but_no_invented_verified_path():
    # PA-2: a candidate page moves the unit to NEEDS_REVIEW; it is never a verified path until a capture is read.
    cands = [r for r in csv.DictReader((ROOT / "data/acquisition_candidate_pages.csv").open(encoding="utf-8"))
             if r["source_id"] == "pa_pittsburgh_city_property"]
    assert cands and all(r["url"].startswith("https://www.pittsburghpa.gov/") for r in cands)
    ev = json.loads((ROOT / "public/acquisition-evidence.json").read_text(encoding="utf-8"))
    units = [u for u in ev["status"] if u.get("source_id") == "pa_pittsburgh_city_property"]
    assert units and all(u["status"] == "NEEDS_REVIEW" for u in units)
    for name in ("data/purchase_path_evidence.csv", "data/purchase_path_evidence_expansion.csv"):
        assert "pa_pittsburgh_city_property" not in (ROOT / name).read_text(encoding="utf-8")
