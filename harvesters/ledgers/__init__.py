"""The three first-class customer ledgers (2026-09-30).

    AUCTIONS               property in a tax sale / auction process
    AVAILABLE              property purchasable / applicable for AFTER a sale, or
                           through another verified government-held process
    LIENS & CERTIFICATES   the lien / certificate product itself - never the land

They are three products with three harvesting domains, three lifecycles,
three freshness ledgers and three customer surfaces - not three filters
over one feed. What they SHARE is the property intelligence layer
(identity, parcel, county, legal description, name assessed, tax-roll
values, acreage, land use, homestead, coordinates, imagery, FDOR
enrichment, provenance), which every ledger's row references through the
same `properties` columns.

HOW THE EXISTING SCHEMA ALREADY CARRIES THIS - nothing here is a second
architecture:
  * `properties.source` (auction | laft | certificate) is the ledger
    discriminator on every row, and `properties.ledger_type`
    (auctions | buy | lien - migration 003, kept in sync by a trigger) is
    its cross-state alias. `Ledger` below is the single mapping between
    those two spellings, the harvest-side ids and the customer names.
  * A property row is the CURRENT state of one record in one ledger:
    (state, source, county, case_no). The same parcel may hold a row in
    more than one ledger over time (an auction that failed becomes an
    AVAILABLE record; a certificate row and a deed-auction row for the same
    parcel are two records).
  * History lives beside the current row, never over it: `auction_events`
    + `auction_event_observations` (migration 014) for AUCTIONS;
    `inventory_status_observations` (migration 021) for every ledger's
    status changes; `field_provenance` / `otc_provenance` for origin.
  * Each domain has its OWN status file, harvest file, sync script and
    close-out gate (`domains.py`); `domains.assert_isolated()` proves no
    file is shared, so a failure in one ledger can never read as "empty"
    in another.
"""
from __future__ import annotations

from enum import Enum

__all__ = ["Ledger", "LEDGER_BY_SOURCE", "LEDGER_BY_LEDGER_TYPE", "CUSTOMER_NAMES", "ledger_for_source",
           "ledger_for_ledger_type", "ledger_for_row", "ledgers_for_source_id"]


class Ledger(str, Enum):
    AUCTIONS = "AUCTIONS"
    AVAILABLE = "AVAILABLE"
    LIENS_CERTIFICATES = "LIENS_CERTIFICATES"

    @property
    def source(self) -> str:
        """properties.source value (the row discriminator every sync writes)."""
        return {"AUCTIONS": "auction", "AVAILABLE": "laft", "LIENS_CERTIFICATES": "certificate"}[self.value]

    @property
    def ledger_type(self) -> str:
        """properties.ledger_type value (migration 003's cross-state alias)."""
        return {"AUCTIONS": "auctions", "AVAILABLE": "buy", "LIENS_CERTIFICATES": "lien"}[self.value]

    @property
    def customer_name(self) -> str:
        return CUSTOMER_NAMES[self]

    @property
    def slug(self) -> str:
        """The frontend route slug (public/app.js LEDGERS[...].slug)."""
        return {"AUCTIONS": "auctions", "AVAILABLE": "lands", "LIENS_CERTIFICATES": "certificates"}[self.value]


CUSTOMER_NAMES = {
    Ledger.AUCTIONS: "Auctions",
    Ledger.AVAILABLE: "Available",
    Ledger.LIENS_CERTIFICATES: "Liens & Certificates",
}

LEDGER_BY_SOURCE = {l.source: l for l in Ledger}
LEDGER_BY_LEDGER_TYPE = {l.ledger_type: l for l in Ledger}

# Inventory types (migration 017 / 020 vocabulary) that belong to the
# AVAILABLE ledger. An auction row carries none; a certificate row carries none.
AVAILABLE_INVENTORY_TYPES = frozenset({"POST_SALE_FIXED_PRICE", "STRUCK_OFF_HELD_IN_TRUST", "FUTURE_RESALE", "POST_SALE",
                                       "STATE_HELD_TAX_LAND", "ADJUDICATED_PROPERTY"})

