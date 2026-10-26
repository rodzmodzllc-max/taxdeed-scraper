"""Louisiana - adjudicated property, starting with East Baton Rouge Parish's
open-data dataset (source adapter, 2026-09-30).

THE SOURCE. Evidence grade: LIVE READ (2026-09-30), on top of the earlier
search-index ledger (`EBR_EVIDENCE`). The manual evidence job
(scripts/capture_state_sources.py; GitHub Actions runs 36752875012 and
36753767965) read the dataset page, its metadata JSON and its CSV:

    * metadata: licenseId PUBLIC_DOMAIN, provenance "official", attribution
      "East Baton Rouge Parish Assessor's Office", custom field "Update
      Frequency: Annually", rowsUpdatedAt 2024-02-27 (1709060068), and the
      description "... If no one buys the property at the tax sale, the
      property will then be adjudicated to the Parish of East Baton Rouge in
      compliance with the laws of the State of Louisiana. The records in this
      dataset reflect the most current adjudicated property listing."
                                              -> inventory type ADJUDICATED_PROPERTY, publisher = the Parish
    * CSV header: exactly the 16 INDEXED_COLUMNS, in that order.
    * PROPERTY NUMBER values have the shape 999-9999-9 (13,942 of the first
      13,948 rows; 999-99999-9 and 9999999-9 three times each). The CSV
      carries one row per property number PER TAX YEAR (6 distinct tax
      years, 5,694 distinct property numbers in the first 3 MB).
                                              -> identity = PROPERTY NUMBER, the latest TAX YEAR row kept
    * No price and no purchase column.        -> amount NOT_PUBLISHED; no purchase URL

THE LIST IS DATED. Publication was approved by the owner on 2026-09-30 ONLY
as "adjudicated inventory as of" the dataset's own last-update date: every
record carries `list_as_of` = the metadata's own rowsUpdatedAt (read on every
run, never the retrieval date), and the frontend never calls a Louisiana row
"available now". A run whose metadata no longer says PUBLIC_DOMAIN refuses to
publish anything (the approval was for that licence).

SWITCHED 2026-10-26 (owner decision, "Yes close 6,643"): production reads the
Parish's NEWER "Adjudicated Parcel" dataset shrr-fsqq (rows updated
2026-05-06, STATUS 'AJ' only - `EBR_PARCEL_SOURCE`, aliased as `EBR_SOURCE`).
The older a4h4-zi7e "Adjudicated Property" config (rows updated 2024-02-27)
is kept, disabled, as `EBR_LEGACY_SOURCE`. Same source_id and the same
identity: the assessor's number as published (old PROPERTY NUMBER = new
ASSESSMENT NO., both 999-9999-9), so the 3,691 numbers on both lists keep
their rows and the next COMPLETE read closes the 6,643 that are not on it.

WHAT THIS MODULE DOES: `EBR_SOURCE` (production), `parse_csv()` (the CSV
with the configured headers -> records: the assessor's number as identity
and parcel, physical address, legal description, the name on the row,
assessed / market value, tax year and geolocation where the dataset carries
them), `classify_outcome()`, a gated `harvest()` (metadata + one CSV
download) with an injected transport.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
import json
from datetime import date, datetime, timezone
from typing import Callable

from ...governance import states
from ...governance.states import PublishingUnit
from ..model import AmountKind, InventoryType, OtcRecord, SourceAuthority
from . import common
from .common import CountyOutcome, Evidence, GateDecision, HarvestResult

__all__ = ["EBR_EVIDENCE", "EBR_LEGACY_SOURCE", "EBR_PARCEL_COLUMNS", "EBR_PARCEL_EVIDENCE", "EBR_PARCEL_SOURCE", "EBR_SOURCE", "INDEXED_COLUMNS",
           "ColumnLabels", "LouisianaSourceConfig", "can_run", "classify_outcome", "harvest", "parse_csv", "parse_geolocation",
           "parse_metadata", "requirement_evidence"]

STATE = "LA"
STATUS_FILE_NAME = "harvest_louisiana_status.json"
HARVEST_FILE_NAME = "harvest_louisiana.json"
EVIDENCE_DATE = "2026-09-30"
EBR_HOST = "data.brla.gov"
EBR_DATASET_ID = "a4h4-zi7e"
EBR_DATASET_URL = "https://data.brla.gov/Housing-and-Development/Adjudicated-Property/a4h4-zi7e"
EBR_CSV_URL = "https://data.brla.gov/api/views/a4h4-zi7e/rows.csv?accessType=DOWNLOAD"
EBR_METADATA_URL = "https://data.brla.gov/api/views/a4h4-zi7e.json"
APPROVED_LICENSE_ID = "PUBLIC_DOMAIN"   # the licence the owner's publication decision was taken on
EBR_MAP_URL = "https://data.brla.gov/Housing-and-Development/Adjudicated-Property-Map/c7mi-6t2x"
EBR_GIS_URL = "https://gisdata.brla.gov/datasets/adjudicated-property"
PARISH = "East Baton Rouge"

INDEXED_COLUMNS = ("TAX YEAR", "PROPERTY NUMBER", "TAXPAYER NAME", "TAXPAYER ADDRESS", "TAXPAYER CITY STATE ZIP", "PHYSICAL ADDRESS",
                   "SUBDIVISION NAME", "BLOCK/SQUARE NO", "LOT NO", "WARD", "LEGAL DESCRIPTION", "FAIR MARKET VALUE",
                   "TOTAL ASSESSED VALUE", "COUNCIL DISTRICT", "ZIP CODE", "GEOLOCATION")

# The Parish's NEWER adjudicated list (read live 2026-10-25, docs/la-tx-acquisition-paths.md):
# Open Data BR "Adjudicated Parcel" (shrr-fsqq) - attribution "East Baton Rouge
# Parish Assessor", provenance official, licenseId PUBLIC_DOMAIN, Update Frequency
# "Annually", rowsUpdatedAt 1778037958 (2026-05-06), 4,527 rows, every STATUS 'AJ'
# ("Status of the parcel (adjudicated)"). The Parish Attorney's Adjudicated
# Property page links its ArcGIS twin as "Adjudicated Property Listing (GIS)".
EBR_PARCEL_DATASET_ID = "shrr-fsqq"
EBR_PARCEL_DATASET_URL = "https://data.brla.gov/d/shrr-fsqq"
EBR_PARCEL_CSV_URL = "https://data.brla.gov/api/views/shrr-fsqq/rows.csv?accessType=DOWNLOAD"
EBR_PARCEL_METADATA_URL = "https://data.brla.gov/api/views/shrr-fsqq.json"
EBR_PARCEL_HEADER = ("ASSESSMENT NO.", "OWNER NAME", "OWNER ADDRESS", "OWNER CITY STATE ZIP", "PHYSICAL ADDRESS", "SUBDIVISION",
                     "WARD SECTION", "LOT", "BLOCK", "LEGAL DESCRIPTION", "FLOOD ZONE", "SALE YEAR", "STATUS",
                     "HOMESTEAD EXEMPTION SUM", "LOT VALUE SUM", "LAND VALUE SUM", "IMPROVEMENT VALUE SUM", "FAIR MARKET VALUE",
                     "ASSESSED VALUE", "GEOMETRY", "PRONO")

EBR_EVIDENCE: tuple[Evidence, ...] = (
    Evidence("dataset", "SEARCH_INDEX", EVIDENCE_DATE, EBR_DATASET_URL,
             "Title 'Adjudicated Property - Open Data BR'. Description: 'a list of properties that have been adjudicated due to "
             "delinquent property taxes'; 'if no one buys the property at the tax sale, the property will then be adjudicated to the "
             "Parish of East Baton Rouge in compliance with the laws of the State of Louisiana'."),
    Evidence("columns", "SEARCH_INDEX", EVIDENCE_DATE, EBR_DATASET_URL + "/data",
             "Indexed column list: " + ", ".join(INDEXED_COLUMNS) + "."),
    Evidence("csv", "SEARCH_INDEX", EVIDENCE_DATE, EBR_CSV_URL, "Indexed CSV download endpoint for dataset a4h4-zi7e (also JSON / XML / RDF)."),
    Evidence("map", "SEARCH_INDEX", EVIDENCE_DATE, EBR_MAP_URL, "Title 'Adjudicated Property Map | Open Data BR' (interactive map of the same parcels)."),
    Evidence("gis", "SEARCH_INDEX", EVIDENCE_DATE, EBR_GIS_URL, "Title 'Adjudicated Property | EBRGIS Open Data'; 'Adjudicated Parcel' polygons 'last updated on September 07, 2026'."),
    Evidence("live_metadata", "LIVE_READ", EVIDENCE_DATE, EBR_METADATA_URL,
             "licenseId PUBLIC_DOMAIN; provenance official; attribution 'East Baton Rouge Parish Assessor's Office'; Update Frequency "
             "'Annually'; rowsUpdatedAt 1709060068 (2024-02-27); 'The records in this dataset reflect the most current adjudicated "
             "property listing.' (GitHub Actions run 36752875012)"),
    Evidence("live_csv", "LIVE_READ", EVIDENCE_DATE, EBR_CSV_URL,
             "Header = the 16 indexed columns; PROPERTY NUMBER shape 999-9999-9 (13,942 / 13,948), 6 distinct TAX YEAR values, "
             "5,694 distinct property numbers in the first 3 MB; Last-Modified Tue, 27 Feb 2024 (run 36752875012)"),
    Evidence("audit_note", "AUDIT_NOTE", "2026-09-29", "",
             "50-state audit group 4: 'LA=A (sec B): adjudicated property (parish/municipal); EBR Open Data BR dataset a4h4-zi7e + GIS; "
             "... CivicSource vendor (EBR >5yr, $0+costs); 9/64 identified'. The vendor purchase process is NOT verified and NOT implemented."),
)


EBR_PARCEL_EVIDENCE: tuple[Evidence, ...] = (
    Evidence("parcel_metadata", "LIVE_READ", "2026-10-25", EBR_PARCEL_METADATA_URL,
             "name 'Adjudicated Parcel'; licenseId PUBLIC_DOMAIN; provenance official; attribution 'East Baton Rouge Parish "
             "Assessor'; Update Frequency 'Annually'; rowsUpdatedAt 1778037958 (2026-05-06); description 'Polygon geometry with "
             "attributes displaying adjudicated tax parcels in East Baton Rouge Parish'; STATUS described as 'Status of the parcel "
             "(adjudicated)'."),
    Evidence("parcel_csv", "LIVE_READ", "2026-10-25", EBR_PARCEL_CSV_URL,
             "Header = EBR_PARCEL_HEADER (21 columns); 4,527 rows, STATUS 'AJ' on every row; ASSESSMENT NO. shape 999-9999-9 "
             "(4,524 / 4,527); 4,520 distinct assessment numbers; GEOMETRY is a MULTIPOLYGON (no point); Last-Modified 06 May 2026. "
             "Of the 10,334 property numbers in a4h4-zi7e, 3,691 are on this list and 6,643 are not."),
    Evidence("parcel_catalog", "LIVE_READ", "2026-10-25", "https://data.brla.gov/api/catalog/v1?q=adjudicated",
             "Open Data BR catalog: a4h4-zi7e data updated 2024-02-27; shrr-fsqq 'Adjudicated Parcel' data updated 2026-05-06 - "
             "the newer of the Parish's two adjudicated lists."),
)


@dataclass(frozen=True)
class ColumnLabels:
    """The published header label of each field one dataset carries
    (matched after normalization). Blank = the dataset has no such column."""
    identity: str = "PROPERTY NUMBER"
    address: str = "PHYSICAL ADDRESS"
    legal: str = "LEGAL DESCRIPTION"
    owner: str = "TAXPAYER NAME"
    assessed: str = "TOTAL ASSESSED VALUE"
    market: str = "FAIR MARKET VALUE"
    tax_year: str = "TAX YEAR"
    geolocation: str = "GEOLOCATION"
    status: str = ""                         # the source's own status column, when it publishes one
    known: tuple[str, ...] = INDEXED_COLUMNS  # every header the dataset is known to carry (others are reported unmapped)


EBR_PARCEL_COLUMNS = ColumnLabels(identity="ASSESSMENT NO.", owner="OWNER NAME", assessed="ASSESSED VALUE", tax_year="",
                                  geolocation="", status="STATUS", known=EBR_PARCEL_HEADER)


def requirement_evidence() -> dict[str, str]:
    return {
        "source_of_record_identified": "the Parish's open-data dataset shrr-fsqq 'Adjudicated Parcel' (attribution: East Baton Rouge "
                                       "Parish Assessor), read live 2026-10-25; it replaced a4h4-zi7e (read live 2026-09-30) on 2026-10-26",
        "live_source_verified": "metadata JSON and CSV read live 2026-10-25 (EBR_PARCEL_EVIDENCE); a4h4-zi7e read by the manual "
                                "evidence job 2026-09-30 (runs 36752875012, 36753767965)",
        "publishing_unit_coverage_established": "one parish (East Baton Rouge); the other 63 are not covered",
        "identifier_format_established": "ASSESSMENT NO., shape 999-9999-9 (4,524 / 4,527) - the same assessor's number a4h4-zi7e "
                                         "published as PROPERTY NUMBER, in the same shape",
        "inventory_semantics_established": "STATUS 'AJ' ('Status of the parcel (adjudicated)') - a DATED list (rows updated "
                                           "2026-05-06; the earlier a4h4-zi7e list was dated 2024-02-27)",
        "purchase_path_established": "none published in the dataset (no purchase column, no link) - shown as not published",
        "amount_semantics_established": "no price column -> NOT_PUBLISHED (assessed / market value are tax-roll figures, not prices)",
        "parser_fixture_validated": "tests/python/fixtures/louisiana/ carries the LIVE headers verbatim with synthetic values in the live shapes",
        "governance_approved": "licence PUBLIC_DOMAIN (dataset metadata); owner publication decision 2026-09-30, dated list only; "
                               "owner switch to shrr-fsqq 2026-10-26",
        "production_registry_authorized": "owner decisions 2026-09-30 (docs/state-expansion.md) and 2026-10-26 "
                                          "(docs/la-tx-acquisition-paths.md)",
    }


@dataclass(frozen=True)
class LouisianaSourceConfig:
    source_id: str
    publishing_unit: str                     # PARISH or MUNICIPALITY
    publishing_unit_name: str                # "East Baton Rouge Parish"
    county: str                              # the parish / municipality name the properties row carries
    list_url: str
    document_url: str                        # the CSV
    required_columns: tuple[str, ...]        # headers the CSV must carry (normalized match) - else PARSE_FORMAT_CHANGE
    metadata_url: str | None = None          # the dataset's own metadata JSON (licence, rows-updated date)
    inventory_type: InventoryType = InventoryType.ADJUDICATED_PROPERTY
    source_authority: SourceAuthority = SourceAuthority.GOVERNMENT_DIRECT
    source_terminology: str = ""
    live_verified: bool = False
    identifier_format_established: bool = False
    parser_fixture_validated: bool = False
    enabled: bool = False
    evidence: str = ""
    columns: ColumnLabels = ColumnLabels()
    status_include: tuple[str, ...] = ()     # with columns.status: only rows whose status is one of these are read

    def __post_init__(self) -> None:
        if self.publishing_unit not in (PublishingUnit.PARISH.value, PublishingUnit.MUNICIPALITY.value):
            raise ValueError(f"Louisiana publishes by PARISH or MUNICIPALITY, not {self.publishing_unit!r}")
        for name in ("list_url", "document_url"):
            if not getattr(self, name).startswith("https://"):
                raise ValueError(f"{name} must be https")
        if not self.county.strip() or not self.publishing_unit_name.strip():
            raise ValueError("county and publishing_unit_name are required")
        if self.columns.identity not in self.required_columns:
            raise ValueError("the identity column must be required")
        if self.columns.status and (not self.status_include or self.columns.status not in self.required_columns):
            raise ValueError("a status column must be required and name the statuses it reads")
        if self.enabled and not (self.live_verified and self.identifier_format_established and self.parser_fixture_validated):
            raise ValueError("a source cannot be enabled before it is live-verified, its identifier format established "
                             "and its parser fixture validated")


def can_run(cfg: LouisianaSourceConfig) -> GateDecision:
    return common.can_run(STATE, enabled=cfg.enabled, live_verified=cfg.live_verified,
                          identifier_format_established=cfg.identifier_format_established,
                          parser_fixture_validated=cfg.parser_fixture_validated, list_url=cfg.list_url)


def _norm(label: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (label or "").strip().lower())).strip()


_HAS_DIGIT = re.compile(r"\d")
_POINT = re.compile(r"^POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)$", re.I)
_PAIR = re.compile(r"^\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?$")


def parse_geolocation(value) -> tuple[float, float] | None:
    """(latitude, longitude) from the two shapes a Socrata location column
    is known to take - WKT 'POINT (lon lat)' or '(lat, lon)' - or None.
    Anything else (an address string, a JSON blob) is left alone."""
    if value is None:
        return None
    text = str(value).strip()
    m = _POINT.match(text)
    if m:
        lon, lat = float(m.group(1)), float(m.group(2))
    else:
        m = _PAIR.match(text)
        if not m:
            return None
        lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _num(value) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.]", "", str(value))
    if not re.match(r"^\d+(\.\d+)?$", cleaned):
        return None
    return float(cleaned)


def _text(value) -> str | None:
    t = re.sub(r"\s+", " ", str(value or "")).strip()
    return t or None


def parse_metadata(text: str) -> dict:
    """The dataset metadata JSON -> {license_id, rows_updated_at (aware UTC
    datetime or None), list_as_of (its date), update_frequency}. Only the
    Parish's own fields; nothing is inferred."""
    data = json.loads(text)
    ts = data.get("rowsUpdatedAt")
    when = datetime.fromtimestamp(int(ts), tz=timezone.utc) if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.isdigit()) else None
    custom = ((data.get("metadata") or {}).get("custom_fields") or {}).get("Dataset Information") or {}
    return {"license_id": data.get("licenseId"), "rows_updated_at": when, "list_as_of": when.date() if when else None,
            "update_frequency": custom.get("Update Frequency")}


