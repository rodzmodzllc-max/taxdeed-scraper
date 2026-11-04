"""Acquisition-evidence persistence across inventory syncs (2026-10-05).

Production, 2026-10-04: scripts/sync_state_inventory.py upserted each adapter
row's own otc_provenance (layer / identifier / coordinates facts) with
PostgREST merge-duplicates, which REPLACES the jsonb column - and 3,500 East
Baton Rouge rows lost the verified acquisition record (steps, office,
contacts, Request to Purchase form, evidence page) the laft lifecycle had
written, while keeping purchase_path_type. These tests reproduce that read and
pin the merge rules. No network, no database."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(1, str(REPO))

import sync_state_inventory as SYNC  # noqa: E402

UNITS = {"East Baton Rouge": "COMPLETE"}
VERIFIED = {
    "source_id": "la_ebr_adjudicated", "list_url": "https://data.brla.gov/x",
    "purchase_evidence_url": "https://www.brla.gov/DocumentCenter/View/795/Adjudicated-Memo-PDF",
    "purchase_evidence_type": "county_document", "purchase_evidence_title": "Adjudicated Property memorandum",
    "purchase_instructions": "Request to purchase through the Office of the Parish Attorney",
    "purchase_path_observed_on": "2026-10-01",
    "acquisition": {"mode": "multi_step", "channels": ["application", "phone", "mail"], "office": "Office of the Parish Attorney",
                    "phone": "(225) 389-3114", "application_url": "https://www.brla.gov/DocumentCenter/View/9351/REQUEST",
                    "steps": ["Confirm the property is still adjudicated", "Call the Parish Attorney's Office", "Open a file"],
                    "evidence_url": "https://www.brla.gov/DocumentCenter/View/795/Adjudicated-Memo-PDF", "observed_on": "2026-10-01"},
    "source_match": {"identifier": "case_no", "value": "012-3456-7"},
}
STORED_PATH = {"purchase_path_type": "county_instructions", "purchase_path_scope": "source",
               "purchase_path_evidence": "Parish Attorney's page (fixture)", "purchase_path_observed_on": "2026-10-01",
               "purchase_url": "https://www.brla.gov/455/Adjudicated-Property", "purchase_url_kind": "purchase_instructions"}


def _row(**kw):
    base = {"state": "LA", "source": "laft", "county": "East Baton Rouge", "case_no": "012-3456-7", "source_id": "la_ebr_adjudicated",
            "address": "10 FIXTURE AVE", "bid": 0, "purchase_amount": None, "purchase_amount_kind": "NOT_PUBLISHED",
            "inventory_type": "ADJUDICATED_PROPERTY", "list_as_of": "2024-02-27", "status": "active",
            "otc_provenance": {"adapter": "socrata_csv", "identifier": "assessment_number", "coordinates": "published", "amount": None}}
    base.update(kw)
    return base


def _stored(prov=None, **cols):
    out = {"harvester_source": "la_ebr_adjudicated", "otc_provenance": copy.deepcopy(VERIFIED if prov is None else prov)}
    out.update(STORED_PATH)
    out.update(cols)
    return out


def _plan(rows, stored, state="LA", units=UNITS):
    return SYNC.plan(state, rows, SYNC.registry_rows(state), units, stored_rows=stored)


KEY = ("laft", "East Baton Rouge", "012-3456-7")


# ==================== the production failure ====================

def test_p01_reproduces_the_overwrite_and_preserves_the_verified_record():
    """The 2026-10-04 read: an adapter row whose otc_provenance has no
    acquisition keys, over a stored verified record. Before the fix the row's
    dict was sent as-is (the record vanished); now the record survives intact
    and the adapter's facts are refreshed beside it."""
    sent, counts = _plan([_row()], {KEY: _stored()})
    prov = sent[0]["otc_provenance"]
    assert prov["acquisition"] == VERIFIED["acquisition"]
    for k in ("purchase_evidence_url", "purchase_evidence_type", "purchase_evidence_title", "purchase_instructions",
              "purchase_path_observed_on", "source_match"):
        assert prov[k] == VERIFIED[k], k
    assert prov["adapter"] == "socrata_csv" and prov["identifier"] == "assessment_number"
    assert counts["acquisition_preserved"] == 1
    # The source does not state its own path: the stored path columns are not sent at all.
    assert "purchase_path_type" not in sent[0] and "purchase_url" not in sent[0]


