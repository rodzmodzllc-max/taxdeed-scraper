"""Texas per-parcel CAD enrichment (ARCHITECTURAL DRAFT, not working code).

Status: DRAFT SKELETON. Mirrors scripts/enrich_property_details.py's shape
(env-var-driven batch/limit constants, anti-starvation per-source quotas,
incremental-by-design via an *_enriched_at stamp so successful matches are
never re-fetched while failures retry indefinitely) but the actual per-CAD
fetch/parse logic is stubbed out, for one specific, load-bearing reason
that does not have a Florida analog:

    Florida has ONE statewide enrichment source (the FDOR FeatureServer)
    that every county's parcels can be queried against with the same join
    logic (see claude/parcel-enrichment-and-gis-plan.md). Texas has NO
    confirmed equivalent. Appraisal is administered by 254 independent
    county Central Appraisal Districts (CADs), each running its own site
    and, as far as this session's research found, its own data-access
    mechanics - there is no confirmed single statewide parcel API with
    FDOR-equivalent attribute richness (market value, use code,
    exemptions). TNRIS StratMap Land Parcels
    (tnris.org/stratmap/land-parcels.html) surfaced as a candidate
    statewide TX parcel dataset during research but was NOT live-verified
    this session (no API call was made against it) and is likely
    attribute-poor relative to FDOR even if it pans out (a base parcel
    layer, not necessarily one that carries CAD market value / use code /
    exemption data the way FDOR's tax-roll layer does).

    This is the single biggest open architectural question for this
    deliverable and should be resolved with its own research-and-prove-
    the-join pass - mirroring exactly how claude/parcel-enrichment-and-
    gis-plan.md documents that approach being used for Florida's FDOR
    join - BEFORE real per-CAD enrichment code is written. Committing to
    "one enrichment function per major CAD" (HCAD, TAD, DCAD, BCAD, TCAD,
    ...) as scoped in the original request is a reasonable starting shape,
    but each one needs its own live confirmation that a usable public data
    endpoint exists at all (some CADs publish nothing but a manual
    address-search web form with no stable per-parcel URL or API - that
    would mean no automatable enrichment for that county without a much
    heavier headless-browser approach, a materially different cost/effort
    picture than a JSON API).

    UPDATE 2026-09-08: this de-risks meaningfully for Harris County
    specifically. HCAD publishes a public, unauthenticated ArcGIS REST
    query endpoint (see _fetch_hcad() below) confirmed live this session
    with real market/land/building values and the raw Comptroller SPTB
    code per parcel - a genuine JSON API, not an interactive-form-only
    site. That is exactly the kind of source this module needs and is
    now real, tested-against-live-data code rather than a stub.

    UPDATE 2026-09-08 (later same session): audited TAD/DCAD/BCAD/Travis
    CAD for the same kind of endpoint. Results are mixed, not uniform -
    this is the expected shape for Texas (unlike Florida's one statewide
    source), not a surprise:
      - TAD (Tarrant): a real, RICHER-than-HCAD endpoint confirmed live -
        has valuation, an exemption field, AND building square footage
        (which HCAD's layer lacks). Now real code, not a stub - see
        _fetch_tad(). Its classification and exemption fields are
        unconfirmed-content (truncated field names, values not sampled),
        same caveat level HCAD had before its state_class was sampled.
      - Bexar (BCAD): a real, valuation-rich endpoint confirmed live
        (LAND_VALUE/IMP_VALUE/MKT_VALUE), but its likely classification
        fields have ArcGIS-truncated names not yet sampled, and no
        exemption field was found at all. Still a stub pending that
        sampling - see _fetch_bcad()'s comment block.
      - Dallas (DCAD): no single rich source found. The CAD's own
        service (maps.dcad.org) was unreachable from this project's
        tooling (connectivity, not confirmed absence) both attempts this
        session; a separate City of Dallas layer IS reachable and has
        SPTBCODE + exemption fields but no valuation. Needs a two-source
        join, unproven - see _fetch_dcad()'s comment block.
      - Travis (TCAD): a real, live, but confirmed WEAK endpoint -
        geometry/situs/parcel-ID only, no valuation, no classification,
        no exemption data. A genuinely different source is needed here,
        not yet found - see _fetch_travis_cad()'s comment block.
    So the biggest architectural risk is narrowed further but still not
    closed: 2 of 5 named counties (Harris, Tarrant) now have a real,
    reasonably rich path; Bexar has a real path pending one more
    verification step; Dallas needs an unproven join; Travis needs an
    entirely different source. The original per-CAD-variance premise -
    that Texas enrichment will look meaningfully different county to
    county, unlike Florida's one-source model - is holding up exactly as
    expected.

Everything below is real, working *scaffolding* - the batch loop, the
config constants, the wiring into tx_use_codes.py and tx_yield_calc.py -
built so that once even one CAD's real fetch mechanics are confirmed, only
CAD_FETCHERS needs a real entry added, not a rewrite of this file.
"""

