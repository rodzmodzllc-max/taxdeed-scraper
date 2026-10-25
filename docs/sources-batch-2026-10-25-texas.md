# Texas sources batch - 2026-10-25 (Dallas and Bexar struck-off lists)

Two Texas counties were checked on 2026-10-25 for an official, county-published list of struck-off property:
tax-foreclosed property that drew no bid at the sheriff's sale, was struck off to the taxing units, and is offered for
resale. That inventory belongs in the AVAILABLE ledger (`properties.source = 'laft'`, `ledger_type = 'buy'`,
inventory type `STRUCK_OFF_HELD_IN_TRUST`).

This batch is **backend only and gated**, the same way the Florida and ePropertyPlus batches of the same day were done:

- no workflow step, no schedule change, no sync;
- no production write and no migration;
- no front-end change.

Every figure below is a count or a shape. No account, cause number, address, owner or amount from a source is recorded
here.

The owner's direction: collect public records to fill gaps and show coverage, and sell nothing until legal review.

## Summary

| County | Official list found | Reachable from the sandbox | Standing | Count read |
|---|---|---|---|---|
| Bexar (`tx_bexar_struckoff`) | Yes. Bexar County Public Works links a "Current Struck-Off Property List" PDF from its own page. | Yes (direct `curl`) | Gated reader; registry `MANUAL_REVIEW_REQUIRED` / `TERMS_NOT_VERIFIED` / `UNREVIEWED` | 41 one-account rows kept; 3 lines refused; a multiple-account section (7 accounts) not read. List updated 2026-10-06. INCOMPLETE. |
| Dallas | **No County document today.** The County's page links its list only to the LGBS vendor map. | Yes (direct `curl`) | Candidate only. Registry row `HISTORICAL_ONLY`; `tx_dallas_struckoff` in `data/available_source_candidates.csv`. | none |

## 1. Bexar County

### Where the list is published

- **Page:** `https://www.bexar.org/1670/About-Us` (Bexar County Public Works, "About Us"), read live. Under Property Tax
  Foreclosures it says the division is "Responsible for the sale of Tax Foreclosed Properties previously struck-off
  (deeded in trust) to Bexar County through the Private Sale process", and: "to obtain a current Struck-Off List please
  click the link below".
- **Links on that page:** "General Information" (DocumentCenter 41851) and "Current Struck-Off Property List"
  (DocumentCenter 41852). The document's URL slug carries an old date (`...-4-2-24`), but the document itself is current
  (see below).
- **General information sheet** (DocumentCenter 41851, read, 4 pages, modified 2026-03-06):
  - "Properties that are not sold during the monthly Sheriff's sale ... are Struck Off and deeded in trust to Bexar
    County. Struck Off properties are available for Private Sale."
  - They are sold by private sale (Public Works' Asset Management Division) or at the semi-annual Commissioners Court
    resale auction.
  - "Properties are sold at a minimum amount of the court judgment against the property or for the adjudged value of the
    property, whichever is less." The buyer also pays code-compliance liens not in the tax suit, interim taxes (tax years
    not in the judgment) and the deed recording fee.
  - Every sale goes to Commissioners Court for approval. Bexar County gives a quitclaim deed only, without warranty.
  - The sheet describes a redemption period for the former owner.

### What the list is (read 2026-10-25, structure and counts only)

- **Document:** a scanned PDF (producer: a Lexmark scanner) with an OCR text layer and no table structure. 2 pages.
- **Page 1:**
  - heading "BEXAR COUNTY RESALE PROPERTIES" and "List Updated October 6, 2026";
  - columns Property Address / Suit No. / Account No. / "Struck off amt w/o interim tax / fees";
  - one property per line.
- **Page 2:** "MULTIPLE ACCOUNTS". One suit covers several accounts with one amount, laid out across several lines. The
  OCR order does not reliably tie each account to its suit and amount.
- **Footer:** "THE DOLLAR AMOUNTS LISTED ARE NOT GUARANTEED TO BE ACCURATE".
- **Shapes:**
  - account `99999-999-9999` (the Bexar Appraisal District account);
  - suit number `99-AA9-99999` and close variants, e.g. a one- or four-digit year, or three letters;
  - amount `$99,999.99`.
- **No owner names** are on the list. No bidder or purchaser is named.

### The reader

`scripts/harvest_tx_bexar_struckoff.py`, source `tx_bexar_struckoff`, dataset `struck_off_properties`.

- **Finding the PDF:** it reads the About Us page and takes the href of the link whose own text is "Current Struck-Off
  Property List". The URL is never constructed, and a link that leaves `www.bexar.org` is refused.
- **Text:** taken from the PDF's own text layer with `pdfplumber`. There is no OCR in the reader; a document without a
  text layer FAILS.