def _year(value) -> int:
    t = str(value or "").strip()
    return int(t) if t.isdigit() else -1


def parse_csv(cfg: LouisianaSourceConfig, text: str, *, retrieved_at: datetime, list_as_of: date | None = None,
              rows_updated_at: datetime | None = None) -> tuple[list[OtcRecord], dict]:
    """The dataset CSV -> (records, outcome). Headers are matched after
    normalization; every required column must be present or nothing is
    read (outcome header_table_found False, category PARSE_FORMAT_CHANGE
    via classify_outcome). Per row: PROPERTY NUMBER (identity and parcel,
    as published; digit-less or blank rows rejected), PHYSICAL ADDRESS,
    LEGAL DESCRIPTION, TAXPAYER NAME (the name on the tax roll for TAX
    YEAR), TOTAL ASSESSED VALUE / FAIR MARKET VALUE (tax-roll figures,
    never a price), TAX YEAR, GEOLOCATION when it parses. Amount is
    always None + NOT_PUBLISHED: no price column exists."""
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    cols = cfg.columns
    outcome = {"header_table_found": False, "data_rows": 0, "empty_marker": False, "rejected_identifier": 0, "missing_columns": [],
               "unmapped_columns": [], "geolocation_parsed": 0, "superseded_tax_year_rows": 0, "other_status_rows": 0,
               "not_on_latest_tax_year": 0}
    if not rows:
        return [], outcome
    header = [_norm(c) for c in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    missing = [c for c in cfg.required_columns if _norm(c) not in idx]
    outcome["missing_columns"] = missing
    outcome["unmapped_columns"] = sorted(rows[0][i] for i, h in enumerate(header) if h not in {_norm(c) for c in cols.known})
    if missing:
        return [], outcome
    outcome["header_table_found"] = True
    body = rows[1:]
    outcome["data_rows"] = len(body)

    def cell(r, name):
        if not name:
            return None
        i = idx.get(_norm(name))
        return r[i] if i is not None and i < len(r) else None

    include = {_norm(v) for v in cfg.status_include}
    out: list[OtcRecord] = []
    for r in body:
        if cols.status and _norm(cell(r, cols.status) or "") not in include:
            outcome["other_status_rows"] += 1
            continue
        ident = _text(cell(r, cols.identity))
        if not ident or not _HAS_DIGIT.search(ident) or len(ident) > 40:
            outcome["rejected_identifier"] += 1
            continue
        geo = parse_geolocation(cell(r, cols.geolocation))
        if geo:
            outcome["geolocation_parsed"] += 1
        assessed, market = _num(cell(r, cols.assessed)), _num(cell(r, cols.market))
        prov = {
            "adapter": "louisiana",
            "publishing_unit": cfg.publishing_unit,
            "publishing_unit_name": cfg.publishing_unit_name,
            "source_terminology": cfg.source_terminology or None,
            "identifier": f"{cols.identity} as published by the Parish's dataset; no normalization (format not established)",
            "parcel": f"{cols.identity} (the assessor's property number is the parcel identity in this dataset)",
            "owner_name": (f"{cols.owner} - the name on the tax roll for {cols.tax_year}" if cols.tax_year
                           else f"{cols.owner} - the name on the dataset's row") + ", as published; not asserted to be the current owner",
            "assessed": f"{cols.assessed} column (tax roll)" if assessed is not None else "not published on the row",
            "market": f"{cols.market} column (tax roll)" if market is not None else "not published on the row",
            "coordinates": (f"{cols.geolocation} column, parsed from its published shape" if geo
                            else f"{cols.geolocation} absent or in an unparsed shape" if cols.geolocation
                            else "no point column in this dataset (its geometry is a polygon)"),
            "inventory_type": f"configuration: {cfg.inventory_type.value} ('adjudicated to the Parish' per the dataset description)",
            "amount": "NOT_PUBLISHED: the dataset carries no price; assessed / market value are tax-roll figures, not prices",
            "purchase_url": "no online path published in the dataset; the Parish's purchase process is not verified",
            "list_as_of": ("dataset metadata rowsUpdatedAt - the Parish's own last-update date for every row; TAX YEAR is the roll year"
                           if list_as_of else "not stated; TAX YEAR is the roll year, not a list date"),
        }
        if cols.status:
            prov["status"] = f"{cols.status} column: {_text(cell(r, cols.status))} (the dataset's own adjudicated status)"
        out.append(OtcRecord(
            state=STATE, county=cfg.county, case_no=ident, source_id=cfg.source_id, source_authority=cfg.source_authority,
            inventory_type=cfg.inventory_type, retrieved_at=retrieved_at, parcel=ident,
            address=_text(cell(r, cols.address)), legal_desc=_text(cell(r, cols.legal)),
            owner_name=_text(cell(r, cols.owner)), assessed=assessed, market=market, tax_year=_text(cell(r, cols.tax_year)),
            latitude=geo[0] if geo else None, longitude=geo[1] if geo else None,
            amount=None, amount_kind=AmountKind.NOT_PUBLISHED, list_url=cfg.list_url, document_url=cfg.document_url,
            purchase_url=None, purchase_url_kind=None, provenance=prov,
            list_as_of=list_as_of, source_published_at=rows_updated_at,
        ))
    # One row per PROPERTY NUMBER per TAX YEAR in the dataset: keep the
    # latest tax year's row (deterministic: ties keep the first seen).
    latest: dict[str, OtcRecord] = {}
    for rec in out:
        cur = latest.get(rec.case_no)
        if cur is None or _year(rec.tax_year) > _year(cur.tax_year):
            latest[rec.case_no] = rec
    outcome["superseded_tax_year_rows"] = len(out) - len(latest)
    # Counts only, nothing dropped: property numbers whose newest row is older
    # than the dataset's newest TAX YEAR (not among the latest roll's
    # adjudicated rows). Reported so a dated list's staleness is measurable.
    newest = max((_year(r.tax_year) for r in latest.values()), default=-1)
    if newest > 0:
        outcome["not_on_latest_tax_year"] = sum(1 for r in latest.values() if 0 < _year(r.tax_year) < newest)
    return list(latest.values()), outcome


def classify_outcome(cfg: LouisianaSourceConfig, records: list[OtcRecord], outcome: dict, *, url: str | None = None) -> CountyOutcome:
    if outcome.get("missing_columns"):
        return CountyOutcome(county=cfg.county, status="INCOMPLETE", category="PARSE_FORMAT_CHANGE", row_count=0, url=url, report=outcome,
                             reason="required columns missing: " + ", ".join(outcome["missing_columns"]))
    return common.classify(parser_fixture_validated=cfg.parser_fixture_validated, county=cfg.county, records=records,
                           header_found=bool(outcome.get("header_table_found")), data_rows=int(outcome.get("data_rows") or 0),
                           empty_marker=False, url=url, report=outcome, unmapped=tuple(outcome.get("unmapped_columns") or ()))


def harvest(cfg: LouisianaSourceConfig, fetch_text: Callable[[str], str], *, retrieved_at: datetime) -> HarvestResult:
    """The dataset metadata, then one CSV download - REFUSED unless can_run()
    allows it. Transport injected. A metadata licence other than the one
    publication was approved on, or no rows-updated date (the list's date is
    what makes publication honest), reads nothing (FAILED)."""
    decision = can_run(cfg)
    if not decision.allowed:
        raise RuntimeError(f"Louisiana source {cfg.source_id} may not run: {decision.reason}")
    result = HarvestResult(units_offered=1)
    try:
        meta = parse_metadata(fetch_text(cfg.metadata_url)) if cfg.metadata_url else {}
        result.requests += 1 if cfg.metadata_url else 0
        if cfg.metadata_url and meta.get("license_id") != APPROVED_LICENSE_ID:
            result.outcomes.append(CountyOutcome(county=cfg.county, status="FAILED", category="UNKNOWN", url=cfg.metadata_url,
                                                 reason=f"dataset licence is {meta.get('license_id')!r}, not the approved {APPROVED_LICENSE_ID}"))
            return result
        if cfg.metadata_url and not meta.get("list_as_of"):
            result.outcomes.append(CountyOutcome(county=cfg.county, status="FAILED", category="PARSE_FORMAT_CHANGE", url=cfg.metadata_url,
                                                 reason="dataset metadata carries no rowsUpdatedAt - the list date cannot be stated"))
            return result
        text = fetch_text(cfg.document_url)
        result.requests += 1
        recs, outcome = parse_csv(cfg, text, retrieved_at=retrieved_at, list_as_of=meta.get("list_as_of"),
                                  rows_updated_at=meta.get("rows_updated_at"))
    except Exception as exc:  # noqa: BLE001
        result.outcomes.append(CountyOutcome(county=cfg.county, status="FAILED", category=common.error_category(exc),
                                             reason=type(exc).__name__, url=cfg.document_url))
        return result
    result.records.extend(recs)
    result.outcomes.append(classify_outcome(cfg, recs, outcome, url=cfg.document_url))
    return result


# The OLDER list (a4h4-zi7e, rows updated 2024-02-27): production from
# 2026-09-30 to 2026-10-26, kept DISABLED (never requested) for reference and
# for the parser's structural tests.
EBR_LEGACY_SOURCE = LouisianaSourceConfig(
    source_id="la_ebr_adjudicated",
    publishing_unit=PublishingUnit.PARISH.value,
    publishing_unit_name="East Baton Rouge Parish (City of Baton Rouge / Parish of East Baton Rouge open data)",
    county=PARISH,
    list_url=EBR_DATASET_URL,
    document_url=EBR_CSV_URL,
    required_columns=("PROPERTY NUMBER", "PHYSICAL ADDRESS", "LEGAL DESCRIPTION", "TAX YEAR"),
    source_terminology="adjudicated property; adjudicated to the Parish of East Baton Rouge; property number; tax year",
    metadata_url=EBR_METADATA_URL,
    live_verified=True, identifier_format_established=True, parser_fixture_validated=True, enabled=False,
    evidence="harvesters/otc/adapters/louisiana.py EBR_EVIDENCE (search index + LIVE READ, 2026-09-30); docs/state-expansion.md",
)


# The newer list - PRODUCTION since 2026-10-26 (owner decision: "Yes close
# 6,643"). It moves the list date from 2024-02-27 to 2026-05-06, and the next
# COMPLETE read closes the 6,643 property numbers that are not on it (the laft
# lifecycle closes absent rows of a COMPLETE read only). Same source_id: the
# same Parish, portal and licence, and the same identity (the assessor's
# number, as published).
EBR_PARCEL_SOURCE = LouisianaSourceConfig(
    source_id="la_ebr_adjudicated",
    publishing_unit=PublishingUnit.PARISH.value,
    publishing_unit_name="East Baton Rouge Parish (City of Baton Rouge / Parish of East Baton Rouge open data)",
    county=PARISH,
    list_url=EBR_PARCEL_DATASET_URL,
    document_url=EBR_PARCEL_CSV_URL,
    required_columns=("ASSESSMENT NO.", "PHYSICAL ADDRESS", "LEGAL DESCRIPTION", "STATUS"),
    source_terminology="adjudicated parcel; status AJ (adjudicated); assessment number",
    metadata_url=EBR_PARCEL_METADATA_URL,
    columns=EBR_PARCEL_COLUMNS,
    status_include=("AJ",),
    live_verified=True, identifier_format_established=True, parser_fixture_validated=True, enabled=True,
    evidence="harvesters/otc/adapters/louisiana.py EBR_PARCEL_EVIDENCE (LIVE READ 2026-10-25); docs/la-tx-acquisition-paths.md",
)

# The production source (scripts/harvest_state_inventory.py, the registry builder).
EBR_SOURCE = EBR_PARCEL_SOURCE
