# AVAILABLE publication evidence: five UNREVIEWED sources (2026-10-03)

Evidence gathered for the customer-publication decision on the five
AVAILABLE sources collected in production run 37062776012 (main
`4169067`). **Nothing here approves a source.** All five stay UNREVIEWED
(`harvesters/otc/adapters/expansion.PUBLICATION`, registry
`publication_status`); a test pins that.

Each fact is labelled by how it was obtained:

- **OFFICIAL DOCUMENT, READ**: the document itself was downloaded and its
  text read.
- **CAPTURE LOG**: from the value-free evidence captures (runs 37038385659,
  37039824035, 37040250643, 37033274319, 37035908843, 37036374756).
- **SEARCH INDEX ONLY**: a web-search summary of an official page. The page
  itself was **not** read. It is a lead to confirm, never a verified fact.

**Access limits on 2026-10-03.** The sandbox and the fetch tool were refused
by the egress proxy for buildingdetroit.org, arcgis.com,
services2.arcgis.com, detroitmi.gov, horrycountysc.gov, oceana.mi.us and
gtcountysc.gov. Web search worked. One official DLBA document, on the
DLBA's own storage host, could be downloaded. No evidence workflow was
dispatched: this pass was not authorized to dispatch production
workflows.

## 1. Acquisition-path semantics fix (this PR)

The review found that a county's downloadable form was presented as an
online purchase:

- Horry's county-wide FLC bid-form PDF was typed `direct_property_url` with
  `property` scope on all 51 rows.
- Oceana's and Georgetown's application PDFs resolved to mode `online`.

The customer page said "Purchase or apply online" for all three.

| | Before | After |
|---|---|---|
| Oceana MI (application PDF) | `application_page` / source / mode `online` | `application_download` / source / mode `application` ("Download the county application") |
| Georgetown SC (bidder application PDF) | `application_page` / source / mode `online` | `application_download` / source / mode `application` |
| Horry SC (FLC bid-form PDF) | `direct_property_url` / **property** / mode `online` | `application_download` / source / mode `bid` ("Bid application required - purchase process not online") |
| Horry registry `purchase_path_mode` | `online_property` | `application` |

**The rule** lives in `laft_purchase_paths.is_document_url` and
`mode_for_kind`, and in `purchase_path_engine.type_and_scope` and
`acquisition_mode`:

- A downloadable form (PDF / Word / Excel, or a CivicPlus `DocumentCenter`
  item) is an `application_download` at **source** scope.
- A `bid_form` or `offer_form` is mode `bid`.
- Neither is ever `online`.
- A genuine online purchase page keeps its `direct_property_url` and its
  `online` mode.

**What did not change:**

- Every source URL and `purchase_url_kind`, and every amount. Horry keeps its
  published minimum bid as `OPENING_BID`.
- The path-type vocabulary, which migration 023's CHECK constraint fixes. No
  migration was written.

**Frontend** (`public/app.js`):

- `purchasePathOf()` presents a property-action kind as the county's
  process, never as "Property-level link", when it is source scope or a
  document.
- `acquisitionOf()`'s type-only fallback follows the same rule.
- A `bid` mode gets the CTA "Download bid form".

**Rollout.** Production rows change only when the next scheduled expansion
run re-attaches paths after this PR is merged. No production row was
written here.

**Tests:**

- `tests/python/test_acquisition_path_semantics.py`: real adapter
  configurations and registry rows through `harvest_expansion.attach_purchase_paths`.
- `tests/run_test.mjs` check `acqPathHorryDetail`.

## 2. Detroit Land Bank Authority (30,661 lots + 12 program records)

### OFFICIAL DOCUMENT, READ: the DLBA Vacant Land Policy

- **URL:**
  `https://dlba-production-bucket.s3.us-east-2.amazonaws.com/DLBA+Policies/POLICIES+-+Vacant+Land+Policy+(FINAL+Oct+2023).pdf`
