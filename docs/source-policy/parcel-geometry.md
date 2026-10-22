# Official parcel-geometry (boundary) sources: survey for TAXACQ (2026-10-22)

This is a read-only survey. Nothing in the repository, database or workflows was changed, and nothing was loaded or enabled.
A source listed here is **not** approved just because it is public. Before it is used, each one still needs:
- an entry in `data/source_approvals.csv` and permission records in `data/source_permissions.csv`;
- a `BoundarySource` in `harvesters/boundary/sources.py`;
- an exact-identifier match measured live.

## How it was read
- **Repository files:** `CLAUDE.md`, `docs/parcel-boundaries.md`, `data/source_approvals.csv`, `harvesters/boundary/sources.py`, `harvesters/enrichment/sources.py`, `data/enrichment_source_catalog.csv`, `harvesters/otc/adapters/expansion.py` (which column each source stores as `parcel` / `case_no`), `scripts/discover_sources.py` `DEEP_TARGETS`, `docs/property-enrichment.md`.
- **Live sources:** layer metadata (`?f=pjson`), item metadata (`sharing/rest/content/items/<id>`), Socrata `api/views/<id>.json` and PASDA FGDC XML, read 2026-10-22.
- **Identifier checks:** these used value-free shapes only (digit → 9, letter → A). No parcel number, owner or address was recorded.
- **Status words:**
  - **VERIFIED** means the licence or terms text was read on the publisher's own metadata and is quoted.
  - **UNVERIFIED** means none was found, or it was seen only in a search snippet.
  - Anything not read is marked "not read".

## Pipeline fit (effort scale)
`harvesters/boundary` supports two source locations:
- **`arcgis`:** a keyed query through `scripts/parcel_boundary_refresh.py arcgis_read`, joined exactly by `plan.py`;
- **`files`:** local shapefiles (pyshp/pyproj), as for Florida DOR.

Effort:
- **S:** an ArcGIS polygon layer with an exact key. It needs a config, approval and permission records, a dry run, and a display attribution.
- **M:** a new transport (Socrata `the_geom`), a normaliser, or a bulk file per county.
- **L:** no direct key (a crosswalk is needed), a token or click-through, or a restricted licence needing a negotiated agreement.

**Neighbour lines.** A whole-county or whole-state parcel layer can also supply the yellow neighbouring-parcel lines. A source's own tax-sale layer (York, Albany, Lenawee) only contains the listed parcels, so it cannot.

---

## Summary by state

