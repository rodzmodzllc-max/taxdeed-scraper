# Source rights enforcement and data provenance (2026-10-16)

This is the follow-up to the 84-row source disposition register
(`data/audit/source_register_2026-10-12.csv`). It reconciles the register
with the code and adds per-use enforcement on top of the permission engine.
It also adds a customer-safe provenance contract, and lists every unsafe path
found, each with a disposition. **The register is an audit baseline, not an
authorization.** Nothing here grants a permission, activates a source or
changes production.

Generated table: [`docs/audit/source-rights-reconciliation.md`](audit/source-rights-reconciliation.md)
(machine-readable: `data/audit/source_rights_reconciliation.json`). Both are
built by `scripts/build_source_rights_report.py`, and the `--check` mode is
pinned by a test.

## 1. Reconciliation: register rows to code source IDs

`data/audit/register_code_map.csv` maps each register row, in order, to the
code source IDs (the IDs in `data/source_permissions.csv` and
`data/county_source_registry.csv`). Each mapping records the row's datasets,
its county scope and a match type.

| Match type | Rows | Meaning |
|---|---|---|
| EXACT | 47 | Register ID is the code ID |
| RENAMED | 4 | Same source under another ID: `fl_dor_statewide_nal` → `fl_dor_statewide`, `fl_statewide_cadastral_fgio` → `fl_fdor_cadastral`, `usda_naip_via_usgs` → `usda_naip`, `google_street_view_static` → `google_street_view` |
| SPLIT_OF | 5 | A county or dataset slice of one code source: three `fl_realauction` rows (Alachua/Volusia, the other 44, closed results) and two `fl_laft_html` rows (direct vs Escambia/Columbia/Union) |
| AGGREGATE_OF | 4 | One register row covers several code IDs: `la_ebr_tax_parcels` + `la_ebr_tax_roll`, the two Douglas CO datasets, the two Detroit Land Bank layers, and `tx_jim_wells_cad_parcels` (the BIS CADs have no code source) |
| OPERATION_OF | 1 | `scraperapi_proxy` is the `fetch_via_proxy` operation of `fl_laft_html` |
| NO_CODE_SOURCE | 19 | Links-only, catalog-only or do-not-add rows: nothing reads them |
| NO_PERMISSION_RECORD | 1 | `sc_spartanburg_forfeited_land`: the `sc_flc` adapter could parse it, but no registry row or permission record exists, and nothing runs it |
| CLIENT_SIDE | 3 | Google Maps JS/static, MapTiler and the OpenStreetMap embed are loaded by the browser, outside the permission engine |

Every code source ID that has permission records maps to a register row; the
test fails on any unmapped code source.

**Discrepancies.** These are operations the code allows beyond the register's
decision. The table evaluates each county of a row's scope separately: a
permission for one county or dataset is never read as covering another.

| Register row | Code allows beyond the decision | Disposition |
|---|---|---|
| `fl_lienhub_certificates` (register: keep disabled pending permission) | fetch, parse, store, display - interim, 32 counties | **Owner decision** (section 3) |
| `ut_ugrc_lir_saltlake` (register: not needed now) | fetch, enrich - documented (CC BY 4.0) | Keep. The state is not activated, so the state gate stops it before any request. Recorded as a reminder. |
| Google Maps / MapTiler / OSM (client-side) | no permission record | **Owner decision** (section 3) |
| `sc_spartanburg_forfeited_land` | no record; not wired | Keep unwired. A record (deny by default) must exist before any code reads it. |

## 2. Central policy per use (`harvesters/governance/source_rights.py`)

`rights_profile(source_id, state=, county=, dataset=)` answers each use from
`permissions.authorize()` and fails closed:

