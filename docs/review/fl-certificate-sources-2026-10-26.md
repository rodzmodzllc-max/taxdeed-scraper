# Florida certificate sources outside LienHub - 2026-10-26

## Why this exists

LienHub (Grant Street Group) has answered every GitHub runner with HTTP 403 since 2026-10-01. That block is never
worked around: no proxy, no other IP, no CAPTCHA or login.

Production on 2026-10-26 (read-only, counts only):
- 1,611 active FL certificate rows;
- every one links to its county's LienHub page;
- none has been refreshed by a LienHub read since the block began.

The owner's direction (2026-10-26): "find every property and every source, and then we'll work on the legal." So
this survey records, for each of the 32 LienHub counties, whether the county's own Tax Collector site publishes its
county-held certificate list anywhere other than LienHub. Where one was found and is publicly reachable, a reader was
built, with interim permission records.

No row value appears here: only counts, shapes and page locations.

## Method

The survey used two kinds of evidence:
- the repository's own records: `data/florida_certificate_sale_platforms.csv` (32 LienHub counties),
  `data/acquisition_candidate_pages.csv`, `data/enrichment_source_catalog.csv` and `docs/`. None of them held a
  non-LienHub certificate list for a LienHub county;
- one plain GET from the sandbox of each county Tax Collector home page (2026-10-26). The survey then followed
  certificate / county-held links one level, plus each site's sitemap.

These were plain public GETs with no login, form submission or retry. The sandbox's own egress proxy refused some
hosts; those are marked "not reached", which says nothing about the site.

## Result

| County | What the Tax Collector's own site offers for county-held certificates | Status |
|---|---|---|
| **Sarasota** | "County-Held Certificates for Purchase": `sarasotataxcollector.gov/files/docs/CountyHeldCertificates.pdf`, linked from `/services/tax-services/property-tax/tax-cert-sale`. A five-page table: ACCOUNT, CERT YEAR, CERT#, ASSESSED VALUE, FACE AMOUNT, INTEREST, TAX YEAR, two charge columns, PURCHASE PRICE. | **In production** (below) |
| St. Lucie | "County Held Certificates" page: purchase through the Lien Auction site (LienHub); the list itself is the TaxSys report "All County Held Certs". | TaxSys answered a GitHub runner with a Cloudflare 403 (run 40384773704). Stopped |
| Hillsborough | "County-Held Tax Certificates" page links LienHub, plus "Tax Certificate Search" / "download tax sale reports" on TaxSys (`hillsborough.county-taxes.com/public/reports/real_estate`, `county-taxes.net/.../reports/real-estate`). | TaxSys answered a GitHub runner with a Cloudflare 403 (run 40384773704). Stopped |
| Escambia | "County Held Certificate Sale" page points to `escambiataxsale.com` and LienHub; old sale-result PDFs (2011-2023). | `escambiataxsale.com` was not reachable. No current list found |
| Osceola | "County Held Certificates" link goes to `lienhub.com/county/osceola/countyheld/certificates`. | LienHub only |
| Lee | Both "Participate" and "Purchase or Research County Held Certificates" go to LienHub. | LienHub only |
| Flagler | "Purchasing County Held Certificates": "available for purchase through our vendor's website - LienHub". | LienHub only |
| Alachua, Brevard, Clay, Duval, Monroe, Okaloosa, Pasco, Sumter, Volusia, Walton | Certificate pages link only LienHub (sale, schedule, FAQ) and the county's own process / FAQ PDFs. No list. | LienHub only |
| Pinellas | "Tax Certificate & Tax Deed" page and FAQ; no county-held list linked. | No list found |
| Nassau, Santa Rosa, Seminole, Lake, Indian River | Home pages render their menus by script, and the sitemaps carry no certificate list page. | No list found (not exhaustive) |
| Bay, Broward | The site answered the sandbox 403. | Not reached |
| Charlotte, Citrus, Collier, Hernando, Martin, Orange | The sandbox's egress proxy refused these hosts (ProxyError / TLS). | Not reached: a runner read is needed |
| Miami-Dade | The tax collector URL tried redirected to the Clerk's finance page. | Not reached; candidate path not identified |

### TaxSys (`<county>.county-taxes.com` / `county-taxes.net`)

TaxSys is the counties' own online property-tax system. Grant Street hosts it, but it is a different service from
LienHub. St. Lucie's page names a TaxSys report, "All County Held Certs", as the county-held list, and Hillsborough
links TaxSys "tax sale reports".

