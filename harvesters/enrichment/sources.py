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

# The state's STATEWIDE layer (at most one per state).
PARCEL_SOURCES: dict[str, ParcelSourceConfig] = {}
# Every registered layer, statewide and county-scoped, in registration order.
_ALL: list[ParcelSourceConfig] = []


def register(cfg: ParcelSourceConfig) -> ParcelSourceConfig:
    if any(c.source_id == cfg.source_id for c in _ALL):
        raise ValueError(f"{cfg.source_id} is already registered")
    if not cfg.counties:
        if cfg.state in PARCEL_SOURCES:
            raise ValueError(f"{cfg.state} already has a statewide parcel source")
        PARCEL_SOURCES[cfg.state] = cfg
    else:
        for other in _ALL:
            # Two county layers may serve one county only when one of them is
            # fill-blank only (it never replaces what the other wrote).
            if other.state == cfg.state and set(other.counties) & set(cfg.counties) \
                    and not (cfg.fill_blank_only or other.fill_blank_only):
                raise ValueError(f"{cfg.source_id}: county scope overlaps {other.source_id}")
    _ALL.append(cfg)
    return cfg


def for_state(state: str) -> ParcelSourceConfig | None:
    return PARCEL_SOURCES.get(state)


def all_sources() -> list[ParcelSourceConfig]:
    return list(_ALL)


def for_county(state: str, county: str) -> list[ParcelSourceConfig]:
    """Every layer covering (state, county): county-scoped layers first (the
    county's own assessor is the closer source), then the statewide one."""
    scoped = [c for c in _ALL if c.state == state and c.counties and county in c.counties]
    statewide = [c for c in _ALL if c.state == state and not c.counties]
    return scoped + statewide


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


# ---------------------------------------------------------------------------
# Louisiana - East Baton Rouge Parish Assessor "Tax Parcel" dataset on Open
# Data BR (data.brla.gov, view ei2c-krsr): one record per tax parcel with the
# assessor's land, fair-market and assessed sums. LICENCE: the dataset's own
# metadata reads licenseId PUBLIC_DOMAIN ("Public Domain"), attribution "EBR
# Parish Assessor" - read live (enrichment-sprint evidence run 36832227666,
# 2026-10-01), the same basis the approved adjudicated list rests on. The
# ArcGIS service carrying the same parcels states "Access Constraints:
# copyright", so the Socrata publication is the one used.
# MATCH: the parish rows' parcel is the adjudicated list's PROPERTY NUMBER,
# shape 999-9999-9; this dataset's assessment_num has the same shape (194 of
# 200 sampled, run 36835470121) - 'exact' rule, no county attribute (the
# dataset is parish-wide). Two records for one number -> AMBIGUOUS. Only the
# attributes seen populated in the live sample are mapped.
# ---------------------------------------------------------------------------
LA_EBR_TAX_PARCELS = register(ParcelSourceConfig(
    source_id="la_ebr_tax_parcels", state="LA",
    agency="East Baton Rouge Parish Assessor (Open Data BR)",
    dataset="Tax Parcel (data.brla.gov ei2c-krsr)",
    landing_url="https://data.brla.gov/d/ei2c-krsr",
    layer_url="https://data.brla.gov/resource/ei2c-krsr.json",
    transport="socrata", id_field="assessment_num", id_rule="exact",
    field_map={"land_value": "sum_land_value", "market": "sum_fair_market_value", "assessed": "sum_assessed_value",
               "legal_desc": "legal_description"},
    licence="Public Domain (Open Data BR dataset metadata, licenseId PUBLIC_DOMAIN); attribution: EBR Parish Assessor.",
    publication_status="APPROVED", county_field=None, centroid=False, columns_verified=True, batch_size=100,
    notes="enrichment sprint evidence (2026-10-01): licence run 36832227666; field names and assessment_num shape run 36835470121. "
          "All-sources engine deep probe (run 36922621158, 2026-10-01): 10,157 of 10,334 AVAILABLE rows match exactly on "
          "assessment_num; legal_description is populated on about 60% of the matched records, so it is now mapped "
          "(fill-blank only - the adjudicated list's own legal description keeps precedence).",
))


