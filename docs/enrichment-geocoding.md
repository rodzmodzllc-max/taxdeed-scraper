# Enrichment priority and authoritative geocoding (2026-10-06)

This sprint improves property data, not the UI. It adds three pieces:

* an explicit **enrichment priority** for every active record;
* an **authoritative geocoding pipeline** with plan / dry-run / apply modes;
* a counts-only **enrichment audit** per state × county × ledger.

## 1. Measured baseline (production, read-only, 2026-10-06)

All counts are active records (status `active` or `available`). A record is
"visible" when its publication status is NULL (auction and lien sources) or
APPROVED / APPROVED_GRANDFATHERED.

Column notes:
* **Coords** = rows with coordinates.
* **Auth.** = authoritative coordinates: from a parcel layer, the tax roll, a
  land bank, or an official list location.
* **Unrecorded** = rows with coordinates whose origin was never recorded.

| State | Ledger | Active | Visible | Coords | Auth. | Unrecorded | No coords |
|---|---|---:|---:|---:|---:|---:|---:|
| CO | Liens | 144 | 144 | 117 | 117 | 0 | 27 |
| FL | Auctions | 1,351 | 1,351 | 1,104 | 189 | 915 | 247 |
| FL | Available | 158 | 158 | 142 | 3 | 139 | 16 |
| FL | Liens | 1,611 | 1,611 | 839 | 25 | 814 | 772 |
| LA | Available | 10,334 | 10,334 | 10,334 | 10,334 | 0 | 0 |
| MI | Auctions | 38 | 38 | 38 | 38 | 0 | 0 |
| MI | Available | 30,783 | 0 | 30,779 | 30,778 | 1 | 4 |
| MN | Available | 2 | 0 | 2 | 2 | 0 | 0 |
| MO | Available | 9,758 | 0 | 0 | 0 | 0 | 9,758 |
| OK | Available | 195 | 0 | 0 | 0 | 0 | 195 |
| PA | Available | 376 | 0 | 0 | 0 | 0 | 376 |
| SC | Auctions | 853 | 853 | 853 | 853 | 0 | 0 |
| SC | Available | 52 | 0 | 0 | 0 | 0 | 52 |
| TX | Auctions | 122 | 122 | 82 | 0 | 82 | 40 |
| TX | Available | 421 | 421 | 421 | 0 | 39 | 0 |
| WY | Auctions | 253 | 253 | 253 | 253 | 0 | 0 |

Notes on the table:
* TX Available's 382 other coordinates come from vendor listings (LGBS), which
  are never authoritative.
* Florida's "unrecorded" coordinates (1,868) were written before coordinate
  provenance existed. They are most likely US Census address geocodes. Their
  origin cannot be attested, so the app labels them "Origin not recorded".

The same measurement covered the other fields. Coverage by ledger:

| State | Ledger | Parcel | Legal desc. | Value | Taxable | Acreage | Land use | Acq. evidence |
|---|---|---|---|---|---|---|---|---|
| FL | Auctions | 97% | 73% | 92% | 68% | 67% | 72% | 0% (no auction acquisition path) |
| FL | Liens | 100% | 33% | 100% | 32% | 42% | 32% | 0% |
| FL | Available | 99% | 91% | 90% | 80% | 89% | 90% | 28% |
| TX | Auctions | 100% | 8% | 100% | 0% | 0% | 0% | 0% |
| TX | Available | 100% | 56% | 100% | 0% | 0% | 0% | 43% |
| LA | Available | 100% | 81% | 100% | 56% | 0% | 58% | 100% |
| SC | Auctions | 100% | 100% | 100% | 100% | 95% | 100% | 100% |
| WY | Auctions | 100% | 100% | 100% | 0% | 97% | 0% | 0% |

FL "Value" is the assessed or just value. FDOR enrichment covers 983 of 1,351
FL auction rows and 671 of 1,611 FL lien rows.

County-level counts come from `scripts/enrichment_audit.py`, which runs as the
first step of the `geocode` workflow job and writes
`out/public/enrichment-audit.json` (counts only). A county breakdown was not
pulled into this document: a further production query was declined during the
sprint.

## 2. Enrichment priority (`harvesters/enrichment/priority.py`)

There is no score. A record's priority is the first rule that holds:

| Rule | Holds when |
|---|---|
| P1 | Customer-visible AVAILABLE record |
| P2 | Customer-visible AUCTION record |
| P3 | Customer-visible LIEN / CERTIFICATE record |
| P4 | County with a VERIFIED acquisition path (`public/acquisition-evidence.json`) |
| P5 | County listed for market testing (`data/market_test_counties.csv`) |
| P6 | Strong identity (an identifier with a digit) and at least one enrichment gap |
| P7 | Any other active record |

* **Order:** records are worked in rule order, then by state, county and id,
  so two runs visit the same rows in the same order.
* **Inactive records** are never enriched.
* **Hidden records:** UNREVIEWED / RESTRICTED / BLOCKED records are collected
  for admins only, so they never outrank a record a customer can see.
* **Gaps:** `priority.gaps(row)` lists a record's gaps in investor order:
  coordinates, parcel, legal description, assessed value, taxable value,
  acreage, land use, acquisition evidence (Available only), imagery.

