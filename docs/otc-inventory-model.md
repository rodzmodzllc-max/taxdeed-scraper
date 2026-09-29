# OTC / LAFT / struck-off inventory model

**Status:** implemented 2026-09-29 from the master LAFT / OTC / struck-off audit
(same date). Repository implementation only. **Migrations 017 and 018 are
NOT APPLIED to production**; the Florida lifecycle script detects their absence
and limits itself to columns that exist today. Production activation of any
part of this is a separate authorisation.

## 1. What the audit found, and what this implements

Three different things shared `source = 'laft'`: Florida's post-sale
fixed-price Lands Available list (F.S. 197.502(7)), Texas property struck off
to the taxing units and held in trust, and Texas property "Available for
Future Sale". Nothing said which; nothing said who the source of record was;
a zero-row harvest looked identical to a broken parser; nothing ever closed a
Florida row out; `bid = 0` meant "not published". This change adds:

| Area | Where | What |
|---|---|---|
| Per-county harvest status | `scripts/laft_status.py`, all nine `scripts/harvest_laft_*.py` | `out/harvest_laft_status.json`: COMPLETE / EMPTY / INCOMPLETE / FAILED per county with transport/parse/empty-marker signals, error category, source URL, parser version, document hash. STALE / NOT_RUN are assigned by the reader. |
| Lifecycle | `scripts/laft_lifecycle.py` (new `laft` job step after the sync) | `last_seen_at` for rows actually read; close-out only for COMPLETE / EMPTY counties; reactivation of re-listed rows. |
| State filter | `scripts/sanity_check_laft.ps1` | `state=eq.FL` - Texas LGBS rows are never Florida anomalies. |
| Schema | `scripts/migrations/017_otc_inventory_provenance_lifecycle.sql` | inventory type, source authority, source id, list / document / purchase URLs, nullable purchase amount + kind, first/last seen, delisted, source dates, document hash, per-field provenance. |
| Registry | `data/county_source_registry.csv`, `harvesters/governance/county_source_registry.py`, `scripts/build_county_source_registry.py`, `scripts/migrations/018_county_source_registry.sql` | One row per (state, county, source) with authority, access method, format, verification, governance, last check, completeness. |
| Texas framework | `harvesters/otc/` | `OtcRecord` contract, run gate, generic tabular adapter (fixtures only), LGBS bridge. No live Texas government adapter. |
| Frontend | `public/app.js` `hasPublishedBid()` | `purchase_amount_kind` is authoritative when present; legacy `bid` rule otherwise. |

## 2. Status vocabulary (per county, per run)

| Status | Meaning | May close absent rows? |
|---|---|---|
| COMPLETE | transport + parse succeeded, rows extracted (or byte-identical to a prior parse) | yes |
| EMPTY | the source itself said nothing is listed: `empty_marker`, `empty_table` (recognised header, zero rows), `reported_count_zero`, `empty_list` | yes |
| INCOMPLETE | transport succeeded but the inventory is not trustworthy as a whole: no table and no marker, count mismatch, truncation, an unconfirmed zero. Parsed rows are still observed. | no |
| FAILED | transport / access / hard format failure - nothing observed | no |
| STALE | reader-side: entry older than the freshness window (36 h) | no |
| NOT_RUN | reader-side: registry expects a harvester, no entry | no |

A missing or unreadable status file closes nothing. Row count alone never
decides a status.

