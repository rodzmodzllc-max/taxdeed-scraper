"""ArcGIS REST adapter - Phase 39 Sections 5, 24, 46.

One reusable adapter for every unauthenticated public ArcGIS
FeatureServer/MapServer parcel layer. This is the single highest-leverage
adapter in the engine, because ArcGIS REST is the mechanism behind:

  - HCAD (Harris County, TX) - `_fetch_hcad()` in
    `scripts/enrich_property_details_tx.py`
  - TAD (Tarrant County, TX) - `_fetch_tad()` in the same file
  - BCAD (Bexar County, TX) - a real endpoint, fields not yet sampled
  - Florida's statewide FDOR Cadastral layer - the same mechanism, noted in
    `claude/parcel-enrichment-and-gis-plan.md`
  - most county GIS portals in both states

Section 47's rule applies exactly here: these counties do NOT need separate
parser implementations, they need separate CONFIGURATION. Adding Bexar is
a `CadLayerConfig` entry; it is not a new module and not a new parser.

**Live re-verification performed this phase (2026-09-16)**, through this
session's sanctioned, robots-respecting web-fetch path:

  - HCAD layer `.../HCAD/Parcels/MapServer/0` answers; layer name "HCAD
    Parcels", type Feature Layer; fields `HCAD_NUM`, `state_class`,
    `total_market_val`, `land_value`, `bld_value` all confirmed present.
  - A real single-parcel query (`HCAD_NUM='1011020000003'`) returned one
    feature whose attributes matched the sample recorded in
    `_fetch_hcad()`'s 2026-09-08 comment block **exactly**
    (`total_market_val` 199689.0, `land_value` 61382.0, `bld_value`
    138307.0, `Acreage` null, `land_sqft` 7697.0). This is the first time
    that function's query mechanics have been confirmed from this
    project's own tooling - its comment block previously said "NOT
    execution-tested from this project's own sandbox".
  - TAD layer `.../Tax/TCProperty/MapServer/0` answers; layer name
    "Tarrant County Parcel"; fields `ACCOUNT`, `TAXPIN`, `LAND_VALUE`,
    `IMPR_VALUE`, `TOTAL_VALU`, `APPRAISEDV`, `EXEMPTION_`, `LIVING_ARE`
    all confirmed present.

Normalization is NOT reimplemented here: this adapter calls the existing
`hcad_attributes_to_generic()` / `tad_attributes_to_generic()` /
`normalize_cad_response()` functions in
`scripts/enrich_property_details_tx.py`, per Section 24's "verify the
existing Harris/Tarrant functionality" and Section 9's preservation rule.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from ..adapter import AdapterConfig, SourceAdapter, deduplicate, utc_now_iso
from ..categories import DataCategory, SourceTier
from ..result import AcquisitionResult, AcquisitionStatus, RetrievalMetadata, build_result
from ..transport import SchemaError, TransportError

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _cad_normalizers():
    """Late import, same rationale as json_api._lgbs_helpers()."""
    from enrich_property_details_tx import (  # type: ignore
        hcad_attributes_to_generic,
        normalize_cad_response,
        tad_attributes_to_generic,
    )

    return hcad_attributes_to_generic, tad_attributes_to_generic, normalize_cad_response


# Florida's statewide normalizers live in `scripts/enrich_property_details.py`,
# which this module deliberately does NOT import: that script calls
# `sys.exit(1)` at module scope when `SUPABASE_URL`/`SUPABASE_SERVICE_KEY`
# are unset (line ~163), so importing it would terminate any process that
# merely touches this adapter - including the test suite. The two tiny pure
# helpers below reproduce that script's documented FDOR semantics exactly;
# `tests/python/test_phase39_acquisition_engine.py` asserts the sentinel
# rule against the script's own source text so the two cannot drift apart
# silently. Moving those helpers into an importable module is a clean,
# behavior-preserving refactor for a future phase - it was not done here
# because Section 10 forbids touching the working Florida pipeline for
# architectural reasons alone.
def _fdor_num(value):
    """FDOR uses 0 as the 'no data' sentinel for every numeric field (a real
    $0 just value / year built / square footage does not occur), so 0 and
    blanks both become None rather than a misleading 0. Verbatim semantics
    from `enrich_property_details.py::_num`."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def _fdor_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# Standard FL DOR county numbering: 67 counties, alphabetical, 11-77.
