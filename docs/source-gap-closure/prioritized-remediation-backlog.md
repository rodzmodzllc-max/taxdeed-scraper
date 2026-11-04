# Prioritized remediation backlog (source gap closure, 2026-10-22)

One ranked list across the three workstreams, then the detail of each. Every count comes from the read-only baseline in [`baseline/`](baseline/) (captured 2026-10-22, about 17:25 UTC) or from repository records; nothing here was measured after that. An item marked **owner** or **counsel** needs a decision or a production authorization; this sprint did not take it.

## Cross-workstream ranking

Ranked by investor value, coverage gained, reliability, permission confidence and effort, in that order of weight. Effort: S under a day, M a few days, L longer or dependent on someone outside the team.

| Rank | Item | Why first | Measurable result | Effort | Who acts |
|---|---|---|---|---|---|
| 1 | **C-1** Report a sale day whose closed listing stopped at ten items as truncated | Today a partly read day looks complete in the run report (`scripts/realauction_results.py` `fetch_area`). Nothing else on this list can be measured honestly until the gap is visible. | Truncated FL sale days reported per run (today: never reported). | S | engineering (code PR, this sprint) |
| 2 | **B-04** Pass the ledger's dataset to the display permission check | Every Florida `display` record is per dataset; the check passes none, so Florida rows the records allow come back `NO_RECORD`. Once migration 031 is applied this would hide them from customers. | Florida sources whose recorded `display` permission is honoured by the publication gate: from 0 to every source with a record. | S | engineering (code PR, this sprint); 031 itself stays an owner decision |
| 3 | **A2 / B-15** Seed the live `county_source_registry` with the 116 missing repository rows and fill blank `ledgers` / `update_frequency` | Reads of 113 production units can never be recorded, so freshness and failures are invisible for them. | Units with a recorded last attempt: 121 → 237. | S | engineering + owner (production write) |
| 4 | **C-2** Read every closed item of a sale day, not only the first ten | The most likely main cause of FL past events with no verified outcome. | FL past events with a source-stated outcome: up to +237 of 257 unknown. | M | engineering (no new permission: same anonymous session) |
| 5 | **A1** Restore Florida certificate reads | LienHub has refused the runner since 2026-10-01; no active FL certificate row is confirmed. | Active FL certificate rows read within 14 days: 0 → up to 1,611. | M–L | owner (provider or Tax Collector access; never route around the refusal) |
| 6 | **A3** Close FL auction rows that left the county sale feed before their sale date | 183 active rows are stale or never stamped; they read as upcoming sales elsewhere. | Unstamped/stale active FL auction rows: 183 → 0, each closed with basis "left the feed", never "sold". | S–M | owner authorization (lifecycle change), then engineering |
| 7 | **B-01** Decide the customer CSV export against `redistribute` | No source has an allowed `redistribute` record, yet the export ships owner names, values and legal descriptions. | Export columns each traced to an allowed operation. | S code, decision first | owner + counsel |
| 8 | **A8** Publication reviews for UNREVIEWED Available sources | Inventory already collected but invisible to customers. | Customer-visible Available rows: up to +42,797 active, per decision. | S (owner time) | owner |
| 9 | **A5** Decide Texas cadence (scheduled with close-out, or labelled manual) | 382 of 421 TX Available rows stale; 122 TX auction rows never stamped, sale dates past. | TX active rows read within 14 days: 0 → 543, or explicit labelling. | M | owner |
| 10 | **B-02 / B-03** Counsel reads the core vendor terms; put the DOR and UGRC written replies on file | Interim allowances expire 2027-04-12; internal acceptance is not permission. | Sources with documented (not interim) permission. | L | counsel + owner |

Items not in the top ten stay ranked inside their workstream below.

## Workstream A: listing coverage and freshness (detail)

This backlog covers listing coverage and freshness. The items are ranked by five things together: investor value, missing coverage, reliability, how confident we are about permission, and effort.

The numbers come from `baseline/` (captured 2026-10-22) and the repository registry. The "expected change" column states counts that can be measured afterwards with the query in `coverage-baseline.md` §4. A count describes a listing or read state. It never says anything about whether a sale, redemption or cancellation happened.

