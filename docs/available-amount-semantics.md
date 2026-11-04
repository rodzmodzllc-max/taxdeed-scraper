# Available amounts: what each figure is (2026-10-05)

Customer report (Citrus 2024-0075TD): the card called the clerk grid's
**opening bid** ($2,606.70) the "Purchase price". The clerk's own List of
Lands statement for the case reads "Total Due from Purchaser $27,689.42 (IF
RECEIVED BY 8/31/2026)". This document records what every Available amount
in the data actually is, where that is established, and how the app now
shows it. Nothing here changes a stored value.

## 1. Tax data the app already holds

`public.properties` has **no column for a tax amount owed**: no annual tax
bill, no delinquent balance, no millage, no certificate face total for an
Available row. `tax_year` is empty on every one of the 54 rows below.
What exists are property **values** - `assessed`, `market` (FDOR just value),
`taxable_value`, `land_value`, `improvement_value`, `value_year` (roll year),
`homestead` - and `url_taxcoll` (empty on the 54 rows). A value is not a tax
owed, and no tax is ever derived from one (a tax bill also carries
non-ad-valorem assessments and a millage this app does not have).

## 2. Florida opening bid - what it already contains

The 2026 Florida Statutes (read from the Legislature's site through a
read-only capture, 2026-10-05):

- **F.S. 197.502(6)(a)** (county-held certificates): the opening bid "shall be
  the sum of the value of all outstanding certificates against the property,
  plus omitted years' taxes, delinquent taxes, current taxes, if due,
  interest, and all costs and fees paid by the county."
- **(6)(b)** (individual certificate): the amount paid at application, the
  amount to redeem the applicant's certificate, costs and fees, certificates
  sold after the application, current taxes if due, and omitted taxes.
- **(6)(c)** (homestead): "shall include ... an amount equal to one-half of the
  latest assessed value of the homestead."
- **F.S. 197.502(7)** (Lands Available): after 90 days anyone may purchase "for
  the opening bid"; "Interest on the opening bid continues to accrue through
  the month of sale as prescribed by s. 197.542."
- **F.S. 197.542(1)**: delinquent taxes / certificates arising after the tax
  deed application must be paid, and the purchaser pays the documentary stamp
  tax and the recording fees.

The clerks' own documents say the same (verified evidence rows in
`data/purchase_path_evidence.csv`):
Duval FAQ - "the opening bid, subsequent omitted taxes, and any accrued
interest. Documentary stamps and recording fees are also assessed";
Orange - "the opening bid, plus omitted years taxes, as cited in section
197.542(1)". The Citrus "LOL" statement (OCR, labels only) itemises Opening
Bid, Lands Available Interest, Omitted Taxes / Total Omitted Taxes,
Documentary Stamp Tax, Deed Recording Fee, Lands Available Total and Valid
Through.

**Double counting.** Delinquent taxes, certificates, current taxes, interest
and costs as of the application - and the homestead half-assessed amount -
are already inside the opening bid. Adding any of them again is wrong. Only
four things are added on top: Lands Available interest, taxes that came due
after the opening bid was set, documentary stamp tax, recording fee
(`FL_LAFT_ADDITIONS` in `public/app.js`).

**"Two years of taxes".** Not supported as a rule. Neither the statute nor
any clerk document read sets a year count: the added taxes are the years that
came due after the opening bid was set, which depends on how long the parcel
has been listed, and the clerk's statement names them. The app assumes no
year count; it says the years are on the clerk's statement.

**Fee estimate fix.** `fees()` used to add half the assessed value on a
homestead parcel on top of the opening bid (an open question since the
2026-09-26 launch review). (6)(c) settles it: the opening bid already
includes it, so the surcharge is removed. `fees()` now returns doc stamps +
recording on the bid for Florida auction rows only, and null for Available
rows (whose added costs are itemised instead).

## 3. What every Available figure is (production, 2026-10-05)