from __future__ import annotations

import os
import random
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(__file__))

from tx_use_codes import category_label, is_probably_agricultural, normalize_category  # noqa: E402
from tx_yield_calc import compute_redemption_terms  # noqa: E402

# --- Config, mirroring enrich_property_details.py's env-driven constants ---

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")  # never log, never commit - see CLAUDE.md

# How many TX rows to attempt per run. Kept modest by default the same way
# enrich_property_details.py's FL batch limit is - a per-CAD fetcher is
# unproven, so a small default limits the blast radius of a bad first run
# against a real CAD site.
BATCH_LIMIT = int(os.environ.get("TX_ENRICH_BATCH_LIMIT", "200"))

# Anti-starvation quota per CAD, same rationale as enrich_property_details.py's
# PER_COUNTY_LIMIT / COUNTY_MISS_STREAK: once real multi-CAD fetching exists,
# a single large or slow CAD (e.g. HCAD, by far the largest Texas county)
# should not be able to consume the whole batch and starve smaller CADs
# every run, which was a real production bug in the FL version before this
# constant existed there.
PER_CAD_LIMIT = int(os.environ.get("TX_ENRICH_PER_CAD_LIMIT", "50"))
CAD_MISS_STREAK = int(os.environ.get("TX_ENRICH_CAD_MISS_STREAK", "20"))

# Polite pacing between requests to any one CAD site - same rationale as
# enrich_property_details.py's REQUEST_DELAY_SECONDS: these are county
# government sites, not a bulk API meant for scraping, so pace requests
# conservatively until each CAD's actual rate-limit tolerance is known.
REQUEST_DELAY_SECONDS = float(os.environ.get("TX_ENRICH_REQUEST_DELAY_SECONDS", "0.5"))

ENRICHED_AT_COLUMN = "tx_cad_enriched_at"  # mirrors *_enriched_at incremental-by-design pattern


# --- Per-CAD fetchers: THE STUBBED PART. Each entry is a confirmed county
# name paired with an unconfirmed fetch function. None of these should be
# trusted to run against production without its own live-verification pass
# (does this CAD expose a stable per-parcel URL or API at all? what does a
# real response actually contain?). Modeled on how each Florida county in
# enrich_property_details.py's fallback-GIS-layer handling was individually
# confirmed (e.g. the Santa Rosa/Flagler special-casing there) rather than
# assumed to work generically. ---

HCAD_ARCGIS_QUERY_URL = (
    "https://www.gis.hctx.net/arcgis/rest/services/HCAD/Parcels/MapServer/0/query"
)

