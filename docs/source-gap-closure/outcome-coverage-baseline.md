# Historical auction outcomes: coverage baseline (Workstream C)

Measured 2026-10-22 at about 17:25 UTC with read-only queries against production. The inputs are in
`baseline/`:

- `outcomes.json`: `auction_events` grouped by state, source, county and sale month.
- `outcome_values.json`: (outcome, lifecycle) counts.
- `observations.json`: `auction_event_observations` grouped by feed and outcome.
- `inventory_status.json` and `by_county.json`: context from `properties`.

Every number below comes from those files. Numbers marked **derived** were computed from them, and the method is
stated with each one. No count was estimated.

**What this report is not.**
- **It is not a sold rate.** Outcome coverage measures how many past events carry a result the source published.
  Unknown events are not unsold, so a ratio such as "sold / past events" is not a market sold rate.
- **Win-rate or bidder analytics are not possible.** They need the bidder's identity and auction-level results
  (every bid, the bidder count). No source here publishes those per bidder. The repository also forbids storing
  purchaser or bidder identity:
  - `auction_events.winning_bidder_ref` must stay NULL (migration 014).
  - `bid_count` and `winning_bidder_ref` are on the forbidden-patch list in `scripts/auction_outcomes.py`.
  - RealAuction's published purchaser *category* (`ST`, e.g. "3rd Party Bidder") is never read into a record
    (`test_18_19_bid_count_and_bidder_are_never_written`).

  This report keeps those rules.

## 1. Scope and history window

- **Event history starts 2026-09-28.** The first `waiting` observation is 2026-09-28 17:56 UTC, and the first
  closed-feed result 2026-09-30 14:58 UTC. Sale months present: 2026-09 to 2026-12. Earlier sales have no event
  row and are not rebuilt (`docs/auction-outcomes.md` section 5). The 2026-09-25 audit counted 876 FL auction
  rows with a past sale date and no outcome; these are outside the event model.
- **Totals:** 1,575 events. FL has 1,489 events in 41 counties (34 with past events). TX has 86 events, all
  `tx_realauction`, in 11 counties, all in 2026-10 and all past.
- **No events exist for:** Okaloosa (Bid4Assets), Texas LGBS, or any expansion state (MI, WI, WY, SC, CO). The
  expansion states' published results (Eaton MI "Has Been Sold", Green WI "Previous Sales") are written to
  `properties`, not to the event tables (section 6).

## 2. Coverage by state

Denominators:
- "Past" means the scheduled sale date is before 2026-10-22.
- "With outcome" means `outcome` is `sold` or `redeemed`.
- Winning bid is shown as a share of sold events.

| State | Events | Past events | Outcome stated by source (sold / redeemed) | Sold | Redeemed | Past, outcome unknown | Winning bid / sale amount |
|---|---|---|---|---|---|---|---|
| FL | 1,489 | 531 | 274 (51.6% of 531) | 172 | 102 | 257 (48.4% of 531) | 172 (100% of 172 sold) |
| TX | 86 | 86 | 0 (0% of 86) | 0 | 0 | 86 (100% of 86) | 0 |
| **Total** | 1,575 | 617 | 274 (44.4% of 617) | 172 | 102 | 343 (55.6% of 617) | 172 |

Other columns the brief asked for, all with denominator 617 past events:

| Measure | FL (of 531 past) | TX (of 86 past) | Basis |
|---|---|---|---|
| Verified cancellation (source wording "Canceled per County" / "Canceled per Bankruptcy") | 11 **derived** | 0 | `outcome_values.json` unknown/cancelled = 11. Only the closed-feed reader writes `cancelled`, and it reads FL only. |
| Any source-stated result (sold + redeemed + cancelled) | 285 **derived** (53.7%) | 0 | 274 + 11 |
| Verified redemption | 102 (19.2%) | 0 | outcome `redeemed`, all lifecycle `cancelled` |
| Verified winning bid / sale amount | 172 (32.4% of past; 100% of sold) | 0 | `winning_bid` is set only when the item prints "Amount" beside a money value |
| Deed-record confirmation | **0** | **0** | No deed-recording source is read. No column in migration 014 holds a recording instrument (section 7). |
| Blocked by permission | 0 | 0 read / 86 not attempted | FL closed results hold an INTERIM allowance. TX has no outcome reader: the `tx_realauction` interim record covers dataset `*`, but the source is REVIEW_REQUIRED and the texas job is manual-only. Extending it needs an owner decision; nothing was denied at run time. |
| Source unavailable (failed day reads) | not in this baseline | n/a | Counted per run in `out/public/auction-outcomes.json` (`days_unavailable`). That artifact was not part of the baseline. |