| Source | Rows | Stored kind | What the source says | Shown as |
|---|---|---|---|---|
| FL Pioneer clerks, Hillsborough, Leon, Osceola, St. Lucie, Escambia, Gadsden | 49 | OPENING_BID | the tax deed opening bid | **Opening bid** + "Not the price to buy now ..." |
| FL Indian River | 2 | ORIGINAL_OPENING_BID | original opening bid | **Original opening bid** + same note |
| FL Orange | 3 | MINIMUM_PURCHASE_AMOUNT | "Min Bid" | **Minimum purchase amount** + same note |
| FL RealTDM (Polk, Sarasota, Alachua, Highlands, Lee) | 40 | FIXED_PURCHASE_PRICE | detail page "Purchase Price" BASE figure, before the fees/stamps/interest its own script adds | **Base purchase price** + "not a final quote" |
| FL Putnam | 46 | ESTIMATED_PURCHASE_PRICE | "Estimated Purchase Price" | **Estimated purchase price** |
| FL Hendry | 1 | PUBLISHED_AMOUNT_KIND_UNSPECIFIED | unstated | **Amount type not published** |
| TX LGBS | 421 (402 with a bid) | none | vendor listing minimum bid | **Minimum bid (vendor listing)** - was "Purchase price" |
| SC Horry / PA Fayette / MN Ramsey | 51 / 375 / 2 | OPENING_BID | "MINIMUM BID" / "Min. Bid" / "MinimumBid" | **Minimum bid** (source column) + "Not the full price" |
| SC Georgetown | 1 | OPENING_BID | "Opening Bid" | **Opening bid** |
| OK Oklahoma County | 195 | unspecified | "Suggested Initial Bid Amount" | **Amount type not published** + the column name |
| MI / MO / LA / PA (1) / FL (16) | 50,892 | NOT_PUBLISHED | no amount | **Not published** |

Also corrected: the Florida inventory label "fixed price, over the counter"
(read as "the price is fixed at this figure") -> "over the counter from the
clerk, no bidding"; the filter section "Price" -> "Bid / listed amount"; the
table column "Opening Bid" -> "Amount" with each Available cell naming its
figure; certificate figures -> "Certificate amount (not a property price)";
the Map strip / popups and county tooltip now label every figure.

## 4. Property page - "What it costs" and forms

