# AVAILABLE expansion: MO, OK, PA, MN (2026-10-04)

Four new county AVAILABLE sources. Each one says itself that its parcels are
available, and each is configured through the shared adapters in
`harvesters/otc/adapters/expansion.py`. No new architecture was added.

Every source is **UNREVIEWED**:

- it is collected and synced like any AVAILABLE source;
- its rows carry `publication_status = UNREVIEWED`;
- admins see them labelled;
- customers see none of them until an admin review approves the source.

Mississippi was evaluated and **deferred** (section 5).

## 1. Evidence

All sources were read value-free by `scripts/capture_state_sources.py`
(`--available-five`, `-2`, `-3`) on the `evidence/available-five` branch:

| Run | What it read |
|---|---|
| 37203515518 | pass 1 |
| 37203652975 | pass 2 |
| 37203694092 | MS state GIS directory |
| 37203843581 | MS layer vocabulary |
| 37204541253 | live parser validation: `scripts/harvest_expansion.py` per state, no database credential, counts and identifier shapes only |

The workflow, `.github/workflows/probe-available-five.yml`, is now dispatch-only.

**Privacy incident during the evidence passes.** Pass 1 printed fragments of
real list rows into the public job log: owner names and addresses from the
Fayette PDF, and street / neighbourhood values from a misdetected header row.

- The run's logs were deleted (run 37202982184; the log URL now returns 404).
- The capture no longer prints any free text from a list document.
- Header cells are printed only when they match column-name vocabulary.
- `tests/python/test_capture_table_privacy.py` pins all of this.

## 2. Sources

| State | Source | Kind | Available rule | Identifier | Amount | Acquisition path | Live rows (run 37204541253) |
|---|---|---|---|---|---|---|---|
| MO | St. Louis Land Reutilization Authority inventory: City open data, `LRA_INVENTORY.csv`, updated nightly | `csv` | the source's own `Parcel_Status` = `Available` (587 `Unavailable` rows are not read) | `ParcelId`, 11 digits | none published: `NOT_PUBLISHED` | none verified (LRA process not captured) | 9,761 read, 3 duplicate ids dropped: **9,758** |
| OK | Oklahoma County Treasurer, County Owned Property list (`table#mytable`) | `html_table` | every row (the page says county-owned property "can be purchased by the public through a bidding process") | `Parcel_No`, `9999-99-999-9999` | "Suggested Initial Bid Amount": `PUBLISHED_AMOUNT_KIND_UNSPECIFIED`, never a minimum or a price | Treasurer's bid form PDF: `application_download`, source scope, mode `bid` (offline) | **195** |
| PA | Fayette County Tax Claim Bureau repository list (PDF "Repository Update 10-7-2025") | `pdf_table` | repository rows; rows whose Comments read `Bid Received` are pending and not read (25) | `PARCEL`, `99-99-9999` with optional `-99` segments | "Min. Bid": `OPENING_BID` | sealed bid to the Tax Claim Bureau; no form URL verified, none invented | **376** |
| MN | Ramsey County Tax Forfeited Land public layer | `arcgis` (MapServer, points) | the layer's own `Status` = `Available for purchase` (server `where` plus a local re-check) | `PIN`, 12 digits | `MinimumBid`: `OPENING_BID` | over the counter; no link on the layer | **2** |

Expected first-run inventory is **10,331 AVAILABLE rows**, all UNREVIEWED.

Fields read per source:

- MO: address, legal description, `PropertyType` as land use (Lot / Building / Other).
- OK: the combined "Physical Address Per Assessor/Legal Description" column. It is
  kept as the **legal description**, because it is not reliably a street address.
- PA: description and the list's own date (`list_as_of` = 2025-10-07, read from the
  document name).
- MN: address, legal description, and coordinates from the layer's own point geometry.

**Owner and taxpayer columns are never mapped.** Fayette's `OWNER` column is read
by no field, and a test proves no owner text reaches a row or the log.

**Fayette is a dated document.** The configuration pins DocumentCenter item 9761.
If the county publishes a newer repository file under another id, that file is not
followed, and rows keep showing the 2025-10-07 date. Re-capture the new document
before re-pointing the config.

## 3. What changed in the shared code

- `tabular.py`:
  - `status_include` / `status_exclude`: the source's own status words; other rows are counted, never kept;
  - `ColumnMap.land_use`;
  - `parse_rows()` and `pdf_table_rows()` (pdfplumber; a scanned PDF yields no rows, never a guess);
  - a header repeated on later PDF pages is skipped;
  - `header_required` is now enforced for every input path, not only HTML tables;
  - a status filter now requires the status column itself, so a list that lost a column is FAILED, never EMPTY.
- `harvest_expansion.py`: runner kinds `csv` and `pdf_table`, each with these outcomes:
  - transport error: FAILED;
  - unreadable file: FAILED / `PARSE_FORMAT_CHANGE`;
  - every row filtered out by the source's own status: EMPTY / `no_offered_status`.
- `build_state_basemap.py --rename FIPS=NAME`. us-atlas names both St. Louis County
  (29189) and the independent City of St. Louis (29510) "St. Louis"; the city is
  "St. Louis City".
- `states.py`: `_available_expansion()` registers MO, OK, PA and MN as activated
  county states with `production_inventory_types = {"", "POST_SALE"}`. Its
  `governance_approved` evidence states that every source is UNREVIEWED and never
  customer-published until approved.
- Registry: four generated rows, PRODUCTION_VERIFIED, ledger AVAILABLE,
  `publication_status = UNREVIEWED`. The existing 232 rows are byte-identical.
- Frontend:
  - `mo` / `ok` / `pa` / `mn` pages (generated) and county basemaps;
  - `STATE_META`, `MINIMAP_PROJ`, `STATE_ASSETS`, `PROJ`, `STATEWIDE_VIEW`;
  - per-state ledger copy;
  - service worker `tdw-shell-v75`;
  - mirror `FILES` list and CI importmap.
- Workflow: the `expansion` matrix gains MO, OK, PA and MN. They run in the existing
  12:00 UTC slot; no schedule changed.

## 4. Lifecycle

These rows use the same path as every expansion source:

- a COMPLETE or EMPTY county read closes rows the source no longer lists (`closed`,
  never sold);
- a FAILED or INCOMPLETE read closes nothing;
- one failing source never stops another state's leg.

## 5. Mississippi: deferred

| What was tried | Result |
|---|---|
| `sos.ms.gov` | HTTP 403 to the runners |
| The SOS tax-forfeited land portal | needs a login |
| The `tflgis` app's items | private |

The state GIS server (`gisserver.its.ms.gov`, Hosted folder) does carry
`Hinds_Tax_Forfeit_Properties_May_2026` (2,446 polygons). It was not used, because:

- its layer name is `Jackson_Blight_Hinds_Active_2026_May_12`: a City of Jackson
  blight-project snapshot frozen on 2026-05-12;
- every sampled row reads `Status = Active`;
- it publishes no definition of availability;
- it carries the assessed owner.

It is not the source of record and does not itself state that a parcel is offered,
so no adapter was built. The next step is a public SOS inventory endpoint, or
written permission to read the portal.

## 6. Not done here

- No source was approved.
- No production workflow was dispatched.
- No migration was created or applied (none is needed: POST_SALE and every amount
  kind used are storable since migration 020).
- No Michigan inventory was added.
- Auctions and certificates are unchanged.
