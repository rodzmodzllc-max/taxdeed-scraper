"""Three first-class customer ledgers (2026-09-30): AUCTIONS / AVAILABLE /
LIENS & CERTIFICATES - harvesters/ledgers, the registry's ledger
participation, per-ledger status isolation, certificate-vs-property
semantics, the Arizona certificate adapter, and FL / TX regression."""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import inventory_status as IS  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.ledgers import (BLOCKED_SOURCE_IDS, CUSTOMER_NAMES, LEDGER_STATUSES, SOURCE_LEDGERS, Ledger,  # noqa: E402
                                ledger_for_ledger_type, ledger_for_row, ledger_for_source, ledgers_for_source_id)
from harvesters.ledgers import domains as D  # noqa: E402
from harvesters.otc.adapters import arizona as AZ  # noqa: E402
import laft_lifecycle as L  # noqa: E402
import laft_status as ls  # noqa: E402
import unit_freshness as U  # noqa: E402

ROWS = csr.load_registry()
T = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
FIX = REPO / "tests/python/fixtures/arizona"


def _names(path: str, col: str = "County") -> set[str]:
    with open(REPO / "data" / path, newline="", encoding="utf-8") as fh:
        return {r[col] for r in csv.DictReader(fh)}


# ==================== 1. the three ledgers, one mapping ====================

def test_l01_three_ledgers_map_source_ledger_type_and_customer_name_one_to_one():
    assert [l.value for l in Ledger] == ["AUCTIONS", "AVAILABLE", "LIENS_CERTIFICATES"]
    assert {l.source for l in Ledger} == {"auction", "laft", "certificate"}
    assert {l.ledger_type for l in Ledger} == {"auctions", "buy", "lien"}
    assert {l.slug for l in Ledger} == {"auctions", "lands", "certificates"}
    assert CUSTOMER_NAMES == {Ledger.AUCTIONS: "Auctions", Ledger.AVAILABLE: "Available", Ledger.LIENS_CERTIFICATES: "Liens & Certificates"}
    for l in Ledger:
        assert ledger_for_source(l.source) is l and ledger_for_ledger_type(l.ledger_type) is l
    with pytest.raises(ValueError):
        ledger_for_source("deed")
    with pytest.raises(ValueError):
        ledger_for_ledger_type("liens")


def test_l02_row_classification_uses_source_then_alias_then_lgbs_raw_status_never_a_guess():
    assert ledger_for_row({"source": "auction"}) is Ledger.AUCTIONS
    assert ledger_for_row({"source": "laft"}) is Ledger.AVAILABLE
    assert ledger_for_row({"source": "certificate"}) is Ledger.LIENS_CERTIFICATES
    assert ledger_for_row({"ledger_type": "lien"}) is Ledger.LIENS_CERTIFICATES
    # LGBS: one feed, two ledgers, split by the vendor's own raw status.
    assert ledger_for_row({"harvester_source": "tx_lgbs", "tx_sale_status": "Scheduled for Online Auction"}) is Ledger.AUCTIONS
    assert ledger_for_row({"harvester_source": "tx_lgbs", "tx_sale_status": "Struck off to Jurisdiction"}) is Ledger.AVAILABLE
    assert ledger_for_row({"harvester_source": "tx_lgbs", "tx_sale_status": "Available for Future Sale"}) is Ledger.AVAILABLE
    # Unknown status, no source: not classifiable - never defaulted.
    assert ledger_for_row({"harvester_source": "tx_lgbs", "tx_sale_status": "Something new"}) is None
    assert ledger_for_row({"county": "Marion"}) is None
    assert ledger_for_row({}) is None


