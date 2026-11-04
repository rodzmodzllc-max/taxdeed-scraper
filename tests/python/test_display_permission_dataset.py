"""Customer display permission is decided for the ledger's own listing dataset
(2026-10-22, backlog B-04 in docs/source-gap-closure/).

Every Florida `display` record in data/source_permissions.csv names a dataset
(sale_calendar, lands_available, county_held_certificates, ...). The
publication gate used to ask without one, so only '*' records could ever
match and every Florida source came back NO_RECORD - once migration 031 is
applied that would withhold rows the records allow. These tests run against
the real permission file; nothing is stubbed."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import permissions as P  # noqa: E402
from harvesters.governance import publication_state as PS  # noqa: E402
import source_publication as SP  # noqa: E402


def test_a_per_dataset_record_is_honoured_for_its_own_ledger():
    assert P.authorize("fl_laft_html", "display", state="FL", county="Leon").reason_code == "NO_RECORD"
    assert P.listing_display("fl_laft_html", state="FL", county="Leon", ledger="AVAILABLE").allowed
    assert P.listing_display("fl_realauction", state="FL", county="Leon", ledger="AUCTIONS").allowed
    assert P.listing_display("fl_lienhub_certificates", state="FL", county="Leon", ledger="LIENS_CERTIFICATES").allowed


def test_a_record_for_one_ledger_never_authorizes_another():
    assert not P.listing_display("fl_laft_html", state="FL", county="Leon", ledger="AUCTIONS").allowed
    assert not P.listing_display("fl_realauction", state="FL", county="Leon", ledger="AVAILABLE").allowed


def test_a_parcel_geometry_approval_never_authorizes_listings():
    for ledger in (None, "AUCTIONS", "AVAILABLE", "LIENS_CERTIFICATES"):
        assert not P.listing_display("fl_dor_pto_parcel_gis", state="FL", county="Broward", ledger=ledger).allowed


def test_a_star_record_still_applies_to_every_ledger_and_to_none():
    for ledger in (None, "AUCTIONS", "LIENS_CERTIFICATES"):
        assert P.listing_display("co_douglas_county_held_liens", state="CO", county="Douglas", ledger=ledger).allowed


def test_no_record_and_unknown_sources_fail_closed():
    assert not P.listing_display("no_such_source", state="FL", county="Leon", ledger="AVAILABLE").allowed
    assert not P.listing_display("tx_ctsa", state="TX", county="Harris", ledger="AUCTIONS").allowed


def test_the_publication_gate_passes_the_rows_ledger():
    seen = []
    c = PS.Context(now=datetime(2026, 10, 22, tzinfo=timezone.utc))
    c.display_permitted = lambda sid, st, county, ledger=None: seen.append(ledger) or True
    c.source_publication = {"fl_laft_html": "APPROVED_GRANDFATHERED"}
    PS.decide({"id": "x", "state": "FL", "county": "Leon", "source": "laft", "source_id": "fl_laft_html",
               "status": "active"}, c)
    assert seen == ["AVAILABLE"]


def test_the_default_gate_uses_the_real_records_for_florida():
    assert PS._display_permitted("fl_laft_html", "FL", "Leon", "AVAILABLE")
    assert not PS._display_permitted("fl_laft_html", "FL", "Leon", None)


def test_registry_publishable_reads_each_ledger_the_source_feeds():
    reg = {r.source_id: r for r in csr.load_registry() if r.state == "FL"}
    row = next(r for r in reg.values() if r.source_id == "fl_laft_html")
    assert "AVAILABLE" in row.ledger_set
    assert SP.publishable(row) is (SP.effective_publication(row) in SP.PUBLISHABLE_STATUSES)
