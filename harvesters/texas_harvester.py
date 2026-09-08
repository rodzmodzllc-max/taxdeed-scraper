"""Texas delinquent-tax-sale / struck-off-inventory harvester (ARCHITECTURAL DRAFT).

Status: DRAFT SKELETON, not a working scraper yet. This mirrors the shape of
scripts/harvest_laft_pdfs.py (the Florida LAFT-PDF harvester) - CSV-driven
per-county source list, tolerant HEADER_MAP column aliasing, "never
fabricate a field the source doesn't publish" discipline - but every
vendor-specific parsing function below is a stub. Each Florida harvester in
this project only became trustworthy after a real per-source verification
pass (confirm the URL is live, confirm what the DOM/PDF/API actually looks
like today, confirm which columns are actually populated vs. usually blank,
record all of that in a Notes column). None of that per-vendor pass has
happened yet for Texas - what follows is the confirmed *entry points* this
session's research turned up, not confirmed *scrapers*.

--- What was actually confirmed live this session (2026-09) ---

  1. taxsales.lgbs.com - Linebarger Goggan Blair & Sampson's tax sale
     portal. Confirmed reachable. NOT yet inspected for DOM structure,
     pagination, or per-county URL pattern - that's the first real work
     item before harvest_lgbs() is anything but a stub.

  2. pbfcm.com - Perdue Brandon Fielder Collins & Mott. Confirmed live
     (via search-engine indexing this session; the live site itself was
     unreachable from this sandbox - see the correction below), "struck-
     off tax resale property" PDFs at a predictable URL shape:
         pbfcm.com/docs/taxdocs/resales/<client-slug>taxresale.pdf
     e.g. nacogdochescountytaxresale.pdf, chamberscountytaxresale.pdf.
     This is structurally the closest analog to Florida's laft_pdf_sources
     pattern (per-client PDF, one row per property) - harvest_pbfcm() is
     the best candidate to reach "real" status first, following
     harvest_laft_pdfs.py's own CSV+PDF-table-extraction approach.

     CORRECTION, 2026-09-08 (this is the load-bearing reason the URL
     pattern above says "<client-slug>", not "<countyname>" as an earlier
     draft of this module assumed): PBFCM's resale PDFs are keyed by
     PBFCM's own taxing-unit CLIENT name, which is NOT always "the
     county." Confirmed slugs found this session include county names
     (nacogdochescountytaxresale.pdf, chamberscountytaxresale.pdf,
     matagordacountytaxresale.pdf) but also independent school districts
     and cities (huffmanisdtaxresale.pdf, willisisdtaxresale.pdf,
     channelviewisdtaxresale.pdf, fortbendisdtaxresale.pdf) - a single
     geographic county can have zero, one, or several separate PBFCM
     client lists (one per taxing unit that retained PBFCM), and there is
     no guarantee "<countyname>taxresale.pdf" exists just because the
     county exists.

     Concretely, for the two counties this session was asked to
     prioritize: NO "harriscountytaxresale.pdf" or "fortbendcountytaxresale.pdf"
     was found. Harris County's delinquent-tax collection is represented
     by Linebarger Goggan Blair & Sampson (LGBS), not PBFCM - confirmed
     via a Harris County Tax Office-linked brochure naming Linebarger
     directly - so Harris County struck-off inventory should be sourced
     from harvest_lgbs() or directly from the Harris County Tax Office
     (hctax.net), not harvest_pbfcm(). The one Fort Bend-area PBFCM
     document found is "fortbendisdtaxresale.pdf" - Fort Bend ISD (a
     school district within the county), not a Fort Bend County-wide
     list. Before building a per-county source CSV for this harvester,
     the real next step is enumerating PBFCM's actual client list (their
     taxresale.html page names a client picker, not fetchable from this
     sandbox this session - see below) rather than guessing county-name
     slugs.

     ALSO NOT yet confirmed: the actual column layout inside any of these
     PDFs, whether they're a real table (pdfplumber-extractable) or
     scanned/image-only - pbfcm.com returned a TLS-level connection error
     from both this project's web-fetch tooling and a live browser this
     session (independent of a specific page; the whole site was
     unreachable, which reads as a site-side/network issue rather than a
     bot block, but was not resolved), so no PDF content was actually
     opened and inspected this session despite the URLs above being
     confirmed to exist via search-engine indexing.

  3. liveauctions.govease.com - GovEase, a real online TX tax-deed auction
     vendor, per-county URL pattern:
         liveauctions.govease.com/tx/<countyslug>/<id>/browse
     e.g. liveauctions.govease.com/tx/txwichita/1429/browse.
     Confirmed reachable. NOT yet inspected for whether listing data is
     server-rendered (scrapeable) or loaded via an XHR/JSON API (which
     would be both easier and more robust to target directly - worth
     checking network requests before writing a DOM scraper).

--- Discovered but not yet scoped in Step 1 ---

  - MVBA (mvbalaw.com) - a third major TX delinquent-tax law firm running
    monthly tax sale listings. Found via research, not named in the
    original request. Not yet inspected at all.
  - County Tax Sale App / CTSA (countytaxsaleapp.org) - found via
    research. Not yet inspected at all.
  - hctax.net (Harris County Tax Office) - found this session while
    correcting the Harris-County-via-PBFCM assumption above. Harris
    County publishes its own tax sale FAQ/info directly
    (hctax.net/About/Announcements/Tax Sale FAQs.pdf) alongside using
    LGBS as its collection attorney - worth checking whether the county
    site itself publishes a struck-off/resale list independent of LGBS's
    portal, since a first-party county source is generally more current
    and lower-risk to scrape than a law-firm portal. Not yet inspected.

Neither of the two above is wired into SOURCES below yet - adding them is
future scoping work, flagged here so they aren't silently lost.

--- Output contract ---

UPDATED 2026-09-08, after 003_ledger_type_and_state_isolation.sql: this
session's multi-state query-isolation work split what used to be one
`source` field (both "which ledger" AND "which vendor") into two fields,
because Texas - unlike Florida - has more than one vendor feeding the SAME
ledger (e.g. both LGBS and PBFCM can feed Event Terminal/auction rows for
different counties). `TexasSaleRow.source` below is NOT the vendor tag
anymore - it is one of the three ledger values Florida already uses
('auction' | 'laft' | 'certificate'), so the DB's
sync_ledger_type_from_source trigger derives ledger_type for Texas rows
the exact same way it already does for Florida rows, with zero special-
casing. The vendor tag moved to the new `harvester_source` field.

Every harvest_*() function should normalize to the same row shape,
mirroring the core `properties` schema fields named in the original
request:
    parcel_id, county, state ('TX'), auction_date, min_bid,
    cad_market_value, legal_description, address
plus:
  - `source`: which of the three ledgers this row belongs to, using
    Florida's own three values so the DB trigger derives ledger_type
    for free - 'auction' for a live-bid Sheriff/Constable sale (Event
    Terminal), 'laft' for struck-off/resale inventory (OTC Catalog),
    'certificate' for a redeemable deed already sold (Yield Desk). See
    the open semantic-mismatch note on the 'certificate' mapping in
    public/app.js's LEDGERS comment block and
    claude/fl-tx-region-switcher.md - reusing FL's lien-shaped ledger slot
    for TX's deed-shaped Yield Desk is a surface fit, not a clean one.
  - `harvester_source`: the actual vendor/provenance tag (e.g. 'tx_pbfcm',
    'tx_lgbs', 'tx_govease') so a row can still be traced back to which
    harvester produced it, independent of which ledger it landed in.

Never fabricate a field a source doesn't actually publish - leave it None
and let a later CAD-enrichment pass fill it in if possible, the same
discipline harvest_laft_pdfs.py already follows for Florida (e.g. "Amount
to Purchase" is often simply not published there - it's left null, not
guessed).
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, fields
from pathlib import Path

HERE = Path(__file__).parent
SOURCES_CSV = HERE / "../data/tx_pbfcm_counties.csv"  # NOT YET CREATED - see note below

# Tolerant column-name aliasing for whatever header variants each PBFCM
# per-county PDF turns out to use once real PDFs are opened and compared -
# mirrors HEADER_MAP in harvest_laft_pdfs.py, which exists because
# Florida's per-county LAFT PDFs were NOT consistent about column naming
# even though they came from "the same" program. Populate this for real
# once at least 3-4 PBFCM county PDFs have actually been opened and diffed
# - guessing the aliases ahead of that would repeat the mistake this
# project explicitly avoided for Florida (never assume one source's column
# names transfer unchanged to the next).
HEADER_MAP: dict[str, str] = {
    # "raw pdf column text (lowercased)": "normalized field name"
    # TODO: populate from real PBFCM PDFs, e.g.:
    # "acct #": "parcel_id",
    # "adjudged value": "cad_market_value",
    # "minimum bid": "min_bid",
}


@dataclass
class TexasSaleRow:
    """Normalized output row - the contract every harvest_*() function fills.

    Field selection mirrors the properties columns named in the Step 1
    request plus the 002_add_texas_support.sql additions
    (redemption_expiration_date / max_statutory_return_usd are NOT computed
    here - those are an enrichment-time concern, see
    enrich_property_details_tx.py and tx_yield_calc.py; a harvester's job
    is to capture what the source actually publishes at listing time, not
    to derive anything).

    `source` / `harvester_source` split 2026-09-08 (see the module
    docstring's "Output contract" section) - `source` is the LEDGER
    ('auction' | 'laft' | 'certificate', Florida's own three values so
    003_ledger_type_and_state_isolation.sql's trigger derives ledger_type
    automatically), `harvester_source` is the VENDOR tag
    ('tx_pbfcm' | 'tx_lgbs' | 'tx_govease'). Each harvest_*() function
    should set both - e.g. harvest_pbfcm() emits
    source='laft', harvester_source='tx_pbfcm' for struck-off resale rows
    (PBFCM's resale PDFs are OTC Catalog / struck-off inventory listings,
    not live sale-date auctions - confirm this against real PDF content
    once pbfcm.com is reachable, don't assume every PBFCM row is 'laft'
    without checking, some client lists may turn out to be upcoming-sale
    notices instead of struck-off inventory).
    """

    parcel_id: str | None
    county: str | None
    state: str = "TX"
    auction_date: str | None = None  # ISO 'YYYY-MM-DD' once parsed; raw string is fine as a first pass
    min_bid: float | None = None
    cad_market_value: float | None = None
    legal_description: str | None = None
    address: str | None = None
    source: str = ""  # 'auction' | 'laft' | 'certificate' - which FL-shaped ledger this row belongs to
    harvester_source: str = ""  # 'tx_pbfcm' | 'tx_lgbs' | 'tx_govease' - which vendor produced it


def harvest_pbfcm(limit: int | None = None) -> list[TexasSaleRow]:
    """Harvest PBFCM per-county struck-off resale PDFs.

    STUB. Real implementation, once scoped, should follow
    harvest_laft_pdfs.py's shape closely:
      1. Read a data/tx_pbfcm_counties.csv source list (County, Url,
         Notes) - NOT YET CREATED. Building it means visiting pbfcm.com's
         resales index (if one exists) or testing the
         <countyname>taxresale.pdf slug pattern against a real TX county
         list, and recording in Notes exactly what was found (a real
         table? zero properties? a text notice instead of a table, the
         way harvest_laft_pdfs.py's own Notes column records for at least
         one Florida county?).
      2. For each county, fetch the PDF and extract its table (pdfplumber,
         same as the Florida LAFT-PDF harvester) into rows.
      3. Apply HEADER_MAP once it's populated for real.
      4. Normalize into TexasSaleRow, leaving anything unpublished as None
         rather than guessed.

    Currently returns an empty list - wiring this up for real is the
    concrete next step once the user confirms this scoping.
    """
    raise NotImplementedError(
        "harvest_pbfcm() is an architectural stub - needs a real per-county "
        "source list (data/tx_pbfcm_counties.csv, not yet created) and a "
        "live-verification pass on at least a few counties' actual PDF "
        "structure before this can safely run, following the same "
        "confirm-before-trust discipline used for every Florida LAFT county."
    )


def harvest_lgbs(limit: int | None = None) -> list[TexasSaleRow]:
    """Harvest Linebarger Goggan Blair & Sampson's tax sale portal.

    STUB. taxsales.lgbs.com was confirmed reachable this session but its
    DOM/listing structure, per-county navigation, and whether it's a
    single statewide listing or per-county pages was NOT inspected. First
    real step: load the site, check read_network_requests for an
    underlying JSON API (would be far more robust than DOM scraping if one
    exists), and record findings the way every FL platform's initial
    reconnaissance was recorded before a scraper was written against it.
    """
    raise NotImplementedError(
        "harvest_lgbs() is an architectural stub - taxsales.lgbs.com's "
        "actual page/API structure has not been inspected yet."
    )


def harvest_govease(county_slugs: list[str] | None = None, limit: int | None = None) -> list[TexasSaleRow]:
    """Harvest GovEase's per-county live Texas tax-deed auctions.

    STUB. liveauctions.govease.com/tx/<countyslug>/<id>/browse was
    confirmed as a real, live URL pattern this session (e.g.
    liveauctions.govease.com/tx/txwichita/1429/browse), but:
      - the full list of TX county slugs and their numeric IDs is not yet
        enumerated (may require crawling a county-picker page rather than
        guessing slugs),
      - whether listings are server-rendered or fetched via XHR/JSON is
        not yet checked (check read_network_requests first - if GovEase
        exposes a JSON endpoint, that is a far more reliable integration
        than scraping rendered auction cards, and this project has
        precedent for preferring a confirmed API over DOM scraping
        wherever one exists), and
      - GovEase may gate listings behind a registration/bidder-account
        wall for some counties, the way some FL RealAuction/RealTDM
        counties required session handling - not yet checked.
    """
    raise NotImplementedError(
        "harvest_govease() is an architectural stub - county slug/ID "
        "enumeration and the rendered-HTML-vs-JSON-API question are both "
        "still open."
    )


# Vendors found during this session's research but not yet scoped into
# Step 1 - listed here so they're visible rather than silently dropped.
# Each would need the same live-reconnaissance pass as the three above
# before a harvest_*() stub is even worth writing.
UNSCOPED_CANDIDATE_VENDORS = {
    "mvba": "mvbalaw.com - third major TX delinquent-tax law firm, monthly tax sale listings, not yet inspected",
    "ctsa": "countytaxsaleapp.org - County Tax Sale App, not yet inspected",
}


SOURCES = {
    "tx_pbfcm": harvest_pbfcm,
    "tx_lgbs": harvest_lgbs,
    "tx_govease": harvest_govease,
}


def main() -> None:
    print(
        "texas_harvester.py is an architectural draft - no source below is "
        "live-verified yet. Confirmed entry points: taxsales.lgbs.com, "
        "pbfcm.com/docs/taxdocs/resales/<county>taxresale.pdf, "
        "liveauctions.govease.com/tx/<countyslug>/<id>/browse. Run the "
        "per-vendor reconnaissance pass described in each harvest_*() "
        "docstring before wiring this into a sync job.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
