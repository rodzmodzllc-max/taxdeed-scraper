"""Louisiana - adjudicated property, starting with East Baton Rouge Parish's
open-data dataset (source adapter, 2026-09-30).

THE SOURCE. Evidence grade: SEARCH INDEX - dataset titles, URLs, the
dataset's own description and its COLUMN NAMES as a web search indexed
them on 2026-09-30 (`EBR_EVIDENCE`). Nothing has been fetched from this
repository (data.brla.gov is egress-blocked from the sandbox and from the
assistant's fetch tool), so the exact CSV header spelling, the value
formats (the geolocation shape in particular), the refresh cadence and
the terms are UNVERIFIED; fixtures are SYNTHETIC.

  Established from the indexed text:
    * "a list of properties that have been adjudicated due to delinquent
      property taxes"; "if no one buys the property at the tax sale, the
      property will then be adjudicated to the Parish of East Baton Rouge
      in compliance with the laws of the State of Louisiana".
                                              -> inventory type ADJUDICATED_PROPERTY, publisher = the Parish
    * Dataset id a4h4-zi7e on data.brla.gov ('Adjudicated Property'), with
      CSV / JSON / XML / RDF downloads; the indexed CSV endpoint is
      /api/views/a4h4-zi7e/rows.csv?accessType=DOWNLOAD.
    * Indexed column list: TAX YEAR, PROPERTY NUMBER, TAXPAYER NAME,
      TAXPAYER ADDRESS, TAXPAYER CITY STATE ZIP, PHYSICAL ADDRESS,
      SUBDIVISION NAME, BLOCK/SQUARE NO, LOT NO, WARD, LEGAL DESCRIPTION,
      FAIR MARKET VALUE, TOTAL ASSESSED VALUE, COUNCIL DISTRICT, ZIP CODE,
      GEOLOCATION.                             -> the field map below
    * No price and no purchase link are among the columns.
                                              -> amount NOT_PUBLISHED; no purchase URL
  NOT established: header spelling (case / punctuation - matched after
  normalization), the geolocation format, whether the dataset is the
  CURRENT inventory or a yearly snapshot ("2023 Tax Roll and Adjudicated
  Property Datasets" per a news item - the TAX YEAR column is kept per
  row), purchase process (a vendor is reported in the audit; not
  verified, not implemented), terms of use.

WHAT THIS MODULE DOES: `EBR_SOURCE` (not enabled), `parse_csv()` (the
CSV with the indexed headers -> records: PROPERTY NUMBER as identity and
parcel, physical address, legal description, taxpayer name as the name on
the roll, assessed / market value, tax year, geolocation when it parses in
one of two deterministic shapes), `classify_outcome()`, a gated
`harvest()` (one CSV download) with an injected transport.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ...governance import states
from ...governance.states import PublishingUnit
from ..model import AmountKind, InventoryType, OtcRecord, SourceAuthority
from . import common
from .common import CountyOutcome, Evidence, GateDecision, HarvestResult

__all__ = ["EBR_EVIDENCE", "EBR_SOURCE", "INDEXED_COLUMNS", "LouisianaSourceConfig", "can_run", "classify_outcome",
           "harvest", "parse_csv", "parse_geolocation", "requirement_evidence"]

STATE = "LA"
STATUS_FILE_NAME = "harvest_louisiana_status.json"
HARVEST_FILE_NAME = "harvest_louisiana.json"
EVIDENCE_DATE = "2026-09-30"
EBR_HOST = "data.brla.gov"
EBR_DATASET_ID = "a4h4-zi7e"
EBR_DATASET_URL = "https://data.brla.gov/Housing-and-Development/Adjudicated-Property/a4h4-zi7e"
EBR_CSV_URL = "https://data.brla.gov/api/views/a4h4-zi7e/rows.csv?accessType=DOWNLOAD"
EBR_MAP_URL = "https://data.brla.gov/Housing-and-Development/Adjudicated-Property-Map/c7mi-6t2x"
EBR_GIS_URL = "https://gisdata.brla.gov/datasets/adjudicated-property"
PARISH = "East Baton Rouge"

INDEXED_COLUMNS = ("TAX YEAR", "PROPERTY NUMBER", "TAXPAYER NAME", "TAXPAYER ADDRESS", "TAXPAYER CITY STATE ZIP", "PHYSICAL ADDRESS",
                   "SUBDIVISION NAME", "BLOCK/SQUARE NO", "LOT NO", "WARD", "LEGAL DESCRIPTION", "FAIR MARKET VALUE",
                   "TOTAL ASSESSED VALUE", "COUNCIL DISTRICT", "ZIP CODE", "GEOLOCATION")

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
    Evidence("audit_note", "AUDIT_NOTE", "2026-09-29", "",
             "50-state audit group 4: 'LA=A (sec B): adjudicated property (parish/municipal); EBR Open Data BR dataset a4h4-zi7e + GIS; "
             "... CivicSource vendor (EBR >5yr, $0+costs); 9/64 identified'. The vendor purchase process is NOT verified and NOT implemented."),
)


def requirement_evidence() -> dict[str, str]:
    return {
        "source_of_record_identified": "search index names the Parish's open-data dataset and its CSV endpoint; not read directly",
        "live_source_verified": "nothing fetched from this repository (egress blocked)",
        "publishing_unit_coverage_established": "one parish (East Baton Rouge); 63 others not covered",
        "identifier_format_established": "PROPERTY NUMBER column named in the index; no value observed",
        "inventory_semantics_established": "'adjudicated to the Parish' per the description; whether the dataset is current inventory or a yearly snapshot not established",
        "purchase_path_established": "no purchase column; the audit reports a vendor process, unverified",
        "amount_semantics_established": "no price column in the indexed list -> NOT_PUBLISHED (assessed / market value are tax-roll figures, not prices)",
        "parser_fixture_validated": "parser exercised on SYNTHETIC fixtures only",
        "governance_approved": "terms of use not reviewed; registry governance_status TERMS_NOT_VERIFIED",
        "production_registry_authorized": "no decision taken",
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
    inventory_type: InventoryType = InventoryType.ADJUDICATED_PROPERTY
    source_authority: SourceAuthority = SourceAuthority.GOVERNMENT_DIRECT
    source_terminology: str = ""
    live_verified: bool = False
    identifier_format_established: bool = False
    parser_fixture_validated: bool = False
    enabled: bool = False
    evidence: str = ""

    def __post_init__(self) -> None:
        if self.publishing_unit not in (PublishingUnit.PARISH.value, PublishingUnit.MUNICIPALITY.value):
            raise ValueError(f"Louisiana publishes by PARISH or MUNICIPALITY, not {self.publishing_unit!r}")
        for name in ("list_url", "document_url"):
            if not getattr(self, name).startswith("https://"):
                raise ValueError(f"{name} must be https")
        if not self.county.strip() or not self.publishing_unit_name.strip():
            raise ValueError("county and publishing_unit_name are required")
        if "PROPERTY NUMBER" not in self.required_columns:
            raise ValueError("the identity column must be required")
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


def parse_csv(cfg: LouisianaSourceConfig, text: str, *, retrieved_at: datetime) -> tuple[list[OtcRecord], dict]:
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
    outcome = {"header_table_found": False, "data_rows": 0, "empty_marker": False, "rejected_identifier": 0, "missing_columns": [],
               "unmapped_columns": [], "geolocation_parsed": 0}
    if not rows:
        return [], outcome
    header = [_norm(c) for c in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    missing = [c for c in cfg.required_columns if _norm(c) not in idx]
    outcome["missing_columns"] = missing
    outcome["unmapped_columns"] = sorted(rows[0][i] for i, h in enumerate(header) if h not in {_norm(c) for c in INDEXED_COLUMNS})
    if missing:
        return [], outcome
    outcome["header_table_found"] = True
    body = rows[1:]
    outcome["data_rows"] = len(body)

    def cell(r, name):
        i = idx.get(_norm(name))
        return r[i] if i is not None and i < len(r) else None

    out: list[OtcRecord] = []
    for r in body:
        ident = _text(cell(r, "PROPERTY NUMBER"))
        if not ident or not _HAS_DIGIT.search(ident) or len(ident) > 40:
            outcome["rejected_identifier"] += 1
            continue
        geo = parse_geolocation(cell(r, "GEOLOCATION"))
        if geo:
            outcome["geolocation_parsed"] += 1
        assessed, market = _num(cell(r, "TOTAL ASSESSED VALUE")), _num(cell(r, "FAIR MARKET VALUE"))
        prov = {
            "adapter": "louisiana",
            "publishing_unit": cfg.publishing_unit,
            "publishing_unit_name": cfg.publishing_unit_name,
            "source_terminology": cfg.source_terminology or None,
            "identifier": "PROPERTY NUMBER as published by the Parish's dataset; no normalization (format not established)",
            "parcel": "PROPERTY NUMBER (the assessor's property number is the parcel identity in this dataset)",
            "owner_name": "TAXPAYER NAME - the name on the tax roll for TAX YEAR, as published; not asserted to be the current owner",
            "assessed": "TOTAL ASSESSED VALUE column (tax roll)" if assessed is not None else "not published on the row",
            "market": "FAIR MARKET VALUE column (tax roll)" if market is not None else "not published on the row",
            "coordinates": "GEOLOCATION column, parsed from its published shape" if geo else "GEOLOCATION absent or in an unparsed shape",
            "inventory_type": f"configuration: {cfg.inventory_type.value} ('adjudicated to the Parish' per the dataset description)",
            "amount": "NOT_PUBLISHED: the dataset carries no price; assessed / market value are tax-roll figures, not prices",
            "purchase_url": "no online path published in the dataset; the Parish's purchase process is not verified",
            "list_as_of": "not stated per row; TAX YEAR is the roll year, not a list date",
        }
        out.append(OtcRecord(
            state=STATE, county=cfg.county, case_no=ident, source_id=cfg.source_id, source_authority=cfg.source_authority,
            inventory_type=cfg.inventory_type, retrieved_at=retrieved_at, parcel=ident,
            address=_text(cell(r, "PHYSICAL ADDRESS")), legal_desc=_text(cell(r, "LEGAL DESCRIPTION")),
            owner_name=_text(cell(r, "TAXPAYER NAME")), assessed=assessed, market=market, tax_year=_text(cell(r, "TAX YEAR")),
            latitude=geo[0] if geo else None, longitude=geo[1] if geo else None,
            amount=None, amount_kind=AmountKind.NOT_PUBLISHED, list_url=cfg.list_url, document_url=cfg.document_url,
            purchase_url=None, purchase_url_kind=None, provenance=prov,
        ))
    return out, outcome


def classify_outcome(cfg: LouisianaSourceConfig, records: list[OtcRecord], outcome: dict, *, url: str | None = None) -> CountyOutcome:
    if outcome.get("missing_columns"):
        return CountyOutcome(county=cfg.county, status="INCOMPLETE", category="PARSE_FORMAT_CHANGE", row_count=0, url=url, report=outcome,
                             reason="required columns missing: " + ", ".join(outcome["missing_columns"]))
    return common.classify(parser_fixture_validated=cfg.parser_fixture_validated, county=cfg.county, records=records,
                           header_found=bool(outcome.get("header_table_found")), data_rows=int(outcome.get("data_rows") or 0),
                           empty_marker=False, url=url, report=outcome, unmapped=tuple(outcome.get("unmapped_columns") or ()))


def harvest(cfg: LouisianaSourceConfig, fetch_text: Callable[[str], str], *, retrieved_at: datetime) -> HarvestResult:
    """One CSV download, REFUSED unless can_run() allows it. Transport injected."""
    decision = can_run(cfg)
    if not decision.allowed:
        raise RuntimeError(f"Louisiana source {cfg.source_id} may not run: {decision.reason}")
    result = HarvestResult(units_offered=1)
    try:
        text = fetch_text(cfg.document_url)
        result.requests += 1
        recs, outcome = parse_csv(cfg, text, retrieved_at=retrieved_at)
    except Exception as exc:  # noqa: BLE001
        result.outcomes.append(CountyOutcome(county=cfg.county, status="FAILED", category=common.error_category(exc),
                                             reason=type(exc).__name__, url=cfg.document_url))
        return result
    result.records.extend(recs)
    result.outcomes.append(classify_outcome(cfg, recs, outcome, url=cfg.document_url))
    return result


EBR_SOURCE = LouisianaSourceConfig(
    source_id="la_ebr_adjudicated",
    publishing_unit=PublishingUnit.PARISH.value,
    publishing_unit_name="East Baton Rouge Parish (City of Baton Rouge / Parish of East Baton Rouge open data)",
    county=PARISH,
    list_url=EBR_DATASET_URL,
    document_url=EBR_CSV_URL,
    required_columns=("PROPERTY NUMBER", "PHYSICAL ADDRESS", "LEGAL DESCRIPTION", "TAX YEAR"),
    source_terminology="adjudicated property; adjudicated to the Parish of East Baton Rouge; property number; tax year",
    evidence="harvesters/otc/adapters/louisiana.py EBR_EVIDENCE (search index, 2026-09-30); docs/arkansas-louisiana-onboarding.md",
)