# ---------------------------------------------------------------------------
# Louisiana - East Baton Rouge Parish Assessor "EBRP Tax Roll" (Open Data BR,
# myfc-nh6n). One record per parcel per TAX YEAR (2015-2025). Licence read
# live: Public Domain - the same publisher and basis as the approved Tax
# Parcel dataset above. Column meanings are the dataset's OWN definitions
# (discover_sources.py --metadata, run 36940907360):
#   structure_use  "Type of use of the structure including commercial,
#                  residential or not determined"  -> land_use (raw value;
#                  NOT DETERMINED is no classification and is never stored;
#                  blank from tax year 2024 on, so taken from 2023 - see
#                  column_year_floor)
#   taxpayer_val   "TAXABLE PARISH - the taxable amount for determining Parish
#                  taxes derived from the sum of land/acreage value and any
#                  improvement value minus any applicable homestead
#                  exemption"                       -> taxable_value
#   legal_description "Full description of the tax parcel which serves as the
#                  legal record"                    -> legal_desc (fill-blank)
#   units          "Total number of structures attached to the tax parcel" -
#                  NOT acreage, so NOT mapped: no EBR dataset publishes acreage.
# Match (deep probe, run 36937077351): assessment_no equals the adjudicated
# list's parcel for 10,318 of 10,334 rows; the roll repeats each parcel once
# per year, so only the LATEST published year (and no year before 2024) is a
# candidate - two different records in that year stay AMBIGUOUS.
# ---------------------------------------------------------------------------
LA_EBR_TAX_ROLL = register(ParcelSourceConfig(
    source_id="la_ebr_tax_roll", state="LA",
    agency="East Baton Rouge Parish Assessor (Open Data BR)",
    dataset="EBRP Tax Roll (data.brla.gov myfc-nh6n)",
    landing_url="https://data.brla.gov/d/myfc-nh6n",
    layer_url="https://data.brla.gov/resource/myfc-nh6n.json",
    transport="socrata", id_field="assessment_no", id_rule="exact",
    field_map={"land_use": "structure_use", "taxable_value": "taxpayer_val", "legal_desc": "legal_description"},
    no_value={"land_use": ("NOT DETERMINED",)},
    provenance_attrs=("tax_year", "vacant_lot_yn", "assessment_status"),
    latest_field="tax_year", latest_min=2024, value_year_field="tax_year",
    # STRUCTURE USE is filled on every matched record 2015-2023 and blank on
    # every 2024 / 2025 record (per-year fill, run 36942777361): land use comes
    # from tax year 2023, dated as such in its provenance.
    column_year_floor={"land_use": 2023},
    licence="Public Domain (Open Data BR dataset metadata, licence read live in runs 36921157970 / 36940907360); attribution: EBR Parish Assessor.",
    publication_status="APPROVED", counties=("East Baton Rouge",), centroid=False, columns_verified=True, batch_size=100,
    notes="AVAILABLE sprint 2026-10-01: column definitions run 36940907360; identifier match run 36937077351 (10,318 of 10,334).",
))


# ---------------------------------------------------------------------------
# Texas - Jim Wells Central Appraisal District parcel web service (hosted by
# the district's GIS vendor, BIS Consultants). DEEP PROBE (all-sources engine,
# run 36922621158): all 11 Jim Wells AVAILABLE rows match exactly - the row's
# case_no (the LGBS account number) equals the layer's geoID (13 digits both
# sides); legalDescr is populated on 11 and legalAcrea on 9.
# LICENCE: the layer carries no licenseInfo / copyrightText and no terms of
# use were found. Appraisal records are public under the Texas Public
# Information Act, but public is not permission to republish: UNREVIEWED,
# so enrichment_allowed() refuses it until a publication review approves.
# ---------------------------------------------------------------------------
TX_JIM_WELLS_CAD = register(ParcelSourceConfig(
    source_id="tx_jim_wells_cad_parcels", state="TX",
    agency="Jim Wells Central Appraisal District (GIS hosted by BIS Consultants)",
    dataset="JimWellsCADWebService - Parcels",
    landing_url="https://services8.arcgis.com/36tOt5wOeEMz3tyS/arcgis/rest/services/JimWellsCADWebService/FeatureServer",
    layer_url="https://services8.arcgis.com/36tOt5wOeEMz3tyS/arcgis/rest/services/JimWellsCADWebService/FeatureServer/0",
    id_field="geoID", id_rule="alnum", row_id_column="case_no",
    field_map={"legal_desc": "legalDescr", "acreage": "legalAcrea"},
    licence="None stated on the layer (no licenseInfo / copyrightText) and no terms of use found - reuse not reviewed.",
    publication_status="UNREVIEWED", counties=("Jim Wells",), centroid=True, columns_verified=True, batch_size=50,
    notes="all-sources engine deep probe run 36922621158: 11 of 11 rows match on geoID = case_no; legalDescr 11, legalAcrea 9.",
))


