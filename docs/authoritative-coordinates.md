# Authoritative coordinates (2026-10-06)

`harvesters/sources/coordinates.py` is the one rule for where a property's
latitude / longitude came from and what may replace it. `app.js`
`coordinateProvenance()` mirrors it, and both are pinned by
`tests/python/fixtures/coordinate_cases.json`.

## Methods (strongest first) and geometry

| Method | Meaning | Authoritative |
|---|---|---|
| PARCEL_GIS | official county / state parcel layer, matched on the parcel id | yes |
| TAX_ROLL | official tax-roll / cadastral layer (FDOR NAL) | yes |
| LAND_BANK_GIS | the land bank's own layer (Detroit DLBA latitude / longitude attributes) | yes |
| OFFICIAL_ADDRESS | the location the source list itself publishes (East Baton Rouge list) | yes |
| OTHER_REVIEWED | government-published location of unstated derivation | yes |
| VENDOR_LISTING | coordinates in a vendor / counsel listing (Texas LGBS) | no |
| DETERMINISTIC_GEOCODE | US Census Bureau address geocode | no - an address location, never a parcel |
| UNRECORDED | coordinates on file, origin not recorded | no |

Geometry:

- `POINT`: a point the source published.
- `PARCEL_CENTROID`: the area-weighted centroid of the matched parcel polygon.
  It is not a building, and it is not the buildable area.
- `PARCEL_GEOMETRY`: the boundary itself (not stored).

## Matching and replacement

- **Matching.** A coordinate comes only from one feature matched on a strong
  identifier (parcel id, account, state parcel number, GIS id), or from an
  address that agrees on state, county and house number. Several features, a
  nearest-feature search, or a fuzzy address never produce a coordinate
  (`accept_match`).
- **Replacement.** Replacement only goes up the ranking, and never from
  authoritative to non-authoritative (`should_replace`).
- **Provenance rank.** In `scripts/field_provenance.py`, `census_geocoder`
  ranks 0, so any parcel layer replaces a geocode, and a geocode never
  replaces anything.

## Census geocoder (`scripts/geocode_properties.py`)

- **Independent cities.** "St. Louis City" now matches only the Census NAME
  "St. Louis city", never St. Louis County. Before this, every MO LRA row
  would have been rejected as county-mismatch.
- **Scoped runs.** `GEOCODE_SOURCE_ID=<source>` scopes a run to one AVAILABLE
  source, and is strict:
  - the Census match must also agree on the house number and the first
    street word;
  - each write carries `field_provenance` latitude / longitude entries
    (`census_geocoder`, `DETERMINISTIC_GEOCODE`, `POINT`), merged into the
    stored provenance;
  - the public log prints counts only.
- **Unscoped runs** behave exactly as before.

## Parcel layers for the coordinate gap

Found through the search index only, because every government host is
blocked from the sandbox. They are probed before any use.

| State | Layer | Key | Status |
|---|---|---|---|
| MO | City of St. Louis `GIS.ASR.PARCELS` (`stlgis.stlouis-mo.gov/.../PDA_ZONING/MapServer/0`) | `HANDLE` | `mo_stl_parcels_coordinates` config: centroid only, **inert** (columns not verified, UNREVIEWED) |
| OK | Oklahoma County Assessor `TaxParcelsPublics_view/FeatureServer/0` | to be read | probe target only |
| PA | PASDA `FayetteCounty/MapServer` | to be read (TAXIDNUM per the search index) | probe target only |
| SC | Horry County `Public/HorryCountyGIS/MapServer/24` | to be read | probe target only |

`scripts/discover_sources.py` `DEEP_TARGETS` carries all four:

- `available_mode=metadata` reads each layer's own fields;
- `available_mode=probe` measures exact identifier matches and ambiguity
  against our rows (value-free).

## Customer view

GIS & Location shows:

- **Coordinate source:** the method label, plus "Not an authoritative parcel
  location" when it is not one;
- **Location type:** Point or Parcel centroid, with a centroid note;
- or **"No authoritative coordinates available"** when there are none.

Imagery (PR #101) labels a geocoded point "Centered on the geocoded street
address (an address location, not the parcel boundary)".

## Production coordinate coverage (read-only SQL, 2026-10-06, active AVAILABLE)

| State | Rows | With coordinates | Method today |
|---|---|---|---|
| FL | 158 | 142 | TAX_ROLL (fdor_nal) for some, UNRECORDED for the rest |
| LA | 10,334 | 10,334 | OFFICIAL_ADDRESS |
| MI | 30,783 | 30,779 | LAND_BANK_GIS (Detroit), UNRECORDED (Oceana) |
| MN | 2 | 2 | PARCEL_GIS (point) |
| TX | 421 | 421 | VENDOR_LISTING (382), UNRECORDED (39) |
| MO | 9,758 | 0 | - (addresses on every row: geocode candidate) |
| OK | 195 | 0 | - (no address; parcel layer needed) |
| PA | 376 | 0 | - (no address; parcel layer needed) |
| SC | 52 | 0 | - (no address; parcel layer needed) |

## Needs authorization (not run)

1. **MO deterministic geocode.**
   - Workflow and variables: `GEOCODE_SOURCE_ID=mo_stl_lra_inventory GEOCODE_BATCH_LIMIT=<n> python scripts/geocode_properties.py` (a new manual step or a one-off dispatch).
   - Population: the 9,758 active `mo_stl_lra_inventory` rows with `latitude IS NULL`.
   - Fields written: `latitude`, `longitude`, `field_provenance.latitude/longitude`.
   - Match rule: Census one-line match agreeing on state, the St. Louis city county-equivalent, house number and street word.
   - Safety: rows with coordinates are never selected; the log is counts-only; a dry run (`GEOCODE_DRY_RUN=1`) first.
2. **Parcel-layer probes.** `job=available`, `available_mode=metadata`, then
   `available_mode=probe` (read-only, value-free). A probe result plus a terms
   review is needed before any coordinate config may be set
   `columns_verified=True` / APPROVED.
