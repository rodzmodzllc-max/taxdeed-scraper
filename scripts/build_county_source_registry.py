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
]

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
    row.update(kw)
    return row


def _read(name: str) -> list[dict]:
    with open(DATA / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fl_production_rows() -> list[dict]:
    rows: list[dict] = []
    common = dict(state="FL", inventory_type=FL_INVENTORY, verification_status="PRODUCTION_VERIFIED",
                  governance_status="APPROVED_GRANDFATHERED", last_checked="2026-09-29")
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
        rows.append(_row(state="FL", county=county, source_id="", harvester="", inventory_type=FL_INVENTORY if verification != "NOT_FOUND_AFTER_SEARCH" else "",
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
                         evidence_ref="harvesters/governance/registry.py tx_lgbs; data/tx_lgbs_observed_county_roster.csv",
                         notes="Delinquent-tax counsel publication (not the county); rows carry no per-property URL; feed INCOMPLETE on 2026-09-29, last success 2026-09-23. Do not retry."))
    for county, url, fmt, governance, note in TX_CANDIDATES:
        rows.append(_row(state="TX", county=county, source_id=("tx_hctax" if county == "Harris" else ""), harvester="",
                         inventory_type="", source_authority="GOVERNMENT_DIRECT", canonical_url=url,
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


def build_rows() -> list[dict]:
    rows = fl_production_rows() + fl_candidate_rows() + tx_rows()
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
