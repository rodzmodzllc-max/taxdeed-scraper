# Current acquisition amounts (2026-10-06)

`harvesters/sources/amount_semantics.py` describes what an AVAILABLE money
figure is and whether it is current. It also reads a purchase statement's
text with validation. `public/app.js` `amountSemanticType()` /
`amountTemporal()` mirror it, and
`tests/python/fixtures/amount_semantics_cases.json` pins both.

The display wording is still `amountInfo()` and the financial position
(`docs/available-financial-position.md`). This layer adds the two facts those
surfaces were missing: the semantic type and the time status. The property
page's Financial position block shows them as "Amount type", "Amount status"
and "Valid through" (`amountMetaHtml`, `.fp-meta`).

## Semantic types

There are twelve semantic types:
- OPENING_BID
- MINIMUM_BID
- CURRENT_PURCHASE_PRICE
- CURRENT_AMOUNT_DUE
- APPLICATION_FEE
- DEPOSIT
- TAX_AMOUNT
- INTEREST_AMOUNT
- PENALTY_AMOUNT
- DEED_FEE
- RECORDING_FEE
- OTHER_PUBLISHED_AMOUNT

The row's figure maps to a type as follows:
- A stored clerk statement maps to `CURRENT_AMOUNT_DUE`.
- Otherwise the type comes from `purchase_amount_kind`:
  - `FIXED_PURCHASE_PRICE` maps to `CURRENT_PURCHASE_PRICE`.
  - `MINIMUM_PURCHASE_AMOUNT` maps to `MINIMUM_BID`.
  - An unspecified or estimated kind maps to `OTHER_PUBLISHED_AMOUNT`.
- A source column named as a minimum (`Min. Bid`, `MinimumBid`, `MINIMUM BID`)
  turns an `OPENING_BID` kind into `MINIMUM_BID`.
- Texas LGBS's own field is a minimum bid.

An assessed, market or taxable value is never an amount here, and no tax
figure is derived from one.

## Time status

| Status | When |
|---|---|
| CURRENT | A statement is inside its valid-through date, or the figure is on the source list read in the last 14 days from a list not older than 365 days. |
| EXPIRED | A statement is past its valid-through date. Shown as "Expired - request a current statement", never as current. |
| HISTORICAL | The figure is an original or superseded one (`ORIGINAL_OPENING_BID`), or the row is no longer listed. |
| UNKNOWN | The list was not read recently, or the list itself is older than a year. Fayette PA's repository list, dated 2025-10-07, crosses that line on 2026-10-07. |

## Statements

`parse_statement_text()` reads a statement's text, whether from the PDF text
layer or from OCR, into the `otc_provenance.purchase_statement` shape:
- It requires exactly one total. Two different totals is NEEDS_REVIEW; no
  total is FAILED.
- A garbled figure such as `1,2O4.56` is never read as a number.
- Printed components must reconcile with the total to the cent. Components
  are never added up to make a total.
- A document whose reuse is not cleared (`rights_status != PERMITTED`) is for
  internal verification only: `displayable: false`, NEEDS_REVIEW.

No statement is stored in production. The Florida Pioneer statements are
scanned images whose reuse permission is not established, and no other
source publishes a per-parcel statement.

## What did not change

- No amount was written to production.
- No migration was added.
- Application costs and deposits stay separate from the price
  (`financialPositionCore`).
- `sw.js` → `tdw-shell-v98`.