- **Title:** "DETROIT LAND BANK AUTHORITY AMENDED AND RESTATED VACANT LAND
  POLICY". 26 pages.
- **PDF metadata:** created 2023-10-04, modified 2023-10-23.
- **SHA-256:** `ac01ff4fa32154ca28c6bf04800124d77f1d90e56dab9485f093337823b6ffba`.
- **The DLBA's own website.** The document names it: the programs "will each
  be announced on the DLBA website at buildingdetroit.org". So the policy
  itself establishes buildingdetroit.org as the DLBA's site.

| Inventory status | What the policy says (short quotes) | Price in the policy | Who may buy |
|---|---|---|---|
| Side Lot For Sale | A vacant residential lot, at most 7,500 sq ft, "Adjacent to an applicant's property that contains an occupied residential structure of 1-4 units" | "Side Lots are priced at $100 per lot." | The applicant must "hold title to the Applicant's Occupied Property", be current on Detroit property taxes, and be in good standing with the DLBA |
| Neighborhood Lot For Sale | A vacant residential lot, at most 7,500 sq ft, "within 500 feet of an applicant's property that contains an occupied residential structure of 1-2 units" | "$250 per lot, unless the estimated value of the lot exceeds $2,500" (then priced under the Projects Procedures and Guidelines) | The applicant must hold title to the nearby home with a Principal Residence Exemption. A non-adjacent lot needs an endorsement (block club, Community Partner, Council Member or District Manager). The application is cancelled after 60 days without one. "No person ... may purchase in total more than two Neighborhood Lots in a calendar year." |
| Oversized Lot For Sale ("Oversize Lot") | A vacant residential lot of 7,500 to 15,000 sq ft, "Street Adjacent to the Applicant's Occupied Property" | "$200 per lot, unless the estimated value of the lot as determined by the DLBA exceeds $2,500" | The applicant must hold title to the adjacent occupied home, with a Principal Residence Exemption or proof of owner occupancy |
| Marketed Lot For Sale | **Not defined in this policy** | not in this policy | not in this policy |

**Process (policy):**

- A purchase is made by a "Complete Application ... to purchase property
  under this Policy".
- The DLBA holds applications for at least ten days after the first one
  arrives, then chooses by priority.
- The DLBA "may choose to remove a property from ... eligibility at any time
  and for any reason".

**What this establishes:**

- The three defined statuses are DLBA-owned lots offered through
  application programs, at policy prices.
- Each is restricted to a defined class of buyer: an owner-occupant of an
  adjacent or nearby Detroit home.
- They are **not** open-market inventory any customer can buy. Publishing
  them as "Available" without that restriction would misstate them.

### Not verified

- **Whether the October 2023 policy is still in force.** The policy itself
  says the rules "may be updated by staff periodically, and published on the
  website".
  - SEARCH INDEX ONLY: a buildingdetroit.org Neighborhood Lot page is
    summarised with "have not already purchased three Neighborhood Lots".
  - That differs from the policy's "two ... in a calendar year". The current
    rules may differ.
- **"Marketed Lot For Sale."**
  - SEARCH INDEX ONLY: buildingdetroit.org/marketing-programs is summarised
    as marketed properties sold through a contracted broker, with a process
    of roughly 90 days to closing.
  - Not read.
  - No price or eligibility is established.
- **Program records** (Own It Now 5, Renovation Programs 6, Economic
  Development 1). No official definition was read.
  - CAPTURE LOG: one `listing_date` was later than the read date.
- **The 1,000 "Marketed Lot For Sale" count.**
  - Our paging cannot produce it: one ordered query across all four
    statuses, and a truncated read fails the whole source.
  - The ArcGIS layer was unreachable for an independent count, so it is
    **not reconciled**.
- **Terms of use / licence.**
  - CAPTURE LOG: both ArcGIS items carry an empty `licenseInfo`.
  - The Vacant Land Policy contains no reuse or licence statement.
  - SEARCH INDEX ONLY: a buildingdetroit.org "Privacy Policy & Disclaimer"
    page exists. Not read.
  - **No licence is established.**
