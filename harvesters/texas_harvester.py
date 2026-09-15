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
    account_number (named parcel_id in the original request - see the
    "harvest_lgbs() shipped" note below for why it was renamed),
    county, state ('TX'), auction_date, min_bid, cad_market_value,
    legal_description, address
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

--- harvest_lgbs() shipped 2026-09-09 ---

Built after a live-verification pass confirmed the API's real field
semantics (see the function's own docstring for the details: pagination,
the `area=TX` parameter NOT actually being a strict state filter, and why
`status` rather than `sale_type` decides the ledger). Two design decisions
worth flagging here because they aren't obvious from the field names alone:

  - `TexasSaleRow.account_number` (LGBS's own CAD parcel/account number,
    e.g. HCAD's 13-digit account format) is what becomes the DB's `case_no`
    - NOT `cause_number`. This looks backwards next to Florida (where
    case_no is the legal case number), but a live sample this session
    showed two different properties (two different account numbers) sharing
    one `cause_nbr` - a single Texas tax suit routinely covers multiple
    parcels. Using cause_number as case_no would let the second parcel's
    upsert silently overwrite the first's row under this table's
    (state, source, county, case_no) unique constraint. account_number
    is always per-parcel, so it's the safe uniqueness key; cause_number
    goes into the DB's `parcel` column instead, as a secondary/display-only
    identifier (matches enrich_property_details_tx.py's _fetch_hcad()/
    _fetch_tad(), which already expect a CAD account number as input - so
    a future enrichment pass should read this table's `case_no` for TX
    rows, not `parcel`).
  - LGBS publishes real per-property lat/lon (`geometry.coordinates`) -
    `TexasSaleRow.latitude`/`longitude` carry that straight through, so
    LGBS-sourced rows can skip scripts/geocode_properties.py's Census
    Geocoder pass entirely (that script already only processes rows where
    latitude IS NULL, so this requires no change there - it will simply
    have nothing to do for these rows).

--- harvest_realauction() shipped 2026-09-14 ---

Texas's own instances of the same RealAuction/RealForeclose platform
Florida's harvest_all_counties.ps1 already scrapes -
`<county>.texas.sheriffsaleauctions.com` (most of the confirmed 24
counties) or `<county>.texas.realforeclose.com` (Montgomery, Travis - a
genuinely different hostname pattern, confirmed live, not just a branding
difference). See the function's own docstring for the full live-
verification writeup: the calendar's CALSELT/dayid markup and AITEM_-block
AJAX pagination are byte-for-byte identical to Florida's, but the
per-property field LABELS are Texas's own ("Cause Number" / "Account
Number" rather than FL's "Case #" / "Parcel ID"), and - exactly like
harvest_lgbs() - the legal Cause Number is not safely unique per parcel
(confirmed live: one cause number can cover several separately-numbered
sub-lots), so Account Number, not Cause Number, is what maps to this
table's uniqueness-bearing `case_no` (via TexasSaleRow.account_number).

data/tx_realauction_counties.csv's hostnames are a mix of individually
browser-confirmed (Smith, Dallas, El Paso, San Patricio, Montgomery,
Travis) and pattern-derived-but-unverified (the remaining 18, built from
the confirmed `<lowercased county name, spaces removed>.texas.
sheriffsaleauctions.com` convention) - see that CSV and the harvester's own
docstring before assuming every row in it has been individually checked.

Known open question, carried over unresolved from the original vendor
research (claude/texas-vendor-reconnaissance.md): Dallas, Ellis, Galveston,
Gregg, Hopkins, Llano, Nueces, Orange, El Paso and Victoria are harvested by
BOTH LGBS and RealAuction. Both vendors' account/parcel-number formats look
county-appraisal-district-native but have not been confirmed to actually
match digit-for-digit for the same physical property, so
sync-texas-to-supabase.py's (county, case_no) de-dup will NOT catch a
same-property row harvested by both vendors unless their account-number
strings happen to be identical - meaning these overlap counties may show
duplicate-but-differently-keyed cards in the app until this is
investigated and resolved. Not fixed here; flagging again so it isn't lost.

--- Production end-to-end verification, 2026-09-14 (run #128, workflow_dispatch) ---

First actual run of this harvester through the real `texas` GitHub Actions
job (not a local/synthetic test). Harvested successfully: tx_lgbs (411 rows,
9 counties) and tx_realauction (25 rows, 4/24 counties with matches) both
ran, combined into 436 total rows written to out/harvest_texas.json. Two
real bugs found and fixed as a direct result of this being a genuine
end-to-end run rather than a unit test:

  1. Sync failed 100% (0 of 436 rows reached Supabase) - `harvester_source`
     is sent in every row's payload but does not exist as a column on the
     live `public.properties` table, even though the migration that adds it
     (003_ledger_type_and_state_isolation.sql) has been committed since
     2026-09-08. Same "migration written, never run against production"
     failure CLAUDE.md already documents for schema-v4/schema-v7. Browser
     automation cannot type the ALTER TABLE itself into the Supabase SQL
     Editor (safety-tooling restriction), so scripts/sync-texas-to-supabase.py
     now omits harvester_source (SEND_HARVESTER_SOURCE = False) until a
     human runs that migration for real - see that script's own comment.
  2. Per-county logging silently said nothing for a county whose calendar
     DID have scheduled dates but whose AJAX pages yielded zero rows with a
     parseable Account Number - indistinguishable in the log from a county
     never visited at all. Hit 6/24 counties this run (Cameron, El Paso,
     Galveston, Gregg, Orange, Victoria), including El Paso, an
     individually browser-confirmed-good hostname - meaning this wasn't
     only a pattern-derived-guess problem. Fixed: harvest_realauction() now
     prints exactly one terminal line per county covering all three
     outcomes (no auction days / N kept / dates-found-but-0-kept), so this
     case is never silently identical to "not visited."

Confirmed working correctly by this run: errors on one county/page never
aborted the run (LGBS's page-6 timeout was caught, logged, and the harvest
continued with what it already had; each RealAuction per-county failure is
independently caught); Account Number (not Cause Number) is what
sync-texas-to-supabase.py maps to case_no (see that script - unchanged by
this pass); the (county, case_no) dedup and county/state/source values all
came out as designed. NOT yet confirmed by this run: whether the 6
dates-found-but-0-kept counties (especially El Paso) are a real parsing gap
or a genuinely-empty calendar - the fix above makes this visible in future
logs, but this run predates the fix, so it wasn't itself distinguishable at
the time. See claude/texas-vendor-reconnaissance.md for the full verification
writeup and the rerun's results.
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

    `account_number` / `cause_number` split, added with harvest_lgbs()
    2026-09-09 - see the module docstring's "harvest_lgbs() shipped" note
    for why `account_number` (the CAD parcel/account id), not
    `cause_number` (the legal tax-suit cause number), is what the sync
    script maps to the DB's uniqueness-bearing `case_no` column.
    """

    account_number: str | None  # CAD parcel/account number - maps to DB `case_no` (see module docstring)
    county: str | None
    state: str = "TX"
    auction_date: str | None = None  # ISO 'YYYY-MM-DD' once parsed; raw string is fine as a first pass
    min_bid: float | None = None
    cad_market_value: float | None = None
    legal_description: str | None = None
    address: str | None = None
    cause_number: str | None = None  # legal tax-suit cause/case number - maps to DB `parcel` (secondary id, see module docstring)
    latitude: float | None = None
    longitude: float | None = None
    source: str = ""  # 'auction' | 'laft' | 'certificate' - which FL-shaped ledger this row belongs to
    harvester_source: str = ""  # 'tx_pbfcm' | 'tx_lgbs' | 'tx_govease' - which vendor produced it


# ---------------------------------------------------------------------------
# Phase 12 (Production Provenance & Data Lineage Integration)
# ---------------------------------------------------------------------------
#
# FIELD_LINEAGE_MAP documents, as DATA (not as per-row Provenance objects -
# see build_row_provenance()'s own docstring for why field-level lineage is
# represented this way), the source-field -> TexasSaleRow-field mapping
# each real harvester actually performs. This is the answer to Phase 12
# Step 4/8's "field -> source -> source field -> transformation" question
# for the two real production sources - read directly from harvest_lgbs()/
# harvest_realauction()'s own row-construction code above, not invented.
# Keyed by harvester_source, matching SourceRecord.source_id.
#
# A value of None means the field is NOT populated by that source (e.g.
# RealAuction publishes no coordinates) - explicitly recorded as "not
# provided" rather than omitted, so a future reader can tell "this source
# doesn't have this field" apart from "nobody documented this yet".
FIELD_LINEAGE_MAP: dict[str, dict[str, str | None]] = {
    "tx_lgbs": {
        "account_number": "account_nbr",
        "county": "county (normalized via _lgbs_normalize_county())",
        "auction_date": "sale_date_only",
        "min_bid": "minimum_bid (parsed via _lgbs_to_float())",
        "cad_market_value": "value (parsed via _lgbs_to_float())",
        "legal_description": "sale_notes",
        "address": "composed from multiple raw fields via _lgbs_compose_address()",
        "cause_number": "cause_nbr",
        "latitude": "geometry.coordinates[1] (parsed via _lgbs_to_float())",
        "longitude": "geometry.coordinates[0] (parsed via _lgbs_to_float())",
        "source": "status (mapped via LGBS_STATUS_TO_LEDGER)",
    },
    "tx_realauction": {
        "account_number": "'Account Number' field (via _realauction_get_field())",
        "county": "data/tx_realauction_counties.csv (the CSV row this harvest came from, not a per-row source field)",
        "auction_date": "the calendar day's dayid attribute (via _realauction_date_to_iso())",
        "min_bid": "'Est. Min. Bid' field (parsed via _realauction_to_float())",
        "cad_market_value": "'Adjudged Value' field (parsed via _realauction_to_float())",
        "legal_description": None,  # not published by this vendor
        "address": "'Property Address' field",
        "cause_number": "'Cause Number' field",
        "latitude": None,  # not published by this vendor - see geocode_properties.py for the ENRICHED-stage backfill
        "longitude": None,
        "source": "constant 'auction' - see harvest_realauction()'s own docstring for why (no struck-off/resale feed)",
    },
}


def build_row_provenance(harvester_source: str, *, retrieved_at: str):
    """Construct a whole-row `Provenance` record (harvesters/governance/
    provenance.py) for one already-harvested row, identified by its
    `harvester_source` (e.g. "tx_lgbs") - the same string every
    TexasSaleRow carries and the same string that survives the
    TexasSaleRow -> out/harvest_texas.json -> sync-script-dict round trip
    (unlike a full TexasSaleRow object, which does not - see this
    function's two real call sites: harvesters/texas_harvester.py's
    main(), which has real TexasSaleRow instances, and
    scripts/sync-texas-to-supabase.py, which only ever has the plain dict
    parsed back from that JSON file - accepting just the id string, the
    one piece of data both call sites actually have, lets one function
    serve both without a TexasSaleRow-shaped adapter). Phase 12
    integration point - closes the gap docs/data-provenance.md's own
    "Remaining risks" #1 named: "No production code path actually
    constructs a Provenance record yet."

    Deliberately WHOLE-ROW, not one Provenance object per field: this
    pipeline harvests and normalizes a listing as a single unit (see
    harvest_lgbs()/harvest_realauction() above - there is no point where
    an individual field exists as a separately-tracked value before the
    full TexasSaleRow is built), and nothing downstream in this codebase
    reads a per-field Provenance object - generating 13 of them per row,
    for thousands of rows, on every harvest run, for a story no code
    consumes would be exactly the over-engineering Phase 12 Step 23 warns
    against. Field-level lineage (Phase 12 Step 4/8's actual objective) is
    answered instead by FIELD_LINEAGE_MAP above, which is real, checkable
    data pulled from this module's own harvesting code, at zero per-row
    runtime cost.

    Stage is NORMALIZED, not RAW: this pipeline never persists the raw
    API/HTML payload anywhere (parsed inline, in-memory, then discarded -
    confirmed by inspection of harvest_lgbs()/harvest_realauction() above,
    neither of which writes the raw response body anywhere) - constructing
    a RAW-stage Provenance would claim a materialized artifact that does
    not exist. See docs/provenance-production-integration.md's "Raw data
    provenance" section for the full accounting of what is and is not
    retained per source.

    `source_url`/`restrictions` come from the existing registry/gate
    (harvesters/governance/registry.py, harvesters/governance/gate.py) -
    the SAME data check_ingestion_gate() already used to decide this row
    was allowed to be harvested at all, not a second, independently
    maintained copy. This is deliberate: provenance must never become an
    alternate path around governance (Phase 12 Step 16) - it is a report
    ON TOP OF that decision, sourced from it directly.
    """
    # Two valid import contexts for this module (see this function's own
    # docstring on its two real call sites): run directly as __main__ (sys.
    # path[0] is this file's own directory, harvesters/, so the bare
    # `governance` package resolves - main()'s existing imports already
    # rely on this) OR imported as `harvesters.texas_harvester` by
    # scripts/sync-texas-to-supabase.py (which only puts the repo ROOT on
    # sys.path, where `governance` isn't a top-level package - only
    # `harvesters.governance` is). Try the bare form first (matches every
    # other import in this file); fall back to the package-qualified form
    # for the second context, rather than forcing the sync script to
    # mutate sys.path further than it already does.
    try:
        from governance import FieldClassification, PipelineStage, Provenance, check_ingestion_gate
        from governance.registry import get_source
    except ImportError:
        from harvesters.governance import FieldClassification, PipelineStage, Provenance, check_ingestion_gate
        from harvesters.governance.registry import get_source

    decision = check_ingestion_gate(harvester_source)
    src = get_source(harvester_source)  # None for an unknown source - get_source() never raises (see registry.py)
    source_url = src.source_url if src is not None else ""

    return Provenance(
        source_id=harvester_source,
        source_url=source_url,
        source_field=None,  # whole-row record - see FIELD_LINEAGE_MAP for per-field detail
        retrieved_at=retrieved_at,
        stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC,  # every TX field harvested to date is public tax-sale data - see docs/data-provenance.md
        restrictions=decision.restrictions,
        is_source_provided=True,
    )


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


LGBS_API_URL = "https://taxsales.lgbs.com/api/property_sales/"
LGBS_PAGE_SIZE = 500  # confirmed live 2026-09-09 that the API honors limit=500

# Authoritative status -> ledger mapping, confirmed 2026-09-09 by
# cross-referencing /api/sale_status/'s 8-value enum against real sampled
# rows. `sale_type` (SALE/RESALE/STRUCK OFF/FUTURE SALE) is NOT reliable
# alone for this: live samples showed a `sale_type=SALE` row can carry
# status "Cancelled", "Sold", or "Struck off to Jurisdiction" - so this
# harvester filters/maps on `status`, never `sale_type`. Statuses not
# listed here (Cancelled, Sold, Stayed, Sale Results Pending) are resolved
# or in-limbo and are dropped entirely rather than defaulted to a ledger.
LGBS_STATUS_TO_LEDGER: dict[str, str] = {
    "Scheduled for Auction": "auction",
    "Scheduled for Online Auction": "auction",
    "Available for Future Sale": "laft",
    "Struck off to Jurisdiction": "laft",
}

# Python's str.title() mis-capitalizes county names with an internal
# capital ("MCLENNAN COUNTY".title() -> "Mclennan" instead of "McLennan") -
# override the TX Mc-prefixed counties. Extend this if a future county is
# found mis-cased (the same Miami-Dade-hyphen lesson in this repo's
# CLAUDE.md "Known landmines" section - verify a naive string transform
# against every real value it will actually see, don't assume).
_LGBS_COUNTY_NAME_OVERRIDES = {
    "Mclennan": "McLennan",
    "Mcculloch": "McCulloch",
    "Mcmullen": "McMullen",
}


def _lgbs_normalize_county(raw: str | None) -> str | None:
    """'HARRIS COUNTY' -> 'Harris' - matches this app's existing
    county-naming convention (Title Case, no "County" suffix - see
    data/realauction_counties.csv and public/app.js), not LGBS's own
    ALL-CAPS-plus-suffix style."""
    if not raw:
        return None
    name = raw.strip()
    if name.upper().endswith(" COUNTY"):
        name = name[: -len(" COUNTY")]
    name = name.strip().title()
    return _LGBS_COUNTY_NAME_OVERRIDES.get(name, name) or None


def _lgbs_to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _lgbs_compose_address(raw: dict) -> str | None:
    street = (raw.get("prop_address_one") or raw.get("street_name") or "").strip()
    city = (raw.get("prop_city") or "").strip().title()
    zipcode = (raw.get("prop_zipcode") or "").strip()
    if not street and not city:
        return None
    pieces = [p for p in [street] if p]
    if city:
        pieces.append(f"{city}, TX{(' ' + zipcode) if zipcode else ''}")
    elif zipcode:
        pieces.append(f"TX {zipcode}")
    return ", ".join(pieces) if pieces else None


def harvest_lgbs(limit: int | None = None) -> list[TexasSaleRow]:
    """Harvest Linebarger Goggan Blair & Sampson's public tax-sale API.

    API confirmed live 2026-09-09 via a real browser session (this
    sandbox's own outbound network cannot reach taxsales.lgbs.com - see
    CLAUDE.md-adjacent notes on _fetch_hcad()/_fetch_tad() in
    enrich_property_details_tx.py for the identical situation: the request
    mechanics below were verified through a separate live-browser fetch
    path, not by running this function from this sandbox):

        GET https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=&offset=

    Unauthenticated, DRF-style pagination (`count`/`next`/`previous`/
    `results`); confirmed the API honors limit=500.

    CRITICAL, confirmed live: `area=TX` is NOT a strict state filter. A
    live sample of `area=TX&status=Scheduled+for+Auction` returned rows
    with `"state":"PA","county":"PHILADELPHIA COUNTY"` interleaved with
    real Texas rows (LGBS also runs Philadelphia County sales through this
    same portal/API). This function filters on each row's own `state`
    field and never trusts the query parameter alone - skipping that
    filter would silently import Pennsylvania properties into this app's
    Texas ledger.

    `limit`, when given, caps the number of TexasSaleRow results returned
    (stops paginating once reached) - useful for a quick smoke test without
    walking the full ~6,500+ row dataset.

    See LGBS_STATUS_TO_LEDGER above for the status->ledger mapping and why
    it keys off `status`, not `sale_type`; see the module docstring's
    "harvest_lgbs() shipped" note for the account_number/cause_number ->
    case_no/parcel mapping and the lat/lon passthrough.
    """
    import json
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    url = f"{LGBS_API_URL}?{urllib.parse.urlencode({'area': 'TX', 'limit': str(LGBS_PAGE_SIZE)})}"

    rows: list[TexasSaleRow] = []
    counties_seen: set[str] = set()
    seen_raw = 0
    skipped_non_tx = 0
    skipped_status: dict[str, int] = {}
    page_num = 0

    while url:
        page_num += 1
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            print(f"harvest_lgbs: request failed on page {page_num} ({url}): {exc}", file=sys.stderr)
            break

        for raw in payload.get("results", []):
            seen_raw += 1

            if raw.get("state") != "TX":
                skipped_non_tx += 1
                continue

            status = raw.get("status")
            ledger = LGBS_STATUS_TO_LEDGER.get(status)
            if ledger is None:
                skipped_status[status] = skipped_status.get(status, 0) + 1
                continue

            county = _lgbs_normalize_county(raw.get("county"))
            account_number = raw.get("account_nbr") or None
            if not county or not account_number:
                continue

            coords = ((raw.get("geometry") or {}).get("coordinates")) or [None, None]
            lon, lat = (list(coords) + [None, None])[:2]

            rows.append(
                TexasSaleRow(
                    account_number=account_number,
                    county=county,
                    auction_date=raw.get("sale_date_only") or None,
                    min_bid=_lgbs_to_float(raw.get("minimum_bid")),
                    cad_market_value=_lgbs_to_float(raw.get("value")),
                    legal_description=(raw.get("sale_notes") or "").strip() or None,
                    address=_lgbs_compose_address(raw),
                    cause_number=raw.get("cause_nbr") or None,
                    latitude=_lgbs_to_float(lat),
                    longitude=_lgbs_to_float(lon),
                    source=ledger,
                    harvester_source="tx_lgbs",
                )
            )
            counties_seen.add(county)

            if limit is not None and len(rows) >= limit:
                url = None
                break

        if url is None:
            break
        url = payload.get("next")
        # Confirmed live: LGBS's own `next` links come back as plain
        # http://, not https:// - upgrade before following so every request
        # after the first stays encrypted.
        if url and url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        if url:
            time.sleep(0.3)  # polite pacing between pages - same rationale as
            # enrich_property_details_tx.py's REQUEST_DELAY_SECONDS

    print(
        f"harvest_lgbs: kept {len(rows)} TX rows across {len(counties_seen)} counties "
        f"({seen_raw} raw rows walked over {page_num} page(s), {skipped_non_tx} non-TX "
        f"rows dropped, dropped-status breakdown: {skipped_status})",
        file=sys.stderr,
    )
    return rows


REALAUCTION_COUNTIES_CSV = HERE / "../data/tx_realauction_counties.csv"
REALAUCTION_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Texas's own field-label vocabulary for this vendor, confirmed live 2026-09-14
# against Dallas County's 10/06/2026 sale (33 of 34 properties still
# pending/"waiting") - genuinely different label text from Florida's own
# RealAuction/RealForeclose skin (which uses "Case #", "Certificate #",
# "Opening Bid", "Assessed Value", "Parcel ID"), so harvest_all_counties.ps1's
# Get-Field label list could NOT simply be reused unchanged even though the
# underlying platform, calendar markup (CALSELT/dayid - see below) and
# AITEM_-block AJAX pagination are all identical to Florida's. Texas's own
# label set: "Sale Type", "Cause Number", "Precinct/Sale Number",
# "Adjudged Value", "Est. Min. Bid", "Account Number", "Property Address".
REALAUCTION_FIELD_LABELS = (
    "Sale Type",
    "Cause Number",
    "Account Number",
    "Adjudged Value",
    "Est. Min. Bid",
    "Property Address",
)


def _realauction_get_field(block: str, label: str) -> str | None:
    """Python port of harvest_all_counties.ps1's Get-Field - same CAD_LBL/
    CAD_DTA pattern the FL script depends on, confirmed live to be the exact
    same markup Texas's RealAuction/RealForeclose skin emits (2026-09-14,
    Dallas County) despite the label TEXT itself differing from Florida's
    (see REALAUCTION_FIELD_LABELS above)."""
    import re

    pat = re.escape(label) + r':(?:@F|<)[\s\S]{0,200}?CAD_DTA\\">\s*([^@<]*(?:<a[^>]*>([^<]*)</a>)?[^@<]*)'
    m = re.search(pat, block)
    if not m:
        return None
    v = m.group(2) if m.group(2) else m.group(1)
    if v is None:
        return None
    v = v.replace('\\"', '"')
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


def _realauction_to_float(value: str | None) -> float | None:
    if not value:
        return None
    import re

    cleaned = re.sub(r"[^0-9.]", "", value)
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _realauction_date_to_iso(mmddyyyy: str) -> str | None:
    try:
        mm, dd, yyyy = mmddyyyy.split("/")
        return f"{yyyy}-{mm}-{dd}"
    except ValueError:
        return None


def harvest_realauction(limit: int | None = None) -> list[TexasSaleRow]:
    """Harvest Texas's RealAuction/RealForeclose county sites
    (`<county>.texas.sheriffsaleauctions.com` / `<county>.texas.realforeclose.com`).

    CONFIRMED LIVE 2026-09-14, resolving the open question left from this
    project's first pass at this vendor (see
    claude/texas-vendor-reconnaissance.md): this is genuinely the same
    RealAuction/RealForeclose platform Florida's harvest_all_counties.ps1
    already scrapes (identical calendar markup, identical AJAX pagination),
    NOT a different skin needing different scraping mechanics. The first
    pass's "zero CALSELT/dayid matches" result was a false alarm caused by
    checking a county (Smith) that simply had no scheduled sale in the
    checked date range - not a markup difference. Verified directly against
    Dallas County:

      - Calendar days with a scheduled sale carry BOTH a `CALSELT` class
        token and a `dayid="MM/DD/YYYY"` attribute on the same `<div
        class="CALBOX ... CALSELT ">` element - byte-for-byte the same
        pattern FL's `CALSELT[^>]*dayid=['"](\\d{2}/\\d{2}/\\d{4})['"]` regex
        depends on.
      - The per-property listing AJAX call
        (`zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD&AREA=W&PageDir=<n>`,
        after first hitting `zaction=AUCTION&zmethod=PREVIEW&AuctionDate=...`
        to seed session state) returns the identical `AITEM_`-delimited
        block format FL's script splits on.
      - Texas's own per-property field LABELS differ from Florida's (see
        REALAUCTION_FIELD_LABELS) - most importantly "Cause Number" (the
        legal tax-suit cause number - confirmed live to carry a "(N)"
        sub-lot suffix, e.g. "TX-23-02150 (3)", matching the
        "Precinct/Sale Number" field's "/3" - i.e. one cause number can
        cover multiple separately-auctioned parcels, the EXACT same
        multi-parcel-per-legal-case risk harvest_lgbs() already found and
        designed around) and "Account Number" (the CAD parcel/account
        number - confirmed live to be per-parcel-unique, e.g.
        "00000478120000000" for Dallas CAD). This harvester therefore maps
        Account Number -> TexasSaleRow.account_number (-> DB `case_no`) and
        Cause Number -> TexasSaleRow.cause_number (-> DB `parcel`),
        mirroring harvest_lgbs()'s account_number/cause_number split for
        exactly the same reason: cause_number is not safely unique per
        parcel, account_number is.

    Every row surfaced this way is, by construction, sitting under a
    specific scheduled AuctionDate on the calendar - unlike LGBS (whose
    single API mixes scheduled-auction and struck-off-inventory rows keyed
    off `status`), RealAuction gives no separate struck-off/resale feed, so
    every row here maps to the 'auction' ledger (Event Terminal), never
    'laft'. The "Sale Type" field was observed BLANK on every sampled
    property this session (all "Tax Sale" calendar entries, none marked
    resale) - if a future run finds it populated with something like
    "RESALE" or "STRUCK OFF", that should be investigated before assuming
    'auction' still applies, the same "don't trust one field name alone"
    lesson harvest_lgbs() already learned from `sale_type`.

    No lat/lon is published by this vendor (unlike LGBS's `geometry`) - left
    None, same as every other non-LGBS source; scripts/geocode_properties.py
    already backfills any row where latitude IS NULL, so this needs no
    special handling here.

    Hostnames for Angelina, Aransas, Atascosa, Caldwell, Cameron, Ellis,
    Galveston, Gregg, Hopkins, Jackson, Kaufman, Llano, Matagorda, Nueces,
    Orange, Tyler, Victoria, Wilson are PATTERN-DERIVED (lowercased county
    name + ".texas.sheriffsaleauctions.com"), not individually browser-
    confirmed - only Smith, Dallas, El Paso, San Patricio (the
    ".sheriffsaleauctions.com" pattern) and Montgomery, Travis (the
    ".texas.realforeclose.com" variant, confirmed live to be genuinely
    different from the rest) were actually loaded and verified this
    session. A wrong pattern-derived hostname fails this function's request
    for that one county (caught and logged below, per-county, same as every
    other per-county failure) rather than crashing the whole harvest -
    correcting a bad guess just means fixing one row in
    data/tx_realauction_counties.csv once it's noticed.

    `limit`, when given, caps total rows returned across all counties
    (stops early) - same contract as harvest_lgbs()'s `limit`.
    """
    import csv as csv_module
    import http.cookiejar
    import re
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    if not REALAUCTION_COUNTIES_CSV.exists():
        print(f"harvest_realauction: {REALAUCTION_COUNTIES_CSV} not found - nothing to harvest", file=sys.stderr)
        return []

    with open(REALAUCTION_COUNTIES_CSV, newline="", encoding="utf-8") as f:
        counties = list(csv_module.DictReader(f))

    rows: list[TexasSaleRow] = []
    seen_keys: set[tuple[str, str]] = set()
    counties_with_matches = 0
    now = __import__("datetime").datetime.now()

    for c in counties:
        county_name = c["County"]
        host = c["Host"]

        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        def _get(url: str, extra_headers: dict | None = None) -> str | None:
            req = urllib.request.Request(url, headers={"User-Agent": REALAUCTION_USER_AGENT, **(extra_headers or {})})
            try:
                with opener.open(req, timeout=25) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                print(f"harvest_realauction: {county_name} request failed ({url}): {exc}", file=sys.stderr)
                return None

        # Walk the current month plus the next 2, same 3-month lookahead
        # harvest_all_counties.ps1 uses, for the same reason: the calendar
        # page only ever shows the currently-displayed month.
        dates: list[str] = []
        for month_offset in range(3):
            total_month = now.month - 1 + month_offset
            year = now.year + total_month // 12
            month = total_month % 12 + 1
            ts_literal = f"{{ts '{year:04d}-{month:02d}-01 00:00:00'}}"
            cal_url = f"https://{host}/index.cfm?zaction=user&zmethod=calendar&selCalDate=" + urllib.parse.quote(ts_literal, safe="")
            html = _get(cal_url)
            if html is None:
                continue
            dates.extend(re.findall(r"CALSELT[^>]*dayid=['\"](\d{2}/\d{2}/\d{4})['\"]", html))
        dates = sorted(set(dates))

        if not dates:
            print(f"harvest_realauction: {county_name} - no auction days in the next 3 months", file=sys.stderr)
            continue

        county_kept = 0
        for date in dates:
            preview_url = f"https://{host}/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate={date}"
            calendar_referer_url = f"https://{host}/index.cfm?zaction=USER&zmethod=CALENDAR"
            _get(preview_url, {"Referer": calendar_referer_url})

            for page in range(12):
                update_url = (
                    f"https://{host}/index.cfm?zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD"
                    f"&AREA=W&PageDir={page}&doR=1&bypassPage=1&test=1"
                )
                txt = _get(
                    update_url,
                    {
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": preview_url,
                    },
                )
                if not txt or "AITEM_" not in txt:
                    break

                blocks = txt.split("AITEM_")[1:]
                if not blocks:
                    break

                new_on_page = 0
                for block in blocks:
                    fields_found = {label: _realauction_get_field(block, label) for label in REALAUCTION_FIELD_LABELS}
                    account_number = fields_found["Account Number"]
                    if not account_number:
                        continue
                    key = (county_name, account_number)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    new_on_page += 1

                    rows.append(
                        TexasSaleRow(
                            account_number=account_number,
                            county=county_name,
                            auction_date=_realauction_date_to_iso(date),
                            min_bid=_realauction_to_float(fields_found["Est. Min. Bid"]),
                            cad_market_value=_realauction_to_float(fields_found["Adjudged Value"]),
                            legal_description=None,  # not published in this feed - see docstring
                            address=fields_found["Property Address"],
                            cause_number=fields_found["Cause Number"],
                            source="auction",  # every row here has a scheduled AuctionDate - see docstring
                            harvester_source="tx_realauction",
                        )
                    )
                    county_kept += 1

                    if limit is not None and len(rows) >= limit:
                        break
                if limit is not None and len(rows) >= limit:
                    break
                if new_on_page == 0:
                    break
                time.sleep(0.2)  # polite pacing between pages, same rationale as harvest_lgbs()
            if limit is not None and len(rows) >= limit:
                break
        if county_kept:
            counties_with_matches += 1
            print(f"harvest_realauction: {county_name} - {county_kept} properties across {len(dates)} sale date(s)", file=sys.stderr)
        else:
            # CONFIRMED LIVE 2026-09-14 (first real workflow_dispatch run):
            # this branch was previously silent - a county whose calendar
            # DID have scheduled dates but whose AJAX pages produced zero
            # rows with a parseable Account Number printed nothing at all,
            # indistinguishable in the log from a county that was never
            # visited. That run hit this exact case for 6 of 24 counties
            # (Cameron, El Paso, Galveston, Gregg, Orange, Victoria) - one
            # of them, El Paso, is an individually browser-confirmed-good
            # hostname, not a pattern-derived guess, so "no log line" could
            # not be trusted to mean
            # "verified empty" - it could equally mean a wrong page
            # structure or a blocked/failed per-page request that didn't
            # itself raise (a non-2xx body without AITEM_ in it, e.g.).
            # Every county now gets exactly one terminal line covering all
            # three outcomes (no auction days / N kept / dates-but-0-kept),
            # so "no source this run" and "something to investigate" are
            # never silently the same thing again.
            print(
                f"harvest_realauction: {county_name} - {len(dates)} sale date(s) found but 0 properties "
                "parsed (calendar loaded; either the sale(s) genuinely list nothing yet, or the page "
                "structure/field labels didn't match what this county's host returned - worth a manual check)",
                file=sys.stderr,
            )
        if limit is not None and len(rows) >= limit:
            break

    print(
        f"harvest_realauction: kept {len(rows)} TX rows across {counties_with_matches}/{len(counties)} counties with matches",
        file=sys.stderr,
    )
    return rows


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
    "tx_realauction": harvest_realauction,
    "tx_govease": harvest_govease,
}


def main() -> None:
    """Run every implemented harvest_*() function and write the combined
    result to out/harvest_texas.json, the file
    scripts/sync-texas-to-supabase.py and .github/workflows/harvest-and-sync.yml's
    `texas` job both expect.

    UPDATED 2026-09-14 (Phase 10A - Commercial Source Governance
    Infrastructure): before calling ANY harvest_*() function, this loop now
    checks harvesters/governance's ingestion gate for that vendor's
    source_id (the same string already used as `harvester_source`, e.g.
    'tx_pbfcm'). A source whose registry status is LEGAL_REVIEW_REQUIRED,
    BLOCKED, DISABLED, or TERMS_CHANGED is skipped WITHOUT calling its
    harvest_*() function at all - this is a strictly additive safety net,
    not a behavior change for any currently-working vendor:
      - tx_lgbs and tx_realauction are both registered APPROVED (reflecting
        their existing, already-shipped, already-verified production
        status - see harvesters/governance/registry.py's own notes on each
        entry), so the gate passes and both run exactly as before. Neither
        harvest_lgbs() nor harvest_realauction() was modified by this phase.
      - tx_pbfcm and tx_govease are both registered BLOCKED (per
        claude/pbfcm-source-reconnaissance-blocked.md and
        claude/govease-source-onboarding-blocked.md) - previously these
        were "called, then caught a NotImplementedError"; now they are
        skipped by the gate before ever being called. The net effect for
        this run's output is identical (both are skipped either way), but
        the gate is now the reason, and it would ALSO catch these two
        sources the moment someone fills in their still-stubbed bodies
        without separately re-reading the blocked-vendor docs - the
        NotImplementedError stub and the gate are two independent layers,
        deliberately redundant.
    Harris County (tx_hctax) is registered LEGAL_REVIEW_REQUIRED and has no
    entry in SOURCES below at all (no harvest_hctax() exists yet) - the
    gate has nothing to check it against in this loop; its registry entry
    exists so the source is representable, per Phase 10A Step 10.
    """
    import json
    from dataclasses import asdict
    from datetime import datetime, timezone

    from governance.gate import check_ingestion_gate

    out_dir = HERE / "../out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "harvest_texas.json"

    # Phase 12 (Production Provenance & Data Lineage Integration): one
    # retrieval timestamp for this entire run - every row harvested below
    # genuinely was retrieved within this one process invocation, so a
    # single shared retrieved_at is an accurate record of the actual
    # retrieval event, not an approximation. Provenance.retrieved_at is
    # documented as "set once, at RAW/NORMALIZED, never updated by
    # advance()/derive()" (docs/data-provenance.md) - this is that value.
    retrieved_at = datetime.now(timezone.utc).isoformat()

    all_rows: list[TexasSaleRow] = []
    rows_by_source: dict[str, int] = {}
    for name, fn in SOURCES.items():
        decision = check_ingestion_gate(name)
        if not decision.allowed:
            print(f"main: skipping {name} - ingestion gate rejected it ({decision.reason})", file=sys.stderr)
            continue

        try:
            vendor_rows = fn()
        except NotImplementedError as exc:
            # Still possible even for a gate-approved source: a source can
            # be legally APPROVED while its harvester remains an
            # unfinished architectural stub. Kept as a second safety net,
            # unchanged from the pre-Phase-10A behavior.
            print(f"main: skipping {name} - {exc}", file=sys.stderr)
            continue
        except Exception as exc:  # noqa: BLE001 - deliberate, see Phase 14A note below
            # Phase 14A (Customer-Safety Hardening): harvest_lgbs()/
            # harvest_realauction() already catch every NETWORK failure
            # internally (urllib.error.URLError/HTTPError/TimeoutError, on
            # a per-page/per-request basis - see each function's own try/
            # except), so this branch is deliberately for everything else:
            # an unexpected response shape, a parsing bug, or any other
            # non-network exception a future vendor change could trigger.
            # Before this fix, an uncaught exception here would propagate
            # out of this loop entirely, meaning tx_lgbs failing would
            # silently prevent tx_realauction from ever running too (dict
            # insertion order runs lgbs before realauction - see SOURCES
            # above) AND prevent out/harvest_texas.json from being written
            # at all, since that write happens after this whole loop -
            # confirmed by tracing this function's control flow, not
            # assumed. This is exactly the vendor-failure-isolation gap
            # docs/phase-14a-customer-safety-hardening.md's freshness audit
            # names as a precondition for ever safely moving Texas off
            # workflow_dispatch-only scheduling: one vendor's future,
            # unanticipated breakage must never silently zero out the
            # other vendor's otherwise-healthy data for that run. Isolating
            # it here does not change today's behavior for either
            # currently-working vendor (both have run clean; this is
            # defense-in-depth for a failure mode that hasn't happened
            # yet, the same "additive, not a behavior change" discipline
            # Phase 10A's own gate check above used).
            print(f"main: {name} raised an unexpected (non-network) error - continuing with remaining sources: {exc}", file=sys.stderr)
            continue
        print(f"main: {name} produced {len(vendor_rows)} rows ({decision.reason})", file=sys.stderr)
        all_rows.extend(vendor_rows)
        rows_by_source[name] = rows_by_source.get(name, 0) + len(vendor_rows)

    out_path.write_text(json.dumps([asdict(r) for r in all_rows], indent=2))
    print(f"main: wrote {len(all_rows)} total TX rows to {out_path}", file=sys.stderr)

    # Phase 12: log one Provenance summary line per source actually
    # harvested this run - not one object per row (see
    # build_row_provenance()'s own docstring for why per-row Provenance is
    # built downstream, in scripts/sync-texas-to-supabase.py, rather than
    # here: every row from the same source in the same run shares
    # identical lineage metadata, so a per-source summary here is a
    # complete, non-redundant audit record of this harvest event, without
    # constructing and immediately discarding thousands of duplicate
    # objects). Ephemeral - printed for audit purposes only, never written
    # to out/harvest_texas.json or Supabase (see Phase 12 Step 19/6 - no
    # schema/file-shape change).
    for name, count in rows_by_source.items():
        prov = build_row_provenance(name, retrieved_at=retrieved_at)
        print(
            f"main: provenance - {count} row(s) from '{name}' @ stage={prov.stage.value}, "
            f"source_url={prov.source_url!r}, restrictions={[r.value for r in prov.restrictions]}, "
            f"retrieved_at={prov.retrieved_at}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
