# Florida sources batch - 2026-10-25

Three Florida sources found on 2026-10-25, added **backend only and gated**. Nothing here runs on a
schedule. The batch:

- adds no workflow step;
- leaves `sync-laft-to-supabase.ps1` and `sync-certificates-to-supabase.ps1` unchanged;
- makes no production write and adds no migration;
- changes nothing a customer sees.

Every figure below is a count or a shape. No case number, parcel, owner, applicant or amount from a
source is recorded here.

The owner's direction for this work: collect public records to fill gaps and show coverage, and sell
nothing until legal review. Neither new source publishes reuse terms. Each therefore has
`fetch` / `parse` / `store` records on `INTERNAL_RISK_ACCEPTANCE`:

- status `OWNER_PERMISSION_REQUIRED`;
- effective 2026-10-25, expiring 2027-04-12;
- condition `excluded_from_paid_tier`;
- reason ending "not sold until legal review."

That is an interim allowance, never documented permission (`decision.documented` is False). Neither
source has a `display`, `redistribute` or `fetch_via_proxy` record, so each of those is denied.

## Summary

| Source | Reachable from the sandbox | Registry standing | Count read |
|---|---|---|---|
| Lake County Lands Available on realTDM (`lake.realtdm.com`) | No: HTTP 403 from the vendor's AWS load balancer | `SOURCE_EXISTS_ACCESS_UNKNOWN` candidate (no source id, not runnable) | none |
| Charlotte County Clerk Lands Available (`fl_laft_charlotte`) | Yes | `MANUAL_REVIEW_REQUIRED` / `TERMS_NOT_VERIFIED` / `UNREVIEWED` | endpoint Total 4, 4 rows, all `LANDS AVAILABLE` |
| Leon County Tax Collector county-held certificates (`fl_leon_tc_certificates`) | Page and zip: Akamai 403 to `curl`; the zip was read once through the assistant's fetch tool | `MANUAL_REVIEW_REQUIRED` / `TERMS_NOT_VERIFIED` / `UNREVIEWED` | 121 certificates, list as of 2026-10-01 |

A non-production registry row can never be run: `harvesters/otc/gate.py` refuses everything that is not
`PRODUCTION_VERIFIED`, and the registry validator refuses a harvester name on a candidate row.

## 1. Lake County: realTDM

- **Read:** `https://lake.realtdm.com/public/cases/list` with the harvester's own User-Agent answered
  `HTTP 403` (`server: awselb/2.0`). In the same minute, the production tenant
  `https://alachua.realtdm.com/public/cases/list` also answered 403.
- **What the 403 means:** realTDM's load balancer refuses the sandbox's address. It says nothing about
  the tenant, so it is not a tenant check.
- **Not ruled out:** the tenant may be a `TEST` placeholder; `osceola.realtdm.com` and
  `nassau.realtdm.com` are placeholders (`_is_placeholder_tenant()`).
- **The Clerk's own portal** (`taxdeeds.lakecountyclerk.org`) was refused by the egress proxy.
- **Not added to `data/laft_realtdm_counties.csv`,** because the registry builder turns every row of that
  file into a `PRODUCTION_VERIFIED` / `APPROVED_GRANDFATHERED` source.
- **Lake's AVAILABLE candidate row** now names the realTDM URL, `GOVERNMENT_PLATFORM`, `HTTP_POST_FORM`
  and `HTML_CARDS`, last checked 2026-10-25.
- **Financial terms:** the source-wide `fl_laft_realtdm` row (`BASE_PRICE_PLUS_ADDITIONS`) already
  covers any realTDM county, so no new terms row is needed.
- **Next step:** a runner read showing the real "List of Lands - Available For Public" status on this
  tenant. Then add `Lake,lake,...` to the CSV in a reviewed change, since that makes it production.

## 2. Charlotte County: Clerk Lands Available (JSON endpoint)

### What the page is

`https://taxdeeds.charlotteclerk.com/TaxDeed/Lands`, read live on 2026-10-25:

- **Page:** an ASP.NET MVC page whose HTML has no data rows.
- **Grid:** the Kendo UI grid `#gridTaxCase` loads through its own `transport.read`, type
  `aspnetmvc-ajax`. That is a `POST /TaxDeed/GetTaxDeedViewByLandsAvailable` with the page's hidden
  `__RequestVerificationToken`, plus `page` / `pageSize` / `sort` / `group` / `filter`.
