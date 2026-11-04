# Six-state expansion (2026-09-30)

Branch `claude/six-state-expansion`. Five new states are **production**
(MI, WY, SC, CO, WI). Two more, WV and UT, are **registered and gated**.
The sprint asked for six activated states. Five passed the gate. This file
says why, per source.

## 1. How the states were chosen

The candidates came from the repository's prior research:
- the 50-state audit;
- the AL / AR / LA / AZ onboarding docs;
- the MN, NC, CT, TN, MD, NJ, OH and VT leads.

Every candidate source was then read **live** by the manual evidence job:
`harvest-and-sync.yml` with `job=evidence` and `evidence_scope=expansion`,
running `scripts/capture_state_sources.py --expansion`. The sandbox cannot
reach state hosts, so every fact below comes from that job's value-free
digest. The digest records structure only: page titles, table headers,
ArcGIS field names and counts, licence text, and identifier shapes (each
digit becomes 9, each letter becomes A). It never records a row value.

| Pass | GitHub Actions ID |
|---|---|
| 1 | run 36778382226 |
| 2 | run 36779189506 |
| 3 | run 36780071129 |
| 4 | job 110112178937 |

A candidate became a state only when all three of these held:

1. **A real inventory list.** A government page or layer lists parcels in a
   sale, held by the county, or held as certificates.
2. **Verified columns.** The column names were read live, and identifiers
   have a stable shape.
3. **The owner's publication decision.** None of the county sources
   publishes an explicit reuse licence. The owner approved each one for
   publication on 2026-09-30. The approval is recorded in the registry
   `restrictions` column and in `harvesters/governance/states.py`
   (`EXPANSION_EVIDENCE`). It is an owner decision, not a claimed licence.

Candidates that failed the checks:
- **Login walls:** MD and NJ (RealTaxLien calendars).
- **No readable current inventory:** UT, whose next sale is May 2027.
- **Inventory behind a client-script flow no parser reads:** WV (State Auditor).
- **Guessed URLs that were not the claimed data:** for example, Burke NC's
  "Tax_Sales" layer turned out to be ordinary property transfers.

## 2. Source matrix

| State | Auction | Available | Lien / certificate | Statewide parcel ("FDOR equivalent") | Publication | Status |
|---|---|---|---|---|---|---|
| MI | Eaton County Treasurer "For Sale 2026" layer (min bid, own **Has Been Sold** flag, SEV, taxable value, acreage, use); Lenawee "2026 Tax Sale" layer (min bid, acreage) | none published | none | none open statewide (Michigan has no state parcel/CAMA layer with values) | owner-approved, no licence published | **production** |
| WY | Albany County "2026 tax sale properties, 1st list" (account, parcel, owner, address, legal, **Total** of unspecified kind, acreage, total value, tax year) | none | the sale sells certificates; none exist before the sale | none found with values | owner-approved | **production** |
| SC | York County "Tax Sale Properties" layer (tax map id, owner, location, type, acres, tax year, lat/lng); no amount | none | none | none found | owner-approved | **production** |
| CO | none tracked | none | **Morgan County county-held tax lien sale certificates** (cert #, account, name, legal, date eligible for auction, purchase amount good to a dated header) | **Colorado Public Parcels (OIT GIS), 2,599,744 parcels**: account, parcel id, owner, situs, legal, acres, land use, zoning, subdivision, last sale, total value, taxable value, polygons | county: owner-approved. Statewide: the State disclaims warranties and says **resale is forbidden**. The owner approved display (not resale) on 2026-09-30 | **production** |
| WI | Green County "Current Tax Deed Sales": current sealed-bid sales (the page says "no current sales" today) and Previous Sales with a published **Sale Price** | none | none | Wisconsin Statewide Parcels (SCO) exists; its service URL tried in this sprint returned no layers, and it was not in the owner approval set | owner-approved | **production** |
| WV | State Auditor statewide certified / sold / redeemed list | same | same | WV Parcels (1.39M, no values) | Auditor's terms grant no reuse right | **gated**: client-script flow + terms |
| UT | none current (next sale May 2027) | - | - | **UGRC SGID LIR parcels, CC BY 4.0**: market value, land value, acres, class, type, year built, sq ft, polygons (Salt Lake layer read) | CC BY 4.0 (attribution) | **gated**: no inventory |

**Richest statewide property data:**
- **Colorado** is the richest source actually in use: a statewide layer with
  values, use, zoning and polygons, matched by assessor account.
- **Utah's** UGRC LIR is richer per parcel (market and land value, year
  built, living area), but the state has no inventory to attach it to until
  2027.

