# Due diligence (2026-10-06)

Every property page now has a **Due diligence** section. It is a factual checklist in which each item's **evidence state** is decided only by the property's records. Saved properties also carry the customer's own review marks and notes per item.

## Evidence states

| State | Means |
|---|---|
| VERIFIED | The record carries the value **and** evidence for it. The evidence is one of: the source list that published it was read; a recorded `field_provenance` origin; an official coordinate method; a verified acquisition record; a result the source published. |
| NOT VERIFIED | A value or process may exist, but the evidence rules do not support "verified". Examples: a value of unrecorded origin, vendor or geocoded coordinates, a source awaiting review, a list not read in the last 14 days. |
| NOT PUBLISHED | The source publishes no such value for this record. |
| NOT APPLICABLE | The item does not apply to this ledger, and is hidden. |
| SOURCE UNAVAILABLE | The source could not be read at its last attempt. |

**A populated field is never "Verified" on its own.** Legal description, acreage, land use and assessed / taxable values need a recorded origin; parcel and county need a read of the source; coordinates need an authoritative method.

## Items, by group

- **Property identity:** parcel / account identifier, county, legal description.
- **Acquisition** (Available only):
  - official source;
  - acquisition path;
  - purchase / application document;
  - current amount (semantic type + CURRENT time status);
  - amount date.
- **Property** (not for certificates): coordinates, acreage, land use, imagery, assessed / taxable value.
- **Auction:** sale date, opening / minimum bid (as published, never a price), auction source, sale result. The sale result is VERIFIED only from a source-published outcome. A sale not yet held is not applicable, and a past sale with no published result is "Not published".
- **Lien / certificate:** certificate number, face / certificate amount, interest rate, redemption / expiration.
- **Source:** source record, last read, provenance, source health.

Each item shows the evidence behind its state, for example "Recorded from fdor nal", "On file; origin not recorded", "Official parcel GIS layer (point)", "Opening bid $5,000.00 as published - not a price" or "Sale not held yet".

## The rule

`harvesters/sources/due_diligence.checklist(facts)` is the same function as app.js `diligenceChecklistFromFacts(facts)`, pinned by `tests/python/fixtures/due_diligence_cases.json`. app.js `diligenceFacts(p)` derives the categorical facts from a row by reusing the existing evidence functions:
- `acquisitionOf`, `acquisitionEvidenceStatus`;
- `amountSemanticType`, `amountTemporal`;
- `coordinateProvenance`, `auctionOutcomeState`, `auctionLinkInfo`;
- `sourceHealthState`, `isCustomerPublishable`.

There is no second provenance system.

## The customer's own marks

Once a property is saved to a research list (My Research), each item gets a "Reviewed by me" check and a private note.

- **Where they are stored:** in `research_items.diligence` (migration 029, not applied), or in this browser until 029 is applied.
- **They never change an evidence state.** A customer cannot mark an item verified, and the Playwright check proves the state is identical before and after a mark.

The My Research row shows "N of M verified", followed by counts of not verified, not published, source unavailable and "reviewed by you".

## Tests

- **Python** (`tests/python/test_due_diligence.py`):
  - the vectors;
  - every item has a state for every case;
  - a populated value without evidence is never verified;
  - ledger scoping;
  - app.js constants equal the Python ones.
- **Playwright** block "Due diligence":
  - the vectors in the browser and the p15 states;
  - populated-but-unsourced values read "Not verified";
  - a review mark persists while the evidence state is unchanged;
  - the My Research summary;
  - ledger scoping for an auction (past and upcoming) and a certificate;
  - browser-only marks persist across a reload;
  - no overflow at 390 / 430 / 768 / 1024 / 1440 / 1920.

`sw.js` → `tdw-shell-v101`.