# ---------------------------------------------------------------------------
# Missouri - City of St. Louis parcel layer, for COORDINATES ONLY
# (authoritative-coordinates sprint, 2026-10-06).
#
# The LRA inventory list (mo_stl_lra_inventory) publishes a street address
# but no coordinates. The city's own parcel layer GIS.ASR.PARCELS (PDA_ZONING
# MapServer layer 0) is keyed on HANDLE, which the city names as the parcel
# key in its parcel datasets.
#
# SEARCH INDEX ONLY - nothing here has been read live: every stlouis-mo.gov
# host is blocked from the development sandbox. This config is therefore
# inert (columns_verified=False, publication UNREVIEWED; enrichment_allowed()
# refuses it). It writes no column except the centroid of the one matched
# parcel polygon (latitude / longitude, provenance statewide_parcel ->
# coordinates.PARCEL_GIS / PARCEL_CENTROID).
#
# Before it may run:
#   1. available_mode=metadata reads the layer's own field list
#      (scripts/discover_sources.py DEEP_TARGETS);
#   2. available_mode=probe measures exact HANDLE matches against the LRA
#      ParcelId (believed to be the same 11-digit handle - NOT verified);
#   3. the terms of reuse are reviewed.
# ---------------------------------------------------------------------------
MO_STL_PARCELS = register(ParcelSourceConfig(
    source_id="mo_stl_parcels_coordinates", state="MO",
    agency="City of St. Louis (Assessor parcel GIS)",
    dataset="GIS.ASR.PARCELS (public/PDA_ZONING MapServer layer 0)",
    landing_url="https://www.stlouis-mo.gov/data/datasets/dataset.cfm?id=82",
    layer_url="https://stlgis.stlouis-mo.gov/arcgis/rest/services/public/PDA_ZONING/MapServer/0",
    id_field="HANDLE", id_rule="digits", field_map={},
    licence="City of St. Louis open data - terms not yet reviewed for this product",
    publication_status="UNREVIEWED", centroid=True, columns_verified=False,
    counties=("St. Louis City",),
    notes="Coordinates only: the area-weighted centroid of the one parcel whose HANDLE equals the row's parcel id. "
          "Search-index evidence only; inert until the layer's fields and the HANDLE / ParcelId match are measured live.",
))


