#!/usr/bin/env python3
"""Backfill `prop_type` (and, only where the scraped `address` is a known
junk placeholder, `address`) on `properties` using Florida's free, no-API-
key statewide parcel dataset: the FL Dept of Revenue / Florida Geographic
Information Office "Florida Statewide Cadastral" ArcGIS FeatureServer,
built from the same annual tax-roll submissions every one of the 67 county
property appraisers already sends the state.

Why this exists (2026-09-02 scoping, see claude/improvement-roadmap.md in
the project docs for the full research writeup): the original plan was to
build a property-appraiser CAMA scraper per county (Qpublic/Schneider for
some, bespoke portals for the big counties) - 40+ potential harvesters.
Before writing any of that, a live test against this project's own data
found something much cheaper: 99.2% of `properties` rows already carry a
`parcel` number (captured straight off the source listing, not inferred),
and that parcel number can be looked up directly against ONE free statewide
API instead of 60+ county-specific ones. Verified live: exact matches for
Alachua/Marion with zero changes, Miami-Dade after stripping dashes from
our stored format. Some counties' parcel-number formatting doesn't match
the statewide layer's PARCEL_ID as-is (Volusia, Nassau confirmed so far) -
NORMALIZE_CANDIDATES below tries a few cheap reformattings automatically
rather than requiring that every county's exact format be hand-researched
up front; a county whose format isn't cracked by any candidate just quietly
gets 0 matches and its rows are left alone; the county-level match-rate
line this script prints is what identifies which counties still need a
bespoke normalization rule added here.

Important nuance (confirmed live, see the roadmap doc): the statewide layer
is sourced from the SAME county tax-roll data that produces our own junk
address placeholders ("UNASSIGNED LOCATION RE", "NO STREET COUNTY", etc.)
for genuinely-vacant/unassigned parcels - so this will NOT invent a real
street address where the county itself doesn't have one on file. It DOES
still return DOR_UC (the property-type/use code) for those same parcels,
which is the main win here: property-type coverage can approach the ~99%
parcel-coverage ceiling even for rows whose address coverage is capped by
a real data limitation, not a scraper gap.

Fairness / anti-starvation design (the geocoding backfill's own hard-won
lesson, applied proactively here rather than waiting to get bitten by it
again - see the geocoding starvation-bug writeup in the roadmap doc): a
flat `LIMIT BATCH_LIMIT` with no ordering would let whichever counties
happen to sit first in Postgres's stable scan order consume the whole
budget every run, and a county whose parcel format never matches (e.g.
Volusia/Nassau today) would occupy that spot forever, permanently starving
every other county's rows behind it - the exact failure mode already found
and fixed in scripts/geocode_properties.py. Fixed here by construction
instead of by ordering: every county with outstanding rows gets its own
small, capped slice (PER_COUNTY_LIMIT) each run, in a randomized county
order, so a county that can never match still only ever spends its own
small quota and can never block another county's rows.

Incremental by design, same as geocode_properties.py: a row is stamped with
`fdor_enriched_at` on a successful match and never re-fetched afterwards, so
this is cheap to run every harvest cycle. Rows that did NOT match are left
unstamped and retried later on purpose, so a county whose parcel format gets
cracked in a future revision picks up its whole backlog automatically.

What it fills (expanded 2026-09-02 from just prop_type/address, after finding
the layer exposes 121 fields rather than the 4 originally used):
  * prop_type, address     - as before (address only over a junk placeholder)
  * dor_use_code           - added 2026-09-08: the raw 2-digit FL DOR use
                             code (e.g. "01" Single Family) DOR_UC translates
                             into prop_type's coarser label - kept alongside
                             it rather than instead of it, since the UI can
                             now show the state's own exact category
  * market                 - JV, the county appraiser's own statutory "just
                             value"; `value_year` carries the assessment year
                             alongside it so the UI can attribute the number
                             honestly instead of implying a live estimate
  * assessed, owner_name   - fill-blank only, never over a scraped value
  * latitude/longitude     - the parcel polygon's centroid, which needs no
                             street address and so lifts map/Street View
                             coverage off the ~3.6% address-geocoding ceiling
  * year_built, living_area, lot_sqft, num_buildings, land_value, legal_desc,
    last_sale_price, last_sale_year - columns only this script populates
  * expanded 2026-09-17 (phase 52) after checking the FDOR 2025 NAL/SDF/NAP
    User's Guide for what the layer's other fields actually mean, since the
    layer itself supplies no field descriptions at all (all 127 aliases are
    identical to their names):
      taxable_value        TV_NSD, post-exemption, beside assessed's AV_NSD
      improvement_value    DERIVED, JV - LND_VAL - see improvement_value_from()
      acreage              DERIVED, LND_SQFOOT / 43560 - a unit conversion
      land_use             PA_UC, the county's own code beside the state's
      effective_year_built EFF_YR_BLT, renovation-aware vs year_built's
                           ACT_YR_BLT - the gap between them is the renovation
      num_res_units        NO_RES_UNT - units on the parcel, NOT bedrooms
      last_sale_month      SALE_MO1
      last_sale_qual_code  QUAL_CD1 - whether that sale is market evidence at
                           all; a tax roll's latest sale is very often a $100
                           intra-family quitclaim the appraiser disqualified
      last_sale_vi_code    VI_CD1 - vacant/improved AT THE TIME OF THAT SALE
      last_sale_or_book/   OR_BOOK1/OR_PAGE1/CLERK_NO1 - the county clerk's
        _or_page/_clerk_no official-records lookup key, i.e. the entry point
                           to a real title/lien check
      prior_sale_*         SALE_PRC2/YR2/MO2/QUAL_CD2 - direction, not just a
                           number
      fdor_alt_key         ALT_KEY, raw and under its own name; the "tax
                           collector account number" reading of it is an
                           unvalidated hypothesis and is not asserted here

Deliberately NOT filled from this layer, and why - so this does not get
re-litigated every time someone reads the field list (see also
docs/fdor-field-provenance.md):
  * delinquent_tax - DEL_VAL is NOT delinquent value. The guide defines it as
    the "[r]eduction in just value resulting from the deletion of improvements
    on the property since the previous assessment", i.e. a demolition
    adjustment. Writing it into a back-taxes column would print an invented
    dollar figure on the screen where someone decides what to bid.
  * annual_tax - the NAL is a VALUE roll, not a bill roll. It contains no tax
    amount of any kind. That comes from a tax collector, not from here.
  * beds, baths, zoning, subdivision, municipality - confirmed absent from the
    NAL layout entirely. NO_RES_UNT is units and NBRHD_CD is a county-defined
    neighbourhood code, neither of which is what those columns mean.
"""
import os
import random
from collections import Counter
import re
import sys
import time
from datetime import datetime, timezone

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
# Raised 2026-09-02 from 300/10. Measured live at that point: 2,041 of 3,232
# rows sat in counties this script has ALREADY matched successfully at least
# once - i.e. they were merely queued behind the old per-run cap, not blocked
# by anything. At 300/run that backlog needed ~7 runs (3+ days) to clear,
# which is what kept mappable coordinates at a few hundred rows. These
# limits clear it in 2-3 runs instead. Steady state stays cheap regardless:
# `fdor_enriched_at` means only genuinely new rows are ever fetched again.
# Phase 51. This script reads FLORIDA's statewide cadastral layer, so it can
# only ever enrich Florida rows. `properties` gained Texas rows in
# 002_add_texas_support.sql and nobody rescoped this script, so 449 TX rows
# across 14 counties sat in a Florida-only queue: never matchable, never
# stamped, and therefore re-attempted on every single run. Measured live
# 2026-09-17 - 0 of 449 enriched, Galveston alone 176 rows. The waste was not
# just the stall: up to 14 TX counties x COUNTY_MISS_STREAK rows x ~8
# normalisation candidates is roughly 670 pointless requests per run against
# a free public state API.
#
# An env var rather than a hard-coded literal so a future state with its own
# statewide layer can reuse this runner by pointing it at that state's
# endpoint - but the DEFAULT is FL, because FDOR_ENDPOINT is Florida's.
ENRICH_STATE = os.environ.get("ENRICH_STATE", "FL")

