# Source links: what could be checked from the sandbox (2026-10-27)

Counts only. Paths are masked to their shape (digits → `#`); no parcel number
appears here. Produced with the new checker, offline mode:

    python3 scripts/check_source_links.py --no-db --dry-run

That mode reads the URLs held in the repository: every `canonical_url` /
`document_url` / `purchase_url` in `data/county_source_registry.csv` and every
URL in `public/acquisition-evidence.json`. **The property rows' own URLs were
not checked from here.** The sandbox cannot reach the Supabase REST API with
a service key. The daily workflow, `source-link-check.yml`, reads them with
keyset pages.

Production holds roughly 11,000 distinct property URLs. Read-only counts,
2026-10-27:

- 10,606 distinct active Available `purchase_url` values;
- a few hundred `url_auction` / `list_url` / `document_url` values;
- otc_provenance links: about 120 distinct in an 8,000-row sample.

Almost all of the purchase URLs are per-parcel pages on two hosts:

| Host | Per-parcel pages |
|---|---|
| `www.stlouis-mo.gov` | 8,807 |
| `public-sctn.epropertyplus.com` | 1,784 |

The workflow checks at most 1,500 URLs per host per run. Last run's failures go
first, then never-checked URLs, then the oldest. A full cycle of St. Louis
therefore takes about six days.

## Result: 346 distinct repository URLs on 239 hosts

| Result | Count | What it means |
|---|---:|---|
| OK | 211 | Answered 2xx (after redirects) |
| BROKEN | 14 | 404 from the source |
| BLOCKED | 107 | 403 (58) or a Cloudflare / bot challenge (49) |
| ERROR | 14 | 500 (6), TLS (3), connection (1), timeout (1), proxy (1), HTTP 400 (1), redirect not followed (1) |

### BLOCKED: not checkable from the sandbox

The sites themselves refuse the sandbox's datacenter address. The refusal is a
real HTTP 403 from the site, not from the agent proxy: the CONNECT succeeds,
then the site answers `server: awselb/2.0` or `cf-mitigated: challenge`.

| Host group | URLs |
|---|---:|
| `*.realtaxdeed.com` / `*.realforeclose.com` / `*.realtdm.com` | about 55 |
| `lienhub.com` | 31 of 32 |
| `library.municode.com` | 1 |
| Clerk sites: Baker, Escambia, Lee, Manatee, Palm Beach, Taylor, Union | |
| Others: `occompt.com`, `bid4assets.com`, Brazoria, Galveston and Johnson TX, York SC | |

The Actions runners will check these from a different address. They may get
answers; LienHub has refused runners before. A BLOCKED result never hides a
link.

### BROKEN: 404 from the source, in the repository's own records

| Where | Masked path | Ref |
|---|---|---|
| registry `document_url` (Hendry, both rows) | `mcclibraryfunctions.azurewebsites.us/api/munidocDownload/#####/…/pdf` | 2 |
| registry `document_url` | `app.pascoclerk.com/public_records/tax-deeds/List%##of%##Lands…pdf` | 1 |
| registry `document_url` | `www.gtcountysc.gov/DocumentCenter/View/####/####-FLC-LIST---UPDATED-MAY-####-PDF` | 1 |
| registry `document_url` | `www.fayettecountypa.org/DocumentCenter/View/#####/Repository-Update-…` | 1 |
| registry `document_url` | `www.tax-sale.info/catalog/getCsv/id/` | 1 |
| registry `canonical_url` | `campcad.org/struck-off-list/` | 1 |
| registry `canonical_url` | `pioneer.okeechobeelandmark.com/TaxSmartWebLive/` | 1 |
| registry `canonical_url` | `www.revenue.alabama.gov/property-tax/delinquent-search/` | 1 |
| acquisition evidence | `www.brevardclerk.us/lands-available` | 1 |
| acquisition evidence | `www.eatoncounty.org/####/####-Foreclosure-Sale` | 1 |
| acquisition evidence | `www.fayettecountypa.org/DocumentCenter/View/####/Repository-Bid-Form` | 1 |
| acquisition evidence | `www.greencountywi.org/DocumentCenter/View/####/Tax-Deed-Bid-Form` | 1 |

Notes on some of these:

- The `tax-sale.info` getCsv path is an API template, not a page. Alabama is
  not activated.
- The Fayette and Georgetown list documents are dated files. The harvesters now
  pick the newest dated file, so these registry entries are stale pointers.
- The Pasco list PDF is dated, and the same is likely true for it.
- The evidence pages are customer-visible: they appear in the acquisition path
  ("Official source"). They need a fresh capture (`job=evidence`,
  `evidence_scope=acquisition_candidates`) and an evidence-row update. Until
  then, once the daily check has seen them broken twice, the app shows them as
  "Link broken at source".

### ERROR: not proof either way

- `public-*.epropertyplus.com/.../getPublishedProperties`: 500 on a plain GET.
  It is the harvester's POST/paging API, not a page, and is not rendered as a
  link.
- `taxdeeds.charlotteclerk.com/.../GetTaxDeedViewByLandsAvailable`: 400. It is
  the Kendo grid JSON endpoint and needs its own parameters.
- `taxsales.lgbs.com`: TLS failure from the sandbox.
- `jeffcotax.com/.../delinquent-tax-sale/`: the redirect was not followed.
- Grayson, Gregg and Jefferson TX, and Maricopa AZ: 500, timeout or connection
  failures.

## Six SOURCE_UNAVAILABLE counties in the 2026-10-27 laft run

| County | Source / note | From the sandbox |
|---|---|---|
| Hendry | Municode PDF | BROKEN: 404 on both stored document URLs |
| Charlotte | Kendo grid | ERROR: 400 to a parameterless GET, expected; the runner got 403 |
| Escambia | clerk site | BLOCKED: 403 |
| Manatee | clerk site | BLOCKED: 403 |
| Union | clerk site | BLOCKED: 403 |
| Columbia | | No registry URL answered BROKEN or BLOCKED for it here |

## What changes in the app

- **Broken links.** A link that was BROKEN on two separate daily checks is shown
  as its label plus "Link broken at source (checked <date>)", with no href.
  BLOCKED and ERROR links stay links.
- **Unconfirmed Available records.** An Available record whose own source has
  not confirmed it is withheld from customers: `last_seen_at` NULL, or older
  than 7 days.
  - Production on 2026-10-27 had three such rows:
    - Hendry: two rows, never confirmed;
    - one `fl_laft_html` row, last confirmed more than 7 days ago.
  - The ledger, or the county, says records are withheld because the source
    could not be read.
  - Nothing is closed.
