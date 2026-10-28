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


OWNER_2026_10_25 = ("Owner's decision 2026-10-25: a public-record parcel layer collected to fill gaps on records the "
                    "product already holds; nothing is sold until legal review.")


def register(cfg: ParcelSourceConfig) -> ParcelSourceConfig:
    if any(c.source_id == cfg.source_id for c in _ALL):
        raise ValueError(f"{cfg.source_id} is already registered")
    if not cfg.counties:
        if cfg.state in PARCEL_SOURCES:
            raise ValueError(f"{cfg.state} already has a statewide parcel source")
        PARCEL_SOURCES[cfg.state] = cfg
    else:
        for other in _ALL:
            # Two county layers may serve one county only when they write
            # DIFFERENT columns (2026-10-27: Horry's assessor layer, its address
            # points and its open-data parcels): one column, one county source -
            # or when one of them is fill-blank only (TX enrichment 2026-10-27:
            # it never replaces what the other wrote).
            shared = other.written_columns() & cfg.written_columns()
            if other.state == cfg.state and other.counties and set(other.counties) & set(cfg.counties) and shared \
                    and not (cfg.fill_blank_only or other.fill_blank_only):
                raise ValueError(f"{cfg.source_id}: county scope overlaps {other.source_id} on {sorted(shared)}")
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
    # Thin-fields sprint (2026-10-27): Saguache's 2026 Tax Sale list keeps the
    # assessor ACCOUNT in case_no and the 12-digit PARCEL number in parcel (the
    # column this layer is matched on), so the account-only match found none of
    # its 900 rows - the "64 of 994" the 2026-10-27 run reported were Morgan and
    # Douglas only. The layer publishes that parcel number as `parcel_id`
    # (Saguache, read live: 200 of 200 sampled list parcels equal exactly one
    # parcel_id, 0 ambiguous). An account (a letter + digits) and a parcel_id
    # (12 digits) can never normalize to the same key, and a key reaching two
    # different features is AMBIGUOUS (nothing written).
    alt_id_fields=("parcel_id",),
    field_map={"owner_name": "owner", "address": "situsAdd", "legal_desc": "legalDesc", "acreage": "landAcres",
               "land_use": "landUseDsc", "market": "apprValTot", "taxable_value": "asedValTot"},
    licence="State of Colorado (OIT GIS): data modified from its original source; no warranty; resale of the data "
            "is forbidden by the source. Displayed per the owner's publication decision of 2026-09-30.",
    publication_status="APPROVED", county_field="countyName", centroid=True, columns_verified=True,
    batch_size=25,   # 2026-10-27: two identifier attributes double the where clause; a GET past ~2 KB answers 404
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
               "legal_desc": "legal_description",
               # Thin-states sprint (2026-10-27), from the dataset's own column
               # definitions (data.brla.gov/api/views/ei2c-krsr.json, read live):
               # physical_address "Physical address of the tax parcel" (never the
               # owner_address columns); sum_improvement_value "Improvement value
               # sum of the tax parcel".
               "address": "physical_address", "improvement_value": "sum_improvement_value"},
    no_value_patterns={"address": (r"[^0-9]*$",)},
    # 2026-10-27: no EBR dataset publishes a parcel area (the Lot / Lot Profile
    # / Property Information datasets' area_meas_acres is keyed on a planning
    # lot_id, never the assessment number; the roll's `units` counts
    # structures). This dataset's the_geom is "Shape geometry of the tax
    # parcel" (column definition, read live): the lot size is that polygon's
    # own area, labelled as derived (parcels.DERIVED_AREA_NOTE).
    derived_lot_area=True, geometry_field="the_geom",
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
    field_map={"land_use": "structure_use", "taxable_value": "taxpayer_val", "legal_desc": "legal_description",
               # 2026-10-27: parcel_address "The physical or situs address of the
               # tax parcel" (column definition read live); fill-blank, after the
               # Tax Parcel dataset's physical_address. The taxpayer_addr_*
               # columns are the MAILING address and are never mapped.
               "address": "parcel_address"},
    no_value={"land_use": ("NOT DETERMINED",)},
    # A situs with no house number at all ("<street> RD") is not an address.
    no_value_patterns={"address": (r"[^0-9]*$",)},
    provenance_attrs=("tax_year", "vacant_lot_yn", "assessment_status"),
    latest_field="tax_year", latest_min=2024, value_year_field="tax_year",
    # STRUCTURE USE is filled on every matched record 2015-2023 and blank on
    # every 2024 / 2025 record (per-year fill, run 36942777361): land use comes
    # from tax year 2023, dated as such in its provenance.
    # PARCEL ADDRESS likewise (2026-10-27, per-year counts read live): 370,144
    # of 370,144 roll records carry it in tax year 2023, 3 of 373,713 in 2024
    # and 3 of 375,635 in 2025; among adjudicated records of 2023, 3,930 read
    # "N/A" (no value - SENTINEL_TEXT) and the rest a situs address.
    column_year_floor={"land_use": 2023, "address": 2023},
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
# Owner's decision of 2026-10-25 (data-enrichment sprint): the five county
# parcel layers below are public records, collected to fill gaps on records
# the product already holds and to demonstrate coverage; nothing is sold
# until legal review. None publishes a licence, so each runs on an
# INTERNAL_RISK_ACCEPTANCE in data/source_permissions.csv (never permission),
# the same footing as co_oit_public_parcels. Every layer's fields were read
# live from the development sandbox on 2026-10-25, and a sample of the
# held records' own parcel numbers was matched exactly (counts in `notes`).
# Matching is the factory's deterministic rule: one feature for the row's own
# identifier, or nothing; a zero / blank value is never stored.
# ---------------------------------------------------------------------------

