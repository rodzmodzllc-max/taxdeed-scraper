"""Value-free live capture of the candidate (non-production) state sources.

State-expansion sprint (2026-09-30). AL / AR / LA / AZ are registered but
not activated: every fact about their sources is search-index evidence
because the sandbox cannot reach them. This script runs ONLY in the manual
`job=evidence` / `evidence_scope=state_sources` job of harvest-and-sync.yml
and reads, once, the pages / documents the registry rows and the adapters
already name, plus the terms / disclaimer / licence pages those pages link
to (one hop, same site, capped). It writes nothing to any database and
enables nothing.

What it prints is STRUCTURE, never a row value:
  * page title, headings, status, content type, Last-Modified;
  * table header texts and body-row counts; form field names; select
    option texts (digits masked) - the selector vocabulary a parser needs;
  * sentences carrying terms / licence / purchase vocabulary with no
    7+ digit run, every digit masked;
  * for a CSV: the header row, the number of rows read, and per identifier-
    like column the SHAPE of its values (every digit -> 9, every letter ->
    A), never the values;
  * for a Socrata dataset: the dataset's own metadata (name, licence,
    attribution, update timestamps, column names and types).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - the workflow installs it
    BeautifulSoup = None

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "data" / "county_source_registry.csv"
OUT_PATH = REPO / "out" / "public" / "state-source-capture.json"
CANDIDATE_STATES = ("AL", "AR", "LA", "AZ")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}

# Extra pages the adapters' evidence ledgers name (same hosts as the registry rows).
EXTRA_URLS = {
    "AL": ["https://www.revenue.alabama.gov/faqs/where-can-i-find-a-list-of-tax-delinquent-property/",
           "https://www.revenue.alabama.gov/faq-categories/land-sales/"],
    "AR": ["https://cosl.org/Home/Faq", "https://cosl.org/Home/Laws", "https://auction.cosl.org/"],
    "LA": ["https://data.brla.gov/api/views/a4h4-zi7e.json"],
    "AZ": ["https://treasurer.maricopa.gov/TaxLien", "https://ftp.treasurer.maricopa.gov/TaxAssignment/State_CP/state-cp-data.csv"],
}
# Candidate NEW sources (not in the registry): official pages named by a web
# search, read once for structure and terms. Discovery only.
DISCOVERY_PAGES = {
    "MN": ["https://www.stlouiscountymn.gov/departments-a-z/land-minerals/sales-and-contracts/tax-forfeited-land-sales",
           "https://www.hennepincounty.gov/services/property/tax-forfeited-land",
           "https://gishub-beltramicounty.hub.arcgis.com/datasets/county-land-sales/about",
           "https://www.itascacountymn.gov/616/Tax-Forfeit-Land",
           "https://www.carltoncountymn.gov/935/Tax-Forfeited-Land-Sale",
           "https://www.hubbardcounty.gov/tfl",
           "https://ottertailcounty.gov/property-home/property-sales/tax-forfeited-lands/"],
}
# Six-state expansion sprint (2026-10-01): candidate inventory pages and
# statewide parcel / assessment services for states beyond FL/TX/AL/AR/LA,
# named by web searches (search-index evidence only). Read once, value-free,
# with --expansion. ArcGIS services get their layers' field names, counts,
# copyright text and the SHAPES of identifier-like attributes (digits -> 9,
# letters -> A) so a deterministic join can be judged without a value.
EXPANSION_TARGETS = {
    "MD": ["https://dat.maryland.gov/pages/tax-sale-schedule.aspx",
           "https://baltimorecity.marylandtaxsale.com/",
           "https://annearundel.marylandtaxsale.com/",
           "https://frederick.marylandtaxsale.com/",
           "https://geodata.md.gov/imap/rest/services/PlanningCadastre/MD_PropertyData/MapServer",
           "https://opendata.maryland.gov/api/views/ed4q-f8tm.json",
           "https://opendata.maryland.gov/api/views/8dzc-9xpq.json"],
    "NJ": ["https://easthanover.newjerseytaxsale.com/",
           "https://cranford.newjerseytaxsale.com/",
           "https://www.nj.gov/nj/legal.html"],
    "CO": ["https://gis.colorado.gov/public/rest/services/Address_and_Parcel/Colorado_Public_Parcels/FeatureServer",
           "https://morgancounty.colorado.gov/county-held-tax-lien-sale-certificates",
           "https://www.clearcreekcounty.us/329"],
    "WV": ["https://www.wvsao.gov/CountyCollections/Default",
           "https://services.wvgis.wvu.edu/arcgis/rest/services/Planning_Cadastre/WV_Parcels/MapServer",
           "https://www.mapwv.gov/parcel/"],
    "MS": ["https://www.sos.ms.gov/public-lands/tax-forfeited-lands",
           "https://tflgis.sos.ms.gov/",
           "https://gis.mississippi.edu/server/rest/services/Cadastral/MS_Parcels_2023/MapServer",
           "https://maris.mississippi.edu/HTML/RESOURCES/Liability.html"],
    "NC": ["https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer",
           "https://www.nconemap.gov/pages/terms",
           "https://tax.mecknc.gov/services/tax-foreclosure-properties",
           "https://www.buncombenc.gov/622/Tax-Foreclosure-Sales"],
    "MN": ["https://gisweb.co.wilkin.mn.us/arcgis/rest/services/Auditor/TaxForfeitSales/FeatureServer",
           "https://maps.co.itasca.mn.us/arcgis/rest/services/Real_Estate/Direct_County_Lands/FeatureServer",
           "https://gisdata.mn.gov/dataset/plan-parcels-open"],
    "UT": ["https://auditor.utahcounty.gov/may-tax-sale/property-list",
           "https://maps.carbon.utah.gov/arcgis/rest/services/Hosted/TaxParcelForeclosures_37979aa0515c4818ac1804457ab42ae1/FeatureServer",
           "https://services1.arcgis.com/99lidPhWCzftIe9K/arcgis/rest/services/Parcels_SaltLake_LIR/FeatureServer",
           "https://gis.utah.gov/products/sgid/cadastre/parcels/"],
    "WI": ["https://services3.arcgis.com/n6uYoouQZW75n5WI/arcgis/rest/services/Wisconsin_Statewide_Parcels/FeatureServer",
           "https://www.sco.wisc.edu/parcels/data/",
           "https://www.co.sauk.wi.us/treasurer/tax-foreclosure-property-sale-sealed-bid",
           "https://www.greencountywi.org/492/Current-Tax-Deed-Sales"],
    "MA": ["https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/L3_TAXPAR_POLY_ASSESS_gdb/FeatureServer",
           "https://www.mass.gov/info-details/massgis-data-property-tax-parcels"],
    "CT": ["https://data.ct.gov/api/views/fyh6-7xga.json",
           "https://services3.arcgis.com/3FL1kr7L4LvwA2Kb/arcgis/rest/services/Connecticut_CAMA_and_Parcel_Layer/FeatureServer"],
    "TN": ["https://comptroller.tn.gov/office-functions/pa/gisredistricting/redistricting-and-land-use-maps/parcel-data.html"],
    "OH": ["https://services2.arcgis.com/MlJ0G8iWUyC7jAmu/arcgis/rest/services/OhioStatewidePacels_full_view/FeatureServer"],
    "VT": ["https://services.arcgis.com/XG15cJAlne2vxtgt/ArcGIS/rest/services/VT_Parcel/FeatureServer"],
}
# Pass 2 (2026-10-01): ArcGIS items whose licenceInfo / access text we need
# (catalog ids from pass 1), inventory-page links to follow (same host,
# listing / terms vocabulary), and extra pages.
EXPANSION_ITEMS = {
    "NC": ["8774cb904d5148d48c6c4d36f8101952"],        # Burke County NC Tax_Sales_FS
    "SC": ["0bf91b9d18f14702873af5f3ad870429"],        # York County SC Tax Sale Properties 2026 View
    "MI": ["47baabcecf1a4f4e9c47ef15c7c4b7ef", "5b973732a9e84fdd94fa225f8160650d"],  # Lenawee / Eaton
    "IN": ["57dc076f5fb845978b9a7df9971fbd29"],        # Muncie (Delaware Co.) Fall 2026 tax sale
    "GA": ["239e5314f25f4e9898f9201d36301af9"],        # Albany GA 2026 tax sale
    "XX": ["cfde38996bd443f8bc0b4ef7aac8d4e1", "2213fa3775db4f75ac1c13dc121dd28f"],  # unidentified 2026 tax sale layers
}
EXPANSION_ITEM_QUERIES = ('"NC1Map" parcels', 'owner:NCOneMap', '"Colorado Public Parcels"',
                          '"tax foreclosure" type:"Feature Service"', '"tax sale" 2026 type:"Feature Service"',
                          '"forfeited" type:"Feature Service"')
EXPANSION_EXTRA = {
    "UT": ["https://gis.utah.gov/documentation/policy/license/", "https://www.saltlakecounty.gov/property-tax/property-tax-sale/"],
    "WV": ["https://www.wvsao.gov/CountyCollections/LandSales", "https://www.wvsao.gov/CountyCollections/DeputyLandCommissioners",
           "https://www.wvsao.gov/CountyCollections/CertifiedToState"],
    "IN": ["https://www.in.gov/gis/", "https://www.sriservices.com/properties"],
    "TN": ["https://comptroller.tn.gov/disclaimer.html"],
    "WI": ["https://www.sco.wisc.edu/parcels/data/", "https://www.co.sauk.wi.us/treasurer/tax-deeded-properties"],
    "NC": ["https://www.nconemap.gov/pages/parcels", "https://www.burkenc.org/2263/Tax-Foreclosures"],
    "MD": ["https://baltimorecity.marylandtaxsale.com/index.cfm?zaction=AUCTION&Zmethod=CALENDAR"],
    "NJ": ["https://easthanover.newjerseytaxsale.com/index.cfm?zaction=AUCTION&Zmethod=CALENDAR"],
}
FOLLOW_VOCAB = re.compile(r"land sale|listing|certified|no bid|delinquent|foreclos|tax sale|tax deed|forfeit|sealed bid|"
                          r"terms of use|disclaimer|current sales|sale list|properties for sale", re.I)
MAX_FOLLOW = 6
EXPANSION_ITEMS.update({
    "WY": ["239e5314f25f4e9898f9201d36301af9"],
    "MI": ["47baabcecf1a4f4e9c47ef15c7c4b7ef", "5b973732a9e84fdd94fa225f8160650d"],
    "SC": ["0bf91b9d18f14702873af5f3ad870429"],
})
EXPANSION_ITEMS.pop("GA", None)
EXPANSION_ITEMS.pop("XX", None)
EXPANSION_EXTRA.update({
    "WV": ["https://www.wvsao.gov/Legal/TermsOfUse"],
    "NC": ["https://www.buncombenc.gov/622/Tax-Foreclosure-Sales", "https://tax.mecknc.gov/service/rem-foreclosures"],
    "CO": ["https://morgancounty.colorado.gov/county-held-tax-lien-sale-certificates"],
    "WI": ["https://www.greencountywi.org/492/Current-Tax-Deed-Sales"],
})
EXPANSION_TARGETS.update({
    "MI": ["https://services6.arcgis.com/mjEvhc9AE3ceAXtG/arcgis/rest/services/Tax_Sale_2026_view/FeatureServer",
           "https://services2.arcgis.com/c9l1e4fKpsCnqD7H/arcgis/rest/services/For_Sale_2026_view/FeatureServer"],
    "WY": ["https://services1.arcgis.com/EmwrhKkmuQhTATzU/arcgis/rest/services/2026TAXSALEPROP_1ST/FeatureServer"],
    "SC": ["https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/Tax_Sale_Properties_2025_View/FeatureServer"],
})
# Five-state enrichment sprint (2026-10-01): candidate sources for MI / WY /
# SC / CO / WI named by web searches (search-index evidence only; nothing was
# fetched from the sandbox). Read once with --five-state: pages for their
# structure and process text (dates, times, office phone numbers kept - they
# are the office's own published contact / schedule, never a row value;
# anything parcel-shaped stays masked), ArcGIS services for fields, counts,
# copyright text and identifier SHAPES, ArcGIS service DIRECTORIES for the
# names of a county org's other published services, and catalog items for
# their licence text.
FIVE_STATE_PAGES = {
    "MI": ["https://www.eatoncounty.org/1076/Foreclosure-Auction-Claimants",
           "https://www.eatoncounty.org/301/Treasurer",
           "https://www.lenawee.mi.us/712/Tax-Sale",
           "https://www.lenawee.mi.us/850/Lenawee-County-Landbank-Authority",
           "https://data-ecgis.opendata.arcgis.com/datasets/eaton-county-gis-open-data-policy",
           "https://co.muskegon.mi.us/1435/Residential-Properties",
           "https://www.thelandbank.org/find_properties.asp?fq=5",
           "https://www.crawfordco.org/offices-departments/treasurer/foreclosed-properties-sale/",
           "https://waynecountytreasurermi.com/"],
    "WY": ["https://www.albanycountywy.gov/299/Tax-Lien-Sale",
           "https://www.albanycountywy.gov/300/Tax-Sale-Listings",
           "https://www.albanycountywy.gov/178/Web-Map-Acknowledgment",
           "https://www.lincolncountywy.gov/government/treasurer/tax_sale.php",
           "https://www.niobraracounty.org/_departments/_treasurer/tax_sale.asp",
           "https://www.sweetwatercountywy.gov/departments/treasurer/tax_sales_and_redemptions.php"],
    "SC": ["https://www.yorkcountysc.gov/216/Tax-Collection",
           "https://oconeesc.com/delinquent-tax/sale-list",
           "https://oconeesc.com/delinquent-tax/tax-sale-information",
           "https://www.dorchestercountysc.gov/government/property-tax-services/delinquent-tax/delinquent-property-locator-map",
           "https://lex-co.sc.gov/departments/treasurer/forfeited-land-commission/flc-property-list",
           "https://www.lancastercountysc.gov/480/Forfeited-Properties-Available",
           "https://www.horrycountysc.gov/boards-and-commissions/forfeited-land-commission/guidelines-purchasing-property/",
           "https://www.richlandcountysc.gov/Property-Business/Taxes/Delinquent-Taxes/Forfeited-Land-Available",
           "https://www.gtcountysc.gov/415/Forfeited-Land-Commission",
           "https://berkeleycountysc.gov/dept/forfeited-land-commission/",
           "https://www.spartanburgcounty.org/388/Forfeited-Land-Commission",
           "https://www.newberrycounty.gov/forfeited-land-commission",
           "https://chestercountysc.gov/boards/tax-and-assessment/forfeited-land-commission/",
           "https://www.greenvillecounty.org/taxcollector/TaxSaleProcedures.aspx"],
    "CO": ["https://morgancounty.colorado.gov/tax-lien-sale",
           "https://morgancounty.colorado.gov/treasurer-and-public-trustee",
           "https://morgancounty.colorado.gov/treasurers-deed-option-auctions",
           "https://morgancounty.colorado.gov/morgan-county-treasurer-tax-deed-option-auction-results",
           "https://www.douglasco.gov/treasurer/tax-lien-sale-information/",
           "https://treasurer.mesacounty.us/reports/county-held-liens/",
           "https://kiowacounty.colorado.gov/tax-lien-sale-information",
           "https://adamscountyco.gov/our-county/elected-officials/treasurer-public-trustee/treasurer-division/tax-lien-sale/",
           "https://conejoscounty.colorado.gov/treasurers-tax-deed",
           "https://riograndecounty.colorado.gov/treasurers-tax-deed",
           "https://sanjuancounty.colorado.gov/treasurers-deeds",
           "https://kitcarsoncounty.colorado.gov/departments/treasurer/public-trustee/treasures-deed-auctions"],
    "WI": ["https://www.greencountywi.org/492/Current-Tax-Deed-Sales",
           "https://www.sco.wisc.edu/parcels/data/",
           "https://www.woodcountywi.gov/Departments/Treasurer/TaxDeed.aspx",
           "https://www.sccwi.gov/586/Tax-Deed-Information",
           "https://treasurer.danecounty.gov/taxdeedauction",
           "https://treasurer.danecounty.gov/Property-Owner-Info/foreclosure/Tax-Deed-Details",
           "https://www.co.pierce.wi.us/departments/county_clerk/tax_deeds/tax_deed_lands.php",
           "https://www.co.juneau.wi.gov/i_want_to/find_learn_about/land_sales.php",
           "https://www.co.sauk.wi.us/treasurer/sauk-county-properties-sale-offer-purchase",
           "https://www.co.lincoln.wi.us/forestry-land-and-parks/page/tax-delinquent-properties-sale"],
}
FIVE_STATE_SERVICES = {
    "MI": ["https://maps.muskegoncountygis.com/arcgis/rest/services/PropertyViewer/MapServer"],
    "WY": ["https://gis.deq.wyo.gov/arcgis/rest/services/WY_PRIVATE_PARCELS/MapServer",
           "https://gis.deq.wyo.gov/arcgis/rest/services/WY_PARCELS/MapServer",
           "https://services5.arcgis.com/V4b98G4pSkzvUam9/arcgis/rest/services/Parcels/FeatureServer"],
    "WI": ["https://services3.arcgis.com/n6uYoouQZW75n5WI/arcgis/rest/services/Wisconsin_Statewide_Parcels_DB/FeatureServer",
           "https://services3.arcgis.com/n6uYoouQZW75n5WI/arcgis/rest/services/Wisconsin_Statewide_Parcels/FeatureServer"],
}
FIVE_STATE_DIRECTORIES = {
    "MI": ["https://services2.arcgis.com/c9l1e4fKpsCnqD7H/arcgis/rest/services",
           "https://services6.arcgis.com/mjEvhc9AE3ceAXtG/arcgis/rest/services",
           "https://ecgis.eatoncounty.org/ecgis_ssl/rest/services"],
    "WY": ["https://services1.arcgis.com/EmwrhKkmuQhTATzU/arcgis/rest/services",
           "https://gis.deq.wyo.gov/arcgis/rest/services"],
    "SC": ["https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services"],
}
FIVE_STATE_ITEMS = {
    "MI": ["31f8414f00144961827881053d69b1d0"],                                  # Eaton "Tax Parcel Sale Web Map"
    "WY": ["fd2106a2896446008f88b42dfbd14f9d", "163f1611abc3415383d7f89393d4e2d5"],  # WY statewide parcel viewer; Albany map
    "SC": ["3491ddd798ea4097a0c8037f2a00c6fb"],                                  # "Delinquent Tax Sale Web Map (Ongoing)", owner unknown
    "CO": ["87f9905d9faf4ae3a7a385c0707717b5", "c525f98f102f4ee5b9eb56fc5ecf4d1c"],  # Douglas County tax sale list; lien map
}
FIVE_STATE_QUERIES = ('orgid:2AGLxyiJoNiVHKwq (forfeited OR "tax sale" OR delinquent)',
                      'orgid:c9l1e4fKpsCnqD7H ("for sale" OR "tax" OR "parcel")',
                      '"tax lien" Douglas County Colorado',
                      '"forfeited land" type:"Feature Service"',
                      '"county held" lien type:"Feature Service"',
                      '"tax deed" Wisconsin type:"Feature Service"',
                      '"tax foreclos" Michigan type:"Feature Service"',
                      '"tax sale" Wyoming type:"Feature Service"')
# Pass 2 (2026-10-01): what pass 1 pointed at. PDFs are read as process text
# (pdfplumber, first pages only); layer probes read the SHAPES of identifier
# fields and the value counts of named CATEGORY fields (a sale flag, a tax
# year, a sale type - never an owner, address or amount) under a WHERE
# clause, so a join key or a list's sale cycle can be judged value-free.
FIVE_STATE_PASS2_PAGES = {
    "MI": ["https://www.eatoncounty.org/1530/2026-Foreclosure-Sale",
           "https://www.thelandbank.org/terms_of_use.asp",
           "https://www.thelandbank.org/find_properties.asp"],
    "SC": ["https://www.yorkcountysc.gov/DocumentCenter/View/5241/Tax-Sale-Fact-Sheet"],
    "CO": ["https://morgancounty.colorado.gov/county-held-tax-lien-sale-certificates",
           "https://morgancounty.colorado.gov/bidding-rules-and-information"],
    "WI": ["https://www.greencountywi.org/DocumentCenter/View/2103/Tax-Deed-Bid-Form",
           "https://www.greencountywi.org/copyright",
           "https://www.sccwi.gov/124/Privacy-Legal-Notices"],
}
FIVE_STATE_PASS2_SERVICES = {
    "MI": ["https://services2.arcgis.com/c9l1e4fKpsCnqD7H/arcgis/rest/services/Parcels_AGO/FeatureServer",
           "https://services6.arcgis.com/mjEvhc9AE3ceAXtG/arcgis/rest/services/Lenawee_Parcels_Public/FeatureServer"],
    "WY": ["https://services1.arcgis.com/EmwrhKkmuQhTATzU/arcgis/rest/services/2026TAXSALEPROP_1STC/FeatureServer",
           "https://gis.deq.wyo.gov/arcgis/rest/services/PARCEL_OWNER_MAP/MapServer"],
}
# (layer, where, id fields -> shapes, category fields -> value counts)
FIVE_STATE_PROBES = {
    "MI": [("https://services2.arcgis.com/c9l1e4fKpsCnqD7H/arcgis/rest/services/For_Sale_2026_view/FeatureServer/0", "1=1",
            ["lparcel"], ["Sold", "type"])],
    "WY": [("https://services1.arcgis.com/EmwrhKkmuQhTATzU/arcgis/rest/services/2026TAXSALEPROP_1ST/FeatureServer/0", "1=1",
            ["accountno", "pidn"], ["taxyear"])],
    "CO": [("https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest/services/Tax_Sale_List_Locations/FeatureServer/0", "1=1",
            ["Account_No", "State_Parcel_No"], ["Tax_Year", "Prior_Year_Lien"]),
           ("https://gis.colorado.gov/public/rest/services/Address_and_Parcel/Colorado_Public_Parcels/FeatureServer/0",
            "countyName='Douglas'", ["account", "parcel_id"], [])],
    "WI": [("https://services3.arcgis.com/n6uYoouQZW75n5WI/arcgis/rest/services/Wisconsin_Statewide_Parcels_DB/FeatureServer/0",
            "CONAME='GREEN'", ["PARCELID", "TAXPARCELID", "STATEID"], ["TAXROLLYEAR", "PROPCLASS"]),
           ("https://services3.arcgis.com/n6uYoouQZW75n5WI/arcgis/rest/services/Wisconsin_Statewide_Parcels_DB/FeatureServer/0",
            "CONAME='DANE'", ["PARCELID", "TAXPARCELID", "STATEID"], ["TAXROLLYEAR", "PROPCLASS"])],
}
FIVE_STATE_PASS2_QUERIES = ('orgid:seTexOicoRXDvRsJ (lien OR "tax sale")',
                            'owner:DouglasCountyCO_GISServices lien')
# (page, [column headers whose value counts are category words - never names, addresses or amounts])
FIVE_STATE_TABLE_VALUES = {
    "https://www.thelandbank.org/find_properties.asp": ["Class", "Sale Type"],
    "https://www.thelandbank.org/find_properties.asp?fq=5": ["Class", "Sale Type"],
}


# Pass 3 (2026-10-01): Douglas County CO's lien layers (licence tail, lien
# type values), the Wisconsin statewide parcel licence, York SC's sale page.
FIVE_STATE_PASS3_PAGES = {
    "CO": ["https://www.douglasco.gov/documents/open-data-guidelines.pdf/",
           "https://www.douglasco.gov/documents/request-for-assignment-of-county-held.pdf/",
           "https://www.douglasco.gov/treasurer/"],
    "WI": ["https://www.sco.wisc.edu/parcels/data/", "https://www.sco.wisc.edu/parcels/"],
    "SC": ["https://www.yorkcountysc.gov/789/Tax-Information"],
}
FIVE_STATE_PASS3_SERVICES = {
    "CO": ["https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest/services/OpenData/FeatureServer/2",
           "https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest/services/County_Held_Tax_Liens1/FeatureServer"],
}
FIVE_STATE_PASS3_PROBES = {
    "CO": [("https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest/services/OpenData/FeatureServer/2", "1=1",
            ["account_id", "lien_id"], ["type", "lien_type", "lien_year", "sale_or_purchase_date"]),
           ("https://services.arcgis.com/seTexOicoRXDvRsJ/arcgis/rest/services/County_Held_Tax_Liens1/FeatureServer/0", "1=1",
            ["USER_account_id", "USER_lien_id"], ["USER_type", "USER_lien_type", "USER_lien_year"])],
}
FIVE_STATE_PASS3_ITEMS = {
    "CO": ["950fd2c3a9bf4e0e92fa4a64f1859fec", "0a54a67e8b944ddeae533a2f6a3fe047", "7ca5a1199ee94728bb3324bf4d646c9e"],
    "SC": ["ef9243d9330c4891ba724689f2eb1502"],
}
FIVE_STATE_PASS3_QUERIES = ('"Wisconsin Statewide Parcels" V12', 'owner:SCO_Admin parcels')


# Property-enrichment sprint (2026-10-01): candidate PARCEL / TAX-ROLL sources
# for rows already in production - Texas (TxGIO StratMap statewide parcels,
# matched on the CAD account the Texas rows carry as case_no), Louisiana (East
# Baton Rouge Parish Assessor tax roll / tax parcels), Wyoming (Department of
# Revenue statewide parcels). Licence pages, layer fields, identifier SHAPES
# per county - never a value.
STRATMAP = "https://feature.geographic.texas.gov/arcgis/rest/services/Parcels/stratmap_land_parcels_48_most_recent/MapServer"
ENRICH_PAGES = {
    "TX": ["https://geographic.texas.gov/stratmap/land-parcels", "https://www.geographic.texas.gov/stratmap/land-parcels.html",
           "https://tnris.org/stratmap/land-parcels.html"],
    "LA": ["https://data.brla.gov/api/views/myfc-nh6n.json", "https://data.brla.gov/api/views/ei2c-krsr.json",
           "https://city.brla.gov/gis/metadata/TAX_PARCEL.html"],
    "WY": ["https://wyo-prop-div.wyo.gov/tax-districts/maps-gis-data", "https://ets.wyo.gov/gis-office/georesources"],
}
ENRICH_SERVICES = {
    "TX": [STRATMAP],
    "LA": ["https://maps.brla.gov/gis/rest/services/Cadastral/Tax_Parcel/MapServer"],
    "WY": ["https://gis.deq.wyo.gov/arcgis/rest/services/WY_PRIVATE_PARCELS/MapServer"],
}
_TX_COUNTIES = ("Galveston", "Liberty", "Leon", "Dallas", "Travis", "Nueces", "Hardin", "Maverick", "Van Zandt", "Smith",
                "Cameron", "Jim Wells", "Matagorda", "Concho", "Atascosa", "Llano", "Victoria", "Caldwell")
ENRICH_PROBES = {
    "TX": [(STRATMAP + "/0", f"UPPER(COUNTY) = '{c.upper()}'", ["Prop_ID", "GEO_ID", "PROP_ID"], ["TAX_YEAR", "STAT_LAND_USE", "LOC_LAND_USE"])
           for c in _TX_COUNTIES],
    "WY": [("https://gis.deq.wyo.gov/arcgis/rest/services/WY_PRIVATE_PARCELS/MapServer/0", "1=1",
            ["PIDN", "ACCOUNTNO", "PARCELNB", "LOCAL_ID"], ["COUNTY", "JURISDICTION"])],
}
ENRICH_ITEMS = {
    "WY": ["fd2106a2896446008f88b42dfbd14f9d", "9b60a7596f5d464c9cd4667efa8abbb5"],
}
# Round 2 (2026-10-01): StratMap with its real (lowercase) attribute names,
# the StratMap program's own data-use statement, and the EBR Socrata
# datasets' identifier SHAPES through the SODA API (never a value).
ENRICH2_PAGES = {
    "TX": ["https://geographic.texas.gov/stratmap/index.html", "https://geographic.texas.gov/stratmap/",
           "https://txwaterdatahub.org/dataset/stratmap-land-parcels", "https://cdn.tnris.org/documents/tnris-land-parcel-schema.pdf"],
}
ENRICH2_PROBES = {
    "TX": [(STRATMAP + "/0", f"UPPER(county) = '{c.upper()}'", ["prop_id", "geo_id"], ["tax_year", "stat_land_use", "source", "date_acq"])
           for c in _TX_COUNTIES],
}
# (SODA resource, id fields, category fields)
ENRICH2_SODA = {
    "LA": [("https://data.brla.gov/resource/myfc-nh6n.json", ["property_number", "legacy_property_number"], ["tax_year", "assessment_type", "assessment_status"]),
           ("https://data.brla.gov/resource/ei2c-krsr.json", ["property_no", "assessment_no"], ["status", "sale_year"]),
           ("https://data.brla.gov/resource/a4h4-zi7e.json", ["property_number"], ["tax_year"])],
}


# Round 3 (2026-10-01): East Baton Rouge's own acquisition process for
# adjudicated property (the Parish's page, its "Acquiring Adjudicated Property"
# document, the FAQ) and the assessment-number SHAPES the three EBR datasets
# use, so a join is judged before any configuration exists.
ENRICH3_PAGES = {
    "LA": ["https://www.brla.gov/455/Adjudicated-Property", "https://www.brla.gov/DocumentCenter/View/6524/Acquiring-Adjudicated-Property-PDF",
           "https://www.brla.gov/Faq.aspx?QID=286", "https://www.brla.gov/Faq.aspx?TID=63"],
}
# Round 4: York County SC's 2026 Tax Sale Information document (the sale's
# date, time and place as the county states them).
ENRICH4_PAGES = {
    "SC": ["https://www.yorkcountysc.gov/DocumentCenter/View/3590/2026-Tax-Sale-Information", "https://www.yorkcountysc.gov/216/Tax-Collection"],
}
ENRICH3_SODA = {
    "LA": [("https://data.brla.gov/resource/a4h4-zi7e.json", ["assessment_num"], ["tax_roll_year"]),
           ("https://data.brla.gov/resource/ei2c-krsr.json", ["assessment_num"], ["status", "sale_year"]),
           ("https://data.brla.gov/resource/myfc-nh6n.json", ["assessment_no", "assessment_no_new"], ["tax_year", "unit_type", "vacant_lot_yn"])],
}


def soda_probe(session: requests.Session, resource: str, id_fields: list[str], cat_fields: list[str]) -> dict:
    """A Socrata dataset's identifier SHAPES and category counts from a 200-row
    sample (field names as the SODA API spells them). Never a value."""
    out = {"url": resource + " (SODA sample)", "kind": "layer_probe"}
    r, e = fetch(session, resource + "?" + urlencode({"$select": "count(*)"}))
    try:
        out["count"] = (r.json() or [{}])[0] if r is not None and r.status_code == 200 else (e or getattr(r, "status_code", None))
    except ValueError:
        out["count"] = "not json"
    r, e = fetch(session, resource + "?" + urlencode({"$limit": 200}))
    try:
        rows = r.json() if r is not None and r.status_code == 200 else []
    except ValueError:
        rows = []
    rows = rows if isinstance(rows, list) else []
    out["sampled"] = len(rows)
    out["fields_present"] = sorted({k for row in rows[:50] for k in row})[:60]
    out["id_shapes"] = {n: dict(Counter(shape(str(row.get(n) if row.get(n) is not None else "")) for row in rows).most_common(5)) for n in id_fields}
    out["value_counts"] = {n: dict(Counter(mask_digits(str(row.get(n)))[:40] if "year" not in n else str(row.get(n)) for row in rows).most_common(10)) for n in cat_fields}
    return out


ENRICH_QUERIES = ('StratMap Land Parcels', 'Wyoming statewide parcels', 'Albany County Wyoming parcels',
                  'Eaton County Michigan parcels', 'Lenawee County parcels', 'York County SC parcels')


def pdf_process(session: requests.Session, url: str, max_pages: int = 6) -> dict:
    """A PDF's process text (first pages), through process_text()."""
    out = {"url": url, "kind": "pdf_process"}
    resp, err = fetch(session, url)
    if err or resp is None:
        out["error"] = err
        return out
    out.update({"status": resp.status_code, "content_type": resp.headers.get("Content-Type", ""), "final_url": resp.url})
    if resp.status_code != 200 or "pdf" not in out["content_type"].lower():
        return out
    try:
        import pdfplumber  # noqa: PLC0415
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            out["pages"] = len(pdf.pages)
            text = "\n".join((p.extract_text() or "") for p in pdf.pages[:max_pages])
    except Exception as exc:  # noqa: BLE001
        out["parse_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return out
    snippets = []
    for s in re.split(r"(?<=[.!?])\s+|\n{2,}|\n(?=[A-Z0-9•\-])", text):
        s = clean(s)
        if len(s) > 20 and (SNIPPET_VOCAB.search(s) or PROCESS_VOCAB.search(s)) and not LONG_DIGITS.search(s):
            snippets.append(process_text(s)[:MAX_SNIPPET_CHARS])
        if len(snippets) >= 60:
            break
    out["snippets"] = snippets
    return out


def layer_probe(session: requests.Session, layer: str, where: str, id_fields: list[str], cat_fields: list[str]) -> dict:
    out = {"url": f"{layer} WHERE {where}", "kind": "layer_probe"}
    r, e = fetch(session, layer + "/query?" + urlencode({"where": where, "returnCountOnly": "true", "f": "json"}))
    try:
        out["count"] = r.json().get("count") if r is not None and r.status_code == 200 else e
    except ValueError:
        out["count"] = "not json"
    r, e = fetch(session, layer + "/query?" + urlencode({"where": where, "outFields": ",".join(id_fields + cat_fields),
                                                        "returnGeometry": "false", "resultRecordCount": 200, "f": "json"}))
    try:
        feats = (r.json().get("features") or []) if r is not None and r.status_code == 200 else []
    except ValueError:
        feats = []
    attrs = [ft.get("attributes") or {} for ft in feats]
    out["sampled"] = len(attrs)
    out["id_shapes"] = {n: dict(Counter(shape(str(a.get(n) if a.get(n) is not None else "")) for a in attrs).most_common(5)) for n in id_fields}
    out["value_counts"] = {n: dict(Counter(mask_digits(str(a.get(n)))[:40] if n.lower() not in ("tax_year", "taxyear", "taxrollyear")
                                           else str(a.get(n)) for a in attrs).most_common(10)) for n in cat_fields}
    return out


def table_values(session: requests.Session, url: str, headers: list[str]) -> dict:
    out = {"url": url + " (column values)", "kind": "table_values"}
    resp, err = fetch(session, url)
    if err or resp is None or resp.status_code != 200 or BeautifulSoup is None:
        out["error"] = err or f"status {getattr(resp, 'status_code', None)}"
        return out
    soup = BeautifulSoup(resp.text, "html.parser")
    counts: dict[str, Counter] = {h: Counter() for h in headers}
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if not rows:
            continue
        head = [clean(c.get_text(" ")) for c in rows[0].find_all(["th", "td"])]
        idx = {h: head.index(h) for h in headers if h in head}
        for tr in rows[1:]:
            cells = [clean(c.get_text(" ")) for c in tr.find_all("td")]
            for h, i in idx.items():
                if i < len(cells):
                    counts[h][mask_digits(cells[i])[:40]] += 1
    out["value_counts"] = {h: dict(c.most_common(12)) for h, c in counts.items()}
    return out


PROCESS_KEEP = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d|\d\s*(a\.?m\.?|p\.?m\.?)\b|\$\s*\d|"
                          r"\(?\d{3}\)?[-. ]?\d{3}[-. ]\d{4}|\d{1,2}/\d{1,2}/\d{2,4}|%", re.I)