| Rank | Item | Problem | Evidence | Proposed fix | Effort | Expected coverage change (measurable) | Permission dependency |
|---|---|---|---|---|---|---|---|
| A1 | Restore Florida certificate reads | LienHub has refused the GitHub runner since 2026-10-01. Every active FL certificate row is unconfirmed. | 1,611 of 1,611 active rows have never been stamped. 22 of 26 counties were last updated 2026-09-30. 6 registered counties hold 0 rows (Brevard, Clay, Collier, Indian River, Lee, Pinellas). See `docs/gap-queue.md` §D. | 1. Read the status files of the last `certificates` runs to confirm which error category applies.<br>2. Record that category: it is currently NULL in every row.<br>3. Contact the provider (Grant Street Group) or the counties' Tax Collectors for allow-listed access or a data feed.<br>Do not route around the refusal. Until reads resume, label the rows with their last read date, as the frontend already does. | M (outside dependency) | Active FL certificate rows stamped within 14 days goes from 0 to up to 1,611. Counties with a recorded read goes from 0 to 32. | `fl_lienhub_certificates` is LEGAL_REVIEW_REQUIRED (`docs/florida-data-map.md` §3). It runs on an interim allowance in `data/source_permissions.csv` that expires 2027-04-12 (CLAUDE.md "Source permissions"). Asking for access is a good moment to ask for documented permission. |
| A2 | Seed the live registry with every repository registry row | `unit_freshness.py` can only PATCH rows that already exist. 116 registry rows are absent from the production table, so their reads are never recorded. | 121 live rows against 237 in the repository. Missing: `fl_realauction` 46, `fl_lienhub_certificates` 32, `tx_realauction` 24, 10 Available sources, Okaloosa Bid4Assets, AL, AR and AZ. In the live rows, `ledgers` is NULL in 92, `update_frequency` NULL in 60, and `last_error_category` NULL in all 121 (7 of them FAILED). | Add an idempotent upsert from `data/county_source_registry.csv` that inserts missing rows and refreshes `ledgers` and `update_frequency`. Freshness columns are never overwritten. Then check why `last_error_category` is not written. | S | Units with a recorded last attempt goes from 121 to 237, of which 113 are production units. FAILED units with an error category goes from 0 of 7 to 7 of 7. | None for the sources. The production write needs owner authorization. |
| A3 | Florida auction rows that left the sale feed before their sale date | A row whose sale date is still in the future stays `active` after it disappears from the county's Waiting feed. The close-out only acts after the sale day. | 146 active rows never stamped and 37 stale more than 14 days, out of 1,065. Largest: Lee 28 + 8, Hillsborough 21 + 11, Broward 21 + 1, Orange 17 + 3, Manatee 14. CLAUDE.md records this mechanism ("Auctions off the county's current sale list", 2026-10-06). | Extend the deed sync's close-out, owner-authorized: a future-dated row absent from a COMPLETE county read becomes `closed` / `removed`, with the basis "left the feed". A sale is never inferred. The frontend already labels these rows (`offCurrentSaleList`). | S–M | Active FL auction rows that are not stamped and not current goes from 183 to 0. Each is closed with an explicit basis. | Covered by the existing `fl_realauction` store permission (interim). |
| A4 | Florida Available units whose reads fail | 12 of 52 production units have no healthy read. | FAILED: Brevard 22 consecutive, Hendry 22, Columbia 10, Escambia 10, Union 10 (all three last succeeded 2026-10-01), Pasco 9, Manatee 5 (last succeeded 2026-10-15). INCOMPLETE with no success ever: Franklin, Gulf, Hamilton, Holmes, Taylor. Rows stuck as a result: Hendry 2 and Pasco 1 never stamped, Escambia 1 stale. Escambia and Hendry pages answer 403 to the runner (`docs/gap-queue.md` §D). CLAUDE.md says Brevard's procedural PDF reads INCOMPLETE by design, but the live status is FAILED. | Diagnose each unit with `job=evidence` (value-free capture). Fix parser drift where the source answered. Where the source refused, record SOURCE_UNAVAILABLE and request records access. Reconcile Brevard's FAILED status with its documented by-design INCOMPLETE. | M | Healthy units (COMPLETE or EMPTY) goes from 40 of 52 to as many as 52 of 52. | Every unit is APPROVED_GRANDFATHERED with interim permission. Nothing new is needed. |
| A5 | Decide how often Texas is read, or label it | Texas is manual-only by owner decision. Rows go stale with no read and no close-out, and the auction rows' sale dates had passed by 2026-10-10. | TX Auctions: 122 active rows, all never stamped, `inventory_status` NULL on all 122, and 13 of 24 registered RealAuction counties hold 0 rows. TX Available: 382 of 421 stale more than 14 days and 39 never stamped. `sync-texas-to-supabase.py` has no close-out or `last_seen_at`. | Owner decision first. Then either:<br>(a) a scheduled `texas` job with `stamp_seen`, a close-out gated on COMPLETE reads, and the inventory-status writer; or<br>(b) stay manual, but treat past-sale auctions as closed or "not on the current list" when displayed. | M | Active TX rows with a read in the last 14 days goes from 0 to 543. TX auction rows with a non-NULL `inventory_status` goes from 0 to 122. | `tx_lgbs` and `tx_realauction` are REVIEW_REQUIRED in the enrichment source model (CLAUDE.md "All-sources AVAILABLE enrichment engine"). Scheduling needs the owner's decision and the permission records. |
| A6 | Publication state for ledgers with NULL `publication_status` | FL Auctions, FL Liens and TX Auctions carry no `publication_status`. Under migration 031, a row with no publication state is hidden from customers. | 4,433 rows NULL: FL Auctions 2,644, FL Liens 1,667, TX Auctions 122. `publication_gate.py` covers the Available ledger only (lines 2, 133–134). CLAUDE.md records 031 as not applied; that was not re-checked. | Run `publication_state_writer.py` for FL and TX (`job=publication`) before 031 is applied. Keep the documented order: 031, then the writer for every state. | S | Rows with a publication state goes from 55,592 to 60,025 (a gain of 4,433). | Needs a `display` permission record per source (`permissions.authorize`). FL RealAuction and LienHub hold interim records only. |
| A7 | Registered counties with no rows, and orphan units | Some registered county sources have never produced a row. Some rows have no registry row, so no read can ever close them. | Registered with 0 rows: `fl_realauction` Calhoun, Gulf, Monroe, Okeechobee, St. Johns, and `fl_bid4assets_okaloosa`. Orphans: FL DeSoto (9 rows, 4 active never stamped), FL Collier (1 row), TX Concho `tx_lgbs` (9 active never stamped). | Read `harvest_all_status.json` for the six registered units. EMPTY with a valid signal is a legitimate zero. Anything else is a read defect to fix. For orphans: either register the county (DeSoto and Collier would need `data/realauction_counties.csv` entries) or close their rows with the basis "no current source". | S | Registered units with a recorded outcome: 6 more. Orphan active rows goes from 13 to 0. | Same interim records as the existing source. Adding a county is a scope change that needs the owner's sign-off. |
| A8 | Publication reviews for UNREVIEWED Available sources | Collected inventory that customers cannot see. | 43,361 rows (42,797 active): MI 30,847, MO 9,778, TN 2,111, PA 376, OK 195, SC 52, MN 2. See `docs/state-coverage.md` APPROVAL_UNRESOLVED. | The admin records a review per source (`data/available_publication_reviews.csv` and the admin panel). No engineering is needed. | S (owner time) | Customer-visible Available rows grows by up to 42,797, depending on each decision. | This is the dependency itself: each approval needs a published licence or recorded permission (`docs/source-permissions.md`). |
| A9 | Capture fields the sources publish that TAXACQ does not keep | Fields are read or published but not kept. See `field-availability-matrix.csv`, rows marked PUBLISHED_NOT_CAPTURED. | • RealAuction item id (`sale_event_id`): 2,644 FL auction rows.<br>• Sale time on closed items.<br>• FL Available `high_bid` / `winning_bid`, read by `harvest_laft_pioneer.py:119`, `_osceola.py:116`, `_orange.py:229` and `_hillsborough.py:153`: about 39 rows.<br>• Georgetown tax sale date (`sc_flc.py:334`).<br>• Morgan "date eligible for auction" (`tabular.py:303`). | Store the RealAuction item id on `auction_events`, which links events across postponements. Keep the Available high and winning bids as historical, source-labelled facts, never as a price. | S each | Rows with a source sale-event id goes from 0 to 2,644. FL Available rows with the original auction result goes from 0 to about 39. | Same source records. Storing an original-sale figure is display-relevant: confirm the `display` operation. |
| A10 | Field fill on sources where it is unverified | Many cells are NOT_YET_VERIFIED: the adapter maps nothing, but the source may publish the field. | • Legal description 0 on 30,847 MI Available and 2,111 TN rows.<br>• Coordinates 0 on 195 OK, 376 PA and 52 SC Available rows; MO has them on 412 of 9,778.<br>• MI auction `sale_date` is stored on 38 of 43 rows, but no mapping for it exists in `expansion.py`. | 1. Probe the fill of each layer's fields with `scripts/probe_field_fill.py` (`job=evidence`, `evidence_scope=field_fill`).<br>2. Map only the columns that are measured as filled.<br>3. For coordinates, use `geocode_authoritative.py` exact-identifier matches only.<br>4. Trace where the MI `sale_date` values come from. | S to probe, M to map | Measurable per field, for example MI Available `legal_desc` fill from 0 of 30,847 upward. Coordinates on up to 623 OK, PA and SC rows plus 9,366 MO rows. | `discovery_guard` refuses capture without a `discover` record. Parcel or coordinate layers each need their own permission records. |
| A11 | Counties with no source at all | Coverage gaps in the registry. | FL: 15 of 67 counties have no production Available source and 20 of 67 have no auction source. TX: 24 RealAuction counties, 8 LGBS counties, 14 blocked-vendor rows and 20 search-evidence candidates, out of 254 counties. | Use the existing discovery process (`data/acquisition_candidate_pages.csv`, `data/available_discovery_pages.csv`, then `job=evidence`). Build an adapter only after the source is verified. | L | Counties with a production source, per ledger. Measure with `county-source-map.csv`. | Every new source needs governance review. Blocked vendors stay blocked: `tx_pbfcm` and `tx_mvba` are hard-denied in code. |

