# Phase 69: FDOR enrichment starvation by certificate rows, measured and fixed

Companion to `docs/phase-68-geocoder-state-context.md`. All numbers measured
2026-09-22 against production (`gone_since IS NULL`) and Actions logs.

## 0. The Texas-as-Florida trace (asked for first): no identity contamination

- Every Texas row carries `state = 'TX'` and a `harvester_source`
  (`tx_lgbs` 19 auction + 421 LAFT, `tx_realauction` 91 auction); no Florida
  row carries one; `state` is NULL on 0 rows.
- The five Texas addresses that appeared in the geocoder log as "Cameron
  County, FL", "Dallas County, FL" etc. exist only as `state = 'TX'` rows
  (5 of 5); no Florida row has those addresses.
- Live unique key: `properties_state_source_county_case_no_key UNIQUE
  (state, source, county, case_no)` (migration 004); both sync paths
  upsert on that key.
- The "County, FL" text came from one line in the old
  `scripts/geocode_properties.py`: `query = f"{address}, {county} County, FL"`
  and the matching `print`. Nothing in the harvesters, sync scripts,
  RPCs or the FDOR script relabels a row. The geocoder's 0 of 250 was an
  independent defect (county in the parser's city slot, hard-coded state,
  no answer verification), fixed in PR #26 with a measured 295 of 600.

## 1. Processing order, reconstructed from the code and the data

`enrich_property_details.py` (`fetch_county_batch` + `main`):

- Slice = up to `PER_COUNTY_LIMIT` (40) unenriched rows of one county,
  ordered `id ASC` (v4 UUIDs, so a fixed but arbitrary order), starting at
  a random offset in `[0, outstanding - 40]`.
- Rows are looked up in that order; one county-wide `miss_streak`; at
  `COUNTY_MISS_STREAK` (6) consecutive misses the rest of the slice is
  abandoned for the run. A miss is never stamped, so the same rows return
  next run.
- The per-county log line prints `matched / len(rows)`, i.e. the slice
  length, not the rows looked up: "Escambia: 0/40" means six lookups.

Measured order of each county's unenriched rows (A = auction, L = LAFT,
c = certificate, M = Santa Rosa 20-char `…M` certificate):

| County | outstanding | auction+LAFT | first auction at | longest certificate run |
|---|---:|---:|---:|---:|
| Escambia | 42 | 6 | position 32 | 31 (a contiguous prefix: `c×31 AAcAAccAccA`) |
| Volusia | 285 | 57 | position 8 | 47 |
| Santa Rosa | 345 | 12 | position 10 | 68 |

Simulation over every possible window start, assuming certificates miss and
auction rows hit (both confirmed below):

| County | runs that reach any auction row (old) | (per-source streak) | auction rows attempted per run (old → new) |
|---|---:|---:|---:|
| Escambia | 0 of 3 windows (0%) | 3 of 3 (100%) | 0.00 → 5.33 |
| Volusia | 155 of 246 (63%) | 238 of 246 (97%) | 2.70 → 8.18 |
| Santa Rosa | 69 of 306 (23%) | 249 of 306 (81%) | 0.26 → 1.46 |

Requests per run stay bounded: max 12 / 19 / 9 per county under the new
rule vs 6 / 40 / 17 before.

## 2. Identifier clusters

| County | source | unenriched | identifier shape | matches the layer? |
|---|---|---:|---|---|
| Escambia | auction | 6 | 16-char `362S301500001006`, same as its 37 enriched | yes, 6 of 6 |
| Escambia | certificate | 36 | 11-char account `11-1856-000` | no, 0 of 12 sampled |
| Volusia | auction | 50 | 12-digit, same as its 23 enriched | yes, 50 of 50 |
| Volusia | LAFT | 7 | 4 real 12-digit + 3 junk (`WNISTHEORIGINALOPENING`) | 1 of 4 real; junk never |
| Volusia | certificate | 228 | 12-digit `722000004331` | 1 of 12 sampled |
| Santa Rosa | auction | 12 | 24-char dashed, same as its 19 enriched | yes, 12 of 12 (directly in FDOR) |
| Santa Rosa | certificate | 333 | 20-char `121N270000001000000M` | 0 of 12 sampled |

The certificate rows do consume the streak budget: in Escambia they are a
contiguous 31-row prefix, so every window opens with six certificate misses.

