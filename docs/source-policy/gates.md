# Suppression gates by review, permission or publication status: inventory

Read-only audit of `/home/user/taxdeed-scraper`, branch `claude/fl-outlines-all-ledgers` at `833ff5b`, 2026-10-22.
All paths are relative to the repo root. Every claim cites a file and line.

## 0. Facts that change the premise

1. **On `main`, the tester preview is ON.** Root `config.js:48` is `publicationMode: "preview"`, and `git show origin/main:config.js` matches.
   - Its comment (`config.js:41-47`) says every approved account, not only admins, sees rows from UNREVIEWED sources, each labelled "Source review". It also says to set the mode back to `"enforced"` before selling.
   - `viewerScope()` (`public/app.js:684-688`) returns `"preview"` for every non-admin who is not a role-`customer`. Before migration 027, nobody is a `customer`: the role comes from the profile (`app.js:676-678`).
   - Result: with today's repo config, approved non-admin accounts **do** see the 10 UNREVIEWED sources, labelled.
   - The exceptions are Detroit rows outside the Detroit subset (gate F6) and BLOCKED rows.
   - "Customers do not see them today" holds only in `enforced` mode (`tests/config.js` has no `publicationMode`, so it defaults to enforced at `app.js:663`), or for a role-`customer` (paid scope, dormant).
   - I could not check the deployed bundle. Cloudflare serves `main`, whose config is `preview`.
2. **None of the 10 UNREVIEWED sources has a `display` or `link` permission record.**
   - `data/source_permissions.csv` gives each of them only `fetch` and `store`. Some also have `parse` or `discover`, and those are not listed below.
   - Status is `OWNER_PERMISSION_REQUIRED`, evidence `INTERNAL_RISK_ACCEPTANCE`, expiring 2027-04-12.
   - So `permissions.listing_display()` denies them with `NO_RECORD`. This is pinned by `tests/python/test_source_permissions.py:275-280`.
   - Only six `link` records exist, and all are TX: `tx_comptroller_directory` and `tx_hctax` are LINK_ONLY; `tx_ctsa`, `tx_govease`, `tx_mvba` and `tx_pbfcm` are BLOCKED.
3. **The frontend and backend disagree on what "publishable" means.**
   - **Frontend:** reads only `properties.publication_status` (`app.js:702-705`), and NULL counts as publishable.
   - **Backend `publishable()`:** needs APPROVED* **and** a `display` permission (`scripts/source_publication.py:76-85`).
   - **Server rule in migration 031:** also needs a display permission, verified state rules, a path and freshness (`harvesters/governance/publication_state.py:348-405`).
   - **The sync:** writes `publication_status = effective_publication(reg)` and never consults the permission (`scripts/sync_state_inventory.py:266`).
   - **Consequence:** an admin approving a source in the panel makes its rows customer-visible in the browser even with no `display` record. Migration 031 would then hide them again.
4. **The FL PowerShell syncs never write `publication_status`.**
   - No `.ps1` file contains `publication_status` (grep).
   - `scripts/publication_gate.py:117-146` propagates the column only to `source=laft` rows.
   - Hence the NULL values on `fl_realauction`, `fl_lienhub_certificates`, `tx_lgbs` auctions and `tx_realauction`.
   - Whether NULL counts as visible depends on the gate:

     | Treats NULL as visible | Treats NULL as not visible |
     |---|---|
     | `app.js:704`, `harvesters/enrichment/priority.py:79-81` | JS acquisition gate (`app.js:601`, Available only) |
     | | Python `harvesters/sources/acquisition_gate.py:211` |
     | | Migration 027's policy (`027:303`, `publication_status = 'APPROVED'`) |
     | | Imagery priority filter (`harvesters/imagery/__init__.py:248`, `in.(...)`) |

## 1. Gate table

Abbreviations:
- **Applies to:** C = customer in `enforced` mode, T = tester in `preview` mode, P = paid `customer` role (needs 027), A = admin, Pipe = pipeline.
- **Kind:** **REVIEW** = only about source review or publication status (candidate to relax). **KEEP** = hard block, permission, acquisition-path quality, freshness or rules (keep). **MIXED** = both in one gate.
- **UNREV10** = the 10 UNREVIEWED sources in the brief.