PHONE = re.compile(r"\(?\d{3}\)?[-. ]?\d{3}[-. ]\d{4}")
PARCELISH = re.compile(r"[A-Za-z0-9-]*\d[A-Za-z0-9-]*")


def process_text(sentence: str) -> str:
    """A process / schedule sentence with its dates, times, amounts and the
    office's phone numbers kept; any token that could be a parcel, account,
    case or certificate number (six or more digits in one token, a phone
    number aside) is masked."""
    if not PROCESS_KEEP.search(sentence):
        return mask_digits(sentence)
    base = PHONE.sub(lambda m: "\x00" * len(m.group(0)), sentence)
    out = list(sentence)
    for m in PARCELISH.finditer(base):
        if sum(ch.isdigit() for ch in m.group(0)) >= 6:
            for i in range(m.start(), m.end()):
                if out[i].isdigit():
                    out[i] = "9"
    return "".join(out)


def arcgis_directory(session: requests.Session, url: str) -> dict:
    """An ArcGIS REST services directory: the names and types of the
    services (and folders) an organisation publishes - metadata only."""
    resp, err = fetch(session, url.rstrip("/") + "?f=json")
    if err or resp is None or resp.status_code != 200:
        return {"error": err or f"status {getattr(resp, 'status_code', None)}"}
    try:
        data = resp.json()
    except ValueError:
        return {"error": "not json"}
    return {"services": [f"{s.get('name')}:{s.get('type')}" for s in data.get("services") or []][:200],
            "folders": (data.get("folders") or [])[:60]}