## 3. Coverage by sale month

| State, month | Events | Past events | Sold / redeemed | Sold | Redeemed | Past unknown | Winning bid |
|---|---|---|---|---|---|---|---|
| FL 2026-09 | 61 | 61 | 41 (67.2%) | 38 | 3 | 20 (32.8%) | 38 |
| FL 2026-10 | 676 | 470 | 233 (49.6%) | 134 | 99 | 237 (50.4%) | 134 |
| FL 2026-11 | 478 | 0 | – | 0 | 0 | 0 | 0 |
| FL 2026-12 | 274 | 0 | – | 0 | 0 | 0 | 0 |
| TX 2026-10 | 86 | 86 | 0 (0%) | 0 | 0 | 86 (100%) | 0 |

**September events are already outside the 21-day window.** `scripts/auction_outcomes.py` reads only sale days
within 21 days of the run (`--days 21`). On 2026-10-22 that covers sale days from 2026-10-01 on, so every
2026-09 sale day is no longer re-read. The 20 unknown FL September events stay unknown unless the window is
widened for one run, and only if the source still serves those days (not measured).

## 4. Coverage by county (every county with past events)

Sorted by past events. Percentages use that county's past events as the denominator.

| County | Events | Past | Sold / redeemed | Sold | Redeemed | Past unknown | Winning bid |
|---|---|---|---|---|---|---|---|
| FL Charlotte | 77 | 41 | 18 (43.9%) | 14 | 4 | 23 | 14 |
| FL Volusia | 69 | 33 | 9 (27.3%) | 3 | 6 | 24 | 3 |
| FL Putnam | 52 | 31 | 29 (93.5%) | 28 | 1 | 2 | 28 |
| FL Lee | 104 | 29 | 13 (44.8%) | 10 | 3 | 16 | 10 |
| FL Duval | 32 | 27 | 11 (40.7%) | 9 | 2 | 16 | 9 |
| FL Bay | 47 | 23 | 15 (65.2%) | 7 | 8 | 8 | 7 |
| FL Highlands | 75 | 22 | 7 (31.8%) | 6 | 1 | 15 | 6 |
| FL Hillsborough | 116 | 22 | 12 (54.5%) | 1 | 11 | 10 | 1 |
| FL Leon | 36 | 22 | 6 (27.3%) | 2 | 4 | 16 | 2 |
| FL Orange | 90 | 22 | 7 (31.8%) | 1 | 6 | 15 | 1 |
| FL Marion | 42 | 21 | 9 (42.9%) | 6 | 3 | 12 | 6 |
| FL Washington | 71 | 20 | 17 (85.0%) | 15 | 2 | 3 | 15 |
| FL Hernando | 33 | 19 | 7 (36.8%) | 5 | 2 | 12 | 5 |
| FL Jackson | 47 | 19 | 13 (68.4%) | 13 | 0 | 6 | 13 |
| FL Polk | 32 | 18 | 8 (44.4%) | 1 | 7 | 10 | 1 |
| FL Indian River | 24 | 16 | 2 (12.5%) | 2 | 0 | 14 | 2 |
| FL Palm Beach | 39 | 16 | 5 (31.2%) | 4 | 1 | 11 | 4 |
| FL Escambia | 35 | 14 | 4 (28.6%) | 2 | 2 | 10 | 2 |
| FL Pinellas | 28 | 14 | 7 (50.0%) | 1 | 6 | 7 | 1 |
| FL Miami-Dade | 21 | 12 | 10 (83.3%) | 3 | 7 | 2 | 3 |
| FL Osceola | 22 | 12 | 8 (66.7%) | 1 | 7 | 4 | 1 |
| FL Citrus | 22 | 11 | 8 (72.7%) | 7 | 1 | 3 | 7 |
| FL Martin | 11 | 11 | 6 (54.5%) | 6 | 0 | 5 | 6 |
| FL St. Lucie | 23 | 11 | 6 (54.5%) | 1 | 5 | 5 | 1 |
| FL Suwannee | 9 | 9 | 6 (66.7%) | 4 | 2 | 3 | 4 |
| FL Clay | 26 | 8 | 7 (87.5%) | 5 | 2 | 1 | 5 |
| FL Seminole | 24 | 8 | 5 (62.5%) | 1 | 4 | 3 | 1 |
| FL Alachua | 17 | 6 | 6 (100%) | 5 | 1 | 0 | 5 |
| FL Nassau | 9 | 4 | 4 (100%) | 3 | 1 | 0 | 3 |
| FL Pasco | 28 | 4 | 4 (100%) | 4 | 0 | 0 | 4 |
| FL Santa Rosa | 13 | 3 | 2 (66.7%) | 1 | 1 | 1 | 1 |
| FL Baker | 1 | 1 | 1 (100%) | 1 | 0 | 0 | 1 |
| FL Manatee | 52 | 1 | 1 (100%) | 0 | 1 | 0 | 0 |
| FL Walton | 10 | 1 | 1 (100%) | 0 | 1 | 0 | 0 |
| TX Atascosa, Cameron, Dallas, Galveston, Matagorda, Nueces, Smith (each) | 10 | 10 | 0 | 0 | 0 | 10 | 0 |
| TX Llano | 6 | 6 | 0 | 0 | 0 | 6 | 0 |
| TX Victoria | 4 | 4 | 0 | 0 | 0 | 4 | 0 |
| TX Caldwell, Travis (each) | 3 | 3 | 0 | 0 | 0 | 3 | 0 |