def test_p02_without_a_stored_row_the_adapter_dict_is_sent_unchanged():
    sent, counts = _plan([_row()], {})
    assert sent[0]["otc_provenance"] == _row()["otc_provenance"]
    assert not any(k.startswith("acquisition_") for k in counts)


def test_p03_a_blank_value_never_overwrites_a_stored_fact():
    stored = _stored(prov=dict(VERIFIED, coordinates="published", identifier="assessment_number"))
    sent, _ = _plan([_row(otc_provenance={"adapter": "socrata_csv", "coordinates": None, "identifier": ""})], {KEY: stored})
    prov = sent[0]["otc_provenance"]
    assert prov["coordinates"] == "published" and prov["identifier"] == "assessment_number"


# ==================== richer vs weaker ====================

def _with_acq(acq, observed="2026-10-05"):
    return {"adapter": "arcgis", "purchase_path_observed_on": observed, "acquisition": acq,
            "purchase_evidence_url": acq.get("evidence_url", "")}


def test_r01_weaker_evidence_never_replaces_richer():
    weak = {"mode": "instructions", "channels": ["instructions"], "observed_on": "2026-10-05"}
    sent, counts = _plan([_row(otc_provenance=_with_acq(weak))], {KEY: _stored()})
    assert sent[0]["otc_provenance"]["acquisition"] == VERIFIED["acquisition"]
    assert sent[0]["otc_provenance"]["purchase_path_observed_on"] == "2026-10-01"     # the record's own date, not spliced
    assert counts["acquisition_preserved"] == 1


def test_r02_equal_or_richer_evidence_replaces_the_stored_record_as_a_unit():
    rich = dict(VERIFIED["acquisition"], steps=VERIFIED["acquisition"]["steps"] + ["An appraisal is ordered"],
                mailing_address="P.O. Box 1471, Baton Rouge, LA 70821", observed_on="2026-10-05")
    sent, counts = _plan([_row(otc_provenance=_with_acq(rich))], {KEY: _stored()})
    prov = sent[0]["otc_provenance"]
    assert prov["acquisition"] == rich and prov["purchase_path_observed_on"] == "2026-10-05"
    # keys the new record did not state are not carried over from the old one
    assert "purchase_instructions" not in prov and "purchase_evidence_title" not in prov
    assert counts["acquisition_replaced_equal_or_richer"] == 1


def test_r03_a_new_record_is_added_where_none_was_stored():
    acq = {"mode": "in_person", "channels": ["in_person"], "steps": ["Bid in person"], "address": "1 Court St", "observed_on": "2026-10-05"}
    sent, counts = _plan([_row(otc_provenance=_with_acq(acq))], {KEY: _stored(prov={"adapter": "socrata_csv"})})
    assert sent[0]["otc_provenance"]["acquisition"] == acq and counts["acquisition_added"] == 1


def test_r04_strength_counts_only_published_fields():
    assert SYNC.acquisition_strength({}) == ()
    assert SYNC.acquisition_strength({"acquisition": {"channels": []}}) == ()            # no mode = no record
    full = SYNC.acquisition_strength(VERIFIED)
    bare = SYNC.acquisition_strength({"acquisition": {"mode": "instructions"}})
    assert full > bare and full[0] == 1 and bare[0] == 0


# ==================== isolation ====================