# ---------------------------------------------------------------------------
# Texas - TxGIO StratMap Land Parcels 2026 (TX enrichment, 2026-10-27).
#
# The Texas Geographic Information Office (Texas Water Development Board)
# publishes the appraisal districts' parcel data, "translated into this common
# schema" (BIS Consultants), as ONE zipped shapefile per county:
#   https://tnris-data-warehouse.s3.us-east-1.amazonaws.com/LCD/collection/
#     stratmap-2026-land-parcels/items/shp/stratmap-2026-land-parcels_<FIPS>_shp.zip
# (253 counties; listed 2026-10-27). The statewide map service lists Query as a
# capability but refuses every query ("Requested operation is not supported by
# this service", read 2026-10-27) - hence the county_file transport.
#
# FIELD DEFINITIONS - the TxGIO Land Parcel Schema (Appendix A,
# https://geographic.texas.gov/_uploads/TxGIO-land-parcel-schema.pdf, read
# 2026-10-27), under the shapefile's 10-character names:
#   PROP_ID / GEO_ID  "Source unique identifier that can be joined with other datasets"
#   STAT_LAND_        STAT_LAND_USE "Legal land use utilizing State of Texas land use codes" -> land_use (raw)
#   LEGAL_AREA        "Legal area per deed. The non-rounded value." -> acreage, ONLY when
#   LGL_AREA_U        LGL_AREA_UNIT "Legal area units per deed" reads ACRE / ACRES / AC
#   LAND_VALUE        "Current value of land"          -> land_value
#   IMP_VALUE         "Current value of improvements"  -> improvement_value
#   MKT_VALUE         "Current market value"           -> market
#   TAX_YEAR          "The year of this dataset"       -> value_year
#   YEAR_BUILT        "Year structure built"           -> year_built (a single year only;
#                     several years joined with commas is not one year and is not stored)
# NOT mapped: LOC_LAND_USE (local codes, no published legend), GIS_AREA (a GIS
# computation, not the deed area), owner / mailing columns, and SITUS_ADDR /
# LEGAL_DESC (the Texas listing syncs write address / legal_desc themselves -
# mapping them would make the two writers take turns). The schema has no
# building-area column.
#
# MATCH - each appraisal district fills a different identifier column, so the
# column AND rule are MEASURED per county (county_id below): for every county
# with TX rows, a sample of the rows' accounts (case_no, the CAD account the
# vendor listings publish) was matched against that county's 2026 file
# (2026-10-27, counts only). A county is listed only when at least half of its
# sampled accounts matched exactly one record; 'numeric' (digits, leading
# zeros dropped) is used only where the listing's sampled accounts share one
# shape (e.g. every one written 'R' + digits) and the CAD file stores digits.
# Excluded (no or too few matches): Tarrant (its PROP_ID is TAD's lot/block
# key, not the 8-digit account), Hunt, Matagorda, Smith, Grayson, Hardin,
# Red River, Travis, Anderson, Erath, Franklin, Goliad, Panola.
#
# PERMISSION - interim internal risk acceptance (owner decision 2026-10-26,
# owner request 2026-10-27) in data/source_permissions.csv. TWDB's site
# "freely grants permission to copy and distribute its materials", but the
# parcel attributes are the appraisal districts' records, whose own reuse
# terms were not read. Fill-blank only; the dataset is never redistributed.
# ---------------------------------------------------------------------------
TX_STRATMAP_COUNTY_ID = {
    "Dallas": (("PROP_ID",), "alnum"),  # 12/12 sampled; 697171 parcels
    "Harris": (("PROP_ID",), "alnum"),  # 5/10 sampled; 542330 parcels
    "Jefferson": (("GEO_ID",), "alnum"),  # 8/8 sampled; 122325 parcels
    "Orange": (("GEO_ID",), "alnum"),  # 7/8 sampled; 50691 parcels
    "Galveston": (("GEO_ID",), "alnum"),  # 7/8 sampled; 190730 parcels
    "Navarro": (("GEO_ID",), "alnum"),  # 8/10 sampled; 46146 parcels
    "Jasper": (("GEO_ID",), "numeric"),  # 8/8 sampled; 34290 parcels
    "Liberty": (("GEO_ID",), "alnum"),  # 4/8 sampled; 164598 parcels
    "San Patricio": (("PROP_ID",), "alnum"),  # 5/8 sampled; 51392 parcels
    "Cameron": (("GEO_ID",), "alnum"),  # 8/8 sampled; 185061 parcels
    "Hidalgo": (("GEO_ID",), "alnum"),  # 8/8 sampled; 334039 parcels
    "Leon": (("GEO_ID",), "numeric"),  # 8/8 sampled; 28254 parcels
    "Bexar": (("GEO_ID",), "alnum"),  # 8/8 sampled; 721499 parcels
    "Nueces": (("GEO_ID",), "alnum"),  # 7/8 sampled; 158832 parcels
    "Atascosa": (("PROP_ID",), "alnum"),  # 7/8 sampled; 37147 parcels
    "Victoria": (("GEO_ID",), "alnum"),  # 8/8 sampled; 43838 parcels
    "Ector": (("PROP_ID",), "alnum"),  # 8/8 sampled; 88980 parcels
    "El Paso": (("GEO_ID",), "alnum"),  # 8/8 sampled; 401228 parcels
    "Montgomery": (("GEO_ID",), "numeric"),  # 7/8 sampled; 320910 parcels
    "McLennan": (("GEO_ID",), "alnum"),  # 8/8 sampled; 116150 parcels
    "Tyler": (("PROP_ID",), "numeric"),  # 4/8 sampled; 32913 parcels
    "Live Oak": (("PROP_ID",), "alnum"),  # 8/8 sampled; 17256 parcels
    "Starr": (("PROP_ID",), "numeric"),  # 8/8 sampled; 40525 parcels
    "Angelina": (("PROP_ID",), "alnum"),  # 7/8 sampled; 60763 parcels
    "Gregg": (("PROP_ID",), "alnum"),  # 5/8 sampled; 78015 parcels
    "Val Verde": (("GEO_ID",), "alnum"),  # 7/8 sampled; 31660 parcels
    "Lamar": (("PROP_ID",), "alnum"),  # 8/8 sampled; 36525 parcels
    "Marion": (("PROP_ID",), "numeric"),  # 8/8 sampled; 19757 parcels
    "Cass": (("GEO_ID",), "alnum"),  # 8/8 sampled; 35172 parcels
    "Fort Bend": (("GEO_ID",), "alnum"),  # 8/8 sampled; 375108 parcels
    "Jim Wells": (("GEO_ID",), "alnum"),  # 8/8 sampled; 27945 parcels
    "Frio": (("PROP_ID",), "alnum"),  # 8/8 sampled; 13311 parcels
    "Wood": (("PROP_ID",), "numeric"),  # 7/8 sampled; 45058 parcels
    "Duval": (("GEO_ID",), "alnum"),  # 4/8 sampled; 15319 parcels
    "Jackson": (("GEO_ID",), "alnum"),  # 7/8 sampled; 18437 parcels
    "Maverick": (("PROP_ID",), "alnum"),  # 7/8 sampled; 26212 parcels
    "Polk": (("GEO_ID",), "alnum"),  # 8/8 sampled; 59975 parcels
    "Parker": (("PROP_ID",), "numeric"),  # 8/8 sampled; 102062 parcels
    "Upshur": (("PROP_ID",), "alnum"),  # 8/8 sampled; 30544 parcels
    "Zavala": (("GEO_ID",), "alnum"),  # 8/8 sampled; 9716 parcels
    "Hays": (("GEO_ID",), "alnum"),  # 4/8 sampled; 121110 parcels
    "Shelby": (("PROP_ID",), "numeric"),  # 8/8 sampled; 21455 parcels
    "Henderson": (("PROP_ID",), "alnum"),  # 7/8 sampled; 106332 parcels
    "Kaufman": (("PROP_ID",), "alnum"),  # 7/8 sampled; 99589 parcels
    "Llano": (("PROP_ID",), "numeric"),  # 6/8 sampled; 38954 parcels
    "Falls": (("GEO_ID",), "alnum"),  # 7/8 sampled; 18835 parcels
    "Gonzales": (("GEO_ID",), "alnum"),  # 8/8 sampled; 20854 parcels
    "Madison": (("PROP_ID",), "alnum"),  # 8/8 sampled; 10394 parcels
    "Zapata": (("GEO_ID",), "alnum"),  # 8/8 sampled; 12664 parcels
    "Cherokee": (("PROP_ID",), "numeric"),  # 8/8 sampled; 47020 parcels
    "Jim Hogg": (("GEO_ID",), "alnum"),  # 8/8 sampled; 4446 parcels
    "La Salle": (("GEO_ID",), "alnum"),  # 6/8 sampled; 9894 parcels
    "Van Zandt": (("GEO_ID",), "alnum"),  # 8/8 sampled; 43840 parcels
    "Bosque": (("PROP_ID",), "numeric"),  # 7/7 sampled; 20055 parcels
    "Caldwell": (("PROP_ID",), "alnum"),  # 7/7 sampled; 28036 parcels
    "Delta": (("GEO_ID",), "alnum"),  # 7/7 sampled; 6471 parcels
    "Ellis": (("PROP_ID",), "alnum"),  # 7/7 sampled; 101497 parcels
    "Kleberg": (("PROP_ID",), "alnum"),  # 7/7 sampled; 14909 parcels
    "Montague": (("GEO_ID",), "alnum"),  # 6/7 sampled; 26548 parcels
    "Aransas": (("PROP_ID",), "alnum"),  # 6/6 sampled; 27005 parcels
    "Brooks": (("GEO_ID",), "alnum"),  # 6/6 sampled; 6029 parcels
    "Morris": (("GEO_ID",), "alnum"),  # 5/6 sampled; 11972 parcels
    "Tom Green": (("GEO_ID",), "alnum"),  # 6/6 sampled; 59030 parcels
    "Wise": (("GEO_ID",), "alnum"),  # 5/6 sampled; 53011 parcels
    "Concho": (("GEO_ID",), "alnum"),  # 5/5 sampled; 8035 parcels
    "Kerr": (("GEO_ID",), "alnum"),  # 4/5 sampled; 36659 parcels
    "Robertson": (("GEO_ID",), "alnum"),  # 5/5 sampled; 17237 parcels
    "Bee": (("PROP_ID",), "alnum"),  # 2/4 sampled; 23063 parcels
    "Fannin": (("GEO_ID",), "alnum"),  # 4/4 sampled; 29359 parcels
    "Limestone": (("PROP_ID",), "numeric"),  # 4/4 sampled; 22175 parcels
    "Titus": (("GEO_ID",), "alnum"),  # 4/4 sampled; 20955 parcels
    "Wilson": (("GEO_ID",), "alnum"),  # 4/4 sampled; 29144 parcels
    "Hamilton": (("PROP_ID",), "numeric"),  # 3/3 sampled; 14001 parcels
    "Houston": (("PROP_ID",), "numeric"),  # 3/3 sampled; 26621 parcels
    "Reeves": (("GEO_ID",), "alnum"),  # 2/2 sampled; 23494 parcels
    "Sabine": (("PROP_ID",), "numeric"),  # 2/2 sampled; 23731 parcels
    "Camp": (("PROP_ID",), "alnum"),  # 1/1 sampled; 11708 parcels
    "Collin": (("GEO_ID",), "alnum"),  # 1/1 sampled; 387736 parcels
    "Hopkins": (("GEO_ID",), "alnum"),  # 1/1 sampled; 25436 parcels
    "Kinney": (("PROP_ID",), "alnum"),  # 1/1 sampled; 11071 parcels
    "Pecos": (("GEO_ID",), "alnum"),  # 1/1 sampled; 17908 parcels
    "Rockwall": (("GEO_ID",), "alnum"),  # 1/1 sampled; 55134 parcels
    "Rusk": (("GEO_ID",), "alnum"),  # 1/1 sampled; 40321 parcels
}