## Workstream B: commercial-use permissions (detail)

Inputs:

- `docs/source-gap-closure/permission-evidence-matrix.csv`: 97 sources. The operation rights in it are derived by
  `harvesters/governance/permissions.authorize()` evaluated 2026-10-22.
- `validation-and-test-plan.md`, section "Permission enforcement gaps found in code": code gaps T-1 to T-12.
- `baseline/by_county.json`: row counts.
- `baseline/registry_live.json`: the production registry snapshot.

Nothing here is a legal opinion. "Interim" always means internal risk acceptance or grandfathered practice. It
expires 2027-04-12 and is never external permission.

### Where things stand (counts only)

| Eligibility (matrix) | Sources |
|---|---|
| APPROVED_DEFINED_USE | 0 |
| APPROVED_WITH_CONDITIONS | 8: la_ebr_adjudicated, la_ebr_tax_parcels, la_ebr_tax_roll, co_douglas_county_held_liens, co_douglas_tax_sale_list, usda_naip, ut_ugrc_lir_saltlake, fl_dor_pto_parcel_gis |
| OFFICIAL_LINK_ONLY | 3: tx_hctax, tx_comptroller_directory, wi_dane_tax_deed_auction |
| PERMISSION_UNRESOLVED | 24 |
| COUNSEL_REVIEW_REQUIRED | 15 |
| BLOCKED | 6: tx_govease, tx_pbfcm, tx_mvba, tx_ctsa, google_street_view, streetview_imagery |
| INSUFFICIENT_EVIDENCE | 41 |

Customer-visible active rows (baseline), by the basis of their `display` record:

- **Documented licence: 10,472.** LA EBR 10,334 and Douglas CO 138.
- **Interim only: 4,524.** These lose their allowance on 2027-04-12.

  | Source | Active rows |
  |---|---|
  | fl_lienhub_certificates | 1,611 |
  | fl_realauction | 1,065 |
  | sc_york_tax_sale | 853 |
  | tx_lgbs | 440 |
  | wy_albany_tax_sale | 253 |
  | FL LAFT | 158 |
  | tx_realauction | 103 |
  | mi_lenawee_tax_sale | 35 |
  | mi_eaton_treasurer_sale | 3 |
  | co_morgan_county_held_certificates | 3 |

  Of these, 2,798 have a NULL `publication_status`: no publication decision at all.
