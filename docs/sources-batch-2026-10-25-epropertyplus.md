# ePropertyPlus land banks, batch 2 (2026-10-25)

Two more land banks were checked on the ePropertyPlus platform, the one the Shelby County (TN) Land Bank uses
(`harvesters/otc/adapters/epropertyplus.py`). One source is added. It is **gated and UNREVIEWED**, and nothing
is enabled in production. No migration, no workflow, no front end.

## What was read

These were live reads from the development sandbox on 2026-10-25. Only counts and field names were taken. No
evidence-job run has read either portal.

| Portal | Linked from the land bank's own site? | Published rows | County field | Status field | Amount fields |
|---|---|---|---|---|---|
| `public-cclba.epropertyplus.com` (Cook County Land Bank Authority, IL) | **Yes.** On cookcountylandbank.org's pre-qualification application page, the "APPLY" button opens the portal's `propertySearch` (read with the fetch tool). | 923 | `county`: Cook 923 | `currentStatus`: Acquired 914, Rehab In Progress 8, Target - Dlqt Taxes 1. **No `available` flag.** | `minimumBid` filled 918, `askingPrice` filled 108 |
| `public-kclb.epropertyplus.com` (Land Bank of Kansas City, MO) | **Not confirmed.** The hostname was guessed. kcmolandbank.org now redirects to an unrelated "Sarawak Portal" login page, and kcmo.gov's Land Bank page answered HTTP 403. | 2,577 | `county`: Jackson in mixed spellings, plus 1 Clay | none published | `askingPrice` filled 2,576 |

Cook's parcel numbers have one shape, `99-99-999-999-9999`, and all 923 are distinct. Coordinates are on 922
rows. A legal description is on 583.

## Cook County (IL): added as a gated, UNREVIEWED source

- **State.** `harvesters/governance/states.py` registers Illinois as a NON-production state. It is representable
  but never runnable, and it has no state page or front end.
  - Missing activation requirements: inventory semantics, purchase path, amount semantics, governance approval,
    production registry authorization.
- **Configuration.** The configuration is `expansion.IL_COOK_LANDBANK`, with `SOURCES["IL"]`.
  - **Rows read:** every published Cook row, read on list presence. The row's own `currentStatus` is kept
    verbatim in `inventory_status_raw`. The portal publishes no availability flag, so Shelby's rule cannot
    apply.
  - **Rows excluded:** a `Target - Dlqt Taxes` row is a parcel the land bank pursues, not one it holds, and is
    never read. A row whose `county` is not Cook is counted as `excluded_county` and never relabelled.
  - **Amount:** `minimumBid` is kept as the published minimum bid (`OPENING_BID`; terms basis `MINIMUM_BID`).
    `askingPrice` is never mapped.
  - **Never mapped:** `comments`, broker fields, court/case custom fields and thumbnails.
  - **Purchase link:** the pre-qualification page is the application path. No per-parcel purchase link is
    constructed.
- **Adapter changes, per portal.** The fields a page must carry are now derived from the configuration
  (`required_fields()`). For Shelby that is still `parcelNumber, currentStatus, available`, as before. The
  configuration also gained:
  - `offered=()`: every published row is read;
  - `excluded`: (field, value) pairs that are never read;
  - `county_field` / `county_values`;
  - `legalDescription` mapped to `legal_desc`, for every tenant.
- **Gates.** `harvest_expansion.gate("IL")` refuses the state before any request. `runnable_sources()` also
  gates every source of a non-activated state (`STATE_NOT_ACTIVATED`), whatever its publication decision. A
  test proves `main(["--state", "IL"])` exits 2 without importing `requests`.
- **Registry.** There is one candidate row: `MANUAL_REVIEW_REQUIRED`, `TERMS_NOT_VERIFIED`, `UNREVIEWED`, no
  harvester, not runnable. It comes from `_candidate_expansion_row()` in
  `scripts/build_county_source_registry.py`, so the registry has 238 rows.
- **Permissions.** `data/source_permissions.csv` has fetch / parse / store records only:
  - `OWNER_PERMISSION_REQUIRED` on `INTERNAL_RISK_ACCEPTANCE`, condition `excluded_from_paid_tier`;
  - effective 2026-10-25, expiring 2027-04-12.

  Display, redistribution and enrichment are denied.
- **Financial terms.** The terms row is basis `MINIMUM_BID` and quotes the portal field.
- **Publication review.** There is no row in `data/available_publication_reviews.csv`. That file accepts only
  APPROVED / REVIEW_REQUIRED / HARD_BLOCKED reviews that cite a numeric evidence run, and there is none. The
  UNREVIEWED decision lives in `expansion.PUBLICATION` and the registry, as Shelby's does.
- **Generated files.** These were rebuilt: `source-inventory`, `available-coverage`, `available-terms`,
  `acquisition-evidence` (IL / Cook is a NOT_FOUND unit), `commercial-scope`, `county-intelligence`,
  `state-rules`, the gap queue and the interim permissions. Root mirrors were copied.
- **Tests.** `tests/python/test_epropertyplus_batch2.py` runs against the synthetic fixture
  `tests/python/fixtures/illinois/il_cook_landbank.json`.

## Kansas City (MO): candidate only

The Land Bank of Kansas City's official linkage to `public-kclb` could not be verified, so no adapter
configuration was added. It is recorded in `data/available_source_candidates.csv` as `mo_kc_landbank_portal`
(Jackson County). The portal answers publicly, but it also carries a Housing Authority (`KCMHA`) inventory type
and an "ePP TEST" row. Its rows would need an offered rule before any configuration.

## Not verified

- **CCLBA Policies & Procedures** (not read):
  - what `minimumBid` binds, and how it differs from `askingPrice`;
  - whether "Acquired" / "Rehab In Progress" rows are offered for sale.
- **Reuse terms** for either portal: none recorded.
- **Runner read:** no evidence-job run has read either portal.
- **Kansas City:** the official portal linkage.