- **Response:** `{"Data": [...], "Total": n, "AggregateResults": null, "Errors": null}`.
- **Row fields:** Applicant, BaseBid, CaseId, CaseNumber, CertificateNumber, HighBid, Owners, ParcelId,
  SaleDate (an ISO datetime string), Status, Surplus.
- **Shapes:** case `99-9999`, certificate `9999-9999`, parcel twelve digits.
- **On 2026-10-25:** Total 4, 4 rows, every row `Status = "LANDS AVAILABLE"`.

This is the same kind of fix as Leon's `listoflands.txt`: read the data source the page's own script reads.

### The reader

`scripts/harvest_laft_charlotte.py`, source `fl_laft_charlotte`, follows the single-county script
pattern (Leon, Osceola).

**Mapped fields:**

| Source field | Output | Notes |
|---|---|---|
| CaseNumber | `case_no` | |
| CertificateNumber | `certificate_no` | |
| ParcelId | `parcel` | whitespace removed |
| SaleDate | `sale_date` | date part, MM/DD/YYYY |
| BaseBid | `bid` | only when > 0; `bid_kind` `OPENING_BID` (`laft_status.AMOUNT_KIND_BY_HEADER["base bid"]`) |

**Never mapped:**

- Owners;
- Applicant (the certificate holder who applied);
- HighBid / Surplus (a result is never inferred from a lands-available case);
- CaseId.

**Status file entries** (`out/harvest_laft_status.json`, harvester `fl_laft_charlotte`):

| Status | When |
|---|---|
| COMPLETE | rows kept, and the rows returned equal Total |
| EMPTY | only the endpoint's own `Total 0` with an empty `Data` and no `Errors` (`reported_count_zero`) |
| INCOMPLETE | the count differs (`PARSE_COUNT_MISMATCH`), no row has the offered status (`UNCONFIRMED_EMPTY`), or every row fails the identifier gate / a field is missing (`PARSE_FORMAT_CHANGE`) |
| FAILED | transport, missing token, non-JSON, or an unrecognised envelope |

- **Output:** `out/harvest_laft_charlotte.json`. No sync reads it.
- **`--fixture F.json`** reads one Kendo envelope, or a list of envelopes, with no network.
- **Live run against the real endpoint (2026-10-25):** COMPLETE, 4 of 4 rows kept, 0 other status,
  0 rejected.
- **Terms:** `data/available_financial_terms.csv` has a source-wide `fl_laft_charlotte` row, identical
  in basis to the other Clerk counties (`OPENING_BID_PLUS_ADDITIONS`, F.S. 197.502(6)-(7) and
  197.542(1)).
- **Registry:** the Charlotte candidate row is now `MANUAL_REVIEW_REQUIRED`, source id
  `fl_laft_charlotte`, `JSON_ENDPOINT` / `JSON`, with the endpoint as `document_url`. That makes
  Charlotte an acquisition-path unit with status `NOT_FOUND` (gap queue category F): no official
  acquisition page has been identified.

## 3. Leon County: Tax Collector county-held certificates

### The source

