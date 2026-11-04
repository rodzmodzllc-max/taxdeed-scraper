# Image storage: optimization, deduplication, priority

Storage-optimization sprint, 2026-10-01. This sprint is about image objects
only. It does not add a paid storage tier, does not change the schema, and
does not touch publication, acquisition, ledger or source rules.

## What is stored

- Every object in the `property-photos` bucket is a USDA NAIP aerial tile
  (`photo_source = 'usda_naip'`).
- Before this sprint each one was a lossless PNG of 600 × 450, about 290 KB.
- The bucket held 3,518 objects and 967.5 MB, against the application's
  950 MB budget.

## Optimization (`scripts/image_storage.py`)

`optimize_image()` re-encodes an image as WebP at quality 82 and the **same
dimensions**. 600 × 450 is already the largest size the app shows: card
banner, property-page hero and map preview. The result is used only if it
passes every check:

- it decodes;
- its dimensions are unchanged;
- it is strictly smaller;
- it keeps its detail (a minimum colour spread).

If any check fails, the source bytes are kept unchanged. A WebP input is never
re-encoded, so the process is idempotent.

## Content-addressed paths = exact deduplication

New images are stored at `naip/v2/<sha256 of the source bytes>.webp`.

- Identical source images resolve to one object.
- When the object already exists, the upload is skipped and the row points at
  it.
- Visually similar but different images have different hashes and are never
  merged.

## Existing objects (`scripts/optimize_stored_images.py`, `job=storage`)

**`analyze`** (read-only) reports:

- bytes, object count and size distribution;
- a breakdown by tier, state, ledger and county;
- exact-duplicate candidates;
- a measured sample of format, dimensions and WebP ratio;
- projections for policies A–D.

The output is counts and sizes only.

**`apply`** re-encodes each PNG **in place**, at the same path and URL. For
each object it:

1. downloads it through the authenticated endpoint (not the CDN);
2. optimizes it;
3. uploads it;
4. reads it back and checks the bytes and the dimensions;
5. restores the original if that check fails.

No `properties` row is written. That matters because every UPDATE on
`properties` fires `touch_updated_at`, and the app shows `updated_at` as "Last
synced" and uses it for stale warnings. Repointing thousands of rows would
falsely mark them freshly synced.

**`apply_consolidate`** also folds byte-identical objects:

- it confirms identity by sha256 after download, never by eTag alone;
- it repoints the rows to one object;
- it re-counts the references and deletes the redundant object only at zero.

It is opt-in because the repoint bumps `updated_at` on those rows. 151
Miami-Dade certificates share one coordinate, and therefore one image; that is
also a geocoding finding.

## Priority and the fail-closed budget (`scripts/enrich_property_photos_naip.py`)

| Tier | New imagery | Existing imagery |
|---|---|---|
| 1. Available (`laft`, active) | collected first | kept |
| 2. Active / upcoming auctions | collected second | kept |
| 3. Closed / dropped auctions | **deferred by policy**: counted, not collected | kept |
| 4. Liens & certificates | **never requested** | kept |

- **The 950 MB budget still fails closed.**
  - No upload happens when usage is unknown or the budget is reached.
  - The budget is checked against the optimized size.
  - A reused duplicate costs 0 bytes.
- **Deferred and failed rows stay `photo_url IS NULL`**, never marked
  complete.
- **Both imagery steps are `continue-on-error`.** A storage failure can never
  fail the structured harvest and sync, or skip the steps after them.
- **`out/public/imagery-priority.json` reports**, per tier:
  - outstanding, attempted, stored, no coverage, failed and deferred;
  - compressed, deduplicated, bytes stored and estimated bytes saved.
