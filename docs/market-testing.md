# Market testing: measurement, filtering and visibility (2026-10-06)

The generated shortlist is in [`market-test-report.md`](market-test-report.md).
This page explains how it is built and how large inventories stay visible
without crowding out smaller markets. **No market is activated by being on
any list here.**

## What a market is

A market is one state × ledger: AVAILABLE, AUCTION or LIEN. Single-county
sources are named by county (York SC, East Baton Rouge LA, Albany WY, ...).
Florida and Texas markets are statewide: the snapshot holds state × ledger
counts. A county-level split comes from `scripts/enrichment_audit.py`, which
runs as part of `job=geocode`. Each county could then become its own market
with the same rules, by adding its counts to `data/market_audit_snapshot.json`.

## Inputs (all in the repository)

* `data/market_audit_snapshot.json`: counts only, measured read-only in
  production on 2026-10-06, over records with status active or available.
* `data/market_caveats.csv`: documented facts that limit a market. Each row
  cites where it is documented. Kinds:
  * `freshness`, `dated_list`, `source_review` and `not_current` affect the tier;
  * `gap` is reported only.
* `public/acquisition-evidence.json`: counties with a verified acquisition
  record.

## The rules (`harvesters/sources/market_metrics.py`)

Every market shows its metrics, its tier and the rules it failed. There is no
single number.

| Tier | Rule |
|---|---|
| HELD | No customer-visible record: the source is not cleared for customers. Kept for admins. |
| NOT_CURRENT | Visible, but the inventory is a finished sale. |
| FOCUS | Visible, and every rule below holds. |
| BROWSE | Visible, and at least one rule below fails. |

The FOCUS rules:

| Rule | Holds when |
|---|---|
| identity | ≥ 95% of active records carry a parcel / account identifier |
| coordinates | ≥ 75% carry coordinates (imagery-capable) |
| path | ≥ 80% carry the ledger's published path (see below) |
| current | No freshness, dated-list or source-review caveat applies |

The published path depends on the ledger:
* **Auctions:** the sale page.
* **Liens:** the certificate sale page or acquisition evidence.
* **Available:** verified acquisition evidence only. An Available list page is
  not a purchase path.

The shortlist order:
1. FOCUS markets, by customer-visible records.
2. BROWSE markets, by number of failed rules, then customer-visible records.

NOT_CURRENT and HELD markets are listed as "not prioritized", largest first.
They are never dropped.

## The market filter: size is not value

A 30,000-record market whose records lack identity, coordinates or an
acquisition path ranks below a 150-record market where they are present.
Size only orders markets that pass the same rules.

* **Detroit:** 30,783 Available records. HELD: the source is unreviewed, and
  only 5 records carry an acquisition record.
* **St. Louis:** 9,758 records. HELD, and no coordinate source is cleared.
* **York County SC:** 853 auction records, 100% identity, coordinates and
  path. FOCUS.

## Visibility strategy for large inventories

Nothing is hidden for being large. Visibility follows the source decision,
and the existing interface already scales:

* **Collection is separate from publication.** HELD sources are collected and
  shown to admins (and in preview mode) with a "Source review" label. A
  customer sees a record only when its source is APPROVED.
* **Large counties stay usable.** List groups page 50 cards, the table pages
  200 rows, and map pins cluster above 250 per view. A 30,000-record county
  never renders 30,000 nodes.
* **Detroit customer subset.** Once approved, customers see only offered
  structures in the deterministic ~50% subset (`docs/detroit-customer-subset.md`).
* **Discovery stays in navigation.** The state picker, the County
  Intelligence index and per-ledger counts reach every market. FOCUS markets
  are not pushed into a customer's view by default.
* **Enrichment goes where customers look.** `data/market_test_counties.csv`
  (generated from the strongest markets) feeds enrichment rule P5. Its
  counties' records, including ones not yet customer-visible, are enriched
  before other non-visible records.

## Re-measuring

1. Dispatch `job=geocode` with `geocode_mode=plan` (read-only). It writes
   `out/public/enrichment-audit.json`.
2. Copy the state × ledger (or state × county × ledger) counts into
   `data/market_audit_snapshot.json`.
3. Update `data/market_caveats.csv` when a documented fact changes.
4. Run `python3 scripts/build_market_report.py`.

`--check` (and its test) fails when the report or the county list is not
current.
