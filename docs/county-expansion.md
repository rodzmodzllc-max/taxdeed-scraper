# County Expansion (Phase 38)

What this phase actually did, stated narrowly so it cannot be read as more.

## The two directories that were read

| Directory | Operator | Coverage | Evidence |
|---|---|---|---|
| County directory, 254 per-county pages | Texas Comptroller of Public Accounts | 254/254 TX counties | `comptroller.texas.gov/taxes/property-tax/county-directory/<slug>.php` |
| Local Officials directory | Florida Department of Revenue | 67/67 FL counties | `floridarevenue.com/property/Pages/LocalOfficials.aspx` |

Both were fetched and read in full on 2026-09-16. The Texas path is covered by
that host's `robots.txt` (`Allow: /taxes/`). The Florida page is the one Phase 35
recorded as `MECHANISM_CONFIRMED_NOT_EXTRACTED` because its county list is not
statically linkable; the three dropdowns (Property Appraiser, Tax Collector,
Value Adjustment Board/Clerk) were read out of the page's own DOM, which is what
closed that gap.

## What was extracted

- **Texas**, per county: Comptroller county code, Appraisal District chief
  appraiser + website + the directory's own "Last Updated" date, Tax
  Assessor-Collector name + website + "Last Updated".
- **Florida**, per county: Property Appraiser URL, Tax Collector URL, Value
  Adjustment Board / Clerk URL.

Raw extracts are checked in under `data/reference/` so every derived row can be
traced to the exact text that produced it. `scripts/build_phase38_expansion.py`
rebuilds every artifact from them.

## What this proves, and what it does not

It proves that **the state itself names this office and this URL for this
county**, and that the directory entry was read rather than guessed.

It does not prove the county site is reachable, that it offers bulk data, GIS or
an API, or — decisively — that its terms permit automated access, storage,
customer display, export or redistribution. **No county site was fetched this
phase and no county's terms were read.** Under Phase 38 Section 31, permission is
never inferred from silence, so every county office lands at
`LEGAL_REVIEW_REQUIRED`.

`DISCOVERED != VERIFIED != AUTHORIZED != PRODUCTION`. This phase moved 321
counties along the **first arrow only**. Nothing was promoted, enabled, or
harvested.

## Vocabulary

`SourceStatus` in `harvesters/governance/registry.py` is unchanged — the eight
approval states stand and no second legal-status system exists. One value was
added to the CSV-level `verification_status` vocabulary the coverage maps
already use:

```
DIRECTORY_LISTED - a state-operated directory names this office and this URL,
                   and that directory entry was read. The office's own site was
                   not fetched and its terms were not reviewed.
```

It sits deliberately **below** the existing `MECHANISM_CONFIRMED` and
`CONTENT_VERIFIED`. Writing these rows as `CONTENT_VERIFIED` would claim we read
the county's site; we did not.

## Coverage movement

| Measure | Before (Phase 35) | After (Phase 38) |
|---|---|---|
| FL counties with Property Appraiser identified | 12 | **67** |
| FL counties with Tax Collector identified | 0 | **67** |
| FL counties with Clerk/VAB identified | 0 | **64** |
| TX counties with Appraisal District identified | 42 | **246** |
| TX counties with Tax Assessor-Collector identified | 0 | **250** |
| TX counties with no source in any category | 212 | **0** |

The prior baseline is preserved under `_history` in
`data/county_coverage_matrix_summary.json` rather than overwritten.

## Counties where the directory itself lists no website

Not an error and not a scraping failure — the state's directory has no URL for
these offices. Recorded as `SOURCE_NOT_FOUND`, never as a technical failure.

- **TX appraisal district (8):** Crockett, Dickens, Kaufman, Kleberg, Motley,
  Palo Pinto, Sabine, Young
- **TX tax assessor-collector (4):** Briscoe, Caldwell, Haskell, Hunt
- **FL Clerk/VAB (3):** Hamilton, Lafayette, Levy

## What this phase did NOT do

- No county appraisal district, property appraiser, tax collector or clerk site
  was fetched, sampled or technically verified.
- No terms of use, license or robots policy of any county site was read.
- No statewide bulk dataset (FL DOR NAL/SDF/GIS, TNRIS/StratMap parcels) was
  acquired or evaluated beyond what earlier phases recorded.
- No auction or foreclosure source was added for any county.
- No source was promoted, enabled, or moved out of `LEGAL_REVIEW_REQUIRED`.
- `harvest_lgbs()`, the acquisition engine, the governance stack, production
  schema and production data are untouched.