| State | Active records | Best source | Terms | Match | Effort | Coverable (est.) |
|---|---:|---|---|---|---|---:|
| MI | 30,645 | City of Detroit "Parcels (Current)" (Wayne/Detroit); Lenawee: its own tax-sale layer | Detroit: **UNVERIFIED** (no licence on item or service). Lenawee: no licence | Detroit: exact (same shapes `99999999.` / `99999999-9`) | M (S technically, plus a licence decision) | 30,602 + 35 |
| LA | 10,334 | EBR Parish Assessor "Tax Parcel" (Socrata `ei2c-krsr`, column `the_geom`, multipolygon) | **VERIFIED Public Domain** (licenseId PUBLIC_DOMAIN) | exact (`assessment_num`; 10,157 / 10,334 matched in deep probe run 36922621158) | M (Socrata geometry transport) | ~10,157 |
| MO | 9,778 | City of St. Louis Assessor `Assessor_Public_Parcels` MapServer layer 11 "Parcels" (or the PARCELS.zip shapefile) | **UNVERIFIED** (no licence; footer "© 2011 - 2026 City of St. Louis") | probable exact on `ParcelId` (LRA ParcelId `\d{11}`); also `Handle`. Not measured | S technically; needs a licence | up to 9,778 |
| TN | 1,787 | Shelby County ReGIS "CERT_Parcel" | **UNVERIFIED / restrictive** (snippet: "for the sole use of ReGIS its participants and their authorized agents ... may be displayed publicly, but may not be sold or transferred ... without the written consent of ReGIS"); service returned 403 | unknown (portal parcelNumber 14 chars) | L (written ReGIS consent) | 0 until consent |
| FL | 45 counties (top 10 = 1,876) | DOR PTO county PIN files (`fl_dor_pto_parcel_gis`, already approved) | **Written permission (on file as relayed)** | exact NAL id, or listing parcel + point-in-polygon | S per county (pipeline exists) | all FL counties, limited by join rules (Broward: 10 of 64) |
| SC | 905 | York: its own tax-sale layer (polygons); Horry: county `HorryCountyGIS` MapServer layer 24 | York: no licence (owner approved the list 2026-09-30, not geometry explicitly). Horry: disclaimer only, **UNVERIFIED** | York: exact (the record IS the feature, `TAXMAPID`). Horry: `PINtext` (11 chars) vs PIN `\d{9,11}`, needs normalisation | S (York), S-M (Horry) | 853 + 51 |
| PA | 376 | PASDA "Fayette County Parcels region 202602" (MapServer layer 2) | Metadata `useconst` "None", `accconst` "None" (a published no-constraints statement, not a licence grant) | `TAXIDNUM` `99-99-9999` vs repository PARCEL `\d{2}-\d{2}-\d{4}(-…)*`: exact for the base shape; suffixed ids need checking | S | ≤376 |
| WY | 253 | Albany County's own `2026TAXSALEPROP_1ST` layer (polygons) | no licence (owner approval 2026-09-30 for the list) | exact (the record is the feature: `pidn` / `accountno`) | S | 253 |
| OK | 195 | "Tax Parcels Public" (`TaxParcelsPublics_view`, owner account `artimcon`) | **UNVERIFIED** (licenseInfo empty; publisher not confirmed as the county) | exact (`pin` shape `9999-99-999-9999` = Parcel_No pattern) | S technically; needs a licence and publisher confirmation | 195 |
| CO | 141 | Colorado OIT `Colorado_Public_Parcels` (already in repo as `co_oit_public_parcels`) | **VERIFIED**: "Commercial use of the data is allowed so long as the State of Colorado is attributed ..."; "Resale of this data is strictly forbidden." | exact on `account` (Douglas `A9999999` = record account_id; Morgan `AAA999999`, record shape not checked) | S | 141 |
| TX | 562 (19 counties) | TxGIO StratMap Land Parcels (most recent); per-county CAD services | **UNVERIFIED** (licenseInfo "None"; copyright "TxGIO, Various Counties, Various Vendors"); query not supported on the service (HTTP 400) | unknown: record case_no is the CAD account; `prop_id` / `geo_id` mapping varies (Jim Wells exact on geoID; Liberty 0 / 113; Hardin 1 / 9) | L | Jim Wells 11 identifiable; rest unknown |
| MN | 2 | Ramsey County parcel data (MN Geospatial Commons) | **UNVERIFIED** (MetroGIS org page "License not specified"; 2012 MetroGIS licence restrictive; current status not read) | PIN (12 digits), not measured | S-M | 2 |

---

## Per-source detail

### LA - East Baton Rouge Parish Assessor "Tax Parcel" (data.brla.gov `ei2c-krsr`)
- **Publisher:** EBR Parish Assessor's Office, through Open Data BR.
- **URLs:**
  - landing page: https://data.brla.gov/d/ei2c-krsr
  - API: https://data.brla.gov/resource/ei2c-krsr.json
  - metadata: https://data.brla.gov/api/views/ei2c-krsr.json
  - data dictionary: https://city.brla.gov/gis/metadata/TAX_PARCEL.html (not read)