**Future events only:** FL Brevard (31), Broward (47), Flagler (1), Gilchrist (8), Hendry (12), Lake (27) and
Sarasota (26).

**Largest unknown counts in FL:** Volusia 24, Charlotte 23, then Duval, Lee and Leon at 16 each, Highlands and
Orange at 15, and Indian River at 14. Together these eight counties hold 139 of the 257 FL past-unknown events.

## 5. Why outcomes stay unknown (explained from the code)

### 5.1 The 257 FL past-unknown events, by lifecycle (derived)

How the split was derived:
- `outcome_values.json` gives unknown/scheduled = 1,044. FL has 958 future events (1,489 − 531), and the 86 TX
  events stay `scheduled` (the Phase B writer applies neither completion nor supersession to Texas). 958 + 86 =
  1,044.
- So every FL past-unknown event has a non-scheduled lifecycle: 11 + 47 + 198 + 1 = 257, which matches the FL
  total exactly.

A grouped `state, lifecycle, outcome` query on past events would confirm this. That query was not part of the
baseline.

| Lifecycle (outcome `unknown`) | Events | What it means (scripts/auction_events_writer.py, scripts/auction_outcomes.py) |
|---|---|---|
| `cancelled` | 11 | **These are verified results.** "Canceled per County" and "Canceled per Bankruptcy" map to `RESULTS["cancelled"] = ("unknown", "cancelled")`, so the outcome column stays `unknown` *by design*, and `outcome_raw` carries the wording. `is_verified()` treats them as results and the UI shows "Cancelled - verified". They are "unknown" only in the outcome column. |
| `completed` | 47 | The event writer saw the item on the Waiting feed on or after its sale day, and a later COMPLETE county read no longer listed it (`lifecycle_after_absence`). That is migration 014's definition of `completed`, with the outcome still unknown. The closed-feed reader then found **no mapped result** for it, for one of these reasons: (a) the listing stopped at its first ten items (section 5.3); (b) the item carried an unmapped wording or no wording, which counts as "checked, not published"; (c) the day read failed (nothing written); (d) no item matched the case number exactly, or the parcel disagreed; (e) the sale day had already left the 21-day window. |
| `unknown` | 198 | The listing left the Waiting feed **before** its sale day. Withdrawn, postponed, redeemed before the sale or corrected cannot be told apart from absence, so none is claimed. Redemptions before the sale do appear in the closed listing as "Redeemed", so these events can still resolve, but only if the item is within the ten the listing returns. |
| `superseded` | 1 | Re-listed under a new date while the old date was still in the future. The new date is its own event. |

### 5.2 The 14 closed-feed observations with outcome `unknown`

`observations.json` holds 14 `feed='closed'` rows with outcome `unknown`, written between 2026-10-02 and
2026-10-22. Two code paths write such a row:

1. **A verified cancellation.** `_obs()` writes the lifecycle `cancelled` with outcome `unknown`, because that is
   how `RESULTS["cancelled"]` is stored. There are 11 cancelled events, and the reader appends a result
   observation only when the event's state changes. So **11 of the 14 are expected to be these cancellation
   observations** (derived; not split by lifecycle in the baseline).
