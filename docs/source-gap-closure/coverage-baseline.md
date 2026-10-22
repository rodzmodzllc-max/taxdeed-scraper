# Workstream A: listing coverage and freshness baseline

Measured 2026-10-22 at about 17:25 UTC. These are read-only, counts-only reads of the production `properties` table and `county_source_registry` table, saved under [`baseline/`](baseline/). There are 60,025 property rows in 133 state × source × county units.

This document records what was measured on that day. Use the other documents for related views:

- [`docs/state-coverage.md`](../state-coverage.md): the classification for each state × ledger.
- [`docs/gap-queue.md`](../gap-queue.md): the queue of acquisition-path and rules work.
- [`docs/source-quality-matrix.md`](../source-quality-matrix.md) (snapshot 2026-10-10): per-source quality and defect counts.

Do not copy those documents' content into this one. Compare with them instead.

The companion files are:

- [`county-source-map.csv`](county-source-map.csv): one row per state × county × source × ledger. The rows come from the repository registry, are joined to the live registry and the measured rows, and include 3 orphan units.
- [`field-availability-matrix.csv`](field-availability-matrix.csv): one row per source × ledger × field. A field is marked CAPTURED only where the harvester, sync or writer code maps it.

**A listing that is missing proves nothing about a sale, redemption or cancellation.** A row can leave a list, never be stamped, or go stale for several reasons: the source failed, the source was not read, the list was superseded, or the record was redeemed, sold or cancelled. The repository's own rule is the same: absence is `closed` or `removed`, never `sold` (`harvesters/governance/inventory_status.py`; `docs/auction-outcomes.md`). Every number below describes TAXACQ's observation of a listing. None of them describes what happened to the property.

## 1. Per state × ledger

Definitions used in the table:

- **Active**: the row's status is `active` or `available`.
- **Stale > 14 d**: an active row whose `last_seen_at` is more than 14 days old.
- **Never stamped**: an active row whose `last_seen_at` is NULL.

Fill shares are taken over all rows, not only active ones.

\* The address fill is inflated. When a source publishes no address, the syncs write placeholder text: `"Address not published - see county PDF"`, `"Parcel <n>"` and `"Case <n>"` (`scripts/sync-laft-to-supabase.ps1:220-225`), and `"Account <n>"` (`scripts/sync-texas-to-supabase.py:295`). So 100% does not mean every row has a published address.

