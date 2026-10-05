# Property list performance: independent ledgers, list payload, detail provenance (2026-10-05)

## The problem

Louisiana Auctions holds no rows. Its query answers in about 10-33 ms warm.
Even so, the List showed skeletons for as long as Louisiana Available
(10,334 rows, 11 pages) took to download. Three things caused this:

1. **First-render gating.** `loadAll()` awaited `fetchProperties()`, which
   awaited every page of all three ledgers. It then awaited the
   auction-outcome index (two more paged reads) before anything painted.
2. **Payload.** Each `get_properties()` row carried the full `otc_provenance`
   and `field_provenance`: per-row evidence that the list, cards, map and
   search never read. Measured read-only in production on 2026-10-05:

   | State / ledger | Rows | Full JSON | Provenance in it |
   |---|---|---|---|
   | LA Available | 10,334 | 112.6 MB | 76.3 MB (39.2 field + 37.2 otc) |
   | MI Available | 30,801 | 151.5 MB | 63.6 MB (41.7 field + 21.9 otc) |
   | FL (all three) | 4,112 | 14.4 MB | small |

   The same county acquisition record and purchase instructions (~3 KB)
   were repeated in 6,834 Louisiana rows.
3. **Order.** All three ledgers were requested at once, so a large background
   ledger competed with the one on screen.

## What changed

### Independent ledger loading (`public/app.js`)

- `fetchProperties(activeKey, onUpdate)` returns `{ ready, done }`.
  - The active ledger (from the URL) loads first. The other two start once
    its first page is in.
  - Rows land in `LEDGER_RAW` as pages arrive, and `applyLedgerRows()`
    rebuilds `ALL` with the same rules as before: id de-dup, Detroit
    customer subset, publication gate, withheld / review counters.
  - `LEDGER_LOAD[k]` moves `idle → loading → partial → done | error`.
- **`ready`** resolves as soon as the List can paint without misleading:
  - a routed ledger: once its first page, or its failure, is in;
  - unrouted: once the landing ledger can be decided (Available, then
    Auctions, then Liens & Certificates). A ledger counts as empty only once
    its own load is settled.
- `loadAll()` awaits `ready` plus the small per-user reads, then paints.
  These run in the background and never gate the first paint:
  - the other ledgers;
  - the auction-outcome index;
  - the watchlist diff, which needs every ledger and is skipped when one
    failed.
- **Background updates** (`scheduleLedgerUpdate`) are coalesced. While the
  customer reads one ledger, another ledger's pages only refresh the counts
  (`renderLedgerCounts`); the list being scrolled is not rebuilt.
- **Counts and empty states:**
  - A ledger still loading shows `…` (or `1,000…` while pages arrive) on its
    tab, sidebar and Home card. It is never shown as `0`.
  - The active ledger, while loading, shows "Loading <ledger> for <state>…"
    (`data-ledger-loading`).
  - A settled empty ledger says "No auction properties currently available."
    (or the Available / Liens equivalent) before the state's own ledger copy
    (`data-ledger-empty`).
  - "No properties currently available for this state." appears only once
    every ledger is settled.
- **Unchanged:**
  - concurrent calls share one run (no duplicate page requests);
  - page retry, back-off, partial-load notice and the Retry button;
  - a deep link to a property on a later page or another ledger opens once
    every ledger is in.

### List payload: migration 028 (NOT applied)

`scripts/migrations/028_property_list_payload.sql` adds two functions and
changes nothing else.

**`get_properties_list(...)`** has the same signature, the same 105
columns in the same order, the same narrow-key sort and paging, STABLE,
search_path and SECURITY INVOKER as `get_properties()` (025). It differs in
three places:

- **`otc_provenance`** keeps every key except those no list surface reads:
  - `purchase_instructions`: the county's process text, about 1.5 KB,
    repeated in every row of a county (6,834 Louisiana rows). The list fills
    it back in `acquisitionProvenance()` from `acquisition-evidence.json`,
    and only from the county record of the same source, county, path type
    and evidence page;
  - the ArcGIS harvest internals `query_where`, `attributes`, `layer_url`,
    `columns`, `id_field` and `object_id_field`.

  The acquisition record is kept whole. Four production groups have one
  with no county evidence file entry (Oceana MI, Oklahoma OK, Georgetown and
  Horry SC). `source_match`, amounts and statements are kept too. A test
  greps the frontend to prove no dropped key is read outside
  `acquisitionProvenance()`.
- **`field_provenance`** keeps only the entries that mark a source under
  review (governance set, or `tx_lgbs` / `tx_realauction`), reduced to
  source / source_id / governance.
- **`provenance_scope = 'list'`** is appended.

**`get_property_provenance(p_id)`** returns one row's full pair, for the
property page. It is SECURITY INVOKER, so the properties RLS policy decides
what a caller can read.

`get_properties()` is untouched, and so are 025 and 026. Grants match
`get_properties()`.

The frontend calls `get_properties_list()`. Until 028 is applied, that
function is missing (PGRST202) and the app falls back to `get_properties()`
exactly as before. Rows then carry no `provenance_scope`, and no detail fetch
happens.

**Measured** with the same projection inlined in a read-only SELECT
(2026-10-05; byte counts of `to_jsonb`, before gzip):

| State / ledger | Full | List | Provenance: full → list |
|---|---|---|---|
| LA Available (10,334) | 112.6 MB | 63.5 MB | 76.3 → 26.9 MB |
| MI Available (30,801) | 151.5 MB | 97.0 MB | 63.6 → 8.1 MB |
| FL Auctions / Available / Liens | 8.5 / 0.8 / 5.1 MB | 8.2 / 0.8 / 5.1 MB | 1.7 → 1.1 MB |

Most of what remains:

- **Louisiana:** the kept acquisition record, 9.2 MB. It is byte-identical
  in all 6,834 rows, so gzip removes nearly all of it on the wire.
- **Both states:** the 105 column names repeated per row, about 20 MB
  (Louisiana) and 60 MB (Michigan) of key text, which also compresses
  heavily.

The independent loading above is what removes the wait. The payload change
removes most of the per-row provenance.

### Property page: full provenance on open

`openDetail()` and `selectProperty()` call `ensureFullProvenance(p)`:

- For a list-scope row, it fetches `get_property_provenance` once per
  property per page load and merges the pair into the row in place.
- It then redraws only the property on screen, keeping its scroll position.
- While loading, the provenance card says "Loading full source provenance…".
  On failure it shows a Retry. It never claims "no provenance recorded".

"How to acquire", forms, official links and the financial lines were already
complete from the list row plus the county evidence file. They stay
complete.

## Tests

- **`tests/python/test_migration_028_property_list_payload.py`**
  - Static: columns = 025's + `provenance_scope`; order, paging, STABLE,
    search_path and invoker are kept; only provenance is reshaped; nothing is
    dropped or revoked; 025 / 026 are untouched; key lists are equal across
    the SQL, the stub and app.js; the frontend uses the list RPC with a
    fallback.
  - Live, on the 026 scratch schema:
    - pages, rows and order are identical to `get_properties()` for six
      roles;
    - every other column is identical;
    - the dropped keys are gone, the acquisition record is kept, and the
      payload is smaller;
    - the detail function returns the full pair, only where RLS allows;
    - the migration is idempotent and leaves `get_properties()` unchanged.
- **`tests/run_test.mjs`**, "Independent ledger loading" block:
  - LA Auctions shows its empty state in under 3 s on desktop and 390px
    while LA Available takes 4 s per page; Available then arrives;
  - a loading Available list is never called empty;
  - MI Auctions is not blocked by a 3,000-row Available ledger;
  - FL is not gated on a slow auction-outcome read;
  - one list call per ledger page;
  - LA list rows are slim, and opening one loads the full pair once, with
    acquisition and forms intact;
  - the `?nolistrpc=1` fallback still works.