def test_i01_another_sources_stored_row_is_never_a_merge_base():
    other = _stored(harvester_source="la_some_other_source")
    sent, counts = _plan([_row()], {KEY: other})
    assert "acquisition" not in sent[0]["otc_provenance"]
    assert not any(k.startswith("acquisition_") for k in counts)


def test_i02_identity_isolates_county_and_case_number():
    # The stored record belongs to another parcel / county: same source, different identity.
    stored = {("laft", "East Baton Rouge", "999-0000-0"): _stored(), ("laft", "Orleans", "012-3456-7"): _stored()}
    sent, _ = _plan([_row()], stored)
    assert "acquisition" not in sent[0]["otc_provenance"]


def test_i03_a_different_path_type_never_inherits_the_stored_record():
    new = {"adapter": "arcgis", "purchase_path_observed_on": "2026-10-05",
           "acquisition": {"mode": "in_person", "channels": ["in_person"], "observed_on": "2026-10-05"}}
    row = _row(otc_provenance=new, purchase_path_type="in_person", purchase_path_scope="source",
               purchase_path_evidence="county page (fixture)", purchase_path_observed_on="2026-10-05")
    sent, counts = _plan([row], {KEY: _stored()})
    prov = sent[0]["otc_provenance"]
    assert prov["acquisition"] == new["acquisition"]
    assert "purchase_instructions" not in prov and "purchase_evidence_url" not in prov    # never mixed across path types
    assert sent[0]["purchase_path_type"] == "in_person" and counts["acquisition_path_type_changed"] == 1


def test_i04_state_isolation_rows_of_another_state_are_never_planned():
    sent, counts = _plan([_row(state="SC")], {KEY: _stored()})
    assert sent == [] and counts["wrong_state"] == 1


# ==================== path columns + lifecycle ====================

def test_c01_an_active_row_stating_no_path_keeps_the_stored_path_and_record_together():
    row = _row(purchase_path_type=None, purchase_path_scope=None, purchase_path_evidence=None, purchase_path_observed_on=None)
    sent, counts = _plan([row], {KEY: _stored()})
    r = sent[0]
    for k, v in STORED_PATH.items():
        assert r[k] == v, k                                       # restored, never NULL over a verified path
    assert r["otc_provenance"]["acquisition"] == VERIFIED["acquisition"] and counts["acquisition_preserved"] == 1


def test_c02_a_listing_that_is_no_longer_active_sheds_its_path_as_before():
    row = _row(status="closed", purchase_path_type=None, purchase_path_scope=None, purchase_path_evidence=None,
               purchase_path_observed_on=None, purchase_url=None, purchase_url_kind=None)
    sent, counts = _plan([row], {KEY: _stored()})
    r = sent[0]
    assert r["purchase_path_type"] is None and r["purchase_url"] is None
    assert "acquisition" not in r["otc_provenance"] and "purchase_evidence_url" not in r["otc_provenance"]
    assert counts["acquisition_shed_not_active"] == 1


def test_c03_no_acquisition_url_is_ever_synthesized():
    sent, _ = _plan([_row()], {KEY: _stored()})
    prov = sent[0]["otc_provenance"]
    urls = [v for v in (prov.get("purchase_evidence_url"), prov["acquisition"].get("application_url"),
                        prov["acquisition"].get("evidence_url")) if v]
    known = {VERIFIED["purchase_evidence_url"], VERIFIED["acquisition"]["application_url"], VERIFIED["acquisition"]["evidence_url"]}
    assert set(urls) <= known                                     # only URLs the stored verified record already had
    assert "purchase_url" not in sent[0]


def test_c04_stored_fetch_reads_otc_provenance_and_path_columns():
    src = (REPO / "scripts/sync_state_inventory.py").read_text(encoding="utf-8")
    body = src[src.index("def stored_provenance("):src.index("def upsert(")]
    assert "otc_provenance" in body and "PATH_COLUMNS" in body and "harvester_source" in body
    assert "stored_rows=stored_rows" in src