| State | Ledger | Sources | Counties | Rows | Active | Stale > 14 d | Never stamped | Parcel | Address* | Point | Legal | Sale date | Amount | Link | Publication approved† / other / NULL |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CO | Liens & Certificates | 2 | 2 | 146 | 141 | 0 | 0 | 100% | 100% | 82% | 82% | 0% | 100% | 100% | 146 / 0 / 0 |
| FL | Auctions | 1 | 43 | 2,644 | 1,065 | 37 | 146 | 97% | 100% | 89% | 76% | 100% | 100% | 100% | 0 / 0 / 2,644 |
| FL | Liens & Certificates | 1 | 26 | 1,667 | 1,611 | 0 | **1,611** | 100% | 100% | 53% | 34% | 0% | 100% | 100% | 0 / 0 / 1,667 |
| FL | Available | 9 | 25 | 172 | 158 | 1 | 3 | 98% | 100% | 88% | 88% | 88%‡ | 87% | 100% | 172 / 0 / 0 |
| LA | Available | 1 | 1 | 10,334 | 10,334 | 0 | 0 | 100% | 100% | 100% | 81% | 0% | 0% | 100% | 10,334 / 0 / 0 |
| MI | Auctions | 2 | 2 | 43 | 38 | 0 | 0 | 100% | 100% | 100% | 100% | 88% | 100% | 100% | 43 / 0 / 0 |
| MI | Available | 3 | 3 | 30,847 | 30,607 | 12 | 0 | 100% | 100% | 100% | 0% | 0% | 0% | 100% | 0 / 30,847 / 0 |
| MN | Available | 1 | 1 | 2 | 2 | 0 | 0 | 100% | 100% | 100% | 100% | 0% | 100% | 100% | 0 / 2 / 0 |
| MO | Available | 1 | 1 | 9,778 | 9,778 | 0 | 0 | 100% | 100% | 4% | 100% | 0% | 0% | 100% | 0 / 9,778 / 0 |
| OK | Available | 1 | 1 | 195 | 195 | 0 | 0 | 100% | 100% | 0% | 100% | 0% | 100% | 100% | 0 / 195 / 0 |
| PA | Available | 1 | 1 | 376 | 376 | 0 | 0 | 100% | 100% | 0% | 100% | 0% | 100% | 100% | 0 / 376 / 0 |
| SC | Auctions | 1 | 1 | 853 | 853 | 0 | 0 | 100% | 100% | 100% | 100% | 0% | 0% | 100% | 853 / 0 / 0 |
| SC | Available | 2 | 2 | 52 | 52 | 0 | 0 | 100% | 100% | 0% | 100% | 0% | 100% | 100% | 0 / 52 / 0 |
| TN | Available | 1 | 1 | 2,111 | 1,787 | 0 | 0 | 100% | 100% | 100% | 0% | 0% | 100% | 100% | 0 / 2,111 / 0 |
| TX | Auctions | 2 | 13 | 122 | 122 | 0 | **122** | 100% | 100% | 69% | 8% | 100% | 100% | 84% | 0 / 0 / 122 |
| TX | Available | 1 | 8 | 421 | 421 | **382** | 39 | 100% | 100% | 100% | 56% | 0% | 95% | 0% | 421 / 0 / 0 |
| WI | Auctions | 1 | 1 | 9 | 0 | 0 | 0 | 100% | 100% | 44% | 0% | 100% | 100% | 100% | 9 / 0 / 0 |
| WY | Auctions | 1 | 1 | 253 | 253 | 0 | 0 | 100% | 100% | 100% | 100% | 0% | 100% | 100% | 253 / 0 / 0 |
| **All** | | | 133 units | **60,025** | **57,793** | **432** | **1,921** | | | 48,873 | 22,990 | 2,964 | 8,166 | 59,585 | 12,231 / 43,361 / 4,433 |

† "Approved" counts APPROVED and APPROVED_GRANDFATHERED. "Other" is UNREVIEWED.
‡ For Florida Available rows, the sale date is the original tax-deed sale date, not an upcoming auction.

Read health per unit comes from the live `county_source_registry` (121 rows):

| State | COMPLETE | EMPTY | FAILED | INCOMPLETE | No attempt recorded |
|---|---|---|---|---|---|
| FL (Available) | 22 | 18 | 7 | 5 | 0 |
| LA, MI, SC, WI, WY, CO | 8 | 1 | 0 | 0 | 3 (`co_morgan_treasurer_deed_auctions`, `sc_oconee_tax_sale_list` and `wi_dane_tax_deed_auction`: these are UNREVIEWED auction sources, gated before any request) |
| TX (`tx_lgbs`) | 0 | 0 | 0 | 0 | 8 (manual-only) |

## 2. What the notable facts mean, from the repository's own records

- **All 1,611 active FL certificate rows have never been stamped.**
  - LienHub has answered HTTP 403 to the GitHub runner since 2026-10-01 (`docs/gap-queue.md` §D).
  - `stamp_seen.py --status` stamps only counties whose status file is COMPLETE or EMPTY (CLAUDE.md "Data-quality fixes before merge"). So these rows have not been re-read since then.
  - 22 of the 26 counties' rows were last updated on 2026-09-30. The other 4 (Escambia, Miami-Dade, Osceola, Volusia) were updated later, but `updated_at` moves on any PATCH, including enrichment, so it is not evidence of a read.
  - Six registered LienHub counties hold 0 rows: Brevard, Clay, Collier, Indian River, Lee and Pinellas.