## 3. Architecture added (reusable, not per-state code)

**Adapters and harvest**
- **`harvesters/otc/adapters/expansion.py`** holds the configuration only:
  one `ArcGisLayerConfig` or `TabularConfig` per source. It contains no
  parser. The shared adapters gained what these sources publish:
  - ArcGIS: owner, acreage, land use, taxable, assessed, market, tax year,
    lat/lng and a published sold flag.
  - Table: owner, certificate number, sale date, result amount, eligible
    date, label-to-several-fields mappings, required or forbidden headers,
    the source's own empty statement, and "N/A" cells treated as no value.
- **`OtcRecord`** handles auction records (`record_source="auction"`):
  - sale date and minimum bid are stored;
  - `status='closed'` is set only when the source publishes a sold flag or a
    completed-sale price;
  - absence alone never closes a record here.
- **`scripts/harvest_expansion.py`** is one runner for every state:
  - It gates on the state, the registry and verified columns, so a gated
    state makes 0 requests.
  - Each county gets a COMPLETE, EMPTY or FAILED status. A county with two
    sources (WI current + previous) is FAILED if either failed.
  - It de-duplicates on the upsert's conflict target.
  - It attaches purchase paths through the shared engine, to active rows only.

**Sync and lifecycle**
- **`scripts/sync_state_inventory.py --close-absent`**: stored active rows
  that a COMPLETE or EMPTY county read no longer lists become `closed`.
  Absence never means sold. An INCOMPLETE or FAILED read closes nothing.

**Statewide enrichment**
- **`harvesters/enrichment/`** is the factory for statewide parcels (the
  FDOR equivalent):
  - Config-driven: `ParcelSourceConfig`, registered in `sources.py`.
  - Deterministic match on (county, normalized identifier) only. AMBIGUOUS
    when two features match; UNMATCHED or NO_IDENTIFIER is recorded when
    none does.
  - Per-field provenance with source `statewide_parcel` (rank 2 in
    `field_provenance.RANK`).
  - Centroids only from the parcel's own polygon.
  - Coverage reported with denominators.
- **`scripts/enrich_statewide_parcels.py`** is the runner. Configs:
  - `co_oit_public_parcels`, active;
  - `ut_ugrc_lir_saltlake`, registered; the state is not activated.

**Acquisition**
- **Acquisition evidence** lives in `data/purchase_path_evidence_expansion.csv`:
  - The columns and verification rules are the same as the Florida table's.
    The two tables are kept separate.
  - Morgan CO: `quoted_amount`, bought from the County Treasurer for the
    listed amount; the steps are quoted from the page.
  - Green WI: `application_download`, the county's Tax Deed Bid Form, a
    sealed bid to the County Clerk.

**Frontend and workflow**
- **Frontend state factory**:
  - `scripts/build_state_basemap.py` builds the county SVG and centroids
    from us-atlas, and prints the exact projection.
  - `scripts/build_state_page.py` builds `<st>.html` from `tx.html` with
    five anchors.
  - Each state then needs one row in each of the state tables: STATE_META,
    MINIMAP_PROJ, STATE_ASSETS, PROJ and STATEWIDE_VIEW.
  - Per-state ledger copy lives in `EXPANSION_LEDGER_COPY`. Value labels are
    named as each source names them (`marketLabel`, `assessedLabel`).
  - The service worker's offline fallback serves any precached state page.
  - The header `#stateSelect` picks the new states up from STATE_META
    automatically.
