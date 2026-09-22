# Phase 68: Geocoder builds from the row's state and verifies the county

Evidence-first fix to `scripts/geocode_properties.py` (the US Census Bureau
Geocoder backfill that runs in `harvest-and-sync.yml`'s deeds job right
before the FDOR step). Measured 2026-09-21/22 against production
(`gone_since IS NULL` unless stated) and the deeds job log of Actions run
35623773086.

## What the production log showed

The geocoding step's last run: **Geocoded 0, no match 249, errors 1 (of 250
attempted).** Every query was built as `"<address>, <county> County, FL"`:

- Texas rows were queried as Florida: `14107 HORSESHOE TRL, Dallas County,
  FL`, `4418 FIR ST, Nueces County, FL`, `Account 16941, Matagorda County,
  FL` (all 69 TX auction rows without coordinates).
- `<county> County` sat in the parser's CITY slot. The Census one-line
  parser has no county input, so bare street lines (the dominant shape:
  `2709 W TRAPNELL RD`, `615 WASHINGTON ST`) could never resolve.
- Rows with a ZIP but no comma (`321 GARFIELD DR 32505`,
  `10697 WILD TAMARIND DR\nTAMPA    33647`) were fetched in the junk tier,
  since "has a comma" was the only signal for "has usable context".

## What the stored coordinates showed

Distance from every stored coordinate to its own county's centroid
(`public/county-centroids.json`):

| Rows with coordinates | n | > 90 km from own county centroid |
|---|---:|---:|
| FL auction, geocoder-written (no FDOR stamp) | 48 | **2** |
| FL auction, FDOR centroid | 1,383 | 5 |
| FL certificate, geocoder-written | 56 | 0 |
| FL certificate, FDOR centroid | 666 | 1 |
| FL LAFT, FDOR centroid | 134 | 0 |
| TX auction / LAFT (harvester or geocoder) | 41 / 421 | 0 / 0 |

The two geocoder-written outliers are a **Lee County row at 40.84,-115.79
(Elko, Nevada)** and a **Leon County row placed in Osceola County** - the
parser's best nationwide guess for a bare street line, written unchecked.
Those coordinates then fed the FEMA flood lookup and the NAIP imagery step
for the wrong place. (The six FDOR-centroid outliers are a separate,
unrelated finding for the FDOR step - noted, not touched here.)

## The Lee / Volusia evidence pass (asked for before implementing)

| | Lee (auction) | Volusia (auction) | Volusia (LAFT) |
|---|---:|---:|---:|
| Unenriched by FDOR | 48 | 50 | 7 |
| Of those, no coordinates | 47 | 50 | 7 |
| Street number present | 40 | 40 | 0 |
| ZIP anywhere in the address | 1 | 1 | 4 (junk parcels) |
| Comma (city already spelled out) | 0 | 1 | 1 |
| City/ZIP anywhere else in the record (`url_*`, `legal_desc`) | 0 | 0 | 0 |

The deed harvester (`scripts/harvest_all_counties.ps1`) already captures the
RealAuction listing's unlabelled city/ZIP line when the site shows one and
appends it with a comma. A Lee or Volusia row with no comma therefore had no
city or ZIP at the source either; nothing was dropped on the way in.

**Recoverable by the geocoder for Lee + Volusia: about 2 rows** (the one
ZIP-bearing row in each). The remaining ~95 rows can only be geocoded as
`<street>, FL` and kept if the Census answer verifies to the right county -
possible, not promised. Their real fix is the FDOR side, kept separate:

- Lee: 57 STRAPs with numeric area codes (`14-44-26-03-00028.0100`) have no
  layer rows under the prefix the alnum-area STRAPs match on (probe
  evidence, Phase 65) - identifier shape still unresolved.
- Volusia: the probe hit 6/6 sampled auction parcels exactly. Its backlog
  is 228 certificate rows the layer never matches next to 50 auction rows,
  and the per-county miss streak abandons the county before an auction row
  is reached. That is a scheduling gap in `enrich_property_details.py`, not
  a source miss - a separate change.