# Confirmed live 2026-09-08 via direct query against HCAD_ARCGIS_QUERY_URL
# (unauthenticated, public ArcGIS REST FeatureServer/MapServer query - same
# mechanism FDOR's layer uses for Florida, not an interactive-form scrape).
# Sample real responses pulled this session:
#   {"HCAD_NUM":"1011020000003","state_class":"A1","land_use":"1001",
#    "total_market_val":199689.0,"land_value":61382.0,"bld_value":138307.0,
#    "Acreage":null}
#   {"HCAD_NUM":"1311220010001","state_class":"F1","land_use":"8001",
#    "total_market_val":3090000.0,"land_value":1575220.0,"bld_value":1514780.0,
#    "Acreage":"1.8081 AC"}
# state_class values (A1, F1, X1 all observed live) match tx_use_codes.py's
# CODE_LABELS keys exactly - HCAD reports the real Comptroller SPTB code,
# not a county-specific variant, which is a meaningfully better outcome
# than the per-CAD-variance caution in tx_use_codes.py's docstring warned
# might be necessary to code around.
#
# Two confirmed gaps, not yet resolved:
#   1. No homestead/exemption flag found among this layer's fields (the
#      full field list was pulled and inspected - see the migration
#      writeup). tx_yield_calc.classify_redemption_period() will fall back
#      to the UNCONFIRMED category-code guess for every HCAD-sourced row
#      until an exemption source is found - possibly HCAD's separate
#      PDATA bulk "Real & Personal Property Database" text-file export
#      (hcad.org/pdata/pdata-property-downloads.html, not yet inspected
#      field-by-field) rather than this GIS layer.
#   2. No building-square-footage field found in this layer either
#      (land_sqft is LAND square footage, not building/improvement sqft) -
#      likely another PDATA-export-only field, same caveat as above.
#   3. Acreage is a free-text string with a unit suffix (e.g. "1.8081 AC"),
#      sometimes null - needs its own parser, not a bare float() cast.
#
# NOT execution-tested from this project's own sandbox: this sandbox's
# outbound network does not reach gis.hctx.net (confirmed - a direct
# request from here fails at the network layer, unrelated to HCAD itself).
# The query mechanics above were confirmed through a separate live fetch
# path, not by running this function. Run and smoke-test this for real
# once it's wired into an environment with real outbound access before
# trusting it in production.
def _fetch_hcad(parcel_id: str, *, market_value_floor: float = 0.0) -> dict | None:
    """Query HCAD's public ArcGIS parcel layer for one account number.

    `parcel_id` should be HCAD's own account number format (e.g.
    "1011020000003" - the HCAD_NUM field), not a FDOR-style parcel ID -
    Texas CADs do not share Florida's parcel-ID conventions, so whatever
    harvester captures a Texas parcel_id needs to capture it in HCAD's own
    format for this join to work. That mapping has not been confirmed
    against real texas_harvester.py output yet, since that harvester is
    itself still a stub - flagging the dependency rather than assuming it
    lines up.
    """
    import json
    import urllib.parse
    import urllib.request

    fields = (
        "HCAD_NUM,state_class,land_use,total_market_val,land_value,"
        "bld_value,impr_value,acreage,land_sqft,legal_dscr_1,owner_name_1"
    )
    params = {
        "where": f"HCAD_NUM='{parcel_id}'",
        "outFields": fields,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{HCAD_ARCGIS_QUERY_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        payload = json.loads(resp.read())

    features = payload.get("features") or []
    if not features:
        return None
    return features[0].get("attributes")


def _parse_hcad_acreage(raw_acreage: str | None) -> float | None:
    """Parse HCAD's free-text acreage field (e.g. "1.8081 AC", or None).

    Confirmed live this session that this field is sometimes null even for
    real, valued parcels (typical platted single-family lots appear to
    report size via land_sqft instead) - callers should not assume a null
    here means missing/bad data.
    """
    if not raw_acreage:
        return None
    digits = raw_acreage.strip().upper().replace("AC", "").strip()
    try:
        return float(digits)
    except ValueError:
        return None


def hcad_attributes_to_generic(attrs: dict) -> dict:
    """Adapt a raw _fetch_hcad() attributes dict to normalize_cad_response()'s
    generic input shape, so HCAD-sourced rows flow through the same
    normalize_cad_response()/compute_yield_fields() pipeline every other CAD
    will eventually use. See _fetch_hcad()'s comment block for exactly
    which fields are confirmed present (market/land/building value,
    state_class as the raw SPTB code) versus confirmed absent so far
    (homestead exemption, building square footage).
    """
    return {
        "market_value": attrs.get("total_market_val"),
        "land_value": attrs.get("land_value"),
        # HCAD splits bld_value (building) from impr_value (all
        # improvements, which may include non-building structures) -
        # bld_value is the closer match to "building value" as named in
        # the Step 1 request; impr_value is kept available on the raw
        # dict for a caller that wants the broader figure instead.
        "improvement_value": attrs.get("bld_value"),
        "acreage": _parse_hcad_acreage(attrs.get("acreage") or attrs.get("Acreage")),
        "building_sqft": None,  # confirmed NOT present in this layer - see _fetch_hcad()'s comment block
        "tx_category": attrs.get("state_class"),
        "homestead_exemption": None,  # confirmed NOT found in this layer - see _fetch_hcad()'s comment block
    }


TAD_ARCGIS_QUERY_URL = (
    "https://mapit.tarrantcounty.com/arcgis/rest/services/Tax/TCProperty/MapServer/0/query"
)

# Confirmed live 2026-09-08 via direct field-list query against
# TAD_ARCGIS_QUERY_URL (unauthenticated ArcGIS REST, same mechanism as
# HCAD above). This layer is actually RICHER than HCAD's: alongside
# LAND_VALUE/IMPR_VALUE/TOTAL_VALU/APPRAISEDV it also carries an
# EXEMPTION_ field (truncated name - real content not yet sampled, but
# this is the homestead-equivalent signal HCAD's layer was confirmed
# missing) and a LIVING_ARE field (building square footage - also
# confirmed missing from HCAD's layer). PARCELTYPE + DESCR look like the
# SPTB-equivalent classification pair but have not been sampled against
# real data the way HCAD's state_class was (see _fetch_hcad()'s comment
# block for that live sample) - treat PARCELTYPE/DESCR as unconfirmed
# until a real query is run and compared against tx_use_codes.py's
# CODE_LABELS, and treat EXEMPTION_'s actual values as unconfirmed until
# sampled too. Also has LAND_ACRES and LAND_SQFT (both, unlike HCAD's
# single ambiguous Acreage field), YEAR_BUILT, BEDROOMS, BATHROOMS.
#
# NOT execution-tested from this project's own sandbox (same network
# limitation as _fetch_hcad() - outbound access to mapit.tarrantcounty.com
# was not available from here either). Field list confirmed via a
# separate live fetch path, not by running this function.
def _fetch_tad(parcel_id: str) -> dict | None:
    """Query TAD's public ArcGIS parcel layer for one account number.

    `parcel_id` should be TAD's own ACCOUNT or TAXPIN field value, not a
    FDOR- or HCAD-style parcel ID - confirm which one texas_harvester.py
    or a TAD-specific lookup step actually captures before wiring this
    in for real.
    """
    import json
    import urllib.parse
    import urllib.request

    fields = (
        "TAXPIN,ACCOUNT,OWNER_NAME,SITUS_ADDR,EXEMPTION_,LEGAL_1,"
        "LAND_VALUE,IMPR_VALUE,TOTAL_VALU,APPRAISEDV,LAND_ACRES,"
        "LAND_SQFT,LIVING_ARE,YEAR_BUILT,PARCELTYPE,DESCR"
    )
    params = {
        "where": f"ACCOUNT='{parcel_id}'",
        "outFields": fields,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{TAD_ARCGIS_QUERY_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        payload = json.loads(resp.read())

    features = payload.get("features") or []
    if not features:
        return None
    return features[0].get("attributes")


def tad_attributes_to_generic(attrs: dict) -> dict:
    """Adapt a raw _fetch_tad() attributes dict to the generic shape
    normalize_cad_response() expects. See _fetch_tad()'s comment block -
    PARCELTYPE/DESCR and EXEMPTION_'s actual real-world values are NOT
    yet sampled, so tx_category and homestead_exemption below are best-
    guess field mappings, not confirmed-correct the way HCAD's are.
    """
    return {
        "market_value": attrs.get("APPRAISEDV") or attrs.get("TOTAL_VALU"),
        "land_value": attrs.get("LAND_VALUE"),
        "improvement_value": attrs.get("IMPR_VALUE"),
        "acreage": attrs.get("LAND_ACRES"),
        "building_sqft": attrs.get("LIVING_ARE"),
        # UNCONFIRMED mapping - DESCR/PARCELTYPE have not been sampled
        # against real data to check whether either one is actually an
        # SPTB code in tx_use_codes.py's format. Do not trust this field
        # until that sample is taken.
        "tx_category": attrs.get("DESCR"),
        # UNCONFIRMED - EXEMPTION_'s real values (a flag? a code? blank
        # when none?) have not been sampled either.
        "homestead_exemption": attrs.get("EXEMPTION_"),
    }


# Confirmed live 2026-09-08: DCAD does NOT have one single rich source -
# it needs a two-source join that has not been proven yet:
#   1. maps.dcad.org/prdwa/rest/services/Property/{ParcelQuery,PropMap}/
#      MapServer - DCAD's OWN ArcGIS service, which should be the richest
#      source (it is the CAD's own data), but was unreachable from this
#      project's tooling both attempts this session (robots.txt-level
#      connection failures, not a confirmed-absent service - this needs
#      a retry from a different network path before being written off).
#   2. egis.dallascityhall.com/arcgis/rest/services/Basemap/
#      DallasTaxParcels/MapServer/0 - the City of Dallas's own GIS
#      (different host, confirmed reachable and live this session).
#      Field list confirmed: has SPTBCODE (a real, live field literally
#      named after the same State Property Tax Board code standard
#      tx_use_codes.py documents - strong independent confirmation of
#      that module's approach), PROP_CL, BLDG_CL, TOTEXEMPT, AREA_FEET,
#      ACCT/GIS_ACCT for the join key - but NO valuation fields
#      (market/land/improvement value) at all.
# Net: this city layer alone can supply tx_category (from SPTBCODE) and
# a homestead-adjacent signal (TOTEXEMPT), but not cad_market_value -
# real enrichment needs maps.dcad.org reachable, or another valuation
# source, joined to this one by ACCT. Not attempted as working code yet -
# the join and the maps.dcad.org connectivity both need to be proven
# first, the same "prove the join, don't assume it" discipline this
# project already applies to Florida's FDOR join.
def _fetch_dcad(parcel_id: str) -> dict | None:
    """Dallas: needs a two-source join, neither half fully proven yet.

    See the comment block above this function for what's confirmed
    (egis.dallascityhall.com's classification/exemption fields) versus
    unresolved (maps.dcad.org's valuation data - connectivity, not
    confirmed absence).
    """
    raise NotImplementedError(
        "DCAD needs a two-source join (egis.dallascityhall.com for "
        "SPTBCODE/exemption + maps.dcad.org for valuation) that has not "
        "been proven yet - maps.dcad.org was unreachable from this "
        "project's tooling this session, not confirmed to lack the data."
    )


# Confirmed live 2026-09-08: services7.arcgis.com/.../Bexar_CAD_Parcels/
# FeatureServer/3 (note the layer's own name literally contains
# "Bexar_CAD_Parcels" - a strong signal this is BCAD's real data, not
# just county GIS boundaries). Field list confirmed rich: LAND_VALUE,
# IMP_VALUE, MKT_VALUE (all three, cleanly named - better than HCAD's
# split of bld_value vs impr_value), LEGAL_AREA/GIS_AREA (acreage,
# though with a separate _U unit-suffix field rather than an embedded
# string like HCAD's "1.8081 AC" - worth checking those unit fields
# before assuming acres), YEAR_BUILT, LEGAL_DESC. Two likely
# classification fields exist but their names are ArcGIS-truncated to 10
# characters (STAT_LAND_, LOC_LAND_U) - almost certainly
# STAT_LAND_USE/LOC_LAND_USE, but NOT sampled against real data yet, so
# it is unconfirmed whether either one carries an SPTB-format code the
# way HCAD's state_class does. No exemption/homestead field identified
# among the 38 fields inspected.
def _fetch_bcad(parcel_id: str) -> dict | None:
    """Bexar: real endpoint confirmed, field-name truncation unresolved.

    See the comment block above this function. Same shape of work as
    _fetch_tad() once STAT_LAND_/LOC_LAND_U are sampled and confirmed to
    (or not to) carry SPTB codes.
    """
    raise NotImplementedError(
        "BCAD's endpoint and field list are confirmed live, but "
        "STAT_LAND_/LOC_LAND_U (the likely classification fields) have "
        "truncated names not yet sampled against real data - confirm "
        "their actual content before writing the query/adapter pair."
    )


# Confirmed live 2026-09-08: gis.traviscountytx.gov/server1/rest/services/
# Boundaries_and_Jurisdictions/TCAD_public/MapServer/0 is real and
# reachable, but - unlike HCAD/TAD/BCAD above - its field list is
# geometry/situs/parcel-ID ONLY (PROP_ID, geo_id, situs_*, tcad_acres,
# legal_desc, a hyperlink field, centroid coordinates). NO valuation,
# NO classification/SPTB code, NO exemption data of any kind. The
# "_public" in this service's own name is a plausible explanation - TCAD
# may keep a richer, non-public-branded layer for internal/licensed use
# that this session did not find. This is the weakest of the four CADs
# audited this session; Travis County enrichment needs either a
# different TCAD/Travis County service found and verified, or a
# different data path entirely (e.g. TCAD's own property-search site,
# travis.prodigycad.com/maps, which was found via search but not
# inspected for an underlying API this session).
def _fetch_travis_cad(parcel_id: str) -> dict | None:
    """Travis: confirmed-live endpoint, confirmed NOT to carry appraisal
    data. See the comment block above this function - this is a
    negative result, not an unexplored one.
    """
    raise NotImplementedError(
        "TCAD_public's ArcGIS layer is live but confirmed to carry only "
        "geometry/situs/parcel-ID fields, no valuation or classification "
        "data - a different Travis County source is needed, not yet "
        "found."
    )


# County name -> fetcher. Deliberately a plain dict, not a CSV-driven list
# like harvest_laft_pdfs.py's SOURCES_CSV, because unlike Florida's
# uniform-FeatureServer join, each CAD is expected to need genuinely
# different fetch code (different site, possibly different data shape) -
# a CSV row wouldn't meaningfully reduce this to config the way it does
# for a set of same-shaped PDF/HTML sources. Worth reconsidering once 3-4
# CADs are real and a common shape (or lack thereof) is actually visible.
CAD_FETCHERS = {
    "harris": _fetch_hcad,
    "tarrant": _fetch_tad,
    "dallas": _fetch_dcad,
    "bexar": _fetch_bcad,
    "travis": _fetch_travis_cad,
}


def normalize_cad_response(raw: dict, tx_category_raw: str | None = None) -> dict:
    """Map a (future, real) CAD response into properties-table fields.

    This is the one function in this file that IS fully real, because it
    doesn't depend on any CAD's actual fetch mechanics - it only assumes a
    CAD response has been reduced to a plain dict with the fields named in
    the Step 1 request (cad_market_value, land_value, building_value,
    acreage, building_sqft, tx_category, homestead_exemption). Once a real
    fetcher exists for any CAD, its job is to produce that shape; this
    function's job is unchanged.
    """
    category = tx_category_raw or raw.get("tx_category")
    return {
        "cad_market_value": raw.get("market_value"),
        "land_value": raw.get("land_value"),
        "building_value": raw.get("improvement_value"),
        "acreage": raw.get("acreage"),
        "building_sqft": raw.get("building_sqft"),
        "tx_category": normalize_category(category),
        "tx_category_label": category_label(category),
        "is_probably_agricultural": is_probably_agricultural(category),
        # HEX-equivalent flag. Field name on the CAD side is unconfirmed
        # per-CAD (HCAD/TAD/DCAD/BCAD/TCAD may each label this
        # differently) - .get() with a few plausible aliases as a
        # placeholder, to be replaced with real per-CAD field names once
        # each fetcher is real.
        "homestead_exemption": raw.get("homestead_exemption")
        or raw.get("hs_exemption")
        or raw.get("exemption_hs"),
    }


def compute_yield_fields(row: dict, cad_fields: dict) -> dict:
    """Wire normalized CAD fields + auction data into tx_yield_calc.py.

    This is the concrete link between deliverable #4 (CAD enrichment) and
    deliverable #5 (yield/penalty math) - once a real per-parcel CAD fetch
    exists, this function needs no changes; it already consumes exactly
    the shape normalize_cad_response() produces.
    """
    auction_date_raw = row.get("auction_date")
    if not auction_date_raw:
        return {}
    if isinstance(auction_date_raw, str):
        sale_date = date.fromisoformat(auction_date_raw[:10])
    else:
        sale_date = auction_date_raw

    bid = row.get("min_bid") or row.get("winning_bid")
    if bid is None:
        return {}

    terms = compute_redemption_terms(
        sale_or_deed_filed_date=sale_date,
        bid_usd=float(bid),
        is_homestead=cad_fields.get("homestead_exemption"),
        is_agricultural=cad_fields.get("is_probably_agricultural") if cad_fields.get("homestead_exemption") is None else None,
        tx_category=cad_fields.get("tx_category"),
    )
    return {
        "redemption_period_months": terms.redemption_period_months,
        "redemption_expiration_date": terms.redemption_expiration_date.isoformat(),
        "max_statutory_return_usd": terms.max_statutory_return_usd,
        "redemption_basis": terms.basis,  # not yet a real column - see note below
    }


def run(limit: int = BATCH_LIMIT) -> None:
    """Entry point. NOT SAFE TO RUN YET - every CAD_FETCHERS entry raises.

    Once at least one real fetcher exists, this should follow
    enrich_property_details.py's loop shape closely: pull up to `limit`
    TX rows where tx_cad_enriched_at is null (or, for permanently-failing
    rows, retry indefinitely the same way FL rows do - see that module's
    incremental-by-design rationale), respecting PER_CAD_LIMIT /
    CAD_MISS_STREAK so one CAD can't starve the others, sleeping
    REQUEST_DELAY_SECONDS between requests to any one CAD, and writing
    normalize_cad_response() + compute_yield_fields()'s output back via
    the Supabase REST API (same pattern as enrich_property_details.py -
    not reproduced here since SUPABASE_URL/SERVICE_KEY wiring is
    boilerplate, not the open question this draft needs to flag).

    NOTE: redemption_basis (the human-readable audit-trail string from
    tx_yield_calc.RedemptionTerms) has no column in
    002_add_texas_support.sql yet - the migration as drafted only stores
    the numeric/date outputs. Worth deciding whether that basis string is
    worth persisting (useful for a UI tooltip explaining *why* a
    redemption period was assigned, especially for the "UNCONFIRMED
    guess"/"UNCONFIRMED default" cases) before this script is finalized -
    flagging here rather than silently dropping it or silently adding an
    unrequested column.
    """
    raise NotImplementedError(
        "enrich_property_details_tx.py is an architectural draft - no "
        "CAD_FETCHERS entry is live-verified yet. See the module "
        "docstring: the open question is whether a usable per-parcel CAD "
        "data source exists at all for each major county, which needs its "
        "own research-and-prove-the-join pass (mirroring "
        "claude/parcel-enrichment-and-gis-plan.md's approach for Florida's "
        "FDOR join) before this can run against production."
    )


if __name__ == "__main__":
    run()