**Runner read, owner decision 2026-10-26:**
- **Records:** interim `discover` / `fetch` / `parse` records for `fl_taxsys_county_held`.
- **The read:** `scripts/harvest_taxsys_certificates.py --check` made one GET per county, with no retry, through
  evidence run 40384773704 (`evidence_scope=taxsys_check`).
- **Result:**
  - `hillsborough.county-taxes.com/public/reports/real_estate`: HTTP 403, `server: cloudflare`, title "Just a
    moment..." (a Cloudflare browser challenge);
  - `stlucie.county-taxes.com/public/reports/real_estate`: the same response.

**Stopped and recorded.** It is the same kind of block as LienHub's, and it is never worked around: no browser
automation, no other address, no proxy. No harvester was built for TaxSys. The `--check` reader stays as the record of
the read.

## The Sarasota reader and sync (in production on the owner's decision of 2026-10-26)

- **Script:** `scripts/harvest_sarasota_certificates.py`, source `fl_sarasota_tc_certificates`.
- **Link:** read from the page's own "County-Held Certificates for Purchase" link, never constructed.
- **Identity, one row per certificate:**
  - `case_no` = `<tax year>-<CERT#>`, unique on all 232 rows of the live list;
  - `parcel` = ACCOUNT (94 accounts carry 232 certificates).
  - LienHub's Sarasota rows use the account as `case_no`, so the two sources never share a row under the key
    `(state, source, county, case_no)`.
- **Mapping:** CERT# goes to `certificate_no`, TAX YEAR to `tax_year`, ASSESSED VALUE to `assessed`, INTEREST to
  `interest_rate`, and PURCHASE PRICE to `bid`.
- **Not stored:** owner, address (the NOT NULL placeholder is "Account <account>") and issue date. The list publishes
  none of them.
- **Statuses:** COMPLETE / INCOMPLETE / FAILED. A zero is never EMPTY.
- **Permission:** `fetch` / `parse` / `store` / `display` / `link` records on `INTERNAL_RISK_ACCEPTANCE`:
  - status `OWNER_PERMISSION_REQUIRED`, jurisdiction `FL:Sarasota`;
  - effective 2026-10-26, expiring 2027-04-12;
  - condition `excluded_from_paid_tier`;
  - the reason cites the owner's decisions.

  There is no `redistribute` or `fetch_via_proxy` record.
- **Registry:** `fl_sarasota_tc_certificates` is `PRODUCTION_VERIFIED`, governance and publication `APPROVED`,
  authority `GOVERNMENT_DIRECT`. Its restrictions column records the owner's approval.
- **Sync:** `scripts/sync_sarasota_certificates.py` writes nothing after a FAILED read, and checks the store
  permission first. It then:
  - writes `source_id` = `harvester_source` = `fl_sarasota_tc_certificates`;
  - stamps `last_seen_at`, and keeps `first_seen_at`;
  - merges `field_provenance` as `county_list`;
  - applies the ledger contract and the stored-value guard;
  - closes only this source's own rows to `notfound`, and only after a COMPLETE read.

  The LienHub close-out (`sync-certificates-to-supabase.ps1`) now reads only LienHub's own rows.
- **Wiring:** two `continue-on-error` steps of the certificates job, independent of the LienHub steps.
- **Live reads on GitHub runners:**
  - run 40382658673 and run 40383361568: COMPLETE, 232 certificates kept, 0 rejected, header recognised on 6 pages;
  - list headed "2026 CERTIFICATES"; tax years 2019-2021 and 2023-2025; 94 accounts.
- **First production write:** the first scheduled certificates run after merge.

## Leon (PR #182)

- **State:** PR #182 is OPEN, mergeable, not merged.
- **What it adds:** `scripts/harvest_leon_certificates.py` (`fl_leon_tc_certificates`), which reads the Leon Tax
  Collector's dated "OpenCountyCertificates" workbook. It carries interim fetch / parse / store records (2026-10-25).
- **Not new for LienHub:** Leon is not a LienHub county (its sale platform is WFBSUSA), so it adds coverage but
  replaces nothing LienHub lost.
- **Last read:** its single read (121 certificates) was taken through the assistant's fetch tool, because the
  sandbox got Akamai 403s. A runner read has not happened.

## Still open

- **Hosts not reached here** need one runner read to know whether they publish a list: Charlotte, Citrus, Collier,
  Hernando, Martin, Orange, Bay, Broward, Miami-Dade and Escambia's `escambiataxsale.com`. There is no `discover`
  permission for them today, so the discovery guard would refuse the capture scripts.
- **LienHub's 32 counties** stay SOURCE_UNAVAILABLE.