def test_l03_source_ids_feed_the_right_ledger_and_blocked_vendors_feed_none():
    assert ledgers_for_source_id("fl_realauction") == {Ledger.AUCTIONS}
    assert ledgers_for_source_id("fl_lienhub_certificates") == {Ledger.LIENS_CERTIFICATES}
    assert all(ledgers_for_source_id(f"fl_laft_{k}") == {Ledger.AVAILABLE}
               for k in ("pdfs", "html", "pioneer", "realtdm", "orange", "stlucie", "osceola", "hillsborough", "leon"))
    assert ledgers_for_source_id("tx_realauction") == {Ledger.AUCTIONS}
    assert ledgers_for_source_id("tx_lgbs") == {Ledger.AUCTIONS, Ledger.AVAILABLE}
    assert ledgers_for_source_id("az_maricopa_state_cp") == {Ledger.LIENS_CERTIFICATES}
    for sid in ("al_ador_state_land", "ar_cosl_post_auction", "la_ebr_adjudicated"):
        assert ledgers_for_source_id(sid) == {Ledger.AVAILABLE}
    for sid in BLOCKED_SOURCE_IDS:
        assert ledgers_for_source_id(sid) == frozenset() and sid not in SOURCE_LEDGERS
    assert ledgers_for_source_id("tx_govease") == frozenset() and ledgers_for_source_id("not_a_source") == frozenset()
    # No Texas certificate source exists or is mapped.
    assert not any(Ledger.LIENS_CERTIFICATES in v and k.startswith("tx_") for k, v in SOURCE_LEDGERS.items())


def test_l04_statuses_are_partitioned_per_ledger():
    certs = {"certificate_listed", "certificate_redeemed", "certificate_assigned", "certificate_expired"}
    assert certs <= LEDGER_STATUSES[Ledger.LIENS_CERTIFICATES]
    assert not certs & LEDGER_STATUSES[Ledger.AUCTIONS] and not certs & LEDGER_STATUSES[Ledger.AVAILABLE]
    assert {"available_otc", "state_held", "resale_inventory"} <= LEDGER_STATUSES[Ledger.AVAILABLE]
    assert not {"available_otc", "state_held", "resale_inventory", "upcoming"} & LEDGER_STATUSES[Ledger.LIENS_CERTIFICATES]
    assert "upcoming" in LEDGER_STATUSES[Ledger.AUCTIONS] and "upcoming" not in LEDGER_STATUSES[Ledger.AVAILABLE]
    for l in Ledger:
        assert LEDGER_STATUSES[l] <= set(IS.INVENTORY_STATUSES)


# ==================== 2. three harvester domains, isolated ====================

def test_d01_domains_are_isolated_and_every_status_file_belongs_to_exactly_one():
    D.assert_isolated()
    assert [d.name for d in D.DOMAINS] == ["AuctionHarvester", "AvailableHarvester", "LienCertificateHarvester"]
    assert D.domain_for_status_file("out/harvest_all_status.json") is D.AUCTION_HARVESTER
    assert D.domain_for_status_file("harvest_laft_status.json") is D.AVAILABLE_HARVESTER
    assert D.domain_for_status_file("harvest_certificates_status.json") is D.LIEN_CERTIFICATE_HARVESTER
    assert D.domain_for_status_file("harvest_arizona_status.json") is D.LIEN_CERTIFICATE_HARVESTER
    assert D.domain_for_status_file("nope.json") is None
    assert [d.name for d in D.domains_for_source_id("tx_lgbs")] == ["AuctionHarvester", "AvailableHarvester"]
    assert D.domains_for_source_id("tx_pbfcm") == ()
    # Every script a domain names exists in the repository.
    for d in D.DOMAINS:
        for script in d.harvesters + d.sync_scripts:
            assert (REPO / script).is_file(), script
    # The FL harvesters and syncs really read / write the file their domain names.
    assert "harvest_laft_status.json" in (REPO / "scripts/laft_lifecycle.py").read_text(encoding="utf-8")
    assert "harvest_certificates_status.json" in (REPO / "scripts/sync-certificates-to-supabase.ps1").read_text(encoding="utf-8")
    assert "harvest_all_status.json" in (REPO / "scripts/sync-harvest-to-supabase.ps1").read_text(encoding="utf-8")
    assert "harvest_all_status.json" not in (REPO / "scripts/laft_lifecycle.py").read_text(encoding="utf-8")


