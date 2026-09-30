#!/usr/bin/env python3
"""Build data/county_source_registry.csv - the county-level OTC / LAFT /
struck-off SOURCE registry (Phase 3 of the 2026-09-29 implementation that
followed the master LAFT / OTC / struck-off audit).

Why a generator: the nine Florida harvesters already keep their production
source lists in four CSVs (data/laft_pdf_sources.csv, laft_html_sources.csv,
laft_pioneer_counties.csv, laft_realtdm_counties.csv) plus five single-county
scripts. Those files stay the operational truth - the harvesters read them.
This script derives the registry's PRODUCTION rows from them (so the two can
never drift; tests/python/test_county_source_registry.py asserts the committed
CSV equals this script's output) and adds the CANDIDATE rows the audit found
but did not verify, from the hand-maintained tables below.

Nothing here fetches anything. Candidate rows carry the audit's evidence
level verbatim (SEARCH_EVIDENCE_ONLY, SOURCE_EXISTS_ACCESS_UNKNOWN,
HISTORICAL_ONLY, NOT_FOUND_AFTER_SEARCH, BLOCKED_VENDOR_ONLY) and can never
be run by a harvester: harvesters/otc/gate.py refuses every row whose
verification_status is not PRODUCTION_VERIFIED, and the four blocked Texas
vendors are refused by name regardless.

Run:  python3 scripts/build_county_source_registry.py   (rewrites the CSV)
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
OUT = DATA / "county_source_registry.csv"

COLUMNS = [
    "state", "county", "source_id", "harvester", "inventory_type", "source_authority",
    "canonical_url", "document_url", "purchase_url", "purchase_url_kind",
    "access_method", "machine_format", "verification_status", "governance_status",
    "last_checked", "completeness_status", "evidence_ref", "notes",
    # 2026-09-29 (Alabama onboarding): the publishing-unit and semantics
    # columns - county_source_registry.EXTENDED_COLUMNS. Every FL/TX row is
    # COUNTY-level with the other four blank; migration 020 (NOT applied)
    # adds them to the table.
    "publishing_unit", "publishing_unit_name", "amount_kind", "update_frequency", "source_terminology",
    # 2026-09-30 (three ledgers): which customer ledger(s) the source feeds -
    # AUCTIONS, AVAILABLE, LIENS_CERTIFICATES, "|"-joined. The registry now
    # holds every production source of every ledger, not only the AVAILABLE
    # (LAFT / struck-off) ones; harvesters/ledgers/__init__.py SOURCE_LEDGERS
    # is the same mapping on the harvest side and a test pins the two equal.
    "ledgers",
]

AUCTIONS, AVAILABLE, LIENS = "AUCTIONS", "AVAILABLE", "LIENS_CERTIFICATES"

FL_INVENTORY = "POST_SALE_FIXED_PRICE"

# Per-county completeness as the 2026-09-29 production run (workflow run
# 185) reported it, under the OLD harvesters' semantics: rows > 0 ->
# COMPLETE, an ERROR line -> FAILED, a bare zero -> UNKNOWN (the old code
# could not distinguish empty from broken - which is what this whole change
# fixes). The next production run rewrites these from the status file.
RUN_185 = {
    "COMPLETE": {"Marion", "Pasco", "Volusia", "Escambia", "Indian River", "Putnam", "Gadsden",
                 "Alachua", "Highlands", "Lee", "Sarasota", "Polk", "Miami-Dade",
                 "Citrus", "Bay", "Duval", "Hernando", "Palm Beach", "Levy",
                 "Orange", "St. Lucie", "Osceola", "Hillsborough", "Leon"},
    "FAILED": {"Hendry", "Union", "Walton"},
}


def _completeness(county: str) -> str:
    for status, names in RUN_185.items():
        if county in names:
            return status
    return "UNKNOWN"


def _row(**kw) -> dict:
    row = {c: "" for c in COLUMNS}
    row["publishing_unit"] = "COUNTY"
    row.update(kw)
    return row


def _read(name: str) -> list[dict]:
    with open(DATA / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fl_production_rows() -> list[dict]:
    rows: list[dict] = []
    common = dict(state="FL", inventory_type=FL_INVENTORY, verification_status="PRODUCTION_VERIFIED",
                  governance_status="APPROVED_GRANDFATHERED", last_checked="2026-09-29", ledgers=AVAILABLE)
    for src in _read("laft_pdf_sources.csv"):
        municode = "mcclibraryfunctions.azurewebsites.us" in src["Url"]
        rows.append(_row(**common, county=src["County"], source_id="fl_laft_pdfs", harvester="harvest_laft_pdfs.py",
                         source_authority="GOVERNMENT_PLATFORM" if municode else "GOVERNMENT_DIRECT",
                         canonical_url=src["SourcePage"], document_url=src["Url"],
                         access_method="HTTP_GET_PDF", machine_format="PDF",
                         completeness_status=_completeness(src["County"]), evidence_ref="data/laft_pdf_sources.csv",
                         notes="Clerk PDF" + (" published through Municode (third-party document host)" if municode else "")))
    for src in _read("laft_html_sources.csv"):
        rows.append(_row(**common, county=src["County"], source_id="fl_laft_html", harvester="harvest_laft_html.py",
                         source_authority="GOVERNMENT_DIRECT", canonical_url=src["SourcePage"], document_url=src["Url"],
                         access_method="HTTP_GET_HTML", machine_format="HTML_CARDS" if src["County"] == "Putnam" else "HTML_TABLE",
                         completeness_status=_completeness(src["County"]), evidence_ref="data/laft_html_sources.csv",
                         notes="Clerk page; static HTML" + (" (WAF blocks runner IPs; ScraperAPI fallback)" if src["County"] in ("Escambia", "Columbia", "Union") else "")))
    for src in _read("laft_pioneer_counties.csv"):
        rows.append(_row(**common, county=src["County"], source_id="fl_laft_pioneer", harvester="harvest_laft_pioneer.py",
                         source_authority="GOVERNMENT_PLATFORM", canonical_url=src["BaseUrl"],
                         access_method="JSON_ENDPOINT", machine_format="JSON",
                         completeness_status=_completeness(src["County"]), evidence_ref="data/laft_pioneer_counties.csv",
                         notes="Pioneer Technology Group TaxSmartWeb portal contracted by the Clerk; GridSearchData JSON"))
    for src in _read("laft_realtdm_counties.csv"):
        rows.append(_row(**common, county=src["County"], source_id="fl_laft_realtdm", harvester="harvest_laft_realtdm.py",
                         source_authority="GOVERNMENT_PLATFORM", canonical_url=f"https://{src['Subdomain']}.realtdm.com/public/cases/list",
                         access_method="HTTP_POST_FORM", machine_format="HTML_CARDS",
                         completeness_status=_completeness(src["County"]), evidence_ref="data/laft_realtdm_counties.csv",
                         notes="realTDM case-management portal (RealAuction family) contracted by the Clerk; vendor domain"))
    singles = [
        ("Orange", "fl_laft_orange", "harvest_laft_orange.py", "GOVERNMENT_DIRECT",
         "https://occompt.com/158/Land-Available-For-Taxes", "HTTP_POST_FORM", "HTML_TABLE",
         "Comptroller-run TDSM search (guest disclaimer acknowledged, no credentials)"),
        ("St. Lucie", "fl_laft_stlucie", "harvest_laft_stlucie.py", "GOVERNMENT_PLATFORM",
         "https://acclaimweb.stlucieclerk.gov/TributeWeb/", "HEADLESS_BROWSER", "PORTAL",
         "AcclaimWeb/TributeWeb search on the Clerk's domain; Playwright"),
        ("Osceola", "fl_laft_osceola", "harvest_laft_osceola.py", "GOVERNMENT_PLATFORM",
         "https://officialrecords.osceolaclerk.org/browserviewtd/", "JSON_ENDPOINT", "JSON",
         "NewVision Systems search API on the Clerk's domain"),
        ("Hillsborough", "fl_laft_hillsborough", "harvest_laft_hillsborough.py", "GOVERNMENT_PLATFORM",
         "https://publicaccess.hillsclerk.com/TD/", "HEADLESS_BROWSER", "PORTAL",
         "OnBase Public Access View on the Clerk's domain; Playwright"),
        ("Leon", "fl_laft_leon", "harvest_laft_leon.py", "GOVERNMENT_DIRECT",
         "https://lforms.leonclerk.com/tax_deeds/lands-available.html", "JSON_ENDPOINT", "JSON",
         "Clerk portal's own JSON data file (listoflands.txt)"),
    ]
    for county, sid, script, authority, url, access, fmt, note in singles:
        rows.append(_row(**common, county=county, source_id=sid, harvester=script, source_authority=authority,
                         canonical_url=url, document_url=("https://lforms.leonclerk.com/tax_deeds/listoflands.txt" if county == "Leon" else ""),
                         access_method=access, machine_format=fmt, completeness_status=_completeness(county),
                         evidence_ref=f"scripts/{script}", notes=note))
    return rows


AUDIT = "MASTER LAFT/OTC/STRUCK-OFF AUDIT 2026-09-29"

# Florida counties with no production harvester - one row each, the audit's
# own evidence level, never runnable. County names must match the app's
# canonical spelling (fl-counties.svg).
FL_CANDIDATES = [
    # county, verification, authority, canonical_url, machine_format, notes
    ("Broward", "SEARCH_EVIDENCE_ONLY", "GOVERNMENT_DIRECT",
     "https://www.broward.org/RecordsTaxesTreasury/TaxesFees/Pages/LandsAvailableforTaxes.aspx", "HTML_TABLE",
     "County Records, Taxes & Treasury (not the Clerk) LAFT list; SharePoint list page seen in search results only; purchase is offline (quote within 3-5 business days). NOT VERIFIED."),
    ("Okaloosa", "SEARCH_EVIDENCE_ONLY", "GOVERNMENT_DIRECT",
     "https://www.okaloosaclerk.com/board-services/tax-deed-sales/lands-available-for-taxes/", "UNKNOWN",
     "Clerk page title only in search results. NOT VERIFIED."),
    ("DeSoto", "SEARCH_EVIDENCE_ONLY", "GOVERNMENT_DIRECT",
     "https://www.desotoclerk.com/public-sales/tax-deeds/", "PDF",
     "Dated PDF (2025/06 path) seen in search results; page reportedly says no properties listed. NOT VERIFIED."),
    ("Wakulla", "SEARCH_EVIDENCE_ONLY", "GOVERNMENT_DIRECT",
     "https://www.wakullaclerk.org/official_records/tax_deed_sales.php", "UNKNOWN",
     "Clerk page reportedly says the List of Lands currently has no parcels. NOT VERIFIED."),
    ("Charlotte", "SOURCE_EXISTS_ACCESS_UNKNOWN", "GOVERNMENT_DIRECT", "https://www.charlotteclerk.com/departments/taxdeed/", "UNKNOWN",
     "Tax Collector says the listing is obtained by contacting the Clerk; portal at or.charlotteclerk.com/TaxDeeds unexamined."),
    ("Collier", "SOURCE_EXISTS_ACCESS_UNKNOWN", "GOVERNMENT_DIRECT", "https://www.collierclerk.com/accessing-tax-deed-sales-in-collier-county/", "UNKNOWN",
     "Auctions described; no LAFT list seen."),
    ("Gilchrist", "SOURCE_EXISTS_ACCESS_UNKNOWN", "GOVERNMENT_DIRECT", "https://www.gilchristclerk.com/tax-deeds/", "UNKNOWN", "No list seen."),
    ("Lake", "SOURCE_EXISTS_ACCESS_UNKNOWN", "GOVERNMENT_DIRECT", "https://taxdeeds.lakecountyclerk.org", "UNKNOWN",
     "Portal plus a 2022-2023 dated PDF; no newer document seen."),
    ("Monroe", "SOURCE_EXISTS_ACCESS_UNKNOWN", "GOVERNMENT_DIRECT", "https://www.monroe-clerk.com", "UNKNOWN", "Home page only."),
    ("Nassau", "SOURCE_EXISTS_ACCESS_UNKNOWN", "GOVERNMENT_DIRECT", "https://www.nassauclerk.com/view-tax-deeds-1", "UNKNOWN", "No list URL."),
    ("Suwannee", "SOURCE_EXISTS_ACCESS_UNKNOWN", "GOVERNMENT_DIRECT", "https://www.suwgov.org/tax-deed-sales/", "UNKNOWN",
     "County page says unsold properties go on the List of Lands Available; no list URL."),
    ("Jefferson", "HISTORICAL_ONLY", "GOVERNMENT_DIRECT", "https://www.jeffersonclerk.com", "PDF",
     "Only a 2022/03 'Lands Available' PDF indexed; no current list found."),
    ("Baker", "NOT_FOUND_AFTER_SEARCH", "", "", "NONE", "No government LAFT source found after one search query; manual check needed."),
    ("Jackson", "NOT_FOUND_AFTER_SEARCH", "", "", "NONE", "No government LAFT source found after one search query; manual check needed."),
    ("Liberty", "NOT_FOUND_AFTER_SEARCH", "", "", "NONE", "No government LAFT source found after one search query; manual check needed."),
]


def fl_candidate_rows() -> list[dict]:
    rows = []
    for county, verification, authority, url, fmt, note in FL_CANDIDATES:
        found = verification != "NOT_FOUND_AFTER_SEARCH"
        rows.append(_row(state="FL", county=county, source_id="", harvester="", inventory_type=FL_INVENTORY if found else "",
                         ledgers=AVAILABLE if found else "",
                         source_authority=authority, canonical_url=url, access_method="UNKNOWN" if url else "NONE",
                         machine_format=fmt, verification_status=verification, governance_status="TERMS_NOT_VERIFIED" if url else "NOT_APPLICABLE",
                         last_checked="2026-09-29", completeness_status="UNKNOWN", evidence_ref=f"{AUDIT} s5", notes=note))
    return rows


# Texas counties whose struck-off / future-resale rows are in production
# today, all supplied by LGBS (delinquent-tax counsel), none from a county
# document. inventory_type is left blank on purpose: the 421 rows predate
# the raw tx_sale_status writer, so struck-off cannot be told from
# future-resale for them (migration 017 classifies only rows that carry the
# raw status).
TX_LGBS_PRODUCTION = ["Galveston", "Liberty", "Leon", "Maverick", "Jim Wells", "Hardin", "Van Zandt", "Goliad"]

# Government-published Texas struck-off / resale / trust lists the audit
# found in search results and could NOT fetch (sandbox egress blocked).
# Every row is SEARCH_EVIDENCE_ONLY; inventory_type is blank because a
# "resale list" may hold struck-off and future-resale inventory alike and
# nothing has been read. Harris keeps the registry's LEGAL_REVIEW_REQUIRED.
TX_CANDIDATES = [
    ("Dallas", "https://www.dallascounty.org/departments/pubworks/property-division.php", "HTML_TABLE", "TERMS_NOT_VERIFIED", "Public Works Property Division 'Tax Foreclosure Resales'; downloadable list reported."),
    ("Bexar", "https://www.bexar.org/DocumentCenter/View/41851/Bexar-County-Tax-Foreclosure-Struck-Off-Properties-General-Information", "UNKNOWN", "TERMS_NOT_VERIFIED", "DocumentCenter 'struck off' general information; distribution list container unknown."),
    ("Travis", "https://tax-office.traviscountytx.gov/properties/foreclosed", "XLSX", "TERMS_NOT_VERIFIED", "Tax Assessor-Collector 'Resale List' XLSX (ResaleList.xlsx) plus foreclosed-properties page."),
    ("Harris", "https://www.hctax.net/Property/listings/taxsalelisting", "PORTAL", "LEGAL_REVIEW_REQUIRED", "hctax.net Tax Resales category; registry tx_hctax LEGAL_REVIEW_REQUIRED (Phase 9.5) - gate refuses until resolved."),
    ("Montgomery", "https://www.mctx.org/departments/departments_q_-_z/tax_office/tax_trust_property.php", "HTML_TABLE", "TERMS_NOT_VERIFIED", "Tax Office 'Tax Trust Properties'."),
    ("Collin", "https://www.collincountytx.gov/Tax-Assessor/properties-for-sale", "HTML_TABLE", "TERMS_NOT_VERIFIED", "Tax Assessor 'Properties For Sale'; bids reportedly processed by outside counsel."),
    ("Brazoria", "https://www.brazoriacountytx.gov/departments/tax-office/property-taxes/sheriff-sale-tax-resales", "HTML_TABLE", "TERMS_NOT_VERIFIED", "Tax Office 'Sheriff Sale & Tax Resales'."),
    ("Jefferson", "https://www.jeffersoncountytx.gov", "PDF", "TERMS_NOT_VERIFIED", "Dated 'Resale List' PDFs (2026-06-02, 2026-03-03, 2025-09-09) under Documents/Sales; some may be sale notices."),
    ("Grayson", "https://taxsearch.co.grayson.tx.us:8443/Sales/Struck-Off-Properties", "PORTAL", "TERMS_NOT_VERIFIED", "County tax portal 'Struck Off Properties'."),
    ("Gregg", "https://www.greggcounty.texas.gov/assets/main/tax-assessor-collector/tax-resale-property.pdf", "PDF", "TERMS_NOT_VERIFIED", "Tax Assessor-Collector 'tax resale property' PDF."),
    ("Orange", "https://www.co.orange.tx.us/departments/TaxAssessor-Collector/PropertyTaxSales", "PDF", "TERMS_NOT_VERIFIED", "Tax Assessor-Collector 'Trust Property Listing' PDF dated 04.09.25 plus bid forms."),
    ("Camp", "https://www.campcad.org/struck-off-list/", "HTML_TABLE", "TERMS_NOT_VERIFIED", "Appraisal district 'Struck Off List of Properties' (03-03-2026 snippet)."),
    ("Hood", "https://www.hoodcad.net/struck-off-property-list/", "HTML_TABLE", "TERMS_NOT_VERIFIED", "Appraisal district 'Struck off Property List'."),
    ("Fayette", "https://www.fayettecad.org/trust-properties-offered-for-sale", "HTML_TABLE", "TERMS_NOT_VERIFIED", "Appraisal district 'Trust Properties Offered for Sale'."),
    ("Jim Wells", "https://www.co.jim-wells.tx.us", "PDF", "TERMS_NOT_VERIFIED", "County 'JWC Resale List' PDF (properties struck off to taxing entities)."),
    ("Tom Green", "https://www.tomgreencountytx.gov/page/cck.TrusteeTaxSales", "HTML_TABLE", "TERMS_NOT_VERIFIED", "County Clerk 'Tax Trustee Property' (struck-off) list, bid forms, procedures PDF."),
    ("Trinity", "https://www.trinitycad.net/resale-property-information/", "HTML_TABLE", "TERMS_NOT_VERIFIED", "Appraisal district 'Resale Property List'; bid form on the CIRA state host."),
    ("Randall", "https://www.randallcounty.gov/293/Sheriff-Sale", "HTML_TABLE", "TERMS_NOT_VERIFIED", "Struck-off properties list reported in summary text only - weakest of the candidates."),
    ("Bandera", "https://www.banderacounty.gov/page/open/1095/0/Purchasing%20Land%20Held%20in%20Trust", "HTML_TABLE", "TERMS_NOT_VERIFIED", "Tax Office 'land held in trust'; county also appears in a blocked vendor's roster."),
    ("Bee", "https://www.beecounty.texas.gov", "DOCX", "TERMS_NOT_VERIFIED", "'TAX FORECLOSURE RESALE' DOCX; list or procedure unknown."),
]

# Counties whose only known publication is a BLOCKED vendor (PBFCM / MVBA).
# No URL is recorded: a blocked vendor's document must never enter a
# machine-readable registry a future adapter could pick up.
TX_BLOCKED_VENDOR_ONLY = {
    "tx_pbfcm": ["Austin", "Chambers", "Fort Bend", "Hidalgo", "Matagorda", "Maverick", "Milam",
                 "Nacogdoches", "San Jacinto", "Uvalde", "Walker", "Zavala"],
    "tx_mvba": ["Calhoun", "Runnels"],
}


def tx_rows() -> list[dict]:
    rows = []
    for county in TX_LGBS_PRODUCTION:
        rows.append(_row(state="TX", county=county, source_id="tx_lgbs", harvester="harvesters/texas_harvester.py",
                         inventory_type="", source_authority="VENDOR_COUNSEL", canonical_url="https://taxsales.lgbs.com/",
                         access_method="VENDOR_API", machine_format="JSON", verification_status="PRODUCTION_VERIFIED",
                         governance_status="APPROVED", last_checked="2026-09-23", completeness_status="FAILED",
                         ledgers=f"{AUCTIONS}|{AVAILABLE}",
                         evidence_ref="harvesters/governance/registry.py tx_lgbs; data/tx_lgbs_observed_county_roster.csv",
                         notes="Delinquent-tax counsel publication (not the county); rows carry no per-property URL; feed INCOMPLETE on 2026-09-29, last success 2026-09-23. Do not retry."))
    for county, url, fmt, governance, note in TX_CANDIDATES:
        rows.append(_row(state="TX", county=county, source_id=("tx_hctax" if county == "Harris" else ""), harvester="",
                         inventory_type="", source_authority="GOVERNMENT_DIRECT", canonical_url=url, ledgers=AVAILABLE,
                         access_method="UNKNOWN", machine_format=fmt, verification_status="SEARCH_EVIDENCE_ONLY",
                         governance_status=governance, last_checked="2026-09-29", completeness_status="UNKNOWN",
                         evidence_ref=f"{AUDIT} s5", notes=note + " NOT VERIFIED (search index only)."))
    for sid, counties in TX_BLOCKED_VENDOR_ONLY.items():
        for county in counties:
            rows.append(_row(state="TX", county=county, source_id=sid, harvester="", inventory_type="",
                             source_authority="VENDOR_COUNSEL", canonical_url="", access_method="NONE", machine_format="PDF",
                             verification_status="BLOCKED_VENDOR_ONLY", governance_status="BLOCKED",
                             last_checked="2026-09-29", completeness_status="UNKNOWN", evidence_ref=f"{AUDIT} s5",
                             notes="Only a BLOCKED vendor publishes this county's struck-off list; discovery-only, no URL recorded."))
    return rows


# Alabama (2026-09-29): ONE state-level candidate row for the researched
# concept - tax-delinquent land held by the State and sold by the Alabama
# Department of Revenue, Property Tax Division (State Land Commissioner),
# reported (search index only) as per-county transcripts updated weekly,
# with the purchase price quoted on application. Every field that would
# need a fetched page to fill (URL, access method, machine format) is blank
# or UNKNOWN on purpose: no URL is recorded until one has been read from
# this repository, and SEARCH_EVIDENCE_ONLY / TERMS_NOT_VERIFIED keep the
# gate shut (harvesters/otc/gate.py refuses the state before it even looks
# at the row). See docs/alabama-onboarding.md for the activation checklist.
# 2026-09-30: the Alabama Department of Revenue source, configured in
# harvesters/otc/adapters/alabama.py (ADOR_SOURCE / ADOR_EVIDENCE). The
# URLs, the query parameter names and the process wording were seen in a
# web search's index of revenue.alabama.gov (page titles, URLs, snippets)
# - concrete, but STILL search-index evidence: nothing was fetched from
# this repository. So the row stays SEARCH_EVIDENCE_ONLY / TERMS_NOT_VERIFIED
# with no harvester named (a non-production row may not name one) and can
# never be run (harvesters/otc/gate.py refuses the state before the row).
sys.path.insert(0, str(REPO))
from harvesters.otc.adapters.alabama import ADOR_SOURCE, EVIDENCE_DATE  # noqa: E402

AL_STATE_LAND = dict(
    state="AL", county="STATEWIDE", source_id=ADOR_SOURCE.source_id, harvester="",
    inventory_type=ADOR_SOURCE.inventory_type.value, source_authority=ADOR_SOURCE.source_authority.value,
    canonical_url=ADOR_SOURCE.list_url, document_url="",
    purchase_url=ADOR_SOURCE.application_url, purchase_url_kind=ADOR_SOURCE.application_url_kind.value,
    access_method="HTTP_GET_HTML", machine_format="PORTAL",
    verification_status="SEARCH_EVIDENCE_ONLY", governance_status="TERMS_NOT_VERIFIED",
    last_checked=EVIDENCE_DATE, completeness_status="UNKNOWN",
    evidence_ref="WEB SEARCH 2026-09-30 (revenue.alabama.gov page titles, URLs, query strings, snippets - "
                 "harvesters/otc/adapters/alabama.py ADOR_EVIDENCE); " + AUDIT,
    notes="State-held tax-delinquent land ('tax delinquent properties currently in State inventory') sold by ADOR Property Tax "
          "Division. canonical_url = the 'Tax Delinquent Properties for Sale Search' page (county / CS Number / Parcel Number / "
          "assessed-name search); purchase_url = the 'Tax Delinquent Property and Land Sales' process page (application for "
          "purchase; price quoted on application) - an instructions page, never a property link. Per-property application "
          "links are the CS Number links on the results page (read from the page by the adapter, never constructed). "
          "Transcript document URL/format unknown (document_url blank). Nothing fetched from this repository; search-index "
          "evidence only; not activated.",
    publishing_unit="STATE",
    publishing_unit_name=ADOR_SOURCE.publishing_unit_name,
    amount_kind=ADOR_SOURCE.amount_kind.value,
    update_frequency="weekly (the Land Sales page says county transcripts are 'updated weekly', per the search index 2026-09-30; not read directly)",
    source_terminology=ADOR_SOURCE.source_terminology + " (search-index wording)",
    ledgers=AVAILABLE,
)


def al_rows() -> list[dict]:
    return [_row(**AL_STATE_LAND)]


# 2026-09-30: Arkansas (COSL Post Auction Sales List) and Louisiana (East
# Baton Rouge adjudicated property), configured in
# harvesters/otc/adapters/arkansas.py / louisiana.py from search-index
# evidence. Same standing as the Alabama row: SEARCH_EVIDENCE_ONLY /
# TERMS_NOT_VERIFIED, no harvester, never runnable (states not activated).
from harvesters.otc.adapters.arkansas import COSL_SOURCE  # noqa: E402
from harvesters.otc.adapters.louisiana import EBR_SOURCE  # noqa: E402

AR_COSL = dict(
    state="AR", county="STATEWIDE", source_id=COSL_SOURCE.source_id, harvester="",
    inventory_type=COSL_SOURCE.tabular.inventory_type.value, source_authority=COSL_SOURCE.tabular.source_authority.value,
    canonical_url=COSL_SOURCE.list_url, document_url="",
    purchase_url=COSL_SOURCE.application_url, purchase_url_kind=COSL_SOURCE.application_url_kind.value,
    access_method="HTTP_GET_HTML", machine_format="UNKNOWN",
    verification_status="SEARCH_EVIDENCE_ONLY", governance_status="TERMS_NOT_VERIFIED",
    last_checked="2026-09-30", completeness_status="UNKNOWN",
    evidence_ref="WEB SEARCH 2026-09-30 (cosl.org page titles, URLs, query string, snippets - harvesters/otc/adapters/arkansas.py COSL_EVIDENCE); " + AUDIT,
    notes="Commissioner of State Lands 'Post Auction Sales List': parcels certified to the State that did not sell at the initial "
          "public auction, offered per county (canonical_url + ?county=<NAME>; one value observed) 30 days after the offering; the "
          "tax due is the minimum bid; bids are placed through the State's own online auction (auction.cosl.org - not a per-parcel "
          "link, not recorded as purchase_url); purchase_url = the State's buyer-instructions page. 10-business-day redemption after "
          "the post auction sale. Nothing fetched from this repository; search-index evidence only; not activated.",
    publishing_unit="STATE", publishing_unit_name=COSL_SOURCE.publishing_unit_name,
    amount_kind=COSL_SOURCE.tabular.amount_kind.value,
    update_frequency="daily (reported by the 2026-09-29 audit; not corroborated by the 2026-09-30 search; not read directly)",
    source_terminology=COSL_SOURCE.source_terminology + " (search-index wording)",
    ledgers=AVAILABLE,
)
LA_EBR = dict(
    state="LA", county=EBR_SOURCE.county, source_id=EBR_SOURCE.source_id, harvester="",
    inventory_type=EBR_SOURCE.inventory_type.value, source_authority=EBR_SOURCE.source_authority.value,
    canonical_url=EBR_SOURCE.list_url, document_url=EBR_SOURCE.document_url, purchase_url="", purchase_url_kind="",
    access_method="JSON_ENDPOINT", machine_format="CSV",
    verification_status="SEARCH_EVIDENCE_ONLY", governance_status="TERMS_NOT_VERIFIED",
    last_checked="2026-09-30", completeness_status="UNKNOWN",
    evidence_ref="WEB SEARCH 2026-09-30 (data.brla.gov dataset titles, URLs, description and column list - harvesters/otc/adapters/louisiana.py EBR_EVIDENCE); " + AUDIT,
    notes="East Baton Rouge Parish open-data dataset a4h4-zi7e 'Adjudicated Property' - properties 'adjudicated to the Parish of East "
          "Baton Rouge' after no one bought them at the tax sale. canonical_url = the dataset page; document_url = its CSV download "
          "(JSON / XML / RDF also offered). Indexed columns: tax year, property number, taxpayer name / address, physical address, "
          "subdivision, block, lot, ward, legal description, fair market value, total assessed value, council district, zip, "
          "geolocation. No price and no purchase link in the dataset (the audit reports a vendor purchase process - unverified, not "
          "implemented). Whether the dataset is current inventory or a yearly snapshot is not established. Nothing fetched from this "
          "repository; search-index evidence only; not activated.",
    publishing_unit="PARISH", publishing_unit_name=EBR_SOURCE.publishing_unit_name,
    amount_kind="NOT_PUBLISHED",
    update_frequency="not established (the GIS 'Adjudicated Parcel' layer reads 'last updated September 07, 2026' in the index; the dataset's own cadence not read)",
    source_terminology=EBR_SOURCE.source_terminology + " (search-index wording)",
    ledgers=AVAILABLE,
)


def ar_rows() -> list[dict]:
    return [_row(**AR_COSL)]


def la_rows() -> list[dict]:
    return [_row(**LA_EBR)]


# ---------------------------------------------------------------------------
# AUCTIONS and LIENS & CERTIFICATES production sources (2026-09-30, three
# ledgers). Until now the registry only knew the AVAILABLE ledger's sources;
# the deed-auction and certificate harvesters kept their county lists in
# their own CSVs (data/realauction_counties.csv,
# data/florida_certificate_sale_platforms.csv, data/tx_realauction_counties.csv)
# and the governance registry (harvesters/governance/registry.py) knew the
# platforms. Same derivation rule as the LAFT rows: the harvesters' own
# CSVs stay the operational truth, the registry rows are generated from
# them, and a test pins the two equal. Every URL below is the exact form
# the shipped harvester requests (read from the script, not invented):
#   harvest_all_counties.ps1     https://<Host>/index.cfm?zaction=USER&zmethod=CALENDAR
#   harvest_okaloosa_bid4assets.ps1  https://www.bid4assets.com/OkaloosaFLTax/listings
#   harvest_lienhub_certificates.ps1 https://lienhub.com/county/<slug>/countyheld/certificates
#   harvesters/texas_harvester.py (tx_realauction)  https://<Host>/index.cfm?zaction=USER&zmethod=CALENDAR
# completeness_status is UNKNOWN for all of them here: these ledgers'
# per-county freshness lives in their own status files
# (harvest_all_status.json / harvest_certificates_status.json /
# harvest_texas_status.json - harvesters/ledgers/domains.py) and the
# registry patch (scripts/unit_freshness.py) is what rewrites it after a
# run. No inventory_type: an auction row and a certificate row carry none.

REALAUCTION_CALENDAR = "https://{host}/index.cfm?zaction=USER&zmethod=CALENDAR"


def _lienhub_slug(county: str) -> str:
    """harvest_lienhub_certificates.ps1 Get-Slug: lowercase, letters only."""
    return "".join(ch for ch in county.lower() if "a" <= ch <= "z")


def fl_auction_rows() -> list[dict]:
    rows = []
    common = dict(state="FL", inventory_type="", verification_status="PRODUCTION_VERIFIED",
                  governance_status="APPROVED_GRANDFATHERED", last_checked="2026-09-30",
                  completeness_status="UNKNOWN", ledgers=AUCTIONS, source_authority="VENDOR_AUCTION")
    for src in _read("realauction_counties.csv"):
        rows.append(_row(**common, county=src["County"], source_id="fl_realauction", harvester="harvest_all_counties.ps1",
                         canonical_url=REALAUCTION_CALENDAR.format(host=src["Host"]),
                         access_method="HTTP_GET_HTML", machine_format="HTML_TABLE",
                         evidence_ref="data/realauction_counties.csv; harvesters/governance/registry.py fl_realauction",
                         notes="RealAuction / RealForeclose / RealTaxDeed tax-deed sale calendar contracted by the Clerk; per-sale "
                               "auction pages carry the case, bid, parcel and the county appraiser deep-link."))
    rows.append(_row(**common, county="Okaloosa", source_id="fl_bid4assets_okaloosa", harvester="harvest_okaloosa_bid4assets.ps1",
                     canonical_url="https://www.bid4assets.com/OkaloosaFLTax/listings",
                     access_method="HTTP_GET_HTML", machine_format="HTML_CARDS",
                     evidence_ref="scripts/harvest_okaloosa_bid4assets.ps1",
                     notes="Bid4Assets tax-deed listings for Okaloosa County (the only FL county on this platform, per the "
                           "script's own header); per-auction detail pages read one at a time."))
    return rows


def fl_certificate_rows() -> list[dict]:
    rows = []
    for src in _read("florida_certificate_sale_platforms.csv"):
        if src["Platform"] != "LienHub":
            continue
        rows.append(_row(state="FL", county=src["County"], source_id="fl_lienhub_certificates",
                         harvester="harvest_lienhub_certificates.ps1", inventory_type="", source_authority="VENDOR_AUCTION",
                         canonical_url=f"https://lienhub.com/county/{_lienhub_slug(src['County'])}/countyheld/certificates",
                         access_method="JSON_ENDPOINT", machine_format="JSON",
                         verification_status="PRODUCTION_VERIFIED", governance_status="APPROVED_GRANDFATHERED",
                         last_checked="2026-09-30", completeness_status="UNKNOWN",
                         evidence_ref="data/florida_certificate_sale_platforms.csv; harvesters/governance/registry.py fl_lienhub_certificates",
                         notes="LienHub county-held tax certificates (the certificate itself, never the parcel): DataTables JSON "
                               "endpoint behind the county-held certificates page; certificate number, account, purchase "
                               "amount, expiration, interest rate.",
                         ledgers=LIENS))
    return rows


def tx_auction_rows() -> list[dict]:
    rows = []
    for src in _read("tx_realauction_counties.csv"):
        rows.append(_row(state="TX", county=src["County"], source_id="tx_realauction", harvester="harvesters/texas_harvester.py",
                         inventory_type="", source_authority="VENDOR_AUCTION",
                         canonical_url=REALAUCTION_CALENDAR.format(host=src["Host"]),
                         access_method="HTTP_GET_HTML", machine_format="HTML_TABLE",
                         verification_status="PRODUCTION_VERIFIED", governance_status="APPROVED",
                         last_checked="2026-09-30", completeness_status="UNKNOWN",
                         evidence_ref="data/tx_realauction_counties.csv; harvesters/governance/registry.py tx_realauction",
                         notes="RealAuction sheriff-sale / tax-sale calendar (sheriffsaleauctions.com or realforeclose.com) "
                               "for the county's tax foreclosure sales; AUCTIONS only - Texas has no certificate ledger.",
                         ledgers=AUCTIONS))
    return rows


# Arizona (2026-09-30): ONE county-level LIENS & CERTIFICATES candidate - the
# Maricopa County Treasurer's "State CP" list (certificates of purchase held
# by the State, sold by assignment), configured in
# harvesters/otc/adapters/arizona.py from search-index evidence. Same
# standing as AL/AR/LA: SEARCH_EVIDENCE_ONLY / TERMS_NOT_VERIFIED, no
# harvester, never runnable (state not activated). It is the first
# non-AVAILABLE candidate; its inventory_type is blank because a lien is not
# purchasable land.
from harvesters.otc.adapters.arizona import MARICOPA_SOURCE  # noqa: E402

AZ_MARICOPA_CP = dict(
    state="AZ", county=MARICOPA_SOURCE.county, source_id=MARICOPA_SOURCE.source_id, harvester="",
    inventory_type="", source_authority="GOVERNMENT_DIRECT",
    canonical_url=MARICOPA_SOURCE.list_url, document_url=MARICOPA_SOURCE.document_url,
    purchase_url=MARICOPA_SOURCE.application_url, purchase_url_kind=MARICOPA_SOURCE.application_url_kind.value,
    access_method="HTTP_GET_HTML", machine_format="CSV",
    verification_status="SEARCH_EVIDENCE_ONLY", governance_status="TERMS_NOT_VERIFIED",
    last_checked="2026-09-30", completeness_status="UNKNOWN",
    evidence_ref="WEB SEARCH 2026-09-30 (treasurer.maricopa.gov page titles, URLs, snippets - harvesters/otc/adapters/arizona.py MARICOPA_EVIDENCE); " + AUDIT,
    notes="Maricopa County Treasurer 'Current State CP Listing': tax-lien certificates of purchase struck to the State, sold by "
          "assignment (Assignments Purchase Form; by mail from 2026-03-02 per the index). canonical_url = the download page; "
          "document_url = its CSV; purchase_url = the Treasurer's Tax Assignment page (instructions, never a per-lien link). "
          "The CSV's columns, the CP number and parcel formats and what the amount column is have NOT been read. Nothing "
          "fetched from this repository; search-index evidence only; not activated. Arizona's tax-deeded land (an AVAILABLE "
          "source) is not represented - nothing located.",
    publishing_unit="COUNTY", publishing_unit_name="Maricopa County Treasurer",
    amount_kind=MARICOPA_SOURCE.amount_kind.value,
    update_frequency="not established",
    source_terminology=MARICOPA_SOURCE.source_terminology + " (search-index wording)",
    ledgers=LIENS,
)


def az_rows() -> list[dict]:
    return [_row(**AZ_MARICOPA_CP)]


def build_rows() -> list[dict]:
    rows = (fl_production_rows() + fl_candidate_rows() + fl_auction_rows() + fl_certificate_rows()
            + tx_rows() + tx_auction_rows() + al_rows() + ar_rows() + la_rows() + az_rows())
    rows.sort(key=lambda r: (r["state"], r["county"], r["source_id"]))
    return rows


def render(rows: list[dict]) -> str:
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main() -> int:
    OUT.write_text(render(build_rows()), encoding="utf-8")
    print(f"wrote {OUT} ({len(build_rows())} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