| Use | Operations (all must be allowed) | Extra rule |
|---|---|---|
| ingest | fetch + parse | |
| persist | store | |
| refresh | fetch + parse + store | A fetch permission never implies a refresh |
| customer display | display | |
| commercial use | display | **DOCUMENTED basis only.** An interim allowance (grandfathered practice, internal risk acceptance) is never commercial permission |
| export / redistribution | redistribute | DOCUMENTED only. Today no source allows it (tested) |
| enrich | enrich | |
| link | link | `LINK_ONLY` allows this and nothing else |
| geometry | none | **Always denied.** No module on `main` grants parcel polygons; a centroid point reaches a record only through `enrich` on the `parcel_centroid` dataset |
| imagery | imagery registry `terms_status` | APPROVED = documented; PROVIDER_DISPLAY = link-only display; anything else is denied |
| attribution | the allowing record's `attribution` | Shown only while display is allowed |

Enforced in the engine (`permissions.py`) and tested:

- **Every condition must hold.** APPROVED_WITH_CONDITIONS needs at least one
  machine-checked condition. One unmet, unknown or erroring condition denies
  the operation.
- **County and data-product scope.** A county record never covers another
  county or the state. A record for one dataset never covers another dataset,
  or a caller that names none. One operation never covers another.
- **Fail closed** on an expired, not-yet-effective, BLOCKED, RESTRICTED or
  unevidenced record, on conflicting records, and on an invalid file (every
  operation denied).
- **Hard blocks.** `tx_pbfcm`, `tx_mvba`, `tx_govease` and `tx_ctsa` are
  denied every operation, including `link`.
- **New (2026-10-16): circumvention needs documented permission.**
  `CIRCUMVENTION_OPERATIONS = {"fetch_via_proxy"}`: an interim allowance can
  never allow routing around a control the source applied (reason code
  `CIRCUMVENTION_NEEDS_DOCUMENTED`). See section 3.

## 3. Unsafe paths and dispositions

Nothing below was probed live. No blocked host was contacted while
investigating; every finding comes from code, the permission records, the
register and the repository's own earlier audits.

