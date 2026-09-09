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
    """Run every implemented harvest_*() function and write the combined
    result to out/harvest_texas.json, the file
    scripts/sync-texas-to-supabase.py and .github/workflows/harvest-and-sync.yml's
    `texas` job both expect.

    Vendors still raising NotImplementedError (harvest_pbfcm,
    harvest_govease as of this writing) are skipped with a warning rather
    than failing the whole run - matches this project's existing tolerance
    pattern (e.g. the FL sync scripts' on_conflict fallback, and
    sanity_check_deeds.ps1 tolerating individual county failures) of never
    letting one unfinished/broken piece take down a harvest that otherwise
    has real data to report.
    """
    import json
    from dataclasses import asdict

    out_dir = HERE / "../out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "harvest_texas.json"

    all_rows: list[TexasSaleRow] = []
    for name, fn in SOURCES.items():
        try:
            vendor_rows = fn()
        except NotImplementedError as exc:
            print(f"main: skipping {name} - {exc}", file=sys.stderr)
            continue
        print(f"main: {name} produced {len(vendor_rows)} rows", file=sys.stderr)
        all_rows.extend(vendor_rows)

    out_path.write_text(json.dumps([asdict(r) for r in all_rows], indent=2))
    print(f"main: wrote {len(all_rows)} total TX rows to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