def test_d02_a_failed_or_unreachable_read_in_one_ledger_closes_nothing_and_never_empties_another():
    now = T.timestamp()
    laft_ok = {"county": "Marion", "harvester": "fl_laft_pdfs", "status": "COMPLETE", "checked_at": T.isoformat(), "rowCount": 3, "state": "FL"}
    laft_down = {"county": "Marion", "harvester": "fl_laft_pdfs", "status": "FAILED", "checked_at": T.isoformat(), "state": "FL",
                 "error_category": "TRANSPORT_HTTP_503"}
    laft_broken = {"county": "Marion", "harvester": "fl_laft_pdfs", "status": "FAILED", "checked_at": T.isoformat(), "state": "FL",
                   "error_category": "PARSE_NO_TABLE"}
    # SOURCE_UNAVAILABLE is the reader-side name for a transport failure; both shapes fail closed.
    assert ls.effective_status(laft_down, now=now) == "SOURCE_UNAVAILABLE"
    assert ls.effective_status(laft_broken, now=now) == "FAILED"
    assert ls.effective_status(laft_ok, now=now) == "COMPLETE"
    g_down = L.county_gates([laft_down], [], now=now, state="FL")["Marion"]
    g_broken = L.county_gates([laft_broken], [], now=now, state="FL")["Marion"]
    assert g_down["status"] == "SOURCE_UNAVAILABLE" and not g_down["closeout_ok"] and not g_down["observed_ok"]
    assert g_broken["status"] == "FAILED" and not g_broken["closeout_ok"] and not g_broken["observed_ok"]
    # An absent row under either gate is skipped, never closed.
    plan = L.plan_lifecycle(L.county_gates([laft_down], [], now=now, state="FL"), L.observed_by_county([]),
                            [{"id": "m1", "county": "Marion", "case_no": "M-1", "status": "active"}])
    assert plan.close == [] and plan.skipped_counties == {"Marion": "SOURCE_UNAVAILABLE"}
    # The AVAILABLE lifecycle reads only the AVAILABLE status file: an entry
    # from the auction / certificate files (different harvester ids) does not
    # gate a LAFT county even when the county name matches.
    assert L.load_expected_units(csr.REGISTRY_PATH, "FL") == csr.expected_harvest_units(ROWS, "FL", ledger="AVAILABLE")
    assert ("fl_realauction", "Marion") not in L.load_expected_units(csr.REGISTRY_PATH, "FL")
    assert ("fl_lienhub_certificates", "Marion") not in L.load_expected_units(csr.REGISTRY_PATH, "FL")


def test_d03_empty_is_only_valid_after_a_successful_read():
    assert ls.STATUSES == ("COMPLETE", "EMPTY", "INCOMPLETE", "FAILED", "SOURCE_UNAVAILABLE", "STALE", "NOT_RUN")
    assert ls.UNAVAILABLE_CATEGORY_PREFIXES == ("TRANSPORT_", "PROXY_", "ACCESS_")
    # A zero that the recorder cannot attribute to an explicit empty signal is INCOMPLETE (laft_status's own rule).
    src = (REPO / "scripts/laft_status.py").read_text(encoding="utf-8")
    assert "INCOMPLETE" in src and "EMPTY" in src
    rec = ls.StatusRecorder("fl_laft_pdfs", source_class="GOVERNMENT_DIRECT", source_id="fl_laft_pdfs", parser_version=1,
                            path=Path("/nonexistent/x.json"), state="FL")
    rec.incomplete("Glades", "PARSE_FORMAT_CHANGE", "zero rows and no empty-list wording", source_url="https://example.invalid/list")
    rec.empty("Hendry", "empty_marker", source_url="https://example.invalid/list")
    rec.failed("Union", "TRANSPORT_HTTP_403_BLOCKED", "403", source_url="https://example.invalid/list")
    by = {e.county: e for e in rec.entries}
    assert by["Glades"].status == "INCOMPLETE" and by["Hendry"].status == "EMPTY" and by["Union"].status == "FAILED"
    # An EMPTY entry records the source's own wording; a transport failure reads as SOURCE_UNAVAILABLE.
    assert ls.effective_status(by["Hendry"].to_json(), now=T.timestamp()) == "EMPTY"
    assert ls.effective_status(by["Union"].to_json(), now=T.timestamp()) == "SOURCE_UNAVAILABLE"


# ==================== 3. registry: ledger participation ====================

def test_r01_every_production_source_names_its_ledger_and_the_registry_agrees_with_source_ledgers():
    assert "ledgers" in csr.OPTIONAL_COLUMNS and csr.LEDGER_VALUES == ("AUCTIONS", "AVAILABLE", "LIENS_CERTIFICATES")
    prod = [r for r in ROWS if r.is_production]
    assert prod and all(r.ledgers for r in prod)
    for r in prod:
        assert r.ledger_set == {l.value for l in ledgers_for_source_id(r.source_id)}, (r.source_id, r.county)
    for r in ROWS:
        if r.source_id in BLOCKED_SOURCE_IDS:
            assert r.ledger_set == frozenset()
        if r.inventory_type:
            assert "AVAILABLE" in r.ledger_set or not r.ledger_set