**Mapped (one-account lines only):**

| Source column | Output | Notes |
|---|---|---|
| Account No. | `case_no` | the CAD account is `case_no` for every Texas source |
| Suit No. | `parcel` | the tax-suit cause number, exactly as `tx_lgbs` / `tx_realauction` carry it |
| Property Address | `address` | the situs as listed; the County says addresses are not guaranteed |
| Struck off amt w/o interim tax / fees | `purchase_amount` | `purchase_amount_kind = PUBLISHED_AMOUNT_KIND_UNSPECIFIED`: the list calls it neither a price nor a minimum bid |
| List Updated | `list_as_of` | |

Every row also carries `state TX`, `county Bexar`, `source laft`, `harvester_source tx_bexar_struckoff`,
`inventory_type STRUCK_OFF_HELD_IN_TRUST` and `url_auction` = the About Us page.

**Never mapped:** the multiple-account section (counted, left unread). No owner, bidder or purchaser fields exist.

**Refused, never repaired:** a line whose account, suit or amount fails its shape (OCR noise) is counted and dropped.
On the live read, 3 lines failed:

- an account with a digit missing;
- an account with a letter where a digit belongs;
- a suit number with letters in its serial.

A duplicate account keeps the first line.

**Status** (own file `out/harvest_tx_struckoff_status.json`, `state TX`, `laft_status` vocabulary):

| Status | When |
|---|---|
| COMPLETE | every data line parsed and no multiple-account section |
| INCOMPLETE | rows kept but a line was refused, or the multiple-account section is present (`PARSE_FORMAT_CHANGE`); or the list was recognised with no row (`UNCONFIRMED_EMPTY`) |
| FAILED | transport, the link missing from the page, not a PDF, no text layer, or the heading not recognised |

There is **no EMPTY outcome**: the list has never been seen to say it is empty, so a zero is never EMPTY.

**Run:**

- `python3 scripts/harvest_tx_bexar_struckoff.py`: a live read, gated;
- `python3 scripts/harvest_tx_bexar_struckoff.py --fixture F.pdf`: no network.

Output goes to `out/harvest_tx_bexar_struckoff.json`. No sync reads it. Logs carry counts, statuses and error categories
only.

**Live read from the sandbox (2026-10-25):**

| Measure | Count |
|---|---|
| data lines on page 1 | 44 |
| rows kept | 41 |
| lines refused | 3 |
| duplicates | 0 |
| multiple-account section | present, 7 account tokens, not read |
| list as of | 2026-10-06 |
| status | INCOMPLETE |

### Governance

- **Permissions** (`data/source_permissions.csv`): `fetch` / `parse` / `store` only, for dataset
  `struck_off_properties`, jurisdiction TX.
  - Status `OWNER_PERMISSION_REQUIRED`, evidence `INTERNAL_RISK_ACCEPTANCE`.
  - Effective 2026-10-25, expiring 2027-04-12, condition `excluded_from_paid_tier`.
  - This is an interim allowance, never documented permission. There is no `display`, `redistribute`, `enrich` or
    `fetch_via_proxy` record, so each is denied.
- **Registry:** the existing Bexar candidate row now carries:
  - source id `tx_bexar_struckoff`, inventory type `STRUCK_OFF_HELD_IN_TRUST`;
  - the About Us page as `canonical_url` and the PDF as `document_url`;
  - `HTTP_GET_PDF` / `PDF`, `MANUAL_REVIEW_REQUIRED`, `TERMS_NOT_VERIFIED`, `UNREVIEWED`;
  - no harvester. That makes it never runnable: `harvesters/otc/gate.py` refuses everything that is not
    `PRODUCTION_VERIFIED`.

  The publisher, amount-kind, cadence and terminology columns stay blank, as on every candidate row. Those facts live in
  the notes, the reader and the terms row.
- **Financial terms** (`data/available_financial_terms.csv`): one source-wide row, basis `BASE_PRICE_PLUS_ADDITIONS`.
  - It quotes the information sheet.
  - Additions: `recording_fees`. Interim taxes and code-compliance liens are named in the note; they have no addition key.
- **Acquisition evidence:** Bexar is now an acquisition unit with status `NOT_FOUND` (gap queue category F). No
  verified acquisition record was written: the information sheet names a staff contact by e-mail, and a person's e-mail
  is never recorded.
- **`harvesters/otc/adapters/tabular.py` `TX_CANDIDATES`:** the Bexar and Dallas entries were updated to say what was
  found.

## 2. Dallas County