### Frontend: `public/app.js` (one filter feeds everything)

| # | Location | Exact condition | What it suppresses | Applies to | Current sources affected | Live? | Kind | Smallest change |
|---|---|---|---|---|---|---|---|---|
| F1 | `app.js:872-885` `isPublishable(p)` | (1) `publication_status === "BLOCKED"` → false (873)<br>(2) `IS_ADMIN` → true (874)<br>(3) `PUBLICATION.enforced && publication_state !== "CUSTOMER_PUBLISHED"` → false (878)<br>(4) `!inCustomerInventory(p)` → false (879)<br>(5) paid: `isPaidBetaPublishable(p) && acqGateAllows(p)` (883)<br>(6) otherwise `(isCustomerPublishable(p) \|\| viewerScope()==="preview") && acqGateAllows(p)` (884) | Whole record, through `applyLedgerRows` (F3) | (1): everyone. (3)-(6): all non-admins | (1): none in production (BLOCKED sources hold no rows). (6): UNREV10 when enforced. (4): Detroit | (1) live; (3) dormant (031); (4) live; (5) dormant (027); (6) live but neutralised by `preview` | (1) KEEP; (6) REVIEW; (3)/(5) MIXED | Leave (1). In (6), replace `isCustomerPublishable(p) \|\| preview` with a new `isPublicRecordDisplayable(p)`: status not BLOCKED and not RESTRICTED, an https official link on file (`list_url` / `url_auction` / `document_url`), and `last_seen_at` present. Keep the label chips. |
| F2 | `app.js:702-705` `isCustomerPublishable(p)` | `!s \|\| s === "APPROVED" \|\| s === "APPROVED_GRANDFATHERED"` | Called by F1, F3, the labels (F11), the dossier (F10) and the acquisition-gate count | C | UNREV10 | Live (enforced only) | REVIEW | Keep it as the "reviewed for reuse" fact used for labels. Stop using it as the visibility test; F1 uses the new predicate instead. |
| F3 | `app.js:4250-4301` `applyLedgerRows()` | `ALL = rows.filter(...)`. Non-admin outside the Detroit subset → dropped and not counted (4284). `isPublishable` → kept (4285). Acquisition gate → `GATE_WITHHELD` (4291-4296). Otherwise `WITHHELD[source]++` (4298) | Whole record from **every** surface, because all of them read `ALL`:<br>• list<br>• counts<br>• map: `computeMapRows` `13260-13274` → `explore.js` / `satellite-map.js` (neither filters on publication; grep finds no `publication_status`)<br>• search (`textMatches` over `ALL`)<br>• CSV export `11425-11427` (`ALL.filter(inLedger).filter(passes)`)<br>• dashboard (13486)<br>• dossier rows (6084)<br>• cross-ledger relation (9092)<br>• Home | as F1 | as F1 | Live | REVIEW (through F1) | No change needed beyond F1. The counter at 4298 then counts only BLOCKED / RESTRICTED. |
| F4 | `app.js:663` `PUBLICATION_MODE`; `config.js:48` | `publicationMode === "preview"` ? `"preview"` : `"enforced"` | Turns the F1(6) review gate on or off per deployment | T vs C | UNREV10 | `config.js` = preview; `tests/config.js` = enforced | REVIEW switch | Becomes moot once F1 uses the new predicate. Otherwise leave `preview` on. |
| F5 | `app.js:684-693` `viewerScope()`, `isPaidBetaPublishable` | Paid: `publication_status === "APPROVED" && PAID_BETA_SOURCES.has(source_id) && inCustomerInventory(p)`. Set from `public/commercial-scope.json` `paid_beta_source_ids` (`app.js:4392`) | Whole record for a paid customer | P | Everything except `la_ebr_adjudicated`, `mi_eaton_treasurer_sale`, `mi_lenawee_tax_sale`, `sc_york_tax_sale`, `wi_green_tax_deed_sales` (incl. FL, TX, WY, CO and UNREV10) | Dormant (027 not applied; `config.js:73` `billing.enabled: false`) | MIXED (commercial scope, not a fact gate) | Commercial decision. To show public facts to paid users too, use the F1 predicate for paid users as well and keep the paid-beta set only for value-added fields. |
| F6 | `app.js:842-867` `detroitSubsetStatus` / `inCustomerInventory` | Detroit sources only. In the subset only when `source_id === "mi_detroit_landbank_lots"`, `inventory_status_raw === "Marketed Structure For Sale"` and `fnv1a32("<sid>\|<parcel>") % 100 < 50` | Whole record (not counted as withheld; 4284). Every `mi_detroit_landbank_programs` row is `not_structure` | C, T, P (not A) | `mi_detroit_landbank_lots` (30,590, of which only ~50% of the structure rows survive); `mi_detroit_landbank_programs` (all 12 hidden) | Live, **including preview** | Neither review nor quality: an owner visibility cap | Separate owner decision. To show everything: `inCustomerInventory = () => true`. Mirror in `harvesters/otc/detroit_subset.py` and `public/admin.js` (`440`). |
| F7 | `app.js:596-642` acquisition gate `acquisitionVerificationWith` / `acqGateAllows` | `SOURCE_NOT_PUBLISHED` when `publication_status` ∉ {APPROVED, APPROVED_GRANDFATHERED}; NULL counts as not published (601). Other reasons: observation ≤14 d, list ≤365 d, verified evidence ≤180 d, a channel, https evidence, path match (602-628) | Whole Available record, non-admins, only when `availableGate === "enforce"` | C, T, P | Would hit all laft rows that fail; dry run: LA 10,334→0, FL 153→41, TX 421→144 (CLAUDE.md, PR #137) | Dormant (`config.js:61` `"off"`; `tests/config.js` unset → off) | MIXED: line 601 is REVIEW, the rest KEEP | Drop the 601 check, or replace it with "not BLOCKED / RESTRICTED". Same in `harvesters/sources/acquisition_gate.py:211` and `tests/python/fixtures/acquisition_gate_cases.json` (2 `SOURCE_NOT_PUBLISHED` cases). |
| F8 | `app.js:769-781, 878, 4269-4279` `PUBLICATION` / `applyPublicationReads` | `enforced` only if `count_publication_states` answers (031). Rows not in the withheld map get `CUSTOMER_PUBLISHED` | Defence in depth for 031 | non-admin | none today | Dormant (031 not applied) | MIXED (follows `publication_state.py`) | Nothing in JS. Change the server rule (B7). |
| F9 | `app.js:15147-15151` `probeStateLedger` | Paid: `.eq("publication_status","APPROVED").in("source_id",paid)`. Enforced non-admin: `.or("publication_status.is.null,publication_status.in.(APPROVED,APPROVED_GRANDFATHERED)")` | The state picker's existence flag for another state's ledger (a count/flag, not a row) | C, P | MO, OK, PA, MN, TN Available read as empty; MI and SC partly | Live in enforced; no filter in preview | REVIEW | Use the same predicate server-side: `publication_status.is.null` or `not.in.(BLOCKED,RESTRICTED)`. |
| F10 | `app.js:6090-6091` dossier; `6326`, `6371`, `6425`, `6471-6472` county source-truth tables; `seeAll` at `6082` / `6524` | `seeAll \|\| x.customer_approved \|\| x.fromRows`. Hidden sources are counted, never named | **Field / link:** source name, publisher and the official source URL in the county dossier and County Intelligence | C (not T, A) | Every UNREVIEWED registry source; `fromRows` exempts sources that have rows on screen (6326) | Live in enforced | REVIEW | In the filters, use `x.publication !== "BLOCKED" && x.publication !== "RESTRICTED"`. Keep the "Awaiting publication review" label (6094 / 6288). |
| F11 | Labels only:<br>• `sourceLineHtml` 896-911<br>• `sourceReviewHtml` 913-924<br>• `sourceReviewBannerHtml` 925-932<br>• `publicationGateHtml` 936-947<br>• `sourceUnderReview` / `sourceReviewText` 8623-8636 (also the export column `11654`)<br>• health `review` 7222 / 7289 / 9253<br>• "Why am I seeing this" 15351<br>• ledger notes 10769-10772, 13599, 14880 | Text derived from `isCustomerPublishable` | Nothing; adds "not customer-published" / "withheld" wording | all | UNREV10 | Live | label | Reword "not customer-published" to "Facts from <source> as published; reuse terms not yet reviewed". Keep the provenance and freshness lines. |
| F12 | `app.js:9085-9095` `auctionAvailableRelation` | `isPublishable(o)` on the related Available row | The cross-ledger sentence | as F1 | as F1 | Live | REVIEW (through F1) | Inherits F1. |
| F13 | `public/admin.js:395, 440` | `customerPublishable(status)` (NULL / APPROVED / APPROVED_GRANDFATHERED) and the Detroit subset | Admin "customer" count only | A | UNREV10 | Live | label / count | Mirror the F1 predicate. |

### Backend: Python, PowerShell, data

| # | Location | Exact condition | What it suppresses | Applies to | Current sources affected | Live? | Kind | Smallest change |
|---|---|---|---|---|---|---|---|---|
| B1 | `scripts/source_publication.py:76-85` `publishable(row)` | `effective_publication(row) ∈ {APPROVED, APPROVED_GRANDFATHERED}` **and** `PERM.listing_display(...)` allowed for some ledger of the source | Feeds `collectable` (B2) for auction / lien sources; `HE.gate` | Pipe | UNREV10 → False (no display record, and UNREVIEWED) | Live | MIXED (review + permission) | Leave as the "customer reuse reviewed" fact. Add a separate `displayable_public_facts(row)`: not BLOCKED / RESTRICTED, plus a `link` or `display` permission. |
| B2 | `scripts/source_publication.py:92-105` `collectable(row, record_source, op)` | `publishable(row)`, or `record_source == "laft"` and status ≠ BLOCKED; **and** `permitted(source_id, op)` | **Fetch and store.** Auction / lien sources need `publishable` | Pipe | Not fetched: `wi_dane_tax_deed_auction`, `co_morgan_treasurer_deed_auctions`, `sc_oconee_tax_sale_list` (UNREVIEWED auction / lien; each has fetch / parse / store records). UNREV10 are laft → collected | Live | MIXED: line 103 REVIEW for auctions / liens; line 105 KEEP (permission) | Change line 103 to `effective_publication(row) not in COLLECTION_BLOCKED | {"RESTRICTED"}` for every ledger. Keep line 105. |
| B3 | `scripts/harvest_expansion.py:124-145` `runnable_sources` | `SP.collectable(row, record_source)` | Zero requests for gated sources | Pipe | as B2 | Live | via B2 | none (inherits B2) |
| B4 | `scripts/sync_state_inventory.py:257-262` (store), `266-268` (writes `publication_status`), `509` (close-out source set) | `not collectable(reg, source, "store")` → `withheld_not_publishable`, not written | Storage. Sets the column the frontend reads | Pipe | as B2 (auction / lien). UNREV10 written with `UNREVIEWED` (`written_review_pending`) | Live | via B2 | none. Optionally also write a display-permission flag so the frontend can honour it (fact 3). |
| B5 | `harvesters/governance/publication.py:83-94` `effective_publication` | blocked vendor / governance BLOCKED → `BLOCKED`; `LEGAL_REVIEW_REQUIRED` and publishable → `RESTRICTED`; blank → `UNREVIEWED` | The status value everything reads | Pipe | tx_pbfcm / tx_mvba / tx_govease / tx_ctsa (BLOCKED) | Live | KEEP | none |
| B6 | `scripts/publication_gate.py:117-146` (propagation, `source=laft` only), `178-207` `apply_reviews` | Writes the registry and review status into `properties.publication_status` for laft rows | Indirect: the input of F2 | Pipe | all laft | Live | REVIEW (data source) | none (it carries the fact; the gate is F1) |
| B7 | `harvesters/governance/publication_state.py:356-368` (source gate), `370-375` (rules gate) | Source passes only when publication is APPROVED* **and** `display_permitted` (`listing_display`). Else `SOURCE_UNREVIEWED` / `SOURCE_RESTRICTED` / `SOURCE_BLOCKED` / `SOURCE_UNKNOWN` → `ADMIN_ONLY_SOURCE_REVIEW`. Rules: eligibility must be OFFERED, or COUNTY_DEPENDENT with the county covered (`data/state_ledgers.csv`) | Whole record server-side, once 031 is applied and the writer has run | C, T, P (not A) | UNREV10 → `SOURCE_UNREVIEWED`. `tx_lgbs` laft (421) → `RULES_NOT_VERIFIED` (TX AVAILABLE `NOT_VERIFIED`; pinned by `test_publication_state_gate.py:157`). Any source without a county-covered rule → `COUNTY_NOT_COVERED` | **Dormant** (031 not applied; `properties` has no `publication_state`) | Source branch: REVIEW (UNREVIEWED) + KEEP (BLOCKED / RESTRICTED). Rules / path / freshness gates (376-405): KEEP | At 358-368, pass when publication ∉ {BLOCKED, RESTRICTED} and (`display` **or** `link` permission). Add a new non-blocking reason `SOURCE_REUSE_NOT_REVIEWED` carried as a label. |
| B8 | `harvesters/governance/permissions.py:515-534` `authorize` / `listing_display`; the hard block at `125` and `444-445`; `449-451` (`NO_RECORD`); `462-463` (`LINK_ONLY` denies display) | Fail closed: no record → `NO_RECORD`; `RESTRICTED` / `BLOCKED` records deny; INTERIM allowed but `documented=False` | Every gated operation; display via B1 / B7 | Pipe | UNREV10 display → `NO_RECORD` | Live | KEEP (hard block, permission) | Code: none. Data: add `display` (or `link`) rows for UNREV10 in `data/source_permissions.csv`. INTERIM needs a reviewer, effective / expiry ≤210 days (`permissions.py:111`, `261-264`). This is an owner / legal record, not a code change. |
| B9 | `scripts/migrations/027_commercial_billing_entitlements.sql:298-305` | RESTRICTIVE SELECT: `can_read_unreleased_sources()` or (`publication_status = 'APPROVED'` and `source_id` in the paid-beta scope) | Whole record server-side for role `customer` | P | everything outside the 5 paid-beta sources, incl. NULL FL / TX rows | Dormant (027 not applied per CLAUDE.md "Controlled paid beta") | MIXED (commercial) | Commercial decision; mirrors F5. |
| B10 | `scripts/migrations/031_publication_state_gate.sql:152-153` | `alter policy "properties: approved only" using ((select is_approved()) and (publication_state = 'CUSTOMER_PUBLISHED' or (select is_admin())))` | Whole record server-side; NULL is never visible | C, T, P | all, until the writer runs, then per B7 | Dormant | via B7 | Change B7 before applying. The 031 SQL itself needs no edit. |
| B11 | `scripts/migrations/032_publication_gate_side_tables.sql:57-58, 82-92` | Side-table reads need the property to be readable (requires 031) | Event / observation / alert rows | C, T | follows B10 | Dormant | via B7 | none |
| B12 | `scripts/migrations/022_available_publication_gate.sql:58, 80-93` | Columns only; `44-45` says withholding is frontend-only, "a stricter, policy-level withholding is a separate, later decision" | none server-side | — | — | Applied (per CLAUDE.md) | — | none |
| B13 | `harvesters/enrichment/priority.py:79-81` `customer_visible`; `harvesters/imagery/__init__.py:233, 248` `CUSTOMER_FILTER`; `scripts/enrich_property_photos_naip.py:383-385` | Publication ∈ APPROVED* (priority also accepts NULL; imagery does not) | Ordering only: UNREV10 rows drop below P1-P3 and are imaged last | Pipe | UNREV10 | Live | REVIEW (priority only, not suppression) | Optional: use the new predicate. |
| B14 | `harvesters/sources/inventory.py:65-69` (`governance_from_publication`) → `harvesters/sources/model.py:156-159` `may_write` | UNREVIEWED registry source → `REVIEW_REQUIRED` → `may_write` False | **Field-level:** the AVAILABLE enrichment engine never writes values *from* that source onto rows (`scripts/enrich_available.py:155`, `207`) | Pipe | UNREV10 as enrichment sources | Live | REVIEW | Optional. Their own rows are unaffected. |
| B15 | `harvesters/governance/gate.py:50-91` `check_ingestion_gate`; `scripts/sync-texas-to-supabase.py:286-293` (plus `_store_permitted` 180) | Legal status ∈ `INGESTION_ALLOWED_STATUSES` (`registry.py:57-60`), and a store permission | Storage of TX rows | Pipe | tx_lgbs / tx_realauction (allowed today); blocked TX vendors | Live | KEEP | none |
| B16 | `scripts/laft_status.py:551-563` `permission_gate`; `scripts/laft_lifecycle.py:390-410` (`NOT_PERMITTED`); FL `.ps1` guards (`scripts/*.ps1:14` → `source_permission_check.py`); also `lgbs_available_refresh.py:205/285`, `auction_outcomes.py:522`, `harvest_state_inventory.py:130`, `texas_harvester.py:1198`, `enrich_property_details.py:1400`, `harvesters/enrichment/parcels.py:226`, `geocode.py:71` | Per-operation permission (fetch / parse / store / enrich) | Fetch, storage, enrichment | Pipe | FL / TX sources (all INTERIM-allowed today) | Live | KEEP | none |
| B17 | `harvesters/governance/commercial_scope.py:61-69` `scope_for` | APPROVED → CUSTOMER_APPROVED; blank / APPROVED_GRANDFATHERED → REQUIRES_PUBLICATION_DECISION; collected other → TESTER_PREVIEW | Labels in `public/commercial-scope.json` (input to F5 / B9) | Pipe | UNREV10 = TESTER_PREVIEW | Live (generated file) | REVIEW (classification) | Only if F5 changes. |
| B18 | `harvesters/sources/acquisition_gate.py:211-212` | `publication_status ∉ PUBLISHED_STATUSES` → `SOURCE_NOT_PUBLISHED` | Python twin of F7 (dry-run / reporting) | Pipe | as F7 | Reporting only | REVIEW | Same as F7, with the fixture. |

### Data semantics

- **`data/source_permissions.csv`** (230 rows).
  - DOCUMENTED = `APPROVED` / `APPROVED_WITH_CONDITIONS` on `PUBLISHED_LICENSE` / `WRITTEN_PERMISSION`.
  - INTERIM = an open status (`LEGAL_REVIEW_REQUIRED` / `OWNER_PERMISSION_REQUIRED` / `UNKNOWN`) on `INTERNAL_RISK_ACCEPTANCE` / `GRANDFATHERED_PRACTICE`. It is allowed but `documented=False` (`permissions.py:20-34`, `90-104`, `480-482`).
  - Operations are listed at `permissions.py:63-73`.
  - Display records exist for `sc_york_tax_sale`, `wy_albany_tax_sale` and `mi_eaton_treasurer_sale` (`OWNER_PERMISSION_REQUIRED` / `INTERNAL_RISK_ACCEPTANCE`).
  - `tx_lgbs`, `tx_realauction`, and `fl_realauction` `sale_calendar` / `fl_lienhub_certificates` hold `LEGAL_REVIEW_REQUIRED` / `GRANDFATHERED_PRACTICE` display records.
  - `la_ebr_adjudicated` has `APPROVED_WITH_CONDITIONS` / `PUBLISHED_LICENSE` with `dated_list_only`.
  - `fl_laft_html` has `UNKNOWN` / `GRANDFATHERED_PRACTICE`.
  - **UNREV10: no display, no link record.**
- **`data/available_publication_reviews.csv`**: two rows, `sc_georgetown_forfeited_land` and `sc_spartanburg_forfeited_land`, both `REVIEW_REQUIRED`.
  - Both have `commercial_use_permitted=not_stated` and `republication_prohibited=not_stated`.
  - The reason text says no grant and no prohibition is published.
  - Spartanburg's list is also "not AVAILABLE inventory".
  - `available_coverage.problems()` requires these rows to agree with the catalog (CLAUDE.md, "SC AVAILABLE"); not re-read here.
- **`data/county_source_registry.csv`**: columns `governance_status` (14), `verification_status` (13), `publication_status` (25), `restrictions` (26), `purchase_path_mode` (27).
  - UNREV10 are all `governance_status=APPROVED`, `PRODUCTION_VERIFIED`, `publication_status=UNREVIEWED`, ledger `AVAILABLE`.
  - Their restrictions read "AVAILABLE source read live; no reuse licence or owner decision...".
  - So the **only** thing separating them from customer display is the publication / reuse review, plus the missing display permission records.

## 2. Classification summary

- **Keep (hard block, permission, quality):**
  - B5, B8 (code), B15, B16;
  - the rules / path / freshness parts of B7;
  - the non-601 reasons of F7 / B18;
  - F1(1) BLOCKED;
  - RESTRICTED anywhere (it means "reviewed and restricted", with a reason; `publication.py:117-118`).
- **Review-status-only candidates:** F1(6), F2 (as a visibility test), F3 / F12 (inherit), F4, F9, F10, F7 line 601, B1 (for auctions / liens through B2 line 103), B7 lines 366-368 for `UNREVIEWED`, B13, B14, B17, B18.
- **Separate owner decisions (not review status):**
  - F6 Detroit subset;
  - F5 / B9 paid-beta scope;
  - B7's rules gate (`RULES_NOT_VERIFIED` would hide `tx_lgbs` laft once 031 is applied).

## 3. Minimal change set

Goal: show UNREVIEWED-source records as "facts from <named source> + official link + provenance + freshness / missing-data labels". Hard blocks, BLOCKED, RESTRICTED, login / captcha sources and permission denials stay as they are.

### 1. `public/app.js`

1. Add a hoisted function declaration (TDZ), `isPublicRecordDisplayable(p)`:
   - `publication_status` not in {BLOCKED, RESTRICTED};
   - an https official link: `list_url` \|\| `url_auction` \|\| `document_url` \|\| `otc_provenance.source_match.source`;
   - optionally `last_seen_at` present (else show "Last read not recorded" rather than hide).
2. In `isPublishable` (872-885), replace `isCustomerPublishable(p) || viewerScope() === "preview"` at **884** with `isPublicRecordDisplayable(p)`. Keep 873, 874, 878, 879 (Detroit, if the owner keeps the cap) and `acqGateAllows`.
3. In `applyLedgerRows` (4285-4298), `REVIEW_PENDING_SHOWN` now also counts for customers. `WITHHELD` counts only BLOCKED / RESTRICTED / no-link.
4. In `probeStateLedger` (15150), change the filter to `publication_status.is.null,publication_status.not.in.(BLOCKED,RESTRICTED)`.
5. Dossier / county truth (6090-6091, 6326, 6371, 6425, 6471-6472): replace `x.customer_approved` in the filters with `!["BLOCKED","RESTRICTED"].includes(x.publication)`.
6. Labels (899, 917-919, 931, 8627, 8633, 10769-10770, 13599, 14880, 15351): reword "not customer-published" to "Source reuse terms not yet reviewed - facts shown as published by <source>". `sourceReviewBannerHtml` (925-932) stays and is reworded.
7. Optional: drop the 601 check, or narrow it to BLOCKED / RESTRICTED (dormant while `availableGate` is off).
8. `public/admin.js:395, 440`: mirror the predicate for the admin "customer" count.

### 2. Backend, only if collection or the 031 rule should match

1. `harvesters/governance/publication_state.py:356-368`: pass the source gate for UNREVIEWED when display **or** link is permitted; reason `SOURCE_UNREVIEWED` becomes a non-blocking label. Keep BLOCKED / RESTRICTED / UNKNOWN blocking.
2. `scripts/source_publication.py:103` (optional, collection of UNREVIEWED auction / lien sources): allow every ledger unless BLOCKED / RESTRICTED. Line 105, the permission check, stays.
3. `harvesters/sources/acquisition_gate.py:211-212` together with F7.

### 3. Data, owner / legal action rather than code

Add `display` (or `link`) rows for UNREV10 to `data/source_permissions.csv`; otherwise B1 and B7 keep denying.
- INTERIM rows need a reviewer, `effective_on`, and an `expires_on` within 210 days (`permissions.py:111`, `261-264`).
- `test_source_permissions.py:275-280` asserts their absence.
- The frontend does not consult permissions today (fact 3), so step 1 alone changes customer visibility.

### Tests that pin current behaviour and would need updating

| Area | Location | What it pins |
|---|---|---|
| Playwright | `tests/run_test.mjs:6274-6351, 6450` | devVis* fixtures |
| Playwright | `tests/run_test.mjs:7188-7194` | Expected `devVisAdminMiLands`, `devVisCustomerMiLands` / `ScLands` `cards: 0` and the withheld text, `devVisPreviewScLands` |
| Playwright | `tests/run_test.mjs:599` and `7406` | `ledgerWithheldText` "1 record withheld - source not approved for customer publication ..." |
| Playwright | `tests/run_test.mjs:7111-7114` | `tnVisibility` customer withheld text |
| Playwright | `tests/run_test.mjs:6706-6741` and `7132-7140` | `paidLegacy` / `paidTester` / `paidCustomerVisibility` vectors; `unreviewed` true / true / **false** |
| Playwright | `tests/run_test.mjs:6315` | `#sourceReviewBanner` |
| Playwright | `tests/run_test.mjs:5030, 5209, 5242, 7086-7094` | The withheld lines in the publication-gate / acquisition-gate blocks; `gateCustomer` / `gateAdmin` / `gateOff` |
| Stub | `tests/vendor/supabase-stub.js:251-337` | UNREVIEWED fixture rows. Add an https link to each if the new predicate requires one; several already carry `list_url` / `url_auction` (e.g. 256-266). |
| Python | `tests/python/test_detroit_customer_subset.py:119-129` | Pins the order of `isPublishable` and the literal `'isCustomerPublishable(p) \|\| viewerScope() === "preview"'` |
| Python | `tests/python/test_commercial_layer.py:55` | `publicationMode: "preview"` in config |
| Python | `tests/python/test_commercial_layer.py:102-106` | In `isPublishable`, the `viewerScope() === "paid"` check precedes the `"preview"` one |
| Python | `tests/python/test_tennessee_enrichment.py:320-322` | `publicationMode` preview and the "withheld - source not approved for customer publication" string |
| Python | `tests/python/test_available_commercialization.py:406` | Same string |
| Python | `tests/python/test_available_inventory_sprint.py:210-275` | `SP.publishable` False and `collectable` True for Oceana; publishable only with a display record |
| Python | `tests/python/test_tennessee_shelby.py:66-77` | `collectable and not publishable` |
| Python | `tests/python/test_available_expansion_mo_ok_pa_mn.py:76, 91, 242` | "collected not published" |
| Python | `tests/python/test_five_state_enrichment.py:276-283` | `wi_dane_tax_deed_auction` gated `UNREVIEWED`, `withheld_not_publishable == 2`. Changes only if B2 line 103 changes. |
| Python | `tests/python/test_source_permissions.py:263-272, 275-280, 445-451` | Display parity, UNREV10 `NO_RECORD`, `SOURCE_RESTRICTED` without a display permission |
| Python | `tests/python/test_publication_state_gate.py:149-154` | e10 `tn_shelby_landbank` → `SOURCE_UNREVIEWED` / `ADMIN_ONLY_SOURCE_REVIEW` |
| Python | `tests/python/test_publication_state_gate.py:157-160` | e11 rules gate; keep |
| Python | `tests/python/test_display_permission_dataset.py:68` | `publishable` per ledger |
| Python | `tests/python/test_acquisition_gate.py:89-91` and `tests/python/test_otc_acquisition_gate.py:154-166` | `availableGate` off; no `ledgerWithheldAcq` |
| Python | `tests/python/fixtures/acquisition_gate_cases.json` | 2 `SOURCE_NOT_PUBLISHED` cases, if F7 / B18 change |
| Python | `tests/python/test_sc_available.py:299-330` | Review-CSV agreement; unaffected unless reviews change |

### Not found

- I found no backend code that drops UNREVIEWED **laft** rows from storage; they are collected and stored (B2 / B4).
- I found no server-side policy active today that filters `properties` on `publication_status`. 022 adds no policy (`022:44-45`); 027 and 031 are unapplied.
- I could not verify the deployed `config.js`, or whether 027 is applied in production (the repo documents it as not applied).
