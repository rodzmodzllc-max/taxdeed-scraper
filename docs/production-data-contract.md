# Production data contract

**Status:** Phase 13 (Production Data Contract & Provenance Readiness Gate), 2026-09-14. Companion to `docs/data-licensing.md` (restriction enforcement), `docs/data-provenance.md` (the lineage model), `docs/provenance-production-integration.md` (Phase 12's write-up of how that model is wired into the real pipeline), and `docs/commercial-data-inventory.md` (the source-by-source legal/commercial summary). This page is the one about the *shape* of the data: what fields exist, what they mean, who is allowed to see them, and where each one actually comes from — read this before adding a county, a source, or a field.

## 1. Purpose

Phase 12 wired real `Provenance` construction into the Texas write path. That closed a specific, narrow gap ("no code ever builds a `Provenance` record"). It did not answer a broader question this project has never answered formally: **what, exactly, is `public.properties`'s customer-facing contract — which fields exist, what do they mean, who wrote them, and who is allowed to see them?** Every prior phase built enforcement machinery (`check_ingestion_gate()`, `project_row_for_customer_output()`, `Provenance`) without ever writing down the field-by-field contract those functions are supposed to be protecting. This phase writes that contract down, from the actual code, before any further Texas county expansion or source activation makes the gap harder to close honestly.

This is a **readiness and documentation phase**. It changes no schema, activates no source, and (per Step 23) implements nothing beyond what is needed to test the contract as it already exists.

## 2. Actual architecture (repeated from Phase 12, unchanged)

```
SOURCE (LGBS / RealAuction / FL RealAuction / FL LienHub / FL LAFT PDFs)
  -> NORMALIZED (harvest_*() functions build TexasSaleRow / the FL harvesters' own row shape)
  -> ENRICHED   (scripts/geocode_properties.py [real, cross-state] and
                 scripts/enrich_property_details.py [real, FL-only];
                 scripts/enrich_property_details_tx.py is a non-working stub - see Section 24)
  -> CUSTOMER PROJECTION (the sync scripts' row-building loop - the one real,
                 exercisable write-time enforcement boundary, per Phase 11/12)
  -> public.properties (Supabase, no field-level RLS - see Section 16)
  -> three independent read surfaces: public/app.js (frontend + CSV export),
     the Supabase REST/RPC surface directly, and supabase/functions/send-digest
     (a fixed-shape RPC, digest_candidates())
```

No RAW stage is ever persisted (confirmed again this phase - no harvester writes an unparsed source payload to disk or to Supabase). No server-side DERIVED stage exists (every derived figure - `valueRatio`, `fees`, `buildingValue`, `accruedInterestEst`, `tdaEligibleMs`, `homesteadSurcharge` - is computed client-side in `public/app.js`, never stored).

## 3. Canonical property identity

**The production identity key is `(state, source, county, case_no)`**, enforced by the `properties_state_source_county_case_no_key` UNIQUE constraint added in `scripts/migrations/004_widen_unique_constraint_for_state.sql`, which replaced the earlier, narrower `(source, county, case_no)` constraint. This is confirmed directly from that migration's own SQL body, not inferred.

**`case_no`'s meaning is not uniform across sources** - it is whatever each harvester/sync script chooses to write into it, and that choice differs by source:

| Source | What actually lands in `case_no` | Confirmed via |
|---|---|---|
| `tx_lgbs` / `tx_realauction` | `account_number` - the CAD parcel/account number, per-parcel unique | `scripts/sync-texas-to-supabase.py` line ~222 (`case_no = p.get("account_number")`) |
| FL `auction` (RealAuction/RealForeclose deed sales) | the county's legal case number (`p.case`) | `scripts/sync-harvest-to-supabase.ps1` |
| FL `laft` | the harvester's `case_no` field, falling back to `parcel` when the county publishes no case number | `scripts/sync-laft-to-supabase.ps1` |
| FL `certificate` | the LienHub `account_number` | `scripts/harvest_lienhub_certificates.ps1` line ~189 (`case_no = $d.account_number`), `scripts/sync-certificates-to-supabase.ps1` |

**Texas identity is the one case in this codebase with a live-verified uniqueness finding, not an assumption.** `harvesters/texas_harvester.py`'s own module docstring records that a live LGBS sample showed two different parcels (two different `account_number`s) sharing one `cause_nbr` - a single Texas tax suit routinely covers multiple parcels - so `cause_number` was rejected as the identity key and `account_number` used instead; `cause_number` is written to the DB's `parcel` column, a secondary/display-only identifier. Harris County's own (not-yet-implemented) reconnaissance independently corroborates this exact pattern with real numbers: `claude/harris-hctax-implementation-readiness.md` Section 8 found 122 unique account numbers across 122 live listings (zero duplicates) versus only 115 distinct cause numbers (6 cause numbers each covering more than one account) - i.e., account-number uniqueness and cause-number non-uniqueness are not merely a Phase-9.5-era guess, they are a measured, cited fact for a real Texas county tax sale, independently agreeing with the design already shipped for LGBS.

**Cross-state collision is the specific risk `(state, source, county, case_no)` exists to prevent.** Florida and Texas both have an Orange County, a Jefferson County, a Madison County, and a Lake County; before migration 004 the narrower `(source, county, case_no)` key could let a Texas Orange County row silently overwrite a Florida Orange County row with a colliding `case_no`. This is now closed at the database level, not merely by convention.

**What this section does NOT establish:** a single physical parcel does not have one canonical identity across sources or across states in this data model - the same real property sold once as an FL `laft` case and once (hypothetically, if it re-enters this dataset) as an FL `auction` case would get two independent rows with two independent `id`s, joined by nothing but a human recognizing the same county+address. There is no cross-source parcel-identity resolution anywhere in this codebase, and this phase does not add one.

## 4. Sale/event identity

`properties` models **one sale-event listing**, not a property with a sale history. There is exactly one row per `(state, source, county, case_no)` and every re-sync **upserts into that same row** (`ON CONFLICT ... DO UPDATE`, in every sync script). Confirmed behaviors:

- **Same property, later re-offered at the same source with the same identity key** -> the existing row is updated in place (`bid`/`sale_date` refreshed; hand-researched fields like `owner_name`/`lien_level`/`notes` deliberately left untouched by the safe-merge design documented in every sync script's own header comment). The prior sale's outcome is not retained anywhere once overwritten, except FL auction's own `status`/`gone_since`/`outcome`/`sold_price` fields (Section 10) for the *most recent* close-out event only - there is no history table.
- **Same account/parcel appearing at two different sources** (e.g. hypothetically both `tx_lgbs` and a future `tx_pbfcm`) -> two independent rows, since `source`/`harvester_source` are not part of the identity key comparison that matters here in the way `case_no` is; `(state, source, county, case_no)` treats them as different rows by construction whenever `source` differs, and there is no reconciliation step that would recognize they describe the same parcel.
- **Same account, different county-vendor case_no shape** - not observed in production data as of this phase; not testable without live data, so not asserted either way.

This is a genuine, real architectural limitation worth naming plainly (see Section 24), not resolved by this phase: **the data model conflates "the property" and "the listing" into one row.** A future sale-event/property split (a real design change) is documented as a future option, not built. (Update 2026-09-25: the schema half of that split now exists as migration 014, Section 26 - two empty tables with no writers yet. `properties` itself is unchanged.)

## 5. Field inventory (customer-visible surface)

The authoritative customer-visible field inventory is **the CSV export column list in `public/app.js`** (`exportCsvBtn`'s `cols` array, ~46 columns) - chosen as authoritative because it is the one place in the codebase that already enumerates, by design, "every field a customer is meant to see," rather than a UI card layout (which selectively renders a subset) or a raw `select *` (which returns internal fields too - see Section 14). Every column below is drawn directly from that array, not inferred from a mockup or the roadmap docs.

| Field (DB column) | CSV label | Type | Populated by | Customer-visible | API/export-visible | Classification |
|---|---|---|---|---|---|---|
| `state` (derived: `regionOf(p)`) | State | text | migration 002 (`state` column, default `FL`) | Yes | Yes | PUBLIC |
| `county` | County | text | every harvester | Yes | Yes | PUBLIC |
| `source` | Source | text | every harvester (`auction`/`laft`/`certificate`) | Yes | Yes | PUBLIC |
| `address` | Address | text | every harvester (fallback to legal desc/parcel/case when unpublished); FL enrichment fills junk placeholders | Yes | Yes | PUBLIC / PUBLIC_RESTRICTED (see below) |
| `parcel` | Parcel | text | harvesters (FL: county parcel #; TX: `cause_number`, secondary id, see Section 3) | Yes | Yes | PUBLIC |
| `case_no` | Case/Account # | text | harvesters, identity-bearing (Section 3) | Yes | Yes | PUBLIC |
| `owner_name` | Owner | text | FL enrichment (fill-blank only); some FL certificate/LAFT harvesters | Yes | Yes | PERSONAL (owner-of-record name; see Section 14 note) |
| `status` | Status | text | sync scripts (`active` default); FL auction sync's close-out patch (`closed`) | Yes | Yes | DERIVED (pipeline-computed close-out state, not source-provided) |
| `prop_type` | Property Type | text | FL enrichment (fill-blank) | Yes | Yes | PUBLIC |
| `dor_use_code` | DOR Use Code | text | FL enrichment (`schema-v9-dor-use-code.sql`) | Yes | Yes | PUBLIC |
| `tx_category` | TX Category (SPTB) | text | not currently populated - `enrich_property_details_tx.py` is a non-working stub (Section 24); column exists (migration 002) but no writer runs in production today | Yes (always blank today) | Yes | PUBLIC |
| `lien_level` | Title Status | text (`clean`/`flag`/`serious`/`unscreened`) | hand-research only, via the app's own admin UI (no harvester writes this) | Yes | Yes | DERIVED (this project's own screening judgment, not source data) |
| `homestead` | Homestead Exemption | boolean | FL enrichment only (`JV_HMSTD > 0` -> `true`; never explicitly set `false` - positive evidence only) | Yes | Yes | PUBLIC |
| `bid` | Opening Bid | numeric | every harvester; TX sync sets it equal to `min_bid` (or 0 if unpublished - Section 8) | Yes | Yes | PUBLIC |
| `assessed` | County Assessed Value | numeric | FL enrichment (`AV_NSD`, fill-blank); TX sync (`cad_market_value`, unconditional) - **semantically overloaded, see Section 9** | Yes | Yes | PUBLIC |
| `market` | County Just Value | numeric | FL enrichment only (`JV`, fill-blank) - **never populated for Texas rows** | Yes | Yes | PUBLIC |
| `value_year` | Just Value Year | int | FL enrichment only (`ASMNT_YR`) | Yes | Yes | PUBLIC |
| `min_bid` | TX Min Bid | numeric | TX sync only (`p.get("min_bid")`) | Yes | Yes | PUBLIC |
| `year_built`, `living_area`, `lot_sqft`, `num_buildings`, `land_value`, `last_sale_price`, `last_sale_year` | (various tax-roll columns) | numeric/int | FL enrichment only | Yes | Yes | PUBLIC |
| `legal_desc` | Legal Description | text | FL enrichment (`S_LEGAL`); TX sync (`legal_description`, from LGBS's `sale_notes` - not published by RealAuction, see `FIELD_LINEAGE_MAP`) | Yes | Yes | PUBLIC |
| `sale_date` | Sale/Auction Date | date | every harvester | Yes | Yes | PUBLIC |
| `certificate_no`, `tax_year`, `issued_date`, `expiration_date`, `interest_rate` | Certificate #, Tax Year, Issued Date, Expiration Date, Interest Rate | text/date/numeric | FL certificate harvester only | Yes | Yes | PUBLIC |
| `redemption_period_months`, `redemption_expiration_date`, `max_statutory_return_usd` | TX Redemption Period/Expires/Max Statutory Return | int/date/numeric | not currently populated - enrichment-time fields, no writer runs in production today (same gap as `tx_category`) | Yes (always blank today) | Yes | DERIVED (statutory formula, not source-provided, once a writer exists) |
| `latitude`, `longitude` | (feed Street View link, not a raw column export) | double | LGBS (source-provided, real per-parcel coords) or `scripts/geocode_properties.py` (ENRICHED, Census Geocoder, fill-blank only) | Yes (via derived Street View URL) | via API only | PUBLIC |
| `url_appraiser` | Appraiser | text | FL deed harvester | Yes | Yes | PUBLIC |
| `url_auction` | Auction/LAFT Listing | text | every harvester (LAFT/auction) | Yes | Yes | PUBLIC |
| `url_taxcoll`, `url_title` | Tax Collector, Title Search | text | not currently populated by any harvester - always blank | Yes (always blank today) | Yes | PUBLIC |
| `url_streetview`, `url_zillow` | (feed fallback link functions) | text | not currently populated by any harvester; `app.js`'s `fallbackStreetviewUrl()`/`fallbackZillowUrl()` construct a client-side search-URL substitute when absent | Yes (via fallback) | via API only | PUBLIC |

Derived, never-stored fields computed client-side only (not columns): `valueRatio` (Gross Equity Spread x bid), the dollar equity-spread figure, `fees`, `buildingValue` (Just Value − Land Value), `accruedInterestEst`, `tdaEligibleMs`/TDA Eligibility Date, `homesteadSurcharge`, `maxBid`. All appear in the CSV export as computed columns, never as a stored value a future reader could query directly in Supabase.

## 6. Internal / not-customer-facing fields

`harvester_source`, `ledger_type`, `fdor_enriched_at` are written to `public.properties` but **never read, rendered, or exported by any `public/app.js` code path** (confirmed: zero matches for any of these three names anywhere in `app.js` outside comments about the migrations that added them). They are internal in the sense of "the frontend's own code never surfaces them" - **not** in the sense of being access-controlled. See Section 16's fail-open finding: because `get_properties()`/`select("*")` return every column with no field-level RLS, these three columns are actually transmitted to every approved browser client today; only the frontend's own choice not to render them keeps them out of the UI and the CSV. This is a real, load-bearing distinction for the READINESS DECISION (Section 30) - "internal" here is a code convention, not a security boundary.

## 7. Source-of-truth rules

- **Direct/unambiguous:** `case_no` (Section 3), `sale_date`, `owner_name`, `certificate_no`/`tax_year`/`issued_date`/`expiration_date`/`interest_rate` (FL certificates), `min_bid`/`legal_desc` (TX) - each has exactly one writer.
- **Fallback chain (source, then enrichment, never overwritten once set):** `address` (junk-placeholder replacement only, FL enrichment), `latitude`/`longitude` (LGBS direct > Census Geocoder fill-blank, cross-state), `market`/`assessed`/`owner_name`/`year_built`/etc. (FL enrichment, fill-blank only - `enrich_property_details.py`'s `build_update_fields()` checks `_num(row.get(column)) is None` / `not _text(row.get(column))` before ever writing).
- **Derivation (never source-provided, computed downstream):** `status`'s `closed` value (FL auction sync's own close-out patch, Section 10), `lien_level` (hand-research via the app's admin UI, never a harvester), every client-side-only derived figure in Section 5.
- **Genuinely ambiguous, documented rather than resolved:** `assessed` (Section 9 - two different real-world meanings share one column across states); `tx_category`/redemption fields (columns exist, no current writer - Section 24).

## 8. Normalization rules

| Field | Raw representation | Normalized representation | Where |
|---|---|---|---|
| County | free-text per vendor (`"Harris"`, `"HARRIS COUNTY"`, etc.) | title-cased canonical county name | `_lgbs_normalize_county()` (LGBS); FL harvesters' own per-vendor normalization (not re-audited this phase - out of scope, unchanged) |
| State | n/a (implicit before migration 002) | 2-letter USPS code, `FL`/`TX` | migration 002 (default `FL` for backward compatibility) |
| Bid/value figures | vendor-formatted currency strings (`"$1,234.56"`, stray whitespace) | `float`/`numeric` | `_lgbs_to_float()`/`_realauction_to_float()` (TX); `ToNum()` (FL PowerShell, strips non-digit/`.` characters) |
| Dates | vendor-specific format (`MM/dd/yyyy`, a `dayid` attribute, etc.) | ISO `YYYY-MM-DD` | `ConvertTo-IsoDate`/`ConvertTo-IsoDateFlexible` (FL PowerShell, tries multiple formats); `_realauction_date_to_iso()` (TX); `sync-texas-to-supabase.py`'s `_iso_date_or_none()` additionally validates the shape with a regex before ever sending it, rejecting anything that isn't already a clean ISO string rather than attempting to reparse it |
| Null/missing numeric | absent field, empty string, or a vendor sentinel (FDOR uses `0` as its own "no data" marker) | `NULL` in Postgres | FL enrichment explicitly maps FDOR's `0` sentinel to `None` before writing (see `app.js`'s own comment on this, Section 9 of that file) so a real `$0` is never confused with "not on the roll" |
| Address | multiple raw fields, vendor-specific | one composed string (`_lgbs_compose_address()`) or a documented fallback chain (case/parcel/legal-desc placeholder text) when no real address is published | every harvester |

This phase made **no normalization changes** - the table above documents existing behavior, per Step 7's own instruction.

## 9. Null / unknown semantics

This codebase has exactly one representable "missing" state at the database level: SQL `NULL`. There is no `UNKNOWN`/`NOT_APPLICABLE`/`NOT_PROVIDED`/`NOT_PERMITTED` value anywhere in the schema, and this phase does not add one (Step 8 forbids introducing new database values). Instead, "missing" is represented three different, documented ways depending on the field, and confusing them is a real, historically-hit bug class in this codebase:

1. **Genuine `NULL`** - the normal case for most enrichment/optional fields. FL enrichment is careful about this: FDOR's own `0`-as-sentinel is explicitly translated to `NULL` before writing, specifically so a real `$0` last-sale-price is never rendered identically to "not on the tax roll" (see Section 8).
2. **A sentinel value standing in for `NULL` at write time, because the column is `NOT NULL` with no default** - `bid` and `address` on the `properties` table have no database default (confirmed live behavior documented in `sync-laft-to-supabase.ps1`'s own comment: omitting `bid` entirely, not just sending an explicit null, still failed with a not-null-constraint violation). Every sync script therefore substitutes `0` for a missing `bid` and a fallback string (parcel #, case #, or `"Address not published - see county PDF"`) for a missing `address`. **The frontend then has to reconstruct "was this actually published?" from that sentinel** - `hasPublishedBid(p)` treats `bid === 0` identically to "not published," never as "free." This is a real, working, but fragile pattern: a genuinely `$0` opening bid (which is not a documented real-world case for any current source, but is not provably impossible for a future one) would be silently mis-displayed as "Not published."
3. **A junk placeholder string standing in for "the county didn't publish this"** - `address` again, but for a different reason than (2): several counties' own listings contain literal placeholder text (`"NO STREET COUNTY"`, `"Case Account"`, column-header text picked up by mistake) rather than an empty field. `app.js`'s `JUNK_ADDRESSES` denylist and `realAddress()` function exist specifically to distinguish a real address from this kind of "technically non-null, semantically missing" value; FL enrichment's own junk-detection (`is_junk_address()`) does the equivalent check before deciding whether to fill in a value from the state cadastral layer.

**"Invalid" is not the same as "missing" anywhere in this codebase**, and this phase does not conflate them: a numeric field that fails to parse (e.g. `_lgbs_to_float()` given unparseable text) becomes `None`/`NULL` (missing), not a raised error and not a stored invalid string - the same fail-quiet-to-null discipline runs through every normalization function audited in Section 8.

## 10. Value semantics

This is the one place this phase found a genuine, previously-undocumented semantic collision, and it is documented here rather than silently collapsed (Step 9's explicit instruction):

**`assessed` carries two different real-world meanings depending on state, under one column name.**

- For Florida rows, `assessed` is written only by `scripts/enrich_property_details.py`, fill-blank-only, from FDOR's `AV_NSD` field - the county property appraiser's own statutory assessed value (non-school-district), a specific, defined term in Florida ad valorem tax law.
- For Texas rows, `assessed` is written unconditionally by `scripts/sync-texas-to-supabase.py` from `cad_market_value` - which itself is not one consistent concept: for `tx_lgbs` rows it is LGBS's raw `value` field (an unverified label - LGBS's API does not itself define what "value" means), and for `tx_realauction` rows it is literally RealAuction's own **"Adjudged Value"** field - a court-adjudged value set for purposes of the sale, a different legal concept from an appraisal district's independently-assessed market value, even though both get funneled into the same `cad_market_value` TexasSaleRow field and then the same `assessed` DB column.

Because `market` is never populated for Texas rows (Section 5), `app.js`'s `valueLabel()` falls back to the "County Assessed Value" label for every Texas property - so a Texas card/export literally displaying "County Assessed Value" is, depending on the source, showing either an appraisal district's raw `value` field or a county's own court-adjudged sale value, neither of which is Florida's `AV_NSD` concept the label was written to describe. **This phase does not fix this** (Step 7 forbids changing production behavior to resolve a documentation ambiguity) - it is recorded here as a known, real limitation (Section 24) for a future relabeling/field-split decision.

Other value fields, confirmed distinct and NOT collapsed:
- `min_bid` (TX court-ordered statutory minimum, Tex. Tax Code 34.01/34.05) vs `bid` (cross-state "opening bid" concept) - the sync script deliberately sets both from the same number (documented in that script's own module docstring as an intentional, honest overlap, not a bug) because Texas's minimum bid genuinely plays both roles.
- `market` (FL `JV`, statutory "just value" for a stated roll year) vs `assessed` (FL `AV_NSD`) - two different, real FDOR fields, never conflated on the Florida side.
- `land_value` (FDOR `LND_VAL`) vs the client-computed `buildingValue` (`market - land_value`) - a real subtraction of two independently-sourced numbers, not itself stored.

## 11. Date contract

- **Event date** (`sale_date`, `issued_date`, `expiration_date`) - when something happens/happened in the real world (an auction, a certificate's issuance/expiration), as published by the source. Normalized to ISO `YYYY-MM-DD` (Section 8); no time-of-day is captured for any current field.
- **Retrieval/processing timestamp** - Phase 12's `retrieved_at`, generated fresh by each of `harvesters/texas_harvester.py`'s `main()` and `scripts/sync-texas-to-supabase.py`'s own run, in each case labeled honestly as "when this process ran," never claimed to be "when the vendor's data changed." **Not stored in Supabase** - pipeline-side/audit-log only (unchanged from Phase 12; Step 11 forbids storing new timestamps this phase too).
- **`updated_at`** - referenced throughout `app.js` (`STALE_DATA_HOURS`, the "Data updated" freshness banner) as a per-row timestamp Postgres appears to maintain automatically on every upsert. No migration file in this repository's tracked history defines this column or the trigger that would maintain it (see Section 24's honest note on undocumented-in-repo schema) - its exact update semantics (does every column-touching upsert bump it, even a no-op safe-merge upsert that changes nothing?) could not be confirmed from code in this repository and are recorded here as **genuinely unknown**, not assumed.
- **`gone_since`** - referenced by `app.js` (`goneExpired()`) as the timestamp a property left the `active` status; same as `updated_at`, referenced by frontend code with no accompanying migration file in this repo to confirm exactly which write path sets it or how.

This phase adds no new persisted timestamp field (Step 11).

## 12. Status contract

`status` is a free-text column with **exactly three values confirmed to be actually emitted by any current writer**: `active` (the implicit Postgres column default every sync script relies on, per every sync script's own "brand-new properties get the table default" comment), and `closed` (written only by `sync-harvest-to-supabase.ps1`'s own close-out step, for FL `auction` rows whose sale date has passed and which no longer appear in the day's harvest). No harvester or sync script anywhere in this codebase currently writes `status='dropped'`, `'sold'`, or `'notfound'`, even though `app.js`'s own `GONE_STATUSES = ["dropped", "sold", "notfound", "closed"]` constant defensively includes all four - `app.js`'s own comment on this (`outcomeText()`, line ~84) states plainly: "The harvesters do not capture it yet: `status` only ever holds active/closed/dropped[sic - dropped is also not currently emitted per the writer audit above], and there is no column for the winning bid." **This phase does not resolve that gap** - it documents the frontend's forward-looking, currently-inert defensive handling exactly as it exists, and flags it as an open item (Section 24), not a bug this phase fixes.

`outcome`/`sold_price` (feeding `outcomeText()`) are likewise referenced defensively by the frontend but are not written by any current harvester or sync script found in this repository - real, but currently always-null, columns.

Per Step 10's own explicit instruction, this phase does not touch Harris/`tx_hctax`'s unresolved sale-type/status semantics (Phase 9.5) - `tx_hctax` has no harvester and does not enter this pipeline at all.

## 13. Provenance contract

Connecting Phase 12's `Provenance` construction to the field inventory above:

| Field category | Provenance classification | Why |
|---|---|---|
| Identity/source-published fields (`case_no`, `parcel`, `address`, `bid`, `min_bid`, `legal_desc`, `sale_date`, and every FL-source-specific field with exactly one writer, Section 7) | **SOURCE** | Comes straight from the harvester's parse of the vendor's own listing, per `FIELD_LINEAGE_MAP` (TX) or the equivalent per-field writer audit (FL, Section 7) |
| `latitude`/`longitude` | **SOURCE** (LGBS) or **ENRICHED** (Census Geocoder fill-blank, or FDOR parcel-centroid fill-blank for FL) | Depends on which writer actually set it for a given row - both paths are real and distinguished in Sections 5/7 |
| `market`, `assessed` (FL only), `owner_name` (fill-blank), `prop_type`, `dor_use_code`, `year_built`, `living_area`, `lot_sqft`, `num_buildings`, `land_value`, `last_sale_price`, `last_sale_year`, `value_year`, `homestead` | **ENRICHED** | `scripts/enrich_property_details.py`, a second source (FDOR Statewide Cadastral), fill-blank only |
| `assessed` (TX) | **SOURCE** (not enrichment - written directly from the harvest, unconditionally, at sync time - see Section 9's semantic-collision note) | This is itself a documentation-worthy quirk: the *same DB column* is ENRICHED for FL rows and SOURCE for TX rows |
| `status` (`closed` value), `lien_level` | **DERIVED** | Computed by this project's own logic (a close-out diff, or hand-research), not retrieved from any source |
| every client-side-only figure in Section 5 | **DERIVED**, never persisted | Computed in the browser on every render, from already-fetched SOURCE/ENRICHED values |
| `tx_category`, redemption fields | **N/A today** (no writer exists) | Would be ENRICHED/DERIVED respectively once a real writer is built - not yet real |

This table answers, for any current customer-visible field, "why is this value in the customer dataset" without reverse-engineering the harvester - Section 1's stated goal. It is a **static documentation artifact**, matching Phase 12's own field-lineage design choice (`FIELD_LINEAGE_MAP` as data, not per-field runtime `Provenance` objects) - nothing here changes Phase 12's implementation.

## 14. Restriction contract

Verified this phase, against the actual functions (not re-derived from scratch - `harvesters/governance/gate.py`/`restrictions.py`, unchanged since Phase 11/12, `harvesters/governance/registry.py` byte-for-byte untouched):

- **Source restriction -> field restriction**: `project_row_for_customer_output()`/`project_row_for_api_export()` apply a source's whole-row blocking restrictions (`BLOCKS_CUSTOMER_DISPLAY`/`BLOCKS_API_EXPORT`) first, then `_strip_restricted_field_shapes()` removes any individual field whose *name* matches `FIELD_SHAPE_KEYWORDS` for a restriction that source actually carries.
- **No restriction can disappear via rename/normalize/enrich/derive/copy/transform**, by construction: restrictions live on the `SourceRecord`/`GateDecision`, not on any individual field value, and every derived/enriched field in this codebase (Section 5) still traces back to `harvester_source`, which is what every enforcement/lineage function actually keys off - there is no code path where a field changes its `harvester_source` attribution partway through the pipeline.
- **Verified against the real customer-facing row shape, not just `TexasSaleRow`**: this phase confirmed (new test, Section 21) that none of `FIELD_SHAPE_KEYWORDS`'s keywords (`image`, `photo`, `html`, `document`, etc.) match any key in the actual dict `scripts/sync-texas-to-supabase.py` builds for the Supabase upsert (`state`, `source`, `county`, `case_no`, `parcel`, `address`, `bid`, `min_bid`, `assessed`, `sale_date`, `legal_desc`, optionally `harvester_source`/`latitude`/`longitude`) - extending Phase 11's existing `TexasSaleRow`-only inertness test to the actual downstream dict shape, which is what really reaches the projection function.
- **Zero registry entries carry any restriction today** (`tx_lgbs`/`tx_realauction` both `APPROVED`, zero restrictions) - every restriction-enforcement code path audited above is therefore, today, a verified no-op for production data, exactly as Phase 11 documented. This phase changes none of that.

## 15. Customer-visible vs internal fields

See Sections 5 and 6 for the full breakdown. Summarizing the three buckets Step 14 asks for:

- **Customer-visible (intentional)**: every field in Section 5's table - the CSV export's ~46 columns, which this phase treats as the authoritative definition of "the product's customer-facing contract."
- **Internal (code-convention only, not access-controlled)**: `harvester_source`, `ledger_type`, `fdor_enriched_at`, `id` (UUID, used only for joins to `notes`/`favorites`/`hidden`/`bid_list`, never displayed as a field itself), `updated_at` (used only to compute freshness banners, never shown as a raw value). **None of these are hidden from the wire** - see Section 16.
- **Future (column exists, not yet part of the live product contract)**: `tx_category`, `redemption_period_months`, `redemption_expiration_date`, `max_statutory_return_usd`, `outcome`, `sold_price` - all appear in the CSV export or frontend code already (so they ARE part of the *declared* contract), but have no current writer, so they are always blank in practice today.

## 16. API contract

Every real read surface in this codebase, confirmed by inspection:

| Surface | Mechanism | Projection/filtering applied | Auth |
|---|---|---|---|
| `public/app.js` (`fetchProperties()`) | `sb.rpc("get_properties", {p_state})`, falling back to unscoped `sb.from("properties").select("*")` if the RPC doesn't exist yet | State-scoped only (`get_properties()`'s SQL body is `select * from properties where state = p_state ...` - **no column projection, no field-level filtering of any kind**); the fallback path has no scoping at all beyond RLS | Supabase Auth (RLS: `is_approved()` restrictive policy) |
| `public/app.js` (CSV export) | reads the already-fetched `ALL` array in memory - same rows `fetchProperties()` returned, no separate query | Client-side column selection only (Section 5's ~46-column list) - **every column is already present in the browser's memory before this filtering happens**, since `get_properties()`/`select("*")` returned the whole row | Same as above (already-authenticated session) |
| Supabase REST directly (`/rest/v1/properties`) | any authenticated client, not just this app's own frontend | RLS only (`is_approved()`) - **no field-level restriction of any kind exists at this layer** | Supabase Auth |
| `supabase/functions/send-digest` (`digest_candidates()` RPC) | Deno Edge Function, `service_role`-privileged, bypasses RLS entirely | **Fixed by the SQL function's own `returns table (...)` clause** (`schema-v5-digest.sql`): `user_id, property_id, county, address, case_no, bid, market, sale_date, url_auction, days_out` - this is the one read surface in the whole codebase with genuine column-level projection, because it is implemented as a typed SQL function rather than a raw table read | `service_role` only (`revoke all ... from public, anon, authenticated`), invoked by a scheduled job, not by any user-facing request |
| `notes`/`favorites`/`hidden`/`bid_list`/`county_calendar` | `sb.from(...).select(...)` | RLS: `favorites`/`hidden`/`bid_list` are fully private per-user (`user_id = auth.uid()`); `notes`/`county_calendar` are shared-visibility, own-row edit/delete | Supabase Auth |

**The load-bearing finding of this section**: `get_properties()` and the unscoped fallback both return `select *` - there is no field-level RLS or column-level view anywhere in this stack. This means Section 6's "internal" fields (`harvester_source`, `ledger_type`, `fdor_enriched_at`) are **not actually hidden from any approved user** - they simply aren't rendered by this particular frontend. A different client calling the same Supabase REST endpoint with the same credentials would see them. This is unchanged by this phase (Step 16 forbids modifying RLS) and is recorded here as the honest state of the API contract, not remediated.

## 17. Export contract

The CSV export (Section 5) is built entirely from the browser's already-fetched `ALL` array (Section 16) - it makes no separate network request and applies no server-side filtering of its own. Verified this phase:

- **Provenance is excluded** - `Provenance` objects are pipeline-side only (Phase 12) and never reach Supabase at all, so there is nothing for the export to leak even in principle.
- **Governance metadata is excluded** - same reasoning; `SourceRecord`/`GateDecision`/`Restriction` values are Python-side-only and never serialized into any row this export could read.
- **Internal fields are excluded from the *rendered* columns** (Section 6) but, per Section 16, are present in the underlying `ALL` array the export code has access to in memory - the export's exclusion of `harvester_source`/`ledger_type`/`fdor_enriched_at` is enforced by the `cols` array simply not naming them, not by any inability to read them.
- **Restricted fields cannot bypass projection** at the point they enter Supabase (Section 14) - but see Section 16's finding: if a future restricted field ever were written to `properties` in error (a projection bug, or a future source added without re-verifying inertness), the CSV export and the raw REST endpoint would both surface it identically, since export applies no restriction-awareness of its own, only column selection.
- **Null semantics remain consistent** (Section 9) - the export's `?? ""` pattern renders `NULL`/`undefined` as an empty CSV cell uniformly across all 46 columns, never converting a stored `NULL` into a `0` or vice versa at export time (the `0`-as-"not published" sentinel, where it exists, was already baked in at write time - Section 9).
- **Field ordering is stable** - the `cols` array is a fixed literal order in source, not derived from object key iteration order, so re-runs are byte-stable column-for-column.

## 18. Frontend contract

Confirmed by inspection of `public/app.js` (not redesigned - Step 17):

- **Queried**: every column `get_properties()`/`select("*")` returns (all of `properties`), plus `notes`/`favorites`/`hidden`/`county_calendar`/`bid_list` via separate parallel queries in `loadAll()`.
- **Displayed**: the card-rendering functions read a large but not-exhaustive subset of `properties` columns directly (`address`, `parcel`, `case_no`, `owner_name`, `status`, `prop_type`, `bid`, `market`/`assessed`, `sale_date`, `lien_level`, `homestead`, the tax-roll spec fields, certificate fields, TX yield-desk fields) plus every client-derived figure (Section 5).
- **Filtered**: `county`, `prop_type` (via `propType()` bucketing), `lien_level`, `assessed` (min threshold), `status` (via `statusView`/`GONE_STATUSES`/`isGone()`), free-text `search`, `favoritesOnly`, `state` (via `PAGE_STATE`, both server-side through `get_properties(p_state)` and client-side through `regionOf()` as a defense-in-depth check documented in the RPC comment itself).
- **Sorted**: via `sortRows()` (not itself audited field-by-field this phase - out of scope, unchanged).
- **Exported**: Section 5/17.
- **Calculated client-side**: every figure in Section 5's "derived, never-stored" list.

The product contract (what a user can see/filter/export) matches the actual data contract documented in Sections 5-17 above - this section is the cross-check that no frontend behavior implies a field this document doesn't already account for, and none was found.

## 19. Data-quality invariants

Machine-testable invariants for the current production dataset, grounded in what the actual write paths enforce or assume (not universal rules invented for their own sake - Step 18's own caution):

- `state` is one of `'FL'`/`'TX'` for every row written by a harvester in this codebase today (no third state exists yet).
- `county` is present (every sync script skips a row missing `county`).
- `source` is registered against a known `harvester_source` in `SOURCE_REGISTRY` for every Texas row (enforced live, at write time, by `check_ingestion_gate()` - Phase 10A/11/12); Florida rows have no equivalent registry check (Florida's pipeline has zero coupling to `harvesters.governance`, confirmed again this phase).
- An `APPROVED`/`APPROVED_WITH_RESTRICTIONS` source is required for a Texas row to reach `properties` at all (Phase 10A's ingestion gate, still enforced, still the same two statuses).
- `case_no` is present when the source provides an identity value; every sync script explicitly skips a row missing it (or, for FL LAFT, missing both `case_no` and `parcel`).
- `sale_date`, when present, is a valid ISO date (`_iso_date_or_none()`'s regex check, TX; `ConvertTo-IsoDate`'s try/catch-and-drop pattern, FL - an unparseable date becomes `NULL`, never a malformed string, Section 9).
- Numeric fields (`bid`, `assessed`, `market`, `min_bid`, etc.) are genuinely numeric or `NULL` - every normalization function fails quiet-to-`NULL` rather than storing a non-numeric string (Section 8/9).
- `latitude`/`longitude`, when present, fall within a real-world sanity bound - confirmed only for the FL enrichment path (`24.0 <= lat <= 31.5 and -88.0 <= lon <= -79.5`, explicitly Florida-bounded); **no equivalent bound is enforced for TX coordinates** anywhere in this codebase (LGBS's coordinates are trusted as-is; `geocode_properties.py`'s Census Geocoder path is state-agnostic and applies no bound at all for either state). This is a real, previously-undocumented gap, noted here rather than silently assumed safe (see Section 24).
- `bid`, when present and non-`NULL`, is non-negative in every code path audited (no normalization function can produce a negative number from a currency string; the `0`-as-sentinel pattern, Section 9, is the only intentional non-representative value).

"Invalid" (fails a format/parse check) is kept distinct from "missing" (genuinely absent) throughout, per Section 9.

## 20. Texas source matrix

| | `tx_lgbs` | `tx_realauction` |
|---|---|---|
| Fields provided | `account_number`, `county`, `auction_date`, `min_bid`, `cad_market_value` ("value" field), `legal_description`, `address` (composed), `cause_number`, `latitude`/`longitude` (real, per-parcel), `source` (via status mapping) | `account_number`, `county` (from the source CSV row, not a per-listing field), `auction_date`, `min_bid` ("Est. Min. Bid"), `cad_market_value` ("Adjudged Value" - see Section 9), `address`; **not published**: `legal_description`, `latitude`/`longitude` |
| Identity field | `account_number` -> DB `case_no` | same |
| Secondary/display id | `cause_number` -> DB `parcel` | same |
| Valuation fields | `min_bid`, `cad_market_value` (raw `"value"`, semantics not independently verified - Section 9) | `min_bid`, `cad_market_value` (RealAuction's own "Adjudged Value" - Section 9) |
| Status/ledger field | `status`, mapped via `LGBS_STATUS_TO_LEDGER` | constant `'auction'` (no struck-off/resale feed for this vendor - `harvest_realauction()`'s own docstring) |
| Source URL | LGBS `property_sales` API (`https://taxsales.lgbs.com/api/property_sales/`) | per-county RealAuction/RealForeclose instance URL |
| Provenance capability | Real - `build_row_provenance()`, Phase 12 | same |
| Enrichment | None needed for coordinates (source-provided); no CAD enrichment runs in production (Section 24) | `scripts/geocode_properties.py` (cross-state, fill-blank) is the only real enrichment this source's rows receive |
| Known limitations | `"value"` field's exact real-world meaning not independently confirmed against LGBS's own documentation (none was found - see `docs/lgbs-rights-audit.md`) | No coordinates, no legal description at all - permanently reliant on Census-Geocoder fill-blank for any map placement |
| Governance status | `APPROVED`; formally rights-reviewed Phase 10B, approval basis requires legal review (`docs/lgbs-rights-audit.md`) | `APPROVED`; formally rights-reviewed Phase 10B, approval basis requires legal review (`docs/realauction-rights-audit.md`) |
| Scheduling reality | **Manual only** (`workflow_dispatch`), not on any cron schedule - `.github/workflows/harvest-and-sync.yml`'s `texas` job `if:` condition is `github.event_name == 'workflow_dispatch'` with no `schedule` branch, unlike every FL job. A Texas row's freshness therefore depends entirely on someone manually triggering the workflow - there is no guaranteed refresh cadence today, in contrast to FL's twice-daily/daily cron schedule. This is a genuine, previously-unstated-as-plainly production-freshness fact, confirmed directly from the workflow file, not assumed from `docs/commercial-data-inventory.md`'s "in production today? Yes" language (which is true in the sense that the code path is live and has been run against production - see `scripts/migration-002-003-004-execution-plan.md` - but does not mean "runs on a schedule"). |

Blocked/unresolved Texas sources (`tx_hctax`, `tx_pbfcm`, `tx_govease`, `tx_mvba`, `tx_ctsa`) are intentionally **not** included in this production matrix - see `docs/commercial-data-inventory.md`'s own inventory table for their status. None was activated, contacted, or reconsidered this phase.

## 21. Florida source matrix

| | `fl_realauction` (auction) | `fl_laft_pdfs` (+ 8 sibling LAFT harvesters) | `fl_lienhub_certificates` |
|---|---|---|---|
| Fields provided | `case_no` (legal case #), `parcel`, `address`, `bid`, `assessed`, `sale_date`, `url_appraiser`, `url_auction` | `case_no` (or `parcel` fallback), `parcel`, `address` (or legal-desc/parcel/case fallback), `bid` (0 if unpublished), `sale_date`, `url_auction` | `case_no` (=`account_number`), `certificate_no`, `tax_year`, `issued_date`, `expiration_date`, `bid`, `address` (or `"Account {case_no}"` fallback), `owner_name`, `parcel`, `assessed`, `interest_rate`, `url_auction` |
| Identity field | `case_no` = the county's legal case number | `case_no` (or `parcel` when no case number is published) | `case_no` = LienHub's own `account_number` |
| Enrichment | `scripts/enrich_property_details.py` (FDOR statewide cadastral - `prop_type`, `dor_use_code`, `market`, fill-blank `assessed`/`owner_name`/`latitude`/`longitude`, tax-roll spec fields) + `scripts/geocode_properties.py` (Census fallback) | same two enrichment scripts (state-agnostic on the geocoder; FDOR enrichment has no `source` filter either, confirmed by inspection) | same two enrichment scripts |
| Governance status | `APPROVED` (grandfathered) - production-approved by existing practice, **not formally rights-audited** (Phase 10B's audit scope was the two TX sources only) | same | same |
| Scheduling | Cron, twice daily (`0 10,22 * * *` UTC) + `workflow_dispatch` | Cron, once daily (`0 12 * * *` UTC) + `workflow_dispatch` | Cron, once daily (`0 12 * * *` UTC) + `workflow_dispatch` (job historically marked "experimental," resolved 2026-08-25 per `CLAUDE.md`) |
| Known limitations | Close-out (`status='closed'`) can only say a listing left the feed, never distinguish redeemed/canceled/sold (Section 12) | ~35 counties remain uncovered by any of the nine current LAFT harvesters (documented gap, unchanged, out of this phase's scope) | none newly found this phase beyond the existing documented ones |

Florida's harvesters are PowerShell (`.ps1`), have zero coupling to `harvesters.governance` (re-confirmed this phase, same check as every prior phase), and were not touched.

## 22. Future source onboarding contract

Generalizing `docs/source-registry.md`'s existing six-step process (unchanged, cross-referenced here) into the minimum gate a future source or county must clear before implementation, using only vocabulary this codebase already has (no new classification invented):

1. **Source identity** - a `source_id` matching the existing `harvester_source` convention (e.g. `tx_pbfcm`).
2. **Legal/commercial status** - a `SourceRecord` entry with a real `legal_status` (one of the existing `SourceStatus` values) and, where the status is anything but a clean `APPROVED`, the honest free-text `commercial_use_status` caveat this project already uses for `tx_lgbs`/`tx_realauction` ("approval basis requires legal review").
3. **Automation status** - confirmed technical accessibility (a real API/page fetch), independent of legal status per this project's own repeated "technical accessibility is never legal permission" principle.
4. **Storage status** - explicit: is raw payload ever persisted? (Today: no, for any source - Section 2.)
5. **Redistribution status** - which `Restriction` values, if any, apply (`restrictions.py`'s existing vocabulary - no new restriction type needed unless a genuinely new kind of contractual limit is found).
6. **Field inventory** - a `FIELD_LINEAGE_MAP`-shaped table (Section 13's pattern) mapping every field the new source's harvester will populate to its real source-field name, following `harvest_lgbs()`/`harvest_realauction()`'s pattern exactly.
7. **Identity mapping** - which raw field becomes `case_no` (the uniqueness-bearing identity, Section 3) and which becomes `parcel` (secondary/display) - live-verified for uniqueness the way `tx_lgbs`'s `account_number` was (Section 3), not assumed from vendor documentation alone.
8. **Provenance mapping** - confirm `build_row_provenance()` (or its FL equivalent, were one ever built) can represent this source without a code change; if it can't, that is itself a finding to report, not a reason to build a second provenance system (Phase 12's explicit rule, unchanged).
9. **Restriction mapping** - confirm the new source's row shape against `FIELD_SHAPE_KEYWORDS` (Section 14's pattern) the way this phase re-verified for the existing sync-script row shape.
10. **Completeness strategy** - does the harvester walk every page/record, or is coverage partial by design (e.g. a `BATCH_LIMIT`)? Document it, per the fairness/anti-starvation pattern `geocode_properties.py`/`enrich_property_details.py` already establish.
11. **Freshness strategy** - is the harvest job on a real cron schedule, or manual-only (Section 20's Texas finding)? State it plainly rather than letting `docs/commercial-data-inventory.md`'s "in production" language stand in for it.
12. **Reconciliation strategy** - if this source can produce a row identity-colliding with an existing one from a *different* source (Section 4's finding: there is none today), document how that is prevented or accepted.
13. **Tests** - a lettered test matrix in `tests/python/`, following the A-J pattern this phase and Phase 11/12 already established, picked up automatically by CI (no workflow change needed, confirmed this phase - Section 23).
14. **Approval** - explicit human sign-off before `legal_status` is ever set to `APPROVED`/`APPROVED_WITH_RESTRICTIONS`, per every prior phase's hard rule that this project never makes its own legal determination.

## 23. Tests

New this phase: `tests/python/test_production_data_contract.py`, a lettered matrix (A-J), 17 tests, added to the existing `pytest tests/python/` suite (now 92 tests total - 75 pre-existing + 17 new). No workflow change needed - `.github/workflows/python-governance-test.yml` already targets the whole directory. Coverage, by letter:

- **A - Identity**: the `(state, source, county, case_no)` constraint text in migration 004; `account_number`->`case_no`/`cause_number`->`parcel` mapping in the sync script's actual source.
- **B - Field contract**: the CSV export's column list, read directly from `public/app.js`, contains a required baseline of canonical fields and never contains any of the internal-only column names (Section 6).
- **C - Field lineage completeness**: `FIELD_LINEAGE_MAP`'s keys stay in sync with `TexasSaleRow`'s actual content fields (catches future drift the way Phase 12's own `test_B` caught a stale string this session).
- **D - Null semantics**: the `bid`-missing-becomes-`0` sentinel and the frontend's `hasPublishedBid()` treatment of it, both confirmed by reading the real source text (not re-implemented as a parallel Python model that could drift from the real code).
- **E - Value semantics**: `market` is never written by the TX sync path; `assessed` is written unconditionally by TX and fill-blank-only by FL enrichment - the Section 9 finding, made regression-proof.
- **F - Status contract**: `GONE_STATUSES`'s real contents and the frontend's own "not currently emitted" comment, both read from source.
- **G - Restriction/provenance leak**: the full sync-script row-dict shape (not just `TexasSaleRow`) is confirmed inert against `FIELD_SHAPE_KEYWORDS`; no `Provenance`-dataclass field name appears in the CSV export's column list.
- **H - Production reality**: the Texas job's `workflow_dispatch`-only `if:` condition vs. the FL jobs' cron schedules, read directly from the workflow YAML.
- **I - API contract**: `send-digest`'s RPC field list matches its own SQL definition (`schema-v5-digest.sql`) and the Edge Function's own `Row` type, and does not silently grow to include a field neither of those declares.
- **J - FL field coverage**: every field this phase's Section 5 inventory attributes to FL enrichment is actually written somewhere in `enrich_property_details.py`'s `build_update_fields()` (extends the same doc-sync discipline to the Florida side, not just Texas).

All 17 tests read real repository files (source code, SQL, YAML) rather than re-implementing a parallel model of them, the same discipline `test_florida_sources_registered_for_state_agnostic_design_but_untouched` (Phase 10A) already established - a test that asserts what the code *says*, not what this document merely claims it says, so the two can never silently drift apart undetected.

## 24. Known architectural limitations

Restating and consolidating every gap found this phase, none of them fixed (Step 23 forbids implementation beyond what's needed to test the existing contract):

1. **No field-level RLS / column-level projection anywhere in Supabase** (Section 16) - "internal" fields are a frontend rendering choice, not an access boundary. A restricted field, were one ever mistakenly written to `properties`, would be visible through the raw REST endpoint even if `app.js` never rendered it.
2. **`assessed` is semantically overloaded across states** (Section 9/10) - FL's statutory `AV_NSD` and TX's raw CAD `"value"`/RealAuction's "Adjudged Value" share one column and, because `market` is never populated for TX, one displayed label ("County Assessed Value").
3. **The data model conflates property identity and sale-event identity** (Section 4) - one row per `(state, source, county, case_no)`, upserted in place on every re-sync, no sale history retained beyond the current row's own `status`/`gone_since`/`outcome`/`sold_price`.
4. **Several columns referenced throughout `app.js`/the sync scripts have no accompanying migration file anywhere in this repository's tracked history** - `owner_name`, `status`, `lien_level`, `lien_note`, `homestead`, `url_streetview`, `url_zillow`, `url_taxcoll`, `url_title`, `outcome`, `sold_price`, `gone_since`, `updated_at`, and the base columns a `schema.sql`/`schema-v2`/`schema-v3` would presumably have defined (none of those three files exist in this repository's git history at all, confirmed via `git log --all --diff-filter=A`, even though `CLAUDE.md` describes them as if present). This means the actual live Supabase schema is **not fully reconstructable from this repository alone** - `information_schema`/`pg_policies` on the live project remains the only full source of truth, exactly as `CLAUDE.md` already warns for RLS policies specifically, now confirmed to extend to column existence itself.
5. **No coordinate sanity bound exists for Texas rows** (Section 19) - the Florida-only lat/lon bound in `enrich_property_details.py` has no Texas equivalent anywhere (LGBS coordinates are trusted as-is; the cross-state Census Geocoder path applies no bound for either state).
6. **`status`'s richer intended vocabulary (`dropped`/`sold`/`notfound`, plus `outcome`/`sold_price`) is declared in frontend code but not currently populated by any writer** (Section 12) - a real, named, pre-existing gap, not something this phase invented or resolved.
7. **`tx_category` and the three TX redemption/statutory-return columns exist in the schema and in the CSV export but have no current writer** - `enrich_property_details_tx.py` remains a non-working architectural stub (confirmed again this phase: still only referenced in a workflow comment, never a real `run:` step), so these columns are always blank in production today despite being part of the declared customer-facing contract.
8. **Texas harvesting runs on `workflow_dispatch` only, not a schedule** (Section 20) - a materially different freshness guarantee than every Florida source, worth knowing before any customer-facing freshness claim is made for Texas listings.
9. **No cross-source or cross-listing property-identity resolution exists** (Section 4) - the same physical parcel appearing under two different `source`s, or being re-offered as a genuinely new listing after a prior one closed, produces independent, unlinked rows.

## 25. Future decisions

Documented as options, per Step 23 - none built this phase:

- **Database-level provenance** - three concrete sub-options already exist in `docs/provenance-production-integration.md`'s own "Future database-level provenance option" section (a dedicated `provenance` table keyed to `properties.id`; JSONB provenance columns on `properties`; a separate audit-log table). Unchanged by this phase; referenced here rather than duplicated.
- **A sale-event/property split** (Section 4's limitation #3) - would require a real schema redesign (a `properties` table proper plus a `sale_events` table referencing it), well beyond this phase's no-schema-change rule; flagged as the natural next architectural question once Texas county coverage grows enough that re-offered listings become common.
- **Field-level RLS or a customer-facing view** (limitation #1) - would close the "internal fields are actually transmitted" gap properly, at the database layer, rather than relying on frontend code discipline; requires a schema/RLS change, explicitly out of scope this phase.
- **Splitting `assessed` into two columns** (limitation #2), or renaming/re-labeling the Texas "County Assessed Value" display once its exact source-field semantics (especially LGBS's raw `"value"`) are independently confirmed against vendor documentation, if any is ever found.
- **A Texas coordinate sanity bound**, mirroring the existing Florida one, the next time `geocode_properties.py` or LGBS's coordinate handling is touched.
- **Populating `tx_category`/the redemption fields** - would require either fixing `enrich_property_details_tx.py` or building its replacement; explicitly not attempted this phase (would be new implementation, not contract documentation).

## 26. Auction-event history contract (migration 014, Phase A - schema only)

Added 2026-09-25 after the read-only auction-event history audit. Migration
`scripts/migrations/014_auction_event_history.sql` creates two tables and
nothing else. This section states the contract those tables establish; it
does not change anything above.

1. **`properties` remains the current-state representation.** One row per
   `(state, source, county, case_no)`, upserted in place by every sync
   script, exactly as Sections 3, 4 and 12 describe. Migration 014 does not
   alter `properties`, any of its columns, constraints, triggers, indexes or
   policies, and does not alter `get_properties()`.
2. **`auction_events` represents individual scheduled auction events.** One
   row per scheduled sale of one property, referencing `properties(id)` with
   `ON DELETE RESTRICT`. Its `state`/`source`/`harvester_source`/`county`/
   `case_no`/`ledger_type` are copied from the property at event creation and
   are immutable on the event, so history survives a later change to the
   property row. `opening_bid` is a snapshot at first observation, not a
   mirror of `properties.bid`. `event_url`/`event_url_kind` are the event's
   own link and kind (same four-value vocabulary as `url_auction_kind`,
   migration 013), separate from the property's current link.
3. **`auction_event_observations` preserves source observations over time.**
   Append-only by application design: one row per `(event_id, observed_at)`
   recording the feed read, the source's own status string verbatim
   (`raw_status`), the normalization applied at that moment, the figures
   shown, and the URL it was read from. Application code inserts only; no
   trigger rewrites it; rows are never updated. Its FK to `auction_events` is
   also `ON DELETE RESTRICT`.
4. **`(property_id, scheduled_sale_date)` is the current event identity**,
   enforced by a UNIQUE constraint. A property re-offered under a new date is
   a new event; the earlier event is marked lifecycle `superseded`, never
   overwritten or deleted. URL, county spelling, case-number formatting and
   parcel are deliberately not identity. No cross-source property matching is
   attempted: the same parcel under two sources is two properties and two
   event streams.
5. **Vocabularies.** `lifecycle` is one of `scheduled`, `completed`,
   `cancelled`, `withdrawn`, `stayed`, `pending_result`, `superseded`,
   `unknown`. `outcome` is one of `sold`, `redeemed`, `struck_off`,
   `future_sale`, `no_sale`, `unknown`, default `unknown`. `properties.status`
   words (`active`, `closed`, `notfound`, `dropped`) are not in either list.
   **A listing that left its feed is not equivalent to "sold"**: it is
   lifecycle `completed` (or `pending_result`) with outcome `unknown` until a
   source states the result. **`unknown` outcomes remain `unknown`**; nothing
   in this schema, and nothing planned, infers an outcome from absence.
6. **Access.** RLS is enabled on both tables with exactly one PERMISSIVE
   SELECT policy each, to `authenticated`, gated on `public.is_approved()`.
   No INSERT/UPDATE/DELETE policy exists; `anon` holds no privilege;
   `authenticated` holds SELECT only; `service_role` (which bypasses RLS)
   holds SELECT/INSERT/UPDATE/DELETE and is the only writer any later phase
   may use, the same posture every sync script already has on `properties`.
7. **Bidder participation is not represented by this schema.** There is no
   bids table, no bidder table, no bidder or purchaser name, and
   `winning_bidder_ref` must stay NULL until a data-handling review (LAFT
   purchaser names, RealAuction winner identifiers, the LGBS redistribution
   scope question in `docs/lgbs-rights-audit.md`) has cleared what, if
   anything, may be stored there. Bidder-level metrics of any kind remain
   unavailable from this project's data.
8. **No customer-facing outcome analytics are enabled by this phase.** Both
   tables are created empty, no harvester or sync script writes to them, no
   RPC reads them, and the frontend does not reference them. Rates that
   depend on outcome coverage are not computable from this phase and no
   figure derived from these tables may be shown to a user until a later,
   separately authorized phase provides both writers and the coverage
   denominators those figures need.

Tests: `tests/python/test_migration_014_auction_event_history.py`. Its static
layer reads the migration file and always runs in CI. Its live layer applies
the migration verbatim to a throwaway scratch database on a local PostgreSQL
(fixture: `tests/python/fixtures/migration_014_scratch_fixture.sql`) and is
skipped where no local database is reachable, including in
`python-governance-test.yml`; it never contacts the Supabase project.

Production status at the time of writing: migration 014 exists in the
repository and has been applied only to a local scratch database. It has NOT
been applied to production; that requires separate explicit authorization.

## Testing strategy

See Section 23. Every new test reads a real repository file (Python source, SQL, YAML, or `app.js`) rather than modeling the contract in a second, parallel Python representation that could silently drift from the code it's meant to describe - the same anti-drift discipline `test_florida_sources_registered_for_state_agnostic_design_but_untouched` already established in Phase 10A.

## CI

No workflow change needed. `.github/workflows/python-governance-test.yml` already runs `pytest tests/python/ -v` against the whole directory; the new file is picked up automatically, exactly as Phase 11's and Phase 12's new test files were.

## Regression summary

`harvesters/governance/registry.py` untouched (byte-for-byte, confirmed via `git diff`). No `legal_status`/`restrictions` value changed for any source. Florida's `.ps1` pipeline has zero coupling to `harvesters.governance` (re-confirmed). `TexasSaleRow` unchanged (still 13 fields). All 75 pre-existing tests (Phase 10A/10B/11/12) still pass, plus 17 new Phase 13 tests - 92/92 total. No production workflow was dispatched; no network call was made to any live vendor; no county was activated; no legal classification changed; no Supabase schema was modified.
