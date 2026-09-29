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
| `019_laft_list_dates.sql` | **NO** | 017 | yes - re-run 017 section 3, drop the two columns (see the file's footer) |

Update 2026-09-29 (production activation): 017 and 018 are APPLIED in
production (`20260929163745`) and the registry CSV is loaded; 019 is not
applied (proposed with the enrichment PR).

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
  written only when a source or document name carries a date. Since the
  enrichment phase the PDF harvester reads `list_as_of` off the document
  text ("as of MM/DD/YYYY" and friends) or an 8-digit date in the filename
  (`laft_status.extract_list_as_of`), and the lifecycle writes
  `source_published_at` from the document's HTTP Last-Modified; the HTML/
  portal harvesters still publish neither.
- `first_seen_at` is unknown for every pre-017 row and stays NULL.

## 10. Enrichment mechanisms (2026-09-29)

Everything here is a reusable pipeline step, not a one-off backfill, and
none of it ran against production in the PR that added it.

### 10.1 County-list fields carried onto the row (`scripts/laft_source_fields.py`)

Runs inside `scripts/laft_lifecycle.py` on every laft job, on the OBSERVED
rows only (a harvested row whose county is COMPLETE or INCOMPLETE this
run - the same gate as `last_seen_at`). Match is the sync's own identity,
`(state, source, county, case_no)`, exact - never an address, never across
counties or states, never fuzzy; an ambiguous key (two database rows) is
skipped. Columns: `legal_desc`, `owner_name` ("name in which assessed"),
`assessed`, `certificate_no`, `homestead` (yes -> true, never false), and -
once migration 019 exists - `escheatment_date`, `available_date`. Fill-blank
only. Every write records a `county_list` entry in `field_provenance`.
Counts reported: matched / unmatched / ambiguous / rows written / nothing
to write / errored, per-column written / skipped-present / unparseable.

### 10.2 Per-column provenance and precedence (`scripts/field_provenance.py`)

`properties.field_provenance` (migration 009, previously never written)
holds one entry per column: `{"source", "recorded_at", ...}` with the
source-specific evidence (list URL + document hash + `list_as_of` for the
county list; matched candidate spelling for the FDOR layer). Rule: a blank
may be filled by any source; a stored value is replaced only by a strictly
higher-ranked source (`hand_research` 3 > `county_list` = `fdor_nal` =
`county_gis` 2 > `vendor_listing` 1). Equal rank never overwrites - first
government source in stays. `scripts/enrich_property_details.py` now reads
`field_provenance`, withholds any column a provenanced equal-or-stronger
value already occupies, and writes its own `fdor_nal` / `county_gis`
entries for every column it fills.

### 10.3 Identifier plausibility gate (`laft_status.plausible_identifier`)

Production held five FL LAFT rows whose parcel/case was heading or
paragraph text (Volusia x3, Pasco x1, Escambia x1). The PDF and HTML
parsers now drop any row whose parcel or case number has no digit, exceeds
40 / 60 characters, or spans a line break, and count it as `rejected`. A
document whose every row is rejected is INCOMPLETE / PARSE_FORMAT_CHANGE,
never EMPTY - so the lifecycle can never close a county out on the strength
of a parse failure. `harvest_cache.PARSER_VERSION` is bumped so cached
pre-gate rows are re-parsed once. The five existing junk rows leave
production on the next COMPLETE harvest of their county (the gated
close-out), or by the explicit backfill listed in the PR - not by this code
on its own.

### 10.4 FDOR enricher hardening

- Hendry list-form parcel normalization (`_expand_hendry_list_form`), from
  the one verified production pair: `2-01-43-29-010-0050-F020` (list) ->
  `2 29 43 01 010 0050-F02.0` (layer).
- A candidate that resolves to more than one layer feature is AMBIGUOUS:
  skipped, counted, never enriched from either feature (`resultRecordCount=2`).
- Public CI logs carry row ids and counts only; parcel numbers and roll
  values no longer appear in error lines.
- Summary line: attempted / matched / written / unmatched / ambiguous /
  errored / columns withheld by precedence.

### 10.5 What is deliberately NOT done here

- Texas: no LGBS retry, no blocked vendor, no CAD adapter for the eight
  LGBS counties (none has a verified government property source in the
  registry; adding one is a new source integration, out of scope), and
  `purchase_amount` stays NULL for LGBS rows (017's rule: the Texas
  minimum bid keeps its own meaning). `inventory_type` for the 421 rows
  needs a future LGBS run that carries `tx_sale_status`.
- Florida FDOR formats that could not be verified from this sandbox
  (Citrus, Hillsborough, Indian River's short account numbers) are left
  alone; the enricher's per-county match line is the signal to revisit.
- No purchase URL is set for any county: the registry carries none that is
  verified, and a list page is never a purchase URL.

## 11. State extensibility (code foundation, 2026-09-29)

The framework no longer assumes Florida or Texas anywhere a third state
would have to edit code to pass. It also does not admit one: every
mechanism below accepts exactly the states registered in
`harvesters/governance/states.py` (FL and TX), and registering a state is
a reviewed commit, not a configuration file or an environment variable.
Nothing in this section activates a state, populates a row, or touches
production; the 50-state audit's candidates (AR, MS, AL, WV, AZ, LA) are
NOT registered and have no registry rows.

### 11.1 What reads the state registry

| Mechanism | Before | Now |
|---|---|---|
| `OtcRecord.validate()` | `state not in ("FL","TX")` | `states.state_problems(state)`; an unregistered or malformed code is rejected |
| `county_source_registry.validate_row()` | `state not in ("FL","TX")`; `if state == "FL": must be POST_SALE_FIXED_PRICE` | state via the registry; the production inventory rule comes from `StateConfig.production_inventory_types` (FL: `POST_SALE_FIXED_PRICE` only; TX: blank / `STRUCK_OFF_HELD_IN_TRUST` / `FUTURE_RESALE` - unchanged) |
| `scripts/laft_lifecycle.py` | module constants `STATE = "FL"`, `INVENTORY_TYPE = "POST_SALE_FIXED_PRICE"` | `--state` (default FL); refuses an unregistered state before any request; the inventory type it stamps is `StateConfig.lifecycle_inventory_type` (FL: the statutory list; TX: none, so the column is left alone) and must be storable |
| `scripts/sanity_check_laft.ps1` | `state=eq.FL` literal | `$env:LAFT_STATE` (default FL, two capital letters or the script throws) |
| `public/app.js`, `explore.js`, `satellite-map.js` | `PAGE_STATE === "TX" ? "tx-…" : "fl-…"` ternaries for basemap, city/zip files, titles, city labels, camera | one lookup table per module (`STATE_META` / `STATE_ASSETS` / `STATEWIDE_VIEW`); a `data-state` outside the table is logged as an error and the page falls back to FL only so it loads - no other state's assets are ever drawn for it |

The workflow still runs `laft_lifecycle.py` and `sanity_check_laft.ps1`
without a state argument, i.e. Florida, exactly as before.

### 11.2 Publishing units

`states.PublishingUnit` names what a registry row describes: `COUNTY`
(FL, TX - every current row), `PARISH`, `BOROUGH`, `MUNICIPALITY`, `STATE`.
A `STATE`-level row (a statewide land office) carries
`county = STATEWIDE` (`states.STATEWIDE_UNIT`) and is not checked against
a county list. The registry loader accepts an optional trailing
`publishing_unit` column (`county_source_registry.OPTIONAL_COLUMNS`);
**the committed CSV, the generator and migration 018 do not carry it** -
blank reads as `COUNTY`, and `to_db_rows()` refuses a non-county row
because the 018 table has no column for it.

### 11.3 Vocabulary the database cannot store yet

`InventoryType` gained `POST_SALE`, `STATE_HELD_TAX_LAND` and
`ADJUDICATED_PROPERTY`; `AmountKind` (and `laft_status.AMOUNT_KINDS`)
gained `QUOTED_ON_APPLICATION` (no figure is published; the price is
quoted to an applicant - like `NOT_PUBLISHED`, the amount must be None).
None of these is in migration 017's check constraints. The code keeps the
two sets apart on purpose:

- `DB_SUPPORTED_INVENTORY_TYPES` / `DB_SUPPORTED_AMOUNT_KINDS`
  (`laft_status.DB_AMOUNT_KINDS`) are exactly 017's values.
- `OtcRecord.to_properties_row()` raises for a value outside them; the
  lifecycle refuses a state whose lifecycle type is outside them;
  `validate_row()` refuses a PRODUCTION_VERIFIED row carrying one;
  `laft_lifecycle.amount_of()` never emits `QUOTED_ON_APPLICATION`.

An FL/TX label is never substituted for one of these values to make a row
storable - that mislabelling is what the separation prevents.

### 11.4 Future migration (proposed, NOT written, NOT applied)

A later migration - 020 or whatever number is next when it is written -
would, in one reviewed file:

1. widen `properties_inventory_type_check` with the three inventory types
   above and the `purchase_amount_kind` constraint with
   `QUOTED_ON_APPLICATION`;
2. add `publishing_unit text not null default 'COUNTY'` (checked against
   the `PublishingUnit` values) to `public.county_source_registry`, and
   the same column to `data/county_source_registry.csv` / the generator;
3. nothing else - no backfill, no state row, no data.

It is a prerequisite for storing any third state's rows; it is not a
prerequisite for anything Florida or Texas does today.

### 11.5 Generic ArcGIS layer adapter (`harvesters/otc/adapters/arcgis.py`)

Several statewide publishers in the audit expose their inventory as an
ArcGIS FeatureServer/MapServer layer. The adapter is configuration-driven
and state-agnostic (`ArcGisLayerConfig`: endpoint, identifier attribute,
field map, fixed county or county attribute, `where`, page size/cap),
does not fetch (a `fetch_json(url)` callable is injected; the package's
no-HTTP-imports test covers it), pages deterministically (ordered by the
identifier, stopped by `exceededTransferLimit`, capped), records the
endpoint / object id / `where` in each record's provenance, and returns
`COMPLETE`, `EMPTY` (the layer itself returned zero features) or `FAILED`
(transport error, ArcGIS error payload, malformed shape, page cap,
unstable paging, a feature without an identifier) - a failure on any page
discards every page. **No layer is configured**; no endpoint is named in
the repository; running one still requires a `columns_verified`
configuration and `gate.evaluate_source()` allowing the source, which
remains impossible for anything that is not PRODUCTION_VERIFIED.

### 11.6 What is still Florida/Texas-specific, on purpose

- The nine LAFT harvesters, `sync-laft-to-supabase.ps1`, the FDOR enricher,
  `texas_harvester.py` and the LGBS bridge: real sources, not framework.
- `DEFAULT_HARVEST_FILES` / the default status path in the lifecycle
  script (the FL harvesters' outputs); a third state passes its own.
- The Texas copy branches in `app.js` (ledger `tx` overrides, `isTx`
  filter hiding): content for a state that exists, not a switch.
- `regionOf()`'s `|| "FL"` default for a row with no `state`; every real
  row carries one and the RPC is state-scoped, so it is inert.
- Basemaps, centroids, city/zip files, `MINIMAP_PROJ` / `PROJ` fits and
  the two HTML pages exist for FL and TX only. A third state needs its
  own real assets; none is fabricated.

## 12. Purchase path, owner carry and list dates (2026-09-29)

- **Purchase path** (`scripts/laft_lifecycle.py`: `purchase_path_of`,
  `load_registry_purchase_paths`). `purchase_url` + `purchase_url_kind` are
  stamped on an observed row from, in order: (1) the harvester row's own
  `purchase_url`/`purchase_url_kind` - a link the source published for that
  exact property; (2) the registry's source-level path for
  `(source_id, county)` (an application / instructions page verified for
  that county's source); (3) nothing - the keys are omitted from the PATCH
  so an existing value is never nulled. A URL is accepted only if https,
  its kind is in `PurchaseUrlKind`, and it differs from the list and
  document URLs (a list page is never a purchase URL). `otc_provenance.
  purchase_url` records which of the three applied. **No FL harvester
  emits a per-property purchase link and the committed registry carries no
  verified path, so nothing is stamped today** - RealTDM's detail page is a
  POST endpoint, the portals are search grids, and no county page was
  verified from this repository. The frontend (`purchasePathOf` in
  `app.js`) renders PROPERTY kinds (`online_purchase`, `offer_form`,
  `bid_form`) as the one prominent action, INSTRUCTION kinds
  (`purchase_instructions`, `application_form`) and unknown kinds as
  "Application / purchase instructions", and no URL as "No online purchase
  link on file".
- **Owner of record** from the grid harvesters: Pioneer, Osceola and
  St. Lucie emit the list's owner cell as `owners`; `laft_source_fields.
  HARVEST_KEY_ALIASES` reads it for `owner_name` (fill-blank, county_list
  provenance). Previously dropped.
- **Dates**: `laft_source_fields.parse_date` accepts every complete,
  unambiguous shape the lists publish (ISO timestamps, `MM/DD/YY`, spelled
  months, `MM/DD/YYYY hh:mm:ss AM`); incomplete or decorated cells stay
  UNPARSEABLE. The HTML harvester now records a page-stated "as of /
  updated / list date" as the county's `list_as_of` (same
  `laft_status.extract_list_as_of` the PDF harvester uses); the lifecycle
  writes it to `list_as_of`, never the retrieval time.
- **Frontend**: the Inventory & Purchase card is three groups - Inventory
  (type, price, certificate, the 019 dates, list/document, list-as-of,
  published-by, last read), Property (parcel, legal description, name in
  which assessed, assessed / taxable value, acreage, land use, homestead -
  each a stored column or an explicit "Not on file") and Purchase path.

## 13. FDOR enrichment: gates, alternate key, diagnostics (2026-09-29)

`scripts/enrich_property_details.py`:
- **Identifier plausibility gate** before any request: a stored `parcel`
  that fails `laft_status.plausible_identifier` (no digit, over 40
  characters, a line break) is counted `malformed_identifier` and never
  looked up. Such values (a PDF paragraph, a heading fragment) used to spend
  every candidate request on every run.
- **Layer errors are not misses.** An ArcGIS error payload or a body with
  no `features` list raises `FdorUnavailable` (counted
  `source_unavailable`; the county's slice is abandoned for the run, rows
  untouched); a non-JSON body raises `FdorParserRejection` (counted
  `parser_rejection`, the row is skipped). Neither advances a ledger's
  miss streak or stamps a row.
- **Alternate key, county-scoped (`ALT_KEY_RULES`).** Escambia only:
  production evidence (all 45 FDOR-matched Escambia rows carry a 9-digit
  `ALT_KEY` with the county's `dd-dddd-ddd` account-number blocks; its 36
  LienHub certificate rows carry exactly that account shape and never
  match `PARCEL_ID`) supports looking up `ALT_KEY = <digits>` with `CO_NO`
  27, only after every `PARCEL_ID` spelling missed, unique feature only,
  and only when the returned feature's own `ALT_KEY` echoes the value.
  Provenance records `matched_field: "ALT_KEY"`, `matched_alt_key` and the
  layer's `PARCEL_ID`. No other county has a rule; the same shape in Bay,
  Santa Rosa or Okaloosa is never tried.
- **County use code "00" is a value.** `land_use` now uses `_use_code`,
  which keeps an all-zero PA_UC (vacant residential in counties that mirror
  the state scheme) and drops only None, blank and a numeric zero.
- **Diagnostics.** The run prints and writes (`ENRICH_REPORT`, default
  `out/public/fdor-enrichment.json`; a GitHub step-summary table) counts
  for matched / written / already_populated / unmatched / ambiguous /
  malformed_identifier / source_unavailable / parser_rejection / error /
  withheld_by_provenance / alt_key_matches, per-county match rates, and
  per county-and-ledger **identifier shapes** of unmatched rows
  (`d10`, `A1d10`, `d2-d4-d3`): value-free, so a persistent shape can be
  taken to a live verification without a parcel number ever entering a
  public log.

Still blocked pending one live lookup each (no rule was invented):
Hillsborough (`d10` folios on auction/LAFT rows, `A1d10` on certificate
rows; which spelling the layer's `PARCEL_ID` uses is unverified), Citrus
(Pioneer grid strings such as `d2A1d2A1d2 d5 d3A1`; auction rows carry no
parcel at all), Indian River LAFT (`d5-d3` account-style numbers; the
county's `ALT_KEY` is 5-6 digits, so no rule follows), Escambia LAFT
(the clerk's list publishes an empty Parcel ID cell - nothing to match).

## 14. Alabama onboarding foundation (2026-09-29)

Full description: `docs/alabama-onboarding.md`. The stable facts: `AL` is
registered in `harvesters/governance/states.py` as a NON-production state
(representable, never runnable); `ACTIVATION_REQUIREMENTS` (ten items) and
`is_activated()` are consulted by `otc.gate.evaluate_source`,
`CountySourceRow.runnable` and `scripts/laft_lifecycle.py`, so a
registered-but-inactive state is refused before any request; the registry
CSV carries `EXTENDED_COLUMNS` (publishing unit and name, amount kind,
update frequency, source terminology) and one Alabama candidate row with
no URL; `harvesters/otc/adapters/alabama.py` is the adapter contract with
no transport; migration `020_state_extensible_vocabulary.sql` widens the
017/018 constraints and adds the registry columns, and is NOT applied.