## 3. History: attempted-and-missed vs never attempted

Enrichment stamps for the three counties' auction rows: Escambia 09-02,
09-03, 09-15, 09-18, 09-19 (15 rows); Volusia 09-02, 09-15, 09-17, 09-18
(11 rows), 09-19 (1); Santa Rosa 09-07, 09-15, 09-17, 09-18. None since,
across six scheduled runs. The two most recent deeds-job logs (runs
35545626749, 35623773086) both print "[Escambia] 6 consecutive misses",
"[Volusia] 6 consecutive misses", "[Santa Rosa] 6 consecutive misses" and
"0/40" for each.

The database cannot separate "attempted and missed" from "never attempted"
(misses are not stamped), so a read-only probe (`scripts/probe_fdor_
starvation.py`, Actions run 35722298578) asked the layer about every
unenriched auction/LAFT row through the production `lookup_fdor()` and the
Santa Rosa fallback:

| County | auction/LAFT rows | hit | miss |
|---|---:|---:|---:|
| Volusia | 57 | 51 | 6 (3 junk LAFT parcels, 3 LAFT parcels absent from the layer) |
| Escambia | 6 | 6 | 0 |
| Santa Rosa | 12 | 12 | 0 |

A hit here would have been stamped by any production attempt (the stamp is
in the same PATCH as the data). **69 unstamped rows that hit = 69 rows the
job never reached.** Starvation is proven, not inferred.

## 4. Pasco's 19-character identifier

The 7 unenriched Pasco auction rows store the appraiser's key
(`url_appraiser=...parcel.aspx?parcel=162632001000J000170`). Pasco's own
enriched rows show the relationship between that key and the layer's
dashed `PARCEL_ID`:

| stored parcel (dashed) | appraiser key | rule |
|---|---|---|
| `26-24-21-0120-00000-00B1` | `21242601200000000B1` | key = RR TT SS BBBB BBBBB LLLL |
| `18-26-16-0400-00004-014A` | `162618040000004014A` | (first and third pairs swapped, dashes removed) |

So the 19-character key is a legitimate alternate identifier, not a
normalization defect, and the transformation is `RRTTSS…` →
`SS-TT-RR-BBBB-BBBBB-LLLL`. The Phase 65 probe tried the naive re-dash
(no swap) and got 0 of 6. The swapped form hit **7 of 7**, and the layer's
own street returned for each matches the row's stored address (`1824 DIXIE,
HOLIDAY` ↔ "1824 Dixie Ln, Holiday FL 34690"; `11725 PARAMUS, SPRING HILL`;
`1522 ELITE, HOLIDAY`; `3621 ANNONA, HOLIDAY`; `11921 FRONTAGE, DADE CITY`;
`6712 TOWER, HUDSON`). Not implemented here - it is a `normalize_candidates()`
rule, i.e. FDOR matching logic, which this phase was told not to change; it
is ready as a one-rule follow-up with this evidence.

## 5. The fix (decision gate passed)

`main()` keeps one miss streak **per source** within the county's slice.
A ledger that has missed `COUNTY_MISS_STREAK` times in a row is skipped
for the rest of the slice without spending a request; the other ledgers
continue. Nothing else changes:

- runaway protection: still at most 6 consecutive paid misses per ledger
  (worst case 3 ledgers × 6 = 18 lookups per county per run, vs 6);
- the global threshold is unchanged;
- no legitimate row is skipped: a ledger that hits keeps going, exactly as
  before;
- idempotent: misses stay unstamped, hits stamp in the same PATCH;
- `fetch_county_batch` now selects `source` (never filters on it);
- the per-county report prints `matched / rows looked up` instead of
  `matched / slice length`.

`tests/python/test_phase69_fdor_per_source_miss_streak.py` replays
Escambia's exact 42-row sequence (6 certificate lookups, then all 5
in-window auction rows written) and covers the per-ledger cap, the
independent reset, a matching certificate, idempotency and the report line.

## 6. Expected impact (measured, not projected)

69 auction/LAFT rows are proven matchable and unreached: Volusia 51,
Escambia 6, Santa Rosa 12. They enrich over the next few scheduled runs
(Escambia in one, Volusia over roughly a week given a 40-row window across
285 outstanding rows, Santa Rosa slower - see the simulation). On the
433-row FL auction+LAFT gap that is 16%. Pasco's 7 wait on the follow-up
rule above.