# Mirrors `enrich_property_details.py::COUNTY_CODES`; a test asserts the two
# agree county-for-county.
FDOR_COUNTY_CODES: dict[str, int] = {
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


@dataclass(frozen=True)
class CadLayerConfig:
    """Per-CAD configuration. Section 24's "create reusable configuration
    rather than copying code", made concrete.

    `attributes_to_generic` names WHICH existing adapter function maps this
    layer's attributes into the generic CAD shape - deliberately a name
    rather than a callable so this config stays a plain, serializable data
    record (the same discipline `registry.SourceRecord` uses).

    `fields_confirmed_live` records the date the field list was actually
    confirmed against the live layer, so a stale config is visible rather
    than assumed current.
    """

    cad_id: str
    cad_name: str
    state: str
    county: str | None  # None = statewide layer covering every county
    query_url: str
    id_field: str
    out_fields: tuple[str, ...]
    attributes_to_generic: str  # "hcad" | "tad" | "fdor" | "generic"
    county_field: str | None = None  # set when the layer supports a county-scoped query
    fields_confirmed_live: str | None = None
    notes: str = ""


HCAD_LAYER = CadLayerConfig(
    cad_id="tx_cad_harris_hcad",
    cad_name="Harris County Appraisal District (HCAD) public parcel layer",
    state="TX",
    county="Harris",
    query_url="https://www.gis.hctx.net/arcgis/rest/services/HCAD/Parcels/MapServer/0/query",
    id_field="HCAD_NUM",
    out_fields=(
        "HCAD_NUM",
        "state_class",
        "land_use",
        "total_market_val",
        "land_value",
        "bld_value",
        "impr_value",
        "acreage",
        "land_sqft",
        "legal_dscr_1",
        "owner_name_1",
    ),
    attributes_to_generic="hcad",
    fields_confirmed_live="2026-09-16",
    notes=(
        "Layer name 'HCAD Parcels'. Confirmed live 2026-09-16 including a real single-parcel query whose "
        "values matched the 2026-09-08 sample exactly. Known gaps (unchanged): no homestead/exemption flag "
        "and no building square footage in this layer; Acreage is free text ('1.8081 AC') and often null."
    ),
)

TAD_LAYER = CadLayerConfig(
    cad_id="tx_cad_tarrant_tad",
    cad_name="Tarrant Appraisal District (TAD) public parcel layer",
    state="TX",
    county="Tarrant",
    query_url="https://mapit.tarrantcounty.com/arcgis/rest/services/Tax/TCProperty/MapServer/0/query",
    id_field="ACCOUNT",
    out_fields=(
        "TAXPIN",
        "ACCOUNT",
        "OWNER_NAME",
        "SITUS_ADDR",
        "EXEMPTION_",
        "LEGAL_1",
        "LAND_VALUE",
        "IMPR_VALUE",
        "TOTAL_VALU",
        "APPRAISEDV",
        "LAND_ACRES",
        "LAND_SQFT",
        "LIVING_ARE",
        "YEAR_BUILT",
        "PARCELTYPE",
        "DESCR",
    ),
    attributes_to_generic="tad",
    fields_confirmed_live="2026-09-16",
    notes=(
        "Layer name 'Tarrant County Parcel'. Richer than HCAD's: carries EXEMPTION_ and LIVING_ARE, both "
        "confirmed absent from HCAD. PARCELTYPE/DESCR/EXEMPTION_ VALUES remain unsampled - the field "
        "existence is confirmed, the content vocabulary is not (unchanged from the pre-existing caveat)."
    ),
)

FDOR_LAYER = CadLayerConfig(
    cad_id="fl_fdor_statewide_cadastral",
    cad_name="Florida Statewide Cadastral (FDOR) ArcGIS FeatureServer",
    state="FL",
    county=None,  # statewide - all 67 counties from ONE layer
    query_url=(
        "https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/"
        "Florida_Statewide_Cadastral/FeatureServer/0/query"
    ),
    id_field="PARCEL_ID",
    out_fields=(
        "PARCEL_ID", "CO_NO", "ASMNT_YR",
        "PHY_ADDR1", "PHY_CITY", "PHY_ZIPCD",
        "DOR_UC",
        "JV", "AV_NSD", "LND_VAL", "JV_HMSTD",
        "ACT_YR_BLT", "TOT_LVG_AR", "NO_BULDNG", "LND_SQFOOT",
        "OWN_NAME", "S_LEGAL",
        "SALE_PRC1", "SALE_YR1",
    ),
    attributes_to_generic="fdor",
    county_field="CO_NO",
    fields_confirmed_live="2026-09-16",
    notes=(
        "Layer name 'FDOR Cadastral 2025', 124 fields, confirmed live 2026-09-16 including a real "
        "county-scoped query (CO_NO=11, Alachua) returning parcels with JV/AV_NSD/DOR_UC populated. "
        "This is THE statewide Florida mechanism: one layer covers all 67 counties (Section 46's "
        "statewide-over-per-county preference). Already in production use by "
        "scripts/enrich_property_details.py; this adapter reaches the same layer through the "
        "acquisition contract without modifying that script. JV is the county property appraiser's "
        "statutory just-value estimate and must never be presented as a live/AVM estimate."
    ),
)


# Registered ArcGIS layers. Adding a county or a state here is the whole job
# for any source that speaks ArcGIS REST - no new module, no new parser.
CAD_LAYERS: dict[str, CadLayerConfig] = {
    layer.cad_id: layer for layer in (HCAD_LAYER, TAD_LAYER, FDOR_LAYER)
}


class ArcGisAdapter(SourceAdapter):
    """Queries one ArcGIS REST layer for one or more parcel identifiers.

    Deliberately parcel-scoped rather than bulk-scoped: these layers are
    enrichment sources joined to properties this project already has, which
    is exactly how `enrich_property_details_tx.py` already uses them. A
    bulk-export adapter for the same layers would be a different adapter
    with different rate-limit characteristics, not a flag on this one.
    """

    def __init__(self, layer: CadLayerConfig, transport=None, *, source_id: str = "tx_hctax"):
        self.layer = layer
        config = AdapterConfig(
            source_id=source_id,
            state=layer.state,
            county=layer.county,
            base_url=layer.query_url,
            categories=(
                DataCategory.ASSESSMENT,
                DataCategory.MARKET_VALUE,
                DataCategory.PROPERTY_TYPE,
                DataCategory.ACREAGE,
                DataCategory.PARCEL_APN,
                DataCategory.PROPERTY_CHARACTERISTICS,
            ),
            tier=SourceTier.OFFICIAL_GOVERNMENT_API,
            retrieval_method="arcgis_rest_query",
            raw_storage_permitted=False,
            notes=layer.notes,
        )
        super().__init__(config, transport)

    def build_query_url(self, parcel_id: str) -> str:
        import urllib.parse

        params = {
            "where": f"{self.layer.id_field}='{parcel_id}'",
            "outFields": ",".join(self.layer.out_fields),
            "returnGeometry": "false",
            "f": "json",
        }
        return f"{self.layer.query_url}?{urllib.parse.urlencode(params)}"

    def build_county_query_url(self, county: str, *, result_record_count: int = 100, offset: int = 0) -> str:
        """County-scoped query, for a statewide layer that supports one
        (Section 46: one statewide source beats 67 per-county scrapers).
        Raises for a layer with no `county_field` rather than silently
        falling back to an unscoped query that would pull another county's
        parcels - Section 50's adversarial test 5 (county-specific state)."""
        import urllib.parse

        if not self.layer.county_field:
            raise ValueError(f"{self.layer.cad_id} has no county_field - county-scoped query is not supported")
        county_code = FDOR_COUNTY_CODES.get(county) if self.layer.attributes_to_generic == "fdor" else None
        if county_code is None:
            raise ValueError(f"{self.layer.cad_id}: no county code known for {county!r}")
        params = {
            "where": f"{self.layer.county_field}={county_code}",
            "outFields": ",".join(self.layer.out_fields),
            "returnGeometry": "false",
            "resultRecordCount": str(result_record_count),
            "resultOffset": str(offset),
            "f": "json",
        }
        return f"{self.layer.query_url}?{urllib.parse.urlencode(params)}"

    def acquire_county(
        self, county: str, *, limit: int = 100, offset: int = 0, purpose=None
    ) -> AcquisitionResult:
        """Acquire parcels for ONE county from a statewide layer. The
        Florida statewide mechanism's real entry point."""
        started_at = utc_now_iso()
        self._retrievals = []

        from ..policy import AcquisitionPurpose, check_acquisition_policy

        effective_purpose = purpose or AcquisitionPurpose.PRODUCTION_ACQUISITION
        decision = check_acquisition_policy(
            self.source_id,
            purpose=effective_purpose,
            state=self.config.state,
            county=county,
            use="INGEST",
        )
        if not decision.allowed:
            return build_result(
                source_id=self.source_id,
                jurisdiction=f"{self.config.state}/{county}",
                status=AcquisitionStatus.LEGAL_RESTRICTION,
                started_at=started_at,
                retrieval_method=self.config.retrieval_method,
                categories=tuple(c.value for c in self.categories),
                errors=(decision.reason,),
            )

        url = self.build_county_query_url(county, result_record_count=limit, offset=offset)
        page_started = utc_now_iso()
        try:
            response = self.transport.get(url)
            payload = response.json()
            attributes_list = self.extract_attributes(payload)
        except TransportError as exc:
            return build_result(
                source_id=self.source_id,
                jurisdiction=f"{self.config.state}/{county}",
                status=exc.status,
                started_at=started_at,
                retrieval_method=self.config.retrieval_method,
                categories=tuple(c.value for c in self.categories),
                errors=(f"{exc.error_code}: {exc}",),
            )

        records: list[dict] = []
        failed = 0
        warnings: list[str] = []
        for attrs in attributes_list:
            try:
                normalized = self.normalize(attrs, county=county)
            except Exception as exc:
                failed += 1
                warnings.append(f"normalization failed: {type(exc).__name__}: {exc}")
                continue
            if normalized is not None:
                records.append(normalized)

        self.record_retrieval(
            RetrievalMetadata(
                source_id=self.source_id,
                state=self.config.state,
                county=county,
                source_url=url,
                retrieval_method=self.config.retrieval_method,
                started_at=page_started,
                completed_at=utc_now_iso(),
                http_status=response.http_status,
                records_seen=len(attributes_list),
                records_acquired=len(records),
                records_failed=failed,
                content_type=response.content_type,
                content_hash_value=response.hash(),
            )
        )

        unique, duplicates = deduplicate(records)
        if not unique:
            status = AcquisitionStatus.NO_DATA
        elif failed:
            status = AcquisitionStatus.PARTIAL_SUCCESS
        else:
            status = AcquisitionStatus.SUCCESS

        return build_result(
            source_id=self.source_id,
            jurisdiction=f"{self.config.state}/{county}",
            status=status,
            started_at=started_at,
            records=unique,
            records_seen=len(attributes_list),
            records_failed=failed,
            records_skipped=duplicates,
            categories=tuple(c.value for c in self.categories),
            warnings=tuple(warnings),
            retrieval_method=self.config.retrieval_method,
            retrievals=tuple(self._retrievals),
            raw_storage_status=self._raw_storage_status(),
            checkpoint={"county": county, "offset": offset + len(attributes_list)} if attributes_list else None,
        )

    def extract_attributes(self, payload) -> list[dict]:
        if not isinstance(payload, dict):
            raise SchemaError(f"{self.layer.cad_id}: expected a JSON object, got {type(payload).__name__}")
        if "error" in payload:
            raise SchemaError(f"{self.layer.cad_id}: ArcGIS error response: {payload['error']}")
        features = payload.get("features")
        if features is None:
            raise SchemaError(f"{self.layer.cad_id}: response has no 'features' key (schema change?)")
        return [f.get("attributes", {}) for f in features if isinstance(f, dict)]

    def acquire_parcels(self, parcel_ids: list[str], *, purpose=None) -> AcquisitionResult:
        """The real entry point for this adapter - `acquire()` with no
        parcel list has nothing to query, and returns NOT_APPLICABLE rather
        than pretending to succeed."""
        self._parcel_ids = list(parcel_ids)
        kwargs = {"purpose": purpose} if purpose is not None else {}
        return self.acquire(**kwargs)

    def _acquire(self, *, started_at: str, limit: int | None, checkpoint: dict | None) -> AcquisitionResult:
        parcel_ids = list(getattr(self, "_parcel_ids", []) or [])
        if checkpoint and checkpoint.get("remaining_parcel_ids"):
            parcel_ids = list(checkpoint["remaining_parcel_ids"])
        if not parcel_ids:
            return build_result(
                source_id=self.source_id,
                jurisdiction=self.jurisdiction,
                status=AcquisitionStatus.NOT_APPLICABLE,
                started_at=started_at,
                retrieval_method=self.config.retrieval_method,
                categories=tuple(c.value for c in self.categories),
                warnings=("no parcel identifiers supplied - this adapter enriches known parcels, it does not enumerate them",),
                raw_storage_status=self._raw_storage_status(),
            )

        if limit is not None:
            parcel_ids = parcel_ids[:limit]

        records: list[dict] = []
        seen = 0
        failed = 0
        skipped = 0
        warnings: list[str] = []
        remaining = list(parcel_ids)

        for parcel_id in parcel_ids:
            url = self.build_query_url(parcel_id)
            page_started = utc_now_iso()
            response = self.transport.get(url)
            payload = response.json()
            attributes_list = self.extract_attributes(payload)
            seen += 1
            remaining.remove(parcel_id)

            acquired_here = 0
            if not attributes_list:
                # A parcel the layer does not carry is a legitimate miss,
                # not a failure - distinguishing these is Section 34's
                # missing-data classification in miniature.
                skipped += 1
            else:
                for attrs in attributes_list:
                    try:
                        normalized = self.normalize(attrs)
                    except Exception as exc:
                        failed += 1
                        warnings.append(f"{parcel_id}: normalization failed: {type(exc).__name__}: {exc}")
                        continue
                    if normalized is None:
                        skipped += 1
                        continue
                    records.append(normalized)
                    acquired_here += 1

            self.record_retrieval(
                RetrievalMetadata(
                    source_id=self.source_id,
                    state=self.config.state,
                    county=self.config.county,
                    source_url=url,
                    retrieval_method=self.config.retrieval_method,
                    started_at=page_started,
                    completed_at=utc_now_iso(),
                    http_status=response.http_status,
                    records_seen=len(attributes_list),
                    records_acquired=acquired_here,
                    content_type=response.content_type,
                    content_hash_value=response.hash(),
                    source_updated_at=response.source_updated_at,
                )
            )

        unique, duplicates = deduplicate(records)
        if duplicates:
            warnings.append(f"{duplicates} duplicate record(s) dropped by idempotency key")

        if not unique:
            status = AcquisitionStatus.NO_DATA
        elif failed:
            status = AcquisitionStatus.PARTIAL_SUCCESS
        else:
            status = AcquisitionStatus.SUCCESS

        return build_result(
            source_id=self.source_id,
            jurisdiction=self.jurisdiction,
            status=status,
            started_at=started_at,
            records=unique,
            records_seen=seen,
            records_failed=failed,
            records_skipped=skipped + duplicates,
            categories=tuple(c.value for c in self.categories),
            warnings=tuple(warnings),
            retrieval_method=self.config.retrieval_method,
            retrievals=tuple(self._retrievals),
            raw_storage_status=self._raw_storage_status(),
            checkpoint={"remaining_parcel_ids": remaining} if remaining else None,
        )

    def normalize(self, raw_record: dict, *, county: str | None = None) -> dict | None:
        parcel_id = raw_record.get(self.layer.id_field)

        if self.layer.attributes_to_generic == "fdor":
            record = self._normalize_fdor(raw_record, county=county)
        else:
            hcad_to_generic, tad_to_generic, normalize_cad = _cad_normalizers()
            if self.layer.attributes_to_generic == "hcad":
                generic = hcad_to_generic(raw_record)
            elif self.layer.attributes_to_generic == "tad":
                generic = tad_to_generic(raw_record)
            else:
                generic = dict(raw_record)
            record = {
                "state": self.layer.state,
                "county": county or self.layer.county,
                "parcel": parcel_id,
                "cad_id": self.layer.cad_id,
                **normalize_cad(generic),
            }

        # Source-native values preserved beside the normalized ones
        # (Section 28). Never overwritten by normalization.
        record["_source_attributes"] = dict(raw_record)
        return self.attach_provenance(
            record,
            source_record_id=str(parcel_id) if parcel_id else None,
            retrieved_at=utc_now_iso(),
        )

    def _normalize_fdor(self, attrs: dict, *, county: str | None) -> dict:
        """Map one FDOR cadastral feature onto this project's existing
        Florida property fields. Field choices mirror
        `enrich_property_details.py`'s own documented mapping (JV ->
        `market`, AV_NSD -> `assessed`, ASMNT_YR -> `value_year`), including
        its 0-as-no-data sentinel rule via `_fdor_num()`."""
        return {
            "state": "FL",
            "county": county or self.layer.county,
            "parcel": _fdor_text(attrs.get("PARCEL_ID")),
            "market": _fdor_num(attrs.get("JV")),
            "assessed": _fdor_num(attrs.get("AV_NSD")),
            "land_value": _fdor_num(attrs.get("LND_VAL")),
            "value_year": int(_fdor_num(attrs.get("ASMNT_YR"))) if _fdor_num(attrs.get("ASMNT_YR")) else None,
            "dor_use_code": _fdor_text(attrs.get("DOR_UC")),
            "year_built": int(_fdor_num(attrs.get("ACT_YR_BLT"))) if _fdor_num(attrs.get("ACT_YR_BLT")) else None,
            "living_area": _fdor_num(attrs.get("TOT_LVG_AR")),
            "lot_sqft": _fdor_num(attrs.get("LND_SQFOOT")),
            "num_buildings": int(_fdor_num(attrs.get("NO_BULDNG"))) if _fdor_num(attrs.get("NO_BULDNG")) else None,
            "owner_name": _fdor_text(attrs.get("OWN_NAME")),
            "legal_desc": _fdor_text(attrs.get("S_LEGAL")),
            "address": _fdor_text(attrs.get("PHY_ADDR1")),
            "last_sale_price": _fdor_num(attrs.get("SALE_PRC1")),
            "last_sale_year": int(_fdor_num(attrs.get("SALE_YR1"))) if _fdor_num(attrs.get("SALE_YR1")) else None,
            "homestead": _fdor_num(attrs.get("JV_HMSTD")) is not None,
        }