- **Format:** Socrata; column `the_geom` (multipolygon), "Polygon tax parcel boundaries with attributes" (metadata description).
- **Identifier:** `assessment_num`. The record's `parcel` / `case_no` is the adjudicated list's PROPERTY NUMBER (`999-9999-9`). Expected match is **exact**: the repository's deep probe matched 10,157 of 10,334.
- **Licence:** **VERIFIED**. Metadata licenseId `PUBLIC_DOMAIN`, name "Public Domain"; attribution "EBR Parish Assessor" (https://www.ebrpa.org).
- **Update:** "Update Frequency: Annually" (metadata custom field). rowsUpdatedAt about 2026-04-30.
- **Commercial display / store:** VERIFIED (public domain).
- **Repository status:** already `la_ebr_tax_parcels` (APPROVED) for attributes, `centroid=False`. The ArcGIS twin `la_ebr_arcgis_parcels` is REVIEW_REQUIRED ("Access Constraints: copyright"): use the Socrata publication, not ArcGIS.
- **Effort:** M. It needs a Socrata geometry read (a new `location` in `harvesters/boundary`), an approval-register row, and display attribution.
- **Neighbours:** yes (parish-wide).
- **Coverage:** about 10,157 records.

### MI - City of Detroit "Parcels (Current)" (Wayne County: Detroit Land Bank 30,602)
- **Publisher:** City of Detroit, Office of the Assessor.
- **Layer:** https://services2.arcgis.com/qvkbeam7Wirps6zC/ArcGIS/rest/services/parcel_file_current/FeatureServer/0
  - polygons, 377,940 features;
  - lastEditDate about 2026-10-22;
  - item `3c784c118e5c4083b37038e9b38573df` ("Parcels (Current)", snippet: 2026 tax-year boundaries; "updated daily").
- **Do not use** the deprecated `Parcels_Current` service (item `9ca25373…`). Its description says "This layer is no longer authoritative".
- **Identifier:** `parcel_id`. The DLBA layers store `parcel_id` as both `parcel` and `case_no`. Shapes on both sides are `99999999.` and `99999999-9`, so the match should be **exact**. It has not been measured.
- **Licence:** **UNVERIFIED**:
  - item licenseInfo and accessInformation are empty;
  - service copyrightText is empty;
  - the detroitdata.org mirror says "No License Provided";
  - no portal terms page was found.
- **Commercial display:** UNVERIFIED. It needs written permission or an owner decision.
- **Effort:** S technically (ArcGIS keyed query, exact key). Licence work is needed first.
- **Neighbours:** yes (whole city).
- **Repository status:** none. The DLBA layers themselves are **points** (`DLBA_Owned_Properties` geometryType esriGeometryPoint), so they cannot supply outlines.

### MI - other counties
- **Lenawee (35):** the county's own `Tax_Sale_2026_view` layer is polygons (esriGeometryPolygon). The record is the feature (`TAXID`), so the match is exact.
  - Its only licence wording is "Public layer for denoting 2026 Lenawee County Tax Sale parcels." There is no reuse grant.
  - The owner approved the list for publication on 2026-09-30.
  - Effort S. No neighbours.
- **Eaton (3):** the `For_Sale_2026_view` layer is **points**, so it supplies no outline. Eaton's own data sits behind a click-through licence (catalog `mi_county_parcels`, REVIEW_REQUIRED).
- **Oceana (5):** no source identified (not researched further).

### MO - City of St. Louis Assessor parcels (St. Louis City 9,778)
- **Publisher:** City of St. Louis Assessor's Office. Dataset page: https://www.stlouis-mo.gov/data/datasets/dataset.cfm?id=82
- **Service:** https://maps8.stlouis-mo.gov/arcgis/rest/services/ASSESSOR/Assessor_Public_Parcels/MapServer/11 ("Parcels", polygon, wkid 102696, JSON / GeoJSON / PBF, maxRecordCount 2000). Fields include `ParcelId`, `Handle`, `CityBlock`, `Parcel`, `Condominium`.
- **Bulk download:** "Current Parcels" shapefile https://static.stlouis-mo.gov/open-data/ASSESSOR/PARCELS.zip (key field "HANDLE"; update "Unknown").
- **Identifier:** the LRA record stores `ParcelId` (`\d{11}`). The layer has `ParcelId` and `Handle`. The match is likely exact on `ParcelId` but has **not been measured**. The repository's inert `mo_stl_parcels_coordinates` config assumes `HANDLE` on a different service (PDA_ZONING layer 0).
- **Licence:** **UNVERIFIED**:
  - the dataset page has no licence;
  - the DCAT metadata has publisher and `accessLevel: public` only;
  - the footer reads "© 2011 - 2026 City of St. Louis".
  - A permission inquiry is recorded in `data/audit/permission_inquiry_tracker.csv` as REPORTED_SENT_UNVERIFIED.
- **Condominiums:** the service has a separate "Condos" layer (10), so condo units need the same exclusion rule Florida uses.
- **Effort:** S technically, after permission.
- **Neighbours:** yes.

### TN - Shelby County ReGIS (Shelby 1,787)
- **Service:** https://gis.shelbycountytn.gov/arcgis/rest/services/Parcel/CERT_Parcel/MapServer ("Certified Parcels and Tax Roll Data"). It returned HTTP 403 to this environment.
- **Terms:** seen only in a search snippet of its iteminfo page: "owned by Shelby County Government and is for the sole use of ReGIS its participants and their authorized agents ... may be displayed publicly, but may not be sold or transferred to any other entity without the written consent of ReGIS". It is shared under the ReGIS Cooperative GIS Data Sharing Agreement. **UNVERIFIED**, and restrictive.
- **Comptroller statewide data:** the download (monthly shapefile) lists Shelby among the counties **not** maintained by the Comptroller (https://comptroller.tn.gov/office-functions/pa/gisredistricting/redistricting-and-land-use-maps/parcel-data.html).
- **Memphis-hosted layers:** these are dated (2014 / 2019) or token-protected (`maps.memphistn.gov` returned "Token Required").
- **Identifier:** unknown. The portal's parcelNumber is 14 characters.
- **Effort:** L (written ReGIS consent). Neighbours: yes, if consent is given.

### FL - Florida DOR PTO county PIN files (existing)
- `fl_dor_pto_parcel_gis`, APPROVED_WITH_CONDITIONS on written permission (as relayed; the original email is not on file). It covers all 67 counties.
- The pipeline and the Florida Available workflow already exist. Coverage is limited by the reviewed join rules:
  - validated NAL id, or the listing parcel plus point-in-polygon;
  - condo units and rights-of-way excluded;
  - Miami-Dade and St. Johns condo files refused.
- **Next step:** dispatch the per-county dry run (owner).
- Counties by records: Santa Rosa 494, Volusia 275, Miami-Dade 202, Hillsborough 196, Pasco 137, Sarasota 131, Duval 128, Alachua 115, Lee 100, Orange 98, plus 35 smaller counties.
- **Not this approval:** the FGIO statewide cadastral (`fl_fdor_cadastral`).
- **Neighbours:** yes (whole-county PIN file).

### SC
- **York (853):** the source's own `Tax_Sale_Properties_2025_View` layer is **polygons** (esriGeometryPolygon; lastEditDate 2026-09-29; https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/Tax_Sale_Properties_2025_View/FeatureServer/0). The record's `parcel` / `case_no` = `TAXMAPID` = the feature, so the match is exact.
  - There is no licence (description and copyrightText empty).
  - The owner approved the list for publication on 2026-09-30, but geometry display is not separately recorded.
  - Effort S. No neighbours.
  - For neighbours, York County GIS's Open Data site / GeoService API is described on https://www.yorkcountysc.gov/239/GIS-Data-Download. That page returned 403, so its terms were **not read**.
- **Horry (51):** https://www.horrycounty.org/gispublic/rest/services/Public/HorryCountyGIS/MapServer/24 "Parcels" (polygon). Identifiers: `PINtext` (string, 11 chars), `PIN` (double), `TMS`.
  - Record PIN `\d{9,11}`: needs normalisation (left-pad) or `PIN` numeric equality. Not measured.
  - Terms: only general disclaimers ("as is", no warranty, a tax fabric, not a survey) on county pages, seen through search. **UNVERIFIED**.
  - Effort S-M. Neighbours: yes.
- **Georgetown (1):** not researched (one record).

### PA - Fayette County parcels via PASDA (Fayette 376)
- **Service:** https://mapservices.pasda.psu.edu/server/rest/services/pasda/FayetteCounty/MapServer/2 ("Fayette County Parcels region 202602", polygon; fields `TAXIDNUM`, `TAXSHORT`).
- **Metadata:** https://www.pasda.psu.edu/metadata/FayetteCounty_Parcels_region202602.xml:
  - originator "Fayette County, Pennsylvania", distributor PASDA;
  - `accconst` "None", `useconst` "None";
  - no update frequency stated (publication 202602).
- **Identifier:** `TAXIDNUM` shape `99-99-9999`. The repository's PARCEL pattern is `\d{2}-\d{2}-\d{4}(?:-\d{1,4})*`. Base ids are an exact match; suffixed ids (`-…`) may not exist in the layer, so they need measurement.
- **Terms:** a published "None" use constraint is permissive but is not an explicit licence grant. Treat it as **UNVERIFIED** for commercial display until the owner decides.
- **Effort:** S. Neighbours: yes.

### WY - Albany County's own tax-sale layer (Albany 253)
- **Layer:** https://services1.arcgis.com/EmwrhKkmuQhTATzU/arcgis/rest/services/2026TAXSALEPROP_1ST/FeatureServer/0 (polygons; lastEditDate about 2026-07-13).
- **Identifier:** the record is the feature (`pidn` = parcel, `accountno` = case_no), so the match is exact.
- **Terms:** none (empty). Owner list approval 2026-09-30.
- **Note:** the layer is the 2026 sale's list and is marked superseded in code.
- **Effort:** S. No neighbours. The county-wide parcel layer was not found (only resellers), so it is **UNVERIFIED**.

### OK - "Tax Parcels Public" (Oklahoma 195)
- **Layer:** https://services8.arcgis.com/euhkr1dAJeQBIjV0/arcgis/rest/services/TaxParcelsPublics_view/FeatureServer/0 (polygon; lastEditDate about 2026-10-15; item `244ff1c03cf34c459092e10142b13b01`, "Oklahoma County Tax Parcels", owner account `artimcon`).
- **Publisher:** **not confirmed** as Oklahoma County.
- **Identifier:** `pin` (`9999-99-999-9999`). It equals the record's Parcel_No pattern, so the match is exact. Other fields: `accountno` (`A999999999`), `propertyid`, `PARCELNB_1`.
- **Terms:** licenseInfo and accessInformation are empty, so **UNVERIFIED**.
- **Effort:** S technically. Publisher and licence need confirming. Neighbours: yes.
- **Repository:** listed in `DEEP_TARGETS` (purpose coordinates).

### CO - Colorado OIT "Colorado_Public_Parcels" (Douglas 138, Morgan 3)
- **Layer:** https://gis.colorado.gov/public/rest/services/Address_and_Parcel/Colorado_Public_Parcels/FeatureServer/0 (polygon). Douglas has 164,818 features (dateReceived 2026-04-21) and Morgan 15,956 (2026-03-27).
- **Terms:** **VERIFIED** from the service iteminfo accessInformation:
  - "Resale of this data is strictly forbidden."
  - "Commercial use of the data is allowed so long as the State of Colorado is attributed in relevant application documentation."
  - Suggested attribution: "State of Colorado Public parcels were accessed on [DATE] from https://gis.colorado.gov/public/rest/services/Address_and_Parcel".
- **Update:** "Updates are collected annually".
- **Identifier:** `account`. Douglas features are `A9999999`, the same shape as the record's `account_id` / `Account_No`, so the match is exact. Morgan features are `AAA999999`; the record's "acct #" shape was not checked.
- **Repository:** already `co_oit_public_parcels` (APPROVED, attributes plus centroid).
- **Effort:** S. Neighbours: yes.
- Displaying geometry inside the app is commercial use, not resale. Storing it is not addressed explicitly, so record a decision.

### TX - TxGIO StratMap Land Parcels and county appraisal districts (562 records, 19 counties)
- **Service:** https://feature.geographic.texas.gov/arcgis/rest/services/Parcels/stratmap_land_parcels_48_most_recent/MapServer/0 (polygon; fields `prop_id`, `geo_id`, `county`, `tax_year`, `date_acq`, ...).
  - Querying it returned HTTP 400 "Requested operation is not supported by this service", so it is display-only. Bulk data comes as per-county downloads.
  - licenseInfo "None"; copyright "TxGIO, Various Counties, Various Vendors".
  - The FAQ (https://www.geographic.texas.gov/stratmap/land-parcels.html) says "not survey grade" and "TxGIO will attempt to refresh annually". It states no licence, and some counties are licensed / by special request only.
  - **UNVERIFIED.**
- **Identifier:** the record's `case_no` is the CAD account. Whether it equals `prop_id` or `geo_id` varies by county:
  - Jim Wells: exact on `geoID` (11 / 11);
  - Liberty: 0 / 113;
  - Hardin: 1 / 9 (repository deep probe run 36922621158).
- **Galveston (205):** the CAD publishes shapefiles at https://galvestoncad.org/gis-data/ (parcels updated 04/14/2026). Its only terms are a disclaimer (seen through search), so **UNVERIFIED**.
- **Effort:** L. It needs per-county identifier crosswalks plus licences. LGBS rows are REVIEW_REQUIRED anyway.

### MN - Ramsey (2)
- The source layer is points.
- Ramsey parcel data is on MN Geospatial Commons. The MetroGIS org page shows "License not specified", and the 2012 MetroGIS Data Licence is restrictive. The current terms were not read: **UNVERIFIED**. Not worth effort for 2 records.

### UT (not active)
- `ut_ugrc_lir_saltlake` already exists (CC BY 4.0). There are no active records.

---

## Ranking: value vs effort (records coverable / effort / terms)
1. **LA EBR Tax Parcel (`ei2c-krsr`).** About 10,157 records, effort M. Terms **VERIFIED** public domain from the same dataset already approved. This is the best ratio.
2. **CO OIT Colorado_Public_Parcels.** 141 records, effort S. **VERIFIED** commercial use with attribution; already in the repository.
3. **City of Detroit Parcels (Current).** 30,602 records, effort S technically, exact shape match. Licence **UNVERIFIED**, so it needs permission.
4. **City of St. Louis Assessor Parcels (layer 11).** 9,778 records, effort S technically. Licence **UNVERIFIED**; an inquiry is already logged.
5. **York SC and Albany WY own tax-sale polygons.** 853 + 253 records, effort S, exact (the record is the feature). They carry no licence, only the owner's 2026-09-30 list approval, so the owner must decide on geometry display.

Also: **Florida DOR** (already approved) is the cheapest remaining Florida gain, by running the per-county dry runs. **Shelby TN** (1,787) is high value but blocked by ReGIS's restrictive terms.
