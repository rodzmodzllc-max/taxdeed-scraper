# AVAILABLE inventory sprint (2026-10-02)

Government-held property that the source itself offers for acquisition, built
on the PR #69 pipeline: discovery, then evidence, parser, deterministic
identifier, AVAILABLE classification, provenance, acquisition path and the
publication gate.

## Sources implemented

| source_id | State / county | Source | Inventory read | Identifier | Amount | Acquisition |
|---|---|---|---|---|---|---|
| `mi_detroit_landbank_lots` | MI / Wayne | Detroit Land Bank Authority, "DLBA_Owned_Properties" ArcGIS layer | only the four lot statuses ending "For Sale" (`DLBA_LOT_STATUSES`), with the status kept verbatim | `parcel_id` | not published | the DLBA's own programs (item page) |
| `mi_detroit_landbank_programs` | MI / Wayne | DLBA "DLBA_For_Sale" layer | the Own It Now, Renovation and Economic Development programs; **Auction is excluded** (it is an auction, not AVAILABLE) | `parcel_id` | not published | program |
| `mi_oceana_landbank` | MI / Oceana | Oceana County Land Bank Authority, "Current Available Properties" table | every row | Parcel ID Number | not published | Application for Proposals form (`APPLICATION_FORM`) |
| `sc_horry_forfeited_land` | SC / Horry | Horry County Forfeited Land Commission, yearly "<YEAR> FLC List" workbooks | only years whose redemption period is over (`list_year_past_redemption`: on or after Jan 1 of year + 2). The current year is an assignment list and is not read | PIN | MINIMUM BID (`OPENING_BID`) | FLC guidelines (`BID_FORM`) |
| `sc_georgetown_forfeited_land` | SC / Georgetown | Georgetown FLC PDF list (PR #69 parser) | only sections past the redemption period | TMS | as published | PR #69 evidence row |

None of these sources reads a TAXPAYER or owner column, and no amount is ever
computed. All five are UNREVIEWED for customer publication; they are collected, synced and shown to admins, labelled.

## Collection vs customer publication (2026-10-02)

Publication review is a **customer release** control. It no longer decides
whether development can see collected data.

```
SOURCE -> COLLECT -> NORMALIZE -> VALIDATE -> MATCH -> ENRICH -> CLASSIFY
       -> properties (every row carries publication_status)
       -> admin / development view (everything collected, labelled)
       -> customer publication gate (frontend, PUBLICATION_MODE)
```

- **Collection** (`source_publication.collectable()`):
  - an APPROVED* source is collected;
  - an AVAILABLE (laft) source awaiting review (UNREVIEWED / RESTRICTED) is collected too, because a review status is not a prohibition;
  - a BLOCKED source is never requested.
  - Auction and lien sources keep the stricter rule (collected only once publishable), so auction and certificate logic is unchanged.
- **Runner** (`scripts/harvest_expansion.py`):
  - every collectable source runs in the normal loop and goes into `out/<st>_properties_rows.json`. There is no held side-path any more.
  - One failing source never stops the others.
  - A record that fails validation is dropped and its county read becomes INCOMPLETE, so nothing is closed on an untrusted read.
- **Sync** (`scripts/sync_state_inventory.py`):
  - writes every collectable row with `publication_status` = the source's effective decision, never relabelled;
  - counts those not customer-publishable as `written_review_pending`;
  - close-out covers collectable sources only after a COMPLETE / EMPTY read.
- **Frontend** (`public/app.js`):
  - `isCustomerPublishable()` is the customer rule (APPROVED* or no decision).
  - `isPublishable()` decides what this session shows:
    - admins always;
    - everyone when `config.js` sets `publicationMode: "preview"`;
    - otherwise the customer rule;
    - BLOCKED never.
  - Every non-customer-published row is labelled:
    - "Source review: Unreviewed · not customer-published" on the card;
    - a banner plus a "Source publication review / Customer-visible" line on the property page;
    - the ledger notes how many such rows are shown and why.
  - The source's own program wording (e.g. "Side Lot For Sale", "Own It Now") sits next to it. Availability stays a separate fact.
  - Admins get a Dashboard panel, "Collected inventory by source": collected / active / customer-visible counts, review status and last read.

No migration: `get_properties()` never filtered on `publication_status`.

## Validated counts (runs 37039824035 / 37040250643, read-only, no credentials)

| Source | Status | Held rows |
|---|---|---|
| `mi_detroit_landbank_lots` | COMPLETE | 30,661 |
| `mi_detroit_landbank_programs` | COMPLETE | 12 |
| `mi_oceana_landbank` | COMPLETE | 5 |
| `sc_horry_forfeited_land` | COMPLETE | 51 (run 37040250643, after `id_pattern`; run 37039824035 had read 55, including note lines and section words; 6 such rows are now skipped) |
| `sc_georgetown_forfeited_land` | COMPLETE | 1 |

The published sources in the same run were unchanged: Eaton 8, Lenawee 35, York 853.

## Evidence

All evidence comes from value-free structural captures:
- `job=evidence`, `evidence_scope=available_sources` (`scripts/capture_available_sources.py`, candidates in `data/available_source_candidates.csv`), run 37038385659;
- `evidence_scope=available_validate`, which runs the real harvest path for MI and SC with no database credentials and prints counts and shapes only.

Candidates that were read and not implemented:
- the Michigan State Land Bank (search application, no list);
- Manistee (parcels only in free text);
- Saginaw;
- Lancaster SC and Abbeville SC (no current list);
- Kenosha WI and Douglas WI (no list or table);
- Gonzales TX (no struck-off list).

They stay in the candidate list and the catalog.

## Tests

- `tests/python/test_available_inventory_sprint.py`: adapters, the redemption rule, ledger isolation, held collection and failure isolation.
- `tests/python/test_available_sources_capture.py`: capture privacy.
