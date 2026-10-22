"""The two parcel-boundary sources and their gates.

Each is the SAME source id the approval register and the permission records
use (data/source_approvals.csv, data/source_permissions.csv); there is no
second permission matrix for boundaries. A boundary source is runnable only
when:

* the approval register has the source and maps it (covered_datasets),
* permissions.authorize() allows `fetch` and `store` for it (and, for the
  read path, `display`),
* its identifier join is configured from the source's own documentation.

Florida DOR (fl_dor_pto_parcel_gis): the county parcel shapefiles DOR
publishes on its PTO Data Portal, read from local files a person downloaded
(no download URL is configured or guessed). The join follows the Parcel
Shapefiles Readme, reviewed by the product owner on 2026-10-20: PIN files,
PARCELNO read as DBF text, matched to the record's VALIDATED NAL PARCEL_ID
exactly, condominium and right-of-way records never attached - see
harvesters/boundary/fl_dor.py.

Utah UGRC (ut_ugrc_lir_saltlake): the Salt Lake County LIR layer whose fields
were read live on 2026-09-30 (harvesters/enrichment/sources.py UT_UGRC_LIR):
PARCEL_ID is the identifier, matched to the record's `parcel` with the same
`alnum` rule the attribute enrichment uses. Utah is not an activated state,
so no Utah property exists to match today.
"""
from __future__ import annotations

from dataclasses import dataclass

from harvesters.enrichment.sources import UT_UGRC_LIR
from harvesters.governance import permissions, source_approvals


@dataclass(frozen=True)
class BoundarySource:
    source_id: str
    state: str
    provider: str
    dataset: str                 # the dataset as the source names it (stored as source_dataset)
    permission_dataset: str | None   # dataset key of the permission records ('*' records when None)
    counties: tuple[str, ...]    # counties this source's layer covers; () = every county of the state
    layer_url: str | None
    feature_key_field: str | None    # the source's parcel identifier field
    feature_id_field: str | None     # the source's own feature identifier (kept as provenance)
    record_key: str                  # the record field matched against feature_key_field
    id_rule: str                     # harvesters/enrichment/parcels.py ID_RULES key, or "exact" (no reformatting)
    join_configured: bool
    not_configured_reason: str = ""
    location: str = "arcgis"         # arcgis (layer_url) | files (local shapefiles given per run)


FL_DOR = BoundarySource(
    # Join from the Parcel Shapefiles Readme (reviewed 2026-10-20, recorded in
    # data/source_approvals.csv): PIN files only (FID, Shape, PARCELNO - no tax-roll
    # attributes), PARCELNO in the shapefile to the record's VALIDATED NAL PARCEL_ID
    # (harvesters/boundary/fl_dor.py). Files are read locally, one county at a time;
    # FID is the feature's position in its file (the dataset names the file).
    source_id="fl_dor_pto_parcel_gis", state="FL",
    provider="Florida Department of Revenue, Property Tax Oversight",
    dataset="DOR PTO Data Portal county GIS parcel files (PIN variant)",
    permission_dataset="county_parcel_geometry",
    counties=(), layer_url=None, feature_key_field="PARCELNO", feature_id_field="FID",
    record_key="join_key", id_rule="exact", join_configured=True, location="files",
)

# Florida DOR county PIN files, as the product owner copied them from the
# portal (2026-10-20). Broward is the ONLY county recorded here: no other county
# link is assumed from this pattern. The folder is 2025F, so this is a 2025 file,
# not "current year". Read only by the manual Broward loader
# (scripts/load_florida_broward_boundaries.py), dry run by default.
FL_DOR_PIN_FILES = {
    "Broward": {
        "url": ("https://floridarevenue.com/property/dataportal/Documents/PTO%20Data%20Portal/"
                "Map%20Data/2025F/2025F%20PIN/broward_2025pin.zip"),
        "tax_year": 2025,
        "variant": "PIN",
        "copied_on": "2026-10-20",
        "copied_by": "product owner (from the DOR PTO Data Portal, Map Data / 2025F / 2025F PIN)",
    },
}

UT_UGRC = BoundarySource(
    source_id=UT_UGRC_LIR.source_id, state="UT",
    provider="Utah Geospatial Resource Center (UGRC)",
    dataset="Parcels_SaltLake_LIR",
    permission_dataset=None,
    counties=("Salt Lake",), layer_url=UT_UGRC_LIR.layer_url,
    feature_key_field=UT_UGRC_LIR.id_field, feature_id_field="OBJECTID",
    record_key="parcel", id_rule=UT_UGRC_LIR.id_rule, join_configured=True,
)

SOURCES: dict[str, BoundarySource] = {s.source_id: s for s in (FL_DOR, UT_UGRC)}


def authorize(src: BoundarySource, operation: str, *, county: str | None = None, today=None):
    kw = {"state": src.state, "county": county, "dataset": src.permission_dataset}
    if today is not None:
        kw["today"] = today
    return permissions.authorize(src.source_id, operation, **kw)


def readiness(src: BoundarySource, *, today=None) -> dict:
    """Whether a refresh may run, and every reason it may not. Nothing here
    makes a request."""
    reasons: list[str] = []
    approval = source_approvals.get(src.source_id)
    if approval is None:
        reasons.append("NOT_IN_APPROVAL_REGISTER")
    elif not any(d.startswith(src.source_id + " <- ") and "MAPPED" in d for d in approval.covered_datasets):
        reasons.append("DATASET_NOT_MAPPED")
    # A layer is requested (fetch); local shapefiles a person downloaded are
    # read (parse). Either way the result is stored.
    for op in (("fetch", "store") if src.location == "arcgis" else ("parse", "store")):
        d = authorize(src, op, today=today)
        if not d.allowed:
            reasons.append(f"{op.upper()}_{d.reason_code}")
    if not src.join_configured:
        reasons.append(src.not_configured_reason.split(":", 1)[0] or "JOIN_NOT_CONFIGURED")
    if src.location == "arcgis" and not src.layer_url:
        reasons.append("NO_SOURCE_LOCATION_CONFIGURED")
    display = authorize(src, "display", today=today)
    return {"source_id": src.source_id, "runnable": not reasons, "reasons": reasons,
            "display_allowed": display.allowed, "display_reason": display.reason_code}


def attribution(source_id: str) -> dict:
    """What every surface showing this source's geometry carries: credit,
    licence, change notice, disclaimer and metadata (from the approval
    register - never retyped here)."""
    a = source_approvals.get(source_id)
    if a is None:
        return {}
    return {"credit": a.credit, "license_name": a.license_name, "license_url": a.license_url,
            "change_notice": a.change_notice, "disclaimer": a.disclaimer, "disclaimer_url": a.disclaimer_url,
            "metadata_url": a.metadata_url, "expected_refresh_cadence": a.expected_refresh_cadence}