| # | Path | Finding | Disposition |
|---|---|---|---|
| U1 | **ScraperAPI proxy** (`scripts/harvest_laft_html.py`, `fetch_via_proxy`) | When a clerk returns HTTP 403, the harvester retried through a commercial proxy. The permission covering this was a grandfathered interim record, checked statewide rather than per county, so any HTML-list county could be proxied. This routes around an access control. | **Gated in this PR.** The circumvention rule denies it. After merge, a 403 county reads FAILED / `PERMISSION_DENIED`: no request through the proxy, nothing closed, and stored rows are kept (a FAILED read closes nothing). Escambia, Columbia and Union then age to STALE until counsel decides. **Merging this is the owner's decision**; the commit is separate so it can be dropped. |
| U2 | **LienHub** (`harvest_lienhub_certificates.ps1`, certificates job, 12:00 UTC daily) | Every read has returned 403 since 2026-10-01 (32 counties). The script does not route around it. The records still allow fetch/parse/store/display (interim), against the register's "keep disabled pending permission". | **Owner decision.** Changing the records now would make the scheduled job exit 3 daily, which is a production change. Recommended: unschedule the job and deny fetch/parse/store until Grant Street replies. Keeping or withholding the existing certificate rows' display is a separate call. |
| U3 | **RealAuction / RealTDM** (FL 46 counties, TX 24 manual, RealTDM LAFT 12) | Interim grandfathered practice only. No terms were ever found. The repository's own audits recorded robots.txt disallow signals on FL and TX hosts (`registry.py` Phase 10B / 33.5). The harvester never reads robots.txt, sends a desktop User-Agent and uses `bypassPage=1`. The register also notes disallow signals for Miami-Dade and Brevard. | **Owner decision** (counsel / RealAuction reply). Production data is being collected without a documented rights basis; this pass did not change it. Commercial use is now denied for these sources (interim basis). |
| U4 | **Volusia LAFT** (`fl_laft_pdfs`, Volusia record) | The record's own reason names a "disclaimer bypass": a direct PDF fetch past the clerk's disclaimer page. | **Owner decision.** It is the same class of control bypass as U1 and runs on the scheduled laft job. Recommended: gate after counsel review. |
| U5 | **FL DOR / NAL and FDOR cadastral** | `fl_dor_statewide` denies every operation, and nothing runs it. `fl_fdor_cadastral` is grandfathered for fetch and enrich of attributes and the centroid; redistribute is denied, and no polygon is stored. However, `harvesters/sources/inventory.py` labels the FDOR / Census / FEMA built-ins `governance="APPROVED"`; the register asks for that to read UNVERIFIED (proposal P-3). | Keep centroid-only. **Owner decision** on P-3: that label gates `enrich_available.py`, so changing it changes manual enrichment runs. The public permission wording was corrected in this PR (U10). |
| U6 | **GovEase / PBFCM / MVBA / CTSA** | Hard-blocked in code and in the records. | **Gated** (already; tested). |
| U7 | **LGBS** (`tx_lgbs`) | Manual dispatch only (`job=texas`, never scheduled). Interim allowance only; the redistribution clause is unresolved (pre-sale blocker 3). | **Keep as is** (manual-only). Owner and counsel decision before any schedule. Commercial use and export are denied. |
| U8 | **Pinellas / Broward / Duval / Miami-Dade property appraisers** | No code source; links only. RealAuction rows carry the appraiser deep link the vendor publishes. | **Keep as a source link.** Nothing is copied. |
| U9 | **Shelby ePropertyPlus and the other eight admin-only sources** (Detroit lots and programs, Oceana, Ramsey, St. Louis LRA, Oklahoma County, Fayette, Georgetown, Horry) | Display is denied in the records and by the register. But `config.js` ships `publicationMode: "preview"`, and while migration 027 is unapplied every approved account is a tester. **So every approved account sees these rows in the app** (labelled "Source review: Unreviewed"). The database also returns them to any approved account, because migration 031 is unapplied. | **Owner decision** (production configuration and migration). Options: set `publicationMode: "enforced"`, or apply 027 so customers never get the preview, plus 031 and the writer for the server side. Not changed here. |
| U10 | **Public files** (`public/*.json` is served without sign-in) | `public/source-inventory.json` named the permission file, internal evidence types (`GRANDFATHERED_PRACTICE`) and status codes for four built-in sources. | **Fixed in this PR.** The wording is now "Permission on file: fetch interim, not documented permission", with no file, code or date. `public_disclosure_problems()` scans every public JSON / JS / HTML file and `config.js` in CI. |
| U11 | **Public repository** | The repository is public (since 2026-08-31). `data/source_permissions.csv` (reviewers, reasons, internal risk acceptances), `data/audit/source_register_2026-10-12.csv` (provider business contacts, outreach status) and `docs/legal/*` are world-readable. They are not customer-facing in the app, but they are public. | **Owner decision** (repository visibility, or moving legal records out). The new reconciliation outputs deliberately leave out contacts and outreach. |
| U12 | **County GIS orthoimagery** | Imagery registry REVIEW_REQUIRED; never requested. | **Keep disabled** (tested). |
| U13 | **Client-side map providers** | Google Maps runs on a Demo Key (testing only, not domain-restricted); MapTiler is origin-restricted on the free plan; OSM tiles are embedded. None has a permission record, and the browser loads them outside the engine. Static satellite images send a record's coordinates to the provider. | **Owner decision.** Replace the Demo Key before paid launch (register / pre-sale blocker); recording the providers' terms is part of the same decision. |
| U14 | **Internal risk acceptances** (56 records, `OWNER_PERMISSION_REQUIRED` + `INTERNAL_RISK_ACCEPTANCE`) | Interim, expiring 2027-04-12, never documented. | Keep (owner decision on file). They now **never** count as commercial permission. `scripts/source_permission_check.py --due 60` lists what is due. |
| U15 | **Enriched values shown under the list source's display permission** | A value attached by another source (FDOR, a statewide parcel layer, the Census geocoder) was displayed because the *record's* source may be displayed. | **Contract added.** `field_provenance_view()` shows such a value only while the attaching source's own `enrich` permission holds for that record's state and county, and carries that source's attribution. Wiring it into the frontend or RPC is a follow-up (section 4). |

