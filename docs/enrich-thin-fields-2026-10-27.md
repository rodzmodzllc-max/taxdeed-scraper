# Thin-fields enrichment (2026-10-27)

The owner asked to fill the measured gaps on active rows: Colorado addresses, Oklahoma County address / land use /
value, lot size in Missouri, Louisiana and Tennessee, year built and building size where any official source
publishes them, and a reliable reader for the Genesee County (MI) Land Bank.

This work follows the standing decisions of 2026-10-25 / 2026-10-26: collect every public source now, legal review to
follow. New sources run on INTERIM `INTERNAL_RISK_ACCEPTANCE` permission records (fetch + enrich only, condition
`excluded_from_paid_tier`, expiring 2027-04-12). Those records are never permission.

No login, CAPTCHA, click-through, paywall, block or proxy was worked around. One host, `gis.okc.gov`, answered with an
Incapsula challenge page; it was left alone.

Every number below is a count. No parcel id, address, owner or value was printed into a file, a test, a commit or a
log. The tests use synthetic identifiers.

## How the numbers were measured

The measurements combine three sources:

- **Production gaps.** A read-only count query on 2026-10-27 over active rows, grouped by state, county and source.
- **Live layer reads from the sandbox.** For each layer:
  - its field list and metadata (`?f=json`);
  - a count;
  - an identifier-shape census (digits and letters masked);
  - a match of the harvested rows' own identifiers against the layer, counts only.
- **Dry runs of the real code.** The real adapters (`harvest_expansion.py`) ran without a database credential to
  produce today's list rows. The real factory then ran over those rows (`enrich_statewide_parcels.run_all_layers`, no
  write, live layer queries). Louisiana rows were built from the adjudicated dataset's own assessment numbers
  (`shrr-fsqq`, status `AJ`).

## Results per gap

### Colorado addresses (5% of 1,047 rows)

**Why `co_oit_public_parcels` matched only 64 of 994.** Saguache's 2026 Tax Sale list keeps the assessor ACCOUNT in
`case_no` and the 12-digit PARCEL number in `parcel`. The statewide OIT layer was matched only on `account`, using the
row's `parcel` column, so none of Saguache's 900 rows could match. The 64 matches were Morgan and Douglas rows.

The OIT layer publishes the parcel number as `parcel_id`. Read live, 200 of 200 sampled Saguache list parcels equal
exactly one `parcel_id` (0 ambiguous).

**Fix.** `alt_id_fields=("parcel_id",)`. An account (a letter followed by digits) and a parcel_id (12 digits) never
normalize to the same key. A key that reaches two different features is AMBIGUOUS, and nothing is written.

The where clause now names both attributes, so `batch_size` drops to 25. A GET longer than about 2 KB answered 404 in
the dry run.

**Dry run over all 1,047 CO rows:** 1,016 matched, 0 ambiguous, 31 unmatched. Fields written:

| Field | Rows |
|---|---|
| owner name | 1,013 |
| acreage | 666 |
| coordinates | 117 |
| legal description | 114 |
| market | 114 |
| taxable value | 114 |
| land use | 114 |
| address | 55 |

The dry-run rows carry no prior enrichment, so these counts overstate what production gains. Production is missing
acreage on 552 Saguache rows.

**Saguache address: no source.**

- OIT's `situsAdd` is blank on every sampled Saguache feature (0 of 200). So are its land use and values.
- The county's own `Saguache_County_Parcels_View` carries Address / City / State / Zip from an owner join. That is the
  owner's mailing address, not the situs, and it is never mapped.
- The county's `SaguAddressesOct31` address points carry no parcel or account number. Joining them would be a spatial
  join, not an identifier match.

**Douglas address (85 rows): no source.** The county's Property Location Data publishes no house number for those 85
accounts (53 of 138 have one), and no other Douglas OpenData layer carries a situs.

**Why `co_douglas_property_improvements` matched 138 of 138 as unmatched.** It is not an identifier mismatch. The
improvements layer's accounts have the same shape (letter + 7 digits). The held county liens' accounts simply have no
improvement record: the 138 parcels have no buildings. A live query for all 138 returned 0 features, while the same
accounts matched 138 of 138 in the locations layer.

