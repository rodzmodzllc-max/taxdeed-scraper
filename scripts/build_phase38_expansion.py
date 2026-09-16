#!/usr/bin/env python3
"""Phase 38. Turn the two OFFICIAL STATEWIDE DIRECTORIES that were actually
fetched this phase into the repository's coverage artifacts.

What was actually fetched, and what that does and does not prove
----------------------------------------------------------------
Two directories, both operated by the state itself, both read in full:

  * Texas Comptroller county directory - 254 per-county pages,
    comptroller.texas.gov/taxes/property-tax/county-directory/<slug>.php,
    each naming that county's Appraisal District (chief appraiser, website,
    "Last Updated") and its Tax Assessor-Collector (name, website, "Last
    Updated"). robots.txt Allow: /taxes/ covers this path.
  * Florida DOR Local Officials directory -
    floridarevenue.com/property/Pages/LocalOfficials.aspx, whose three
    dropdowns carry the Property Appraiser, Tax Collector and Value
    Adjustment Board/Clerk destination URL for all 67 counties. Phase 35
    recorded this page as MECHANISM_CONFIRMED_NOT_EXTRACTED because the
    list is not statically linkable; the options were read out of the DOM
    this phase, which is what closed that gap.

This proves ONE thing: the state itself names this office and this URL for
this county. It does NOT prove the county site is reachable, that it
publishes bulk data or an API, or - above all - that its terms permit
automated access, storage, customer display, export or redistribution. No
county site was fetched this phase and no county's terms were read. Every
county office therefore lands at LEGAL_REVIEW_REQUIRED, per Phase 38
Section 31: permission is never inferred from silence.

DISCOVERED != VERIFIED != AUTHORIZED != PRODUCTION. This script moves 321
counties along the FIRST arrow only.

Vocabulary
----------
`SourceStatus` in harvesters/governance/registry.py is NOT extended - the
eight approval states are untouched and no second legal-status system is
created. One value is added to the CSV-level `verification_status`
vocabulary that the coverage maps already use:

    DIRECTORY_LISTED - a state-operated directory names this office and
                       this URL, and that directory entry was read. The
                       office's own site was not fetched and its terms were
                       not reviewed.

It sits deliberately BELOW the existing MECHANISM_CONFIRMED and
CONTENT_VERIFIED, because it is weaker than both: writing these rows as
CONTENT_VERIFIED would claim we read the county's site, and we did not.

Read-only with respect to production: no database driver, no DML, no
Supabase, no migration, no harvest. Reads two checked-in raw extracts plus
the existing matrices, writes CSV/JSON under data/.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
REF = DATA / "reference"

FETCHED_ON = "2026-09-16"
TX_DIR_BASE = "https://comptroller.texas.gov/taxes/property-tax/county-directory/"
FL_DIR_URL = "https://floridarevenue.com/property/Pages/LocalOfficials.aspx"

DIRECTORY_LISTED = "DIRECTORY_LISTED"
LEGAL_REVIEW = "LEGAL_REVIEW_REQUIRED"
NOT_LISTED = "SOURCE_NOT_FOUND"


def read_psv(path: Path) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(line.split("|"))
    return rows


def tx_slug(county: str) -> str:
    return county.lower().replace(" ", "").replace(".", "").replace("'", "")


# ---------------------------------------------------------------------------
# 1. The two new directory tables - the raw evidence, with provenance
# ---------------------------------------------------------------------------

def build_tx_directory() -> list[dict]:
    out = []
    for county, code, chief, cad_url, cad_upd, tac_name, tac_url, tac_upd in read_psv(
        REF / "tx_comptroller_directory_raw.psv"
    ):
        out.append({
            "state": "TX",
            "county": county,
            "comptroller_county_code": code,
            "comptroller_directory_url": f"{TX_DIR_BASE}{tx_slug(county)}.php",
            "appraisal_district_chief_appraiser": chief,
            "appraisal_district_url": cad_url,
            "appraisal_district_source_timestamp": cad_upd,
            "appraisal_district_status": DIRECTORY_LISTED if cad_url else NOT_LISTED,
            "tax_assessor_collector_name": tac_name,
            "tax_assessor_collector_url": tac_url,
            "tax_assessor_collector_source_timestamp": tac_upd,
            "tax_assessor_collector_status": DIRECTORY_LISTED if tac_url else NOT_LISTED,
            "directory_operator": "Texas Comptroller of Public Accounts",
            "retrieved_at": FETCHED_ON,
            "terms_reviewed": "NO",
            "legal_status": LEGAL_REVIEW,
        })
    return out


def build_fl_directory() -> list[dict]:
    out = []
    for county, pa_url, tc_url, vab_url in read_psv(REF / "fl_dor_local_officials_raw.psv"):
        out.append({
            "state": "FL",
            "county": county,
            "directory_url": FL_DIR_URL,
            "property_appraiser_url": pa_url,
            "property_appraiser_status": DIRECTORY_LISTED if pa_url else NOT_LISTED,
            "tax_collector_url": tc_url,
            "tax_collector_status": DIRECTORY_LISTED if tc_url else NOT_LISTED,
            "vab_clerk_url": vab_url,
            "vab_clerk_status": DIRECTORY_LISTED if vab_url else NOT_LISTED,
            "directory_operator": "Florida Department of Revenue",
            "retrieved_at": FETCHED_ON,
            "terms_reviewed": "NO",
            "legal_status": LEGAL_REVIEW,
        })
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# 2. Fold the new facts into the EXISTING matrices - extend, never replace
# ---------------------------------------------------------------------------

def update_tx_matrix(tx: list[dict]) -> tuple[int, int]:
    path = DATA / "tx_county_coverage_matrix.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    by_county = {r["county"]: r for r in tx}
    cad, tac = 0, 0
    for row in rows:
        d = by_county.get(row["county"])
        if not d:
            continue
        row["comptroller_directory_url"] = d["comptroller_directory_url"]
        if d["appraisal_district_url"]:
            row["appraisal_district_name"] = f"{row['county']} County Appraisal District"
            row["appraisal_district_url"] = d["appraisal_district_url"]
            row["appraisal_district_source"] = (
                "County Appraisal District named by the Texas Comptroller county directory"
            )
            row["appraisal_district_source_status"] = f"{DIRECTORY_LISTED} ({LEGAL_REVIEW} - county site not fetched, terms not reviewed)"
            row["appraisal_district_verification_status"] = DIRECTORY_LISTED
            cad += 1
        else:
            row["appraisal_district_verification_status"] = NOT_LISTED
        if d["tax_assessor_collector_url"]:
            row["tax_assessor_collector_name"] = d["tax_assessor_collector_name"]
            row["tax_assessor_collector_url"] = d["tax_assessor_collector_url"]
            tac += 1
    write_csv(path, rows)
    return cad, tac


def update_fl_matrix(fl: list[dict]) -> tuple[int, int, int]:
    path = DATA / "fl_county_coverage_matrix.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    by_county = {r["county"]: r for r in fl}
    pa = tc = clerk = 0
    for row in rows:
        d = by_county.get(row["county"])
        if not d:
            continue
        if d["property_appraiser_url"]:
            row["property_appraiser_name"] = f"{row['county']} County Property Appraiser"
            row["property_appraiser_url"] = d["property_appraiser_url"]
            row["property_appraiser_source"] = (
                "County Property Appraiser named by the Florida DOR Local Officials directory"
            )
            row["property_appraiser_verification_status"] = DIRECTORY_LISTED
            pa += 1
        else:
            row["property_appraiser_verification_status"] = NOT_LISTED
        if d["tax_collector_url"]:
            tc += 1
        if d["vab_clerk_url"]:
            row["recorded_document_source"] = (
                f"County Clerk / Value Adjustment Board: {d['vab_clerk_url']} "
                f"({DIRECTORY_LISTED}, {LEGAL_REVIEW})"
            )
            clerk += 1
        row["acquisition_method"] = row.get("acquisition_method") or "OFFICIAL_PUBLIC_SEARCH"
    write_csv(path, rows)
    return pa, tc, clerk


# ---------------------------------------------------------------------------
# 3. Section 32's operational rights map
# ---------------------------------------------------------------------------

RIGHTS_COLUMNS = [
    "state", "county", "provider", "source", "field_category", "technical_access",
    "automated_access", "storage", "caching", "derivation", "customer_display",
    "export", "api", "image_use", "document_use", "commercial_use",
    "authorization_required", "legal_status", "evidence_url", "reviewed_at", "notes",
]

UNREVIEWED = "UNREVIEWED"


def rights_row(**kw) -> dict:
    row = {c: UNREVIEWED for c in RIGHTS_COLUMNS}
    row.update(kw)
    return row


def build_rights_matrix(fl: list[dict], tx: list[dict]) -> list[dict]:
    rows: list[dict] = []
    # The two statewide directories themselves - the only sources this phase
    # actually read, so the only ones whose technical access is observed.
    rows.append(rights_row(
        state="TX", county="ALL", provider="Texas Comptroller of Public Accounts",
        source="tx_comptroller_directory", field_category="DIRECTORY",
        technical_access="YES", automated_access="ROBOTS_ALLOWED",
        authorization_required=UNREVIEWED, legal_status=LEGAL_REVIEW,
        evidence_url=TX_DIR_BASE, reviewed_at=FETCHED_ON,
        notes="254/254 county pages read this phase. robots.txt Allow: /taxes/. Terms of use NOT reviewed.",
    ))
    rows.append(rights_row(
        state="FL", county="ALL", provider="Florida Department of Revenue",
        source="fl_dor_local_officials", field_category="DIRECTORY",
        technical_access="YES", automated_access=UNREVIEWED,
        authorization_required=UNREVIEWED, legal_status=LEGAL_REVIEW,
        evidence_url=FL_DIR_URL, reviewed_at=FETCHED_ON,
        notes="All 67 counties read from the page's own dropdowns. Terms of use NOT reviewed.",
    ))
    for d in fl:
        for provider, url, cat in (
            ("County Property Appraiser", d["property_appraiser_url"],
             "PROPERTY_IDENTITY|PARCEL_ID|ADDRESS|LEGAL_DESCRIPTION|PROPERTY_TYPE|ACREAGE|ASSESSED_VALUE|MARKET_VALUE|TAXABLE_VALUE|OWNERSHIP|PROPERTY_CHARACTERISTICS|SALES_HISTORY"),
            ("County Tax Collector", d["tax_collector_url"],
             "ANNUAL_TAX|DELINQUENT_TAX|TAX_CERTIFICATE|PAYMENT_STATUS"),
            ("County Clerk / Value Adjustment Board", d["vab_clerk_url"],
             "CASE_NUMBER|TAX_SALE|SALE_STATUS|RECORDED_DOCUMENTS|LIENS"),
        ):
            if not url:
                continue
            rows.append(rights_row(
                state="FL", county=d["county"], provider=provider,
                source=url, field_category=cat, technical_access=UNREVIEWED,
                authorization_required=UNREVIEWED, legal_status=LEGAL_REVIEW,
                evidence_url=FL_DIR_URL, reviewed_at=FETCHED_ON,
                notes=f"{DIRECTORY_LISTED} by FL DOR. Site not fetched; terms not reviewed.",
            ))
    for d in tx:
        for provider, url, cat in (
            ("County Appraisal District", d["appraisal_district_url"],
             "PROPERTY_IDENTITY|PARCEL_ID|ADDRESS|LEGAL_DESCRIPTION|PROPERTY_TYPE|ACREAGE|MARKET_VALUE|APPRAISED_VALUE|TAXABLE_VALUE|OWNERSHIP|PROPERTY_CHARACTERISTICS|GIS"),
            ("County Tax Assessor-Collector", d["tax_assessor_collector_url"],
             "ANNUAL_TAX|DELINQUENT_TAX|PAYMENT_STATUS|TAX_SALE"),
        ):
            if not url:
                continue
            rows.append(rights_row(
                state="TX", county=d["county"], provider=provider,
                source=url, field_category=cat, technical_access=UNREVIEWED,
                authorization_required=UNREVIEWED, legal_status=LEGAL_REVIEW,
                evidence_url=d["comptroller_directory_url"], reviewed_at=FETCHED_ON,
                notes=f"{DIRECTORY_LISTED} by TX Comptroller. Site not fetched; terms not reviewed.",
            ))
    return rows


# ---------------------------------------------------------------------------
# 4. Summary - the new baseline, with the old one preserved beside it
# ---------------------------------------------------------------------------

def build_summary(fl: list[dict], tx: list[dict], prior: dict) -> dict:
    fl_pa = sum(1 for d in fl if d["property_appraiser_url"])
    fl_tc = sum(1 for d in fl if d["tax_collector_url"])
    fl_clerk = sum(1 for d in fl if d["vab_clerk_url"])
    tx_cad = sum(1 for d in tx if d["appraisal_district_url"])
    tx_tac = sum(1 for d in tx if d["tax_assessor_collector_url"])
    history = prior.pop("_history", [])
    history.append(prior)
    return {
        "_phase": "Phase 38 (County Expansion and Alternate Source Acquisition), " + str(date.today()),
        "_measurement_note": (
            "'directory_listed' counts a county whose office and URL are named by the "
            "state's own directory and whose directory entry was read this phase. It is "
            "NOT technical verification and NOT authorization: no county site was fetched "
            "and no county's terms were reviewed. Every one is LEGAL_REVIEW_REQUIRED."
        ),
        "fl_counties_total": 67,
        "fl_counties_property_appraiser_directory_listed": fl_pa,
        "fl_counties_tax_collector_directory_listed": fl_tc,
        "fl_counties_clerk_vab_directory_listed": fl_clerk,
        "fl_counties_with_any_auction_source": prior.get("fl_counties_with_any_auction_source"),
        "fl_counties_with_any_cert_source": prior.get("fl_counties_with_any_cert_source"),
        "fl_counties_with_any_laft_source": prior.get("fl_counties_with_any_laft_source"),
        "fl_counties_with_no_known_source_any_category": 0,
        "tx_counties_total": 254,
        "tx_counties_appraisal_district_directory_listed": tx_cad,
        "tx_counties_tax_assessor_collector_directory_listed": tx_tac,
        "tx_counties_with_any_auction_source": prior.get("tx_counties_with_any_auction_source"),
        "tx_counties_with_no_known_source_any_category": sum(
            1 for d in tx if not d["appraisal_district_url"] and not d["tax_assessor_collector_url"]
        ),
        "counties_with_approved_production_source": {
            "FL": "0 new this phase (existing grandfathered auction/certificate/LAFT sources unchanged)",
            "TX": "0 new this phase (tx_lgbs unchanged)",
        },
        "counties_with_legal_review_source": {"FL": fl_pa + fl_tc + fl_clerk, "TX": tx_cad + tx_tac},
        "_history": history,
    }


def main() -> int:
    fl = build_fl_directory()
    tx = build_tx_directory()
    assert len(fl) == 67, len(fl)
    assert len(tx) == 254, len(tx)

    write_csv(DATA / "fl_official_directory.csv", fl)
    write_csv(DATA / "tx_official_directory.csv", tx)
    print(f"fl_official_directory.csv        {len(fl)} counties")
    print(f"tx_official_directory.csv        {len(tx)} counties")

    cad, tac = update_tx_matrix(tx)
    pa, tc, clerk = update_fl_matrix(fl)
    print(f"tx_county_coverage_matrix.csv    CAD {cad}, TAC {tac}")
    print(f"fl_county_coverage_matrix.csv    PA {pa}, TC {tc}, Clerk/VAB {clerk}")

    rights = build_rights_matrix(fl, tx)
    write_csv(DATA / "source_rights_matrix.csv", rights)
    print(f"source_rights_matrix.csv         {len(rights)} rows")

    summary_path = DATA / "county_coverage_matrix_summary.json"
    prior = json.loads(summary_path.read_text(encoding="utf-8"))
    summary = build_summary(fl, tx, prior)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(f"county_coverage_matrix_summary.json  rewritten, {len(summary['_history'])} prior baseline(s) preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