# The normalized inventory statuses (harvesters/governance/inventory_status.py)
# each ledger may carry. A status outside its ledger's set is a
# classification bug, not a customer state.
LEDGER_STATUSES = {
    Ledger.AUCTIONS: frozenset({"upcoming", "active", "sold", "redeemed", "withdrawn", "cancelled", "struck_off", "closed", "unknown"}),
    Ledger.AVAILABLE: frozenset({"available_otc", "state_held", "resale_inventory", "struck_off", "sold", "redeemed", "withdrawn",
                                 "cancelled", "active", "closed", "unknown"}),
    Ledger.LIENS_CERTIFICATES: frozenset({"certificate_listed", "certificate_redeemed", "certificate_assigned", "certificate_expired",
                                          "closed", "unknown"}),
}

# harvest-side source ids -> the ledger(s) they feed. A vendor that publishes
# both a sale calendar and post-sale inventory (LGBS) feeds two ledgers; its
# rows are told apart by the row's own status (harvesters/texas_harvester.py
# LGBS_STATUS_TO_LEDGER), never by guess.
SOURCE_LEDGERS: dict[str, frozenset[Ledger]] = {
    # Florida
    "fl_realauction": frozenset({Ledger.AUCTIONS}),
    "fl_bid4assets_okaloosa": frozenset({Ledger.AUCTIONS}),
    "fl_lienhub_certificates": frozenset({Ledger.LIENS_CERTIFICATES}),
    "fl_laft_pdfs": frozenset({Ledger.AVAILABLE}), "fl_laft_html": frozenset({Ledger.AVAILABLE}),
    "fl_laft_pioneer": frozenset({Ledger.AVAILABLE}), "fl_laft_realtdm": frozenset({Ledger.AVAILABLE}),
    "fl_laft_orange": frozenset({Ledger.AVAILABLE}), "fl_laft_stlucie": frozenset({Ledger.AVAILABLE}),
    "fl_laft_osceola": frozenset({Ledger.AVAILABLE}), "fl_laft_hillsborough": frozenset({Ledger.AVAILABLE}),
    "fl_laft_leon": frozenset({Ledger.AVAILABLE}),
    # Texas (existing restrictions untouched: LGBS is never retried here; blocked vendors feed nothing)
    "tx_realauction": frozenset({Ledger.AUCTIONS}),
    "tx_lgbs": frozenset({Ledger.AUCTIONS, Ledger.AVAILABLE}),
    "tx_hctax": frozenset({Ledger.AVAILABLE}),
    # Registered, not activated states
    "al_ador_state_land": frozenset({Ledger.AVAILABLE}),
    "ar_cosl_post_auction": frozenset({Ledger.AVAILABLE}),
    "la_ebr_adjudicated": frozenset({Ledger.AVAILABLE}),
    "az_maricopa_state_cp": frozenset({Ledger.LIENS_CERTIFICATES}),
    # Six-state expansion (2026-09-30): owner-approved county sources (harvesters/otc/adapters/expansion.py)
    "mi_eaton_treasurer_sale": frozenset({Ledger.AUCTIONS}),
    "mi_lenawee_tax_sale": frozenset({Ledger.AUCTIONS}),
    "wy_albany_tax_sale": frozenset({Ledger.AUCTIONS}),
    "sc_york_tax_sale": frozenset({Ledger.AUCTIONS}),
    "co_morgan_county_held_certificates": frozenset({Ledger.LIENS_CERTIFICATES}),
    "wi_green_tax_deed_sales": frozenset({Ledger.AUCTIONS}),
    # Five-state enrichment sprint (2026-10-01): Douglas CO (CC BY-SA 4.0) and the
    # implemented-but-UNREVIEWED county sources (harvesters/otc/adapters/expansion.py PUBLICATION)
    "co_douglas_county_held_liens": frozenset({Ledger.LIENS_CERTIFICATES}),
    "co_douglas_tax_sale_list": frozenset({Ledger.AUCTIONS}),
    "co_morgan_treasurer_deed_auctions": frozenset({Ledger.AUCTIONS}),
    "wi_dane_tax_deed_auction": frozenset({Ledger.AUCTIONS}),
    "sc_oconee_tax_sale_list": frozenset({Ledger.AUCTIONS}),
    # AVAILABLE implementation sprint (2026-10-02): government-held property the
    # source offers for acquisition; collected and held until publication review.
    "mi_detroit_landbank_lots": frozenset({Ledger.AVAILABLE}),
    "mi_detroit_landbank_programs": frozenset({Ledger.AVAILABLE}),
    "mi_oceana_landbank": frozenset({Ledger.AVAILABLE}),
    "sc_horry_forfeited_land": frozenset({Ledger.AVAILABLE}),
    "sc_georgetown_forfeited_land": frozenset({Ledger.AVAILABLE}),
    # AVAILABLE expansion (2026-10-04): MO / OK / PA / MN, collected for admin use
    # (UNREVIEWED) - docs/available-expansion-2026-10.md.
    "mo_stl_lra_inventory": frozenset({Ledger.AVAILABLE}),
    "ok_oklahoma_county_owned": frozenset({Ledger.AVAILABLE}),
    "pa_fayette_repository": frozenset({Ledger.AVAILABLE}),
    "mn_ramsey_tax_forfeit": frozenset({Ledger.AVAILABLE}),
    # Tennessee (2026-10-08): Shelby County Land Bank (UNREVIEWED) - docs/tennessee-survey.md.
    "tn_shelby_landbank": frozenset({Ledger.AVAILABLE}),
}
# The four blocked Texas vendors: discovery only, they feed no ledger.
BLOCKED_SOURCE_IDS = frozenset({"tx_pbfcm", "tx_mvba", "tx_govease", "tx_ctsa"})