# Missouri - City of St. Louis Assessor "Assessor_Public_Parcels" layer 11
# ("Parcels", 134,336 features). ParcelId is the same 11-digit number the LRA
# inventory CSV publishes (20 of 20 sampled LRA parcels matched exactly).
# Supersedes the earlier, never-verified GIS.ASR.PARCELS configuration.
MO_STL_PARCELS = register(ParcelSourceConfig(
    source_id="mo_stl_parcels_coordinates", state="MO",
    agency="City of St. Louis Assessor (parcel GIS)",
    dataset="Assessor_Public_Parcels MapServer layer 11 (Parcels)",
    landing_url="https://www.stlouis-mo.gov/data/parcels.cfm",
    layer_url="https://maps8.stlouis-mo.gov/arcgis/rest/services/ASSESSOR/Assessor_Public_Parcels/MapServer/11",
    id_field="ParcelId", id_rule="exact",
    field_map={"assessed": "AsdTotal", "land_value": "AprLand", "year_built": "FirstYearBuilt"},
    licence="No licence or terms published on the layer (copyright and description blank). " + OWNER_2026_10_25,
    publication_status="APPROVED", centroid=True, columns_verified=True, batch_size=100,
    # 2026-10-27: LandArea / SQFT carry no published definition (layer
    # description blank; the Parcels.shp.xml metadata of the city's own
    # PARCELS.zip has empty attribute definitions for both - read live), so no
    # area attribute is mapped. The lot size is the matched parcel polygon's own
    # area, labelled as derived (parcels.DERIVED_AREA_NOTE).
    derived_lot_area=True,
    counties=("St. Louis City",),
    notes="Fields read live 2026-10-25 (maxRecordCount 2,000). Sample of 20 LRA parcels: 20 matched exactly on ParcelId; "
          "AsdTotal / AprLand filled on 16, FirstYearBuilt on 6. Coordinates are the area-weighted centroid of the matched "
          "parcel polygon (outSR 4326). The land-use code (AsrLandUse1) is not mapped: its decode table is not read yet.",
))