## Does the `, FL` suffix explain the Texas failures?

Only for the cross-state subset. `state` is never NULL on any row (0 of
5,000+); Florida rows were already asked for as Florida. Of the 69 TX
auction rows without coordinates, 40 carry a street number, 11 of those a
ZIP, 29 are bare street lines, 29 have no street number at all. The bare
Texas lines would have failed under either state; the 11 ZIP-bearing rows
and any city-bearing ones (`14317 ILLINIOS DR LA FERIA`) are the ones the
correct state can recover. The Census endpoint itself could not be called
from the assistant's sandbox (egress proxy rejects the CONNECT), so the
per-row outcome is measured by the dry-run workflow below, not projected.

## Rows that carry usable context and no coordinates (statewide)

| | no coords | street number | street + ZIP | street only (no ZIP/comma/newline) | no street number |
|---|---:|---:|---:|---:|---:|
| FL auction | 364 | 282 | 34 | 248 | 82 |
| FL certificate | 924 | 154 | 137 | 13 | 770 |
| FL LAFT | 25 | 0 | 0 | 0 | 25 |
| TX auction | 69 | 40 | 11 | 29 | 29 |

So the priority tier the fix introduces (comma or ZIP) holds roughly 180
rows across both states; 137 of them are certificates (mostly one
Miami-Dade condo building whose 55 sibling units already geocoded under the
same address shape).

## The fix

`scripts/geocode_properties.py`:

- `build_query(address, state)`: newline city lines become comma context,
  whitespace collapses, the row's own `state` is appended unless the
  address already names it, the county is never appended, nothing is
  invented. A row with no `state` is skipped, never defaulted to Florida.
- Switched to the `geographies/onelineaddress` endpoint
  (`vintage=Current_Current`) so every candidate carries the county its
  point falls in. `verify_match()` accepts a candidate only when
  `addressComponents.state` equals the row's state AND a returned county
  name equals the row's county (normalised: `St. Lucie`, `Miami-Dade`,
  `DeSoto`). No county in the response = rejected. Every candidate is tried
  in order; the first that verifies wins.
- Fetch tiers: `or(address.like."*,*",address.match."[0-9]{5}")` first,
  its exact complement second. `state` is selected, never filtered on.
- `GEOCODE_DRY_RUN=1` runs everything and writes nothing;
  `.github/workflows/geocode-dry-run.yml` uses it to measure the verified
  match rate on live rows (read-only, manual or push to the evidence
  branch).
- The PATCH body is still `{latitude, longitude}` only, on rows selected
  with `latitude IS NULL` - existing coordinates are never overwritten,
  and no enrichment here can change a row's state, county or source.

`tests/python/test_phase68_geocoder_state_context.py` (20 checks) covers:
FL row -> FL query without county; TX row -> TX query, never FL; newline
and trailing-ZIP context preserved, already-stated state not doubled;
bare street gets no invented city and is written only when the county
verifies (the Leon/Osceola case is rejected, a county-less response is
rejected, the Nevada candidate is skipped in favour of a later verified
one); a TX row answered with a Florida point is rejected; the PATCH body
never carries state/county; a row without state is skipped; every fetch
targets `latitude IS NULL` with no state filter; dry run writes nothing.

## Not done here, on purpose

- The two wrong-county coordinates already stored (Lee -> Nevada, Leon ->
  Osceola) and the six FDOR-centroid outliers are left in place. Clearing
  them (and the flood/imagery values derived from them) is a production
  data change to approve separately; once cleared, the corrected geocoder
  will re-attempt them under the county check.
- The FDOR-side gaps (Lee identifier shape, Volusia certificate
  starvation, Pasco 19-character folios, Hillsborough/Brevard/Suwannee
  account numbers) are unchanged.