`https://www.leontaxcollector.net/Services/property-taxes/Certificate-Lists` ("Certificates Lists as of
October 1, 2026") links four dated zips under `/Portals/69/userFiles/CertFiles/`:

- `AllCertificates<date>.zip`
- `OpenCertificates<date>.zip`
- `OpenCountyCertificates<date>.zip`
- `RedeemedCertificates<date>.zip`

The page's own update schedule: "updated free of charge on the first business day following the last day
of the discount period due date (or the first business day of each month beginning in April)".

Leon is not a LienHub county, so this list is new certificate coverage, not a duplicate.

The reader takes **only the county-held list**, the same scope as LienHub's `countyheld` list. It finds the
link on the page by its `OpenCountyCertificates<YYYYMMDD>.zip` name and never constructs it. The date in
the file name becomes `list_as_of`.

### What the zip held (2026-10-25)

- **Contents:** one member, `OpenCountyCertificates20261001.xlsx`, with one sheet: a header and 121 data
  rows.
- **Headers** (as written, with stray spaces): bidderno, ceryear, cernumber, cerpartno, rollyear,
  interestrate, issuedate (a YYYYMMDD integer), holdername, holderaddr1, holderaddr2, holdercity,
  holderstate, holderzip, propertynumber, ownername, incareof, Asdbaname, address1, address2, address3,
  city, state, country, zipcode, taxcode, justvalue, taxablevalue, faceamt, legaldesc, subdiv, acreage.
- **Uniqueness:** (ceryear, cernumber, cerpartno) is unique on every row, and one parcel can carry
  several certificates.
- **Holders:** one holder on every row, and one interest rate on every row.
- **Owner columns:** address1, city, state and zipcode follow ownername. They are the owner's mailing
  address, not the property's situs.

### The reader

`scripts/harvest_leon_certificates.py`, source `fl_leon_tc_certificates`. It needs `openpyxl` (3.1.5 is
installed in the sandbox).

**Mapped fields** (to the row shape `sync-certificates-to-supabase.ps1` reads):

| Source field | Output | Notes |
|---|---|---|
| ceryear, cernumber, cerpartno | `case_no` = `certificate_no` | `<ceryear>-<cernumber>`, plus `-<part>` when the part is not 0 |
| rollyear | `tax_year` | |
| issuedate | `issued_date` | ISO |
| faceamt | `bid` | only when > 0; this is `CertificateRecord.face_amount` |
| interestrate | `interest_rate` | |
| propertynumber | `parcel` | whitespace removed |
| legaldesc | `legal_desc` | |
| (the Certificate Lists page) | `url_auction` | the sync marks it `county` |

**Never mapped:**

- owner name / in care of / DBA, and the owner mailing address (address1-3, city, state, zipcode);
- holder name / address;
- bidder number;
- just / taxable value;
- acreage, subdivision, tax code.

No expiration date is published, and none is derived.

**Status:** the reader writes its OWN status file, `out/harvest_certificates_leon_status.json`, because
the LienHub harvester overwrites `harvest_certificates_status.json`.

| Status | When |
|---|---|
| COMPLETE | rows kept |
| EMPTY | the recognised header with zero data rows (`empty_table`) |
| INCOMPLETE | the recognised header, but every row unusable |
| FAILED | transport, not a zip, not exactly one `.xlsx` member / one sheet, an unrecognised header, or an oversized file |

**Guards and output:**

- **Permission gate:** `fetch`, `parse` and `store` (dataset `county_held_certificates`) are each
  required before any request. A `--fixture` read checks only `parse` and `store`.
- **Output:** `out/harvest_certificates_leon.json`. No sync reads it.
- **Read of the real workbook (2026-10-25):** COMPLETE, 121 of 121 rows kept, 0 rejected, 0 duplicates,
  list as of 2026-10-01.
- **Registry:** a new LIENS_CERTIFICATES candidate row, `MANUAL_REVIEW_REQUIRED`, `XLSX`, publisher
  "Leon County Tax Collector". FL rows now total 147, and the registry 238 rows.

## Tests

`tests/python/test_sources_batch_2026_10_25_florida.py` uses SYNTHETIC fixtures only: invented values in
the live shapes, and an `.xlsx` built in memory. It covers:

- mapping, including that the synthetic owner, applicant, holder and values never reach the output;
- EMPTY only on an explicit signal, INCOMPLETE on count mismatch or unusable rows, FAILED on format change;
- token discovery and paging to the reported Total;
- zip-link discovery by name;
- the reader's own status file;
- the permission records, which are interim, carry `excluded_from_paid_tier`, deny `display`, and expire
  after 2027-04-12;
- refusal before any request when permission is denied;
- non-runnable registry rows, with Lake absent from the realTDM CSV;
- no workflow or PowerShell script naming either reader;
- the Charlotte terms row matching the Clerk counties.

Count pins updated for the new rows:

- `test_county_source_registry` (FL 146 → 147; candidates scoped per ledger);
- `test_alabama_onboarding` (FL + TX 212 → 213);
- `test_state_extensibility` (237 → 238);
- `test_three_ledgers` (production certificate rows only);
- `test_gap_closure` (73 acquisition units, 47 unresolved);
- the two publication-gate report tests (the new sources are UNREVIEWED).

## What the owner would need to activate either reader

1. A reuse / publication review of the source (`data/source_permissions.csv`, the admin publication panel).
2. A workflow step. Charlotte goes in the `laft` job, with its output added to
   `sync-laft-to-supabase.ps1`'s list. Leon needs a sync for `harvest_certificates_leon.json` that reads
   its own status file.
3. For Leon, a runner read: the Tax Collector's Akamai edge refused direct requests from the sandbox.