# Michigan - City of Detroit Office of the Assessor "Parcels (Current)"
# (parcel_file_current, 377,940 features, updated daily). parcel_id is the
# same string the Detroit Land Bank layers publish, trailing dot included
# (20 of 20 sampled DLBA parcels matched exactly). Land-bank parcels are
# tax-exempt, so their assessed and taxable values are 0 and are never stored.
MI_DETROIT_PARCELS = register(ParcelSourceConfig(
    source_id="mi_detroit_assessor_parcels", state="MI",
    agency="City of Detroit, Office of the Assessor",
    dataset="Parcels (Current) - parcel_file_current FeatureServer layer 0",
    landing_url="https://data.detroitmi.gov/",
    layer_url="https://services2.arcgis.com/qvkbeam7Wirps6zC/ArcGIS/rest/services/parcel_file_current/FeatureServer/0",
    id_field="parcel_id", id_rule="exact",
    field_map={"land_value": "amt_land_value", "prop_type": "property_class_description", "land_use": "use_code_description",
               "acreage": "total_acreage", "year_built": "year_built", "living_area": "total_floor_area",
               "legal_desc": "legal_description"},
    licence="Item licenseInfo blank; copyright 'Office of the Assessor, City of Detroit'. " + OWNER_2026_10_25,
    publication_status="APPROVED", centroid=False, columns_verified=True, batch_size=100,
    counties=("Wayne",),
    notes="Fields read live 2026-10-25 (maxRecordCount 1,000). Sample of 20 DLBA parcels: 20 matched exactly; land value, "
          "class, acreage and legal description filled on 20, use code on 18, year built / floor area on 1 (vacant lots). "
          "Assessed / taxable are 0 on land-bank parcels (exempt) and are not mapped.",
))

# Oklahoma - Oklahoma County GIS Hub "Tax Parcels Public" (TaxParcelsPublics_view).
# `pin` is written dddd-dd-ddd-dddd, the same form as the county-owned list's
# parcel (20 of 20 sampled matched; one pin returned two features, which the
# factory treats as AMBIGUOUS). County-owned parcels carry no value (exempt).
OK_OKLAHOMA_COUNTY_PARCELS = register(ParcelSourceConfig(
    source_id="ok_oklahoma_county_parcels", state="OK",
    agency="Oklahoma County (GIS Hub, Assessor tax parcels)",
    dataset="Tax Parcels Public - TaxParcelsPublics_view FeatureServer layer 0",
    landing_url="https://services8.arcgis.com/euhkr1dAJeQBIjV0/arcgis/rest/services/TaxParcelsPublics_view/FeatureServer",
    layer_url="https://services8.arcgis.com/euhkr1dAJeQBIjV0/arcgis/rest/services/TaxParcelsPublics_view/FeatureServer/0",
    id_field="pin", id_rule="exact",
    field_map={"acreage": "acres", "legal_desc": "legal",
               # 2026-10-27: `location` is the parcel's situs (the layer keeps
               # the owner's mailing address in mailingaddress1 / city / state,
               # never mapped). Among county-owned parcels the layer writes
               # "0 UNKNOWN <city>" where no street address exists (value-free
               # shape count: 349 of 586 sampled) - that is no address.
               "address": "location"},
    no_value_patterns={"address": (r"0+\s+UNKNOWN\b",)},
    licence="Hub catalog licence field blank; no terms found. " + OWNER_2026_10_25,
    publication_status="APPROVED", centroid=True, columns_verified=True, batch_size=25,
    counties=("Oklahoma",),
    notes="Fields read live 2026-10-25. Sample of 20 county-owned parcels: 20 matched on pin (21 features: one pin twice); "
          "acres filled on 20, legal on 21; market / assessed / taxable are 0 on county-owned parcels and are not mapped.",
))

# Pennsylvania - Fayette County parcels on PASDA (Penn State), "Fayette County
# Parcels region 202602". TAXIDNUM (NN-NN-NNNN) matched 12 of 20 sampled
# repository parcels exactly; the others carry a unit suffix (-77, -98, ...)
# the layer does not publish and stay unmatched - never trimmed to fit.
PA_FAYETTE_PARCELS = register(ParcelSourceConfig(
    source_id="pa_fayette_pasda_parcels", state="PA",
    agency="Fayette County, PA (published on PASDA, Penn State)",
    dataset="Fayette County Parcels region 202602 (PASDA FayetteCounty MapServer layer 2)",
    landing_url="https://www.pasda.psu.edu/download/fayettecounty",
    layer_url="https://mapservices.pasda.psu.edu/server/rest/services/pasda/FayetteCounty/MapServer/2",
    id_field="TAXIDNUM", id_rule="exact", field_map={},
    licence="PASDA metadata: access constraints 'None', use constraints 'None'; originator Fayette County, PA. " + OWNER_2026_10_25,
    publication_status="APPROVED", centroid=True, columns_verified=True, batch_size=25,
    counties=("Fayette",),
    notes="Fields read live 2026-10-25 (TAXIDNUM, TAXSHORT, geometry only). Sample of 20 repository parcels: 12 matched exactly. "
          "Coordinates only.",
))

