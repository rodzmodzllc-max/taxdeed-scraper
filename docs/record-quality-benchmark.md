# Record-quality benchmark

This is a reproducible measure of record quality in a small set of counties, chosen by existing coverage. It can be rerun after every improvement. The current results are in `docs/record-quality-benchmark-results.md`, which is generated and pinned by `tests/python/test_record_quality.py`.

## What it measures

`harvesters/quality/record_invariants.py` computes, per state × county × ledger:

| Metric | Rule |
|---|---|
| Active | `status` active / available / scheduled, and no `delisted_at` |
| Source link | `url_auction` is an https link |
| Parcel # | A plausible identifier: has a digit, ≤ 60 characters, one line |
| Dated | Auctions: `sale_date`. Available: `list_as_of`, `source_published_at` or `available_date`. Certificates: issued date, sale date or tax year. |
| Published amount | A figure the source published, respecting the amount kind. A quote on application is not an amount; the legacy 0 bid is not one. |
| Read ≤ 36 h | `last_seen_at` within 36 h of the export time |
| Acquisition path | Available: `purchase_path_type` set. Auctions and certificates: the source link. |

It also counts these invariant violations among all rows:

- duplicate identity (state, source, county, case number);
- `source` and `ledger_type` disagreeing;
- a status outside its ledger's set;
- a result without the source's own wording;
- a result amount without a published result (an opening bid is never a winning bid);
- a quoted price stored as an amount;
- an active row that has been delisted;
- `last_seen_at` earlier than `first_seen_at`;
- implausible identifiers;
- a certificate with no identity.

## Two inputs, never mixed

**1. Counts-only snapshot** (`data/market_audit_snapshot.json`, read-only production audit of 2026-10-06):

    python scripts/record_quality_benchmark.py --snapshot data/market_audit_snapshot.json --out docs/record-quality-benchmark-results.md

This reports only what the snapshot measured. Dated, amount, freshness, duplicate and lifecycle metrics are printed as **"not in snapshot"**, never estimated.

**2. Full rows export** (all metrics and invariants). Requires a read-only export of `properties` with the columns `get_properties()` returns, and the export time:

    python scripts/record_quality_benchmark.py --rows export.json --now 2026-10-10T12:00:00Z

Producing that export is a production read. It needs the owner's authorization and is not part of this repository's CI.

## Results so far

- **Measured: the 2026-10-06 snapshot**, in `docs/record-quality-benchmark-results.md`. Nine counties, three per ledger, chosen by visible volume.
- **Not measured yet:** the full-rows metrics (dated, published amount, freshness, invariant violations) on production data. No production export was made in this sprint.
- **Fixture-only:** the invariant rules are exercised against synthetic rows in `tests/python/test_record_quality.py`. Those are local results, not production measurements.

**What the snapshot shows, stated plainly:**
- Every selected county has 100% parcel identifiers and source links.
- Gaps:
  - FL certificate and auction counties carry **almost no authoritative coordinates** (Hillsborough, Santa Rosa and Miami-Dade: 0; Volusia: 1 of 228) and **no recorded per-field provenance** for nearly every record (incomplete provenance: 125/125, 480/480, 193/193 and 227/228);
  - TX Liberty (Available) has **no acquisition evidence and no purchase URL**;
  - WY Albany (Auctions) has **no acquisition evidence**.
