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

from ..model import AmountKind, SourceAuthority
from .arcgis import ArcGisFieldMap, ArcGisLayerConfig
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
    amount_kind=AmountKind.OPENING_BID, list_url=_item("5b973732a9e84fdd94fa225f8160650d"), columns_verified=True,
    notes="'Tax parcels for sale in auction by the Eaton County Treasurer following forfeiture and foreclosure' "
          "(item snippet). minbid alias 'Minimum Bid'; Sold alias 'Has Been Sold' (the layer's own flag, kept verbatim); "
          "SEV_1 = State Equalized Value, CNTTXBLVAL = Current Taxable Value.")

MI_LENAWEE = ArcGisLayerConfig(
    source_id="mi_lenawee_tax_sale", state="MI", county="Lenawee",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    layer_url="https://services6.arcgis.com/mjEvhc9AE3ceAXtG/arcgis/rest/services/Tax_Sale_2026_view/FeatureServer/0",
    fields=ArcGisFieldMap(case_no="TAXID", parcel="TAXID", address="PropAdd", legal_desc="TaxDesc", amount="MinBid",
                          acreage="ACREREC"),
    amount_kind=AmountKind.OPENING_BID, list_url=_item("47baabcecf1a4f4e9c47ef15c7c4b7ef"), columns_verified=True,
    notes="'The 2026 Tax Sale Parcels for Lenawee County Michigan'; licence field: 'Public layer for denoting 2026 "
          "Lenawee County Tax Sale parcels.' MinBid = the published minimum bid.")

WY_ALBANY = ArcGisLayerConfig(
    source_id="wy_albany_tax_sale", state="WY", county="Albany",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    layer_url="https://services1.arcgis.com/EmwrhKkmuQhTATzU/arcgis/rest/services/2026TAXSALEPROP_1ST/FeatureServer/0",
    fields=ArcGisFieldMap(case_no="accountno", parcel="pidn", owner_name="name1", address="st_address",
                          legal_desc="LEGALDESCR", amount="TOTAL", acreage="grossacres", market="totalval",
                          tax_year="taxyear"),
    amount_kind=AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED, list_url=_item("239e5314f25f4e9898f9201d36301af9"),
    columns_verified=True,
    notes="'2026 TAX SALE PROPERTIES 1ST LIST FROM ALBANY COUNTY, WY TREASURER'S OFFICE.' The layer's TOTAL figure "
          "carries no alias saying what it totals, so it is kept as a published amount of UNSPECIFIED kind, never "
          "called a bid. totalval (Total value) is kept as the value on file.")

SC_YORK = ArcGisLayerConfig(
    source_id="sc_york_tax_sale", state="SC", county="York",
    source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=None, record_source="auction",
    layer_url="https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/Tax_Sale_Properties_2025_View/FeatureServer/0",
    fields=ArcGisFieldMap(case_no="TAXMAPID", parcel="TAXMAPID", owner_name="OWNNAME", legal_desc="LOCDESC",
                          land_use="PROPTYPE", acreage="TOTALACRES", tax_year="TAXYEAR",
                          latitude="Latitude", longitude="Longitude"),
    list_url=_item("0bf91b9d18f14702873af5f3ad870429"), columns_verified=True,
    notes="Item 'Tax Sale Properties 2026 View' (layer named TaxSaleProperties2025_update, edited 2026-09-29). The "
          "layer publishes no bid amount. Latitude/Longitude are the layer's own attributes.")

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
    amount_kind=AmountKind.OPENING_BID, header_required=("sale price",),
    list_url="https://www.greencountywi.org/492/Current-Tax-Deed-Sales", columns_verified=True,
    notes="'Previous Sales' table: each row is a completed sale with its published Sale Price (a result, as published).")


@dataclass(frozen=True)
class ExpansionSource:
    kind: str                     # "arcgis" | "html_table"
    config: object
    url: str                      # what is fetched


SOURCES: dict[str, tuple[ExpansionSource, ...]] = {
    "MI": (ExpansionSource("arcgis", MI_EATON, MI_EATON.layer_url), ExpansionSource("arcgis", MI_LENAWEE, MI_LENAWEE.layer_url)),
    "WY": (ExpansionSource("arcgis", WY_ALBANY, WY_ALBANY.layer_url),),
    "SC": (ExpansionSource("arcgis", SC_YORK, SC_YORK.layer_url),),
    "CO": (ExpansionSource("html_table", CO_MORGAN, CO_MORGAN.list_url),),
    "WI": (ExpansionSource("html_table", WI_GREEN_CURRENT, WI_GREEN_CURRENT.list_url),
           ExpansionSource("html_table", WI_GREEN_PREVIOUS, WI_GREEN_PREVIOUS.list_url)),
}