- **Paid-beta rows sold on an interim allowance only: 891.** sc_york 853, mi_lenawee 35, mi_eaton 3, wi_green 0. The
  only documented paid-beta source is la_ebr_adjudicated, with 10,334 rows.
- **Withheld from customers because publication is not approved: 42,797 active rows** across the ten admin-only
  AVAILABLE sources.

  | Source | Active rows |
  |---|---|
  | mi_detroit_landbank_lots | 30,590 |
  | mo_stl_lra_inventory | 9,778 |
  | tn_shelby_landbank | 1,787 |
  | pa_fayette_repository | 376 |
  | ok_oklahoma_county_owned | 195 |
  | sc_horry_forfeited_land | 51 |
  | mi_detroit_landbank_programs | 12 |
  | mi_oceana_landbank | 5 |
  | mn_ramsey_tax_forfeit | 2 |
  | sc_georgetown_forfeited_land | 1 |

### Drift: repository registry vs live registry (`baseline/registry_live.json`)

The comparison key is (state, county, source_id), with a blank source_id compared as blank.

- **Live has 121 rows; the repo CSV has 237.** All 121 live rows exist in the repo. **116 repo rows are missing from
  the live table:**

  | Source | Missing rows |
  |---|---|
  | fl_realauction | 46 |
  | fl_lienhub_certificates | 32 |
  | tx_realauction | 24 |
  | the ten admin-only AVAILABLE sources | 1 each |
  | fl_bid4assets_okaloosa | 1 |
  | al_ador_state_land, ar_cosl_post_auction, az_maricopa_state_cp | 1 each |

  `scripts/publication_gate.py:209-226` (`sync_registry_table`) only PATCHes rows that already exist, so these rows
  are never created. Live views that read the registry table cannot see any auction or certificate source, nor any
  of the ten admin-only sources. That includes per-source health / `last_success_row_count` and admin publication
  reviews keyed to a registry row.
- **`governance_status`, `publication_status` and `verification_status` agree on every shared row.** There is no
  status drift.
- **`ledgers` is blank in live for 61 rows** where the repo has values: 52 FL `fl_laft_*` rows (AVAILABLE), 8
  `tx_lgbs` rows (AUCTIONS|AVAILABLE) and 1 `tx_hctax` row (AVAILABLE).
- Live distribution:

  | governance / publication | Rows |
  |---|---|
  | APPROVED_GRANDFATHERED / APPROVED_GRANDFATHERED | 52 |
  | TERMS_NOT_VERIFIED / UNREVIEWED | 31 |
  | BLOCKED / BLOCKED | 14 |
  | APPROVED / APPROVED | 9 |
  | APPROVED / APPROVED_GRANDFATHERED | 8 |
  | APPROVED / UNREVIEWED | 3 |
  | NOT_APPLICABLE / UNREVIEWED | 3 |
  | LEGAL_REVIEW_REQUIRED / RESTRICTED | 1 |

- **Repo-internal drift (registry vs permission records), item B-08:** `governance_status=APPROVED` appears on 20+
  sources whose permission records are OWNER_PERMISSION_REQUIRED, LEGAL_REVIEW_REQUIRED or RESTRICTED.

---

### Ranked items

Effort scale: S < 1 day, M 1–3 days, L > 3 days or external wait.

#### B-01. Gate the customer CSV export on `redistribute` (code enforcement gap; legal exposure)