# ASP.NET postback probes: (page, [(dropdown to post back, pick = first real option)], search button)
ASPNET_PROBES = {
    "WV": ("https://www.wvsao.gov/CountyCollections/Default",
           ["ctl00$FixedWidthContent$YearDD", "ctl00$FixedWidthContent$CountyDD", "ctl00$FixedWidthContent$ddlCounties"],
           "ctl00$FixedWidthContent$SearchBTN"),
}
EXPANSION_QUERIES = ('"tax sale" parcels type:"Feature Service"',
                     '"delinquent" parcels type:"Feature Service"',
                     '"tax deed" type:"Feature Service"',
                     '"county held" OR "tax title" type:"Feature Service"')
ARCGIS_SERVICE_RE = re.compile(r"/(FeatureServer|MapServer)(/\d+)?/?$")
DISCOVERY_QUERIES = ('("tax forfeited" OR "tax forfeit" OR "tax-forfeited") type:"Feature Service"',
                     '"adjudicated" property type:"Feature Service"')
TERMS_VOCAB = re.compile(r"terms|disclaimer|legal|licen[cs]e|conditions|copyright|policy|privacy|open data|use of (this|the) (site|data)", re.I)
SNIPPET_VOCAB = re.compile(r"terms|disclaim|licen[cs]|copyright|permission|commercial|redistribut|reproduc|public record|open data|"
                           r"warrant|liabil|accuracy|purchas|apply|application|bid|auction|redeem|redemption|inventory|"
                           r"adjudicat|certificate|assign|updated|weekly|daily|monthly", re.I)
ID_HEADER = re.compile(r"parcel|number|\bno\b|\bnum|\bid\b|\bcp\b|cert|case|year|date|amount|value|rate|zip|ward", re.I)
LONG_DIGITS = re.compile(r"\d{7,}")
MAX_SNIPPETS, MAX_SNIPPET_CHARS = 40, 320
PROCESS_VOCAB = re.compile(r"sale|held|register|registration|deposit|payment|cash|cashier|certified|phone|contact|email|e-mail|"
                           r"treasurer|clerk|offer|sealed|minimum|opening|deadline|location|address|office|hours|online|in person|"
                           r"assignment|assign|redemption|interest|premium|overbid|list|available|commission|forfeit|"
                           r"public domain|licen[cs]|restrict|permission|free of charge|attribut|creative commons|reuse|redistribut", re.I)