- **Workflow**: the `expansion` job is a matrix over MI, WY, SC, CO and WI.
  - It runs in the existing 12:00 UTC slot and on `job=expansion`; no new
    schedule was added.
  - Steps: harvest, then sync with close-out, then statewide enrichment,
    then freshness and the publication gate, then an evidence-only artifact.

## 4. What is deliberately not done

- No purchase path for MI, WY or SC. No acquisition text was captured and
  verified for them.
- WI's Previous Sales price is stored as `result_amount` only because the
  county publishes it as "Sale Price". No purchaser or bidder is stored.
- Nothing is labelled Street View. No imagery beyond the existing ladder
  (the county-context mini-map) is added for these states.
- No fuzzy matching anywhere. CO parcels attach only on (county, account).
- Florida, Texas, Louisiana, Alabama, Arkansas and Arizona rows, sources and
  schedules are untouched.

## 5. Production activation (measured 2026-09-30, after run 36787016566)

Production writes, all authorized by the sprint:
- Six `county_source_registry` rows inserted; the York notes were then updated.
- Four `job=expansion` dispatches: 36785461117, 36786318568, 36786636912 and
  36787016566. The runs upsert only these five states' rows.
- Florida (3,872 rows) and Texas (543 rows) were not touched by any run.

Row counts:

| State | Counties | Auction | Available | Certificate | Active | Closed |
|---|---|---|---|---|---|---|
| MI | 2 (Eaton, Lenawee) | 43 | 0 | 0 | 38 | 5 (Eaton's own "Has Been Sold" flag) |
| WY | 1 (Albany) | 253 | 0 | 0 | 253 | 0 |
| SC | 1 (York) | 853 | 0 | 0 | 853 | 0 |
| CO | 1 (Morgan) | 0 | 0 | 3 | 3 | 0 |
| WI | 1 (Green) | 9 | 0 | 0 | 0 | 9 (Previous Sales) |
| **Total** | **6** | **1,158** | **0** | **3** | **1,147** | **14** |

Every row is `publication_status=APPROVED` and carries a source URL and
`otc_provenance`.

Coverage is filled rows / rows in that state (MI 43, WY 253, SC 853,
CO 3, WI 9):

| Field | MI | WY | SC | CO | WI |
|---|---|---|---|---|---|
| parcel / account | 43/43 | 253/253 | 853/853 | 3/3 | 9/9 |
| coordinates | 43/43 (own polygon) | 253/253 (own polygon) | 853/853 (own polygon) | 3/3 (statewide parcel polygon) | 0/9 |
| market / total value | 0/43 | 253/253 | 852/853 | 0/3 (not shared by Morgan) | 0/9 |
| assessed | 8/43 (SEV, Eaton) | 0/253 | 851/853 | 0/3 | 0/9 |
| taxable | 8/43 | 0/253 | 852/853 | 0/3 | 0/9 |
| land value | 0/43 | 245/253 | 841/853 | 0/3 | 0/9 |
| improvement value | 0/43 | 0/253 | 511/853 | 0/3 | 0/9 |
| acreage | 43/43 | 245/253 | 813/853 | 0/3 | 0/9 |
| land use | 7/43 | 0/253 | 853/853 | 0/3 | 0/9 |
| legal description | 43/43 | 253/253 | 852/853 | 3/3 | 0/9 |
| owner / name | 0/43 (not published) | 253/253 | 853/853 | 3/3 | 0/9 |
| situs address | 43/43 | 195/253 | 791/853 | 2/3 (statewide parcels) | 4/9 |
| opening / minimum bid | 43/43 | amount of unstated kind, 253/253 | not published | fixed purchase amount, 3/3 | 9/9 |
| published sale result | none published | none published | none published | none published | 8/9 (Sale Price) |
| verified acquisition path | 0/43 | 0/253 | 0/853 | 3/3 (multi-step, Treasurer) | 0/9 (all closed) |

**Imagery.** The new states get no new imagery source. The existing ladder
applies (county-context mini-map from the app's own basemap). Nothing is
labelled Street View.