- **Evidence:** T-1. `public/app.js:11368-11609` exports owner names, values and legal descriptions with no
  `redistribute` check. `co_oit_public_parcels` redistribute is RESTRICTED ("resale ... forbidden by the State's
  terms"). FDOR redistribute is LEGAL_REVIEW_REQUIRED. No source in `data/source_permissions.csv` has an allowed
  `redistribute` record.
- **Who:** engineering builds the gate. The owner decides whether to disable export or limit its columns until
  records exist. Counsel decides whether any export of the Public Domain or CC sources needs a record. Those
  licences permit it, but no record has been written.
- **Effort:** M.
- **Unblocks:** removes a live leak of restricted data. It covers 141 CO rows carrying co_oit fields, and every FL
  row with FDOR attributes. Prerequisite for any paid tier.

#### B-02. Counsel reads the four core vendor documents (legal uncertainty)

- **Evidence:** `docs/legal/pre-sale-blockers.md` items 1–3; `docs/audit/counsel-review-packet.md`. The documents
  are the RealAuction Alachua/Volusia EULAs (no copy in the repo, only the summary in `authorization.py`), the
  LienHub User Agreement (recorded as prohibiting robots/spiders) and the Linebarger legal-disclosures clause
  (`docs/lgbs-rights-audit.md`). All four sources run on interim allowances that expire 2027-04-12.
- **Who:** counsel, then the owner.
- **Effort:** L (external).
- **Unblocks:**
  - the 2,798 NULL-publication rows (FL auctions 1,065, FL certificates 1,611, TX RealAuction 103, LGBS auctions 19);
  - 421 LGBS AVAILABLE rows;
  - 40 RealTDM LAFT rows;
  - 121 of 237 registry rows.

  Without it, all of these are denied on 2027-04-12.

#### B-03. Put the written DOR and UGRC replies on file (missing evidence)

- **Evidence:**
  - `fl_dor_pto_parcel_gis` is recorded as WRITTEN_PERMISSION, but the email is not in the repository:
    `authorization.py:1058-1101` has `written_permission=False`, `document_location=None` and `is_pending=True`;
    `data/source_approvals.csv` has `evidence_received_on` blank.
  - The commercial-use statement rests on the owner's summary.
  - The UGRC reply is in the same state, but its basis is the published CC BY 4.0 licence, so the risk is lower.
- **Who:** the owner, who supplies the email: date, sender address and message id, stored privately with a
  reference only. Engineering then records `document_location` and `document_hash` and flips
  `written_permission=True`.
- **Effort:** S.
- **Unblocks:** a real documented basis for the 64 stored Broward/FL boundaries and the Florida Available boundary
  loader. It also closes T-12.

#### B-04. Fix the dataset-blind display check before applying migration 031 (code enforcement gap; launch blocker for 031)

- **Evidence:** T-3. `harvesters/governance/publication_state.py:201-203` and `scripts/source_publication.py:69-73`
  call `authorize` without a dataset. Every FL source returns `NO_RECORD`, verified locally 2026-10-22.
- **Who:** engineering.
- **Effort:** S–M. This needs one source_id → permission-dataset map, shared with `laft_status`, `stamp_seen` and
  `auction_events_writer`.
- **Unblocks:** a correct `publication_state` for FL. Without the fix, applying 031 and running the writer withholds
  about 2,834 active FL rows that the records do allow.

#### B-05. Make customer display follow `display` permission and its expiry before 031 (code enforcement gap)

- **Evidence:** T-4.
  - `scripts/publication_gate.py:127-145` and `scripts/sync_state_inventory.py:266` write `publication_status` with
    no permission check.
  - `public/app.js:702-705` shows NULL as publishable.
- **Who:**
  - engineering, for the downgrade on denial;
  - the owner, for whether NULL stops meaning "show". That decision affects 2,798 rows today.
- **Effort:** M.
- **Unblocks:** an enforced 2027-04-12 expiry. Otherwise 4,524 interim-display rows stay on screen after their
  allowance lapses.

#### B-06. Add a display decision for enrichment-derived fields (code enforcement gap; legal)

- **Evidence:** T-2. FDOR, co_oit, EBR tax roll/parcels, FEMA, Census, Santa Rosa and Palm Coast values are shown.
  None has a `display` record. `docs/source-permissions.md:199` says FDOR display "is denied".
- **Who:**
  - engineering: a per-field display gate keyed on `field_provenance`;
  - the owner and counsel: which sources get `display` records. The EBR Public Domain sources are a records-only
    change. FDOR (FGIO cadastral) needs counsel, or the DOR reply if it covers it. The DOR PTO approval explicitly
    does not cover tax-roll attributes or FGIO.
- **Effort:** M (engineering) + L (FDOR legal).
- **Unblocks:** honest display of the enriched values on FL rows, the 141 active CO (Douglas/Morgan) rows and the 10,334 LA rows.

#### B-07. Send the county permission requests (group A) and record the replies (missing evidence)

- **Evidence:** `docs/audit/permission-inquiry-tracker.md` group A is NOT SENT for Morgan CO, Eaton MI, Lenawee MI,
  York SC, Green WI and Albany WY. Oklahoma County is DRAFTED, NOT SENT. Group B is REPORTED_SENT_UNVERIFIED (FDOR
  statewide, Detroit GIS, St. Louis, Fayette, Oklahoma OGI, RealAuction).
- **Who:** the owner sends the requests. Engineering records `WRITTEN_PERMISSION` rows only when a written grant
  arrives.
- **Effort:** S to send; L to resolve.
- **Unblocks:** the 891 paid-beta rows now sold on interim (York, Lenawee, Eaton, Green) and 253 Albany rows. For the
  admin-only AVAILABLE sources it would unblock 42,797 withheld rows: Detroit 30,602, St. Louis 9,778, Fayette 376,
  Oklahoma 195 and the rest.

  Note the addressee mismatch the tracker already flags. Detroit Enterprise GIS is not the DLBA, the St. Louis
  Assessor is not the LRA, and Fayette GIS is not the Tax Claim Bureau. A reply from the wrong office is not
  permission.

#### B-08. Reconcile registry `governance_status` and code configs with the permission records (code/data consistency)

- **Evidence:** T-8.
  - `data/county_source_registry.csv` says APPROVED for tx_lgbs, tx_realauction, wi_dane, sc_oconee,
    co_morgan_treasurer_deed_auctions and the 16 owner-accepted or admin-only sources.
  - `harvesters/enrichment/sources.py:77` says co_oit is `publication_status="APPROVED"`.
- **Who:** the owner, to choose the relabel vocabulary. Engineering then makes the data change and adds the
  consistency test.
- **Effort:** S–M.
- **Unblocks:** one source of truth. Today `effective_publication()` would publish a source the permission record
  has not cleared, as soon as a review sets APPROVED.
- **Overlap:** PR #158 (unmerged) covers the register reconciliation but not the registry `governance_status`.

#### B-09. Tie the boundary display grant to the permission record (code enforcement gap)

- **Evidence:** T-5. `scripts/migrations/034_parcel_boundaries.sql:35,54-66,153,160` has a static `display_approved`
  that nothing recomputes.
- **Who:** engineering.
- **Effort:** S–M.
- **Unblocks:** honours the FL expiry (2027-10-20), the UT expiry (2027-10-12) and the UT attribution condition on
  the customer read.

#### B-10. Browser map and imagery providers: record terms, replace the Google Demo Key (legal; enforcement gap)

- **Evidence:**
  - T-6. `public/app.js:1732-1752`, `2301-2304` and `8800`, and `public/satellite-map.js:156-163`, `447` and `667`.
  - Pre-sale blockers 7 and 8. Google documents the Demo Key as testing-only, and it is not domain-restricted.
  - MapTiler's free-plan commercial use and the OSMF tile policy are unconfirmed.
- **Who:**
  - the owner: a production Google key and plan, or drop the Google basemap and static fallback;
  - counsel: the MapTiler plan and the OSM policy;
  - engineering: permission records plus a config gate.
- **Effort:** S (engineering) + external.
- **Unblocks:** a compliant basemap and static imagery on every property page.
- **Overlap:** PR #158 (unmerged) reports these sources but does not enforce anything.

#### B-11. Owner-name policy (legal)

- **Evidence:** pre-sale blocker 6. Owner names are written by the FL lists (`scripts/laft_source_fields.py`), the
  LienHub and RealAuction syncs, FDOR (`scripts/enrich_property_details.py:1266-1267`), co_oit and the expansion
  adapters (`harvesters/otc/adapters/expansion.py:63,88,100,173,224`). They are displayed and exported (T-1).
  - LienHub owner mailing addresses are stored as `address`.
  - The DOR PTO approval explicitly excludes owner names.
- **Who:** counsel, then the owner, then engineering.
- **Effort:** M.
- **Unblocks:** `personal_info`, which is NOT_RECORDED for every listing source in the matrix.

#### B-12. Fix the paid-tier condition and gate the CO paid-beta flip in code (code enforcement gap)

- **Evidence:** T-7. `harvesters/governance/permissions.py:335-336` is vacuous for an enrichment source.
- **Who:** engineering.
- **Effort:** S.
- **Unblocks:** prevents a one-line data edit to `data/paid_beta_sources.csv` from selling co_oit-derived fields
  whose terms forbid resale (141 Douglas/Morgan rows).

#### B-13. Resolve the scraping-method decisions (pre-sale blocker 4) (legal)

- **Evidence:** permission records LEGAL_REVIEW_REQUIRED/interim for these methods:
  - the Orange disclaimer click-through;
  - the Volusia disclaimer bypass (county record);
  - the Osceola browser JSON API;
  - the ScraperAPI `fetch_via_proxy` on `fl_laft_html`.
- **Who:** counsel, then the owner.
- **Effort:** M.
- **Unblocks:** 3 Orange rows, 10 Osceola rows, Volusia's share of the 15 `fl_laft_pdfs` rows, and the proxied
  `fl_laft_html` counties.

#### B-14. Record the federal and minor county services' terms (missing evidence)

- **Evidence:** census_geocoder, fema_nfhl, fl_santa_rosa_parcels, fl_palm_coast_flagler_parcels and
  fl_bid4assets_okaloosa are all UNKNOWN/GRANDFATHERED with terms never read (pre-sale blocker 18).
- **Who:** engineering reads the published terms and drafts records. Counsel confirms where needed.
- **Effort:** S–M.
- **Unblocks:** documented records for the federal sources, which are likely public-domain US Government works, but
  that must be read rather than assumed. Converting them reduces the 2027-04-12 cliff.

#### B-15. Publish the missing registry rows to the live table, and fill the blank `ledgers` (data drift)

- **Evidence:** the drift section above. 116 rows are missing live and 61 live rows have blank `ledgers`.
- **Who:** engineering, with owner authorization for a production write.
- **Effort:** S.
- **Unblocks:** per-source health and admin publication reviews for 46 + 32 + 24 auction and certificate rows and
  for the ten admin-only sources.

#### B-16. Link-only record for Dane WI; FDOR attribute scope (housekeeping)

- **Evidence:** T-11. FDOR: `data/source_approvals.csv` `unresolved_mapping` says FGIO `fl_fdor_cadastral` is NOT the
  DOR-covered dataset. It stays interim and is never upgraded by the DOR reply. Utah: the UGRC CC BY 4.0 approval
  excludes Utah tax-sale data, and Utah has no listing source.
- **Who:** engineering (Dane `link` record); the owner (identify the Florida GeoData item named in the DOR reply).
- **Effort:** S.
- **Unblocks:** an honest link-only state for Dane. It also ensures no Utah or FDOR expansion is argued from the
  wrong approval.

### Guardrails restated (from the records; no change proposed)

- Florida DOR PTO permission covers **only** simplified parcel-boundary geometry from the eligible county GIS PIN
  files (dataset `county_parcel_geometry`). It does **not** cover:
  - `fl_fdor_cadastral` (FGIO statewide cadastral);
  - tax-roll (NAL/SDF/PAR) attributes or owner names;
  - tax-sale or auction listings, outcomes or purchase paths.
- UGRC CC BY 4.0 covers UGRC SGID parcel layers only. It does **not** authorize any Utah tax-sale, auction or
  assessor feed.
- `tx_govease`, `tx_pbfcm`, `tx_mvba` and `tx_ctsa` stay BLOCKED in code
  (`harvesters/governance/permissions.py:121-125`, `county_source_registry.BLOCKED_SOURCE_IDS`). Google Street View
  stays BLOCKED.
- An internal risk acceptance or grandfathered practice is never external permission. `PermissionDecision.documented`
  is False for it, and validation refuses APPROVED on such evidence.

## Workstream C: historical auction outcomes (detail)

Draft, to be merged into the combined backlog. The denominators are from `outcome-coverage-baseline.md`
(production, read-only, 2026-10-22):

- FL: 531 past events, of which 257 have outcome `unknown`. 11 of those 257 are verified cancellations (the
  outcome column is `unknown` by design), so **246** FL past events carry no source-stated result.
- TX: 86 past events, 86 unknown.

Every "gain" below is an **upper bound** on events that *could* resolve. None is a forecast: an event resolves
only if the source publishes a mapped wording for it.

Effort: XS < 1 h · S ≈ half a day · M ≈ 1–3 days · L = a week or more, or a per-county effort.

### Ranked items

#### C-1. Detect and report the ten-item closed-listing limit (rank 1)

- **Evidence.**
  - `realauction_results.fetch_area()` stops when a page adds no new item (`fresh == 0`) without setting
    `truncated`, so `DayRead.complete` stays True. The "(listing may be truncated)" note can only print when
    `MAX_PAGES` is reached.
  - `docs/auction-outcomes.md` section 5 records that the anonymous pager returns the same ten items again.
- **Change.**
  - Mark a day `possibly_truncated` when page 2 repeats page 1 and the day already holds ten items.
  - Add `days_possibly_truncated` and `records_per_day` histograms to `out/public/auction-outcomes.json` (counts
    only).
  - Add test C24.
- **Effort:** S.
- **Gain:** 0 events directly. It measures how many of the 246 unresolved FL events sit on days read only in
  part, which is the input to C-2.
- **Permission:** none new. Uses the existing INTERIM `fl_realauction` / `closed_results` record (expires
  2027-04-12).

#### C-2. Read the whole closed listing for a sale day (rank 2)

- **Evidence.**
  - Same as C-1. Counties with many past events and low coverage fit a cut-off at ten items: Volusia 9 of 33,
    Charlotte 18 of 41, Orange 7 of 22, Highlands 7 of 22, Leon 6 of 22, Indian River 2 of 16.
  - This fits the limit but does not prove it until C-1 measures it.
- **Change.**
  1. Run a value-free capture (`job=evidence`, `evidence_scope=auction_results`) of the sale-day page's own pager
     script, which `realauction_results.page_script_snippets()` already prints masked.
  2. From it, identify the call that returns items 11 and later anonymously.
  3. Implement it only if it is the page's own anonymous call: no login and no new host.
- **Effort:** M. It is blocked if no anonymous call exists; in that case record the finding and stop.
- **Gain:** at most the 237 FL 2026-10 past-unknown events of the 257. All of them are still inside the 21-day
  window on 2026-10-22, which covers sale days from 2026-10-01. Subtract the verified cancellations among them
  (at most 11) and every event whose day the reader already reads in full.
- **Permission:** same INTERIM `closed_results` record. The owner should note that the allowance is grandfathered
  practice with no reviewer decision, and that wider reads increase reliance on it.

#### C-3. Test additions that pin current behaviour before changes (rank 3)

- **Evidence.** `validation-and-test-plan.md` items C03, C12 (duplicate case on one day), C18, C19 (corrected
  outcome) and C24. They are marked NEW because no current test pins the behaviour, even though some of it
  already works (C19).
- **Effort:** S.
- **Gain:** 0 events. It prevents regressions in C-1, C-2 and C-4.
- **Permission:** none.

#### C-4. One-off widened-window re-read for aging sale days (rank 4)

- **Evidence.**
  - `auction_outcomes.py --days 21` is the default, and neither the deeds step nor the manual `outcomes` job
    passes a different value.
  - The 2026-09 sale days have left the window: 20 FL past-unknown events.
- **Change.**
  - Add an optional `outcome_days` dispatch input to the manual `outcomes` job, bounded to at most 60.
  - Run it once with `--dry-run`, then for real.
- **Effort:** XS for the code. The run needs owner authorization.
- **Gain:** up to +20 of 257 (2026-09). Each further month that ages out repeats this, so the default may need to
  grow once C-2 lands. This depends on whether the platform still serves those days, which is not measured.
- **Permission:** same INTERIM record.

#### C-5. Counts-only coverage report as a repeatable artifact (rank 5)

- **Evidence.** This baseline was hand-assembled from grouped queries. The 11 / 47 / 198 / 1 lifecycle split and
  the 14 closed-unknown split are derived, not measured.
- **Change.**
  - A read-only SQL file, `scripts/sql/outcome_coverage.sql`, grouped by state, county, month, lifecycle,
    outcome and `raw_status` (no identifiers).
  - A renderer with `--check` pinning `docs/outcome-coverage.md`.
  - It covers test C26 and reports no "sold rate".
- **Effort:** S.
- **Gain:** 0 events. It turns the derived splits into measured ones.
- **Permission:** none (database read).

#### C-6. Texas: establish whether the TX RealAuction sites publish closed results (rank 6)

- **Evidence.**
  - 86 of 86 TX past events are unknown.
  - TX sites are `<county>.texas.sheriffsaleauctions.com` (`data/tx_realauction_counties.csv`), the same
    platform family.
  - Whether `AREA=C` and the status refresh exist there has **not** been read.
- **Change.**
  1. Owner decision first: `tx_realauction` is REVIEW_REQUIRED and the texas job is manual-only.
  2. Then a value-free capture for 2–3 counties.
  3. Then, only on a positive capture, a TX adapter keyed on the CAD account (`case_no`), never the cause number
     (test C13).
  4. Update `test_28_no_lgbs_govease_and_no_new_state` deliberately.
- **Effort:** M.
- **Gain:** up to +86 of 86 TX past events.
- **Permission:** a dataset `*` INTERIM record exists, but use for results needs an explicit owner decision.
  Without one: PERMISSION_UNRESOLVED.

#### C-7. Data-model extension (proposal 7 in the baseline) (rank 7)

- **Evidence.** Migration 014 has no columns for basis, match method, deed recording, postponement target or
  correction / conflict links.
- **Change.**
  - One additive migration (next free number): new nullable columns, the `government_retained` outcome value,
    the `outcome_status` vocabulary.
  - Writers updated to set `basis='REPORTED'` and `match_method` (`EXACT_CASE` or
    `EXACT_CASE_PARCEL_CONFIRMED`).
  - Tests C04, C14, C15, C19, C20.
- **Effort:** M.
- **Gain:** 0 events on its own. It is a prerequisite for C-8 and C-9 and for showing corrections or conflicts
  honestly.
- **Permission:** none. Applying it to production needs the owner's authorization.

#### C-8. Florida clerk tax-deed docket in the highest-unknown counties (rank 8)

- **Evidence.**
  - Eight counties hold 139 of the 257 FL past-unknown events: Volusia 24, Charlotte 23, Duval 16, Lee 16,
    Leon 16, Highlands 15, Orange 15, Indian River 14.
  - A clerk's tax deed file is expected to share the RealAuction "Case #" key, which would allow an
    `EXACT_CASE` join. That expectation is **not verified**.
  - No clerk docket was read (CANDIDATE_UNVERIFIED in the source map).
- **Change.** Per county:
  1. a value-free capture of the public search page;
  2. a terms read;
  3. a `source_permissions.csv` record;
  4. then an adapter.
- **Effort:** L (per county).
- **Gain:** up to +139 of 257, and the first source of `deed_recorded` and `certificate_redeemed`. It overlaps
  with C-2: whatever C-2 resolves first is not double-counted.
- **Permission:** PERMISSION_UNRESOLVED until a record exists for each county.

#### C-9. Expansion-state results into the event tables (rank 9)

- **Evidence.** MI Eaton "Has Been Sold" (5 rows) and WI Green "Previous Sales" with Sale Price (8 rows) live
  only in `properties`, not in `auction_events`.
- **Change.**
  - A writer step that creates events and REPORTED observations from these adapters' own published flags.
  - Amount only from WI's Sale Price. No date for Eaton (it publishes none).
  - Test C28.
- **Effort:** M.
- **Gain:** +13 verified outcomes in event analytics. They are new denominators outside FL and TX, not a
  reduction of the 257.
- **Permission:** INTERIM `mi_eaton_treasurer_sale` and `wi_green_tax_deed_sales` records (owner, expire
  2027-04-12). There is no new fetch.

#### C-10. Deed-recording corroboration from FDOR NAL last-sale fields (rank 10)

- **Evidence.**
  - `scripts/enrich_property_details.py` already requests SALE_PRC1, SALE_YR1, SALE_MO1, QUAL_CD1, OR_BOOK1,
    OR_PAGE1 and CLERK_NO1 on the validated NAL id.
  - Deed confirmation is 0 of 172 sold events today.
- **Change.**
  - Record an INFERRED `deed_recording` observation when a sold event's property shows a transfer dated in or
    after the sale month, with its OR book/page/clerk number.
  - Never set `winning_bid` from it.
  - First verify which QUAL_CD1 value marks a tax deed; otherwise the observation stays "a later transfer was
    recorded".
- **Effort:** M. Depends on C-7.
- **Gain:** up to 172 of 172 sold events could gain an instrument reference, limited by tax-roll lag (not
  measured).
- **Permission:** INTERIM fetch / enrich for `fl_fdor_cadastral` / `parcel_attributes`. There is **no store or
  display record**, so display stays PERMISSION_UNRESOLVED until one is recorded.

#### C-11. Closed-listing wording discovery across all 46 counties (rank 11)

- **Evidence.**
  - The wording table rests on 21 counties × 6 sale days (capture run 36731266591).
  - No struck-off, withdrawn or no-sale wording was ever observed.
  - Some or all of the ≤3 closed observations that are not cancellations carry unmapped wordings.
- **Change.** A value-free capture over all hosts for the in-window days. Add a wording row only with a cited run
  and a verified meaning. "Bidder Walked Away" and "Rescheduled" stay unmapped.
- **Effort:** S.
- **Gain:** ≤3 of 257 directly. It also matters for future struck-off coverage.
- **Permission:** same INTERIM record.

#### C-12. Cross-ledger corroboration of unsold sales from Lands Available / FLC lists (rank 12)

- **Evidence.** In Florida, a county-held certificate's unsold property is expected to move to the Lands
  Available list. That link is cited but not VERIFIED LAW here: only `available_after_sale` is VERIFIED.
- **Constraint.** `docs/auction-outcomes.md` section 4 forbids an Available record manufacturing a failed
  auction.
- **Change.** Only with an owner decision and C-7: an INFERRED, exact-parcel corroboration observation, shown
  apart from the outcome.
- **Effort:** M.
- **Gain:** 0 verified outcomes, by design.
- **Permission:** INTERIM per `fl_laft_*` source.

#### C-13. Certificate redemption records (rank 13)

- **Evidence.** A certificate leaving the LienHub list is `closed`, never `redeemed`. Whether any LienHub or
  tax-collector page publishes a redemption column is unverified.
- **Effort:** M.
- **Gain:** INFERRED corroboration of `redeemed` only, matched by `EXACT_CERTIFICATE`.
- **Permission:** PERMISSION_UNRESOLVED. The existing record covers `county_held_certificates` only.

#### C-14. Okaloosa (Bid4Assets) results (rank 14)

- **Evidence.** There are 0 Okaloosa auction events, and the permission records cover `sale_calendar` only.
- **Gain:** 0 today.
- **Permission:** PERMISSION_UNRESOLVED.
- **Note:** Park this until Okaloosa events exist and the Bid4Assets terms are read.

### Never in scope

- Purchaser or bidder identity, bidder count, win rates.
- Any LGBS, GovEase, PBFCM, MVBA or CTSA read for outcomes.
- An outcome from absence, a passed date, an opening bid, a deed consideration or a value field.
- Rebuilding sales before 2026-09-28.