**Morgan (9 rows):** OIT matches 3 and publishes a situs on 2. No other Morgan source was found.

### Oklahoma County (195 rows): address 2%, land use 0%, value 0%

**New layer: `ok_okc_government_owned_parcels`.** This is the City of Oklahoma City's "Oklahoma Government Owned
Properties" (ArcGIS Online item `45bc4f81…`, 6,100 parcels "owned by the city, the county, and the state", data last
edited 2023-12-01).

- **Match.** Its `Pin` is the county's 13-digit PIN without dashes, matched under the `digits` rule. A new `id_query`
  mode, `normalized`, queries the layer's dash-free spelling. Of the 195 list parcels, 155 matched exactly one feature
  and 3 were ambiguous.
- **What it writes.** `CLUCat` becomes `land_use`: "Undeveloped" on 163 matched features, "Unspecified" on 1 (stored as
  no value). The layer is fill-blank only.
- **Dry run:** land use on 151 rows.
- **Not mapped:**
  - `Address`: the county's "0 UNKNOWN …" situs on all but 1 matched parcel.
  - `Gross_SqFt`: the placeholder 1000 on 74 of 164 vacant parcels.
  - Values: 0, because the parcels are exempt.

**Address: no further source.** Results by candidate:

- The county assessor layer (`TaxParcelsPublics_view`) and `InternalParcelData_view` publish the same `location`
  situs, which reads "0 UNKNOWN" on these parcels.
- OKC's own GIS host (`gis.okc.gov`) answers with a bot challenge, which was not bypassed.
- No address-point layer carrying a PIN was found.

**Value: none.** County-owned parcels are exempt and carry 0, which is never stored.

### Lot size

| State / source | Rows (prod) | Source | Expected |
|---|---|---|---|
| MO St. Louis City LRA | 9,778 | Assessor layer 11 polygon, **derived** area | about 9,778 (400 of 400 sampled) |
| MO Kansas City Land Bank | 2,575 | portal `parcelSquareFootage`, **published** | about 2,575 (500 of 500 sampled) |
| PA Pittsburgh city property | (offered rows) | portal `parcelSquareFootage`, published | every row (500 of 500 sampled) |
| MI Saginaw Land Bank | 712 | portal `parcelSquareFootage`, published | about 85 (60 of 500 sampled) |
| LA East Baton Rouge | 4,520 | Tax Parcel `the_geom`, **derived** area | about 4,460 (296 of 300 sampled) |
| TN Shelby Land Bank | 1,784 | none | 0 |

**Published area first.** Several ePropertyPlus tenants publish `parcelSquareFootage` on their rows, and the adapter
did not read it. `EppConfig` gained three fields, `lot_sqft_field`, `year_built_field` and `living_area_field`, and
`OtcRecord` gained `lot_sqft`, `year_built` and `living_area`. Values are kept as published: positive and whole, with
year built between 1700 and 2100. An absent figure is never sent as NULL. The sync's `LIST_FIELDS` names them, so
they get `county_list` provenance and the enriched-value guard. Shelby publishes only `parcelLength` × `parcelWidth`,
and that product is never computed.

**Derived area when no area is defined.**

- **St. Louis.** `LandArea` and `SQFT` carry no published definition. The layer description is blank, and the
  `Parcels.shp.xml` metadata in the city's own `PARCELS.zip` has empty attribute definitions for both.
- **East Baton Rouge.** No dataset publishes a parcel area keyed on the assessment number:
  - the Lot, Lot Profile and Property Information datasets' `area_meas_acres` is keyed on a planning `lot_id`;
  - the roll's `units` counts structures.

For both, the factory's new `derived_lot_area` writes `lot_sqft` as the area of the matched parcel's own polygon:

- **Method.** Spherical excess on the WGS 84 authalic sphere; holes subtract.
- **Label.** The provenance entry carries `derived` = `parcels.DERIVED_AREA_NOTE`, which says it is a GIS area computed
  by us, not the deed or assessed lot size. The app prints it as "Derived by our system - …".
- **Precedence.** The value never replaces a published one: the shared precedence rule lets only a blank be filled.
- **Validation.** Over 400 St. Louis parcels, the computed area divided by the layer's `SQFT` has a median of 0.9994
  (p10 0.999, p90 0.999). `SQFT` is evidently the GIS polygon area. That was not taken as its definition; it only
  confirms the computation.