BATCH_LIMIT = int(os.environ.get("ENRICH_BATCH_LIMIT", "1000"))
PER_COUNTY_LIMIT = int(os.environ.get("ENRICH_PER_COUNTY_LIMIT", "40"))
# A county whose parcel format this script can't match burns one request per
# normalize_candidates() variant on every row - 8 wasted lookups per row now
# that the trailing-"R" variants exist. Rather than let an unmatchable county
# spend its whole enlarged slice proving the same thing 40 times, give up on
# it after this many CONSECUTIVE misses within a single run and hand the
# leftover budget to counties that are actually producing.
#
# This does not weaken the anti-starvation design: the county is still tried
# from scratch on the very next run (misses are never stamped), so a format
# fixed later still picks up its whole backlog - exactly what happened for
# Duval. It only stops one run from wasting minutes on a known-bad format.
COUNTY_MISS_STREAK = int(os.environ.get("ENRICH_COUNTY_MISS_STREAK", "6"))
REQUEST_DELAY_SECONDS = 0.3  # polite pacing against a free public API
FDOR_ENDPOINT = (
    "https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/"
    "Florida_Statewide_Cadastral/FeatureServer/0/query"
)

# The layer exposes 121 fields; this is the subset that maps onto something a
# bidder actually wants to see on a property card. Confirmed live 2026-09-02
# against a real matched parcel (Duval 0037090000R -> 6422 BLUEBIRD RD,
# JACKSONVILLE: JV 68017, ACT_YR_BLT 1958, TOT_LVG_AR 1840, LND_SQFOOT 16456,
# OWN_NAME "OAK CLIFF BIBLE CHURCH INCORPO", ASMNT_YR 2025).
#
# JV ("just value") is the single most valuable field here: it is the county
# property appraiser's own statutory estimate of market value, which is
# exactly the honest, attributable number this project needs (the app's
# `market` column was only ~3.6% populated before this). It is NOT a Zestimate
# and must never be labelled as a live/AVM estimate - the companion
# `value_year` column carries ASMNT_YR so the UI can say whose number it is
# and for which tax year.
# Phase 52 expansion. Every field added below was checked against the Florida
# Department of Revenue "2025 NAL/SDF/NAP User's Guide" before being mapped,
# because the layer metadata cannot be used for this: all 127 of its fields
# report an `alias` identical to their `name`, so the service tells you a
# column exists and nothing about what is in it.
#
# That check is not ceremony. DEL_VAL reads like "delinquent value" and is
# defined as "Reduction in just value resulting from the deletion of
# improvements on the property since the previous assessment" - a demolition
# adjustment. Mapping it to a `delinquent_tax` column on the strength of its
# name would have put a made-up back-taxes figure on the screen where someone
# decides what to bid. It is deliberately NOT requested here.
#
# Also confirmed absent from the NAL layout entirely, so no amount of field
# expansion will produce them and the design-gap columns for them stay NULL
# until a real source is acquired: billed tax, taxes due, delinquent tax,
# bedrooms, bathrooms, zoning, subdivision name, municipality.
# See docs/fdor-field-provenance.md.
FDOR_OUT_FIELDS = ",".join([
    "PARCEL_ID", "ASMNT_YR",
    "PHY_ADDR1", "PHY_CITY", "PHY_ZIPCD",
    "DOR_UC",
    # PA_UC is the COUNTY's own use code ("County-defined use codes"), kept
    # beside DOR_UC rather than instead of it: DOR_UC is state-defined and so
    # comparable across counties, PA_UC is not, and only the county's code
    # matches what that county's own appraiser site will show.
    "PA_UC",
    "JV", "AV_NSD", "TV_NSD", "LND_VAL", "JV_HMSTD",
    "ACT_YR_BLT", "EFF_YR_BLT",
    "TOT_LVG_AR", "NO_BULDNG", "NO_RES_UNT", "LND_SQFOOT",
    "OWN_NAME", "S_LEGAL",
    # The most recent sale, with the codes that say whether it means
    # anything. QUAL_CD1 ("Code denoting the property appraiser's sales
    # qualification decisions") is the important one - a tax roll's latest
    # "sale" is very often a $100 intra-family quitclaim that the appraiser
    # has disqualified precisely so it is not read as market evidence.
    "SALE_PRC1", "SALE_YR1", "SALE_MO1", "QUAL_CD1", "VI_CD1",
    # Clerk lookup key: book + page + instrument number is the entry point
    # into the county clerk's official records, i.e. the first real step of a
    # title/lien check rather than a guess about one.
    "OR_BOOK1", "OR_PAGE1", "CLERK_NO1",
    # The prior sale. One sale is a number; two are a direction.
    "SALE_PRC2", "SALE_YR2", "SALE_MO2", "QUAL_CD2",
    # Stored under its own name - the guide calls it an "[o]ptional alternate
    # key identifier some counties use", which is not the same statement as
    # "tax collector account number". See ALT_KEY in migration 009.
    "ALT_KEY",
])