def _tx_fips() -> dict:
    """County -> FIPS from the app's own county table (public/county-centroids.json)."""
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    data = json.loads((Path(__file__).resolve().parents[2] / "public" / "county-centroids.json").read_text(encoding="utf-8"))
    return {c: v["fips"] for c, v in data["TX"].items() if c in TX_STRATMAP_COUNTY_ID}


# The Texas vendor listings whose case_no is the appraisal-district account
# (harvesters/ledgers/records.py CAUSE_IN_PARCEL_SOURCES).
TX_ACCOUNT_IN_CASE_NO_SOURCES = ("tx_lgbs", "tx_realauction", "tx_pbfcm", "tx_mvba", "tx_govease")

TX_STRATMAP = register(ParcelSourceConfig(
    source_id="tx_txgio_stratmap_parcels", state="TX",
    agency="Texas Geographic Information Office (TxGIO, Texas Water Development Board) - county appraisal district data",
    dataset="StratMap Land Parcels 2026 (TxGIO DataHub, one shapefile per county)",
    landing_url="https://geographic.texas.gov/stratmap/land-parcels.html",
    layer_url="https://tnris-data-warehouse.s3.us-east-1.amazonaws.com/LCD/collection/stratmap-2026-land-parcels/",
    file_url_template=("https://tnris-data-warehouse.s3.us-east-1.amazonaws.com/LCD/collection/stratmap-2026-land-parcels/"
                       "items/shp/stratmap-2026-land-parcels_{fips}_shp.zip"),
    transport="county_file", id_field="PROP_ID", id_rule="alnum", row_id_column="case_no",
    county_id=TX_STRATMAP_COUNTY_ID, county_fips=_tx_fips(), counties=tuple(sorted(TX_STRATMAP_COUNTY_ID)),
    field_map={"land_use": "STAT_LAND_", "year_built": "YEAR_BUILT", "land_value": "LAND_VALUE",
               "improvement_value": "IMP_VALUE", "market": "MKT_VALUE"},
    conditional_map={"acreage": ("LEGAL_AREA", "LGL_AREA_U", ("ACRE", "ACRES", "AC"))},
    value_year_field="TAX_YEAR", provenance_attrs=("SOURCE", "DATE_ACQ", "LGL_AREA_U"),
    licence=("TxGIO StratMap Land Parcels: county appraisal district data compiled for TxGIO; TWDB Copyright Policy 'freely "
             "grants permission to copy and distribute its materials' (read 2026-10-27); the appraisal districts' own reuse "
             "terms were not read - interim internal risk acceptance (data/source_permissions.csv)."),
    publication_status="APPROVED", centroid=True, columns_verified=True, fill_blank_only=True,
    row_source_ids=TX_ACCOUNT_IN_CASE_NO_SOURCES,
    notes=("TX enrichment 2026-10-27: schema definitions read from the TxGIO Land Parcel Schema PDF; per-county identifier "
           "column and rule measured against a sample of the rows' accounts for every county with TX rows (counts only); "
           "the shapefiles' .prj is geographic WGS 84, so the centroid is the matched parcel polygon's own."),
))