# South Carolina - Horry County open-data "Parcels" (gisportal.horrycounty.org
# OpenData). PIN is numeric on the layer and the FLC list's 11-digit PIN
# (12 of 20 sampled matched; the unmatched ones are 998... mobile-home
# accounts with no parcel polygon).
SC_HORRY_PARCELS = register(ParcelSourceConfig(
    source_id="sc_horry_county_parcels", state="SC",
    agency="Horry County, SC (GIS open data)",
    dataset="OpenData Parcels FeatureServer layer 0",
    landing_url="https://gisportal.horrycounty.org/server/rest/services/OpenData/Parcels/FeatureServer",
    layer_url="https://gisportal.horrycounty.org/server/rest/services/OpenData/Parcels/FeatureServer/0",
    id_field="PIN", id_rule="numeric", id_query="number", field_map={},
    licence="Licence field and copyright blank; no terms found. " + OWNER_2026_10_25,
    publication_status="APPROVED", centroid=True, columns_verified=True, batch_size=100,
    counties=("Horry",),
    notes="Fields read live 2026-10-25 (PIN, TMS, geometry). Sample of 20 FLC parcels: 12 matched; the rest are 998... "
          "mobile-home accounts with no polygon. Coordinates only.",
))


# ---------------------------------------------------------------------------
# Thin-states sprint (2026-10-27; docs/enrich-thin-states-2026-10-27.md).
# The owner's request "enrich every property" under the standing decisions of
# 2026-10-25 / 2026-10-26 (collect every source now, legal review to follow).
# Each layer below is the county's OWN assessor / GIS publication, matched on
# the row's own identifier only (never an address, a name or a location),
# with every column mapped from the layer's own field names / definitions; a
# zero / blank / sentinel is never stored. Layers that publish no licence run
# on an INTERNAL_RISK_ACCEPTANCE permission record (never permission);
# Douglas County's layers carry the county's own CC BY-SA 4.0 licence.
# ---------------------------------------------------------------------------
OWNER_2026_10_27 = ("Owner's request 2026-10-27 ('enrich every property') under the standing decisions of 2026-10-25 / "
                    "2026-10-26: a public-record layer collected to fill gaps on records the product already holds; legal "
                    "review to follow; nothing sold until then.")

# South Carolina - Horry County's public assessor parcel layer (horrycounty.org
# gispublic, Public/HorryCountyGIS MapServer layer 24 "Parcels", 274,725
# features): the Assessor's acreage, legal description and assessed / market /
# taxable values on the parcel polygon, keyed on the same numeric PIN as the
# open-data parcel layer above (which keeps the coordinates; the two layers
# write different columns). LandUseCode is a bare numeric code with no decode
# table published on the layer - not mapped. Owner / mailing fields never are.
SC_HORRY_ASSESSOR = register(ParcelSourceConfig(
    source_id="sc_horry_assessor_parcels", state="SC",
    agency="Horry County, SC (Assessor parcel data on the county's public GIS)",
    dataset="Public/HorryCountyGIS MapServer layer 24 (Parcels)",
    landing_url="https://www.horrycounty.org/gispublic/rest/services/Public/HorryCountyGIS/MapServer",
    layer_url="https://www.horrycounty.org/gispublic/rest/services/Public/HorryCountyGIS/MapServer/24",
    id_field="PIN", id_rule="numeric", id_query="number",
    field_map={"acreage": "Acreage", "legal_desc": "LegalDescr", "assessed": "AssessedProp", "market": "MarketProp",
               "land_value": "MarketLand", "improvement_value": "MarketImprv", "taxable_value": "TaxableProp"},
    licence="Layer copyright blank; no licence or terms published on the service. " + OWNER_2026_10_27,
    publication_status="APPROVED", centroid=False, columns_verified=True, batch_size=100,
    counties=("Horry",),
    notes="Fields read live 2026-10-27 (maxRecordCount 2,000); sample of 300: Acreage 276, LegalDescr 299, AssessedProp 295, "
          "MarketProp 298, MarketLand 298, MarketImprv 147, TaxableProp 298 filled; PIN 11 digits (as the FLC list's PIN).",
))

