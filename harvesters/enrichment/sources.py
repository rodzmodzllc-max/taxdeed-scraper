"""The statewide parcel / assessment sources the enrichment factory may use,
one ParcelSourceConfig per state (six-state expansion sprint).

A config here is a description of a live layer, not permission: the
factory's `enrichment_allowed()` still refuses any source whose columns
were not verified live or whose publication decision is not APPROVED.
Evidence for every value below is the manual evidence run named in each
config's `notes` (docs/six-state-expansion.md).
"""
from __future__ import annotations

from .parcels import ParcelSourceConfig

PARCEL_SOURCES: dict[str, ParcelSourceConfig] = {}


def register(cfg: ParcelSourceConfig) -> ParcelSourceConfig:
    if cfg.state in PARCEL_SOURCES:
        raise ValueError(f"{cfg.state} already has a statewide parcel source")
    PARCEL_SOURCES[cfg.state] = cfg
    return cfg


def for_state(state: str) -> ParcelSourceConfig | None:
    return PARCEL_SOURCES.get(state)


# ---------------------------------------------------------------------------
# Colorado - Governor's Office of Information Technology (OIT) GIS
# "Colorado_Public_Parcel_Composite": 2,599,744 parcels aggregated from county
# assessors, with account, owner, situs, legal description, acreage, land
# use, zoning and values. Fields read live (evidence pass 4, 2026-09-30).
# Terms: the item states the data "has been modified for use from its
# original source, which is the State of Colorado" and disclaims all
# warranties; the dataset description also says resale of the data is
# forbidden. PUBLICATION: approved by the owner on 2026-09-30 for display
# alongside the product's own county-sourced rows (not for resale of the
# dataset) - recorded here and in docs/six-state-expansion.md.
# Matched on (countyName, account) - Morgan County's certificate list
# publishes the assessor ACCOUNT number ("ACCT #"), which is this layer's
# `account` attribute; never on owner or address.
# ---------------------------------------------------------------------------
CO_OIT_PARCELS = register(ParcelSourceConfig(
    source_id="co_oit_public_parcels", state="CO",
    agency="Colorado Governor's Office of Information Technology (OIT) GIS",
    dataset="Colorado Public Parcels (Colorado_Public_Parcel_Composite)",
    landing_url="https://gis.colorado.gov/public/rest/services/Address_and_Parcel/Colorado_Public_Parcels/FeatureServer",
    layer_url="https://gis.colorado.gov/public/rest/services/Address_and_Parcel/Colorado_Public_Parcels/FeatureServer/0",
    id_field="account", id_rule="alnum",
    field_map={"owner_name": "owner", "address": "situsAdd", "legal_desc": "legalDesc", "acreage": "landAcres",
               "land_use": "landUseDsc", "market": "apprValTot", "taxable_value": "asedValTot"},
    licence="State of Colorado (OIT GIS): data modified from its original source; no warranty; resale of the data "
            "is forbidden by the source. Displayed per the owner's publication decision of 2026-09-30.",
    publication_status="APPROVED", county_field="countyName", centroid=True, columns_verified=True, batch_size=50,
    notes="evidence pass 4 (2026-09-30): layer 0 fields and count read live; apprValTot alias 'Parcel Total Value', "
          "asedValTot alias 'Taxable Value'.",
))