# ---------------------------------------------------------------------------
# Texas - Harris Central Appraisal District parcel layer (www.gis.hctx.net
# HCAD/Parcels MapServer layer 0, copyright "Harris County Appraisal
# District"). Read live 2026-10-27: Query capability, 1,000 records a request;
# HCAD_NUM is the 13-digit HCAD account - 7 of 10 sampled Harris accounts
# matched exactly (StratMap's Harris file: 5 of 10, and it carries no values
# or land use for Harris). The layer publishes NO field definitions (its
# description reads "Parcel polygon is the delineation of the property
# boundary"), so only self-describing columns whose sampled values have the
# expected shape are mapped: state_class (the Comptroller's state property
# category, e.g. 'A1'), land_value, impr_value, total_market_val, acreage_1
# (numeric acres) and tax_year. Not mapped: the free-text 'Acreage', owner /
# mailing columns, legal-description lines. Fill-blank only (StratMap fills
# year_built for Harris; this layer has none). Interim permission records.
# ---------------------------------------------------------------------------
TX_HCAD = register(ParcelSourceConfig(
    source_id="tx_hcad_parcels", state="TX",
    agency="Harris Central Appraisal District (Harris County GIS)",
    dataset="HCAD Parcels (gis.hctx.net HCAD/Parcels MapServer layer 0)",
    landing_url="https://www.gis.hctx.net/arcgis/rest/services/HCAD/Parcels/MapServer",
    layer_url="https://www.gis.hctx.net/arcgis/rest/services/HCAD/Parcels/MapServer/0",
    id_field="HCAD_NUM", id_rule="alnum", row_id_column="case_no",
    field_map={"land_use": "state_class", "land_value": "land_value", "improvement_value": "impr_value",
               "market": "total_market_val", "acreage": "acreage_1"},
    value_year_field="tax_year",
    licence=("Harris Central Appraisal District parcel layer (copyright 'Harris County Appraisal District'); no licence or "
             "terms stated on the layer - interim internal risk acceptance (data/source_permissions.csv)."),
    publication_status="APPROVED", counties=("Harris",), centroid=True, columns_verified=True, fill_blank_only=True,
    row_source_ids=TX_ACCOUNT_IN_CASE_NO_SOURCES, batch_size=50,
    notes="TX enrichment 2026-10-27: fields read live; 7 of 10 sampled Harris accounts matched HCAD_NUM exactly.",
))
