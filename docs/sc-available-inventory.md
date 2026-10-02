# South Carolina AVAILABLE: Georgetown and Spartanburg FLC lists (2026-10-02)

Branch `feat/sc-available-inventory`. Nothing in this work is published to
customers, written to the database, or scheduled.

## How the documents were read

The sandbox cannot reach county sites, so the documents were read by the
manual evidence job, scoped to these two sources only:

```
harvest-and-sync.yml  job=evidence  evidence_scope=sc_available
```

The job runs only `scripts/capture_sc_available.py`.

- **Read-only.** No database credential reaches the evidence job, no other job
  runs on `job=evidence`, and the PDFs stay in memory.
- **What the log may contain:**
  - county-written availability and terms wording, with tables removed;
    sentences carrying a digit run, an amount or an e-mail address are dropped;
  - titles, URLs, HTTP status and read times;
  - PDF heading and column-header lines whose every word is on a whitelist;
  - counts and identifier SHAPES (digits shown as 9);
  - the parser's own counts.
- **What it never contains:** a row, an owner name, an address, a TMS / MAP
  number, or raw PDF text. Phone numbers are counted, not printed.
  `tests/python/test_sc_available.py` feeds the capture a document full of
  names, addresses, identifiers, amounts, a phone and an e-mail, and proves
  none of them reaches its output.

| Run | Purpose |
|---|---|
| 37033274319 | Structure: pages, headings, columns, identifier shapes, terms pages |
| 37035908843 | Parser validation: `harvesters/otc/adapters/sc_flc.py` counts against the live PDFs |
| 37036374756 | Confirmation after the per-section identifier rule: Georgetown COMPLETE (55 rows, 53 valid TMS, 1 AVAILABLE); Spartanburg 5 valid MAP NUMBERs, 0 AVAILABLE |

## Georgetown County: qualifies (one LAND row), REVIEW_REQUIRED

**What the documents say**

- **Program page:**
  - "The main purpose of the Forfeited Land Commission is the sale or
    assignment of properties that have been abandoned or were not bid upon at
    the delinquent tax sale."
  - Property is offered "AS IS, WHERE IS".
  - "The transferring deed will be a Quit Claim Deed."
  - The Committee decides a bidder application and then notifies the
    decision and "the total amount due".
- **List:** "2026 FLC LIST - UPDATED MAY 2026", a 3-page PDF.
  - Columns: Group | Name | TMS # | Description | Tax Sale Date | Opening Bid.
  - Two sections: MOBILE HOMES (pages 1-2) and LAND (page 2). Page 3 is the
    commission's procedure text.

**What the parser found (run 37035908843)**

- 55 data rows, all header-mapped.
- MOBILE HOMES: 54 rows, with 52 valid TMS and 2 malformed identifier cells (shapes
  `99-9999-999-99-99A/A` and `99-9999-999-99-99.999A/A`: trailing letters after the number).
  These rows are personal property and are never AVAILABLE land.
- LAND: 1 row, with a valid TMS and a 2017 tax sale. That sale is past South
  Carolina's twelve-month redemption period (S.C. Code § 12-51-90), so the row
  is **1 AVAILABLE observation**.

**Adapter rules (`sc_flc.GEORGETOWN`)**

- Only a LAND row whose tax sale is past the redemption period qualifies.
- A row is rejected with its own category if it:
  - is still in the redemption period;
  - has an unreadable sale date;
  - has a missing, malformed or duplicate identifier;
  - falls in an unknown section.
- A malformed or missing identifier in the LAND section fails the read
  (format change). The same problem in MOBILE HOMES is counted but does not
  fail the read.
- **Identifier:** the TMS # as published, with whitespace removed and nothing
  else changed. Format: `99-9999-999-99-99`, plus `.999` for a mobile home.
- **Amount:** the Opening Bid column, as `OPENING_BID`.
- **No owner name is read.**
- **`list_as_of` stays empty:** "updated May 2026" names a month, so it is
  kept as text and never turned into a date.

**Acquisition path**

| Field | Value |
|---|---|
| Mode | Application |
| Steps | Complete the FLC bidder application (the "FLC Procedures and Bid Apps (PDF)" linked from the program page) → the Committee decides → the county notifies the decision and the total amount due |
| Deed | Quit Claim Deed |
| Payment | Not published |
| Online purchase | No online purchase link on file |
| Application URL | https://www.gtcountysc.gov/DocumentCenter/View/1587/FLC-Procedures-and-Bid-Apps-PDF (as an application form) |

**Publication review (`data/available_publication_reviews.csv`)**

- No reuse or commercial-use grant is published, and no prohibition.
- The privacy page refers to the SC Freedom of Information Act. That is
  public-record access, not a republication licence.
- The Copyright Notices page published no wording that could be read.
- Result: **REVIEW_REQUIRED**, pending an owner decision or written permission.

## Spartanburg County: does not qualify

**What the documents say**

- **Real-estate PDF:** "2025 TAX SALE PROPERTIES (REAL ESTATE) AVAILABLE FOR
  ASSIGNMENT".
  - Columns: ITEM # | DESCRIPTION | DEFAULTING TAXPAYER | MAP NUMBER | TOTAL TAX DUE.
- **What is offered:** the assignment of the commission's 2025 tax-sale bid
  during the redemption period. The owner may still redeem, so this is not
  property the county holds for purchase.
- **Program page:** "All properties prior to 2023 TAX SALE can only be
  purchased by on-line auction sales."

**What the parser found (run 37035908843)**

5 data rows and 5 valid MAP NUMBERs (`9-99-99-999.99`). All 5 are rejected as
`redemption_assignment`.

**Classification**

- Discovery evidence: `REDEMPTION_ASSIGNMENT` (rejected). The catalog's
  `availability` role was removed.
- Publication review: REVIEW_REQUIRED (no terms published).
- No AVAILABLE adapter. `harvest()` refuses even if the source is approved.

## Matching

- **Rule (`sc_flc.match_existing`):** same state, same county, and the
  identifier equal to the property's published parcel after whitespace
  removal. Owner name, address, legal description and fuzzy rules are never
  used.
- **Today:** production has no Georgetown or Spartanburg property, so the one
  Georgetown observation is **unmatched**. It is kept as the source's own
  record, never made into a property.

## Ledgers

- The FLC adapter emits AVAILABLE (`laft`) records only.
- York's auction source (`expansion.SC_YORK`) emits AUCTIONS records only.
- No SC AVAILABLE source is in production, and neither source has a registry
  row, so no harvester or sync reads them.

## What would make Georgetown customer-visible

1. **An owner publication decision** (or written permission from the county),
   recorded as APPROVED in both the review file and the catalog. The coverage
   check refuses APPROVED without a published grant or recorded permission.
2. **A registry row** for the source, plus wiring the gated adapter into a
   harvest step. That step makes no request until step 1 is done.
