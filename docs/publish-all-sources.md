# Publish every collected source (owner decision, 2026-10-26)

## The decision

The owner wrote on 2026-10-26:

> "Do not block vendors. Post their shit and we'll figure out the legal shit afterwards... You need to find every
> fucking property and every source, and then we'll work on the legal shit."

Before this change, many collected sources were withheld from customers. Their publication decision was `UNREVIEWED`:
the source publishes no reuse licence and no owner decision had been recorded. This change records the owner's decision
for every source that is implemented and live-verified, using the repository's own mechanisms. It is an **internal risk
acceptance, not the source's permission**, and every record says so. The legal review is still pending.

## Sources published by this decision

| State | Source | Ledger | Before | Active rows in production (2026-10-26, read-only) |
|---|---|---|---|---|
| MI | `mi_detroit_landbank_lots` | Available | collected, UNREVIEWED | 30,537 |
| MI | `mi_detroit_landbank_programs` | Available | collected, UNREVIEWED | 12 |
| MI | `mi_oceana_landbank` | Available | collected, UNREVIEWED | 5 |
| MO | `mo_stl_lra_inventory` | Available | collected, UNREVIEWED | 9,778 |
| OK | `ok_oklahoma_county_owned` | Available | collected, UNREVIEWED | 195 |
| PA | `pa_fayette_repository` | Available | collected, UNREVIEWED | 247 |
| MN | `mn_ramsey_tax_forfeit` | Available | collected, UNREVIEWED | 2 |
| SC | `sc_horry_forfeited_land` | Available | collected, UNREVIEWED | 51 |
| SC | `sc_georgetown_forfeited_land` | Available | collected, UNREVIEWED | 1 |
| TN | `tn_shelby_landbank` | Available | collected, UNREVIEWED | 1,784 |
| CO | `co_morgan_treasurer_deed_auctions` | Auctions | **never requested** (auction source awaiting review) | 0 - first read on the next `expansion` run |
| WI | `wi_dane_tax_deed_auction` | Auctions | **never requested** | 0 - first read on the next `expansion` run |
| SC | `sc_oconee_tax_sale_list` | Auctions | **never requested** | 0 - first read on the next `expansion` run |

That is 42,612 Available rows, plus whatever the three auction lists hold when they are first read.

## Where the decision is recorded

- **Registry:** `harvesters/otc/adapters/expansion.py` holds `OWNER_APPROVED_2026_10_26_SOURCE_IDS` and
  `PUBLICATION[...] = ("APPROVED", OWNER_APPROVED_2026_10_26)`. `data/county_source_registry.csv` is regenerated from
  it.
  - `publication_status` is `APPROVED`, which `publication_problems()` accepts: every source is PRODUCTION_VERIFIED
    with governance APPROVED.
  - `restrictions` starts with "Owner approved customer publication 2026-10-26; legal review pending".
  - `APPROVED_GRANDFATHERED` was not used, because it means "served to customers before the gate existed", which is
    not true of these sources.
- **Permissions:** `data/source_permissions.csv` adds `display` and `link` records for all 13 sources:
  - status `OWNER_PERMISSION_REQUIRED` + `INTERNAL_RISK_ACCEPTANCE`, i.e. an INTERIM allowance, never documented;
  - effective 2026-10-26, expiring 2027-04-12 (inside `INTERIM_MAX_DAYS`);
  - for Dane, Morgan deed auctions and Oconee, the `fetch` / `parse` / `store` records also became INTERIM (they were
    `NO_EVIDENCE` / `RESTRICTED TERMS_SILENT`), so these sources are collected now.

  `redistribute` (export / API) is NOT granted.
- **Review files:**
  - `data/available_publication_reviews.csv`: Georgetown becomes `APPROVED`. Its flags stay as read on 2026-10-02
    (`commercial_use_permitted=not_stated`).
  - `data/enrichment_source_catalog.csv`: `wi_dane_tax_deed_auction` and `sc_georgetown_forfeited_land` become
    `APPROVED`. These catalog rows have graduated to registry sources.
  - `harvesters/sources/available_coverage.problems()` accepts an APPROVED review without a published grant only when
    the review cites the owner decision AND an in-date INTERIM `display` record exists. Every other route still needs
    a grant or written permission.
- **Paid beta is unchanged** (5 sources): `data/paid_beta_sources.csv` only had its reason text updated.

## Production

The pipeline applies this decision by itself after merge:
- `sync_state_inventory.py` writes `publication_status` on every row;
- `publication_gate.py` runs per state in the `laft` / `expansion` jobs.

The production writes made to apply it now (listed in the PR) are:
1. One `public.source_publication_reviews` row per source (the admin-review mechanism `publication_gate.py` /
   `source_publication.py` apply, validated by `publication_problems()`). Without them, the next sync from `main`
   would relabel the rows UNREVIEWED before this PR merges.
2. `properties.publication_status` set from `UNREVIEWED` to `APPROVED` on the rows of the 10 Available sources. This is
   the same change `publication_gate.py` PATCHes; it bumps `updated_at`, as every daily sync upsert already does.

## What still withholds rows

- **Detroit customer subset (unchanged; an owner commercial rule independent of review status).** Customers see only
  "Marketed Structure For Sale" lots, and of those the deterministic ~50%: about 57 of 115 structures. The other
  30,422 vacant lots and the 12 programs rows stay admin-only.
- **`config.js availableGate: "off"` (unchanged, owner decision pending).** `"enforce"` would withhold from
  non-admins every Available row without a verified acquisition path. Under that rule, the 2026-10-10 dry run kept
  only 185 of 54,105 rows. The newly published sources are mostly NEEDS_REVIEW / NOT_FOUND for acquisition evidence,
  so they would also be withheld.
- **Migration 031 is not applied.** If it is, the server-side `publication_state` gate (path and freshness rules) will
  withhold rows without a credible acquisition path.
- **Not collected (no data exists):**
  - AL / AR / AZ adapters: the states are not activated, and the evidence is search-index only.
  - FL / TX registry candidate rows: no harvester.
  - `tx_hctax`: RESTRICTED, legal review, search evidence only.
  - The 29 REVIEW_REQUIRED catalog candidates: discovery pages, no adapter.
  - Spartanburg FLC: a redemption-period bid assignment, not Available inventory.
- **Hard blocks:**
  - `tx_ctsa` stays blocked.
  - `tx_pbfcm` / `tx_mvba` / `tx_govease` are handled on `claude/tx-vendors`; this change does not touch them.
- **Technical blocks:** LienHub (FL certificates) returns HTTP 403 to the runner. Rows exist, but they are not
  refreshed.
- **Enrichment-only overrides:** `REVIEW_OVERRIDES` in `harvesters/sources/model.py` keeps `tx_lgbs` / `tx_realauction`
  as REVIEW_REQUIRED for writing enrichment fields. Their rows are already customer-visible.