- **382 of 421 Texas Available rows are stale by more than 14 days, and 39 have never been stamped.** Texas is manual-only by design: the `texas` job is `workflow_dispatch` only, and `unit_freshness.MANUAL_ONLY_SOURCES` never ages a Texas unit by the clock (CLAUDE.md "Texas is manual-only by design"). The last attested read was on 2026-10-02.
- **All 122 Texas Auction rows have never been stamped, and their `inventory_status` is NULL.**
  - `sync-texas-to-supabase.py` writes no `last_seen_at` and has no close-out step. The FL deed close-out is scoped `state=eq.FL`.
  - The 2026-10-10 snapshot already counted all 122 active rows past their sale date (`docs/current-state-coverage.md`). Today's past-sale count is not in this baseline.
  - 13 of the 24 registered `tx_realauction` counties hold 0 rows.
- **No FL Auction row has a `publication_status` (0 approved, 2,644 NULL).** The same is true of FL Liens (1,667 NULL) and TX Auctions (122 NULL).
  - `scripts/publication_gate.py` propagates `publication_status` for the AVAILABLE ledger only (lines 2 and 133-134). NULL "keeps today's behaviour" (CLAUDE.md "AVAILABLE commercialization").
  - Migration 031 makes a row with NULL `publication_state` invisible to customers. CLAUDE.md records 031 as NOT applied; that was not re-checked here.
  - Applying 031 before `publication_state_writer.py` has run for these ledgers would hide 4,433 rows from customers.
- **FL Auctions has 146 active rows that have never been stamped and 37 that are stale by more than 14 days.** This matches the documented "off the county's current sale list" mechanism (CLAUDE.md, 2026-10-06): a row with a future sale date that leaves the Waiting feed is never closed, because the close-out only acts after the sale day. This was not verified per row.
- **43,361 Available rows (42,797 active) belong to UNREVIEWED sources.** These are MI (30,847), MO (9,778), TN (2,111), PA (376), OK (195), SC (52) and MN (2). They are collected for admins, and customers do not see them until an admin publication review exists (CLAUDE.md "collection vs customer publication").
- **The live registry is missing 116 of the 237 repository registry rows.**
  - Missing rows: `fl_realauction` (46), `fl_lienhub_certificates` (32), `tx_realauction` (24), and the 10 Available sources added after migration 018 (Detroit ×2, Oceana, MO, OK, PA, MN, TN, Horry, Georgetown). Also missing are `fl_bid4assets_okaloosa` and the AL, AR and AZ candidate rows.
  - `scripts/unit_freshness.py` only PATCHes existing rows (`RegistryApi.patch`), so these units can never record a last attempt or last success.
  - In the rows that are present, `ledgers` is NULL in 92 rows and `update_frequency` is NULL in 60. `last_error_category` is NULL in every row, including the 7 FAILED ones.

## 3. Largest verified gaps (state × ledger × county)

These are listing-coverage and freshness gaps only. Each count is taken from `baseline/` or the repository registry. The ranked fixes are in [`prioritized-remediation-backlog.md`](prioritized-remediation-backlog.md).