# South Carolina - Horry County open-data "AddressPoints" (246,621 points):
# the county's situs address points, each carrying the PIN of its parcel.
# address <- ADDRESS (house number + street). A PIN with two or more address
# points (a multi-unit parcel) is AMBIGUOUS and gets no address.
SC_HORRY_ADDRESSES = register(ParcelSourceConfig(
    source_id="sc_horry_address_points", state="SC",
    agency="Horry County, SC (GIS open data)",
    dataset="OpenData AddressPoints FeatureServer layer 0",
    landing_url="https://gisportal.horrycounty.org/server/rest/services/OpenData/AddressPoints/FeatureServer",
    layer_url="https://gisportal.horrycounty.org/server/rest/services/OpenData/AddressPoints/FeatureServer/0",
    id_field="PIN", id_rule="numeric", id_query="number",
    field_map={"address": "ADDRESS"},
    licence="Licence field and copyright blank; no terms found. " + OWNER_2026_10_27,
    publication_status="APPROVED", centroid=False, columns_verified=True, batch_size=100,
    counties=("Horry",),
    notes="Fields read live 2026-10-27; sample of 300: PIN, ADDRESS, STREETNAME, StreetNum, CITY filled on 300, UNIT on 10.",
))

# Colorado - Douglas County open data (the same service and CC BY-SA 4.0
# licence as the county-held liens list co_douglas_county_held_liens):
# "Property Location Data" (layer 5, 169,711 records, "Full legal address
# description of parcels within Douglas County") and "Property Improvements
# Data" (layer 8, 151,462 records, "Property improvements data sourced from
# Assessor records"). ACCOUNT_NO (A9999999) is the account the liens list
# publishes as account_id. The situs address is published in parts (house
# number, direction, street, type, unit) and joined as published - no house
# number, no address. Improvements are per BUILDING: an account with two or
# more buildings is AMBIGUOUS and gets no year built.
DOUGLAS_CO_LICENCE = ("Douglas County, Colorado open data - CC BY-SA 4.0 (item licence: 'This data is licensed by Creative "
                      "Commons 4.0 ... even commercially'); attribution: Douglas County, Colorado.")
CO_DOUGLAS_LOCATIONS = register(ParcelSourceConfig(
    source_id="co_douglas_property_locations", state="CO",
    agency="Douglas County, Colorado (Assessor open data)",
    dataset="Property Location Data (OpenData FeatureServer layer 5)",
    landing_url="https://www.arcgis.com/home/item.html?id=b894617bf058491d9a3126204a0d435a",
    layer_url="https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest/services/OpenData/FeatureServer/5",
    id_field="ACCOUNT_NO", id_rule="alnum", field_map={"acreage": "TOTAL_NET_ACRES", "legal_desc": "LEGAL_DESCR"},
    composite_map={"address": (("ADDRESS_NUMBER", ""), ("PRE_DIRECTION_CODE", ""), ("STREET_NAME", ""),
                               ("STREET_TYPE_CODE", ""), ("UNIT_NO", "#"))},
    licence=DOUGLAS_CO_LICENCE,
    publication_status="APPROVED", centroid=False, columns_verified=True, batch_size=100,
    counties=("Douglas",),
    notes="Fields read live 2026-10-27; sample of 300: ACCOUNT_NO 300 (A9999999), ADDRESS_NUMBER 289, STREET_NAME 289, "
          "STREET_TYPE_CODE 285, UNIT_NO 66, LEGAL_DESCR 300, TOTAL_NET_ACRES 171.",
))
CO_DOUGLAS_IMPROVEMENTS = register(ParcelSourceConfig(
    source_id="co_douglas_property_improvements", state="CO",
    agency="Douglas County, Colorado (Assessor open data)",
    dataset="Property Improvements Data (OpenData FeatureServer layer 8)",
    landing_url="https://www.arcgis.com/home/item.html?id=59223a6a14b24022a3831e4ea9913c5e",
    layer_url="https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest/services/OpenData/FeatureServer/8",
    id_field="ACCOUNT_NO", id_rule="alnum", field_map={"year_built": "BUILT_YEAR"},
    licence=DOUGLAS_CO_LICENCE,
    publication_status="APPROVED", centroid=False, columns_verified=True, batch_size=100,
    counties=("Douglas",),
    notes="Fields read live 2026-10-27; sample of 300: BUILT_YEAR 300 (9999). The square-footage columns (IMPROVEMENT_SF, "
          "BUILT_AS_SF) carry no published definition and are not mapped.",
))


