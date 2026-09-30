"""The three harvester domains - one per ledger - as data (2026-09-30).

Each domain names, for its ledger, exactly which existing scripts harvest,
which status file records per-unit outcomes, which harvest file carries
rows, which sync writes `properties`, what closes a row out, and which
registry source ids participate. The point is ISOLATION: a domain reads
only its own status file, so a failed or partial harvest in one ledger can
never be interpreted as an empty inventory in another. `assert_isolated()`
proves the files are disjoint; the tests pin that every script reads the
file its domain names.

Nothing here runs anything. The scripts are the ones that already exist;
this module is the map of them.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import Ledger, ledgers_for_source_id

__all__ = ["HarvesterDomain", "AUCTION_HARVESTER", "AVAILABLE_HARVESTER", "LIEN_CERTIFICATE_HARVESTER", "DOMAINS",
           "domain_for_ledger", "domains_for_source_id", "domain_for_status_file", "assert_isolated"]


@dataclass(frozen=True)
class HarvesterDomain:
    ledger: Ledger
    name: str                                # the domain's name in code and docs
    harvesters: tuple[str, ...]              # scripts that read sources for this ledger
    status_files: tuple[str, ...]            # per-unit COMPLETE/EMPTY/INCOMPLETE/FAILED records (under out/)
    harvest_files: tuple[str, ...]           # row artifacts (under out/)
    sync_scripts: tuple[str, ...]            # what writes properties for this ledger
    lifecycle: str                           # what advances / closes rows, in one line
    closeout_gate: str                       # the only condition under which an absent row is closed
    history: str                             # where the ledger's history is preserved
    source_ids: tuple[str, ...]              # registry source ids that feed this ledger
    states: tuple[str, ...]                  # states with a source in this ledger (production or registered)

    @property
    def customer_name(self) -> str:
        return self.ledger.customer_name


AUCTION_HARVESTER = HarvesterDomain(
    ledger=Ledger.AUCTIONS, name="AuctionHarvester",
    harvesters=("scripts/harvest_all_counties.ps1", "scripts/harvest_okaloosa_bid4assets.ps1", "harvesters/texas_harvester.py"),
    status_files=("harvest_all_status.json", "harvest_texas_status.json"),
    harvest_files=("harvest_all.json", "harvest_texas.json"),
    sync_scripts=("scripts/sync-harvest-to-supabase.ps1", "scripts/sync-texas-to-supabase.py"),
    lifecycle="scripts/auction_events_writer.py records every sighting as an auction event + observation; "
              "scripts/inventory_status_writer.py sets upcoming / unknown (date passed, no result) / closed; "
              "a result (sold, redeemed, withdrawn, cancelled, struck_off) only from a source-published status",
    closeout_gate="sync-harvest-to-supabase.ps1: an active FL auction row whose sale date has passed is closed only when "
                  "harvest_all_status.json marks its county COMPLETE this run; Texas rows are never closed by absence",
    history="auction_events + auction_event_observations (migration 014); inventory_status_observations (021)",
    source_ids=("fl_realauction", "fl_bid4assets_okaloosa", "tx_realauction", "tx_lgbs"),
    states=("FL", "TX"),
)

AVAILABLE_HARVESTER = HarvesterDomain(
    ledger=Ledger.AVAILABLE, name="AvailableHarvester",
    harvesters=("scripts/harvest_laft_pdfs.py", "scripts/harvest_laft_html.py", "scripts/harvest_laft_realtdm.py",
                "scripts/harvest_laft_pioneer.py", "scripts/harvest_laft_orange.py", "scripts/harvest_laft_stlucie.py",
                "scripts/harvest_laft_osceola.py", "scripts/harvest_laft_hillsborough.py", "scripts/harvest_laft_leon.py",
                "harvesters/texas_harvester.py", "scripts/harvest_alabama_state_land.py", "scripts/harvest_state_inventory.py"),
    status_files=("harvest_laft_status.json", "harvest_alabama_status.json", "harvest_arkansas_status.json", "harvest_louisiana_status.json"),
    harvest_files=("harvest_laft.json", "harvest_laft_html.json", "harvest_laft_realtdm.json", "harvest_laft_pioneer.json",
                   "harvest_laft_orange.json", "harvest_laft_stlucie.json", "harvest_laft_osceola.json",
                   "harvest_laft_hillsborough.json", "harvest_laft_leon.json", "harvest_alabama.json", "harvest_arkansas.json",
                   "harvest_louisiana.json"),
    sync_scripts=("scripts/sync-laft-to-supabase.ps1", "scripts/sync-texas-to-supabase.py"),
    lifecycle="scripts/laft_lifecycle.py: last_seen_at + provenance for rows a COMPLETE/INCOMPLETE county read, reactivation, "
              "gated close-out; scripts/inventory_status_writer.py sets available_otc / state_held / resale_inventory / struck_off / "
              "closed, and sold only from the list's own 'Sold To' column",
    closeout_gate="laft_lifecycle.py: only a county whose harvest_laft_status.json entry is COMPLETE or EMPTY may have absent rows closed; "
                  "FAILED, INCOMPLETE, SOURCE_UNAVAILABLE, STALE and NOT_RUN close nothing",
    history="inventory_status_observations (021); field_provenance / otc_provenance per row",
    source_ids=("fl_laft_pdfs", "fl_laft_html", "fl_laft_pioneer", "fl_laft_realtdm", "fl_laft_orange", "fl_laft_stlucie",
                "fl_laft_osceola", "fl_laft_hillsborough", "fl_laft_leon", "tx_lgbs", "tx_hctax",
                "al_ador_state_land", "ar_cosl_post_auction", "la_ebr_adjudicated"),
    states=("FL", "TX", "AL", "AR", "LA"),
)

LIEN_CERTIFICATE_HARVESTER = HarvesterDomain(
    ledger=Ledger.LIENS_CERTIFICATES, name="LienCertificateHarvester",
    harvesters=("scripts/harvest_lienhub_certificates.ps1", "scripts/harvest_state_inventory.py"),
    status_files=("harvest_certificates_status.json", "harvest_arizona_status.json"),
    harvest_files=("harvest_certificates.json", "harvest_arizona.json"),
    sync_scripts=("scripts/sync-certificates-to-supabase.ps1",),
    lifecycle="sync-certificates-to-supabase.ps1 reconciles a certificate absent from a COMPLETE county's LienHub listing to "
              "'notfound'; scripts/inventory_status_writer.py sets certificate_listed / closed; redemption and assignment are "
              "never inferred from absence (LienHub's county-held list does not say why a certificate left it)",
    closeout_gate="sync-certificates-to-supabase.ps1: only a county harvest_certificates_status.json marks COMPLETE this run",
    history="inventory_status_observations (021); a certificate row is its own record (source='certificate'), distinct from any "
            "auction event or available record on the same parcel",
    source_ids=("fl_lienhub_certificates", "az_maricopa_state_cp"),
    states=("FL", "AZ"),
)

DOMAINS = (AUCTION_HARVESTER, AVAILABLE_HARVESTER, LIEN_CERTIFICATE_HARVESTER)


def domain_for_ledger(ledger: Ledger) -> HarvesterDomain:
    return next(d for d in DOMAINS if d.ledger is ledger)


def domains_for_source_id(source_id: str) -> tuple[HarvesterDomain, ...]:
    return tuple(domain_for_ledger(l) for l in sorted(ledgers_for_source_id(source_id), key=lambda l: l.value))


def domain_for_status_file(name: str) -> HarvesterDomain | None:
    base = name.rsplit("/", 1)[-1]
    for d in DOMAINS:
        if base in d.status_files:
            return d
    return None


def assert_isolated() -> None:
    """No status file, harvest file or source-id set is shared between two
    domains (a vendor that feeds two ledgers, LGBS, is listed in both by
    design and excluded here)."""
    for attr in ("status_files", "harvest_files"):
        seen: dict[str, str] = {}
        for d in DOMAINS:
            for f in getattr(d, attr):
                if f in seen:
                    raise AssertionError(f"{attr}: {f} is shared by {seen[f]} and {d.name}")
                seen[f] = d.name
    for d in DOMAINS:
        for sid in d.source_ids:
            if d.ledger not in ledgers_for_source_id(sid):
                raise AssertionError(f"{d.name} lists {sid} but SOURCE_LEDGERS does not feed {d.ledger.value} from it")