## 4. The customer contract

`customer_source_notice(source_id, state=, county=, dataset=)` returns only
these keys: `source_id`, `shown`, `basis`, `attribution`, `conditions`.

- `basis` is one of the fixed `CUSTOMER_BASIS_LABELS`.
- Conditions are fixed customer phrases ("Attribution required", "Dated list
  - not a statement of current availability", ...).
- A test proves that no reviewer, reason, evidence reference, evidence type or
  status string from the records can appear in a notice.

`field_provenance_view(row, field, now=)` is the per-field contract for any
API or customer surface. It returns:

- `value`: None whenever the source may not be displayed, the value is not
  published or the field is not tracked. **Never zero for unknown**: the
  legacy `bid = 0` with no amount kind is NOT_PUBLISHED.
- `value_status`: one of CONFIRMED_SOURCE, ESTIMATED_BY_SOURCE,
  DERIVED_BY_TAXACQ (e.g. a Census address geocode or a polygon centroid),
  UNVERIFIED, NOT_PUBLISHED or NOT_TRACKED.
- `source_id`, `provenance_source`, `source_url`, and `origin`
  (SOURCE_REPORTED / DERIVED_BY_TAXACQ).
- `retrieved_at` (the provenance entry's own `recorded_at`), `effective_at`
  (`list_as_of` / `source_published_at`) and `last_verified_at`
  (`last_seen_at`). Each is **only what the row carries; never filled from
  the clock.**
- `freshness`: CURRENT, STALE (past the ledger window: 7 days auctions and
  liens, 14 days Available), UNVERIFIED (never read successfully), WITHDRAWN
  (closed or delisted, or display no longer allowed) or NOT_TRACKED.
- `attribution` and customer-safe `conditions`.

**Never inferred.** Sold, redeemed, winner, winning bid, price paid, owner,
title, boundary accuracy and returns are NOT_TRACKED on the record. They
appear only as a source-published result through the outcome and
inventory-status writers, which have their own tests.

**A failed retrieval never refreshes verification.** This is covered by
existing tests and one new one:

- `stamp_seen` stamps only COMPLETE / EMPTY counties
  (`test_source_rights.py`, `test_data_quality_fixes.py`);
- the LAFT lifecycle closes and stamps nothing on FAILED, INCOMPLETE,
  SOURCE_UNAVAILABLE, STALE or missing status
  (`test_laft_lifecycle_ledger_health.py`);
- `sync_state_inventory.plan` skips rows of an unread unit
  (`skipped_unit_not_read`, `test_current_state_sprint.py`,
  `test_six_state_expansion.py`).

**Not done here (follow-ups):** projecting `field_provenance_view()` through
`get_properties()` or the frontend needs an RPC (a migration) or a
frontend mirror plus shared vectors. Both are production changes left for
approval.

## 5. Statement: no writes, no dispatches

During this task, nothing was written to production data or configuration:

- no workflow was dispatched and no harvest was run;
- no migration was applied;
- no source was activated and no county was added;
- no permission was granted or broadened.

The only network traffic was to the GitHub repository (git fetch / push and
the pull request). The PR is not merged. Two changes take effect only if the
owner merges:

- **U1:** the proxy fallback stops.
- **U10:** the public inventory wording changes.

## Files

- `harvesters/governance/source_rights.py`: uses, reconciliation, notice,
  provenance contract, disclosure scan.
- `harvesters/governance/permissions.py`: `CIRCUMVENTION_OPERATIONS`.
- `harvesters/sources/inventory.py`: public-safe `permission_basis()`.
- `data/audit/register_code_map.csv`: the mapping.
- `scripts/build_source_rights_report.py`: writes
  `docs/audit/source-rights-reconciliation.md` and
  `data/audit/source_rights_reconciliation.json`.
- `tests/python/test_source_rights.py`: 55 tests. Also updated:
  `test_laft_harvester_gates.py` and `test_permission_gaps.py`.