# ---------------------------------------------------------------------------
# Thin-fields sprint (2026-10-27; docs/enrich-thin-fields-2026-10-27.md).
# Same footing as the thin-states layers above: the county's / city's own
# publication, matched on the row's own identifier only, interim
# INTERNAL_RISK_ACCEPTANCE permission records (never permission).
# ---------------------------------------------------------------------------
OWNER_2026_10_27_FIELDS = ("Owner's direction 2026-10-27 ('fill the measured gaps') under the standing decisions of "
                           "2026-10-25 / 2026-10-26: a public-record layer collected to fill gaps on records the product "
                           "already holds; legal review to follow; nothing sold until then.")

# Oklahoma - City of Oklahoma City "Oklahoma Government Owned Properties"
# (City of OKC GIS on ArcGIS Online, item 45bc4f81e0de464e99ed1ab41a7b0467,
# "Parcels in the Tri-County area owned by the city, the county, and the
# state", 6,100 parcels, data last edited 2023-12-01). `Pin` is the county
# assessor's 13-digit PIN written without its dashes - the county-owned list's
# parcel (dddd-dd-ddd-dddd) under the 'digits' rule: 155 of 195 list parcels
# matched exactly one feature, 3 AMBIGUOUS (read live 2026-10-27). CLUCat is
# the city's land-use category for the parcel ('Undeveloped' on 163 of the 164
# matched features, 'Unspecified' on 1 - never stored). The city's address is
# the county's "0 UNKNOWN ..." situs on all but one matched parcel and is not
# mapped (the county layer already maps the situs); Gross_SqFt reads the
# placeholder 1000 on 74 of 164 vacant parcels and is not mapped; values are
# 0 (exempt). A 2023 snapshot: fill-blank only, the category dated by the
# layer's own edit date in `notes`.
OK_OKC_GOV_OWNED = register(ParcelSourceConfig(
    source_id="ok_okc_government_owned_parcels", state="OK",
    agency="City of Oklahoma City (GIS)",
    dataset="Oklahoma Government Owned Properties (Government_Owned_Properties FeatureServer layer 0)",
    landing_url="https://www.arcgis.com/home/item.html?id=45bc4f81e0de464e99ed1ab41a7b0467",
    layer_url="https://services5.arcgis.com/2mOVdIcRtNH2JsSF/arcgis/rest/services/Government_Owned_Properties/FeatureServer/0",
    id_field="Pin", id_rule="digits", id_query="normalized",
    field_map={"land_use": "CLUCat"},
    no_value={"land_use": ("Unspecified",)},
    provenance_attrs=("CLUCat", "Account_Type"),
    licence="Item licenseInfo and accessInformation blank; no terms found. " + OWNER_2026_10_27_FIELDS,
    publication_status="APPROVED", centroid=False, columns_verified=True, fill_blank_only=True, batch_size=50,
    counties=("Oklahoma",),
    notes="Fields read live 2026-10-27 (maxRecordCount 2,000; editingInfo dataLastEditDate 2023-12-01). Match of the 195 "
          "county-owned list parcels: 155 exactly one feature, 3 ambiguous, 37 absent.",
))