`acquisitionCostBreakdown(p)` (opening-bid / minimum Florida rows):
listed figure -> the four added items, each "Not on file" until a clerk
statement supplies its amount -> "Known tax obligation" (Not on file) ->
"Known amount" (calculated only when an added item has an amount, labelled
calculated / incomplete; never the official total) -> **Official clerk
total** (current with valid-through + source + read date + statement link;
"Expired" with the last figure and date; or "Not on file - request the
current statement") -> earlier statements, marked historical.

`acquisitionForms(p)`: forms already on the property's verified acquisition
record (`otc_provenance.acquisition.application_url`, `purchase_url` with a
form kind, an application document path) - name from the source metadata,
"Required by the county's published steps" only when those steps say so,
offline / online, link. Florida opening-bid rows without a statement also
list "Current Lands Available statement - Request from the clerk" with the
county's verified contact. No URL is ever constructed.

Of the 54 rows: Duval (1) carries the clerk's Statement Request form;
Citrus, Duval, Leon, Levy (phone / e-mail), Hernando (call for the amount)
and Orange (opening bid plus omitted years' taxes) have a verified process;
Bay, Escambia, Gadsden, Hillsborough, Indian River, Osceola, Palm Beach and
St. Lucie have none yet ("Acquisition path not yet verified"). No deterministic
additional-tax amount exists for any of them; no clerk total is stored.

## 5. Clerk statement source (Pioneer TaxSmartWeb) - findings

Read-only captures (a throwaway workflow branch, runs 37248790485 /
37248930656; shapes and labels only):
- Grid row -> `Home/Details?id=<row id>` -> docket entries linking
  `Home/Image/<doc id>` (PDF).
- Citrus: several "LOL <date>" entries per case (one per re-issued
  statement - a history). Duval: "LANDS AVAILABLE ... STATEMENT" entries.
  Palm Beach: "LANDS AVAILABLE <date>". Bay / Hernando: no statement entry.
- Every document is a **scanned image, no text layer**. OCR (tesseract)
  recovers the Citrus statement labels including "Lands Available Total" and
  "Valid Through"; Duval's statement OCR found none of the labels.
- Terms text on every portal: no warranty of accuracy; "Official Record
  images ... have not been certified as being true and correct copies". No
  reuse licence and no reuse prohibition was found. Technically public;
  reuse permission is **not established**.

A harvester for these statements is a separate change: it needs OCR with a
validation that the itemised lines sum to the printed total, per-county
format verification, and a publication decision on the documents' reuse.

## 6. Every state and source: the financial-terms table (global pass)

The Florida rules above are now one case of a source-aware model that covers
every Available source. There is no universal formula.

- **`data/available_financial_terms.csv`** (validated by
  `harvesters/sources/available_terms.problems()`, rendered to
  `public/available-terms.json` by `scripts/build_available_terms.py`,
  `--check` pinned by `tests/python/test_available_terms.py`) holds one row
  per source, with optional county / published-status scoping. The frontend's
  `termsFor(p)` takes the most specific matching row.
- **Basis** says what the listed figure is: OFFICIAL_PRICE, PROGRAM_PRICE,
  OFFICIAL_TOTAL_DUE, OPENING_BID_PLUS_ADDITIONS, BASE_PRICE_PLUS_ADDITIONS,
  ESTIMATE, MINIMUM_BID, BID_SUBMISSION, OFFER_NEGOTIATED, PROPOSAL,
  QUOTED_ON_REQUEST, NOT_PUBLISHED.
- **Additions** (interest, omitted_taxes, doc_stamps, recording_fees) are
  listed only where the statute or the source names them, and are added only
  to an opening / minimum / base figure. A figure that already includes an
  item (`included_in_figure`) never gets it again.
- **Application costs and deposits** are always their own rows, never added
  to a price. `in_price` = yes / no / unknown states whether the source says
  they are part of the price.
- **Every row carries `quote`, `evidence` and `observed_on`.** A row is added
  only from a source that has been read; an unverified claim (for example
  Horry's 15% administrative fee, search-index only) is left out.

| State / source | Basis | What the customer sees |
|---|---|---|
| FL clerk lists (Pioneer, Hillsborough, Leon, Osceola, St. Lucie, Orange, HTML, PDFs) | OPENING_BID_PLUS_ADDITIONS | Opening bid + the four statutory additions, each "Not on file"; official total from a clerk statement only |
| FL Putnam | ESTIMATE | Estimated purchase price |
| FL RealTDM | BASE_PRICE_PLUS_ADDITIONS | Base purchase price + interest / doc stamps / recording |
| LA East Baton Rouge | OFFER_NEGOTIATED | No price; offer + advanced costs (`in_price=no`) |
| TX LGBS | MINIMUM_BID | Minimum bid (vendor listing); Galveston adds a 5% bid deposit (`in_price=unknown`) |
| MI Detroit side / neighborhood / oversized lots | PROGRAM_PRICE | Policy program price (Side Lot $100, dated to the 2023 policy; the others conditional), buyer restrictions noted |
| MI Detroit other statuses and programs, MO St. Louis LRA | NOT_PUBLISHED | Not published |
| MI Oceana | PROPOSAL | Proposal by application |
| OK Oklahoma County | BID_SUBMISSION | "Suggested initial bid (county's column)" |
| PA Fayette, SC Horry | BID_SUBMISSION | Minimum bid |
| MN Ramsey | MINIMUM_BID | Minimum bid |
| SC Georgetown | BID_SUBMISSION | Opening bid; the total is stated by the county after the Commission decides |

A source with no terms row falls back to the stored `purchase_amount_kind`,
and an unknown kind reads "Amount type not published", never a price.
Calculated figures are labelled "Known amount (calculated)", or "...so far
(calculated, incomplete)" when an addition is not on file. They are never
called the official total. No production row was written by this pass.
