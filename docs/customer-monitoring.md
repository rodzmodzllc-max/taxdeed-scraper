# Customer monitoring: watch, saved searches, alerts, analytics

Customer-value sprint, 2026-10-01. This covers the WATCH → RECEIVE CHANGES half
of the product workflow:

DISCOVER → EVALUATE → VERIFY → ACQUIRE → WATCH → RECEIVE CHANGES.

Every signal here is deterministic, and every one is a field the row carries
changing.

- Nothing infers a sale, a bidder, a redemption or an outcome.
- A row leaving a source list is reported as **removed / no longer listed**.
  That is never a sale and never a result.
- A result appears only when the source published one (`result_published`).

## 1. Migration 024 (written, live-tested, NOT applied)

`scripts/migrations/024_customer_monitoring_foundation.sql` is additive only.
`tests/python/test_migration_024_monitoring.py` applies it twice to a scratch
cluster, and checks:

- own-row isolation;
- pending-account and anon denial;
- that alerts can be written only by the service role;
- that analytics are insert-own and admin-read.

**Applying it to production was declined in this sprint, so it is not
applied.** Every feature below feature-detects the tables and degrades
honestly.

| Object | Purpose | Client access |
|---|---|---|
| `get_properties()` | ORDER BY gains an `id` tie-break | unchanged |
| `count_properties()` | row count per state (+ ledger) | approved users |
| `property_change_snapshots` | last snapshot per row | service role only |
| `property_change_events` | detected changes | approved read |
| `source_observation_runs` | per-source observed / added / changed / closed / reactivated | approved read |
| `saved_searches`, `alert_preferences` | per user | own rows + RESTRICTIVE `is_approved()` |
| `user_alerts` | per user | read own rows; only `read_at` is updatable |
| `product_events` | analytics; event vocabulary is a CHECK list | insert own; admins read via `product_usage_summary()` |

## 2. Paged property loading (live now, no migration)

PostgREST's `max-rows` (1,000) also applies to RPC results. Before this sprint,
`get_properties(p_state)` returned at most 1,000 rows, so Florida (4,036 rows)
and Louisiana (10,334) were silently truncated in the browser.

`fetchProperties()` now pages each ledger with `p_ledger_type` + `p_limit` +
`p_offset`. Within one state and ledger, `(county, case_no)` is unique in
production (verified with a read-only query on 2026-10-01), so the existing
ORDER BY is already deterministic. 024's `id` tie-break makes that explicit.

## 3. Change detection (`scripts/detect_property_changes.py`)

It runs after every sync: deeds, certificates, laft for FL / LA / TX, and the
expansion matrix. Every step is `continue-on-error`.

- **First run is a baseline.** It emits no events.
- **Mapping, field to kind:**

  | Fields | Kind |
  |---|---|
  | status / inventory status | `removed`, `reactivated` or `status_changed` |
  | `sale_date` | `sale_date_changed` |
  | opening bid | `opening_bid_changed` |
  | `purchase_path_type`, purchase URL | `acquisition_path_changed` |
  | evidence URL, observed-on date | `acquisition_evidence_changed` |
  | `source_id`, `list_url`, publication | `source_changed` |
  | assessed, taxable, acreage, land use, flood, coordinates, imagery, legal | `field_changed` |
  | result fields, newly set | `result_published` |

- **Alerts:**
  - Watchers come from `bid_list`.
  - Saved searches fire on `new_listing` and `reactivated` when their
    criteria match.
  - `alert_preferences` opt-outs are honoured.
  - Coordinate and imagery changes are events only, never alerts.
- **Without 024:** snapshots go to the job's cache
  (`out/.harvest_cache/change_snapshots_*.json`, restored by `actions/cache`).
  The only output is a count file, `out/public/change-detection-*.json`. The
  database is not written.

## 4. Saved searches

The criteria vocabulary is `scripts/saved_search_match.py` `CRITERIA_KEYS`:

- ledger and counties;
- acreage, assessed, taxable and opening-bid ranges;
- sale date range;
- active only;
- land use;
- acquisition path verified / not;
- imagery has / none;
- read from the source within N days.

An unknown value never satisfies a range. `savedSearchMatches()` in app.js is
the second implementation. `tests/python/fixtures/saved_search_cases.json` pins
both, and `run_test.mjs` runs those cases in the browser.

The **Saved searches** button (List toolbar) saves the current filters. Each
search shows matching / **new** / **changed** / **no longer matching** counts
since it was last marked seen:

- "changed" compares a per-row fingerprint stored in this browser;
- "no longer matching" says "not a sale".

Storage:

- With 024: the account.
- Without it: this browser, and the page says so. Alerts for saved searches
  need the server tables.

## 5. Alerts

The account menu has **Alerts** with an unread count. The modal carries:

- **Preferences:** watched-property changes and saved-search matches.
- **E-mail:** a disabled checkbox reading "not configured on this deployment".
  No e-mail is sent; no delivery was fabricated.

Without 024 the modal says alerts are not enabled. Watchlist changes are still
compared in the browser (the existing snapshot, now also comparing:
acquisition path, last verified, source listing, assessed, taxable, acreage,
land use, flood zone).

## 6. Property page: Watch & changes

A section on every property page (nav pill "Watch") shows:

- the watch status;
- what is monitored;
- the alert state;
- the server change history (`property_change_events`), or "not enabled on
  this deployment yet".

## 7. Filters and exports

**Filters.** Cross-ledger filters were added:

- taxable value min;
- imagery;
- acquisition path verified / not yet verified;
- watch status;
- read from the source in the last 1 / 7 / 30 days;
- sale-date range.

**Exports.** The Available export gains these columns:

- Acquisition Status;
- Acquisition Last Verified;
- Imagery On File;
- Days Since Last Read.

The Auction export gains:

- Taxable Value;
- Latitude / Longitude;
- Imagery On File;
- Last Read From Source.

No governance or internal field is exported.

## 8. Analytics

`track()` in app.js records the 14 events in 024's CHECK list. It sends no
search text, no address and no free text. `search_performed` carries only the
number of active filter groups and whether a search text exists.

Events fired before the monitoring probe answers wait in a small queue.
`session_start` fires once per page load. The admin area shows a usage card
from `product_usage_summary(30)`.

## 9. Imagery priority (`scripts/enrich_property_photos_naip.py`)

Tiers, in order:

1. Available;
2. active auctions;
3. closed auctions.

**Certificates get no new imagery.** Existing images are kept, never deleted.
`out/public/imagery-priority.json` reports outstanding / attempted / stored /
no coverage / failed / deferred per tier. Deferred rows stay unchecked.

The 950 MB storage budget still fails closed. The bucket held 967.5 MB at the
start of this sprint, so **no image can be uploaded** until storage is freed
or the plan changes. That is the owner's decision.