| # | Gap | Numbers |
|---|---|---|
| 1 | FL Liens & Certificates: no read since LienHub started refusing the runner | 1,611 active rows never stamped. Largest counties: Santa Rosa 480, Volusia 228, Miami-Dade 193, Duval 122, Pasco 112, Alachua 100, Sarasota 93, Hillsborough 82. 6 registered counties hold 0 rows. |
| 2 | TX Auctions: manual-only, never stamped, no close-out | 122 active rows never stamped in 11 `tx_realauction` counties plus 2 `tx_lgbs` counties (Concho 9, Galveston 10). 13 of 24 registered RealAuction counties hold 0 rows. |
| 3 | TX Available: manual-only, stale | 382 of 421 stale by more than 14 days, and 39 never stamped. By county: Galveston 144 stale + 39 never, Liberty 113, Leon 84, Maverick 14, Jim Wells 11, Hardin 9, Van Zandt 6, Goliad 1. |
| 4 | FL Auctions: rows off the feed and counties not read | 146 never stamped and 37 stale. Largest: Lee 28 + 8, Hillsborough 21 + 11, Broward 21 + 1, Orange 17 + 3, Manatee 14 + 0. 5 registered RealAuction counties hold 0 rows (Calhoun, Gulf, Monroe, Okeechobee, St. Johns), and so does the Okaloosa Bid4Assets source. 20 of 67 FL counties have no auction source in the registry. |
| 5 | FL Available: units whose reads fail | 12 of 52 production units fail.<br>• FAILED (7): Brevard 22 consecutive failures, Hendry 22, Columbia 10, Escambia 10, Union 10, Pasco 9, Manatee 5.<br>• INCOMPLETE with no success ever recorded (5): Franklin, Gulf, Hamilton, Holmes, Taylor.<br>15 of 67 FL counties have no production Available source (`county-source-map.csv`). |
| 6 | Orphan units (rows with no registry row for the county × source) | FL Collier `fl_realauction` (1 row, 0 active). FL DeSoto `fl_realauction` (9 rows, 4 active and never stamped). TX Concho `tx_lgbs` auction (9 rows, all active and never stamped). No read can close these rows. |
| 7 | Field gaps on rows already listed | Coordinates are missing on 195 OK, 376 PA and 52 SC Available rows, and MO has them on only 412 of 9,778. Legal descriptions are missing on all 30,847 MI Available rows and 2,111 TN rows (their adapters map none), and present on only 563 of 1,667 FL certificates and 10 of 122 TX auctions (TX RealAuction publishes none: `texas_harvester.py:389`). |

Coverage of states and ledgers that have no source at all (RULES_NOT_VERIFIED and similar) is tracked in `docs/state-coverage.md` and `docs/gap-queue.md` §C/F. It is not repeated here.

## 4. How to reproduce

The query below is the exact read-only query that produced `baseline/by_county.json` (2026-10-22, about 17:25 UTC). It returns counts and dates only. Definitions it uses:

- "active" = `status in ('active','available')`;
- "with amount" = a positive `bid` or a positive `purchase_amount`;
- "publication approved" = `publication_status like 'APPROVED%'`.

```sql
select state, source as ledger_source, coalesce(source_id, harvester_source) as src, county,
 count(*) total, count(*) filter (where status in ('active','available')) active,
 count(*) filter (where status not in ('active','available')) inactive,
 max(last_seen_at) last_seen, max(updated_at) last_updated, max(list_as_of) list_as_of,
 count(*) filter (where coalesce(btrim(parcel),'')<>'') with_parcel,
 count(*) filter (where coalesce(btrim(address),'')<>'') with_address,
 count(*) filter (where latitude is not null) with_point,
 count(*) filter (where sale_date is not null) with_sale_date,
 count(*) filter (where coalesce(bid,0)>0 or coalesce(purchase_amount,0)>0) with_amount,
 count(*) filter (where coalesce(btrim(legal_desc),'')<>'') with_legal,
 count(*) filter (where coalesce(btrim(url_auction),'')<>'') with_url,
 count(*) filter (where publication_status like 'APPROVED%') pub_approved,
 count(*) filter (where publication_status is null) pub_null,
 count(*) filter (where last_seen_at < now() - interval '14 days' and status in ('active','available')) active_stale14,
 count(*) filter (where last_seen_at is null and status in ('active','available')) active_never_seen
 from public.properties group by 1,2,3,4 order by 1,2,3,4;
```

The registry snapshot is:

```sql
select state, county, source_id, ledgers, verification_status, governance_status, publication_status,
       access_method, machine_format, last_success_at, last_attempt_status, last_success_row_count,
       consecutive_failures, last_error_category, update_frequency
from public.county_source_registry;
```

The two CSVs were generated once from `baseline/`, `data/county_source_registry.csv` and the cited harvester lines. They are a dated snapshot, not generated files: re-measure with the queries above before relying on a count. Making them reproducible (a `scripts/build_*.py --check` pair, like `scripts/build_state_coverage.py`) is backlog item A in `prioritized-remediation-backlog.md`.