def test_r02_auction_and_certificate_rows_mirror_the_harvesters_own_county_lists():
    fl_auction = {r.county: r for r in ROWS if r.state == "FL" and r.ledger_set == {"AUCTIONS"}}
    assert set(fl_auction) == _names("realauction_counties.csv") | {"Okaloosa"} and len(fl_auction) == 47
    assert fl_auction["Okaloosa"].source_id == "fl_bid4assets_okaloosa" and "bid4assets.com/OkaloosaFLTax" in fl_auction["Okaloosa"].canonical_url
    for county, row in fl_auction.items():
        if county != "Okaloosa":
            assert row.source_id == "fl_realauction" and row.harvester == "harvest_all_counties.ps1"
            assert re.fullmatch(r"https://[a-z-]+\.(realtaxdeed|realforeclose|realauction)\.com/index\.cfm\?zaction=USER&zmethod=CALENDAR", row.canonical_url), row.canonical_url
        assert row.is_production and row.inventory_type == "" and row.source_authority == "VENDOR_AUCTION"
    with open(REPO / "data/florida_certificate_sale_platforms.csv", newline="", encoding="utf-8") as fh:
        lienhub = {r["County"] for r in csv.DictReader(fh) if r["Platform"] == "LienHub"}
    fl_cert = {r.county: r for r in ROWS if r.state == "FL" and r.ledger_set == {"LIENS_CERTIFICATES"}}
    assert set(fl_cert) == lienhub and len(fl_cert) == 32
    for county, row in fl_cert.items():
        slug = re.sub(r"[^a-z]", "", county.lower())
        assert row.canonical_url == f"https://lienhub.com/county/{slug}/countyheld/certificates" and row.source_id == "fl_lienhub_certificates"
        assert row.harvester == "harvest_lienhub_certificates.ps1" and row.inventory_type == ""
    tx_auction = {r.county: r for r in ROWS if r.state == "TX" and r.ledger_set == {"AUCTIONS"}}
    assert set(tx_auction) == _names("tx_realauction_counties.csv") and len(tx_auction) == 24
    assert all(r.source_id == "tx_realauction" and r.is_production for r in tx_auction.values())
    # A non-LienHub certificate platform county has NO certificate row: nothing is invented for it.
    assert "Baker" not in fl_cert and csr.lookup(ROWS, "FL", "Baker", "fl_lienhub_certificates") is None


def test_r03_expected_units_are_scoped_per_ledger():
    assert len(csr.expected_harvest_units(ROWS, "FL")) == 52                                   # default: AVAILABLE
    assert len(csr.expected_harvest_units(ROWS, "FL", ledger="AVAILABLE")) == 52
    assert len(csr.expected_harvest_units(ROWS, "FL", ledger="AUCTIONS")) == 47
    assert len(csr.expected_harvest_units(ROWS, "FL", ledger="LIENS_CERTIFICATES")) == 32
    assert len(csr.expected_harvest_units(ROWS, "FL", ledger=None)) == 52 + 47 + 32
    assert len(csr.expected_harvest_units(ROWS, "TX", ledger="AVAILABLE")) == 8                # LGBS only
    assert len(csr.expected_harvest_units(ROWS, "TX", ledger="AUCTIONS")) == 24 + 8            # RealAuction + LGBS
    assert csr.expected_harvest_units(ROWS, "TX", ledger="LIENS_CERTIFICATES") == []           # no TX certificate ledger
    # A county name shared by two ledgers is two units, never one.
    assert ("fl_laft_realtdm", "Alachua") in csr.expected_harvest_units(ROWS, "FL", ledger="AVAILABLE")
    assert ("fl_realauction", "Alachua") in csr.expected_harvest_units(ROWS, "FL", ledger="AUCTIONS")
    assert ("fl_lienhub_certificates", "Alachua") in csr.expected_harvest_units(ROWS, "FL", ledger="LIENS_CERTIFICATES")