MAX_TERMS_FOLLOW = 4
CSV_BYTES = 3_000_000


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def mask_digits(text: str) -> str:
    return re.sub(r"\d", "9", text or "")


def shape(value: str) -> str:
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", (value or "").strip()))


def fetch(session: requests.Session, url: str, *, stream: bool = False):
    try:
        return session.get(url, headers=HEADERS, timeout=25, allow_redirects=True, stream=stream), None
    except requests.RequestException as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:160]}"


def html_structure(html: str, url: str, *, process: bool = False) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = clean(soup.title.get_text(" ")) if soup.title else ""
    headings = [clean(h.get_text(" "))[:120] for h in soup.find_all(["h1", "h2", "h3"])][:20]
    tables = []
    for t in soup.find_all("table")[:8]:
        hdr = [clean(th.get_text(" "))[:60] for th in t.find_all("th")][:30]
        body_rows = [tr for tr in t.find_all("tr") if tr.find("td")]
        cells = Counter(len(tr.find_all("td")) for tr in body_rows)
        first = [mask_digits(clean(td.get_text(" ")))[:60] for td in body_rows[0].find_all("td")] if body_rows else []
        col_shapes = []
        for i in range(max(cells) if cells else 0):
            vals = [clean(tr.find_all("td")[i].get_text(" ")) for tr in body_rows[1:] if len(tr.find_all("td")) > i]
            col_shapes.append(dict(Counter(shape(v)[:40] for v in vals).most_common(3)))
        tables.append({"headers": [mask_digits(h) for h in hdr], "body_rows": len(body_rows),
                       "cells_per_row": dict(cells.most_common(3)), "id": t.get("id") or "", "class": " ".join(t.get("class") or []),
                       "first_row": first, "col_shapes": col_shapes})
    forms = []
    for f in soup.find_all("form")[:6]:
        fields = []
        for el in f.find_all(["input", "select", "textarea", "button"])[:40]:
            entry = {"tag": el.name, "name": el.get("name") or "", "type": el.get("type") or ""}
            if el.name == "select":
                opts = [mask_digits(clean(o.get_text(" ")))[:40] for o in el.find_all("option")]
                entry["options"] = len(opts)
                entry["option_texts"] = opts[:120]
                vals = [o.get("value") or "" for o in el.find_all("option")]
                entry["value_shapes"] = dict(Counter(shape(v) for v in vals).most_common(5))
            fields.append(entry)
        forms.append({"method": (f.get("method") or "get").lower(), "action": mask_digits(urljoin(url, f.get("action") or "")), "fields": fields})
    terms_links = []
    for a in soup.find_all("a", href=True):
        text = clean(a.get_text(" "))
        href = urljoin(url, a["href"].strip())
        if href.startswith(("http://", "https://")) and (TERMS_VOCAB.search(text) or TERMS_VOCAB.search(urlsplit(href).path)) \
                and not LONG_DIGITS.search(href):
            terms_links.append({"text": text[:80], "href": href})
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"].strip())
        if href.startswith(("http://", "https://")) and not LONG_DIGITS.search(href):
            links.append({"text": clean(a.get_text(" "))[:80], "href": href.split("#")[0]})
    for tag in soup.find_all(["table", "script", "style", "noscript", "select"]):
        tag.decompose()
    snippets = []
    for s in re.split(r"(?<=[.!?])\s+|\n{2,}", soup.get_text("\n")):
        s = clean(s)
        if len(s) > 25 and (SNIPPET_VOCAB.search(s) or (process and PROCESS_VOCAB.search(s))) and not LONG_DIGITS.search(s):
            snippets.append((process_text(s) if process else mask_digits(s))[:MAX_SNIPPET_CHARS])
        if len(snippets) >= MAX_SNIPPETS:
            break
    return {"title": title, "headings": headings, "tables": tables, "forms": forms,
            "terms_links": terms_links[:15], "snippets": snippets, "links": links[:300]}


def csv_structure(resp) -> dict:
    raw = b""
    for chunk in resp.iter_content(65536):
        raw += chunk
        if len(raw) >= CSV_BYTES:
            break
    complete = len(raw) < CSV_BYTES
    text = raw.decode("utf-8-sig", errors="replace")
    if not complete:
        text = text[: text.rfind("\n")]
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {"csv_rows": 0}
    header = rows[0]
    body = [r for r in rows[1:] if any(c.strip() for c in r)]
    columns = []
    for i, h in enumerate(header):
        vals = [r[i] for r in body if i < len(r) and r[i].strip()]
        col = {"header": h, "non_empty": len(vals)}
        if ID_HEADER.search(h):
            col["shapes"] = dict(Counter(shape(v) for v in vals).most_common(4))
            col["distinct"] = len(set(vals))
        columns.append(col)
    return {"csv_header": header, "csv_rows": len(body), "csv_read_complete": complete, "csv_bytes_read": len(raw), "columns": columns}


def socrata_structure(data: dict) -> dict:
    lic = data.get("license") or {}
    meta = data.get("metadata") or {}
    return {"name": data.get("name"), "description": mask_digits((data.get("description") or "")[:700]),
            "licenseId": data.get("licenseId"), "license": {k: lic.get(k) for k in ("name", "termsLink")},
            "attribution": data.get("attribution"), "attributionLink": data.get("attributionLink"),
            "provenance": data.get("provenance"), "publicationDate": data.get("publicationDate"),
            "rowsUpdatedAt": data.get("rowsUpdatedAt"), "viewLastModified": data.get("viewLastModified"),
            "custom_fields": meta.get("custom_fields"),
            "columns": [{"name": c.get("name"), "field": c.get("fieldName"), "type": c.get("dataTypeName")} for c in data.get("columns") or []]}