2. **"Checked, not published".** The status wording is empty, or is not a row in
   `data/auction_outcome_wordings.csv`. That covers "Bidder Walked Away", "Auction to be rescheduled" and
   "Rescheduled", as `data/auction_outcome_wordings_unmapped.md` explains. The wording is kept verbatim in
   `raw_status`, and the customer sees "Outcome not yet verified" with the wording quoted, or "Outcome not
   published" when there is no wording.

   Such a row is written once per change: an unchanged re-check appends nothing
   (`test_21b_an_unchanged_recheck_appends_nothing`), and it is never written over a verified result. The
   remaining **≤3** observations are of this kind.

A query on `auction_event_observations` grouped by `feed, lifecycle, raw_status`, restricted to `feed='closed'`,
would confirm the split. It returns counts and published wordings only, no identifiers.

### 5.3 The ten-item listing limit, and why runs do not report it

`docs/auction-outcomes.md` section 5 documents that the closed listing pages at ten items, and that the
anonymous pager (`PageDir=1&doR=0`) returns the same ten again.

`realauction_results.fetch_area()` stops when a page adds no new item (`fresh == 0`). It sets `truncated` only
when it reaches `MAX_PAGES` (12). In the repeated-page case it never sets it, so:
- `DayRead.complete` stays `True`;
- the run log's "(listing may be truncated)" note never prints;
- every sale day with more than ten closed or canceled items is silently read in part.

This is likely the largest single cause of the 47 + 198 unresolved events. It is not proven: the per-day record
counts are in the job log and the counts-only report, not in this baseline. A dry run of the reader would
measure it, by counting days whose read returned exactly ten records.

### 5.4 Texas: 86 of 86 unknown

- No outcome reader exists for Texas. `scripts/auction_outcomes.py` queries `state=eq.FL` only, and
  `test_28_no_lgbs_govease_and_no_new_state` pins that.
- The Phase B writer does not apply completion to Texas, so all 86 events stay `scheduled` past their dates.
- The texas harvest is manual-only, so no later Waiting-feed read has happened since these events were recorded.
- Texas `parcel` is the tax-suit cause number. Any future matcher must key on the CAD account (`case_no`).

## 6. Results recorded outside the event tables

| Source | Published result | Where it lives | Rows (baseline) |
|---|---|---|---|
| `mi_eaton_treasurer_sale` | Layer flag "Has Been Sold" (no amount, no date) | `properties.inventory_status = 'sold'` | 5 MI auction rows |
| `wi_green_tax_deed_sales` | "Previous Sales" table with Sale Price and sale date | `properties` (`inventory_status 'sold'`, `result_amount`) | 8 WI auction rows (1 more WI row `closed`) |
| FL Lands Available "Sold To" rows | Lands Available purchase, not an auction result | Available ledger (`inventory_status 'sold'`) | not in this baseline |

These results never reach `auction_events`, so per-event analytics miss them. The 5 MI and 8 WI results are
**not** included in any denominator above.

## 7. Data-model proposal (PROPOSAL ONLY - no migration file)

**Goal:** record deed recording, struck-off / government-retained, postponement history, provenance and
corrections in migration 014's two tables. The constraints:
- `properties` is untouched;
- the three ledgers stay separate (`harvesters/ledgers/records.py`);
- no purchaser or bidder identity is stored;
- every write is additive and append-only.

It would be written as a new migration (next free number) after an owner decision, and applied only with
explicit authorization, in the same way as 014 to 035.

### 7.1 `auction_event_observations`: additive columns (all nullable; the table stays insert-only)