Per-harvester zero signals: PDF - empty phrase in the text (else INCOMPLETE:
Brevard's procedural LOLA.pdf is now INCOMPLETE, not an empty list); HTML -
empty phrase, or a recognised header with no data rows; realTDM - a
recognised page plus one of `REALTDM_EMPTY_MARKERS` (none confirmed live yet,
so a realTDM zero is INCOMPLETE / UNCONFIRMED_EMPTY until a phrase is
captured - fail closed by design); Pioneer - the platform's own `records`
count; Osceola - the API's `_total_rows`; Leon - the JSON envelope's empty
list; Orange - the app's "0 items found"; St. Lucie / Hillsborough - a
rendered results grid with zero rows.

Error categories (`TRANSPORT_HTTP_403_BLOCKED`, `TRANSPORT_HTTP_404`,
`PROXY_FAILURE`, `PROXY_NOT_CONFIGURED`, `PLACEHOLDER_TENANT`,
`PARSE_NO_TABLE`, `PARSE_FORMAT_CHANGE`, `PARSE_COUNT_MISMATCH`,
`PARSE_TRUNCATED`, `UNCONFIRMED_EMPTY`, ...) are recorded with the exception
class only - never the message, which could echo request data.

## 3. Lifecycle rules

1. **Observed** = a harvested row whose county is COMPLETE or INCOMPLETE this
   run. Gets `last_seen_at = now` (017) and, if it had been closed, `status =
   'active'` again (migration 006's trigger clears `gone_since`). The
   PowerShell upsert also sends `status = 'active'` for every harvested row.
2. **Closed** = an open row of a COMPLETE or EMPTY county that is not in this
   run's observed keys: `status = 'closed'`, `delisted_at = now` (017),
   `gone_since` via the trigger. "Closed" means "no longer on the county's
   list". No sold / redeemed / escheated outcome is inferred.
3. Identity is exactly the sync's: `county + (case_no or parcel)`.
4. Without 017 the script writes `status` only and says so in the log.

## 4. Amount semantics

`purchase_amount` (nullable) + `purchase_amount_kind` from the source's own
label: `MINIMUM_PURCHASE_AMOUNT`, `OPENING_BID`, `ORIGINAL_OPENING_BID`,
`FIXED_PURCHASE_PRICE`, `ESTIMATED_PURCHASE_PRICE`,
`PUBLISHED_AMOUNT_KIND_UNSPECIFIED`, `NOT_PUBLISHED`. Each harvester now emits
`bid_kind` alongside `bid` (PDF/HTML from the column label; realTDM
"Purchase Price" = FIXED_PURCHASE_PRICE, base figure; Pioneer/Osceola/Leon/
St. Lucie/Hillsborough "Base/Opening Bid" = OPENING_BID; Orange "Min Bid" =
MINIMUM_PURCHASE_AMOUNT; Putnam "Estimated Purchase Price").

`bid` is unchanged: NOT NULL, no default, 0 sentinel written by the FL syncs.
The app's `hasPublishedBid()` reads `purchase_amount_kind` first. Retiring the
sentinel column-side is a later change. The realTDM Miami-Dade price parse
(0/2 on 2026-09-29) is **not** fixed here: the detail-page HTML could not be
fetched from this sandbox, so no deterministic parser change was possible;
the count of unparsed prices is now recorded in the status entry instead.

## 5. URL roles

`list_url` (the list page), `document_url` (the file), `purchase_url` +
`purchase_url_kind` (`purchase_instructions` / `offer_form` / `bid_form` /
`application_form` / `online_purchase`). `url_auction` keeps migration 013's
meaning and is the list page with kind `county`. A list page is never a
purchase URL; no purchase URL is set for any Florida county today (none is
verified).

## 6. The existing 421 Texas LGBS rows

Migration 017 classifies them from what the rows carry: `source_authority =
VENDOR_COUNSEL`, `source_id = tx_lgbs`, `inventory_type` from
`tx_sale_status` when present (`Struck off to Jurisdiction` ->
STRUCK_OFF_HELD_IN_TRUST, `Available for Future Sale` -> FUTURE_RESALE) and
NULL otherwise - which is all 421 today, because they predate the raw-status
writer. No URL is invented, `purchase_amount` is not set from `min_bid`,
`tx_sale_status` is not invented. `harvesters/otc/lgbs_bridge.py` is the same
rule in Python. LGBS is not retried, its schedule and workflow are unchanged.

## 7. Texas government-direct sources

Every Texas government list the audit found is `SEARCH_EVIDENCE_ONLY` in the
registry - seen in a search index, never fetched from this repository. The
`harvesters/otc/` gate refuses all of them (and refuses PBFCM / MVBA /
GovEase / CTSA by name, and Harris/hctax.net under its existing
LEGAL_REVIEW_REQUIRED). The generic tabular adapter is exercised on fixtures
only. `harvesters/otc/adapters/tabular.py::TX_CANDIDATES` lists what a human
must do per county before a config can exist. Search-engine snippets are not
verification; nothing here pretends they are.

Florida candidates (Broward, Okaloosa, DeSoto, Wakulla; the seven
exists-but-unknown counties; Jefferson historical; Baker/Jackson/Liberty not
found) are registry rows only - no harvester.

## 8. Migrations

| File | Applied? | Depends on | Reversible |
|---|---|---|---|
| `017_otc_inventory_provenance_lifecycle.sql` | **NO** | 006, 013 (015 in either order; 017 re-pins `search_path`) | yes - drop the added columns (see the file's footer); get_properties returns to 013's projection by re-running 013 section 3 |
| `018_county_source_registry.sql` | **NO** | nothing | yes - drop the table |

Both apply verbatim to a scratch cluster in
`tests/python/test_migration_017_otc_provenance.py` (fixture:
`tests/python/fixtures/migration_017_scratch_fixture.sql`). The 018 table is
created empty; `county_source_registry.to_db_rows()` produces the load.

## 9. Known limitations

- realTDM empty phrase not yet captured (see section 2); five realTDM
  counties that genuinely have nothing listed will read INCOMPLETE until it is.
- Hendry's Municode successor discovery is best effort and unverified from
  this sandbox (egress blocked): the clerk's node page may be JavaScript-
  rendered, in which case the county stays FAILED / TRANSPORT_HTTP_404 with
  the reason recorded.
- No source publishes a frequency; `source_published_at` / `list_as_of` are
  written only when a source or document name carries a date (the tabular
  adapter does this; the Florida harvesters do not yet).
- `first_seen_at` is unknown for every pre-017 row and stays NULL.
