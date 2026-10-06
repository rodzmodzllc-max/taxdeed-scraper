# Acquisition checklist, source truth and county intelligence (2026-10-05)

These features answer the investor's central question on one screen: is this
property actually available, what will it cost, where did it come from, and
exactly how is it acquired? Every answer comes from a record the repository
or the row already holds. Where a fact is missing, the app says so; it never
guesses.

## 1. Acquisition checklist (Available property page)

The first block of **How to acquire** is a fourteen-item checklist
(`acquireChecklist()` / `acquireChecklistHtml()` in `public/app.js`; the keys
are pinned in `ACQUIRE_CHECKLIST_KEYS`).

| # | Item | Comes from |
|---|---|---|
| 1 | Status | `inventory_status` and the source's own wording; a dated list (Louisiana) is never "available now" |
| 2 | Seller | the verified record's `office` |
| 3 | Method | the acquisition mode (`acquisitionOf`) |
| 4 | Amount | `amountInfo()`: the figure, or the official total when one is current |
| 5 | Amount type | the source's financial terms basis (`AVAILABLE_BASIS_LABELS`) |
| 6 | Form | the first published form (`acquisitionForms`) |
| 7 | Deposit | the source's terms (`available-terms.json` `deposit`) |
| 8 | Documents | every other published document |
| 9 | Instructions | the number of published steps |
| 10 | Listing page | `availabilityLink()` |
| 11 | Contact | phone / e-mail / address on the verified record |
| 12 | Deadlines | statement valid-through, escheatment date and available-from date, only when printed |
| 13 | Last verification | the process's observed date and the listing's last read |
| 14 | Not published or not yet verified | the list of every item above that is missing |

Each item has one of three states:

- `known`: a value is on file;
- `not_published`: the source does not state it;
- `not_verified`: no verified record exists yet.

The header counts how many of the first thirteen are on file. Nothing is
scored or ranked, and no item is ever filled with a default. A test runs a
bare row through the checklist and finds zero known items.

## 2. Source truth (every property page, every ledger)

`sourceTruthHtml()` adds a "Source truth" section to every property page,
including certificates. It shows:

- the source and its publisher;
- the official listing;
- the **source health**;
- this record's first and last observation;
- the source date;
- the publication review;
- a link to the county dossier.

### Customer-readable source health

`sourceHealthState()` in app.js and `scripts/unit_freshness.customer_health()`
are the same function. `tests/python/fixtures/source_health_cases.json` pins
both. Each reads the `county_source_registry` freshness columns; the app now
also selects `last_error_category` (column added by migration 022, which is
applied).

| State | Meaning |
|---|---|
| CURRENT | complete read within 36 h |
| RECENT | complete read within 7 days |
| STALE | no complete read in 7 days (or never) |
| SOURCE_UNAVAILABLE | the last attempt could not reach the source (transport / proxy / access) - listings kept, nothing closed |
| PARTIAL | the last attempt read only part of the source |
| NEEDS_REVIEW | the source awaits customer-publication review |
| MANUAL | a manual-only source (`tx_lgbs`, `tx_realauction`) - read on request, never aged |
| NOT_RECORDED | no read recorded |

`checked_zero` marks a complete read in which the source listed nothing (an
`EMPTY` status, or a complete read with 0 rows). It shows as "checked, none
listed". A checked zero is never shown as SOURCE_UNAVAILABLE, and an
unavailable source is never shown as zero.

## 3. County intelligence (dossier)

`harvesters/sources/county_intel.py` builds one record per county of every
production state. `scripts/build_county_intelligence.py` writes
`public/county-intelligence.json`; that file is value-free, mirrored to the
root and checked with `--check`. Inputs:

- the source registry;
- both verified purchase-path evidence tables;
- `data/available_financial_terms.csv`;
- the discovery-candidate files.

**Rebuild the file after editing any of them.**

### Coverage per ledger

| Coverage | Meaning |
|---|---|
| COVERED | a production source approved for customer publication |
| PARTIALLY_COVERED | a production source collected but awaiting review |
| RESEARCH_ONLY | a known source that is not harvested, or candidate pages |
| NO_SOURCE_BACKED_INVENTORY | nothing recorded, or only blocked vendors |

### County state

| State | Meaning |
|---|---|
| VERIFIED | an approved Available source, a verified acquisition process, and its financial terms read |
| PARTIALLY_VERIFIED | an approved Available source with one of those two |
| SOURCE_BACKED | an approved source, nothing else verified |
| NEEDS_REVIEW | sources or candidates exist, none approved |
| NOT_YET_RESEARCHED | nothing recorded |

A county the file omits is NOT_YET_RESEARCHED with no sources (`default_county`).

**SOURCE_UNAVAILABLE is decided only by the app**, from the last read. A
ledger becomes SOURCE_UNAVAILABLE when every production source feeding it
failed to be reached at its last attempt. A county becomes SOURCE_UNAVAILABLE
when every ledger with a production source is SOURCE_UNAVAILABLE.

### Where the dossier opens

The dossier (`openCountyDossier()`, modal `#countyModal`) opens from:

- the Source truth section;
- every county group in the List.

It shows:

- per ledger: coverage, the rows on file (or "loading…"), and each source
  with its publisher, link, review state and health;
- the verified acquisition process;
- whether financial terms were read;
- research candidates;
- "Show these N in the List".

**Visibility:** customers in enforced or paid scope see only approved sources
by name. Sources awaiting review are counted, not named. Admins and preview
see everything.

As of 2026-10-05 the file covers 12 states and 1,019 counties; 145 are listed
explicitly and the rest are the unresearched default.

## Tests

- `tests/python/test_county_intelligence.py`:
  - the generated file is current, mirrored and value-free;
  - coverage and intel rules;
  - VERIFIED requires a verified evidence row;
  - East Baton Rouge and Detroit cases;
  - the health vectors;
  - JS label sets equal the Python vocabularies;
  - the checklist's fourteen keys, with no scoring words.
- `tests/run_test.mjs`, the "Acquisition checklist, source truth, county
  intelligence" block:
  - the checklist on p15 and on a bare row;
  - Source truth labels and health;
  - the shared health vectors in the browser;
  - the dossier for Citrus (VERIFIED), Dixie (checked zero) and Bay
    (SOURCE_UNAVAILABLE), plus an unresearched county;
  - dossier → List;
  - the county-group link;
  - the viewport sweep now includes 430px.