# South Carolina - Oconee County GIS "OconeeCounty_Parcel_Jan2026" (the
# county's parcel layer on ArcGIS Online, owner OCSCGIS, data edited
# 2026-01-14, maxRecordCount 2,000). TMS_NUMBER is written 999-99-99-999(9),
# exactly as the county's delinquent tax sale list publishes the parcel: all
# 560 list parcels matched one feature each (read live 2026-10-27).
# TMS_ACRES (the tax map's acreage; filled on 272 of the 560) -> acreage.
# GIS_ACRES (a GIS computation) and the text TMS_ACREAG are not mapped;
# PROP_CLASS reads 0 on every sampled feature and is not mapped. No address,
# owner or value attributes are published on the layer. Coordinates: the
# matched parcel polygon's own centroid.
SC_OCONEE_PARCELS = register(ParcelSourceConfig(
    source_id="sc_oconee_county_parcels", state="SC",
    agency="Oconee County, SC (GIS)",
    dataset="OconeeCounty_Parcel_Jan2026 FeatureServer layer 0",
    landing_url="https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/OconeeCounty_Parcel_Jan2026/FeatureServer",
    layer_url="https://services1.arcgis.com/UOvRn2Rvzysthh3i/arcgis/rest/services/OconeeCounty_Parcel_Jan2026/FeatureServer/0",
    id_field="TMS_NUMBER", id_rule="exact",
    field_map={"acreage": "TMS_ACRES"},
    licence="Layer copyright and description blank; no licence or terms found. " + OWNER_2026_10_27_FIELDS,
    publication_status="APPROVED", centroid=True, columns_verified=True, batch_size=50,   # 100 ids: a ~2.4 KB GET answers 404
    counties=("Oconee",),
    notes="Fields read live 2026-10-27 (data edited 2026-01-14). All 560 Oconee tax sale parcels matched exactly one "
          "feature; TMS_ACRES filled on 272.",
))


# ---------------------------------------------------------------------------
# Coordinates for MI / PA / OK records left without a point (2026-10-28,
# docs/coordinates-mi-pa-ok-2026-10-28.md). Measured live, read-only.
#
# Michigan - Wayne County GIS (ArcGIS Online organization "Wayne County",
# urlKey "wayne", the county's own GIS program) "Parcels_AssessmentData"
# (layer ParcelsFINAL5, 812,735 parcel polygons, public, data edited
# 2026-10-26). `pnum` is the parcel number exactly as the Wayne County Land
# Bank list publishes it: 14 digits for the out-county municipalities
# (Romulus, Redford, Inkster, Taylor, ...) and the City of Detroit's own
# "99999999." form, trailing dot included. Read live 2026-10-28 for the 153
# land-bank rows without a point: 148 identifiers present, 146 exactly one
# polygon, 2 several different polygons (AMBIGUOUS - never written), 5 absent.
# pnum2 equals pnum on every hit; apn2 is blank. The City of Detroit layer
# (mi_detroit_assessor_parcels) is not a coordinate source (centroid=False) and
# covers only Detroit, which is why these rows never got a point.
#
# Scoped to the land bank's rows (row_source_ids): the Detroit Land Bank rows
# carry the land bank's own points and are never swept. Coordinates only -
# Address / Acerage / PropertyClass are published but the Detroit layer
# already fills acreage / class for Wayne, and this sprint adds no field.
MI_WAYNE_COUNTY_PARCELS = register(ParcelSourceConfig(
    source_id="mi_wayne_county_parcels", state="MI",
    agency="Wayne County, Michigan (County GIS)",
    dataset="Parcels_AssessmentData FeatureServer layer 0 (ParcelsFINAL5)",
    landing_url="https://services1.arcgis.com/b6rkZNtCd6Mx2gvB/ArcGIS/rest/services/Parcels_AssessmentData/FeatureServer",
    layer_url="https://services1.arcgis.com/b6rkZNtCd6Mx2gvB/ArcGIS/rest/services/Parcels_AssessmentData/FeatureServer/0",
    id_field="pnum", id_rule="exact", field_map={},
    licence="Item licenseInfo, accessInformation and description blank; no licence or terms found. " + OWNER_2026_10_27_FIELDS,
    publication_status="APPROVED", centroid=True, columns_verified=True, batch_size=50,
    counties=("Wayne",),
    row_source_ids=("mi_wayne_county_landbank",),
    notes="Fields read live 2026-10-28 (maxRecordCount 2,000; data edited 2026-10-26). The 153 Wayne County Land Bank "
          "rows without a point: 146 matched exactly one polygon on pnum, 2 ambiguous, 5 absent. Coordinates only.",
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