## 3. Authoritative geocoding

### Sources (`harvesters/enrichment/geocode.py`)

| Source | Where | Method | Geometry | Provenance |
|---|---|---|---|---|
| FDOR Florida Statewide Cadastral | FL, every county | TAX_ROLL | PARCEL_CENTROID | `fdor_nal` |
| Santa Rosa ParcelsOpenData | FL, Santa Rosa | PARCEL_GIS | PARCEL_CENTROID | `county_gis` |
| Every parcel layer with `centroid=True` (CO OIT statewide, ...) | its state / counties | PARCEL_GIS | PARCEL_CENTROID | `statewide_parcel` |

A source is queried only when its publication is APPROVED / APPROVED_GRANDFATHERED
**and** its columns were read live. Otherwise the plan says
`SOURCE_NOT_APPROVED` or `SOURCE_UNVERIFIED`. Today that covers:
* MO St. Louis parcels: UNREVIEWED, never read;
* TX Jim Wells CAD: UNREVIEWED.

Flagler's county layer returns no centroid, so it is not a coordinate source.

### Matching

* The record's own parcel or account identifier is matched against the layer.
  The FL lookups reuse the FDOR enricher's county-scoped candidate spellings
  and its proven ALT_KEY rule.
* **Exactly one feature** is a match. None is `NO_MATCH`; several is
  `AMBIGUOUS`, and nothing is attached.
* There is **no address matching, no fuzzy or partial match, no nearest
  feature, and no other property's point**. A record with an address but no
  identifier is `NO_IDENTIFIER`.
* The point is the matched polygon's centroid. A point outside the record's
  state (a projection error or swapped x / y) is a `PARSER_FAILURE`, never a
  pin.

### Replacement

| Stored coordinate | What the pipeline does |
|---|---|
| None | Any authoritative match is written |
| Authoritative, equal or stronger | Never replaced (`ALREADY_AUTHORITATIVE` / `STRONGER_OR_EQUAL_EXISTING`) |
| Weaker origin (unrecorded, vendor listing, address geocode) | Replaced only with `--allow-upgrade`; counted separately as `UPGRADE` / `UPGRADE_NOT_REQUESTED` |

The field-provenance rule treats a value with no recorded origin as
government-rank, so replacing one is an explicit decision.

### Provenance written

`field_provenance.latitude` and `field_provenance.longitude` receive the same
entry:
* `source`: `fdor_nal` / `county_gis` / `statewide_parcel`;
* `method` and `geometry`;
* `match: parcel_id`, `matched_identifier`, `matched_field`;
* `source_id`, `agency`, `dataset`, `layer_url`, `landing_url`;
* `recorded_at` (the read date);
* `derived` and `pipeline: geocode_authoritative`.

`coordinates.coordinate_provenance()` reads such an entry back as an
authoritative TAX_ROLL / PARCEL_GIS parcel centroid.

### Workflow (`scripts/geocode_authoritative.py`, job `geocode`)

| Mode | Does |
|---|---|
| `plan` (default) | Classifies every active record and orders candidates by priority. No source request, no write. |
| `dry-run` | `plan` plus the lookups: matched / no match / ambiguous / source unavailable / parser failure, and how many coordinates would be written. Nothing is written. |
| `apply` | The dry run plus the writes. The script also needs `--confirm-apply`; the workflow passes it only when the mode is `apply`. |

Further guarantees:
* One failed write or one failed county query never stops the run; it is counted.
* The log and `out/public/geocode-<mode>.json` are counts only.
* The job is manual only, never scheduled, and never part of `all`.

### Plan projected from the measured baseline

The pipeline's own plan needs the workflow, which was not dispatched. From the
counts above:

| Population | Class | Records |
|---|---|---:|
| FL rows without coordinates | `MISSING` (FDOR / Santa Rosa) | 1,035 (247 auction, 16 Available, 772 lien) |
| CO lien rows without coordinates | `MISSING` (CO OIT) | 27 |
| FL rows with unrecorded coordinates | `UPGRADE_NOT_REQUESTED` (`UPGRADE` with `--allow-upgrade`) | 1,868 |
| MO St. Louis | `SOURCE_NOT_APPROVED` | 9,758 |
| TX outside Jim Wells | `NO_SOURCE` | — |
| OK / PA / SC Available | `NO_SOURCE` | — |

How many of the FL / CO candidates match is only known from a dry run.

## 4. Running it (needs authorization; nothing has been dispatched)

1. `job=geocode`, `geocode_mode=plan`: read-only; writes the audit and the
   plan counts.
2. `job=geocode`, `geocode_mode=dry-run`, `geocode_states=FL,CO`: source reads
   only. It reports matched / no match / ambiguous / unavailable / parser
   failure and `would_write`.
3. `job=geocode`, `geocode_mode=apply`, the same states, after the dry run is
   reviewed. Writes only the coordinates and their provenance.
4. Optional, separately: `geocode_allow_upgrade=yes` to replace the 1,868
   unrecorded Florida coordinates with FDOR parcel centroids. This changes
   where existing pins sit, so review it on its own.

Imagery follows coordinates. A record that gains authoritative coordinates
gets the live USDA NAIP view on its card and property page with no further
step, and no image is stored.
