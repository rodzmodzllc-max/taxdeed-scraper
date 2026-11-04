# Data-enrichment sprint (2026-10-25)

**Owner's direction (2026-10-25).** Focus on data, from public records. Collect
everything that can be read from public sources. Nothing is sold until legal
review.

**Boundaries kept.** We read only public pages, open-data portals, map
services and downloads. We never log in, get around a CAPTCHA, block or
click-through gate, or use the hard-blocked vendors (PBFCM, MVBA, CTSA,
GovEase).

Six research agents surveyed sources on 2026-10-25. Their findings are
summarised at the end of this file. This PR adds the first batch: the county
parcel layers that fill gaps on records we already hold.

## Batch 1: parcel layers for held records (this PR)

All five layers share these properties:

- Each is county-scoped (`harvesters/enrichment/sources.py`).
- Each layer's fields were read live from the development sandbox.
- A sample of our own parcel numbers was matched before configuring.
- Matching uses the factory's exact-identifier rule, so a row gets one feature
  or nothing.
- A zero or blank value is never stored. This matters because land-bank and
  county-owned parcels are tax-exempt and carry $0 assessed values.
- Each runs on an `INTERNAL_RISK_ACCEPTANCE` in `data/source_permissions.csv`
  (fetch and enrich only), with the `excluded_from_paid_tier` condition. None
  publishes a licence, so the records never claim permission.

| Source id | County | Layer | Join | Writes | Local dry run (real rows, no write) |
|---|---|---|---|---|---|
| `mo_stl_parcels_coordinates` | St. Louis City, MO | Assessor_Public_Parcels MapServer/11 | ParcelId = LRA ParcelId | coordinates (parcel centroid), assessed, land value, year built | 150 of 150 sampled matched |
| `mi_detroit_assessor_parcels` | Wayne, MI (Detroit) | parcel_file_current FeatureServer/0 | parcel_id (trailing dot kept) | land value, property class, use, acreage, year built, floor area, legal description | 150 of 150 sampled matched |
| `ok_oklahoma_county_parcels` | Oklahoma, OK | TaxParcelsPublics_view FeatureServer/0 | pin | coordinates, acreage, legal description | 168 of 195 matched, 4 ambiguous (not written) |
| `pa_fayette_pasda_parcels` | Fayette, PA | PASDA FayetteCounty MapServer/2 | TAXIDNUM | coordinates | 253 of 376 matched (unit-suffixed ids do not exist on the layer) |
| `sc_horry_county_parcels` | Horry, SC | OpenData Parcels FeatureServer/0 | PIN (numeric) | coordinates | 32 of 51 matched (the rest are mobile-home accounts with no parcel) |

**How it runs.** The existing `job=available` with `available_mode=apply`
(`scripts/enrich_available.py`) runs every cleared layer over the Available
rows missing a field it publishes. The coordinate layers are also
`centroid=True` sources for `job=geocode` (`scripts/geocode_authoritative.py`).

**Not in batch 1:**

- **Ramsey MN:** the layer returned HTTP 403 to the sandbox.
- **St. Louis land-use code (`AsrLandUse1`):** its decode table has not been
  read.
- **Detroit assessed / taxable values:** they are $0 on exempt parcels.

## Findings for the next batches (research agents, 2026-10-25)

"Read" means the agent opened the page or file. "Search" means it only saw a
search result. Each source still needs its fields read live, a sample matched
and a permission record before it is used.

**New Available / auction inventory:**

- **Alabama ADOR:** state-held land, county transcript PDFs updated weekly,
  `https://www.revenue.alabama.gov/wp-content/uploads/property-tax-transcripts/WWW_TRANS_XX.PDF`
  (68 files). Jefferson-Birmingham alone is about 8,972 parcels. Read. They
  carry the CS number and parcel, but no street address.
- **Philadelphia PHDC "LAMAAssets":** ArcGIS layer,
  `https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/LAMAAssets/FeatureServer/0`,
  with about 1,769 parcels owned and available out of 7,853. Read.
- **Cook County Land Bank (IL):** ePropertyPlus, the same platform as the Shelby
  TN adapter, `https://public-cclba.epropertyplus.com/...getPublishedProperties`,
  923 records. Read.
- **Kansas City (Jackson MO):** an ePropertyPlus host,
  `public-kclb.epropertyplus.com`, with 2,577 records. The agent guessed this
  hostname and found no official page linking to it. Confirm before use.
- **Dallas County (TX) struck-off resale list:** PDF from the county's Property
  Division, carrying DCAD account, value, land type and a suggested minimum
  bid. Read.
- **Bexar County (TX) Resale Properties Distribution List:** monthly PDF with
  account number and struck-off amount. Read.
- **Florida Lands Available:**
  - Lake County runs on realTDM, so it could be one row in
    `laft_realtdm_counties.csv`. Read the Clerk page; the realTDM site returned
    403.
  - Charlotte County's Clerk page at `/TaxDeed/Lands` is an HTML table.
- **Leon County (FL) Tax Collector:** certificate lists published as zipped
  Excel files. Read.

**Enrichment layers:**

- **Texas:**
  - TxGIO StratMap statewide parcels: outlines, value and land use, but its
    licence field is blank.
  - CAD downloads for Dallas, Collin and Fort Bend.
  - Travis TCAD layer and Bexar layer.
- **Leon FL:** PARNAL layer (geometry, land use, building facts).
- **East Baton Rouge "Lot Profile":** Public Domain, but it has no assessment
  number, so there is no deterministic join yet.

**Acquisition-path pages read:**

- Oklahoma County Treasurer guidelines and bid form.
- Fayette repository sale page and FAQ.
- Horry FLC guidelines.
- Detroit Land Bank application, side-lot and FAQ pages.
- St. Louis LRA offer-to-purchase page.
- Ramsey tax-forfeited page.

These are candidates for `data/purchase_path_evidence*.csv` rows once their
wording is quoted from a capture.