def test_r04_validator_rejects_cross_ledger_shapes_and_accepts_the_committed_ones():
    base = csr.lookup(ROWS, "FL", "Alachua", "fl_realauction")
    assert base is not None and csr.validate_row(base) == []
    kw = {c: getattr(base, c) for c in csr.EXTENDED_COLUMNS}
    def row(**ch):
        return csr.CountySourceRow(**{**kw, **ch})
    assert any("does not feed AVAILABLE" in p for p in csr.validate_row(row(inventory_type="POST_SALE_FIXED_PRICE")))
    assert any("ledgers" in p for p in csr.validate_row(row(ledgers="DEEDS")))
    assert any("names no ledger" in p for p in csr.validate_row(row(source_id="fl_unknown_thing", ledgers="")))
    blocked = next(r for r in ROWS if r.source_id == "tx_pbfcm")
    bk = {c: getattr(blocked, c) for c in csr.EXTENDED_COLUMNS}
    assert any("blocked vendor row must feed no ledger" in p for p in csr.validate_row(csr.CountySourceRow(**{**bk, "ledgers": "AVAILABLE"})))
    # A row without the column classifies by its source id (registries written before the column).
    assert row(ledgers="").ledger_set == {"AUCTIONS"} and csr.validate_row(row(ledgers="")) == []
    # The LAFT rule is untouched for the AVAILABLE ledger: an FL AVAILABLE production row must be the fixed-price list.
    laft = csr.lookup(ROWS, "FL", "Marion", "fl_laft_pdfs")
    lk = {c: getattr(laft, c) for c in csr.EXTENDED_COLUMNS}
    assert any("must carry one of" in p for p in csr.validate_row(csr.CountySourceRow(**{**lk, "inventory_type": ""})))


def test_r05_unit_freshness_reports_per_ledger():
    assert U.ledgers_of("fl_realauction") == "AUCTIONS" and U.ledgers_of("fl_lienhub_certificates") == "LIENS_CERTIFICATES"
    assert U.ledgers_of("tx_lgbs") == "AUCTIONS|AVAILABLE" and U.ledgers_of("tx_pbfcm") == ""
    def e(county, source_id, status, **kw):
        return {"county": county, "harvester": source_id, "status": status, "checked_at": T.isoformat(), "state": "FL", "row_count": 1, **kw}
    entries = [U.normalize_entry(e("Alachua", "fl_laft_realtdm", "COMPLETE"), default_state="FL", default_source=None),
               U.normalize_entry(e("Alachua", "fl_realauction", "FAILED", error_category="TRANSPORT_HTTP_403_BLOCKED"), default_state="FL", default_source=None),
               U.normalize_entry(e("Alachua", "fl_lienhub_certificates", "COMPLETE"), default_state="FL", default_source=None)]
    rec, _ = U.merge({}, [x for x in entries if x], at="t")
    assert {k.split("|")[1] for k in rec} == {"fl_laft_realtdm", "fl_realauction", "fl_lienhub_certificates"}
    assert rec["FL|fl_realauction|Alachua"]["ledgers"] == "AUCTIONS" and rec["FL|fl_laft_realtdm|Alachua"]["ledgers"] == "AVAILABLE"
    report = U.public_report(rec, {}, at="t")
    assert report["by_ledger"]["AUCTIONS"]["units"] == 1 and report["by_ledger"]["AVAILABLE"]["units"] == 1 and report["by_ledger"]["LIENS_CERTIFICATES"]["units"] == 1
    # The auction read's failure is counted under AUCTIONS only.
    assert report["by_ledger"]["AVAILABLE"]["stale"] == 0 and report["by_ledger"]["AVAILABLE"]["failing"] == 0
    assert report["by_ledger"]["AUCTIONS"]["stale"] == 1 and report["by_ledger"]["AUCTIONS"]["failing"] == 1
    assert report["by_ledger"]["LIENS_CERTIFICATES"]["current"] == 1


# ==================== 4. certificate vs property sale ====================