- **East Baton Rouge geometry.** The geometry is the dataset's own `the_geom` ("Shape geometry of the tax parcel",
  column definition read live), requested through `geometry_field` (Socrata only) and never stored.

**Tennessee (Shelby): no source.**

- The Assessor's GIS host answers 403.
- The statewide TN Property Boundaries layer excludes Shelby.
- The City of Memphis "SCLB" layer (1,050 Land Bank parcels, edited 2026-10-15) matched only 5 of 300 sampled list
  parcels on its trustee parcel id, and publishes no area.
- No other official Shelby parcel layer was found. A user-owned layer (e.g. "Shelby_Parcels" by a private account) is
  not an official source and was not used.

### Year built / building size

| State | Finding |
|---|---|
| MO | St. Louis: `FirstYearBuilt` is already mapped (no building area on layer 11). KC: the city's parcel layer (`mapd.kcmo.org` AGOL/6) has no year built; the portal fills `structureSquareFootage` on 2 of 500 rows (not mapped). |
| MI | **Saginaw** portal: `yearBuilt` on 22 of 500 rows and `structureSquareFootage` on 20, now kept. **Calhoun**: `structureSquareFootage` on 7 of 219, now kept as `living_area`. |
| LA | No EBR dataset publishes year built or building area (the Building Permits dataset's `squarefootage` is a permit's, keyed on an address). |
| TN | Shelby: none (see above); the portal's `squareFootage` (2 of 500) has no stated meaning and is not mapped. |
| SC | Horry assessor layer 24 has no year built. **Oconee** (new layer below) publishes none. |
| CO | Douglas improvements: none for the held accounts (no buildings). Saguache / Morgan: OIT publishes no year built. |

### SC Oconee (560 rows, every field missing)

This gap was not in the brief but was found in the same count. The new layer is `sc_oconee_county_parcels`: Oconee
County's own `OconeeCounty_Parcel_Jan2026` (data edited 2026-01-14).

- **Match.** `TMS_NUMBER` is written exactly as the tax sale list publishes the parcel. All 560 list parcels matched
  one feature.
- **What it writes:**
  - coordinates: the polygon centroid, on 560 rows;
  - `TMS_ACRES` → acreage, on 272 rows.
- **Not mapped:**
  - `GIS_ACRES`, a GIS computation;
  - `PROP_CLASS`, which reads 0 everywhere.
- **Not published.** The layer has no address, owner or value. The county's `DelTax2026` layer is the sale list itself.

### Genesee County (MI) Land Bank

The reader was held because the site answers HTTP 500 at random, a 500 can move its server-side page cursor, and the
three-attempt part restart could not get through the largest part (123 pages). Read live 2026-10-27:

- **Stated total.** Every result page states the search's size, for example "10668 properties found."
- **The parts add up.** The 31 township / Flint-quadrant parts sum to exactly the unfiltered total. The six filters
  that answer 500 every time hold no listings: the site errors on an empty filter, as every empty FindPropclass ×
  quadrant combination also does.
- **No shortcuts.** `FindPropclass` cannot split the big quadrants usefully (one class holds 111 pages), `FindParcNo`
  is ignored, and there is no page-jump or print-all.
- **Session navigation.** `LRCpage=` (empty) re-renders the session's current page, and `LRCpage=prev` steps back one
  page.

**What changed in `harvesters/otc/adapters/paged_table.py`:**

- **Exact totals (`total_pattern`).** A part must read exactly its stated size. The parts must add up to exactly the
  unfiltered size; the old one-page tolerance is gone. A part that never answers is accepted only when the exact sum
  still holds.
- **In-place recovery (`stay_data`, `prev_data`).** After a failed "next", the reader re-requests the current page. If
  the session is still on the last page read, it sends "next" again. If the cursor moved past the wanted page, it sends
  "prev" back to it. A page is accepted only when its counter is exactly the next number, so a recovery can never skip
  or repeat a page. A page not recovered in `recoveries_per_page` tries (4) restarts the part.
- **Duplicates.** The same listing twice within one session is FAILED.