- **A per-lot price on the layer.** None exists. The policy prices are
  program prices, not values published on the record. Nothing was written
  to any row.

## 3. Horry County Forfeited Land Commission (51 records)

### The bid-form / guidelines PDF

`https://horrycountysc.gov/media/sinbmsz5/horrycountyflcguidelines.pdf` is
**unreachable** (egress-blocked). It was **not read**.

SEARCH INDEX ONLY, summarising that PDF (indexed title "Horry County
Forfeited Lands Commission ... FLC Bid Form") and the county page
"Guidelines: Purchasing Property from the Forfeited Land Commission":

- Bids only on the FLC Bid Form, in a sealed envelope with the PIN on the
  outside, Monday to Friday, 9:00am to 4:00pm, to the Horry County Assessor
  in Conway, SC.
- Minimum bid = delinquent and current taxes, plus penalties and costs, plus
  a 15% administrative fee.
- Payment in cash, certified check or money order, within one week of the
  bid-award notice. Deed recording fees, deed stamps and a deed-preparation
  attorney fee are added.
- "AS IS, WHERE IS"; quit claim deed.

These summaries are consistent with the `bid` mode (an offline sealed bid).
They are **not** a verified read, and none is recorded as an evidence row.

**Eligibility restrictions:** none found, but not verified.

### List-year accounting: NOT reconciled

| List | In capture (run 37038385659) | PIN cells (capture count) | Eligible under the rule on 2026-10-02? (on/after Jan 1 of year + 2) |
|---|---|---|---|
| 2020 FLC List | yes, HTTP 200 | 6 | yes |
| 2021 FLC List | yes | 3 | yes |
| 2022 FLC List | yes | 36 | yes |
| 2023 FLC List | yes | 5 | yes |
| 2024 FLC List | yes | 8 | yes (from 2026-01-01) |
| 2025 FLC List | yes | 20 | no - excluded (assignment list) |

**What the runs show:**

- The capture's PIN-cell count for the five eligible years is **58**. The logs do not say which years the harvester actually read.
- The harvest reported 51 records and "6 non-identifier row(s) skipped".
- Before `id_pattern` (run 37039824035) it reported 55 rows. Of those:
  - 51 had an 11-digit PIN;
  - one was a sentence-like note line;
  - one was a 3-letter word;
  - two had no printed shape.

**The gap.** 58 PIN cells against 51 records plus skipped rows does not add
up from the logs:

- The capture's "PIN cells" counter and the harvester's row reading count
  differently, and neither prints per-year counts.
- Two further things could explain it: a PIN repeated across years, or a
  2024 row without a DESCRIPTION column. The 2024 list carries no
  DESCRIPTION header in the capture, yet all 51 production rows have a
  description.
- A per-year production query was not run.

**So it is not proven which list years produced the 51 records, or that no
property row was omitted.** The next step is a read-only capture that prints,
per list year: rows, valid PINs, skipped rows with their shapes, and
duplicates.

## 4. Oceana MI and Georgetown SC

No new source material was reachable. The CAPTURE LOG facts in the 2026-10-02
review stand:

- **Oceana:** "Current Available Properties"; the Application for
  Proposals PDF.
- **Georgetown:** "2026 FLC LIST - UPDATED MAY 2026"; the "FLC Procedures
  and Bid Apps (PDF)"; the committee decides and notifies "the total amount
  due".

Both application PDFs remain unread.

## 5. What is still needed before any publication decision

1. **A reuse decision or permission for all five sources.** None publishes a
   licence.
2. **Detroit:**
   - confirm the current buildingdetroit.org program rules (prices, limits)
     and the meaning of "Marketed Lot";
   - decide how a buyer-restricted program lot may be presented, if at all;
   - reconcile the 1,000 count.
3. **Horry:** read the bid-form PDF directly, and get the per-year
   accounting of the 51 records.
4. **Merge this PR** so that no published record says "Purchase or apply
   online" for an offline form.