def test_c01_a_certificate_is_its_own_record_never_a_property_sale():
    listed = IS.status_for_row({"state": "FL", "source": "certificate", "status": "active"}, today=T.date())
    assert listed.status == "certificate_listed" and listed.basis == "LIST_PRESENCE"
    gone = IS.status_for_row({"state": "FL", "source": "certificate", "status": "notfound"}, today=T.date())
    assert gone.status == "closed" and gone.basis == "LIST_PRESENCE"
    # A certificate that left the list is never a certificate result, and never a property outcome.
    assert gone.status not in IS.RESULT_STATUSES and gone.status not in ("sold", "redeemed")
    for s in ("certificate_redeemed", "certificate_assigned", "certificate_expired"):
        assert s in IS.RESULT_STATUSES and s in IS.LABELS
    # An expired-looking date is not an observed expiry.
    past = IS.status_for_row({"state": "FL", "source": "certificate", "status": "active", "expiration_date": "2020-01-01"}, today=T.date())
    assert past.status == "certificate_listed"
    # The same parcel in AUCTIONS and LIENS_CERTIFICATES are two records under two ledgers.
    assert ledger_for_row({"source": "auction", "parcel": "111"}) is not ledger_for_row({"source": "certificate", "parcel": "111"})
    # The frontend labels carry exactly the vocabulary, including the certificate keys.
    app = (REPO / "public/app.js").read_text(encoding="utf-8")
    m = re.search(r"const INVENTORY_STATUS_LABELS = \{(.*?)\n\};", app, re.S)
    assert m and set(re.findall(r"(\w+): \"", m.group(1))) == set(IS.INVENTORY_STATUSES)
    # Migration 021's constraints accept the certificate values (file, not production).
    sql = (REPO / "scripts/migrations/021_inventory_status_provenance_freshness.sql").read_text(encoding="utf-8")
    assert all(f"'{s}'" in sql for s in ("certificate_listed", "certificate_redeemed", "certificate_assigned", "certificate_expired"))


# ==================== 4b. auction -> available: history preserved across ledgers ====================

