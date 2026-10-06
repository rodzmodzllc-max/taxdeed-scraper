# AVAILABLE quality: three independent workstreams (2026-10-06)

`scripts/available_quality_report.py` measures every active AVAILABLE row on
three workstreams. Each is counted separately, so a gap in one never shows up
as a gap in another. The report is counts only and carries no values.

| Workstream | Rule | Counts per (state, source) |
|---|---|---|
| A. Acquisition evidence | per unit, `public/acquisition-evidence.json` `status` (`docs/acquisition-evidence-status.md`); a typed verified path on the row also counts | verified / needs_review / unavailable / not_found |
| B. Coordinates | `harvesters/sources/coordinates.py` (`docs/authoritative-coordinates.md`) | authoritative_parcel_gis / official_address / deterministic_geocode / vendor_listing / origin_not_recorded / missing |
| C. Amounts | `harvesters/sources/amount_semantics.py` (`docs/current-acquisition-amounts.md`) | current_purchase_price / current_amount_due / opening_bid / minimum_bid / other_published_amount / no_current_amount / published_taxes / published_fees / temporal_* |

## Production measurement (read-only, 2026-10-06, 52,079 active rows)

### A. Acquisition evidence

| State | Rows | Verified | Needs review | Unavailable | Not found |
|---|---|---|---|---|---|
| FL | 158 | 45 | 8 | 31 | 74 |
| LA | 10,334 | 10,334 | 0 | 0 | 0 |
| MI | 30,783 | 5 | 30,778 | 0 | 0 |
| MN | 2 | 0 | 2 | 0 | 0 |
| MO | 9,758 | 0 | 9,758 | 0 | 0 |
| OK | 195 | 195 | 0 | 0 | 0 |
| PA | 376 | 0 | 376 | 0 | 0 |
| SC | 52 | 52 | 0 | 0 | 0 |
| TX | 421 | 183 | 0 | 0 | 238 |

Before this sprint there was no status: only 10,813 rows with a typed path,
and every other row read the same "not yet verified".

### B. Coordinates

| | Rows |
|---|---|
| Parcel / tax-roll / land-bank GIS | 30,783 |
| Official address published by the source | 10,334 |
| Vendor listing (Texas LGBS) | 382 |
| Origin not recorded | 179 |
| Deterministic geocode | 0 |
| Missing | 10,401 |

The missing rows are 9,758 MO, 376 PA, 195 OK, 52 SC, 16 FL and 4 MI.

### C. Amounts

| | Rows |
|---|---|
| Current purchase price | 40 |
| Current amount due (statement) | 0 |
| Opening bid | 480 |
| Minimum bid | 405 |
| Other published amount | 243 |
| No amount published | 50,911 |
| Published taxes | 0 |
| Published fees | 0 |

Time status of the 1,168 published figures:

| Status | Rows |
|---|---|
| CURRENT | 1,126 |
| HISTORICAL | 2 |
| UNKNOWN | 40 |
| EXPIRED | 0 |

## Production runs that would move these numbers (not run; need authorization)

1. **Acquisition evidence capture.**
   - Run: `harvest-and-sync.yml`, `job=evidence`, `evidence_scope=acquisition_candidates`, `evidence_counties="St. Louis City,Fayette,Ramsey,Wayne"`.
   - Reads only the official candidate pages in `data/acquisition_candidate_pages.csv`, prints a value-free digest, and writes nothing.
   - A verified evidence row is added afterwards, by hand, from the digest.
2. **MO coordinates by Census geocode.**
   - Run: `scripts/geocode_properties.py` with `GEOCODE_SOURCE_ID=mo_stl_lra_inventory`.
   - Population: 9,758 active MO laft rows.
   - Writes: `latitude`, `longitude` and `field_provenance.latitude/longitude` (`census_geocoder`, DETERMINISTIC_GEOCODE).
   - Match rule: one Census match whose state is MO, whose county is "St. Louis city", and whose house number and first street word equal the row's.
   - Safety: dry run first; counts-only log; never replaces an existing coordinate.
3. **OK / PA / SC parcel-layer coordinates.**
   - Run: `job=available`, `available_mode=metadata`, then `probe`, against the DEEP_TARGETS in `scripts/discover_sources.py`.
   - Read only. The layers' terms need a publication review before any write.
