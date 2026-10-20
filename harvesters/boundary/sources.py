"""The two parcel-boundary sources and their gates.

Each is the SAME source id the approval register and the permission records
use (data/source_approvals.csv, data/source_permissions.csv); there is no
second permission matrix for boundaries. A boundary source is runnable only
when:

* the approval register has the source and maps it (covered_datasets),
* permissions.authorize() allows `fetch` and `store` for it (and, for the
  read path, `display`),
* its identifier join is configured from the source's own documentation.

Florida DOR (fl_dor_pto_parcel_gis): the county parcel files DOR publishes on
its PTO Data Portal. The join - which file variant (PIN / PAR), which field
carries the parcel number (PARCELNO) and how it lines up with the tax roll's
PARCEL_ID and with the identifier our records carry, how condominium units
are handled - comes from the Parcel Shapefiles Readme. The Readme has not
been read from this repository's environment, so the join is NOT configured
and the source refuses before any request (`fetch` is also held by the
`technical_readme_reviewed` condition). Nothing is guessed.

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
    record_key: str                  # the properties column matched against feature_key_field
    id_rule: str                     # harvesters/enrichment/parcels.py ID_RULES key, applied to both sides
    join_configured: bool
    not_configured_reason: str = ""


FL_DOR = BoundarySource(
    source_id="fl_dor_pto_parcel_gis", state="FL",
    provider="Florida Department of Revenue, Property Tax Oversight",
    dataset="DOR PTO Data Portal county GIS parcel files",
    permission_dataset="county_parcel_geometry",
    counties=(), layer_url=None, feature_key_field=None, feature_id_field=None,
    record_key="parcel", id_rule="alnum", join_configured=False,
    not_configured_reason=("JOIN_NOT_CONFIGURED: the parcel-number field, the PIN/PAR file variant, the PARCELNO to "
                           "PARCEL_ID join, identifier formatting and condominium handling must be taken from the "
                           "Parcel Shapefiles Readme, which has not been read from this environment"),
)

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
    for op in ("fetch", "store"):
        d = authorize(src, op, today=today)
        if not d.allowed:
            reasons.append(f"{op.upper()}_{d.reason_code}")
    if not src.join_configured:
        reasons.append(src.not_configured_reason.split(":", 1)[0] or "JOIN_NOT_CONFIGURED")
    if not src.layer_url:
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