def _phase_b():
    """The Phase B writer test's in-memory store and row builders (same
    five-call contract as PostgrestStore, same uniqueness rules as migration 014)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("phase_b_writers", REPO / "tests/python/test_phase_b_auction_event_writers.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_t01_an_unsold_auction_becoming_available_keeps_its_auction_event_and_gets_its_own_record():
    import auction_events_writer as w
    from datetime import date as _date
    B = _phase_b()
    store = B.MemoryStore([B.prop("p-1", "Lee", "2026000001", sale_date="2026-10-06", hs="fl_realauction_lee")])
    w.record_sightings(store, w.sightings_from_fl_harvest([B.fl_row("Lee", "2026000001", "10/06/2026")]),
                       scope=("FL", "auction"), observed_at=B.T1, run_id=B.RUN, complete_counties={"Lee"}, today=_date(2026, 9, 25))
    assert len(store.events) == 1 and store.events[0]["lifecycle"] == "scheduled" and store.events[0]["outcome"] == "unknown"
    # The sale date passes and the row leaves a COMPLETE county read: the event
    # advances by absence but its OUTCOME stays unknown - "unsold" is never inferred.
    w.record_sightings(store, [], scope=("FL", "auction"), observed_at=B.T3, run_id=B.RUN, complete_counties={"Lee"}, today=_date(2026, 10, 7))
    ev = store.events[0]
    # Last seen BEFORE its sale date -> lifecycle 'unknown' (lifecycle_after_absence:
    # it left the feed before the sale could happen; nothing is claimed).
    assert ev["outcome"] == "unknown" and ev["lifecycle"] == "unknown" and len(store.events) == 1
    # The same parcel then appears on the county's Lands Available list: a
    # separate record in a separate ledger with its own status, sharing the
    # property identity (state, county, parcel) and nothing else.
    laft = {"id": "p-2", "state": "FL", "source": "laft", "county": "Lee", "case_no": "2026000001", "parcel": "P", "status": "active"}
    assert ledger_for_row(laft) is Ledger.AVAILABLE and ledger_for_row(store.properties[0]) is Ledger.AUCTIONS
    assert IS.status_for_row(laft, today=_date(2026, 10, 20)).status == "available_otc"
    assert IS.status_for_row(store.properties[0], today=_date(2026, 10, 20)).status != "sold"
    # Recording the AVAILABLE scope touches nothing in the AUCTIONS scope: the
    # auction event is history, never overwritten by the later ledger.
    before = [dict(e) for e in store.events]
    w.record_sightings(store, [], scope=("FL", "laft"), observed_at=B.T3, run_id=B.RUN, complete_counties={"Lee"}, today=_date(2026, 10, 20))
    assert store.events == before and store.events[0]["property_id"] == "p-1"
    # And a certificate on that parcel is a third record: its "sold" would be a
    # certificate sale, never the property's.
    cert = {"id": "p-3", "state": "FL", "source": "certificate", "county": "Lee", "parcel": "P", "case_no": "ACC-1", "status": "active"}
    assert ledger_for_row(cert) is Ledger.LIENS_CERTIFICATES and IS.status_for_row(cert, today=_date(2026, 10, 20)).status == "certificate_listed"


# ==================== 5. Arizona: first non-FL certificate source, gated ====================

def test_a01_arizona_is_registered_not_production_and_the_registry_row_mirrors_the_adapter():
    assert states.is_supported("AZ") and "AZ" not in states.PRODUCTION_STATES and not states.is_activated("AZ")
    az = [r for r in ROWS if r.state == "AZ"]
    assert len(az) == 1
    row = az[0]
    assert row.county == "Maricopa" and row.source_id == AZ.MARICOPA_SOURCE.source_id == "az_maricopa_state_cp"
    assert row.ledger_set == {"LIENS_CERTIFICATES"} and row.inventory_type == ""
    assert row.canonical_url == AZ.MARICOPA_SOURCE.list_url and row.document_url == AZ.MARICOPA_SOURCE.document_url
    assert row.purchase_url == AZ.MARICOPA_SOURCE.application_url and row.purchase_url_kind == "purchase_instructions"
    assert row.verification_status == "SEARCH_EVIDENCE_ONLY" and row.governance_status == "TERMS_NOT_VERIFIED"
    assert row.harvester == "" and not row.is_production and not row.runnable and row.publishing_unit == "COUNTY"
    assert "not activated" in row.notes and "Nothing fetched" in row.notes
    assert not AZ.can_run(AZ.MARICOPA_SOURCE).allowed
    assert csr.production_rows(ROWS, "AZ") == []


def test_a02_arizona_parser_yields_certificate_records_from_the_synthetic_fixture_and_never_completes():
    text = (FIX / "maricopa_state_cp_SYNTHETIC.csv").read_text(encoding="utf-8")
    records, outcome = AZ.parse_csv(AZ.MARICOPA_SOURCE, text, retrieved_at=T)
    assert records and all(r.record_source == "certificate" and r.inventory_type is None for r in records)
    assert all(r.certificate_no for r in records) and all(r.state == "AZ" and r.county == "Maricopa" for r in records)
    assert all(r.validate() == [] for r in records)
    rows = [r.to_harvest_row() for r in records]
    assert all(row["source"] == "certificate" and row["state"] == "AZ" for row in rows)
    assert all(ledger_for_row(row) is Ledger.LIENS_CERTIFICATES for row in rows)
    for r in records:
        prow = r.to_properties_row()
        assert prow["source"] == "certificate" and prow.get("inventory_type") in (None, "")
    oc = AZ.classify_outcome(AZ.MARICOPA_SOURCE, records, outcome, url=AZ.MARICOPA_SOURCE.document_url)
    assert oc.status == "INCOMPLETE" and oc.status not in ("COMPLETE", "EMPTY")
    # No parcel = no identity = rejected, counted, and the document is never EMPTY.
    text2 = (FIX / "maricopa_state_cp_noparcel_SYNTHETIC.csv").read_text(encoding="utf-8")
    records2, outcome2 = AZ.parse_csv(AZ.MARICOPA_SOURCE, text2, retrieved_at=T)
    oc2 = AZ.classify_outcome(AZ.MARICOPA_SOURCE, records2, outcome2, url=AZ.MARICOPA_SOURCE.document_url)
    assert oc2.status in ("INCOMPLETE", "FAILED") and oc2.status != "EMPTY"


def test_a03_arizona_harvest_refuses_before_the_first_request_and_the_script_writes_its_own_status_file(tmp_path):
    calls = []
    def fetch(url):
        calls.append(url)
        raise AssertionError("must not be called")
    with pytest.raises(RuntimeError, match="may not run"):
        AZ.harvest(AZ.MARICOPA_SOURCE, fetch, retrieved_at=T)
    assert calls == []
    status, out, report = tmp_path / "s.json", tmp_path / "h.json", tmp_path / "r.json"
    r = subprocess.run([sys.executable, "scripts/harvest_state_inventory.py", "--state", "AZ",
                        "--fixture", str(FIX / "maricopa_state_cp_SYNTHETIC.csv"),
                        "--status", str(status), "--out", str(out), "--report", str(report)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    entries = json.loads(status.read_text(encoding="utf-8"))
    entries = entries.get("counties", entries) if isinstance(entries, dict) else entries
    assert all(e.get("state") == "AZ" for e in entries) and {e["status"] for e in entries} == {"INCOMPLETE"}
    rep = json.loads(report.read_text(encoding="utf-8"))
    assert rep["state"] == "AZ" and rep["mode"] == "fixture" and rep["requests"] == 0 and not rep["parser_fixture_validated"]
    assert all(row["source"] == "certificate" for row in json.loads(out.read_text(encoding="utf-8")))
    # Live mode: refused, zero requests.
    live = subprocess.run([sys.executable, "scripts/harvest_state_inventory.py", "--state", "AZ", "--status", str(tmp_path / "live.json")],
                          capture_output=True, text=True, cwd=REPO)
    assert live.returncode == 2 and "0 requests" in live.stdout and not (tmp_path / "live.json").exists()


# ==================== 6. FL / TX regression ====================

def test_x01_fl_and_tx_behaviour_is_unchanged():
    # FL / TX unchanged; LA joined the production states on 2026-09-30 (state-expansion sprint).
    assert states.PRODUCTION_STATES == {"FL", "TX", "LA", "MI", "WY", "SC", "CO", "WI", "MO", "OK", "PA", "MN", "TN"} and states.is_activated("FL") and states.is_activated("TX")
    # The AVAILABLE rows are byte-for-byte the 109 rows the LAFT / struck-off machinery has always read.
    avail = [r for r in ROWS if r.state in ("FL", "TX") and not (r.ledger_set and "AVAILABLE" not in r.ledger_set)]
    assert len(avail) == 109
    assert len([r for r in avail if r.state == "FL"]) == 67 and len({r.county for r in avail if r.state == "FL"}) == 67
    assert {r.county for r in avail if r.state == "TX" and r.is_production} == {"Galveston", "Liberty", "Leon", "Maverick", "Jim Wells", "Hardin", "Van Zandt", "Goliad"}
    # Texas: LGBS is still the only AVAILABLE production source, still not retried; blocked vendors still carry no URL.
    assert all(r.source_id == "tx_lgbs" and "Do not retry" in r.notes for r in avail if r.state == "TX" and r.is_production)
    assert all(r.canonical_url == "" and r.governance_status == "BLOCKED" for r in ROWS if r.source_id in BLOCKED_SOURCE_IDS)
    assert not any("govease" in r.source_id for r in ROWS if r.is_production)
    # The frontend's three ledgers keep their keys, slugs and TX overrides; no fourth ledger.
    app = (REPO / "public/app.js").read_text(encoding="utf-8")
    assert 'const LEDGER_ORDER = ["auction", "laft", "certificate"];' in app
    assert re.search(r'auction: \{\s*slug: "auctions"', app) and re.search(r'laft: \{\s*slug: "lands"', app) and re.search(r'certificate: \{\s*slug: "certificates"', app)
    assert 'title: "Auctions",' in app and 'title: "Available",' in app and 'title: "Liens & Certificates",' in app
    assert 'title: "OTC Catalog — Struck-Off Inventory"' in app and 'title: "Redeemable Tax Deeds"' in app
    # Alabama / Arkansas: one AVAILABLE-ledger candidate each, registered, never runnable, not activated.
    for code, sid in (("AL", "al_ador_state_land"), ("AR", "ar_cosl_post_auction")):
        rows = [r for r in ROWS if r.state == code]
        assert len(rows) == 1 and rows[0].source_id == sid and rows[0].ledger_set == {"AVAILABLE"}, code
        assert not rows[0].is_production and not rows[0].runnable and not states.is_activated(code) and states.is_supported(code)
    # Louisiana (activated 2026-09-30): its one AVAILABLE source is production and runnable.
    la = [r for r in ROWS if r.state == "LA"]
    assert len(la) == 1 and la[0].source_id == "la_ebr_adjudicated" and la[0].ledger_set == {"AVAILABLE"}
    assert la[0].is_production and la[0].runnable and states.is_activated("LA")
    # Migrations created here are files only (020 / 021 unapplied is asserted by their own live tests).
    for name in ("020_state_extensible_vocabulary.sql", "021_inventory_status_provenance_freshness.sql"):
        assert (REPO / "scripts/migrations" / name).is_file()
    # Root mirror in step with public/ for the deployed bundle.
    for f in ("app.js", "index.html", "tx.html", "styles.css", "sw.js"):
        assert (REPO / f).read_bytes() == (REPO / "public" / f).read_bytes(), f
