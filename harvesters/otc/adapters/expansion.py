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
from .sc_flc import GEORGETOWN as SC_GEORGETOWN_FLC   # Georgetown SC FLC list (PR #69)
from .tabular import ColumnMap, TabularConfig

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


HELD_AVAILABLE = ("AVAILABLE source read live; no reuse licence or owner decision yet: collected and synced for "
                  "development, labelled UNREVIEWED; not customer-published until an admin review approves it.")
PUBLICATION = {
    "mi_eaton_treasurer_sale": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "mi_lenawee_tax_sale": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "wy_albany_tax_sale": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "sc_york_tax_sale": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "co_morgan_county_held_certificates": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "wi_green_tax_deed_sales": ("APPROVED", OWNER_APPROVED_2026_09_30),
    "co_douglas_county_held_liens": ("APPROVED", DOUGLAS_CC_BY_SA),
    "co_douglas_tax_sale_list": ("APPROVED", DOUGLAS_CC_BY_SA),
    "co_morgan_treasurer_deed_auctions": ("UNREVIEWED", UNREVIEWED_NO_LICENCE),
    "wi_dane_tax_deed_auction": ("UNREVIEWED", UNREVIEWED_NO_LICENCE),
    "sc_oconee_tax_sale_list": ("UNREVIEWED", UNREVIEWED_NO_LICENCE),
    "mi_detroit_landbank_lots": ("UNREVIEWED", HELD_AVAILABLE),
    "mi_detroit_landbank_programs": ("UNREVIEWED", HELD_AVAILABLE),
    "mi_oceana_landbank": ("UNREVIEWED", HELD_AVAILABLE),
    "sc_horry_forfeited_land": ("UNREVIEWED", HELD_AVAILABLE),
    "sc_georgetown_forfeited_land": ("UNREVIEWED", HELD_AVAILABLE),
}


@dataclass(frozen=True)
class ExpansionSource:
    kind: str                     # "arcgis" | "html_table" | "xlsx_flc_lists" | "sc_flc_pdf"
    config: object
    url: str                      # what is fetched


SOURCES: dict[str, tuple[ExpansionSource, ...]] = {
    "MI": (ExpansionSource("arcgis", MI_EATON, MI_EATON.layer_url), ExpansionSource("arcgis", MI_LENAWEE, MI_LENAWEE.layer_url),
           ExpansionSource("arcgis", MI_DETROIT_LANDBANK_LOTS, MI_DETROIT_LANDBANK_LOTS.layer_url),
           ExpansionSource("arcgis", MI_DETROIT_LANDBANK_PROGRAMS, MI_DETROIT_LANDBANK_PROGRAMS.layer_url),
           ExpansionSource("html_table", MI_OCEANA_LANDBANK, MI_OCEANA_LANDBANK.list_url)),
    "WY": (ExpansionSource("arcgis", WY_ALBANY, WY_ALBANY.layer_url),),
    "SC": (ExpansionSource("arcgis", SC_YORK, SC_YORK.layer_url),
           ExpansionSource("html_table", SC_OCONEE, SC_OCONEE.list_url),
           ExpansionSource("xlsx_flc_lists", SC_HORRY_FLC, SC_HORRY_FLC.list_url),
           ExpansionSource("sc_flc_pdf", SC_GEORGETOWN_FLC, SC_GEORGETOWN_FLC.document_url)),
    "CO": (ExpansionSource("html_table", CO_MORGAN, CO_MORGAN.list_url),
           ExpansionSource("arcgis", CO_DOUGLAS_COUNTY_HELD_LIENS, CO_DOUGLAS_COUNTY_HELD_LIENS.layer_url),
           ExpansionSource("arcgis", CO_DOUGLAS_TAX_SALE_LIST, CO_DOUGLAS_TAX_SALE_LIST.layer_url),
           ExpansionSource("html_table", CO_MORGAN_DEED_AUCTIONS, CO_MORGAN_DEED_AUCTIONS.list_url)),
    "WI": (ExpansionSource("html_table", WI_GREEN_CURRENT, WI_GREEN_CURRENT.list_url),
           ExpansionSource("html_table", WI_GREEN_PREVIOUS, WI_GREEN_PREVIOUS.list_url),
           ExpansionSource("html_table", WI_DANE_AVAILABLE, WI_DANE_AVAILABLE.list_url),
           ExpansionSource("html_table", WI_DANE_SOLD, WI_DANE_SOLD.list_url)),
}


AVAILABLE_SPRINT_SOURCE_IDS = frozenset({"mi_detroit_landbank_lots", "mi_detroit_landbank_programs", "mi_oceana_landbank",
                                         "sc_horry_forfeited_land", "sc_georgetown_forfeited_land"})