# ---------------------------------------------------------------------------
# Utah - Utah Geospatial Resource Center (UGRC), SGID "LIR" (Land Information
# Records) parcels: county year-end tax-roll attributes on parcel polygons.
# Licence: CC BY 4.0 (UGRC data license page, read live) - attribution to
# UGRC, a link to the licence and a note of changes are required. Only the
# Salt Lake County LIR layer's fields were read (evidence pass 3); Utah is
# NOT activated (no current tax-sale inventory until the May 2027 sale), so
# the runner refuses before any request. Registered so activation is data.
# ---------------------------------------------------------------------------
UT_UGRC_LIR = register(ParcelSourceConfig(
    source_id="ut_ugrc_lir_saltlake", state="UT",
    agency="Utah Geospatial Resource Center (UGRC)",
    dataset="SGID Parcels - Salt Lake County LIR (Parcels_SaltLake_LIR)",
    landing_url="https://gis.utah.gov/products/sgid/cadastre/parcels/",
    layer_url="https://services1.arcgis.com/99lidPhWCzftIe9K/arcgis/rest/services/Parcels_SaltLake_LIR/FeatureServer/0",
    id_field="PARCEL_ID", id_rule="alnum",
    field_map={"address": "PARCEL_ADD", "market": "TOTAL_MKT_VALUE", "land_value": "LAND_MKT_VALUE",
               "acreage": "PARCEL_ACRES", "prop_type": "PROP_CLASS", "land_use": "PROP_TYPE",
               "year_built": "BUILT_YR", "living_area": "BLDG_SQFT"},
    licence="CC BY 4.0 (UGRC data license and disclaimer policy): credit UGRC, link the licence, note changes.",
    publication_status="APPROVED", county_field="COUNTY_NAME", centroid=True, columns_verified=True,
    notes="evidence pass 3 (2026-09-30): Salt Lake LIR fields read live; statewide LIR is published per county.",
))


# ---------------------------------------------------------------------------
# Wisconsin - Statewide Parcel Map Initiative, V12 (State Cartographer's
# Office / Wisconsin Land Information Program, DOA): 3,574,646 parcels with
# county assessed values (CNTASSDVALUE, LNDVALUE, IMPVALUE), estimated fair
# market value, assessed acres, owner and site address. Fields, counts and
# identifier shapes read LIVE (five-state sprint, runs 36793062673 /
# 36793611223 / 36793980491): Green County PARCELID is 13 digits and Dane
# County's 12 - exactly the digits of the counties' own published Tax
# Parcel Numbers (99-999 9999.9999 / 9999-999-9999-9), so the match is the
# 'digits' rule on (CONAME, PARCELID). TAXROLLYEAR is mostly 2025.
# LICENCE: the item says only "This data free for public consumption as of:
# 06/30/2026" and the SCO page "This data is provided free of charge" - no
# explicit grant covering commercial reuse or redistribution was read. So
# the source is UNREVIEWED: implemented and verified, refused by
# enrichment_allowed() until a publication decision approves it.
# ---------------------------------------------------------------------------
WI_SCO_V12 = register(ParcelSourceConfig(
    source_id="wi_sco_v12_parcels", state="WI",
    agency="Wisconsin State Cartographer's Office / Wisconsin Land Information Program (DOA)",
    dataset="V12 Statewide Parcel Map Database (V1200_WisconsinParcels_2026)",
    landing_url="https://www.sco.wisc.edu/parcels/data/",
    layer_url="https://services3.arcgis.com/n6uYoouQZW75n5WI/arcgis/rest/services/Wisconsin_Statewide_Parcels_DB/FeatureServer/0",
    id_field="PARCELID", id_rule="digits",
    field_map={"owner_name": "OWNERNME1", "address": "SITEADRESS", "assessed": "CNTASSDVALUE", "land_value": "LNDVALUE",
               "improvement_value": "IMPVALUE", "market": "ESTFMKVALUE", "acreage": "ASSDACRES"},
    licence="'This data free for public consumption as of: 06/30/2026' (item); 'This data is provided free of charge' (SCO "
            "data page). No explicit commercial reuse / redistribution grant read - UNREVIEWED.",
    publication_status="UNREVIEWED", county_field="CONAME", county_values={"Green": "GREEN", "Dane": "DANE"},
    value_year_field="TAXROLLYEAR", centroid=True, columns_verified=True, batch_size=50,
    notes="five-state sprint evidence (2026-10-01): layer fields, count 3,574,646, Green / Dane PARCELID shapes.",
))