**Live result from the sandbox:** see "Genesee live read" below. It stays **HELD**: it is not scheduled, and it is not
in `SOURCES["MI"]`, the ledgers, the permissions or the terms table. Activating it touches `harvest-and-sync.yml`'s MI
leg and the registry, and other sessions are editing that workflow. This PR makes the reader reliable. Scheduling it is
a separate, small follow-up.

## Candidates examined and not used

| Candidate | Why not |
|---|---|
| `gis.okc.gov` (OKC GIS server) | Incapsula bot challenge; not bypassed |
| OKC `InternalParcelData_view` | same `location` situs as the public layer ("0 UNKNOWN") |
| OKC `GovOwnedParcels` (2024) | layer serves no fields |
| Saguache Parcels View `Address` | owner mailing address (an owner join), never a situs |
| Saguache / Douglas address points | no parcel or account number (a spatial join is not an identifier match) |
| St. Louis `LandArea` / `SQFT` | no published definition (layer and shapefile metadata blank) |
| St. Louis `prcl.mdb` (120 MB) | no data dictionary in the archive |
| EBR Lot / Lot Profile / Property Information `area_meas_acres` | keyed on a planning lot id, not the assessment number |
| EBR Tax Roll `units` | counts structures (the dataset's own definition) |
| Shelby Assessor GIS | HTTP 403 |
| Memphis "SCLB" layer | 5 of 300 matched; no area |
| Private-account "Shelby_Parcels" layers | not an official publisher |
| Oconee `GIS_ACRES`, `PROP_CLASS` | a GIS computation; 0 everywhere |
| ePropertyPlus `parcelLength` × `parcelWidth` | a product of two figures, not a published area |
| ePropertyPlus `squareFootage` | no stated meaning (filled on 2 of 500) |
| KC city parcels (`mapd.kcmo.org`) | no year built / building area; values already on the rows |

## Genesee live read

The real adapter (`paged_table.fetch_all` with the Genesee configuration) ran from the sandbox on 2026-10-27, with no
database write. Over this proxy each request took about 6 seconds.

**Run 1: FAILED, correctly.** The parts added up to 6,477 listings against the stated 10,668. The old one-page
tolerance would also have refused it; the exact-total check named the gap. Nothing would have been written or closed.
Per-part logging was not on yet.

**Run 2 (after one fix): COMPLETE.** The fix: a transient page without a counter on the full search is now retried
(`attempts`) instead of failing the read at once.

| Measure | Result |
|---|---|
| Listings read | 10,668, exactly the stated total |
| Pages | 444 |
| Records kept | 10,190 |
| 'Demolition Program' rows excluded | 478 |
| Rejected identifiers | 0 |
| Run time | 3,031 s |

- **Unanswered parts.** The six filters that answer HTTP 500 every time (01, 06, 08, 51, 55, 61) were accepted only
  because the exact sum held.
- **Recoveries.** Two random HTTP 500s on "next" (Flint quadrants 41 and 46) were recovered in place, and both parts
  then read exactly their stated totals (2,306 and 2,755).
- **Proxy errors.** Two sandbox proxy errors were recovered the same way.
- **The largest part.** Quadrant 40 (3,061 listings, 123 pages), which failed on all three attempts on 2026-10-26, read
  completely.

## Applying it after merge (writes; owner-authorized runs only)

- **Expansion legs (daily, automatic).** The next scheduled expansion run handles MO, MI, PA, CO, OK and SC:
  - the sync carries the ePropertyPlus lot / building facts (KC, Pittsburgh, Saginaw, Calhoun);
  - `enrich_statewide_parcels.py --all-layers --limit 500` fills the derived St. Louis area, Saguache acreage, OK land
    use and Oconee coordinates / acreage, 500 rows per layer per run.
- **Backlog in one go.** Dispatch `job=enrich`, `enrich_kinds=parcels`, `enrich_states=MO,CO,OK,SC,LA`. Optionally add
  `enrich_limit=<N>` for bounded batches; the checkpoint resumes the next run. St. Louis alone is about 9,800 rows.
- **Louisiana.** Use `job=enrich` with `LA` (above), or `job=available`, `available_mode=apply`. The LA rows are not in
  the expansion matrix.
- **No probe dispatch is needed.** Every layer here was read live from the sandbox.
