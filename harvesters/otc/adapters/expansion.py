"""Six-state expansion (2026-10-01): the live-verified source configurations
for MI, WY, SC, CO and WI - data, not parsers. Every source here runs through
the shared, state-agnostic adapters (arcgis.py for ArcGIS layers, tabular.py
for HTML tables); nothing below is a state-specific parser.

Evidence: every column name below was read from the LIVE source by the manual
evidence job (`job=evidence`, `evidence_scope=expansion`,
scripts/capture_state_sources.py), runs 36778382226 / 36779189506 /
36780071129 / pass 4 (2026-09-30), value-free. The owner approved each
source for publication on 2026-09-30 (docs/six-state-expansion.md) knowing
that none of them carries an explicit reuse licence.

Ledgers (harvesters/ledgers): a county's upcoming-sale list is an AUCTIONS
record (`record_source="auction"`) - including Wyoming's, whose sale sells
tax lien certificates: no certificate exists until the sale, so a pre-sale
parcel is not a LIENS & CERTIFICATES record. Morgan County (CO)'s
county-held certificates ARE certificates (LIENS & CERTIFICATES).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..model import AmountKind, InventoryType, PurchaseUrlKind, SourceAuthority
from .arcgis import ArcGisFieldMap, ArcGisLayerConfig
from .epropertyplus import EppConfig
from .property_page import PropertyPage
from .sc_flc import GEORGETOWN as SC_GEORGETOWN_FLC   # Georgetown SC FLC list (PR #69)
from .tabular import ColumnMap, TabularConfig
from . import tax_sale_info as TSI
from .paged_table import PagedTableConfig

EVIDENCE_RUNS = ("36778382226", "36779189506", "36780071129", "pass-4 2026-09-30")
APPROVAL = "owner publication approval 2026-09-30 (no explicit reuse licence published by the source)"


def _item(item_id: str) -> str:
    return f"https://www.arcgis.com/home/item.html?id={item_id}"


MI_EATON = ArcGisLayerConfig(
    source_id="mi_eaton_treasurer_sale", state="MI", county="Eaton",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    layer_url="https://services2.arcgis.com/c9l1e4fKpsCnqD7H/arcgis/rest/services/For_Sale_2026_view/FeatureServer/0",
    fields=ArcGisFieldMap(case_no="lparcel", parcel="lparcel", address="SITEADDRESS", legal_desc="description",
                          amount="minbid", sold_flag="Sold", land_use="type", acreage="STATEDAREA",
                          taxable_value="CNTTXBLVAL", assessed="SEV_1"),
    amount_kind=AmountKind.OPENING_BID, list_url=_item("5b973732a9e84fdd94fa225f8160650d"), columns_verified=True, centroid=True,
    notes="'Tax parcels for sale in auction by the Eaton County Treasurer following forfeiture and foreclosure' "
          "(item snippet). minbid alias 'Minimum Bid'; Sold alias 'Has Been Sold' (the layer's own flag, kept verbatim); "
          "SEV_1 = State Equalized Value, CNTTXBLVAL = Current Taxable Value.")

MI_LENAWEE = ArcGisLayerConfig(
    source_id="mi_lenawee_tax_sale", state="MI", county="Lenawee",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    layer_url="https://services6.arcgis.com/mjEvhc9AE3ceAXtG/arcgis/rest/services/Tax_Sale_2026_view/FeatureServer/0",
    fields=ArcGisFieldMap(case_no="TAXID", parcel="TAXID", address="PropAdd", legal_desc="TaxDesc", amount="MinBid",
                          acreage="ACREREC"),
    amount_kind=AmountKind.OPENING_BID, list_url=_item("47baabcecf1a4f4e9c47ef15c7c4b7ef"), columns_verified=True, centroid=True,
    notes="'The 2026 Tax Sale Parcels for Lenawee County Michigan'; licence field: 'Public layer for denoting 2026 "
          "Lenawee County Tax Sale parcels.' MinBid = the published minimum bid.")

WY_ALBANY = ArcGisLayerConfig(
    source_id="wy_albany_tax_sale", state="WY", county="Albany",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    layer_url="https://services1.arcgis.com/EmwrhKkmuQhTATzU/arcgis/rest/services/2026TAXSALEPROP_1ST/FeatureServer/0",
    fields=ArcGisFieldMap(case_no="accountno", parcel="pidn", owner_name="name1", address="st_address",
                          legal_desc="LEGALDESCR", amount="TOTAL", acreage="grossacres", market="totalval", land_value="landval",
                          tax_year="taxyear"),
    amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, list_url=_item("239e5314f25f4e9898f9201d36301af9"),
    columns_verified=True, centroid=True,
    # Five-state sprint (evidence 2026-10-01, run 36793062673): the Treasurer's
    # 'Tax Lien Sale' and 'Tax Sale Listings' pages now publish the NEXT sale -
    # "The 2027 Tax Sale will be held on Friday, August 13th, 2027" - and no
    # longer mention 2026; every row of this layer is tax year 2026 (probe,
    # run 36793611223). The 2026 sale is therefore over and no result is
    # published: rows read 'Not published', never 'Listed'.
    superseded="the county's own pages now name the next sale (August 13, 2027); this layer is the 2026 sale's 1st list and "
               "the county publishes no result for it",
    notes="'2026 TAX SALE PROPERTIES 1ST LIST FROM ALBANY COUNTY, WY TREASURER'S OFFICE.' The layer's TOTAL figure "
          "carries no alias saying what it totals, so it is kept as a published amount of UNSPECIFIED kind, never "
          "called a bid. totalval (Total value) is kept as the value on file.")

SC_YORK = ArcGisLayerConfig(
    source_id="sc_york_tax_sale", state="SC", county="York",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    layer_url="https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/Tax_Sale_Properties_2025_View/FeatureServer/0",
    # Field FILL rates read live (evidence_scope=field_fill, 2026-09-30): the view's older
    # attributes (OWNNAME, LOCDESC, TOTALACRES, Latitude/Longitude) are EMPTY; the filled
    # set is the CAMA block below. SOLD ("Hide On Public Site") is a web-display switch,
    # not a sale outcome, and is never read.
    fields=ArcGisFieldMap(case_no="TAXMAPID", parcel="TAXMAPID", owner_name="Owner1", address="PropertyAddress",
                          legal_desc="LegalDescription", land_use="LandUseDesc", acreage="deededacres",
                          market="AprTotVal", land_value="AprLandVal", improvement_value="AprBldgVal",
                          taxable_value="TaxTotVal", assessed="AsdTotVal", tax_year="TAX_YEAR"),
    list_url=_item("0bf91b9d18f14702873af5f3ad870429"), columns_verified=True, centroid=True,
    notes="Item 'Tax Sale Properties 2026 View' (layer named TaxSaleProperties2025_update, edited 2026-09-29). The "
          "layer publishes no bid amount. Values are the layer's own appraisal / taxable / assessed columns; the "
          "coordinates are the centroid of the layer's own parcel polygon.")

CO_MORGAN = TabularConfig(
    source_id="co_morgan_county_held_certificates", state="CO", county="Morgan",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="certificate",
    columns=ColumnMap(case_no=("cert #",), certificate_no=("cert #",), parcel=("acct #",), owner_name=("name",),
                      legal_desc=("legal description",), amount=("purchase amount to*",),
                      eligible_date=("date eligible for auction",)),
    amount_kind=AmountKind.FIXED_PURCHASE_PRICE,
    list_url="https://morgancounty.colorado.gov/county-held-tax-lien-sale-certificates", columns_verified=True,
    notes="'The following Tax Lien Sale Certificates may be purchased* from Morgan County for the amount shown to the "
          "Morgan County Treasurer.' The amount column's header carries the date the amount is good to.")

WI_GREEN_CURRENT = TabularConfig(
    source_id="wi_green_tax_deed_sales", state="WI", county="Green",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    columns=ColumnMap(case_no=("tax parcel number",), parcel=("tax parcel number",), address=("site address",),
                      amount=("minimum bid amount",), sale_date=("sale date",)),
    amount_kind=AmountKind.OPENING_BID, header_forbidden=("sale price",), empty_phrases=("no current sales",),
    list_url="https://www.greencountywi.org/492/Current-Tax-Deed-Sales", columns_verified=True,
    notes="'Current/Upcoming Sales' table; sealed bids to the County Clerk.")

WI_GREEN_PREVIOUS = TabularConfig(
    source_id="wi_green_tax_deed_sales", state="WI", county="Green",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    columns=ColumnMap(case_no=("tax parcel number",), parcel=("tax parcel number",), address=("site address",),
                      amount=("minimum bid amount",), sale_date=("sale date",), result_amount=("sale price",)),
    amount_kind=AmountKind.OPENING_BID, header_required=("sale price",), past_listing=True,
    list_url="https://www.greencountywi.org/492/Current-Tax-Deed-Sales", columns_verified=True,
    notes="'Previous Sales' table: each row is a completed sale with its published Sale Price (a result, as published).")


# ---------------------------------------------------------------------------
# Five-state enrichment sprint (2026-10-01). Read LIVE by the manual
# evidence job, value-free: five_state run 36793062673, pass 2 run
# 36793611223, pass 3 run 36793980491 (docs/five-state-enrichment.md).
# ---------------------------------------------------------------------------
FIVE_STATE_EVIDENCE_RUNS = ("36793062673", "36793611223", "36793980491")
SIX_STATE_SOURCE_IDS = frozenset({"mi_eaton_treasurer_sale", "mi_lenawee_tax_sale", "wy_albany_tax_sale", "sc_york_tax_sale",
                                  "co_morgan_county_held_certificates", "wi_green_tax_deed_sales"})

# Douglas County (CO) Treasurer - "Tax Liens" open-data table: "Listing of all
# current Investor Held and County Held liens" (updated daily). Licence on
# the item itself: "This data is licensed by Creative Commons 4.0:
# https://creativecommons.org/licenses/by-sa/4.0/ You are free to: Share ...
# Adapt ... even commercially"; the county's Open Data Guidelines: "without
# any registration requirement, license requirement or restrictions on
# their use provided that the County may require ... to explicitly identify
# the source". ONLY county-held liens (type 'CHL', lien_type 'County Lien' -
# value counts, pass 3) are a LIENS & CERTIFICATES record: an investor-held
# lien ('L') belongs to its buyer and is not for sale. account_id (A9999999)
# is the assessor account the Colorado statewide parcel layer is matched on.
CO_DOUGLAS_COUNTY_HELD_LIENS = ArcGisLayerConfig(
    source_id="co_douglas_county_held_liens", state="CO", county="Douglas",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="certificate",
    layer_url="https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest/services/OpenData/FeatureServer/2",
    fields=ArcGisFieldMap(case_no="lien_id", certificate_no="lien_id", parcel="account_id", amount="lien_balance",
                          tax_year="lien_year", issued_date="sale_or_purchase_date"),
    where="type = 'CHL'", require=(("type", "CHL"),), amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED,
    list_url=_item("950fd2c3a9bf4e0e92fa4a64f1859fec"), columns_verified=True,
    notes="Item 'Tax Liens' (Douglas County CO open data): 'Principal balances unpaid on tax liens held by tax buyer and for "
          "liens held by the county ... For current payoff amount please call the Douglas County Treasurer's office.' "
          "lien_balance is that principal balance - shown as published, never as a price. Filtered to county-held (type CHL).")

# Douglas County (CO) - "Tax Sale List Locations": "Owner, account and tax
# information for the accounts in the required newspaper advertisement in
# preparation for the annual tax lien sale" (same CC BY-SA 4.0 licence). The
# rows carry Tax_Year; the Treasurer's page: "The 2026 Internet Tax Lien Sale
# will be held Nov 5th, 2026" - the sale of tax year 2025's unpaid taxes. On
# 2026-10-01 every row is Tax_Year 2024 (last year's list, probe): the cycle
# guard reads none of them; the 2026 list flows in once the county posts it
# ("Information regarding an upcoming tax certificate sale auction will be
# available in October"). Address1 / City are the OWNER'S mailing address -
# never mapped to the property address.
CO_DOUGLAS_TAX_SALE_LIST = ArcGisLayerConfig(
    source_id="co_douglas_tax_sale_list", state="CO", county="Douglas",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    layer_url="https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest/services/Tax_Sale_List_Locations/FeatureServer/0",
    fields=ArcGisFieldMap(case_no="Account_No", parcel="Account_No", owner_name="Owner_Name", legal_desc="Property_Description",
                          amount="Total_Due", tax_year="Tax_Year"),
    amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, list_url=_item("87f9905d9faf4ae3a7a385c0707717b5"),
    columns_verified=True, cycle_field="Tax_Year", cycles=(("2025", "2026-11-05"),),
    notes="Total_Due ('Total Due') is the advertised amount; the sale's opening bid is not stated on the layer - kept as a "
          "published amount of unspecified kind. The internet sale is run by a vendor (the county names it); no purchase "
          "link is taken from it.")

# Morgan County (CO) Treasurer - "Treasurer's Deed Option Auctions": pending
# public auctions of Certificates of Option for a Treasurer's Deed (Tax Deed #,
# Auction Date, Property Tax Acct #, Tax Lien Sale Cert #, Property
# Description and Address; 105 rows read). No explicit reuse licence: the
# owner's 2026-09-30 approval covered the county-held certificate page only,
# so this source is UNREVIEWED until an admin review approves it.
CO_MORGAN_DEED_AUCTIONS = TabularConfig(
    source_id="co_morgan_treasurer_deed_auctions", state="CO", county="Morgan",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    columns=ColumnMap(case_no=("tax deed #",), parcel=("property tax acct #",), certificate_no=("tax lien sale cert #",),
                      sale_date=("auction date",), legal_desc=("property description and address",)),
    list_url="https://morgancounty.colorado.gov/treasurers-deed-option-auctions", columns_verified=True,
    notes="'If the Tax Lien Sale Certificate is not redeemed, an auction for an Option for a Treasurer's Deed will be held at "
          "9:30 a.m. on the Tax Deed Auction date' (the page). No minimum bid on the table.")

# Dane County (WI) Treasurer - "Dane County Tax Deed Auction": sealed-bid sale
# of tax-deeded parcels. Two tables with the same columns: tblAuction
# (available: Address, Parcel Number, Bid Due, Minimum Bid, and the row's own
# "Bid Form" link) and tblAuctionSold (the Minimum Bid cell reads
# "$<bid> SOLD - $<price>"). No explicit reuse licence ("Copyright (c) County
# of Dane") - UNREVIEWED until an admin review approves it.
_DANE = dict(source_id="wi_dane_tax_deed_auction", state="WI", county="Dane",
             source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
             columns=ColumnMap(case_no=("parcel number",), parcel=("parcel number",), address=("address",),
                               sale_date=("bid due",), amount=("minimum bid",)),
             amount_kind=AmountKind.OPENING_BID, list_url="https://treasurer.danecounty.gov/taxdeedauction", columns_verified=True)
WI_DANE_AVAILABLE = TabularConfig(**_DANE, table_id="tblAuction", row_links=(("bid form", "bid_form"),),
                                  notes="'Available parcels are listed online ... in chronological order by Bid Due date'; "
                                        "'Bids are awarded ... Only bids at or exceeding the appraised value' (Minimum Bid). "
                                        "sale_date = the Bid Due date; the bid opening is the following day.")
WI_DANE_SOLD = TabularConfig(**_DANE, table_id="tblAuctionSold", amount_sold_pattern=r"^\$?(?P<bid>[\d,]+(?:\.\d+)?)\s+SOLD\s*-\s*\$?(?P<price>[\d,]+(?:\.\d+)?)$",
                             notes="'Once sold, the purchased parcels are shifted to the \"Sold Parcels\" tab': the county's own "
                                   "SOLD wording and price - a published result; no buyer is published or stored.")

# Oconee County (SC) Delinquent Tax - "Delinquent Tax Sale List" (HTML table:
# Item Number, Owner Name, Map Number, Description, Total Tax Due). On
# 2026-10-01 its only row is the county's statement "The 2026 Tax Sale is
# scheduled for Monday, November 9, 2026." (read as the list not yet being
# posted). Map Number is the identity (item numbers restart each year). No
# explicit reuse licence - UNREVIEWED until an admin review approves it.
SC_OCONEE = TabularConfig(
    source_id="sc_oconee_tax_sale_list", state="SC", county="Oconee",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    columns=ColumnMap(case_no=("map number",), parcel=("map number",), owner_name=("owner name",), legal_desc=("description",),
                      amount=("total tax due",)),
    amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, header_required=("map number",),
    empty_patterns=(r"tax sale is scheduled for",),
    list_url="https://oconeesc.com/delinquent-tax/sale-list", columns_verified=True,
    notes="'If there are no bids, the property will be considered purchased by the county's Forfeited Land Commission for the "
          "amount of taxes, penalties, and costs owed' (Tax Sale Information page). Total Tax Due is kept as published.")

# Publication decision per source (the registry's publication_status +
# restrictions, generated into data/county_source_registry.csv). The six
# sources of PR #57 carry the owner's 2026-09-30 decision; a source added in
# this sprint is APPROVED only on an explicit licence the evidence quotes,
# otherwise UNREVIEWED (implemented and verified, never requested or written
# until an admin review approves it - scripts/source_publication.py).
OWNER_APPROVED_2026_09_30 = ("No explicit reuse licence is published by the source; approved for publication by the owner on "
                             "2026-09-30. Show only what the source publishes; no inferred results.")
DOUGLAS_CC_BY_SA = ("Creative Commons Attribution-ShareAlike 4.0 (stated on the dataset item) and the Douglas County Open Data "
                    "Guidelines (no restrictions on use; the source must be identified). Attribute 'Douglas County, Colorado' "
                    "and the licence wherever these rows are shown; adaptations of this data carry the same licence.")
UNREVIEWED_NO_LICENCE = ("Implemented and read live, but the source publishes no reuse licence and no owner decision exists: "
                         "not requested on a schedule and no row is written until an admin review approves it.")
# ---- AVAILABLE implementation sprint (2026-10-02) ---------------------------
# Government-held property the source itself offers for acquisition. Read
# value-free by the evidence job (`evidence_scope=available_sources`, run
# 37038385659; Georgetown: `sc_available`, runs 37033274319 /
# 37035908843 / 37036374756). Every one is UNREVIEWED for customer
# publication: it is collected and synced like any AVAILABLE source, its rows
# carry publication_status UNREVIEWED, admins (and customer preview) see them
# labelled, and customers do not until an admin review approves the source.
AVAILABLE_SPRINT_EVIDENCE_RUNS = ("37038385659",)

# Detroit Land Bank Authority (Wayne County, MI) - "Properties owned by the
# Detroit Land Bank Authority" (56,896 features, edited 2026-10-01). Its own
# inventory status names the lots it offers: "Neighborhood Lot For Sale",
# "Side Lot For Sale", "Oversized Lot For Sale", "Marketed Lot For Sale".
# "DLBA Owned Lot / Structure" (not offered) and marketed STRUCTURES (sold
# through the DLBA's programs, some by auction) are not read from this layer.
DLBA_LOT_STATUSES = ("Neighborhood Lot For Sale", "Side Lot For Sale", "Oversized Lot For Sale", "Marketed Lot For Sale")
# 2026-10-03 (owner decision): the layer's own OFFERED-structure status is also
# read, kept verbatim in inventory_status_raw. It is the only verified structure
# indicator the DLBA publishes, and it feeds the customer-facing Detroit subset
# (harvesters/otc/detroit_subset.py). "DLBA Owned Structure" is ownership, not
# an offer, and is still not read. The registry's notes text for this source is
# left unchanged on purpose (no registry change); docs/detroit-customer-subset.md.
DLBA_STRUCTURE_STATUSES = ("Marketed Structure For Sale",)
MI_DETROIT_LANDBANK_LOTS = ArcGisLayerConfig(
    source_id="mi_detroit_landbank_lots", state="MI", county="Wayne",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE, record_source="laft",
    layer_url="https://services2.arcgis.com/qvkbeam7Wirps6zC/arcgis/rest/services/DLBA_Owned_Properties/FeatureServer/0",
    keyset=True,   # object-id order, never offset pages (2026-10-26: run 374 FAILED on a page shift)
    fields=ArcGisFieldMap(case_no="parcel_id", parcel="parcel_id", address="name", status="inventory_status_socrata",
                          latitude="latitude", longitude="longitude"),
    where="inventory_status_socrata IN (" + ",".join(f"'{s}'" for s in DLBA_LOT_STATUSES + DLBA_STRUCTURE_STATUSES) + ")",
    list_url=_item("848bc665295f4ca9b1e25068ffa88ab0"), columns_verified=True,
    notes="'Properties owned by the Detroit Land Bank Authority' (item snippet). inventory_status_socrata alias 'DLBA "
          "Inventory Status' - only the four lot statuses ending 'For Sale' are read; the status is kept verbatim (a side "
          "lot is offered to an adjacent owner). parcel_id alias 'Parcel Number', name alias 'Address'. No price published.")

# The DLBA's own "Properties for sale ... through the Auction, Own It Now, and
# Renovation programs" layer: the Auction program is an AUCTION, never
# AVAILABLE, so only the other programs are read.
MI_DETROIT_LANDBANK_PROGRAMS = ArcGisLayerConfig(
    source_id="mi_detroit_landbank_programs", state="MI", county="Wayne",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE, record_source="laft",
    layer_url="https://services2.arcgis.com/qvkbeam7Wirps6zC/arcgis/rest/services/DLBA_For_Sale/FeatureServer/0",
    keyset=True,   # object-id order, never offset pages (2026-10-26: run 374 FAILED on a page shift)
    fields=ArcGisFieldMap(case_no="parcel_id", parcel="parcel_id", address="address", status="program",
                          latitude="latitude", longitude="longitude"),
    where="program <> 'Auction'",
    list_url=_item("e0c4f46a09b9405cb18837e66e85c622"), columns_verified=True,
    notes="'Properties for sale by the Detroit Land Bank Authority through the Auction, Own It Now, and Renovation "
          "programs' (item snippet). program alias 'DLBA Program' (Own It Now / Renovation Programs / Economic "
          "Development read; Auction excluded). No price published on the layer.")

# Oceana County (MI) Land Bank Authority - "Current Available Properties"
# table (Parcel ID Number | Property Address), purchase by the Land Bank's
# Application for Proposals form.
MI_OCEANA_LANDBANK = TabularConfig(
    source_id="mi_oceana_landbank", state="MI", county="Oceana",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE, record_source="laft",
    columns=ColumnMap(case_no=("Parcel ID Number",), parcel=("Parcel ID Number",), address=("Property Address",)),
    list_url="https://oceana.mi.us/departments/treasurer/land-bank-authority/",
    purchase_url="https://oceana.mi.us/wp-content/uploads/2022/12/Purchase-Application-Land-Bank.pdf",
    purchase_url_kind=PurchaseUrlKind.APPLICATION_FORM, columns_verified=True,
    header_required=("Parcel ID Number",),
    notes="'Current Available Properties ... owned by the Oceana County Land Bank Authority'; 'If you are interested in "
          "purchasing a property ... please download and complete the Application for Proposals form'. No price per row.")

# Horry County (SC) Forfeited Land Commission - yearly 'FLC List' workbooks
# (PIN | ITEM # | TAXPAYER | DESCRIPTION | ... | MINIMUM BID). The county:
# "Properties owned by the FLC can be sold and deeded after the end of their
# redemption period, and assignments of the bids for those properties can be
# sold during the redemption period ... one year and one day from the date of
# the tax sale". Only a list whose year's redemption period is over is
# AVAILABLE (sc_flc.list_year_past_redemption); the current year's list is an
# assignment list and is not read. TAXPAYER is never read.
SC_HORRY_FLC = TabularConfig(
    source_id="sc_horry_forfeited_land", state="SC", county="Horry",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE, record_source="laft",
    columns=ColumnMap(case_no=("PIN",), parcel=("PIN",), legal_desc=("DESCRIPTION",), amount=("MINIMUM BID",)),
    amount_kind=AmountKind.OPENING_BID,
    list_url="https://horrycountysc.gov/boards-and-commissions/forfeited-land-commission/",
    purchase_url="https://horrycountysc.gov/media/sinbmsz5/horrycountyflcguidelines.pdf",
    purchase_url_kind=PurchaseUrlKind.BID_FORM, columns_verified=True, header_required=("PIN",),
    id_pattern=r"\d{9,11}",
    notes="Yearly FLC List workbooks linked from the program page; PIN = the county's 11-digit parcel number. 'MINIMUM "
          "BID' is the commission's minimum bid. Lists still inside the redemption period are not read. A PIN cell that "
          "is not a 9-11 digit number (a note line, a section word - run 37039824035) is not a property.")


# ---- AVAILABLE expansion: MO / OK / PA / MN (2026-10-04) --------------------
# Read value-free by the AVAILABLE-five evidence passes (capture_state_sources
# --available-five / -2 / -3; runs 37203515518, 37203652975, 37203694092,
# 37203843581). Each source states availability itself; nothing is inferred
# from an auction, a passed date or an unsold outcome. Every one is
# UNREVIEWED: collected for admin use, never customer-published until an
# admin review approves it. Owner / taxpayer columns are never mapped.
AVAILABLE_FIVE_EVIDENCE_RUNS = ("37203515518", "37203652975", "37203694092", "37203843581", "37204541253")

# St. Louis (independent city), MO - Land Reutilization Authority inventory,
# the City's own open-data CSV (nightly; 10,348 rows on 2026-10-04). Its own
# Parcel_Status column: "Available" (9,761) / "Unavailable" (587). Only
# "Available" is read. ParcelId is the City's 11-digit parcel number. No price
# column. "St. Louis City" names the city apart from St. Louis County.
MO_STL_LRA = TabularConfig(
    source_id="mo_stl_lra_inventory", state="MO", county="St. Louis City",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE, record_source="laft",
    columns=ColumnMap(case_no=("ParcelId",), parcel=("ParcelId",), address=("Address",), legal_desc=("LegalDescription",),
                      status=("Parcel_Status",), land_use=("PropertyType",)),
    status_include=("Available",), id_pattern=r"\d{11}", header_required=("ParcelId", "Parcel_Status"),
    list_url="https://www.stlouis-mo.gov/data/datasets/dataset.cfm?id=30",
    document_url="https://static.stlouis-mo.gov/open-data/SLDC/REAL-ESTATE/LRA_INVENTORY.csv", columns_verified=True,
    property_page=PropertyPage(
        template="https://www.stlouis-mo.gov/government/property/city-owned-property-search.cfm?action=detail&parcelId={id}",
        kind=PurchaseUrlKind.OFFER_FORM, id_pattern=r"\d{11}", verified_on="2026-10-26", action_label="Purchase Property",
        pattern_source="the City's Available City-Owned Property Search links each property as "
                       "'?action=detail&parcelId=<ParcelId>' (the 11-digit ParcelId of LRA_INVENTORY.csv)",
        verification="followed anonymously in a headless browser for 4 parcels sampled from the 'LRA Property For Sale' CSV "
                     "(each page showed its parcel number and the page's own 'Purchase Property' button, which links the "
                     "City's 'Purchase City-Owned Property' page); 2 Available parcels absent from that CSV read "
                     "'No records found', so only listed parcels are linked"),
    property_page_listed_url="https://static.stlouis-mo.gov/open-data/SLDC/REAL-ESTATE/LRA_INVENTORY_AVAILABLE.csv",
    property_page_listed_column="ParcelId",
    notes="LRA_INVENTORY.csv (St. Louis Development Corporation open data): Parcel_Status 'Available' rows only; "
          "PropertyType (Lot / Building / Other) kept verbatim as the land use. No price per row. A row on the City's own "
          "'LRA Property For Sale' CSV (LRA_INVENTORY_AVAILABLE.csv, the same dataset page) carries its property page on "
          "the City's search as its purchase URL; offers go to the LRA on its Offer Submission Form (evidence table).")

# Oklahoma County, OK Treasurer - "County Owned Property" list (table#mytable,
# 196 rows): "Once the County owns these properties, they can be purchased by
# the public through a bidding process". Every row is offered. The combined
# address / legal-description column is kept as the legal description (it is
# not reliably a street address). "Suggested Initial Bid Amount" is the
# county's suggestion, not a stated minimum: PUBLISHED_AMOUNT_KIND_UNSPECIFIED.
OK_OKLAHOMA_COUNTY_OWNED = TabularConfig(
    source_id="ok_oklahoma_county_owned", state="OK", county="Oklahoma",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE, record_source="laft",
    columns=ColumnMap(case_no=("Parcel_No",), parcel=("Parcel_No",),
                      legal_desc=("Physical Address Per Assessor/Legal Description",),
                      amount=("Suggested Initial Bid Amount",)),
    amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, table_id="mytable", id_pattern=r"\d{4}-\d{2}-\d{3}-\d{4}",
    list_url="https://docs.oklahomacounty.org/treasurer/CountyOwnedList.asp",
    purchase_url="https://www.oklahomacounty.org/Portals/0/DNNGalleryPro/uploads/2021/4/28/BidForm.pdf",
    purchase_url_kind=PurchaseUrlKind.BID_FORM, columns_verified=True,
    notes="'Once the County owns these properties, they can be purchased by the public through a bidding process' and "
          "'BUYER BEWARE' (the list page). Bids on the Treasurer's bid form (PDF, offline). The suggested initial bid is "
          "kept as published, never called a minimum or a price.")

# Fayette County, PA Tax Claim Bureau - repository list. The Bureau's
# "Repository Sale" page links a new dated file for every update
# ("Repository Update M-D-YYYY", DocumentCenter): the harvester
# (`latest_dated_document`) reads the page, follows the link whose file name
# carries the NEWEST date, and reads that file - an XLSX workbook (its "Active"
# sheet only; the "Completed" sheet is never read) or a text PDF (the 2025
# files). list_as_of is that file name's own date.
# Columns PARCEL | Municipality | OWNER | DESCRIPTION | SALE | Min. Bid |
# Comments (below the workbook's title rows). OWNER is never mapped. A row
# whose Comments read "Bid Received" (any case / spacing) has a pending bid -
# repository sales need the taxing bodies' consent - and is not read as offered.
# History: pinned to the 10-7-2025 PDF (DocumentCenter 9761) from 2026-10-04 to
# 2026-10-26; the page read live 2026-10-26 linked eleven newer files, the
# newest "Repository-Update-10-7-2026" (DocumentCenter 16576, XLSX) - owner
# decision 2026-10-26 to always read the newest.
PA_FAYETTE_PAGE = "https://www.fayettecountypa.org/930/Repository-Sale"
PA_FAYETTE_LATEST_READ = ("2026-10-26", "https://www.fayettecountypa.org/DocumentCenter/View/16576/Repository-Update-10-7-2026")
PA_FAYETTE_REPOSITORY = TabularConfig(
    source_id="pa_fayette_repository", state="PA", county="Fayette",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE, record_source="laft",
    columns=ColumnMap(case_no=("PARCEL",), parcel=("PARCEL",), legal_desc=("DESCRIPTION",), amount=("Min. Bid",),
                      status=("Comments",)),
    amount_kind=AmountKind.OPENING_BID, status_exclude=("Bid Received",),
    # A segment may lead with one letter: the 10-7-2026 workbook lists two
    # parcels shaped 99-99-9999-A9-9 (live read 2026-10-26, shapes only).
    id_pattern=r"\d{2}-\d{2}-\d{4}(?:-[A-Z]?\d{1,4})*",
    list_as_of_pattern=r"Repository-Update-(\d{1,2}-\d{1,2}-\d{4})", list_as_of_formats=("%m-%d-%Y",),
    document_sheet="Active",
    list_url=PA_FAYETTE_PAGE, document_url=PA_FAYETTE_PAGE, columns_verified=True,
    notes="Repository of unsold properties (PA Real Estate Tax Sale Law): sealed bids opened monthly; 'Min. Bid' kept as "
          "the published minimum bid. The Repository Sale page's newest dated 'Repository Update' file is read on every run "
          "(its 'Active' sheet when it is a workbook; 'Completed' is never read); 'Bid Received' rows are pending, not offered. "
          "No purchase form URL verified - the path is the Tax Claim Bureau's bid process.")

# Ramsey County, MN - Tax Forfeited Land public layer (109 points). Its own
# Status: "Available for purchase" (over the counter), "Purchased from
# counter", "Sold at auction", "Approved for auction". Only "Available for
# purchase" is read (server where + local re-check). MinimumBid is kept as the
# published minimum bid. Coordinates are the layer's own point geometry.
MN_RAMSEY_TAX_FORFEIT = ArcGisLayerConfig(
    source_id="mn_ramsey_tax_forfeit", state="MN", county="Ramsey",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE, record_source="laft",
    layer_url="https://maps.co.ramsey.mn.us/arcgis/rest/services/PRR/TaxForfeitLand_PublicData/MapServer/0",
    fields=ArcGisFieldMap(case_no="PIN", parcel="PIN", address="Address", legal_desc="PropertyDescription",
                          amount="MinimumBid", status="Status"),
    where="Status = 'Available for purchase'", require=(("Status", "Available for purchase"),),
    amount_kind=AmountKind.OPENING_BID, centroid=True,
    list_url="https://maps.co.ramsey.mn.us/arcgis/rest/services/PRR/TaxForfeitLand_PublicData/MapServer/0", columns_verified=True,
    notes="Ramsey County tax-forfeited land: 'Available for purchase' = offered over the counter; parcels sold at auction "
          "or purchased from the counter are not read. PIN = the 12-digit county parcel id.")


# ---- Tennessee (2026-10-08): Shelby County Land Bank -----------------------
# The Land Bank's own site (landbank.shelbycountytn.gov) sends buyers to its
# ePropertyPlus portal (public-sctn.epropertyplus.com); the portal's own code
# reads getPublishedProperties. Value-free evidence runs 37855584514,
# 37855783595, 37856005485, 37856189946, 37856396525 (2026-10-08): 12,884
# published parcels, all Shelby; the portal's own fields say which are
# offered - currentStatus 'FOR SALE' with available 'Y' (2,039). Sold,
# pending, donation, redemption, hold and evaluation rows are not read.
# parcelNumber is the county's 14-character parcel id. askingPrice is the
# portal's "Asking Price"; offers go through the Land Bank's Offer to Purchase
# packet, so it is kept as a published amount of UNSPECIFIED kind, never
# called a fixed price or a minimum.
TN_EVIDENCE_RUNS = ("37855584514", "37855783595", "37856005485", "37856189946", "37856396525")
# What the Shelby source IS, and why it is the AVAILABLE ledger (2026-10-10).
# Every answer is from the evidence runs above and docs/tennessee-survey.md;
# a test pins this record against the config, the ledger map and the registry.
TN_SHELBY_SEMANTICS = {
    "publisher": "Shelby County Land Bank (county government) - its own ePropertyPlus tenant, which the Land Bank's "
                 "site (landbank.shelbycountytn.gov) sends buyers to",
    "inventory": "county-owned parcels already taken through delinquent-tax sales (the portal's inventoryType "
                 "'County DTP' on 12,843 of 12,884 rows) - post-sale, government-held inventory",
    "for_sale_means": "the Land Bank currently offers the parcel: currentStatus 'FOR SALE' AND available 'Y' - "
                      "never the status string alone (SALE PENDING rows with available 'Y' are excluded)",
    "transaction": "an offer to the Land Bank on its Offer to Purchase and Sales Agreement packet; askingPrice is a "
                   "published amount of unspecified kind (financial basis OFFER_NEGOTIATED)",
    "auction": "none - the source publishes no sale date, auction or bid event; Shelby's tax-sale auctions are the "
               "Clerk & Master's, a different source (post-sale books only, not built)",
    "ledger": "AVAILABLE",
    "complete_for": "the Land Bank's published inventory: a read is COMPLETE only when every page is read and the "
                    "row count equals the portal's own size",
    "fields": ("currentStatus", "available", "inventoryType", "parcelNumber", "askingPrice"),
}
TN_SHELBY_LANDBANK = EppConfig(
    source_id="tn_shelby_landbank", state="TN", county="Shelby",
    portal="https://public-sctn.epropertyplus.com",
    list_url="https://public-sctn.epropertyplus.com/landmgmtpub/app/base/landing",
    offered=(("currentStatus", "FOR SALE"), ("available", "Y")),
    id_pattern=r"[A-Z0-9]{14}",
    amount_field="askingPrice", amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, amount_label="Asking Price",
    columns_verified=True,
    property_page=PropertyPage(
        template="https://public-sctn.epropertyplus.com/property/{id}",
        kind=PurchaseUrlKind.ONLINE_PURCHASE, id_pattern=r"[A-Z0-9]{14}", verified_on="2026-10-25",
        action_label="Apply For this Property",
        pattern_source="the portal's own code routes a property's details to `/property/${parcelNumber}` "
                       "(the parcelNumber field of getPublishedProperties) and serves that route without a login",
        verification="rendered anonymously in a headless browser for 3 offered parcels sampled from getPublishedProperties "
                     "(each page showed its parcel number and the portal's own 'Apply For this Property' button); the portal's "
                     "public getPublishedPropertyByParcelNumber returned the same parcel, portal id and FOR SALE / Y status "
                     "for 4 more sampled parcels"),
    notes="Shelby County Land Bank inventory (county-owned parcels from delinquent-tax sales, inventory type 'County "
          "DTP'). Offered = the portal's own currentStatus 'FOR SALE' and available 'Y'. Each offered row carries the "
          "portal's own property page (its 'Apply For this Property' action needs a portal account) as its purchase URL.")


# ---- New-sources sprint (2026-10-26): every property, every source ----------
# Owner decision 2026-10-26: "You need to find every fucking property and every
# source, and then we'll work on the legal shit." Terms-of-service / licensing
# risk is accepted by the owner; every source below carries owner-accepted
# INTERIM permission records (data/source_permissions.csv, expiring 2027-04-12)
# and stays UNREVIEWED for customer publication. Hard limits kept: no login, no
# CAPTCHA, no paywall, no IP evasion; honest User-Agent; a polite rate.
# Structure read live 2026-10-26 (field names, counts, status vocabularies -
# docs/new-sources-2026-10-26.md); evidence run ids in NEW_SOURCES_EVIDENCE_RUNS.
NEW_SOURCES_EVIDENCE_RUNS: tuple[str, ...] = ("live structure read 2026-10-26",)
OWNER_INTERIM_2026_10_26 = ("Owner decision 2026-10-26 (collect every property from every source; terms / licensing risk "
                            "accepted, legal review to follow): collected and synced under INTERIM permission records expiring "
                            "2027-04-12, labelled UNREVIEWED; not customer-published until an admin review approves it.")

# ePropertyPlus land-bank tenants (the same public getPublishedProperties
# endpoint as Shelby TN). These tenants publish no currentStatus / available
# flags (every row null) - except Wayne County MI (`available` Y/N) and the
# City of Pittsburgh (custom field s_custom_0010: 'Available for Sale' /
# 'Sale Pending' / 'Not Available'). A tenant without a flag is read on list
# presence: the land bank's published inventory IS its offered list (each
# portal's public landing page is the land bank's "properties for sale").
_EPP_LIST = "/landmgmtpub/app/base/landing"

# Kansas City (MO) Land Bank - 2,577 published rows (2026-10-26), state MO,
# county Jackson (1 row Clay, counted, never re-labelled); inventoryType
# 'Land Bank' / 'KCMHA' (the Homesteading Authority's lots the Land Bank
# sells) kept verbatim; one 'ePP TEST' row is the vendor's test record and is
# excluded. askingPrice filled on every row: a published amount of
# UNSPECIFIED kind (applications / offers to the Land Bank).
MO_KC_LANDBANK = EppConfig(
    source_id="mo_kc_landbank", state="MO", county="Jackson",
    portal="https://public-kclb.epropertyplus.com", list_url="https://public-kclb.epropertyplus.com" + _EPP_LIST,
    offered=(), excluded=(("inventoryType", "ePP TEST"),), county_field="county", county_values=("Jackson",),
    id_pattern=r"[A-Z]{2}\d{16,17}|\d{2}-\d{3}-\d{2}-\d{2}-\d{2}-\d-\d{2}-\d{3}",
    amount_field="askingPrice", amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, amount_label="Asking Price",
    columns_verified=True,
    # 2026-10-27: parcelSquareFootage filled (positive) on 500 of 500 sampled rows.
    lot_sqft_field="parcelSquareFootage",
    notes="Land Bank of Kansas City, Missouri - its ePropertyPlus public portal (public-kclb). Every published row is read "
          "(no availability flag is published; the row's comments, never mapped, say e.g. 'Property available to apply for'). "
          "parcelNumber = the Jackson County parcel id ('JA' + 17 digits). askingPrice kept as published, never called a price.")

# City of Pittsburgh (PA) - city-owned property portal (public-pgh), the
# eProperty Plus database behind the City's 'City-Owned Properties' open data
# (WPRDC). 2,933 rows, all Allegheny; s_custom_0010 'Available for Sale'
# (1,590) is the only offered value read.
PA_PITTSBURGH_CITY_PROPERTY = EppConfig(
    source_id="pa_pittsburgh_city_property", state="PA", county="Allegheny",
    portal="https://public-pgh.epropertyplus.com", list_url="https://public-pgh.epropertyplus.com" + _EPP_LIST,
    offered=(("s_custom_0010", "Available for Sale"),), status_field="s_custom_0010",
    id_pattern=r"\d{4}[A-Z]\d{5}[0-9A-Z]{6}",
    amount_field="askingPrice", amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, amount_label="Asking Price",
    columns_verified=True,
    # 2026-10-27: parcelSquareFootage filled (positive) on 500 of 500 sampled rows.
    lot_sqft_field="parcelSquareFootage",
    notes="City of Pittsburgh city-owned property (eProperty Plus public portal public-pgh; inventoryType 'Public Sale' / "
          "'PLB Transfer' / 'URA Transfer' kept verbatim). Only rows whose s_custom_0010 reads 'Available for Sale' are read; "
          "'Sale Pending' and 'Not Available' are not. parcelNumber = the Allegheny County 16-character lot-and-block id.")

# Wayne County (MI) Land Bank - public-wclb: 841 rows, its own `available`
# flag Y (810) / N (31); county 'WAYNE'. Only available = 'Y' is read.
MI_WAYNE_COUNTY_LANDBANK = EppConfig(
    source_id="mi_wayne_county_landbank", state="MI", county="Wayne",
    portal="https://public-wclb.epropertyplus.com", list_url="https://public-wclb.epropertyplus.com" + _EPP_LIST,
    offered=(("available", "Y"),), county_field="county", county_values=("Wayne",),
    id_pattern=r"\d{8}(?:\d{6}|\.|-\d)?",
    amount_field="askingPrice", amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, amount_label="Asking Price",
    columns_verified=True,
    notes="Wayne County Land Bank Corporation (Michigan) ePropertyPlus public portal (public-wclb); outside Detroit (Highland "
          "Park, Romulus, Redford, ...). Offered = the portal's own available 'Y'. askingPrice kept as published.")

# Saginaw County (MI) Land Bank Authority - public-sclb: 712 rows, all
# 'Residential Vacant', no availability flag, no price on any row.
MI_SAGINAW_LANDBANK = EppConfig(
    source_id="mi_saginaw_landbank", state="MI", county="Saginaw",
    portal="https://public-sclb.epropertyplus.com", list_url="https://public-sclb.epropertyplus.com" + _EPP_LIST,
    offered=(), county_field="county", county_values=("Saginaw",),
    id_pattern=r"\d{2}-\d{2}-\d-\d{1,2}-\d[0-9A-Z]\d{2}-\d{3}",
    columns_verified=True,
    # 2026-10-27, 500 sampled rows: parcelSquareFootage on 60, yearBuilt on 22
    # and structureSquareFootage on 20 (its structures); kept as published.
    lot_sqft_field="parcelSquareFootage", year_built_field="yearBuilt", living_area_field="structureSquareFootage",
    notes="Saginaw County Land Bank Authority ePropertyPlus public portal (public-sclb): every published row read on list "
          "presence (no availability flag published). No price published.")

# Calhoun County (MI) Land Bank Authority - public-cclb: 219 rows (Battle
# Creek / Albion), no availability flag; askingPrice on 215.
MI_CALHOUN_LANDBANK = EppConfig(
    source_id="mi_calhoun_landbank", state="MI", county="Calhoun",
    portal="https://public-cclb.epropertyplus.com", list_url="https://public-cclb.epropertyplus.com" + _EPP_LIST,
    offered=(), county_field="county", county_values=("Calhoun",),
    id_pattern=r"\d{2,4}-\d{2,3}-\d{3}-\d{1,2}",
    amount_field="askingPrice", amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, amount_label="Asking Price",
    columns_verified=True,
    # 2026-10-27, all 219 rows: structureSquareFootage on 7 (its structures); kept as published.
    living_area_field="structureSquareFootage",
    notes="Calhoun County Land Bank Authority (Michigan) ePropertyPlus public portal (public-cclb): every published row read "
          "on list presence; the program (s_custom_0003, e.g. 'Develop This Lot', 'Side Lot') is not mapped.")

NEW_EPP_SOURCES = (MO_KC_LANDBANK, PA_PITTSBURGH_CITY_PROPERTY, MI_WAYNE_COUNTY_LANDBANK, MI_SAGINAW_LANDBANK,
                   MI_CALHOUN_LANDBANK)

# Tax-Sale.info (Title Check, LLC - the auction service Michigan county
# treasurers use for their tax-foreclosure auctions; harvesters/otc/adapters/
# tax_sale_info.py). One configuration per county Tax-Sale.info listed in its
# 2026 season, for each of its two lists:
#  * mi_tax_sale_info_auction - the UPCOMING auction catalogs (AUCTIONS):
#    2026-10-26 the 'No Reserve Auction' of October 30, 2026 listed 46
#    county catalogs, 755 lots; a county with no upcoming catalog reads EMPTY
#    (closed, never sold);
#  * mi_tax_sale_info_surplus - the counties' surplus offers (AVAILABLE):
#    "properties that have gone through the auction process already and failed
#    to sell ... sold on a first come first serve basis" (8 counties, 57 lots).
MI_TSI_AUCTIONS = tuple(TSI.TaxSaleInfoConfig(
    source_id="mi_tax_sale_info_auction", state="MI", county=c, kind="auction", list_url=TSI.AUCTIONS_URL,
    amount_kind=AmountKind.OPENING_BID, columns_verified=True,
    notes="Tax-Sale.info (Title Check, LLC) upcoming Michigan tax-foreclosure auction catalogs: each county catalog's own "
          "'Catalog Spreadsheet' (CSV). Minimum Bid kept as the published opening bid; sale date = the auction entry's date. "
          "Past auction catalogs are never read.") for c in TSI.SEASON_COUNTIES)
# Horry County (SC) Treasurer - Delinquent Tax: "2026 Real Estate Delinquent
# list <M.D.YY>" workbook linked from the Delinquent Tax page (updated as
# taxes are paid; the 2026-10-23 file read 2026-10-26: one sheet, title row
# "2026 REAL ESTATE DELINQUENT TAX SALE LIST AS OF 10/23/2026", columns Item
# Number | PIN | Owner Name | New Owner Name | Description | FLC Bid Amount,
# 2,343 rows). The county's own Tax Sale Information document: the sale is
# December 1, 2026; "The delinquent tax collector will present the opening
# bid, which is made on behalf of the Forfeited Land Commission" = the FLC
# Bid Amount (OPENING_BID). Owner names are never mapped. The mobile-home list
# (personal property) is never read. The harvester follows the newest dated
# 'real-estate-delinquent-list-<MMDDYY>' file on every run.
SC_HORRY_DELINQUENT_PAGE = "https://www.horrycountysc.gov/departments/treasurer/delinquent-tax/"
SC_HORRY_LATEST_READ = ("2026-10-26", "https://www.horrycountysc.gov/media/urdazygf/2026-real-estate-delinquent-list-102326.xlsx")
SC_HORRY_TAX_SALE = TabularConfig(
    source_id="sc_horry_tax_sale", state="SC", county="Horry",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    columns=ColumnMap(case_no=("PIN",), parcel=("PIN",), legal_desc=("Description",), amount=("FLC Bid Amount",)),
    amount_kind=AmountKind.OPENING_BID, id_pattern=r"\d{9,11}", header_required=("PIN", "FLC Bid Amount"),
    list_as_of_pattern=r"real-estate-delinquent-list-(\d{6})", list_as_of_formats=("%m%d%y",),
    document_sheet="*", list_url=SC_HORRY_DELINQUENT_PAGE, document_url=SC_HORRY_DELINQUENT_PAGE, columns_verified=True,
    notes="Horry County delinquent real-estate tax sale list (the Treasurer's newest dated workbook). The sale is the "
          "county's December 1, 2026 open-bid tax sale (2026 Tax Sale Information document); 'Not all properties advertised "
          "will be sold' (redeemed parcels drop off the updated lists). FLC Bid Amount = the opening bid made for the "
          "Forfeited Land Commission (delinquent taxes, penalties, costs and the current year's taxes).")

# Saguache County (CO) - "2026 Tax Sale" layer (San Luis Valley GIS, item
# beee3cca0e0e4c2382cdcf56166531c7; 900 parcels, edited 2026-09-22): the
# county's 2026 tax lien sale list - TaxSale_Number, TaxSale_Parcel,
# TaxSale_Account, Legal_Description, Total_Due, Deeded_Acres. Owner columns
# and the owner's mailing address (City / State / Zip) are never mapped.
CO_SAGUACHE_TAX_SALE = ArcGisLayerConfig(
    source_id="co_saguache_tax_sale", state="CO", county="Saguache",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    layer_url="https://services1.arcgis.com/zH7gQ37AKcpvTX6d/arcgis/rest/services/2026_Tax_Sale/FeatureServer/204",
    fields=ArcGisFieldMap(case_no="TaxSale_Account", parcel="TaxSale_Parcel", legal_desc="Legal_Description",
                          amount="Total_Due", acreage="Deeded_Acres"),
    amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, list_url=_item("beee3cca0e0e4c2382cdcf56166531c7"),
    columns_verified=True, centroid=True,
    notes="Saguache County 2026 tax lien sale list (layer '2026 Tax Sale'). Total_Due is the advertised amount; the opening "
          "bid is not stated on the layer - kept as a published amount of unspecified kind. No sale date on the layer.")

# Wright County (MN) - "Tax Forfeited Parcels" layer (80 parcels, edited
# 2026-07-08): Status 'Open' (38) / 'Closed' (42), 'Auction Starting Price',
# 'Public Surplus Page' (the county's online auctions on PublicSurplus). Only
# Status 'Open' is read; an AUCTIONS record (the county auctions the parcels
# online), amount = the auction starting price (OPENING_BID).
MN_WRIGHT_TAX_FORFEIT = ArcGisLayerConfig(
    source_id="mn_wright_tax_forfeit", state="MN", county="Wright",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    layer_url="https://services2.arcgis.com/CiQCvRGImIxsaFnM/arcgis/rest/services/Tax_Forfeited_Parcels/FeatureServer/0",
    fields=ArcGisFieldMap(case_no="PID", parcel="PID", legal_desc="LEGAL", amount="Auction_Starting_Price", status="Status",
                          market="EMV__Assessment_2025_", acreage="CalculatedArea"),
    where="Status = 'Open'", require=(("Status", "Open"),), amount_kind=AmountKind.OPENING_BID, centroid=True,
    list_url="https://services2.arcgis.com/CiQCvRGImIxsaFnM/arcgis/rest/services/Tax_Forfeited_Parcels/FeatureServer/0",
    columns_verified=True,
    notes="Wright County tax-forfeited parcels: Status 'Open' rows only (the county's own status; 'Closed' is not read). "
          "Auction Starting Price kept as the opening bid; sales run on the county's PublicSurplus page. EMV = the 2025 "
          "estimated market value.")

# Hubbard County (MN) - "TFL Sales" (tax-forfeited land sales; 16 rows, all
# Sales_Status 'OTC' = over the counter). Notes (free text) never mapped.
MN_HUBBARD_TFL_OTC = ArcGisLayerConfig(
    source_id="mn_hubbard_tfl_otc", state="MN", county="Hubbard",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE, record_source="laft",
    layer_url="https://services.arcgis.com/auNjCUvKlkSqV04X/arcgis/rest/services/TFL_Sales_view/FeatureServer/0",
    fields=ArcGisFieldMap(case_no="Parcel_Number", parcel="Parcel_Number", amount="Minimum_Bid", status="Sales_Status"),
    where="Sales_Status = 'OTC'", require=(("Sales_Status", "OTC"),), amount_kind=AmountKind.OPENING_BID, centroid=True,
    list_url="https://services.arcgis.com/auNjCUvKlkSqV04X/arcgis/rest/services/TFL_Sales_view/FeatureServer/0",
    columns_verified=True,
    notes="Hubbard County tax-forfeited land offered over the counter (Sales_Status 'OTC'). Minimum_Bid when filled.")

# City of Saint Paul (MN) HRA - "HRA Properties" layer (HRA-owned parcels;
# 160 rows): Marketing Status '5 - Available on the open market, subject to
# disposition policy' (32) is read; 'Future marketing' and 'Under
# review/pending sale' are not. Ramsey County.
MN_STPAUL_HRA = ArcGisLayerConfig(
    source_id="mn_stpaul_hra_properties", state="MN", county="Ramsey",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE, record_source="laft",
    layer_url="https://services1.arcgis.com/9meaaHE3uiba0zr8/arcgis/rest/services/HRA_Owned_Parcels_for_Sale/FeatureServer/0",
    fields=ArcGisFieldMap(case_no="ParcelID", parcel="ParcelID", address="SiteAddress", legal_desc="Legal_Description",
                          status="Marketing_Status", market="LandHeldForResale_ActVa_EMVTotal"),
    where="Marketing_Status LIKE '5 -%'",
    require=(("Marketing_Status", "5 - Available on the open market, subject to disposition policy"),), centroid=True,
    list_url="https://services1.arcgis.com/9meaaHE3uiba0zr8/arcgis/rest/services/HRA_Owned_Parcels_for_Sale/FeatureServer/0",
    columns_verified=True,
    notes="Saint Paul Housing and Redevelopment Authority land held for resale: Marketing Status '5 - Available on the "
          "open market, subject to disposition policy' only. No price on the layer.")

# Genesee County (MI) Land Bank Authority (Flint) - "Search All Properties"
# (thelandbank.org/find_properties.asp): the Land Bank's inventory as one
# server-side paged table, 25 per page (427 pages, ~10,670 listings,
# 2026-10-26), columns Parcel ID | Address | City | ZIP | Class | Sale Type.
# Sale Type is the Land Bank's own word for how the parcel is sold ('Vacant
# Land', 'Commercial/Industrial', 'Featured Lot for Development', 'Listed with
# Realtor', ...) and is kept verbatim; 'Demolition Program' (a structure in the
# demolition program) is not read as offered.
MI_GENESEE_LANDBANK = PagedTableConfig(
    table=TabularConfig(
        source_id="mi_genesee_landbank", state="MI", county="Genesee",
        source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE, record_source="laft",
        columns=ColumnMap(case_no=("Parcel ID",), parcel=("Parcel ID",), address=("Address",), land_use=("Class",),
                          status=("Sale Type",)),
        status_exclude=("Demolition Program",), id_pattern=r"\d{2}-\d{2}-\d{3}-\d{3}", header_required=("Parcel ID", "Sale Type"),
        list_url="https://www.thelandbank.org/find_properties.asp", columns_verified=True,
        notes="Genesee County Land Bank Authority inventory ('Search All Properties'), every page of the site's own paged "
              "table read in one session. Sale Type kept verbatim; 'Demolition Program' rows are not read. No price per row; "
              "buyers apply on the Land Bank's applications (Lots Available / Residential / Commercial interest forms)."),
    first_url="https://www.thelandbank.org/find_properties.asp?LRCsearch=do",
    next_url="https://www.thelandbank.org/find_properties.asp?LRCsearch=redo",
    # The search form's own Township / City filter (FindTWP), read 2026-10-26: every
    # township and city, with the City of Flint as its four quadrants ('4' = the
    # entire city would overlap them and is not used). The parts must add up to the
    # unfiltered search (checked on every run).
    partition_field="FindTWP",
    partition_values=("01", "02", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "14", "15", "16", "17",
                      "18", "40", "41", "46", "47", "51", "52", "53", "55", "56", "57", "58", "59", "60", "61"),
    # Thin-fields sprint (2026-10-27), read live from the sandbox: every result
    # page states the search's size ("10668 properties found."); the 31 parts
    # added up to exactly the unfiltered 10,668 (the six filters answering HTTP
    # 500 every time held none - the site errors on an empty filter, e.g. every
    # empty FindPropclass x quadrant combination). "LRCpage=" re-renders the
    # session's current page and "LRCpage=prev" steps back one, so a 500 on
    # "next" is recovered in place instead of restarting a 111-page part.
    total_pattern=r"(\d[\d,]*)\s+propert(?:y|ies)\s+found",
    stay_data=(("LRCpage", ""),), prev_data=(("LRCpage", "prev"),))

NEW_TABLE_SOURCES = (SC_HORRY_TAX_SALE, CO_SAGUACHE_TAX_SALE, MN_HUBBARD_TFL_OTC, MN_STPAUL_HRA, MN_WRIGHT_TAX_FORFEIT)
# Wright County (MN) was configured and read live (38 'Open' rows, 2026-10-26)
# but held until the Minnesota page's customer copy (app.js
# EXPANSION_LEDGER_COPY) named it - the state-rules engine fails a tracked
# ledger whose copy denies it. The copy was updated 2026-10-27 (owner
# approval), so it is scheduled with the other new sources.
# Genesee (MI) is configured and its reader tested, but HELD (not scheduled):
# read from the sandbox 2026-10-26, the site answers HTTP 500 at random about
# every 50-60 pages and on six township filters every time; a 500 mid-session
# moves its server-side page cursor, so the largest part (Flint quadrant 40,
# 123 pages) failed on all three attempts. Every failed read is FAILED (nothing
# written, nothing closed), but each try costs ~15 minutes of requests. Next
# step: split the big Flint quadrants further (FindPropclass within FindTWP),
# then add it to SOURCES["MI"], ledgers, permissions and the terms table.
# 2026-10-27 (thin-fields sprint): exact stated totals + in-place session
# recovery; a full live read from the sandbox was COMPLETE (10,668 listings =
# the stated total, 10,190 kept, two random 500s recovered in place, quadrant
# 40 read whole - docs/enrich-thin-fields-2026-10-27.md). Still not scheduled:
# adding it to SOURCES["MI"] lengthens the MI expansion leg by ~15-50 minutes
# of requests (runner vs sandbox latency) and needs the workflow change (owner / workflow
# session), plus ledgers, permissions and the terms table.
HELD_SERVER_ERRORS = (MI_GENESEE_LANDBANK,)

MI_TSI_SURPLUS = tuple(TSI.TaxSaleInfoConfig(
    source_id="mi_tax_sale_info_surplus", state="MI", county=c, kind="surplus", list_url=TSI.SURPLUS_URL,
    inventory_type=InventoryType.POST_SALE, amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, columns_verified=True,
    notes="Tax-Sale.info surplus property catalogs: lots that failed to sell at the county's tax-foreclosure auction, "
          "re-offered first come first served through the site's surplus lot request form. The catalog's 'Minimum Bid' is "
          "kept as a published amount of unspecified kind.") for c in TSI.SURPLUS_COUNTIES)
# Owner decision 2026-10-26: every new source of the new-sources sprint (collected and customer-published).
NEW_SOURCE_IDS = frozenset(c.source_id for c in NEW_EPP_SOURCES + NEW_TABLE_SOURCES + MI_TSI_AUCTIONS + MI_TSI_SURPLUS)


HELD_AVAILABLE = ("AVAILABLE source read live; no reuse licence or owner decision yet: collected and synced for "
                  "development, labelled UNREVIEWED; not customer-published until an admin review approves it.")
# Owner decision, 2026-10-26 (quoted in docs/publish-all-sources.md): every
# collected source is published to customers now; the legal review follows.
# It is the owner's internal risk acceptance, recorded as such everywhere
# (registry restrictions; data/source_permissions.csv INTERIM display / link
# records expiring 2027-04-12) - never as the source's own permission.
OWNER_APPROVED_2026_10_26 = ("Owner approved customer publication 2026-10-26; legal review pending. The source publishes no "
                             "explicit reuse licence; this is the owner's internal risk acceptance, not the source's "
                             "permission. Show only what the source publishes; no inferred results.")
OWNER_APPROVED_2026_10_26_SOURCE_IDS = frozenset({
    "co_morgan_treasurer_deed_auctions", "wi_dane_tax_deed_auction", "sc_oconee_tax_sale_list",
    "mi_detroit_landbank_lots", "mi_detroit_landbank_programs", "mi_oceana_landbank",
    "sc_horry_forfeited_land", "sc_georgetown_forfeited_land", "mo_stl_lra_inventory",
    "ok_oklahoma_county_owned", "pa_fayette_repository", "mn_ramsey_tax_forfeit", "tn_shelby_landbank",
})
PUBLICATION = {
    "mi_eaton_treasurer_sale": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "mi_lenawee_tax_sale": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "wy_albany_tax_sale": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "sc_york_tax_sale": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "co_morgan_county_held_certificates": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "wi_green_tax_deed_sales": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "co_douglas_county_held_liens": ("APPROVED", DOUGLAS_CC_BY_SA),
    "co_douglas_tax_sale_list": ("APPROVED", DOUGLAS_CC_BY_SA),
} | {sid: ("APPROVED", OWNER_APPROVED_2026_10_26) for sid in sorted(OWNER_APPROVED_2026_10_26_SOURCE_IDS)
     # New-sources sprint (owner decision 2026-10-26, "Do not block vendors. Post their shit"): published to
     # customers on the same internal risk acceptance - INTERIM display / link records, legal review pending.
     } | {sid: ("APPROVED", OWNER_APPROVED_2026_10_26) for sid in sorted(NEW_SOURCE_IDS)}


@dataclass(frozen=True)
class ExpansionSource:
    kind: str                     # "arcgis" | "html_table" | "csv" | "pdf_table" | "xlsx_flc_lists" | "sc_flc_pdf" | "epropertyplus"
                                  # | "latest_dated_document"
    config: object
    url: str                      # what is fetched


SOURCES: dict[str, tuple[ExpansionSource, ...]] = {
    "MI": (ExpansionSource("arcgis", MI_EATON, MI_EATON.layer_url), ExpansionSource("arcgis", MI_LENAWEE, MI_LENAWEE.layer_url),
           ExpansionSource("arcgis", MI_DETROIT_LANDBANK_LOTS, MI_DETROIT_LANDBANK_LOTS.layer_url),
           ExpansionSource("arcgis", MI_DETROIT_LANDBANK_PROGRAMS, MI_DETROIT_LANDBANK_PROGRAMS.layer_url),
           ExpansionSource("html_table", MI_OCEANA_LANDBANK, MI_OCEANA_LANDBANK.list_url),
           ExpansionSource("epropertyplus", MI_WAYNE_COUNTY_LANDBANK, MI_WAYNE_COUNTY_LANDBANK.portal),
           ExpansionSource("epropertyplus", MI_SAGINAW_LANDBANK, MI_SAGINAW_LANDBANK.portal),
           ExpansionSource("epropertyplus", MI_CALHOUN_LANDBANK, MI_CALHOUN_LANDBANK.portal),
           *(ExpansionSource("tax_sale_info", c, c.list_url) for c in MI_TSI_AUCTIONS + MI_TSI_SURPLUS)),
    "WY": (ExpansionSource("arcgis", WY_ALBANY, WY_ALBANY.layer_url),),
    "SC": (ExpansionSource("arcgis", SC_YORK, SC_YORK.layer_url),
           ExpansionSource("html_table", SC_OCONEE, SC_OCONEE.list_url),
           ExpansionSource("xlsx_flc_lists", SC_HORRY_FLC, SC_HORRY_FLC.list_url),
           ExpansionSource("sc_flc_pdf", SC_GEORGETOWN_FLC, SC_GEORGETOWN_FLC.document_url),
           ExpansionSource("latest_dated_document", SC_HORRY_TAX_SALE, SC_HORRY_DELINQUENT_PAGE)),
    "CO": (ExpansionSource("html_table", CO_MORGAN, CO_MORGAN.list_url),
           ExpansionSource("arcgis", CO_DOUGLAS_COUNTY_HELD_LIENS, CO_DOUGLAS_COUNTY_HELD_LIENS.layer_url),
           ExpansionSource("arcgis", CO_DOUGLAS_TAX_SALE_LIST, CO_DOUGLAS_TAX_SALE_LIST.layer_url),
           ExpansionSource("html_table", CO_MORGAN_DEED_AUCTIONS, CO_MORGAN_DEED_AUCTIONS.list_url),
           ExpansionSource("arcgis", CO_SAGUACHE_TAX_SALE, CO_SAGUACHE_TAX_SALE.layer_url)),
    "WI": (ExpansionSource("html_table", WI_GREEN_CURRENT, WI_GREEN_CURRENT.list_url),
           ExpansionSource("html_table", WI_GREEN_PREVIOUS, WI_GREEN_PREVIOUS.list_url),
           ExpansionSource("html_table", WI_DANE_AVAILABLE, WI_DANE_AVAILABLE.list_url),
           ExpansionSource("html_table", WI_DANE_SOLD, WI_DANE_SOLD.list_url)),
    "MO": (ExpansionSource("csv", MO_STL_LRA, MO_STL_LRA.document_url),
           ExpansionSource("epropertyplus", MO_KC_LANDBANK, MO_KC_LANDBANK.portal)),
    "OK": (ExpansionSource("html_table", OK_OKLAHOMA_COUNTY_OWNED, OK_OKLAHOMA_COUNTY_OWNED.list_url),),
    "PA": (ExpansionSource("latest_dated_document", PA_FAYETTE_REPOSITORY, PA_FAYETTE_PAGE),
           ExpansionSource("epropertyplus", PA_PITTSBURGH_CITY_PROPERTY, PA_PITTSBURGH_CITY_PROPERTY.portal)),
    "MN": (ExpansionSource("arcgis", MN_RAMSEY_TAX_FORFEIT, MN_RAMSEY_TAX_FORFEIT.layer_url),
           ExpansionSource("arcgis", MN_HUBBARD_TFL_OTC, MN_HUBBARD_TFL_OTC.layer_url),
           ExpansionSource("arcgis", MN_STPAUL_HRA, MN_STPAUL_HRA.layer_url),
           ExpansionSource("arcgis", MN_WRIGHT_TAX_FORFEIT, MN_WRIGHT_TAX_FORFEIT.layer_url)),
    "TN": (ExpansionSource("epropertyplus", TN_SHELBY_LANDBANK, TN_SHELBY_LANDBANK.portal),),
}


AVAILABLE_SPRINT_SOURCE_IDS = frozenset({"mi_detroit_landbank_lots", "mi_detroit_landbank_programs", "mi_oceana_landbank",
                                         "sc_horry_forfeited_land", "sc_georgetown_forfeited_land"})
AVAILABLE_FIVE_SOURCE_IDS = frozenset({"mo_stl_lra_inventory", "ok_oklahoma_county_owned", "pa_fayette_repository",
                                       "mn_ramsey_tax_forfeit"})
TN_SOURCE_IDS = frozenset({"tn_shelby_landbank"})