def _num(value):
    """FDOR uses 0 as the 'no data' sentinel for every numeric field (a real
    $0 just value / year built / square footage doesn't occur), so 0 and
    blanks both become None rather than being written as a misleading 0."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def _int(value):
    num = _num(value)
    return int(num) if num is not None else None


def _text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None

if not SUPABASE_URL or not SERVICE_KEY:
    print("SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets.", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}

# Standard FL DOR county numbering: 67 counties, alphabetical, 11-77.
# Confirmed live against the FDOR layer this session for Alachua (11),
# Miami-Dade (23), Marion (52), Nassau (55), Volusia (74) - all matched
# the CO_NO the layer itself returned for known parcels in those counties.
COUNTY_CODES = {
    "Alachua": 11, "Baker": 12, "Bay": 13, "Bradford": 14, "Brevard": 15,
    "Broward": 16, "Calhoun": 17, "Charlotte": 18, "Citrus": 19, "Clay": 20,
    "Collier": 21, "Columbia": 22, "Miami-Dade": 23, "DeSoto": 24, "Dixie": 25,
    "Duval": 26, "Escambia": 27, "Flagler": 28, "Franklin": 29, "Gadsden": 30,
    "Gilchrist": 31, "Glades": 32, "Gulf": 33, "Hamilton": 34, "Hardee": 35,
    "Hendry": 36, "Hernando": 37, "Highlands": 38, "Hillsborough": 39,
    "Holmes": 40, "Indian River": 41, "Jackson": 42, "Jefferson": 43,
    "Lafayette": 44, "Lake": 45, "Lee": 46, "Leon": 47, "Levy": 48,
    "Liberty": 49, "Madison": 50, "Manatee": 51, "Marion": 52, "Martin": 53,
    "Monroe": 54, "Nassau": 55, "Okaloosa": 56, "Okeechobee": 57,
    "Orange": 58, "Osceola": 59, "Palm Beach": 60, "Pasco": 61,
    "Pinellas": 62, "Polk": 63, "Putnam": 64, "St. Johns": 65,
    "St. Lucie": 66, "Santa Rosa": 67, "Sarasota": 68, "Seminole": 69,
    "Sumter": 70, "Suwannee": 71, "Taylor": 72, "Union": 73, "Volusia": 74,
    "Wakulla": 75, "Walton": 76, "Washington": 77,
}
# A few counties get harvested/stored under a slightly different spelling
# than the canonical DOR name above - map those aliases here rather than
# silently failing to resolve a CO_NO for them.
COUNTY_ALIASES = {
    "Dade": "Miami-Dade",
    "St Johns": "St. Johns",
    "Saint Johns": "St. Johns",
    "St Lucie": "St. Lucie",
    "Saint Lucie": "St. Lucie",
    "DeSoto County": "DeSoto",
}

# Cheap, generic reformattings tried in order against a county's stored
# `parcel` value until one matches the FDOR layer's PARCEL_ID for that
# county. Confirmed live this session: identity works for Alachua/Marion,
# dash-stripped works for Miami-Dade. Kept intentionally generic (no
# per-county special-casing yet) - counties that need something smarter
# than these will show up with a 0%% match rate in this script's own
# per-county summary, which is the signal to add a rule here.
#
# The trailing-"R" variants were added 2026-09-02 after discovering (via
# fast PARCEL_ID-prefix LIKE queries against the FDOR layer, which stay
# indexed/fast even though bare CO_NO or PHY_ADDR1 queries time out - see
# the roadmap doc for the full investigation) that Duval's FDOR PARCEL_ID
# is exactly its dash-stripped RE# plus a literal trailing "R"
# (e.g. our stored "003709-0000" -> FDOR "0037090000R"), confirmed exact
# across an 11/11 sample. Kept generic rather than Duval-only since it's a
# cheap extra equality try that can only produce a false positive if some
# other county's real PARCEL_ID happens to exactly equal
# <our value>+"R", which is not realistic.
# Added 2026-09-07 after live-testing Clay County (the roadmap's own
# "blocked" list): Clay stores its RE-number with the section-township-range
# collapsed into one 6-digit block before the first dash (e.g.
# "410426-020240-000-00"), but FDOR's own PARCEL_ID for that identical
# parcel splits STR into three explicit 2-digit groups instead
# ("41-04-26-020240-000-00"). Confirmed live: 10/10 fresh unmatched Clay
# samples matched FDOR exactly once expanded this way, with zero prior
# candidates matching any of them. Kept generic (not Clay-only) - any other
# county following the same six-digit-STR-block-then-dash convention would
# benefit identically, and this returns None (no extra HTTP request spent)
# for every county whose parcel doesn't start with exactly six digits then a
# dash, which is why it's cheap to always try: checked live against fresh
# samples from Brevard/Flagler/Lake/Suwannee and none of those four match
# this shape (Brevard/Suwannee are bare digit strings with no dashes at
# all, Flagler is a 20-char alphanumeric STRAP with no dashes, Lake's first
# dash-delimited group is 10 digits, not 6) - so this is additive for Clay
# without changing behavior for anyone else.
_SIX_DIGIT_STR_BLOCK = re.compile(r"^(\d{2})(\d{2})(\d{2})-(.+)$")
def _expand_str_block(parcel):
    m = _SIX_DIGIT_STR_BLOCK.match(parcel)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"


# Added 2026-09-07 after live-testing Lake County (another of the roadmap's
# "blocked" counties): Lake stores its parcel number as a 10-digit
# section-township-range-parcel block, then a dash, then two more dashed
# groups (e.g. "3217270004-000-12600"), but FDOR's own PARCEL_ID for that
# identical parcel splits the leading 10 digits into four explicit groups
# (2-2-2-4: township, range, section, parcel) instead of leaving them
# concatenated ("32-17-27-0004-000-12600"), and leaves everything after the
# first dash untouched. Confirmed live: 8/8 fresh unmatched Lake samples
# matched FDOR exactly once expanded this way, with owner/address data
# matching what was already on file. This is a ten-digit block, so it can
# never collide with the six-digit Clay pattern above (Clay's regex requires
# a dash immediately after exactly six digits; Lake's tenth digit is never a
# dash), and it returns None (no extra request) for every other county's
# shape, so it's additive exactly like the Clay rule.
_TEN_DIGIT_STR_BLOCK = re.compile(r"^(\d{2})(\d{2})(\d{2})(\d{4})-(.+)$")
def _expand_lake_str_block(parcel):
    m = _TEN_DIGIT_STR_BLOCK.match(parcel)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}-{m.group(5)}"


# Added 2026-09-18 from live FDOR evidence (probe_fl_parcel_formats.py, Actions
# run 35406185583): four more counties whose stored parcel is the layer's
# PARCEL_ID with different separators/padding. Each helper returns None for
# every other shape (no extra request spent), so all four are additive.
#
# Lake, second shape: the RealAuction listing now emits
# "01-19-26-100000C00600" while the layer holds "01-19-26-1000-00C-01900" for
# its neighbours - the trailing 12 characters split 4-3-5. (The older
# "3217270004-000-12600" shape is still handled by _expand_lake_str_block.)
_LAKE_DASHED_TAIL = re.compile(r"^(\d{2}-\d{2}-\d{2})-([0-9A-Z]{4})([0-9A-Z]{3})([0-9A-Z]{5})$")
def _expand_lake_dashed_tail(parcel):
    m = _LAKE_DASHED_TAIL.match(parcel)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"


# Leon: we store "411137C0180"; the layer holds "411137  C0050" for its
# neighbours - a fixed 13-character field, 6-digit STR then the block/lot
# right-aligned in 7 (two spaces before a 5-character tail, one before a
# 6-character tail such as "CD0150"). 13-character Leon values already hit.
_LEON_SHORT = re.compile(r"^(\d{6})([A-Z]{1,2}\d{4})$")
def _pad_leon_block(parcel):
    m = _LEON_SHORT.match(parcel)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2).rjust(7)}"


# Citrus (LAFT PDF): we store "19E17S35 2B0E0 0330"; the layer holds
# "19E17S25      3B000 0320" - the section/subdivision block after the
# 6-character township-range prefix is left-justified in 8, then the block
# and lot separated by one space.
_CITRUS_SPACED = re.compile(r"^(\d{2}[A-Z]\d{2}[A-Z])([0-9A-Z]{1,8}) ([0-9A-Z]+) ([0-9A-Z]+)$")
def _pad_citrus_section(parcel):
    m = _CITRUS_SPACED.match(parcel)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2).ljust(8)}{m.group(3)} {m.group(4)}"


# Pasco: RealAuction emits the dashed "22-26-16-0010-00D00-0300" (matched as
# stored for 41 rows) but some listings carry the same 19 characters with no
# dashes, "16263101100060000A0" - the 2-2-2-4-5-4 groups re-dashed.
_PASCO_DASHLESS = re.compile(r"^(\d{2})(\d{2})(\d{2})([0-9A-Z]{4})([0-9A-Z]{5})([0-9A-Z]{4})$")
def _dash_pasco_groups(parcel):
    m = _PASCO_DASHLESS.match(parcel)
    if not m:
        return None
    return "-".join(m.groups())


def normalize_candidates(parcel):
    parcel = parcel.strip()
    seen = set()
    candidates = []
    for value in (
        parcel,
        parcel.replace("-", ""),
        parcel.replace(" ", ""),
        # Space -> dash. Added 2026-09-17 after measuring Alachua stuck at 11%
        # enriched with 118 rows: we store "12734 001 000" and the layer holds
        # "12734-001-000". Every existing candidate here either removes
        # separators or leaves them alone, so a county that uses the same
        # segments with a different separator could never match. Confirmed
        # live against two real unenriched Alachua parcels, both of which
        # resolve under this rule and under no other:
        #     "12734 001 000" -> 12734-001-000
        #     "06400 100 000" -> 06400-100-000
        # The reverse (dash -> space) is deliberately NOT added: no county has
        # been observed needing it, and an unproven candidate is one more
        # request per row against a free public API for every county on every
        # run.
        parcel.replace(" ", "-"),
        # Slash -> dash. Added 2026-09-18 after measuring St. Lucie at 58%
        # enriched overall but 0 of 16 on its LienHub certificate rows while
        # its auction rows sat at 28 of 29 - the same county, the same layer,
        # so the format was already cracked and only these rows' separator
        # differed. We store "2403-602-0056-000/8"; the layer holds
        # "2403-602-0056-000-8". Confirmed live against eight real unenriched
        # St. Lucie parcels, 8 of 8, each returning a real situs address and
        # just value (e.g. 4401-504-0043-000/3 -> 2269 SE UNION PARK DR,
        # JV 51700). The source emits both separators for the same county -
        # "2402-503-0089-000-1" is already stored with a dash - which is what
        # makes this a formatting inconsistency rather than a different
        # identifier.
        #
        # Costs nothing for the other 66 counties: only 20 rows statewide
        # contain "/" at all (19 St. Lucie, 1 Pasco, measured 2026-09-18), and
        # for any parcel without one this expression equals `parcel`, which
        # the `seen` set below already dropped - so no county gains a request.
        parcel.replace("/", "-"),
        "".join(ch for ch in parcel if ch.isalnum()),
    ):
        if value and value not in seen:
            seen.add(value)
            candidates.append(value)
    expanded = _expand_str_block(parcel)
    if expanded and expanded not in seen:
        seen.add(expanded)
        candidates.append(expanded)
    expanded_lake = _expand_lake_str_block(parcel)
    if expanded_lake and expanded_lake not in seen:
        seen.add(expanded_lake)
        candidates.append(expanded_lake)
    for shaped in (_expand_lake_dashed_tail(parcel), _pad_leon_block(parcel),
                   _pad_citrus_section(parcel), _dash_pasco_groups(parcel)):
        if shaped and shaped not in seen:
            seen.add(shaped)
            candidates.append(shaped)
    for value in list(candidates):
        with_r = value + "R"
        if with_r not in seen:
            seen.add(with_r)
            candidates.append(with_r)
    return candidates


# Standard statewide FL DOR use-code table (same 2-digit codes used by
# every county property appraiser's own published copy, e.g.
# https://www.leepa.org/Docs/Codes/DOR_Code_List.pdf - confirmed identical
# scheme against live DOR_UC values returned by the FDOR layer this
# session: 001->Single Family, 000->Vacant Residential, 002->Mobile Home,
# 010->Vacant Commercial, 041->Light Manufacturing, 052->Cropland Class II).
# Only used to backfill prop_type when it's currently NULL - never
# overwrites an existing scraped value (which often carries more specific
# info, like bed/bath counts or acreage, that a use code can't provide).
DOR_USE_LABELS = {
    0: "Vacant Residential", 1: "Single Family", 2: "Mobile Home",
    3: "Multi-Family", 4: "Condo", 5: "Cooperative", 6: "Retirement Home",
    7: "Residential", 8: "Multi-Family", 9: "Residential Common Area",
    10: "Vacant Commercial", 39: "Hotel/Motel",
    40: "Vacant Industrial", 70: "Vacant Institutional",
    80: "Vacant Governmental",
}


def _dor_use_int(dor_uc):
    try:
        return int(str(dor_uc).strip())
    except (TypeError, ValueError):
        return None


def dor_use_code_str(dor_uc):
    """The raw 2-digit FL DOR property-use code as a zero-padded string
    ("00" Vacant Residential, "01" Single Family, "10" Vacant Commercial,
    "40" Vacant Industrial, ...), or None. Added 2026-09-08: this script has
    fetched DOR_UC from the FDOR layer since 2026-09-02, but only ever
    translated it into the generic `prop_type` label below - the exact code
    itself was never persisted, which was flagged as an open gap in this
    project's own docs (a bidder wants the state's own category, not just
    the coarse Residential/Commercial/Industrial/etc. bucket prop_type
    gives). Reuses the same int-parsing dor_use_to_prop_type() uses, then
    zero-pads to 2 digits, so both derive from one normalized reading of
    whatever raw string format the FDOR layer happens to return (observed
    live as a zero-padded 3-digit string, e.g. "001") rather than storing
    that raw format verbatim."""
    code = _dor_use_int(dor_uc)
    if code is None or not (0 <= code <= 99):
        return None
    return f"{code:02d}"


def dor_use_to_prop_type(dor_uc):
    code = _dor_use_int(dor_uc)
    if code is None:
        return None
    if code in DOR_USE_LABELS:
        return DOR_USE_LABELS[code]
    if 0 <= code <= 9:
        return "Residential"
    if 10 <= code <= 39:
        return "Commercial"
    if 40 <= code <= 49:
        return "Industrial"
    if 50 <= code <= 69:
        return "Agricultural"
    if 70 <= code <= 79:
        return "Institutional"
    if 80 <= code <= 89:
        return "Government"
    if 90 <= code <= 99:
        return "Miscellaneous"
    return None


_JUNK_MARKERS = ("UNASSIGNED", "UNKNOWN", "NO STREET", "NOT ASSIGNED", "N/A")
def is_junk_address(address):
    if not address:
        return True
    upper = address.strip().upper()
    if not upper:
        return True
    if any(marker in upper for marker in _JUNK_MARKERS):
        return True
    # A genuine situs address almost always starts with a house number -
    # deliberately conservative (only used to decide whether it's SAFE to
    # overwrite, never to decide whether to geocode/display), so treating
    # "no digit anywhere" as junk risks nothing beyond leaving well enough
    # alone on an address this heuristic can't confidently classify.
    return not any(ch.isdigit() for ch in upper)


def is_junk_fdor_address(phy_addr1, phy_city):
    if not phy_addr1 or is_junk_address(phy_addr1):
        return True
    if not phy_city or not phy_city.strip():
        return True
    return False


def fetch_needing_enrichment_counties():
    """All distinct counties that still have at least one row with a parcel
    number that this script hasn't successfully enriched yet - the fairness
    unit for PER_COUNTY_LIMIT.

    The "already done" marker is `fdor_enriched_at`, not `prop_type IS NULL`.
    That changed 2026-09-02 when this script grew from filling one field
    (prop_type) to filling a dozen: keying off prop_type would have
    permanently locked out every row enriched by an earlier, narrower version
    of this script, so the ~300 rows already typed would never receive the
    just value, owner name, coordinates, year built or living area now
    available to them. A dedicated timestamp column is set only on a
    successful FDOR match, so each row is enriched exactly once and is never
    re-fetched afterwards.

    Rows that do NOT match stay unmarked and are retried on later runs - that
    is deliberate, so that a county whose parcel format gets cracked later
    (as Duval's was) picks up its backlog automatically. The per-county quota
    below is what keeps those retries from starving anyone.

    `parcel=not.is.null` alone still matches empty-string parcels (a real
    row shape confirmed live 2026-09-02: some Citrus rows carry `parcel=''`
    rather than NULL, presumably because the source listing genuinely had
    no parcel number and a harvester wrote '' instead of leaving it NULL).
    Those rows can never match anything here - excluding them keeps a
    parcel-less county from consuming its PER_COUNTY_LIMIT slice on rows
    this script can never fix, without changing the fairness design."""
    params = {
        "select": "county",
        "state": f"eq.{ENRICH_STATE}",
        "and": "(parcel.not.is.null,parcel.neq.\"\")",
        "fdor_enriched_at": "is.null",
        "limit": "5000",
    }
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/properties", headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    outstanding = Counter(row["county"] for row in resp.json() if row.get("county"))
    counties = sorted(outstanding)
    random.shuffle(counties)
    # (county, outstanding) rather than bare names: fetch_county_batch() needs
    # the count to size this run's random window - see its docstring.
    return [(county, outstanding[county]) for county in counties]


def fetch_county_batch(county, limit, outstanding=None):
    # Same empty-string-parcel exclusion as fetch_needing_enrichment_counties()
    # above, and for the same reason (confirmed live for Citrus 2026-09-02):
    # `parcel=not.is.null` alone still matches `parcel=''` rows, which can
    # never resolve through lookup_fdor() and would otherwise burn part of
    # this county's PER_COUNTY_LIMIT slice every run on unfixable rows.
    # Existing values come back too, because this script only ever FILLS
    # BLANKS on columns a harvester also writes (market/assessed/owner_name/
    # coordinates/prop_type) - a scraped value from the source listing always
    # wins over the tax roll's copy of it.
    # Phase 51. `order` + a random `offset` per run. Without them PostgREST
    # returns the same rows in the same scan order every time, and because a
    # miss is never stamped, the SAME rows lead the slice forever - so a
    # county whose first COUNTY_MISS_STREAK rows all miss is abandoned at that
    # same row on every future run and never advances. Measured live on
    # 2026-09-17: Miami-Dade 2/251 enriched, yet its unenriched parcel
    # 0131230340860 returns a full record from the layer on request. The row
    # was matchable the whole time; it was simply never reached.
    #
    # `order` is required for `offset` to mean anything, and a random window
    # start means consecutive runs explore different parts of the backlog
    # rather than re-proving the same six misses. Rows skipped this run are
    # not lost - they are still unstamped, and a later run's window covers
    # them. This does not weaken the anti-starvation design; it completes it,
    # extending the same fairness from between-counties to within-a-county.
    offset = 0
    if outstanding and outstanding > limit:
        offset = random.randrange(0, outstanding - limit + 1)
    params = {
        "select": "id,parcel,address,county,prop_type,market,assessed,owner_name,latitude,longitude",
        "state": f"eq.{ENRICH_STATE}",
        "county": f"eq.{county}",
        "and": "(parcel.not.is.null,parcel.neq.\"\")",
        "fdor_enriched_at": "is.null",
        "order": "id.asc",
        "offset": str(offset),
        "limit": str(limit),
    }
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/properties", headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def lookup_fdor(county, parcel):
    """Returns (attributes, centroid, matched_candidate) or (None, None, None).

    `returnCentroid=true` + `outSR=4326` asks the layer for each matched
    parcel polygon's centroid in plain WGS84 lat/lon, with returnGeometry
    off so the full ring coordinates don't come back too. This is the single
    biggest win available here: geocoding coverage was stuck at ~3.6% because
    the US Census geocoder can only match a real street address and ~94% of
    these rows carry a junk placeholder instead (see the geocoding
    starvation writeup in the roadmap doc). A parcel centroid needs no
    address at all - every parcel that matches by number gets exact
    coordinates, which is what makes the map pin, the Street View link and
    the coordinate-based Zillow link work for those rows.
    """
    co_no = COUNTY_CODES.get(COUNTY_ALIASES.get(county, county))
    if co_no is None:
        return None, None, None  # unmapped county name - skip rather than guess
    for candidate in normalize_candidates(parcel):
        # Escape single quotes defensively - parcel numbers are normally
        # digits/letters/dashes only, but never trust scraped input in a
        # hand-built filter string.
        safe = candidate.replace("'", "''")
        params = {
            "where": f"PARCEL_ID='{safe}' AND CO_NO={co_no}",
            "outFields": FDOR_OUT_FIELDS,
            "returnGeometry": "false",
            "returnCentroid": "true",
            "outSR": "4326",
            "f": "json",
        }
        resp = requests.get(FDOR_ENDPOINT, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if features:
            feature = features[0]
            return feature.get("attributes", {}), feature.get("centroid"), candidate
    return None, None, None


# Santa Rosa's own ArcGIS Hub open-data FeatureServer (discovered 2026-09-07,
# see claude/parcel-format-research.md in the project docs): Santa Rosa's
# local parcel numbering does not textually resemble the statewide FDOR
# PARCEL_ID in any tried form (identity, dash/space-stripped, alnum-only,
# +"R", truncated STR prefixes) - confirmed live across two separate
# research passes with 5+ samples each, so lookup_fdor() above is a
# permanent 0% match for this county specifically. This is a free,
# no-API-key, county-run layer instead, whose own PAR_NUM field matches our
# stored parcel value almost exactly (5 of 6 live samples: exact identity,
# or identity with a trailing "M" stripped). It's a parcel/ownership layer,
# not a CAMA/tax-roll layer, so it lacks just value, year built, living
# area, legal description and sale history - it can only ever supply owner
# name, address, lot size (converted from acreage) and a centroid. Its raw
# attributes are normalized onto FDOR's own field names below so
# build_update_fields() needs no changes to consume either source.
SANTA_ROSA_GIS_ENDPOINT = (
    "https://services.arcgis.com/Eg4L1xEv2R3abuQd/arcgis/rest/services/"
    "ParcelsOpenData/FeatureServer/0/query"
)
SANTA_ROSA_OUT_FIELDS = "PAR_NUM,OwnerName,Addr1,Addr2,Addr3,City,Zip5,CALC_ACRE,PropertyUs"


def _santa_rosa_candidates(parcel):
    parcel = parcel.strip()
    candidates = [parcel]
    # Observed live: some stored Santa Rosa parcel values carry a trailing
    # "M" that this layer's own PAR_NUM does not (e.g. a mobile-home-lot
    # suffix from the source auction listing). Try both forms.
    if len(parcel) > 1 and parcel[-1].upper() == "M":
        candidates.append(parcel[:-1])
    return candidates


def lookup_santa_rosa_gis(parcel):
    """Santa Rosa-only fallback, tried after lookup_fdor() misses for this
    county. Same (attrs, centroid, matched_candidate) return shape as
    lookup_fdor() - (None, None, None) on no match - so main()'s handling
    doesn't need to know which source actually matched.
    """
    for candidate in _santa_rosa_candidates(parcel):
        safe = candidate.replace("'", "''")
        params = {
            "where": f"PAR_NUM='{safe}'",
            "outFields": SANTA_ROSA_OUT_FIELDS,
            "returnGeometry": "false",
            "returnCentroid": "true",
            "outSR": "4326",
            "f": "json",
        }
        resp = requests.get(SANTA_ROSA_GIS_ENDPOINT, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if not features:
            continue
        raw = features[0].get("attributes", {})
        addr1 = next(
            (v for v in (raw.get("Addr1"), raw.get("Addr2"), raw.get("Addr3"))
             if v and str(v).strip()),
            None,
        )
        acres = raw.get("CALC_ACRE")
        try:
            lot_sqft = round(float(acres) * 43560) if acres else None
        except (TypeError, ValueError):
            lot_sqft = None
        attrs = {
            "OWN_NAME": raw.get("OwnerName"),
            "PHY_ADDR1": addr1,
            "PHY_CITY": raw.get("City"),
            "PHY_ZIPCD": raw.get("Zip5"),
            "LND_SQFOOT": lot_sqft,
        }
        return attrs, features[0].get("centroid"), candidate
    return None, None, None


# Palm Coast (Flagler's largest city, and the county's own tax-deed listings
# are disproportionately Palm Coast lots) publishes its own external parcel/
# CAMA layer (discovered 2026-09-07, see claude/parcel-format-research.md):
# FDOR's own CO_NO=28 queries for Flagler are unreliable and time out
# (confirmed via both WebFetch and Chrome), and even when they don't,
# Flagler's stored 19-character parcel value (e.g. "0711317024000700120")
# doesn't match FDOR's own PARCEL_ID in any tried form. This layer's
# PARCELNO field uses the SAME digit order as our stored value, just with
# dashes inserted at fixed group widths (2-2-2-4-5-4:
# "0711317024000700120" -> "07-11-31-7024-00070-0120") - confirmed live 5/5
# on fresh unmatched samples, including two containing embedded letters
# (a "RP0B" block) and one Palm Coast vacant lot with a null situs address
# (not a failure - the county genuinely has no address on file for it,
# same caveat as lookup_fdor()'s own docstring). This layer has no
# `returnCentroid` support at all (confirmed live - the key is simply absent
# from the response) and no year-built/living-area/building-count fields
# anywhere in its 174-field schema, so this can never populate those three
# columns or lat/lon - but it DOES carry owner name, a full situs address,
# just/assessed/land value, lot size (converted from acreage) and a legal
# description, which is most of what lookup_fdor() itself would have given.
FLAGLER_GIS_ENDPOINT = (
    "https://gis.palmcoast.gov/hosting/rest/services/External/"
    "FlaglerCountyParcels/MapServer/1/query"
)
FLAGLER_OUT_FIELDS = ",".join([
    "PARCELNO", "file_as_name",
    "situs_num", "situs_street_prefx", "situs_street", "situs_street_sufix",
    "situs_unit", "situs_city", "situs_zip",
    "JustVal", "Assessed_val", "mktland", "legal_acreage", "Legal",
])


def _flagler_candidates(parcel):
    parcel = parcel.strip()
    candidates = [parcel]
    compact = parcel.replace("-", "")
    if len(compact) == 19:
        groups = []
        idx = 0
        for size in (2, 2, 2, 4, 5, 4):
            groups.append(compact[idx:idx + size])
            idx += size
        dashed = "-".join(groups)
        if dashed not in candidates:
            # Try the known-correct dashed form first - it's the one that's
            # actually verified to match this layer's PARCELNO.
            candidates.insert(0, dashed)
    return candidates


def lookup_flagler_gis(parcel):
    """Flagler-only fallback, tried after lookup_fdor() misses for this
    county. Same (attrs, centroid, matched_candidate) return shape as
    lookup_fdor() - (None, None, None) on no match, centroid always None
    here since this layer doesn't support returnCentroid.
    """
    for candidate in _flagler_candidates(parcel):
        safe = candidate.replace("'", "''")
        params = {
            "where": f"PARCELNO='{safe}'",
            "outFields": FLAGLER_OUT_FIELDS,
            "returnGeometry": "false",
            "f": "json",
        }
        resp = requests.get(FLAGLER_GIS_ENDPOINT, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if not features:
            continue
        raw = features[0].get("attributes", {})
        street = " ".join(
            part for part in (
                _text(raw.get("situs_num")),
                _text(raw.get("situs_street_prefx")),
                _text(raw.get("situs_street")),
                _text(raw.get("situs_street_sufix")),
            ) if part
        )
        unit = _text(raw.get("situs_unit"))
        if unit:
            street = f"{street} #{unit}" if street else f"#{unit}"
        acres = raw.get("legal_acreage")
        try:
            lot_sqft = round(float(acres) * 43560) if acres else None
        except (TypeError, ValueError):
            lot_sqft = None
        attrs = {
            "OWN_NAME": raw.get("file_as_name"),
            "PHY_ADDR1": street or None,
            "PHY_CITY": raw.get("situs_city"),
            "PHY_ZIPCD": raw.get("situs_zip"),
            "JV": raw.get("JustVal"),
            "AV_NSD": raw.get("Assessed_val"),
            "LND_VAL": raw.get("mktland"),
            "LND_SQFOOT": lot_sqft,
            "S_LEGAL": raw.get("Legal"),
        }
        return attrs, None, candidate
    return None, None, None


# Phase 52. Columns that migration 009 (and, for a few, 007) adds and that an
# older database will not have yet. This script runs from a workflow against
# whatever schema production currently has, and PostgREST rejects an entire
# PATCH if any single key in it is not a column - so an expanded writer
# deployed before its migration would not degrade, it would stop enriching
# anything at all, silently, on every row.
#
# Rather than couple the deploy order, the writer asks the database once per
# run which of these it actually has and writes only those. Before the
# migration it behaves exactly like the pre-expansion script; after it, the
# new columns start filling with no redeploy. The run log says which columns
# were skipped and why, so "the migration has not been applied" is visible
# instead of looking like a source that stopped returning data.
OPTIONAL_COLUMNS = (
    "taxable_value",
    "improvement_value",
    "land_use",
    "acreage",
    "effective_year_built",
    "num_res_units",
    "last_sale_month",
    "last_sale_qual_code",
    "last_sale_vi_code",
    "last_sale_or_book",
    "last_sale_or_page",
    "last_sale_clerk_no",
    "prior_sale_price",
    "prior_sale_year",
    "prior_sale_month",
    "prior_sale_qual_code",
    "fdor_alt_key",
)

_available_optional_columns = None


def _column_exists(column):
    """`limit=0` asks PostgREST to project the column and return no rows, so
    this costs one round trip and transfers nothing. A 200 means the column
    is real; a 4xx naming it means it is not."""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/properties",
            headers=HEADERS,
            params={"select": column, "limit": "0"},
            timeout=15,
        )
    except requests.RequestException:
        return False
    return resp.status_code == 200


def available_optional_columns():
    """Memoised per process. Probes the whole set in one request first, which
    is the normal case once the migration is in, and only falls back to
    per-column probing when that request fails."""
    global _available_optional_columns
    if _available_optional_columns is not None:
        return _available_optional_columns

    if _column_exists(",".join(OPTIONAL_COLUMNS)):
        _available_optional_columns = frozenset(OPTIONAL_COLUMNS)
    else:
        _available_optional_columns = frozenset(
            column for column in OPTIONAL_COLUMNS if _column_exists(column)
        )

    missing = [c for c in OPTIONAL_COLUMNS if c not in _available_optional_columns]
    if missing:
        print(
            f"  NOTE: {len(missing)} expanded column(s) are not in this database and "
            f"will not be written: {', '.join(missing)}. "
            "Apply scripts/migrations/009_fdor_verified_field_expansion.sql to enable them."
        )
    return _available_optional_columns


def drop_unavailable_columns(fields):
    """Filter a built patch down to columns this database actually has.

    Only OPTIONAL_COLUMNS are ever dropped. A base column going missing is a
    real fault and is left to fail loudly rather than be silently swallowed."""
    available = available_optional_columns()
    return {
        key: value for key, value in fields.items()
        if key not in OPTIONAL_COLUMNS or key in available
    }


def patch_property(property_id, fields):
    fields = drop_unavailable_columns(fields)
    if not fields:
        return
    url = f"{SUPABASE_URL}/rest/v1/properties?id=eq.{property_id}"
    patch_headers = dict(HEADERS)
    patch_headers["Prefer"] = "return=minimal"
    resp = requests.patch(url, headers=patch_headers, json=fields, timeout=15)
    resp.raise_for_status()


SQFT_PER_ACRE = 43560.0


def _code(value):
    """FDOR's code fields (QUAL_CD1, VI_CD1, PA_UC, ALT_KEY, OR_BOOK1 ...)
    arrive as a mix of strings, ints and floats depending on how the layer
    typed the column, and blank/0 is the no-data sentinel throughout.

    Kept as text rather than parsed: these are identifiers, not quantities.
    An official-record book number and a county use code both have leading
    zeros that matter and neither is ever arithmetic. A float that happens to
    be integral (ArcGIS returns 3.0 for an integer column often enough) is
    rendered without its decimal tail so "3.0" never becomes a book number.
    """
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if not text or text in {"0", "00", "000"}:
        return None
    return text


def _month(value):
    """FDOR sale months. 0/blank is no-data, and anything outside 1-12 is a
    corrupt row rather than a month, so it is dropped instead of stored - the
    database has a CHECK for the same thing and a bad value would otherwise
    fail the whole patch for that row."""
    month = _int(value)
    if month is None or not 1 <= month <= 12:
        return None
    return month


def improvement_value_from(attrs):
    """JV - LND_VAL.

    The NAL layout has no improvement-value field, so this is a derivation
    and is labelled as one everywhere it appears: it is the just value NOT
    attributable to the land, which includes special-feature value as well as
    the structures. Returned only when both inputs are real and the result is
    positive - a land value at or above just value means either a vacant
    parcel or a roll quirk, and neither is an improvement figure worth
    showing.
    """
    just_value = _num(attrs.get("JV"))
    land_value = _num(attrs.get("LND_VAL"))
    if just_value is None or land_value is None:
        return None
    improvement = just_value - land_value
    return improvement if improvement > 0 else None


def acreage_from(attrs):
    """LND_SQFOOT / 43560.

    A unit conversion, not a reinterpretation: the guide defines LND_SQFOOT
    as the "[e]quivalent square footage of the site regardless of the
    information in fields 42 and 43", i.e. it is already normalised to square
    feet whatever unit basis that county assessed the land on, so no
    LND_UNTS_CD branching is needed or appropriate here.
    """
    sqft = _num(attrs.get("LND_SQFOOT"))
    if sqft is None:
        return None
    return round(sqft / SQFT_PER_ACRE, 4)


def build_update_fields(row, attrs, centroid):
    """Map one matched FDOR record onto `properties` columns.

    Two deliberately different rules apply, by column:

    1. Columns a harvester ALSO writes (prop_type, market, assessed,
       owner_name, latitude/longitude, address) are only ever used to FILL A
       BLANK. A value scraped from the source auction listing is the more
       authoritative one for that auction and is never overwritten by the tax
       roll's copy of it. `address` keeps its existing extra guard: it is only
       replaced when ours is a known junk placeholder AND the tax roll's is a
       real street address.
    2. Columns only this script populates (year_built, living_area, lot_sqft,
       num_buildings, land_value, legal_desc, last_sale_*, prior_sale_*,
       value_year, taxable_value, improvement_value, acreage, land_use,
       effective_year_built, num_res_units, fdor_alt_key) are written straight
       from the tax roll, since nothing else supplies them.

    Both rules are ADDITIVE in the same way and for the same reason: a value
    is only ever put into `fields` when it is not None, so a parcel whose roll
    record omits a field leaves whatever is already stored for that column
    untouched. An absent source field is not evidence that the stored value is
    wrong, and this script must never turn silence into a NULL - a row
    enriched last month from a complete record would otherwise be stripped
    this month by a thinner one.

    `homestead` is a special case: only positive evidence is written. A
    homestead exemption on file (JV_HMSTD > 0) sets it True, but the absence
    of one never writes False, because that column already carries a
    non-null value on every row and a blanket overwrite would destroy
    whatever a harvester legitimately recorded there.
    """
    fields = {}

    prop_type = dor_use_to_prop_type(attrs.get("DOR_UC"))
    if prop_type and not _text(row.get("prop_type")):
        fields["prop_type"] = prop_type

    just_value = _num(attrs.get("JV"))
    if just_value is not None and _num(row.get("market")) is None:
        fields["market"] = just_value

    assessed = _num(attrs.get("AV_NSD"))
    if assessed is not None and _num(row.get("assessed")) is None:
        fields["assessed"] = assessed

    owner = _text(attrs.get("OWN_NAME"))
    if owner and not _text(row.get("owner_name")):
        fields["owner_name"] = owner

    # Parcel centroid -> coordinates, but only for rows that have none. A real
    # geocode of a real street address is more precise than a polygon centroid
    # on a large/irregular parcel, so an existing fix is never replaced.
    if centroid and row.get("latitude") is None and row.get("longitude") is None:
        lat, lon = centroid.get("y"), centroid.get("x")
        if (
            isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            # Sanity-bound to Florida rather than merely to valid lat/lon, so a
            # bad projection or a swapped x/y can never silently drop a pin in
            # the ocean or another state.
            and 24.0 <= lat <= 31.5 and -88.0 <= lon <= -79.5
        ):
            fields["latitude"] = lat
            fields["longitude"] = lon

    if is_junk_address(row.get("address")) and not is_junk_fdor_address(
        attrs.get("PHY_ADDR1"), attrs.get("PHY_CITY")
    ):
        zip_part = f" {_text(attrs.get('PHY_ZIPCD')) or ''}".rstrip()
        fields["address"] = f"{attrs['PHY_ADDR1']}, {attrs['PHY_CITY']}, FL{zip_part}"

    if _num(attrs.get("JV_HMSTD")) is not None:
        fields["homestead"] = True

    for column, value in (
        ("year_built", _int(attrs.get("ACT_YR_BLT"))),
        ("living_area", _int(attrs.get("TOT_LVG_AR"))),
        ("lot_sqft", _int(attrs.get("LND_SQFOOT"))),
        ("num_buildings", _int(attrs.get("NO_BULDNG"))),
        ("land_value", _num(attrs.get("LND_VAL"))),
        ("legal_desc", _text(attrs.get("S_LEGAL"))),
        ("last_sale_price", _num(attrs.get("SALE_PRC1"))),
        ("last_sale_year", _int(attrs.get("SALE_YR1"))),
        ("value_year", _int(attrs.get("ASMNT_YR"))),
        # Raw code alongside the translated prop_type above - see
        # dor_use_code_str()'s docstring. None for Santa Rosa/Flagler's
        # fallback GIS layers, which never populate attrs["DOR_UC"] (they
        # aren't the FDOR tax-roll layer), same as prop_type above for
        # those two counties.
        ("dor_use_code", dor_use_code_str(attrs.get("DOR_UC"))),

        # ------------------------------------------------------------------
        # Phase 52 expansion. Definitions quoted in migration 009; every one
        # was read out of the FDOR 2025 NAL/SDF/NAP User's Guide rather than
        # inferred from the field name.
        # ------------------------------------------------------------------
        # TV_NSD is taxable (post-exemption) where AV_NSD above is assessed
        # (pre-exemption). The gap between them IS the exemption, which is
        # what the homestead-risk feature is about, so they are stored as two
        # columns and never collapsed into one.
        ("taxable_value", _num(attrs.get("TV_NSD"))),
        ("improvement_value", improvement_value_from(attrs)),
        ("acreage", acreage_from(attrs)),
        # The county's own use code, beside the state's. Not cross-county
        # comparable, which is exactly why it is not merged with dor_use_code.
        ("land_use", _code(attrs.get("PA_UC"))),
        ("effective_year_built", _int(attrs.get("EFF_YR_BLT"))),
        ("num_res_units", _int(attrs.get("NO_RES_UNT"))),
        # Last sale: the qualification code travels with the price, always.
        ("last_sale_month", _month(attrs.get("SALE_MO1"))),
        ("last_sale_qual_code", _code(attrs.get("QUAL_CD1"))),
        ("last_sale_vi_code", _code(attrs.get("VI_CD1"))),
        ("last_sale_or_book", _code(attrs.get("OR_BOOK1"))),
        ("last_sale_or_page", _code(attrs.get("OR_PAGE1"))),
        ("last_sale_clerk_no", _code(attrs.get("CLERK_NO1"))),
        # Prior sale.
        ("prior_sale_price", _num(attrs.get("SALE_PRC2"))),
        ("prior_sale_year", _int(attrs.get("SALE_YR2"))),
        ("prior_sale_month", _month(attrs.get("SALE_MO2"))),
        ("prior_sale_qual_code", _code(attrs.get("QUAL_CD2"))),
        # Raw, under its own name. See migration 009 - the tax-collector
        # reading of this field is an unvalidated hypothesis, per county.
        ("fdor_alt_key", _code(attrs.get("ALT_KEY"))),
    ):
        if value is not None:
            fields[column] = value

    # The sale-order CHECK in migration 009 pins FDOR's most-recent-first
    # ordering. A roll that violates it would fail the whole row's patch and
    # cost this property every other field too, so the prior sale is dropped
    # instead - the anomaly is not worth losing the just value over.
    last_year = fields.get("last_sale_year", _int(row.get("last_sale_year")))
    prior_year = fields.get("prior_sale_year")
    if last_year is not None and prior_year is not None and prior_year > last_year:
        for column in (
            "prior_sale_price", "prior_sale_year",
            "prior_sale_month", "prior_sale_qual_code",
        ):
            fields.pop(column, None)

    return fields


def main():
    counties = fetch_needing_enrichment_counties()
    print(f"{len(counties)} counties have rows needing enrichment (parcel set, not yet FDOR-enriched).")
    if not counties:
        print("Nothing to enrich.")
        return

    total_attempted = 0
    total_matched = 0
    total_unmapped_county = 0
    per_county_matches = {}
    # Per-column fill counts, so a run's log says exactly which card fields got
    # populated rather than just "N rows matched".
    filled_counts = {}

    for county, outstanding in counties:
        if total_attempted >= BATCH_LIMIT:
            break
        rows = fetch_county_batch(
            county, min(PER_COUNTY_LIMIT, BATCH_LIMIT - total_attempted), outstanding
        )
        if not rows:
            continue
        county_matched = 0
        miss_streak = 0
        for row in rows:
            if miss_streak >= COUNTY_MISS_STREAK:
                # Give up on this county for THIS run only - see the
                # COUNTY_MISS_STREAK note above. Retried in full next run.
                print(f"  [{county}] {miss_streak} consecutive misses - skipping the rest of this county's slice this run.")
                break
            total_attempted += 1
            parcel = row.get("parcel")
            if not parcel:
                continue
            if COUNTY_ALIASES.get(county, county) not in COUNTY_CODES:
                total_unmapped_county += 1
                time.sleep(REQUEST_DELAY_SECONDS)
                continue
            try:
                attrs, centroid, matched_candidate = lookup_fdor(county, parcel)
            except requests.RequestException as e:
                print(f"  [{county}] ERROR looking up parcel {parcel!r}: {e}", file=sys.stderr)
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

            # Santa Rosa-only fallback: FDOR is a confirmed permanent 0% match
            # for this county (see lookup_santa_rosa_gis()'s docstring), so a
            # miss there is worth one extra request against the county's own
            # GIS layer before counting it as a real miss.
            if attrs is None and COUNTY_ALIASES.get(county, county) == "Santa Rosa":
                try:
                    attrs, centroid, matched_candidate = lookup_santa_rosa_gis(parcel)
                except requests.RequestException as e:
                    print(f"  [{county}] ERROR looking up parcel {parcel!r} via Santa Rosa GIS: {e}", file=sys.stderr)

            # Flagler-only fallback, same reasoning as Santa Rosa's above:
            # FDOR is unreliable/non-matching for this county specifically
            # (see lookup_flagler_gis()'s docstring), so a miss there is
            # worth one extra request against Palm Coast's own GIS layer.
            if attrs is None and COUNTY_ALIASES.get(county, county) == "Flagler":
                try:
                    attrs, centroid, matched_candidate = lookup_flagler_gis(parcel)
                except requests.RequestException as e:
                    print(f"  [{county}] ERROR looking up parcel {parcel!r} via Flagler GIS: {e}", file=sys.stderr)

            if attrs is None:
                # Left unmarked on purpose - retried on a later run, so a
                # county whose format gets cracked later picks up its backlog.
                miss_streak += 1
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

            total_matched += 1
            county_matched += 1
            miss_streak = 0  # a hit proves the format works; keep going

            fields = build_update_fields(row, attrs, centroid)
            # Stamped only on a successful match, and in the same PATCH as the
            # data, so a row is never marked enriched unless its values landed.
            fields["fdor_enriched_at"] = datetime.now(timezone.utc).isoformat()

            try:
                patch_property(row["id"], fields)
                for column in fields:
                    if column != "fdor_enriched_at":
                        filled_counts[column] = filled_counts.get(column, 0) + 1
            except requests.RequestException as e:
                print(f"  [{county}] ERROR saving parcel {parcel!r} (matched via {matched_candidate!r}): {e}", file=sys.stderr)

            time.sleep(REQUEST_DELAY_SECONDS)

        if rows:
            per_county_matches[county] = (county_matched, len(rows))

    print(
        f"Done. Attempted {total_attempted}, FDOR matches {total_matched}, "
        f"unmapped-county rows skipped {total_unmapped_county}."
    )
    print("Fields populated this run (column: rows filled):")
    for column, count in sorted(filled_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {column}: {count}")
    print("Per-county match rate this run (matched/attempted) - a persistent 0 for a county across runs is the signal its parcel-number format needs a new normalize_candidates() rule:")
    for county, (matched, attempted) in sorted(per_county_matches.items()):
        print(f"  {county}: {matched}/{attempted}")
    # Non-fatal by design, same reasoning as geocode_properties.py: this is
    # additive enrichment, not a correctness gate on the harvest itself.


if __name__ == "__main__":
    main()