def ledger_for_source(source: str) -> Ledger:
    try:
        return LEDGER_BY_SOURCE[source]
    except KeyError:
        raise ValueError(f"unknown properties.source {source!r}") from None


def ledger_for_ledger_type(ledger_type: str) -> Ledger:
    try:
        return LEDGER_BY_LEDGER_TYPE[ledger_type]
    except KeyError:
        raise ValueError(f"unknown ledger_type {ledger_type!r}") from None


def ledgers_for_source_id(source_id: str) -> frozenset[Ledger]:
    """The ledger(s) a harvest source feeds; empty for a blocked vendor or an
    unknown id (nothing is assumed)."""
    if source_id in BLOCKED_SOURCE_IDS:
        return frozenset()
    return SOURCE_LEDGERS.get(source_id, frozenset())


def ledger_for_row(row: dict) -> Ledger | None:
    """The ledger of a properties row or a harvest row. `source` decides;
    `ledger_type` is accepted as the alias; an LGBS harvest row without a
    `source` is classified by its raw status through the harvester's own
    map. None = not classifiable (nothing is assumed)."""
    source = row.get("source")
    if source in LEDGER_BY_SOURCE:
        return LEDGER_BY_SOURCE[source]
    lt = row.get("ledger_type")
    if lt in LEDGER_BY_LEDGER_TYPE:
        return LEDGER_BY_LEDGER_TYPE[lt]
    status = row.get("sale_status") or row.get("tx_sale_status")
    if row.get("harvester_source") == "tx_lgbs" and status:
        try:
            from ..texas_harvester import LGBS_STATUS_TO_LEDGER
        except Exception:  # pragma: no cover - the harvester module needs its own deps
            LGBS_STATUS_TO_LEDGER = {"Scheduled for Auction": "auction", "Scheduled for Online Auction": "auction",
                                     "Available for Future Sale": "laft", "Struck off to Jurisdiction": "laft"}
        mapped = LGBS_STATUS_TO_LEDGER.get(status)
        return LEDGER_BY_SOURCE.get(mapped) if mapped else None
    return None