def capture(session: requests.Session, url: str, kind: str, *, process: bool = False) -> dict:
    out = {"url": url, "kind": kind, "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    is_csv = ".csv" in urlsplit(url).path.lower()
    resp, err = fetch(session, url, stream=is_csv)
    if err:
        out["error"] = err
        return out
    out.update({"status": resp.status_code, "final_url": resp.url, "content_type": resp.headers.get("Content-Type", ""),
                "last_modified": resp.headers.get("Last-Modified"), "content_length": resp.headers.get("Content-Length")})
    if resp.status_code != 200:
        return out
    ctype = out["content_type"].lower()
    try:
        if is_csv or "text/csv" in ctype:
            out.update(csv_structure(resp))
        elif "json" in ctype or url.endswith(".json"):
            data = resp.json()
            out["socrata"] = socrata_structure(data) if isinstance(data, dict) and "columns" in data else {"keys": sorted(data)[:40] if isinstance(data, dict) else type(data).__name__}
        elif BeautifulSoup is not None:
            out.update(html_structure(resp.text, resp.url, process=process))
    except Exception as exc:  # noqa: BLE001 - evidence capture reports, never crashes
        out["parse_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


def form_probe(session: requests.Session, url: str) -> dict:
    """Submit the page's own GET search form once, with the FIRST non-blank
    option of its first select and every other field at its page default -
    the site's own parameter names and option value, never a guessed URL.
    Only the structure of the result page is kept (the URL is printed with
    digits masked)."""
    resp, err = fetch(session, url)
    if err or resp is None or resp.status_code != 200:
        return {"error": err or f"status {getattr(resp, 'status_code', None)}"}
    soup = BeautifulSoup(resp.text, "html.parser")
    for f in soup.find_all("form"):
        if (f.get("method") or "get").lower() != "get":
            continue
        sel = next((s for s in f.find_all("select") if s.get("name") and len(s.find_all("option")) > 2), None)
        if sel is None:
            continue
        value = next((o.get("value") for o in sel.find_all("option") if (o.get("value") or "").strip()), None)
        if value is None:
            continue
        params = {}
        for el in f.find_all(["input", "button"]):
            if el.get("name") and (el.get("type") or "").lower() not in ("checkbox", "radio", "reset"):
                params.setdefault(el["name"], el.get("value") or "")
        params[sel["name"]] = value
        target = urljoin(resp.url, f.get("action") or "") + "?" + urlencode(params)
        page = capture(session, target, "form_probe")
        page["url"] = mask_digits(target)
        page["final_url"] = mask_digits(page.get("final_url") or "")
        page["probe_params"] = sorted(params)
        return page
    return {"error": "no GET form with a select on the page"}


ARCGIS_SEARCH = "https://www.arcgis.com/sharing/rest/search"


def strip_html(text: str) -> str:
    return clean(re.sub(r"<[^>]+>", " ", text or ""))


def arcgis_layer_meta(session: requests.Session, url: str) -> list[dict]:
    """A feature / map service's layers: name, fields, edit date and feature
    count. Metadata only - never a feature."""
    out = []
    resp, err = fetch(session, url.rstrip("/") + "?f=json")
    if err or resp is None or resp.status_code != 200:
        return [{"error": err or f"status {getattr(resp, 'status_code', None)}"}]
    try:
        svc = resp.json()
    except ValueError:
        return [{"error": "not json"}]
    layers = svc.get("layers") or []
    if not layers and re.search(r"/(FeatureServer|MapServer)/\d+$", url):
        layers = [{"id": int(url.rstrip("/").rsplit("/", 1)[1])}]
        url = url.rstrip("/").rsplit("/", 1)[0]
    for lyr in layers[:3]:
        lurl = f"{url.rstrip('/')}/{lyr.get('id')}"
        rec: dict = {"layer": lurl}
        r2, e2 = fetch(session, lurl + "?f=json")
        if e2 or r2 is None or r2.status_code != 200:
            rec["error"] = e2 or f"status {getattr(r2, 'status_code', None)}"
            out.append(rec)
            continue
        try:
            meta = r2.json()
        except ValueError:
            rec["error"] = "not json"
            out.append(rec)
            continue
        rec.update({"name": meta.get("name"), "geometry": meta.get("geometryType"), "max_records": meta.get("maxRecordCount"),
                    "last_edit": (meta.get("editingInfo") or {}).get("lastEditDate"),
                    "copyright": strip_html(meta.get("copyrightText") or "")[:300],
                    "fields": [f"{f.get('name')}:{(f.get('type') or '').replace('esriFieldType', '')}" + (f"({f.get('alias')})" if f.get("alias") and f.get("alias") != f.get("name") else "")
                               for f in meta.get("fields") or []][:60]})
        r3, _ = fetch(session, lurl + "/query?where=1%3D1&returnCountOnly=true&f=json")
        try:
            rec["count"] = r3.json().get("count") if r3 is not None and r3.status_code == 200 else None
        except ValueError:
            rec["count"] = None
        # The SHAPES of identifier-like attributes in a small sample (never a
        # value): how a parcel / account key is written, so a deterministic
        # join with another source can be judged.
        id_fields = [f.get("name") for f in meta.get("fields") or [] if f.get("name") and ID_HEADER.search(f.get("name"))][:12]
        if id_fields:
            r4, _ = fetch(session, lurl + "/query?" + urlencode({"where": "1=1", "outFields": ",".join(id_fields),
                                                                "returnGeometry": "false", "resultRecordCount": 25, "f": "json"}))
            try:
                feats = r4.json().get("features") or [] if r4 is not None and r4.status_code == 200 else []
                rec["id_shapes"] = {n: dict(Counter(shape(str((ft.get("attributes") or {}).get(n) or "")) for ft in feats).most_common(3))
                                    for n in id_fields}
            except ValueError:
                pass
        out.append(rec)
        time.sleep(0.4)
    return out


def aspnet_probe(session: requests.Session, url: str, dropdowns: list[str], button: str) -> dict:
    """Walk an ASP.NET WebForms search the way a browser does: GET the page,
    post back each dropdown with its FIRST real option (the site's own
    values, never a guess), then press the search button once. Only the
    result page's structure is kept (table headers, row counts, option
    counts) - never a value."""
    if BeautifulSoup is None:
        return {"error": "bs4 missing"}
    steps = []
    resp, err = fetch(session, url)
    if err or resp is None or resp.status_code != 200:
        return {"error": err or f"status {getattr(resp, 'status_code', None)}"}

    def form_state(html):
        soup = BeautifulSoup(html, "html.parser")
        data = {}
        for el in soup.find_all("input"):
            if el.get("name") and (el.get("type") or "").lower() not in ("submit", "button", "image", "checkbox", "radio"):
                data[el["name"]] = el.get("value") or ""
        for sel in soup.find_all("select"):
            if sel.get("name"):
                opt = sel.find("option", selected=True) or sel.find("option")
                data[sel["name"]] = (opt.get("value") if opt else "") or ""
        return soup, data

    prm = re.search(r"PageRequestManager\._initialize\('([^']+)'\s*,\s*'([^']+)'", resp.text)
    panels = re.findall(r"updatePanelIDs['\"]?\s*[:=]\s*\[([^\]]*)\]|_updateControls\(\[([^\]]*)\]", resp.text)
    postbacks = sorted(set(re.findall(r"__doPostBack\(\\?'([^'\\]+)", resp.text)))[:40]
    steps.append({"script_manager": prm.group(1) if prm else None, "panels": [mask_digits(";".join(p))[:400] for p in panels][:3],
                  "postback_targets": postbacks})
    soup, data = form_state(resp.text)
    for dd in dropdowns:
        sel = soup.find("select", attrs={"name": dd})
        opts = [o.get("value") for o in (sel.find_all("option") if sel else []) if (o.get("value") or "").strip()]
        steps.append({"dropdown": dd, "options": len(opts)})
        if not opts:
            break
        data[dd] = opts[0]
        data["__EVENTTARGET"], data["__EVENTARGUMENT"] = dd, ""
        hdrs = dict(HEADERS)
        if prm:
            # An async (UpdatePanel) postback, the way the page's own script sends it.
            data[prm.group(1)] = f"{prm.group(1)}|{dd}"
            data["__ASYNCPOST"] = "true"
            hdrs.update({"X-MicrosoftAjax": "Delta=true", "X-Requested-With": "XMLHttpRequest"})
        try:
            r = session.post(url, data=data, headers=hdrs, timeout=30)
        except requests.RequestException as exc:
            return {"steps": steps, "error": f"{type(exc).__name__}"}
        body = r.text
        if prm and "|updatePanel|" in body:
            # Delta response: re-read hidden fields and the refreshed panel HTML.
            frags = re.findall(r"\|updatePanel\|[^|]*\|(.*?)\|", body, re.S)
            hidden = dict(re.findall(r"\|hiddenField\|([^|]+)\|([^|]*)\|", body))
            steps[-1].update({"delta": True, "delta_len": len(body), "panels_returned": len(frags)})
            soup_panel = BeautifulSoup("".join(frags), "html.parser")
            for sel in soup_panel.find_all("select"):
                if sel.get("name"):
                    steps.append({"refreshed_select": sel["name"], "options": len(sel.find_all("option"))})
            soup = BeautifulSoup(resp.text + "".join(frags), "html.parser")
            data.update(hidden)
            for k in ("__ASYNCPOST",):
                data.pop(k, None)
            if prm:
                data.pop(prm.group(1), None)
        else:
            soup, data = form_state(body)
        data[dd] = opts[0]
        time.sleep(1.0)
    data.pop("__EVENTTARGET", None)
    data[button] = "Search"
    try:
        r = session.post(url, data=data, headers=HEADERS, timeout=45)
    except requests.RequestException as exc:
        return {"steps": steps, "error": f"{type(exc).__name__}"}
    out = html_structure(r.text, r.url)
    out.pop("links", None)
    out["steps"] = steps
    out["status"] = r.status_code
    return out


def arcgis_item(session: requests.Session, item_id: str) -> dict:
    """One ArcGIS Online item's own metadata: title, owner, licence and
    access text, and its service's layers (fields, counts, id shapes)."""
    resp, err = fetch(session, f"https://www.arcgis.com/sharing/rest/content/items/{item_id}?f=json")
    if err or resp is None or resp.status_code != 200:
        return {"id": item_id, "error": err or f"status {getattr(resp, 'status_code', None)}"}
    try:
        it = resp.json()
    except ValueError:
        return {"id": item_id, "error": "not json"}
    rec = {"id": item_id, "title": it.get("title"), "type": it.get("type"), "owner": it.get("owner"), "org": it.get("orgId"),
           "url": it.get("url"), "modified": it.get("modified"), "tags": (it.get("tags") or [])[:12],
           "snippet": strip_html(it.get("snippet") or "")[:240], "description": mask_digits(strip_html(it.get("description") or ""))[:900],
           "license": strip_html(it.get("licenseInfo") or "")[:2400], "access": strip_html(it.get("accessInformation") or "")[:300]}
    if it.get("url") and ARCGIS_SERVICE_RE.search(it["url"]):
        rec["layers"] = arcgis_layer_meta(session, it["url"])
    return rec


def arcgis_discover(session: requests.Session, query: str, *, limit: int = 25) -> list[dict]:
    """ArcGIS Online's own catalog search for public items matching `query`:
    who publishes them, their licence / access text, and (for services) the
    layers' field names and counts."""
    params = {"q": query, "f": "json", "num": limit, "sortField": "modified", "sortOrder": "desc"}
    resp, err = fetch(session, ARCGIS_SEARCH + "?" + urlencode(params))
    if err or resp is None or resp.status_code != 200:
        return [{"error": err or f"status {getattr(resp, 'status_code', None)}"}]
    items = []
    for it in (resp.json().get("results") or [])[:limit]:
        rec = {"id": it.get("id"), "title": it.get("title"), "type": it.get("type"), "owner": it.get("owner"),
               "org": it.get("orgId"), "url": it.get("url"), "modified": it.get("modified"),
               "tags": (it.get("tags") or [])[:12], "snippet": strip_html(it.get("snippet") or "")[:240],
               "license": strip_html(it.get("licenseInfo") or "")[:600], "access": strip_html(it.get("accessInformation") or "")[:240]}
        if it.get("type") in ("Feature Service", "Map Service") and it.get("url"):
            rec["layers"] = arcgis_layer_meta(session, it["url"])
        items.append(rec)
        time.sleep(0.3)
    return items


# Diversified AVAILABLE sprint (2026-10-04): the five states ranked first by
# the national AVAILABLE opportunity review (MS, PA, MO, MN, OK). Every fact
# about them is search-index evidence until this pass reads them from a
# runner. Read once, value-free (--available-five): page structure and
# process / terms sentences, CSV / Socrata / ArcGIS metadata and identifier
# SHAPES, PDF / XLSX table headers and row counts, and the data-service URLs a
# map application embeds. Never a row value, never an owner name.
AVAILABLE_FIVE_PAGES = {
    "MS": ["https://www.sos.ms.gov/public-lands/tax-forfeited-lands",
           "https://www.sos.ms.gov/public-lands/tax-forfeited-lands-faqs",
           "https://tfportal.sos.ms.gov/"],
    "PA": ["https://www.westmorelandcountypa.gov/2722/Repository-List",
           "https://www.westmorelandcountypa.gov/3480/Repository-Procedures",
           "https://public.eriecountypa.gov/property-tax-records/sales/tax-sales/repository-list.aspx",
           "https://schuylkillcountytaxclaim.com/repository/",
           "https://www.cambriacountypa.gov/tax-claim-bureau/",
           "https://www.fayettecountypa.org/DocumentCenter/View/9761",
           "https://www.berkspa.gov/departments/tax-claim/repository",
           "https://philadelphialandbank.org/"],
    "MO": ["https://www.stlouis-mo.gov/data/datasets/dataset.cfm?id=30",
           "https://www.stlouis-mo.gov/data/datasets/distribution.cfm?id=146",
           "https://www.stlouis-mo.gov/data/datasets/distribution.cfm?id=145",
           "https://www.stlouis-mo.gov/government/departments/sldc/real-estate/lra-owned-property-search.cfm",
           "https://www.stlouis-mo.gov/data/terms-of-use.cfm",
           "https://data.kcmo.org/api/views/4257-6mtc.json",
           "https://www.kcmo.gov/city-hall/housing/landbank",
           "https://stlouiscountymo.gov/st-louis-county-departments/revenue/collector-of-revenue/post-third-sale-offerings/"],
    "MN": ["https://www.co.wright.mn.us/1540/Tax-Forfeited-Land",
           "https://www.hubbardcounty.gov/tfl",
           "https://www.stlouiscountymn.gov/departments-a-z/land-minerals/sales-and-contracts/tax-forfeited-land-sales",
           "https://www.hennepincounty.gov/services/property/tax-forfeited-land",
           "https://www.ramseycounty.us/residents/property-home/tax-forfeited-land"],
    "OK": ["https://docs.oklahomacounty.org/treasurer/CountyOwnedList.asp",
           "https://www.oklahomacounty.org/elected-offices/treasurer",
           "https://www2.tulsacounty.org/treasurer/properties-for-sale/county-properties/",
           "https://www.clevelandcountytreasurer.org/portals/0/Cleveland%20Documents/County%20Owned%20Propery%20List%2006-14-2023.pdf"],
}
# Map applications whose embedded data services we need (script / config scan).
AVAILABLE_FIVE_APPS = {
    "MS": ["https://tflgis.sos.ms.gov/"],
    "MN": ["https://www.hubbardcounty.gov/tfl"],
}
AVAILABLE_FIVE_SERVICES = {
    "MN": ["https://maps.co.ramsey.mn.us/arcgis/rest/services/PRR/TaxForfeitLand_PublicData/MapServer",
           "https://gisweb.co.wilkin.mn.us/arcgis/rest/services/Auditor/TaxForfeitSales/FeatureServer"],
}
AVAILABLE_FIVE_DIRECTORIES = {
    "MS": ["https://tflgis.sos.ms.gov/arcgis/rest/services", "https://gis.sos.ms.gov/arcgis/rest/services",
           "https://maps.sos.ms.gov/arcgis/rest/services"],
}
AVAILABLE_FIVE_QUERIES = ('"tax forfeited" Mississippi', '"Tax Forfeited Lands" sos.ms.gov',
                          '"tax forfeited" Minnesota type:"Feature Service"', '"tax forfeit" county Minnesota parcels sale',
                          '"repository" "tax claim" Pennsylvania', 'LRA "Land Reutilization Authority" St. Louis',
                          '"county owned" Oklahoma County treasurer', '"land bank" Kansas City properties')
SERVICE_URL_RE = re.compile(r"https?://[A-Za-z0-9._/-]+?/(?:FeatureServer|MapServer)(?:/\d+)?", re.I)
ITEM_ID_RE = re.compile(r"(?:webmap|itemId|appid|id)[\"'=:\s]+([0-9a-f]{32})", re.I)


def app_services(session: requests.Session, url: str, *, max_assets: int = 12) -> dict:
    """The ArcGIS data services and item ids a map application embeds in its
    page and same-host scripts / config files. URLs and ids only."""
    out = {"url": url, "kind": "app_services"}
    resp, err = fetch(session, url)
    if err or resp is None:
        out["error"] = err
        return out
    out.update({"status": resp.status_code, "final_url": resp.url, "content_type": resp.headers.get("Content-Type", "")})
    texts = [resp.text]
    host = urlsplit(resp.url).hostname or ""
    assets = re.findall(r"""(?:src|href)=["']([^"']+\.(?:js|json))["']""", resp.text, re.I)
    assets += [a for a in ("config.json", "app/config.json", "config/config.json") ]
    seen = set()
    for a in assets:
        full = urljoin(resp.url, a)
        if full in seen or (urlsplit(full).hostname or "") != host or len(seen) >= max_assets:
            continue
        seen.add(full)
        r, e = fetch(session, full)
        if r is not None and r.status_code == 200:
            texts.append(r.text[:3_000_000])
        time.sleep(0.4)
    blob = "\n".join(texts)
    out["assets_read"] = len(seen)
    out["services"] = sorted(set(SERVICE_URL_RE.findall(blob)))[:40]
    out["item_ids"] = sorted(set(ITEM_ID_RE.findall(blob)))[:20]
    return out


def doc_tables(session: requests.Session, url: str, *, max_pages: int = 400) -> dict:
    """A PDF / XLSX list's table STRUCTURE: header cells (digits masked), the
    number of body rows over the whole document and each column's value
    SHAPES (digits -> 9, letters -> A) from its first 200 rows."""
    out = {"url": url, "kind": "doc_tables"}
    resp, err = fetch(session, url)
    if err or resp is None:
        out["error"] = err
        return out
    ctype = resp.headers.get("Content-Type", "").lower()
    out.update({"status": resp.status_code, "final_url": resp.url, "content_type": ctype,
                "last_modified": resp.headers.get("Last-Modified"), "bytes": len(resp.content)})
    if resp.status_code != 200:
        return out
    rows: list[list[str]] = []
    try:
        if "pdf" in ctype or resp.content[:4] == b"%PDF":
            import pdfplumber  # noqa: PLC0415
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                out["pages"] = len(pdf.pages)
                for pg in pdf.pages[:max_pages]:
                    for t in pg.extract_tables() or []:
                        rows.extend([[clean(c or "") for c in r] for r in t if r])
        elif "sheet" in ctype or "excel" in ctype or url.lower().endswith((".xlsx", ".xls")) or resp.content[:2] == b"PK":
            import openpyxl  # noqa: PLC0415
            wb = openpyxl.load_workbook(io.BytesIO(resp.content), read_only=True, data_only=True)
            out["sheets"] = wb.sheetnames[:10]
            ws = wb[wb.sheetnames[0]]
            for r in ws.iter_rows(values_only=True):
                rows.append([clean("" if c is None else str(c)) for c in r])
        else:
            out["note"] = "not a PDF / spreadsheet"
            return out
    except Exception as exc:  # noqa: BLE001
        out["parse_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return out
    out.update(table_structure(rows))
    return out


# A header cell is printed only when it reads like a column NAME. A data row
# mistaken for the header (an owner name, a street) is never printed: its
# cells become "?" and its column keys "colN".
HEADER_VOCAB = re.compile(r"^(?:[A-Za-z#./&()' _-]{0,40})$")
HEADER_WORDS = re.compile(r"parcel|pin|map|account|acct|property|address|location|street|legal|desc|owner|name|municipal|"
                          r"township|city|county|district|ward|neighbo|bid|price|amount|value|minimum|min\.?|sale|date|year|"
                          r"status|type|class|usage|use|zoning|acre|sq|size|record|id|number|no\.?|#|comment|remark|tax|"
                          r"deed|cert|lot|block|section", re.I)


def header_cell(text: str) -> str | None:
    t = clean(text or "")
    if not t:
        return ""
    if re.search(r"\d", t) or not HEADER_VOCAB.match(t) or not HEADER_WORDS.search(t):
        return None
    return t[:40]


def table_structure(rows: list[list[str]]) -> dict:
    """Header names (only cells that read like column names), the body-row
    count and each column's value SHAPES (digits -> 9, letters -> A). No free
    text: no first lines, no snippets, no cell value."""
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return {"table_rows": 0}
    def is_header(r):
        named = [header_cell(c) for c in r]
        return sum(1 for c in named if c) >= max(2, len(r) // 2)
    head_i = next((i for i, r in enumerate(rows[:15]) if is_header(r)), None)
    if head_i is None:
        header, body = [None] * max(len(r) for r in rows), rows
    else:
        header = [header_cell(c) for c in rows[head_i]]
        body = [r for r in rows[head_i + 1:] if r != rows[head_i]]
    keys = [h if h else f"col{i}" for i, h in enumerate(header)]
    return {"header": [h if h is not None else "?" for h in header], "table_rows": len(body),
            "col_shapes": {keys[i]: dict(Counter(shape(r[i])[:30] for r in body[:200] if i < len(r) and r[i]).most_common(4))
                           for i in range(len(keys))}}
    head_i = next((i for i, r in enumerate(rows[:15]) if sum(1 for c in r if c and not re.search(r"\d", c)) >= max(2, len(r) // 2)), 0)
    header = rows[head_i]
    body = [r for r in rows[head_i + 1:] if r != header]
    out["header"] = [mask_digits(h)[:60] for h in header]
    out["table_rows"] = len(body)
    out["col_shapes"] = {mask_digits(h)[:40] or f"col{i}": dict(Counter(shape(r[i])[:30] for r in body[:200] if i < len(r) and r[i]).most_common(4))
                         for i, h in enumerate(header)}
    return out


# Pass 2 (2026-10-04): the gaps the first available-five pass left.
FIVE2_CSV_VALUES = {  # categorical columns only - vocabulary, never a row
    "https://static.stlouis-mo.gov/open-data/SLDC/REAL-ESTATE/LRA_INVENTORY.csv":
        ["Parcel_Status", "Usage", "PropertyType", "Class", "Property_Source", "Side lot Eligible?", "Stories", "Irregular_Lot"],
    "https://static.stlouis-mo.gov/open-data/SLDC/REAL-ESTATE/LRA_INVENTORY_AVAILABLE.csv":
        ["Usage", "PropertyType", "Class"],
}
FIVE2_PAGES = {  # (url, follow-link vocabulary)
    "MO": [("https://www.stlouis-mo.gov/government/property/city-owned-property-search.cfm", r"buy|purchas|offer|apply|application|price|how to|lra"),
           ("https://www.stlouis-mo.gov/data/", r"terms|polic|licen|disclaim|about")],
    "OK": [("https://docs.oklahomacounty.org/treasurer/CountyOwnedList.asp", r"$^")],
    "PA": [("https://www.fayettecountypa.org/Search?searchPhrase=repository", r"repository|tax claim"),
           ("https://www.stlouiscountymn.gov/departments-a-z/land-minerals/sales-and-contracts/tax-forfeited-land-sales", r"available list|over the counter")],
}
FIVE2_NOTICE = re.compile(r"notice|provide|warrant|responsib|accura|purchase|bid|sale|deed|commission|statut|minimum|suggest", re.I)
FIVE2_PDF_LINES = ["https://www.westmorelandcountypa.gov/DocumentCenter/View/13562/Repository-List?bidId="]
FIVE2_LAYER_PROBES = {
    "MN": [("https://maps.co.ramsey.mn.us/arcgis/rest/services/PRR/TaxForfeitLand_PublicData/MapServer/0", "1=1",
            ["PIN"], ["Status", "Archive", "AuctionID", "Zoning", "Municipality", "FourRProperty"])],
}
FIVE2_ITEMS = {"MN": ["d04f4637a2794aa19f1767f8b7fba8d6"]}
FIVE2_APPS = ["https://tflgis.sos.ms.gov/"]


def csv_value_counts(session: requests.Session, url: str, columns: list[str]) -> dict:
    """The VOCABULARY of a CSV's categorical columns: distinct value counts
    (digits masked, 40 chars). Only the named columns are read."""
    out = {"url": url + " (column values)", "kind": "table_values"}
    resp, err = fetch(session, url, stream=True)
    if err or resp is None or resp.status_code != 200:
        out["error"] = err or f"status {getattr(resp, 'status_code', None)}"
        return out
    raw = b""
    for chunk in resp.iter_content(65536):
        raw += chunk
        if len(raw) >= 8_000_000:
            break
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))))
    out["count"] = len(rows)
    out["value_counts"] = {c: dict(Counter(mask_digits(clean(r.get(c) or ""))[:40] for r in rows).most_common(15)) for c in columns}
    return out


def page_notice(session: requests.Session, url: str) -> dict:
    """Sentences of a list page's own notice / process text (digits masked),
    excluding every table cell - the rows themselves are never read out."""
    out = {"url": url + " (notice)", "kind": "process"}
    resp, err = fetch(session, url)
    if err or resp is None or resp.status_code != 200 or BeautifulSoup is None:
        out["error"] = err or f"status {getattr(resp, 'status_code', None)}"
        return out
    soup = BeautifulSoup(resp.text, "html.parser")
    notes = []
    for t in soup.find_all("table"):
        for td in t.find_all(["td", "th"]):
            txt = clean(td.get_text(" "))
            if len(txt) > 60 and FIVE2_NOTICE.search(txt) and len(td.find_all("td")) == 0:
                notes.append(mask_digits(txt)[:600])
        t.decompose()
    text = clean(soup.get_text(" "))
    out["snippets"] = (notes[:4] + [mask_digits(x)[:320] for x in re.split(r"(?<=[.!?])\s+", text) if len(x) > 40 and FIVE2_NOTICE.search(x)][:20])
    return out


def pdf_line_shapes(session: requests.Session, url: str, max_pages: int = 40) -> dict:
    """A text-layout PDF list's line STRUCTURE: how many lines, and the most
    common line shapes (digits -> 9, letters -> A, runs collapsed) - enough to
    write a parser, never a value."""
    out = {"url": url, "kind": "doc_tables"}
    resp, err = fetch(session, url)
    if err or resp is None or resp.status_code != 200:
        out["error"] = err or f"status {getattr(resp, 'status_code', None)}"
        return out
    try:
        import pdfplumber  # noqa: PLC0415
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            out["pages"] = len(pdf.pages)
            lines = []
            for pg in pdf.pages[:max_pages]:
                lines.extend(l for l in (pg.extract_text() or "").splitlines() if l.strip())
    except Exception as exc:  # noqa: BLE001
        out["parse_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return out
    def squash(line):
        return re.sub(r"A{2,}", "A+", re.sub(r"9{2,}", "9+", shape(line)))[:90]
    out["table_rows"] = len(lines)
    out["col_shapes"] = {"line_shape": dict(Counter(squash(l) for l in lines).most_common(25))}
    # Header vocabulary only: from the first 40 lines, the WORDS that are
    # column names (parcel, owner, bid, ...). A line is never printed.
    words = []
    for l in lines[:40]:
        toks = [t for t in re.split(r"[\s/|]+", l) if t and HEADER_WORDS.fullmatch(t.strip(".:#()").lower() or "x")]
        if len(toks) >= 3:
            words.append(" ".join(t.strip(".:()") for t in toks)[:120])
    out["header"] = words[:6]
    return out


def item_services(session: requests.Session, item_id: str) -> dict:
    """An ArcGIS Online app / web map item's data: the web map it opens and
    the service URLs of its operational layers. URLs only."""
    out = {"url": f"item:{item_id} (data)", "kind": "app_services", "services": [], "item_ids": []}
    base = "https://www.arcgis.com/sharing/rest/content/items/"
    r, e = fetch(session, f"{base}{item_id}/data?f=json")
    try:
        data = r.json() if r is not None and r.status_code == 200 else {}
    except ValueError:
        data = {}
    blob = json.dumps(data)
    maps = sorted(set(re.findall(r'"(?:webmap|itemId|id)"\s*:\s*"([0-9a-f]{32})"', blob)))
    out["item_ids"] = maps[:10]
    urls = set(SERVICE_URL_RE.findall(blob))
    for m in maps[:3]:
        r2, _ = fetch(session, f"{base}{m}/data?f=json")
        if r2 is not None and r2.status_code == 200:
            urls |= set(SERVICE_URL_RE.findall(r2.text))
    out["services"] = sorted(urls)[:20]
    return out


def app_hosts(session: requests.Session, url: str) -> dict:
    """Every absolute URL host + path a map app's page and scripts reference
    (any host), filtered to map / data endpoints. URLs only."""
    out = {"url": url + " (endpoints)", "kind": "app_services", "services": [], "item_ids": []}
    resp, err = fetch(session, url)
    if err or resp is None:
        out["error"] = err
        return out
    texts, seen = [resp.text], set()
    for a in re.findall(r"""(?:src|href)=["']([^"']+)["']""", resp.text, re.I):
        full = urljoin(resp.url, a)
        if full in seen or len(seen) >= 15 or not re.search(r"\.(js|json)(\?|$)", full):
            continue
        seen.add(full)
        r, _ = fetch(session, full)
        if r is not None and r.status_code == 200:
            texts.append(r.text[:4_000_000])
    blob = "\n".join(texts)
    out["assets"] = sorted(seen)[:15]
    found = set(re.findall(r"https?://[A-Za-z0-9.-]+(?:/[A-Za-z0-9._~%/-]*)?", blob))
    out["services"] = sorted(u for u in found if re.search(r"rest/services|FeatureServer|MapServer|/api/|arcgis|query|parcel|forfeit", u, re.I))[:40]
    out["item_ids"] = sorted(set(re.findall(r"\b[0-9a-f]{32}\b", blob)))[:10]
    return out


# Pass 3 (2026-10-04): Mississippi only - the map app's script references the
# State ITS ArcGIS server; find the tax-forfeited-lands layer there.
FIVE3_DIRECTORY = "https://gisserver.its.ms.gov/arcgis/rest/services"
FIVE3_FOLDER_RE = re.compile(r"sos|tfl|forfeit|public.?land|land", re.I)
FIVE3_ITEMS = ["bae26a0f2eaa455280a85537d4f3ea0a", "d74c6b741a83487e8ca56bc8ceafbd27"]


def directory_crawl(session: requests.Session, root: str, folder_re, *, max_services: int = 12) -> list[dict]:
    """An ArcGIS server's directory (root + folders matching folder_re): every
    service whose name matches folder_re gets its layers' metadata."""
    pages = []
    top = arcgis_directory(session, root)
    pages.append({"url": root, "kind": "arcgis_directory", **top})
    names = list(top.get("services") or [])
    for folder in top.get("folders") or []:
        if folder_re.search(folder):
            sub = arcgis_directory(session, f"{root}/{folder}")
            pages.append({"url": f"{root}/{folder}", "kind": "arcgis_directory", **sub})
            names += list(sub.get("services") or [])
    done = 0
    for name in names:
        svc_name = name.split(" ")[0]
        if not folder_re.search(svc_name) or done >= max_services:
            continue
        kind = "MapServer" if "MapServer" in name else "FeatureServer"
        url = f"{root}/{svc_name.split(':')[0]}/{kind}"
        pages.append({"url": url, "kind": "arcgis", "layers": arcgis_layer_meta(session, url)})
        done += 1
        time.sleep(0.5)
    return pages


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--digest", default=None)
    ap.add_argument("--state", action="append", default=[])
    ap.add_argument("--arcgis-search", action="append", default=[], help="ArcGIS Online catalog query (repeatable); metadata only")
    ap.add_argument("--skip-registry", action="store_true")
    ap.add_argument("--discovery", action="store_true", help="also read DISCOVERY_PAGES and run DISCOVERY_QUERIES")
    ap.add_argument("--expansion", action="store_true", help="read EXPANSION_TARGETS and run EXPANSION_QUERIES (six-state sprint)")
    ap.add_argument("--five-state", action="store_true", help="read FIVE_STATE_* candidates (five-state enrichment sprint)")
    ap.add_argument("--five-state-pass2", action="store_true", help="read the FIVE_STATE_PASS2 / PROBES targets")
    ap.add_argument("--five-state-pass3", action="store_true", help="read the FIVE_STATE_PASS3 targets")
    ap.add_argument("--enrich-sources-4", action="store_true", help="round 4 of the enrichment-source capture")
    ap.add_argument("--enrich-sources-3", action="store_true", help="round 3 of the enrichment-source capture")
    ap.add_argument("--enrich-sources-2", action="store_true", help="round 2 of the enrichment-source capture")
    ap.add_argument("--enrich-sources", action="store_true", help="read the ENRICH_* parcel / tax-roll candidates (property-enrichment sprint)")
    ap.add_argument("--available-five", action="store_true", help="read the AVAILABLE_FIVE_* candidates (MS, PA, MO, MN, OK)")
    ap.add_argument("--available-five-2", action="store_true", help="pass 2 of the available-five capture")
    ap.add_argument("--available-five-3", action="store_true", help="pass 3 (Mississippi state GIS server)")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args(argv)
    if args.digest:
        print(digest(Path(args.digest)))
        return 0
    wanted = set(args.state) or set(CANDIDATE_STATES)
    session = requests.Session()
    report: dict = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "states": {}}
    with open(REGISTRY, newline="", encoding="utf-8") as fh:
        rows = [] if args.skip_registry else [r for r in csv.DictReader(fh) if r["state"] in wanted]
    for code, urls in DISCOVERY_PAGES.items():
        if not args.discovery:
            break
        entry = {"source_id": f"discovery_{code.lower()}", "county": "(discovery)", "pages": []}
        for url in urls:
            entry["pages"].append(capture(session, url, "discovery"))
            print(f"  {code} discovery      {entry['pages'][-1].get('status', entry['pages'][-1].get('error'))} {url}", flush=True)
            time.sleep(0.8)
        report["states"].setdefault(code, {"sources": []})["sources"].append(entry)
    targets = dict(EXPANSION_TARGETS)
    for extra in (EXPANSION_ITEMS, EXPANSION_EXTRA):
        for code in extra:
            targets.setdefault(code, [])
    for code, urls in targets.items():
        if not args.expansion or (args.state and code not in args.state):
            continue
        entry = {"source_id": f"expansion_{code.lower()}", "county": "(expansion)", "pages": []}
        seen: set[str] = set()
        for url in urls:
            seen.add(url)
            if ARCGIS_SERVICE_RE.search(url):
                page = {"url": url, "kind": "arcgis", "layers": arcgis_layer_meta(session, url)}
                print(f"  {code} arcgis         {len(page['layers'])} layer(s) {url}", flush=True)
            else:
                page = capture(session, url, "expansion")
                print(f"  {code} expansion      {page.get('status', page.get('error'))} {url}", flush=True)
            entry["pages"].append(page)
            time.sleep(0.8)
        for url in EXPANSION_EXTRA.get(code, []):
            if url in seen:
                continue
            seen.add(url)
            page = capture(session, url, "extra")
            print(f"  {code} extra          {page.get('status', page.get('error'))} {url}", flush=True)
            entry["pages"].append(page)
            time.sleep(0.8)
        # One hop to listing / terms links the pages themselves carry (same host).
        followed = 0
        for pg in list(entry["pages"]):
            for link in pg.get("links") or []:
                href = link["href"]
                if href in seen or followed >= MAX_FOLLOW or not FOLLOW_VOCAB.search(link["text"] + " " + urlsplit(href).path):
                    continue
                if (urlsplit(href).hostname or "") != (urlsplit(pg.get("final_url") or pg["url"]).hostname or ""):
                    continue
                seen.add(href)
                followed += 1
                page = capture(session, href, "follow")
                page["link_text"] = link["text"]
                entry["pages"].append(page)
                print(f"  {code} follow         {page.get('status', page.get('error'))} {href}", flush=True)
                time.sleep(0.8)
        if code in ASPNET_PROBES:
            purl, dds, btn = ASPNET_PROBES[code]
            probe = aspnet_probe(session, purl, dds, btn)
            entry["pages"].append({"url": purl + " (postback probe)", "kind": "aspnet_probe", **probe})
            print(f"  {code} aspnet probe   {probe.get('status', probe.get('error'))} steps={probe.get('steps')}", flush=True)
        for item_id in EXPANSION_ITEMS.get(code, []):
            entry["pages"].append({"url": f"item:{item_id}", "kind": "arcgis_item", **arcgis_item(session, item_id)})
            print(f"  {code} item           {item_id}", flush=True)
            time.sleep(0.5)
        follow = 0
        for pg in list(entry["pages"]):
            for link in pg.get("terms_links") or []:
                href = link["href"]
                if href in seen or follow >= MAX_TERMS_FOLLOW * 2:
                    continue
                if ".".join((urlsplit(href).hostname or "").split(".")[-2:]) != ".".join((urlsplit(pg.get("final_url") or pg["url"]).hostname or "").split(".")[-2:]):
                    continue
                seen.add(href)
                follow += 1
                page = capture(session, href, "terms")
                page["link_text"] = link["text"]
                entry["pages"].append(page)
                print(f"  {code} terms          {page.get('status', page.get('error'))} {href}", flush=True)
                time.sleep(0.8)
        report["states"].setdefault(code, {"sources": []})["sources"].append(entry)
    for code in sorted(set(FIVE_STATE_PAGES) | set(FIVE_STATE_SERVICES) | set(FIVE_STATE_DIRECTORIES) | set(FIVE_STATE_ITEMS)):
        if not args.five_state or (args.state and code not in args.state):
            continue
        entry = {"source_id": f"five_state_{code.lower()}", "county": "(five-state)", "pages": []}
        for url in FIVE_STATE_PAGES.get(code, []):
            page = capture(session, url, "process", process=True)
            print(f"  {code} process        {page.get('status', page.get('error'))} {url}", flush=True)
            entry["pages"].append(page)
            time.sleep(0.8)
        for url in FIVE_STATE_SERVICES.get(code, []):
            page = {"url": url, "kind": "arcgis", "layers": arcgis_layer_meta(session, url)}
            print(f"  {code} arcgis         {len(page['layers'])} layer(s) {url}", flush=True)
            entry["pages"].append(page)
            time.sleep(0.8)
        for url in FIVE_STATE_DIRECTORIES.get(code, []):
            page = {"url": url, "kind": "arcgis_directory", **arcgis_directory(session, url)}
            print(f"  {code} directory      {len(page.get('services') or [])} service(s) {url}", flush=True)
            entry["pages"].append(page)
            time.sleep(0.8)
        for item_id in FIVE_STATE_ITEMS.get(code, []):
            entry["pages"].append({"url": f"item:{item_id}", "kind": "arcgis_item", **arcgis_item(session, item_id)})
            print(f"  {code} item           {item_id}", flush=True)
            time.sleep(0.5)
        report["states"].setdefault(code, {"sources": []})["sources"].append(entry)
    if args.available_five:
        for code in sorted(set(AVAILABLE_FIVE_PAGES) | set(AVAILABLE_FIVE_APPS) | set(AVAILABLE_FIVE_SERVICES) | set(AVAILABLE_FIVE_DIRECTORIES)):
            if args.state and code not in args.state:
                continue
            entry = {"source_id": f"available_five_{code.lower()}", "county": "(available five)", "pages": []}
            seen5: set[str] = set()
            for url in AVAILABLE_FIVE_PAGES.get(code, []):
                seen5.add(url)
                if re.search(r"DocumentCenter/View|\.pdf$|\.xlsx?$", url, re.I):
                    page = doc_tables(session, url)
                    entry["pages"].append(page)
                else:
                    page = capture(session, url, "process", process=True)
                    entry["pages"].append(page)
                print(f"  {code} five           {page.get('status', page.get('error'))} {url}", flush=True)
                time.sleep(0.8)
            # One hop to the lists / documents / terms the pages link (same site).
            followed = 0
            for pg in list(entry["pages"]):
                base_host = ".".join((urlsplit(pg.get("final_url") or pg["url"]).hostname or "").split(".")[-2:])
                for link in (pg.get("links") or []) + (pg.get("terms_links") or []):
                    href = link["href"]
                    if href in seen5 or followed >= 14:
                        continue
                    if ".".join((urlsplit(href).hostname or "").split(".")[-2:]) != base_host:
                        continue
                    is_doc = re.search(r"\.(pdf|xlsx?|csv)(\?|$)|DocumentCenter/View|distribution\.cfm", href, re.I)
                    if not (is_doc or FOLLOW_VOCAB.search(link["text"] + " " + urlsplit(href).path) or TERMS_VOCAB.search(link["text"])
                            or re.search(r"repository|land bank|forfeit|county.owned|available", link["text"] + " " + href, re.I)):
                        continue
                    seen5.add(href)
                    followed += 1
                    page = doc_tables(session, href) if is_doc and not href.lower().endswith(".csv") and "distribution.cfm" not in href else capture(session, href, "follow", process=True)
                    page["link_text"] = mask_digits(link["text"])[:80]
                    entry["pages"].append(page)
                    print(f"  {code} follow         {page.get('status', page.get('error'))} {href}", flush=True)
                    time.sleep(0.8)
            for url in AVAILABLE_FIVE_APPS.get(code, []):
                page = app_services(session, url)
                entry["pages"].append(page)
                print(f"  {code} app            services={len(page.get('services') or [])} items={len(page.get('item_ids') or [])} {url}", flush=True)
                for svc in (page.get("services") or [])[:6]:
                    root = re.sub(r"/\d+$", "", svc)
                    entry["pages"].append({"url": root, "kind": "arcgis", "layers": arcgis_layer_meta(session, root)})
                    time.sleep(0.6)
                for item_id in (page.get("item_ids") or [])[:6]:
                    entry["pages"].append({"url": f"item:{item_id}", "kind": "arcgis_item", **arcgis_item(session, item_id)})
                    time.sleep(0.5)
            for url in AVAILABLE_FIVE_SERVICES.get(code, []):
                page = {"url": url, "kind": "arcgis", "layers": arcgis_layer_meta(session, url)}
                print(f"  {code} arcgis         {len(page['layers'])} layer(s) {url}", flush=True)
                entry["pages"].append(page)
                time.sleep(0.8)
            for url in AVAILABLE_FIVE_DIRECTORIES.get(code, []):
                page = {"url": url, "kind": "arcgis_directory", **arcgis_directory(session, url)}
                print(f"  {code} directory      {len(page.get('services') or [])} service(s) {url}", flush=True)
                entry["pages"].append(page)
                time.sleep(0.8)
            report["states"].setdefault(code, {"sources": []})["sources"].append(entry)
        for q in AVAILABLE_FIVE_QUERIES:
            report.setdefault("arcgis", {})[q] = arcgis_discover(session, q)
            print(f"  arcgis search {q!r}: {len(report['arcgis'][q])} item(s)", flush=True)
    if args.available_five_2:
        e2 = {"source_id": "available_five_pass2", "county": "(available five pass 2)", "pages": []}
        for url, cols in FIVE2_CSV_VALUES.items():
            e2["pages"].append(csv_value_counts(session, url, cols))
            print(f"  five2 csv values  {e2['pages'][-1].get('count', e2['pages'][-1].get('error'))} {url}", flush=True)
        for code, items in FIVE2_PAGES.items():
            for url, vocab in items:
                if "CountyOwnedList" in url:
                    e2["pages"].append(page_notice(session, url))
                    print(f"  five2 notice      {url}", flush=True)
                    continue
                page = capture(session, url, "process", process=True)
                e2["pages"].append(page)
                print(f"  five2 page        {page.get('status', page.get('error'))} {url}", flush=True)
                n = 0
                for link in page.get("links") or []:
                    href = link["href"]
                    if n >= 6 or not re.search(vocab, link["text"] + " " + href, re.I):
                        continue
                    n += 1
                    is_doc = re.search(r"\.(pdf|xlsx?)(\?|$)|DocumentCenter/View", href, re.I)
                    sub = doc_tables(session, href) if is_doc else capture(session, href, "follow", process=True)
                    sub["link_text"] = mask_digits(link["text"])[:80]
                    e2["pages"].append(sub)
                    print(f"  five2 follow      {sub.get('status', sub.get('error'))} {href}", flush=True)
                    time.sleep(0.6)
                time.sleep(0.6)
        for url in FIVE2_PDF_LINES:
            e2["pages"].append(pdf_line_shapes(session, url))
            print(f"  five2 pdf lines   {e2['pages'][-1].get('table_rows')} {url}", flush=True)
        for code, probes in FIVE2_LAYER_PROBES.items():
            for layer, where, ids, cats in probes:
                e2["pages"].append(layer_probe(session, layer, where, ids, cats))
                print(f"  five2 probe       count={e2['pages'][-1].get('count')} {layer}", flush=True)
        for code, items in FIVE2_ITEMS.items():
            for item_id in items:
                page = item_services(session, item_id)
                e2["pages"].append(page)
                print(f"  five2 item        services={len(page['services'])} {item_id}", flush=True)
                for svc in page["services"][:4]:
                    root = re.sub(r"/\d+$", "", svc)
                    e2["pages"].append({"url": root, "kind": "arcgis", "layers": arcgis_layer_meta(session, root)})
        for url in FIVE2_APPS:
            page = app_hosts(session, url)
            e2["pages"].append(page)
            print(f"  five2 app hosts   services={len(page.get('services') or [])} {url}", flush=True)
        report["states"].setdefault("ZZ", {"sources": []})["sources"].append(e2)
    if args.available_five_3:
        e3 = {"source_id": "available_five_pass3_ms", "county": "(available five pass 3)", "pages": []}
        e3["pages"] += directory_crawl(session, FIVE3_DIRECTORY, FIVE3_FOLDER_RE)
        print(f"  five3 directory   {len(e3['pages'])} page(s)", flush=True)
        for item_id in FIVE3_ITEMS:
            e3["pages"].append({"url": f"item:{item_id}", "kind": "arcgis_item", **arcgis_item(session, item_id)})
            page = item_services(session, item_id)
            e3["pages"].append(page)
            print(f"  five3 item        services={len(page['services'])} {item_id}", flush=True)
            for svc in page["services"][:4]:
                root = re.sub(r"/\d+$", "", svc)
                if "World_Imagery" in root:
                    continue
                e3["pages"].append({"url": root, "kind": "arcgis", "layers": arcgis_layer_meta(session, root)})
        report["states"].setdefault("MS", {"sources": []})["sources"].append(e3)
    passes = []
    if args.five_state_pass2:
        passes.append(("pass2", FIVE_STATE_PASS2_PAGES, FIVE_STATE_PASS2_SERVICES, FIVE_STATE_PROBES, {}))
    if args.five_state_pass3:
        passes.append(("pass3", FIVE_STATE_PASS3_PAGES, FIVE_STATE_PASS3_SERVICES, FIVE_STATE_PASS3_PROBES, FIVE_STATE_PASS3_ITEMS))
    if args.enrich_sources:
        passes.append(("enrich", ENRICH_PAGES, ENRICH_SERVICES, ENRICH_PROBES, ENRICH_ITEMS))
    soda_sets = []
    if args.enrich_sources_4:
        passes.append(("enrich4", ENRICH4_PAGES, {}, {}, {}))
    if args.enrich_sources_3:
        passes.append(("enrich3", ENRICH3_PAGES, {}, {}, {}))
        soda_sets.append(ENRICH3_SODA)
    if args.enrich_sources_2:
        passes.append(("enrich2", ENRICH2_PAGES, {}, ENRICH2_PROBES, {}))
        soda_sets.append(ENRICH2_SODA)
    for soda in soda_sets:
        for code, probes in soda.items():
            entry = {"source_id": f"enrich_soda_{code.lower()}", "county": "(enrich SODA)", "pages": []}
            for res, ids, cats in probes:
                page = soda_probe(session, res, ids, cats)
                print(f"  {code} soda           count={page.get('count')} {res}", flush=True)
                entry["pages"].append(page)
                time.sleep(0.8)
            report["states"].setdefault(code, {"sources": []})["sources"].append(entry)
    for tag, P_PAGES, P_SERVICES, P_PROBES, P_ITEMS in passes:
     for code in sorted(set(P_PAGES) | set(P_SERVICES) | set(P_PROBES) | set(P_ITEMS)):
        if args.state and code not in args.state:
            continue
        entry = {"source_id": f"five_state_{tag}_{code.lower()}", "county": f"(five-state {tag})", "pages": []}
        for item_id in P_ITEMS.get(code, []):
            entry["pages"].append({"url": f"item:{item_id}", "kind": "arcgis_item", **arcgis_item(session, item_id)})
            time.sleep(0.5)
        for url in P_PAGES.get(code, []):
            if re.search(r"DocumentCenter/View|\.pdf/?$", url, re.I):
                page = pdf_process(session, url)
                if page.get("status") == 200 and "pdf" not in str(page.get("content_type", "")).lower():
                    page = capture(session, url, "process", process=True)
            else:
                page = capture(session, url, "process", process=True)
            print(f"  {code} pass2          {page.get('status', page.get('error'))} {url}", flush=True)
            entry["pages"].append(page)
            if url in FIVE_STATE_TABLE_VALUES:
                entry["pages"].append(table_values(session, url, FIVE_STATE_TABLE_VALUES[url]))
            time.sleep(0.8)
        for url in P_SERVICES.get(code, []):
            page = {"url": url, "kind": "arcgis", "layers": arcgis_layer_meta(session, url)}
            print(f"  {code} arcgis         {len(page['layers'])} layer(s) {url}", flush=True)
            entry["pages"].append(page)
            time.sleep(0.8)
        for layer, where, ids, cats in P_PROBES.get(code, []):
            page = layer_probe(session, layer, where, ids, cats)
            print(f"  {code} probe          count={page.get('count')} {layer}", flush=True)
            entry["pages"].append(page)
            time.sleep(0.8)
        for url in (u for u in FIVE_STATE_TABLE_VALUES if tag == "pass2" and u not in P_PAGES.get(code, []) and code == "MI"):
            entry["pages"].append(table_values(session, url, FIVE_STATE_TABLE_VALUES[url]))
        report["states"].setdefault(code, {"sources": []})["sources"].append(entry)
    queries = list(args.arcgis_search) or (list(DISCOVERY_QUERIES if args.discovery else ()) + list(EXPANSION_ITEM_QUERIES if args.expansion else ())
                                           + list(FIVE_STATE_QUERIES if args.five_state else ())
                                           + list(FIVE_STATE_PASS2_QUERIES if args.five_state_pass2 else ())
                                           + list(FIVE_STATE_PASS3_QUERIES if args.five_state_pass3 else ())
                                           + list(ENRICH_QUERIES if args.enrich_sources else ()))
    for q in queries:
        report.setdefault("arcgis", {})[q] = arcgis_discover(session, q)
        print(f"  arcgis search {q!r}: {len(report['arcgis'][q])} item(s)", flush=True)
    for r in rows:
        st = report["states"].setdefault(r["state"], {"sources": []})
        entry = {"source_id": r["source_id"], "county": r["county"], "pages": []}
        seen: set[str] = set()
        urls = [("canonical_url", r["canonical_url"]), ("document_url", r["document_url"]), ("purchase_url", r["purchase_url"])]
        if r["state"] == "AR":
            urls.insert(1, ("county_list", r["canonical_url"] + "?" + urlencode({"county": "DALLAS"})))
        urls += [("extra", u) for u in EXTRA_URLS.get(r["state"], [])]
        for kind, url in urls:
            url = (url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            entry["pages"].append(capture(session, url, kind))
            print(f"  {r['state']} {kind:<14} {entry['pages'][-1].get('status', entry['pages'][-1].get('error'))} {url}", flush=True)
            time.sleep(0.8)
        terms = []
        for pg in list(entry["pages"]):
            for link in pg.get("terms_links") or []:
                href = link["href"]
                if href in seen or len(terms) >= MAX_TERMS_FOLLOW:
                    continue
                if ".".join((urlsplit(href).hostname or "").split(".")[-2:]) != ".".join((urlsplit(pg.get("final_url") or pg["url"]).hostname or "").split(".")[-2:]):
                    continue
                seen.add(href)
                terms.append(href)
                page = capture(session, href, "terms")
                page["link_text"] = link["text"]
                entry["pages"].append(page)
                print(f"  {r['state']} terms          {page.get('status', page.get('error'))} {href}", flush=True)
                time.sleep(0.8)
        # Alabama: the search page's own county form, submitted once.
        if r["state"] == "AL" and BeautifulSoup is not None:
            probe = form_probe(session, r["canonical_url"])
            entry["pages"].append({"kind": "form_probe", "url": probe.pop("url", r["canonical_url"]), **probe})
            print(f"  AL form_probe     {probe.get('status', probe.get('error'))}", flush=True)
        st["sources"].append(entry)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


def digest(path: Path) -> str:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = [f"# state-source capture {data.get('generated_at')}"]
    for state, st in sorted((data.get("states") or {}).items()):
        for e in st["sources"]:
            out.append(f"@@ {state} | {e['county']} | {e['source_id']}")
            for pg in e["pages"]:
                out.append(f"  ## {pg['kind']} {pg['url']} -> {pg.get('status', pg.get('error'))} final={pg.get('final_url')} "
                           f"ct={str(pg.get('content_type', ''))[:40]} lm={pg.get('last_modified')} len={pg.get('content_length')}"
                           + (f" linktext={pg.get('link_text')!r}" if pg.get("link_text") else ""))
                for l in pg.get("layers") or []:
                    if l.get("error"):
                        out.append(f"    layer error: {l['error']}")
                        continue
                    out.append(f"    layer {l['layer']} name={l.get('name')} geom={l.get('geometry')} count={l.get('count')} last_edit={l.get('last_edit')} max={l.get('max_records')}")
                    out.append(f"      fields: {', '.join(l.get('fields') or [])}")
                    if l.get("copyright"):
                        out.append(f"      copyright: {l['copyright']}")
                    if l.get("id_shapes"):
                        out.append(f"      id_shapes: {json.dumps(l['id_shapes'])[:1500]}")
                if pg.get("kind") in ("layer_probe", "table_values"):
                    out.append(f"  count={pg.get('count')} sampled={pg.get('sampled')} id_shapes={json.dumps(pg.get('id_shapes'))[:1200]}")
                    if pg.get("fields_present"):
                        out.append(f"  fields_present={pg.get('fields_present')}")
                    out.append(f"  value_counts={json.dumps(pg.get('value_counts'))[:1500]}")
                if pg.get("kind") == "doc_tables":
                    out.append(f"  doc pages={pg.get('pages')} sheets={pg.get('sheets')} bytes={pg.get('bytes')} rows={pg.get('table_rows')} note={pg.get('note')}")
                    out.append(f"  header={pg.get('header')}")
                    out.append(f"  col_shapes={json.dumps(pg.get('col_shapes'))[:1800]}")
                if pg.get("kind") == "app_services":
                    out.append(f"  assets_read={pg.get('assets_read')} assets={pg.get('assets')} services={pg.get('services')} item_ids={pg.get('item_ids')}")
                if pg.get("kind") == "pdf_process" and pg.get("pages") is not None:
                    out.append(f"  pdf pages={pg.get('pages')}")
                if pg.get("kind") == "arcgis_directory":
                    out.append(f"  services: {', '.join(pg.get('services') or [])}")
                    out.append(f"  folders: {', '.join(pg.get('folders') or [])}")
                for l in pg.get("links") or [] if pg.get("kind") == "process" else []:
                    if FOLLOW_VOCAB.search(l["text"] + " " + urlsplit(l["href"]).path) or re.search(r"\.(pdf|xlsx?|csv)$|form|apply|bid", l["href"], re.I):
                        out.append(f"  link: {mask_digits(l['text'])!r} -> {l['href']}")
                if pg.get("steps"):
                    out.append(f"  probe steps: {pg['steps']}")
                if pg.get("probe_params"):
                    out.append(f"  probe params: {pg['probe_params']}")
                if pg.get("parse_error"):
                    out.append(f"  parse_error: {pg['parse_error']}")
                if pg.get("title"):
                    out.append(f"  title: {pg['title'][:160]}")
                if pg.get("headings"):
                    out.append("  headings: " + " || ".join(pg["headings"][:12]))
                for t in pg.get("tables") or []:
                    out.append(f"  table id={t['id']!r} class={t['class']!r} rows={t['body_rows']} cells={t['cells_per_row']} headers={t['headers']}")
                    if t.get("first_row") is not None:
                        out.append(f"    first_row(masked)={t.get('first_row')} col_shapes={t.get('col_shapes')}")
                for f in pg.get("forms") or []:
                    out.append(f"  form {f['method']} {f['action']}")
                    for x in f["fields"]:
                        extra = f" options={x.get('options')} shapes={x.get('value_shapes')} texts={x.get('option_texts')}" if x["tag"] == "select" else ""
                        out.append(f"    field {x['tag']} name={x['name']!r} type={x['type']!r}{extra}")
                for l in pg.get("terms_links") or []:
                    out.append(f"  terms-link: {l['text']!r} -> {l['href']}")
                if pg.get("csv_header") is not None:
                    out.append(f"  csv rows={pg.get('csv_rows')} complete={pg.get('csv_read_complete')} bytes={pg.get('csv_bytes_read')}")
                    for c in pg.get("columns") or []:
                        out.append(f"    col {c['header']!r} non_empty={c['non_empty']}" + (f" distinct={c.get('distinct')} shapes={c.get('shapes')}" if "shapes" in c else ""))
                if pg.get("socrata"):
                    so = pg["socrata"]
                    out.append(f"  socrata licence: id={so.get('licenseId')} license={so.get('license')} attribution={so.get('attribution')} "
                               f"rowsUpdatedAt={so.get('rowsUpdatedAt')} custom_license={((so.get('custom_fields') or {}).get('Common Core') or {}).get('License')}")
                    out.append("  socrata: " + json.dumps(so)[:3000])
                if pg.get("kind") == "arcgis_item":
                    out.append(f"  item {pg.get('id')} | {pg.get('type')} | {pg.get('title')} | owner={pg.get('owner')} org={pg.get('org')} url={pg.get('url')} err={pg.get('error')}")
                    for k in ("snippet", "description", "license", "access"):
                        if pg.get(k):
                            out.append(f"    {k}: {pg[k]}")
                for s in pg.get("snippets") or []:
                    out.append(f"  s: {s}")
    for q, items in (data.get("arcgis") or {}).items():
        out.append(f"@@ ARCGIS {q}")
        for it in items:
            if it.get("error"):
                out.append(f"  error: {it['error']}")
                continue
            out.append(f"  * {it['type']} | {it['title']} | owner={it['owner']} org={it['org']} id={it['id']} modified={it['modified']}")
            out.append(f"    url={it.get('url')} tags={it.get('tags')}")
            if it.get("snippet"):
                out.append(f"    snippet: {it['snippet']}")
            if it.get("license"):
                out.append(f"    license: {it['license']}")
            if it.get("access"):
                out.append(f"    access: {it['access']}")
            for l in it.get("layers") or []:
                if l.get("error"):
                    out.append(f"    layer error: {l['error']}")
                    continue
                out.append(f"    layer {l['layer']} name={l.get('name')} geom={l.get('geometry')} count={l.get('count')} last_edit={l.get('last_edit')} max={l.get('max_records')}")
                out.append(f"      fields: {', '.join(l.get('fields') or [])}")
                if l.get("copyright"):
                    out.append(f"      copyright: {l['copyright']}")
                if l.get("id_shapes"):
                    out.append(f"      id_shapes: {json.dumps(l['id_shapes'])[:1500]}")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