| Column | Type | Meaning |
|---|---|---|
| `source_id` | text | Registry source id (e.g. `fl_realauction`), so a permission record maps to every observation. |
| `source_record_url` | text | The property-specific record the fact came from (item, docket entry, instrument page). `evidence_url` stays the page that was read. Both are https and never a search engine or a homepage (`evidence_refusal`). |
| `retrieved_at` | timestamptz | When the bytes were fetched. `observed_at` stays the run's stamp. They can differ for a delayed or cached read. |
| `basis` | text CHECK in (`REPORTED`, `INFERRED`) | REPORTED means the source published the fact for this record. INFERRED means derived from another record (e.g. a Lands Available listing after the sale date). Today's `derived` feed rows are INFERRED. Only REPORTED may set a customer "verified" state. |
| `match_method` | text CHECK in (`EXACT_CASE`, `EXACT_CASE_PARCEL_CONFIRMED`, `EXACT_PARCEL_CONFIRMED`, `EXACT_CERTIFICATE`, `EXACT_INSTRUMENT`, `EXACT_EVENT_REF`, `NONE`) | How the record reached the event. Today's matcher produces `EXACT_CASE`, or `EXACT_CASE_PARCEL_CONFIRMED` when both sides publish an agreeing parcel. `EXACT_PARCEL_CONFIRMED` is a parcel-only match, allowed only when exactly one event on that county and day carries the parcel. Fuzzy methods have no value in this vocabulary, so they cannot be stored. |
| `record_kind` | text CHECK in (`sale_result`, `postponement`, `cancellation`, `redemption`, `deed_recording`, `government_retained`, `listing`) | What the observation reports. It lets several kinds of fact sit on one event without overloading `outcome`. |
| `postponed_to` | date | Only when the source publishes the new date. The new date is still a separate event (014 identity), and this column links the two. |
| `deed_instrument_ref` | text | Recording instrument number or OR book/page, as published. |
| `deed_recorded_on` | date | Recording date, as published. |
| `deed_consideration` | numeric | Only if the recording index publishes it as consideration. Never derived from documentary stamps, and never written into `winning_bid`. |
| `supersedes_observation_id` | bigint FK, self-referencing | Set when this observation corrects an earlier one (e.g. "Auction Sold" then "Redeemed After Sale"). The earlier row is never updated or deleted. |
| `conflict_with_observation_id` | bigint FK, self-referencing | Set when two REPORTED observations for the same event disagree and neither source states a correction. |

### 7.2 `auction_events`: additive columns and vocabulary

- **Outcome vocabulary:** add `government_retained`, which covers "struck off to the county / taxing unit / FLC"
  when the source names the government as holder. `struck_off` stays the general wording. The two are kept apart
  because Texas "Struck off to Jurisdiction" and SC "bid off to the Forfeited Land Commission" name a holder,
  while a bare "struck off" may not.
- **`deed_status`** (`not_observed` | `recorded`), plus `deed_recorded_on` and `deed_instrument_ref`, copied
  from the latest REPORTED `deed_recording` observation. This is separate from `outcome`: a sold event with no
  recorded deed is still sold.
- **`postponement_count`** (int) and **`last_postponed_to`** (date). Both are derived from observations with
  `record_kind='postponement'` and are never inferred from a date change alone; the writer's existing
  `superseded` rule covers date changes.
- **`outcome_basis`** (`REPORTED` | `INFERRED`) and **`outcome_match_method`**: copied from the observation
  that set the current outcome.
- **`outcome_status`** (`verified` | `conflicting` | `corrected` | `unknown`). `conflicting` holds the customer
  state at "Outcome conflicting - sources disagree" and never picks a side. `corrected` shows the latest REPORTED
  correction, with the history link.
- **Never added:** purchaser, bidder name, bidder count or bidder identity. `winning_bidder_ref` keeps its NULL
  rule from 014, and `check_patch` keeps `bid_count` / `winning_bidder_ref` forbidden.

### 7.3 Rules the writers would keep

1. **An observation is never updated or deleted.** A correction is a new row with `supersedes_observation_id`.
   This extends today's `test_21_verified_result_supersedes_unknown_by_appending`.
2. **Only REPORTED evidence sets a verified state.** An INFERRED observation (a Lands Available presence, an
   NAL transfer after the sale, a feed absence) is stored as corroboration and shown apart from the outcome,
   never as the outcome. This keeps `docs/auction-outcomes.md` section 4: an Available record never manufactures
   a failed auction.
3. **An opening bid never becomes `winning_bid`, and a deed consideration never becomes `winning_bid`.**
4. **Certificate results stay instrument results** on the certificate ledger (`records.py`). They never set an
   auction event's outcome. A certificate redeemed before the deed sale may *corroborate* a
   `redeemed` / `cancelled` event only as INFERRED, matched by `EXACT_CERTIFICATE`.
5. **A failed read writes nothing**, and a verified result is never downgraded by "not published" (as today).
6. **Every new source's reader checks `permissions.authorize(source_id, op, state=, dataset=)`** before its first
   request and its first write, as `auction_outcomes.main()` does for `closed_results`.
7. **RLS stays the same.** The 032 pattern (side rows readable only when the property is readable) also covers
   the new columns, so no policy changes.

## 8. Reproducing this baseline

- **Queries:** read-only SELECTs with GROUP BY over `auction_events` and `auction_event_observations` (counts
  only), plus `properties.inventory_status`.
- **Recommended additions for the next measurement** (still counts only):
  - past events by `state, lifecycle, outcome`;
  - closed observations by `lifecycle, raw_status`;
  - per (county, sale day) the number of closed records read, from a `scripts/auction_outcomes.py --dry-run`
    report, to measure the ten-item limit.
