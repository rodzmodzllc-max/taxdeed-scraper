"""Minimal facts plus a deep link: the owner's decision for RealAuction (2026-10-24).

RealAuction declined (ticket 914220, 2026-10-21) to give "any form of written
permission to use automated means for scanning or crawling our auction
sites". The product owner decided on 2026-10-24 to keep the RealAuction sale
calendars (Florida `fl_realauction`, Texas `tx_realauction`) as an internal risk
acceptance, never as permission, limited to the facts a customer needs to find
the sale and go to the county's own auction site:

  county, sale date, case number, certificate number, parcel, situs address,
  the published opening / minimum bid, the sale's published status, and links
  to the county's auction page and the county property appraiser.

Everything else the vendor's pages carry is not stored from them: assessed or
market values, legal descriptions, coordinates and any other descriptive
field. Those come only from a source with its own record (for Florida, the DOR
statewide parcel data under written permission).

This module is the one list of those columns. The Texas sync applies it to
`tx_realauction` rows; the Florida PowerShell sync builds its rows from the
same list, pinned by tests/python/test_permission_decisions_2026_10_24.py.
"""
from __future__ import annotations

MINIMAL_FACT_SOURCES = frozenset({"fl_realauction", "tx_realauction"})

# Row columns a minimal-facts source may write to `properties`. Bookkeeping
# columns (source, state, status, harvester_source) identify the row; they are
# not facts copied from the vendor.
MINIMAL_FACT_COLUMNS = frozenset({
    # identity and bookkeeping
    "state", "source", "county", "case_no", "parcel", "status", "harvester_source",
    # the sale facts
    "address", "bid", "min_bid", "sale_date", "tx_sale_status",
    # links to the official pages (copying nothing)
    "url_auction", "url_auction_kind", "url_appraiser",
})


def minimal_row(row: dict, source_id: str | None) -> dict:
    """The row as a minimal-facts source may write it: unchanged for any other
    source, otherwise only MINIMAL_FACT_COLUMNS kept (a dropped column is
    omitted, never sent as null, so a value another source wrote stays)."""
    if source_id not in MINIMAL_FACT_SOURCES:
        return row
    return {k: v for k, v in row.items() if k in MINIMAL_FACT_COLUMNS}