- **Page:** `https://www.dallascounty.org/departments/pubworks/property-division.php`, read live with `curl`, and
  cross-checked with the assistant's fetch tool. It is titled "Property Division Tax Foreclosure Resales", welcomes the
  visitor to "the Dallas County Neighborhood Revitalization Program for Tax Foreclosure Resales", and then lists "TAX
  SALE PROPERTIES - Sold by the Dallas County Sheriff via Live Online Auction".
- **The list link:** its "List of Tax Sale Properties" link goes to the **LGBS vendor map** (`taxsales.lgbs.com`, with
  `sale_type=SALE,RESALE,STRUCK OFF,FUTURE SALE&county=DALLAS COUNTY`). The page's other links go to the RealAuction
  sheriff-sale site. **No County document is linked.** The page also does not mention sealed bids.
- **The County's own FAQs** (both read):
  - `TaxFCResaleFAQ_2019.pdf` and `TaxFCResaleFAQ_2024_Bids.pdf` say properties "struck-off to Dallas County as Trustee
    are posted on the Dallas County website where they are listed for resale and available for downloading".
  - The 2024 version describes "HOLD FOR SEALED BIDS" and sealed-bid solicitations.
  - The County Public Works PMUC overview page (`div-prop.php`) says the division manages "the disposition of tax
    foreclosed properties struck off to Dallas County at the Sheriff's Sale" under the Dallas County Tax Foreclosure
    Resale Policy and Tax Code 34.05.
- **Earlier County lists:** a search index showed `StruckListWorking_2024_Inventory-Post-2025-2.pdf` and
  `StruckListWorking_2023_Seal-Bids_Post.pdf` under `/Assets/uploads/docs/public-works/`. Both answer **HTTP 404** today.
- **Other places checked:**
  - the Dallas County purchasing bids page: no struck-off or resale solicitation;
  - the Tax Office help article: HTTP 403 to both `curl` and the fetch tool.

**Standing:**

- The County's only current list is hosted by LGBS, which is `REVIEW_REQUIRED` and must not become a new source, so
  the work stops for Dallas.
- The registry row is now `HISTORICAL_ONLY`, last checked 2026-10-25. No LGBS URL is recorded in it.
- `tx_dallas_struckoff` is in `data/available_source_candidates.csv`, pointing at the County page.
- Dallas has no reader, no permission record and no terms row.
- **Next step:** watch for a County-hosted list on that page again; the FAQ says one is normally posted when a
  sealed-bid round is announced.

Not checked in depth: the City of Dallas and the Dallas Central Appraisal District. A search index showed City of Dallas
"Tax Sale List" PDFs (e.g. a March 2024 sale) under `dallascityhall.com`. Those are sale notices, not a struck-off
inventory, and they were not read. The City's land bank is a different program, out of scope.

## Tests

`tests/python/test_sources_batch_2026_10_25_texas.py` uses SYNTHETIC fixtures only: invented accounts, suits, addresses
and amounts in the live shapes, rendered into a PDF built by hand. It covers:

- the mapping, with the CAD account as `case_no` and the cause number as `parcel`;
- OCR-garbled lines refused and counted;
- the multiple-account section counted and left unread;
- a zero that is never EMPTY;
- duplicates;
- format changes that FAIL;
- link discovery by text, never constructed;
- the reader's own TX status file;
- a log that prints no identifier, address or amount;
- the permission records (interim, `excluded_from_paid_tier`, no display, expired after 2027-04-12);
- refusal before any request when permission is denied;
- the registry rows (candidates, never runnable, no vendor URL);
- no workflow, PowerShell script or sync naming the reader;
- the terms row and the Dallas candidate.

**Count pins updated:**

- `test_county_source_registry` (TX `SEARCH_EVIDENCE_ONLY` candidates 20 → 18);
- `test_gap_closure` (73 acquisition units, 47 unresolved, 33 NOT_FOUND);
- `test_otc_framework` (the Bexar candidate is looked up by its new source id).

The registry still holds 237 rows, and the source inventory still holds 360 sources (232 approved / 113 review required
/ 15 hard blocked). The admin Sources pin in `tests/run_test.mjs` is unchanged.

## Not verified

- The Bexar list's reuse terms: none are published, and none were reviewed.
- What the "struck off amount" binds at a private sale, beyond the information sheet's wording.
- Whether the OCR layer's amounts are exact. The County itself says the amounts are not guaranteed, and a misread digit
  in an amount cannot be detected.
- A runner read: no evidence-job run has read either county.
- Dallas: whether and when the County will post a list document again.

## What the owner would need to activate Bexar

1. A reuse / publication review of the source.
2. A sync for `harvest_tx_bexar_struckoff.json` that reads its own status file, plus a decision on the multiple-account
   section.
3. A workflow step (none exists; the Texas job is manual-only).
