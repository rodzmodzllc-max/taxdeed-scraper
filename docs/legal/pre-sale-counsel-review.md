# Pre-sale counsel review package

Prepared 2026-09-26 by engineering, for a licensed attorney to review before
the product is offered for sale. **This document is not legal advice and
does not claim that anything here is lawful, compliant or approved.** It
records what the product does, what data it holds, where that data comes
from, and what the repository says about each source's terms. Every
question that needs a legal answer is listed in the last section, not
answered.

Companion document: [`pre-sale-blockers.md`](pre-sale-blockers.md), which
sorts open items by when they must be resolved.

## How to read the evidence labels

Every statement about a source's terms or rights carries one of these four
labels:

| Label | Meaning |
|---|---|
| **Confirmed from source documentation** | Engineering read the source's own published terms, EULA, robots file or licence text and quotes or cites it in the repository. |
| **Source restriction recorded in repository** | A restriction is written down in this repository (in a rights audit, a registry entry or a harvester comment), but nobody re-read it live for this review. The sandbox used for this review could not reach most terms pages. |
| **Not yet verified live** | Nobody has recorded the source's terms. Neither a restriction nor a permission is known. |
| **Attorney interpretation required** | The facts are recorded, but whether the use is allowed depends on a legal reading. |

These labels describe the evidence. They are not conclusions.

---

## 1. Product model

- A private web app (a PWA at `rodz-taxdeeds.pages.dev`) that lists Florida
  and Texas tax-sale properties for a small, invite-only group.
- **Access:** anyone can sign up. An administrator must approve an account
  before it sees any data (`profiles.approved`, enforced by row-level
  security and an `is_approved()` check).
- **Current use:** internal research by the owner and partners. The
  proposed change is to charge outside customers for access. **No payment
  flow exists in the code.**
- **What a user sees:**
  - listings, with the county's opening or minimum bid;
  - county roll values;
  - parcel, owner and legal-description fields where a source supplied
    them;
  - an overhead aerial image;
  - map views;
  - links out to county, vendor and third-party sites.
- **What a user can do:**
  - favourite, hide or watchlist a listing (all private to the user);
  - leave notes, which are **shared with every approved member**;
  - use a scenario worksheet that does arithmetic on the user's own inputs;
  - export CSV files.
- **What the product does not do:**
  - It does not place bids.
  - It does not run a title search.
  - It does not track auction outcomes. There is no sold, redeemed or
    winning-bidder data. `winning_bidder_ref` is always NULL.
  - It does not produce an appraisal.
  - It does not give a recommendation. The former "Top pick" label is now
    "Filter match", a user-controlled arithmetic filter.
- **Email:** a "favourites with a sale date in the next N days" digest is
  written (`supabase/functions/send-digest/`), but **it is not deployed**.
  Production has zero Edge Functions (checked 2026-09-26).

## 2. Populations (production snapshot, 2026-09-26 00:20 UTC, read-only)

| State | Ledger | Rows |
|---|---|---|
| FL | Tax deed auctions | 1,960 |
| FL | Tax certificates (county-held) | 1,667 |
| FL | Lands Available for Taxes (LAFT) | 159 |
| TX | RealAuction county sheriff/tax sale sites | 91 |
| TX | LGBS auction listings | 19 |
| TX | LGBS struck-off / resale | 421 |
| **Total** | | **4,317** |

The auction-event and observation history tables (migration 014) hold 0
rows. The Phase B writers are in PR #33, which is unmerged.

### Field completeness (same snapshot)

**FL auctions (n = 1,960)**

| Field | Rows | Share |
|---|---|---|
| Opening bid | 1,959 | 99.95% |
| Parcel | 1,908 | 97.35% |
| Appraiser link | 1,809 | 92.30% |
| Assessed value | 1,669 | 85.15% |
| Coordinates | 1,617 | 82.50% |
| Stored image | 1,614 | 82.35% |
| Just value | 1,498 | 76.43% |
| Owner name | 1,485 | 75.77% |
| Legal description | 1,477 | 75.36% |
| FDOR enrichment | 1,477 | 75.36% |

**FL certificates (n = 1,667)**

| Field | Rows | Share |
|---|---|---|
| Coordinates | 858 | 51.47% |
| FDOR enrichment | 678 | 40.67% |
| Legal description | 531 | 31.85% |

**FL LAFT (n = 159):** most enriched fields are present on 137 rows
(86.16%).

**TX (n = 531)**

| Field | Rows | Share |
|---|---|---|
| Valuation beyond the vendor's own figure | 0 of 531 | 0% |
| RealAuction legal description | 0 of 91 | 0% |
| RealAuction coordinates | 49 of 91 | 53.85% |
| LGBS reference links | 0 | 0% |
| `tx_sale_status` | 0 of 531 | 0% |

**Stored images:** 3,136. All are USDA NAIP aerial imagery
(`photo_source = usda_naip`). There are no Google Street View images and
no `''` "checked, no image" rows.

---

## 3. Source register

The detail for each source lives in:

- `docs/source-registry.md`
- `harvesters/governance/registry.py`
- `docs/realauction-rights-audit.md`
- `docs/lgbs-rights-audit.md`
- `docs/image-rights-policy.md`
- `docs/data-licensing.md`
- `docs/provider-authorization-status.md`

This table summarises them for counsel. **Nothing in it was re-verified
live for this review.**

| Source | What we take | How | Evidence label | What the repository records |
|---|---|---|---|---|
| **RealAuction / RealForeclose / RealTaxDeed** (46 FL county sites; the 91 TX rows also come from RealAuction county sites) | Auction calendar, case, parcel, opening bid, sale URL | Automated harvest. FL runs on the twice-daily `deeds` cron; the TX schedule has not been re-checked for this review | **Source restriction recorded in repository.** **Attorney interpretation required.** | EULA text "as supplied" says the site is for purchasing or attempting to purchase property. It prohibits automated access without approval, and says content "cannot be used, altered, sold, or distributed without RealAuction's express written consent" (`docs/realauction-rights-audit.md`). No written consent is on file. |
| **LienHub** (32 FL counties, tax certificates) | Certificate number, amount, rate, issue date, owner name, owner address | Scheduled automated harvest; backs off on HTTP 403 (WAF) | **Source restriction recorded in repository.** | Terms say robots and spiders are "EXPRESSLY PROHIBITED", and redistribution is restricted. |
| **Bid4Assets** (Okaloosa) | Auction listings | Scheduled harvest | **Not yet verified live** | No terms recorded. |
| **County LAFT PDFs / HTML / RealTDM** (32 FL counties) | Lands Available lists | Scheduled harvest | **Not yet verified live** (per county) | 8 non-PDF LAFT platforms have no registry entry. |
| **Orange County LAFT** | LAFT list | A disclaimer page is accepted programmatically | **Attorney interpretation required** | The harvester clicks through the county's disclaimer. |
| **Volusia County LAFT** | LAFT list | The disclaimer step is bypassed | **Attorney interpretation required** | Recorded in the harvester. Not to be expanded (task constraint). |
| **Osceola Clerk (NewVision)** | LAFT list | Direct calls to the portal's JSON API | **Attorney interpretation required** | Plaintext API calls behind a browser UI. |
| **ScraperAPI** (proxy vendor) | Used to route requests to sources that block by IP | Paid proxy | **Attorney interpretation required** | Used specifically to get past IP blocks. The vendor's own terms are not recorded. |
| **FDOR NAL/SDF** (Florida Dept. of Revenue roll) | Just/assessed/land value, use code, owner, legal description, building facts | Bulk public file download | **Not yet verified live** | "No restriction found; no permission found." |
| **LGBS** (`taxsales.lgbs.com` API, Texas) | Texas sale and struck-off listings | Manual `workflow_dispatch` only | **Source restriction recorded in repository.** **Attorney interpretation required.** | `www.lgbs.com/legal-disclosures/` contains a use clause. Whether it governs the `taxsales` API is unresolved (`docs/lgbs-rights-audit.md`). |
| **US Census Geocoder** | Coordinates | API | **Not yet verified live** | Federal data. Terms not recorded. |
| **FEMA NFHL** | Flood zone | API | **Not yet verified live** | Federal data. Terms not recorded. |
| **USDA NAIP** | Aerial images, **stored** in the public Supabase bucket `property-photos` | Fetched and cached | **Not yet verified live** | Generally public-domain federal imagery, but this is not confirmed in the repository. The images are publicly reachable by URL. |
| **Google Maps JS API** | Basemap (satellite/roadmap toggle) | Browser, Demo Key | **Attorney interpretation required** | Google calls a Demo Key testing-only. It is not for production or commercial use. |
| **Google Street View Static** | *Not used in production.* The script exists, the key is unset, and there are 0 stored rows. | — | **Source restriction recorded in repository** | Caching is likely restricted under Google's terms. Not live-verified. Caching must not start (task constraint). |
| **MapTiler** | Basemap and static satellite thumbnails | Browser, free plan, origin-restricted key | **Not yet verified live** | Free-plan commercial-use terms are not recorded. |
| **OpenStreetMap** | Embedded map on the property page | iframe | **Not yet verified live** | The tile usage policy is not recorded. |
| **Santa Rosa / Palm Coast GIS** | Enrichment | API | **Not yet verified live** | No registry entry. |
| **Zillow** | Outbound search link only (no data taken) | Link | **Not yet verified live** | Only a link, but it uses Zillow's name. |

### Deferred / blocked sources (not active)

| Source | Registry status |
|---|---|
| PBFCM | BLOCKED |
| MVBA | BLOCKED |
| CTSA | BLOCKED |
| GovEase | BLOCKED |
| HCTAX | LEGAL_REVIEW_REQUIRED |
| Texas Comptroller directory | DISCOVERED |
| Texas appraisal-district enrichment | Not started (task constraint) |

None of these supply rows. None were touched in this pass.

---

## 4. Rights questions (facts for counsel)

- **Collection.** Several active sources record a prohibition on automated
  access (RealAuction, LienHub). Several others are reached by getting past
  an access control:
  - a clicked-through disclaimer (Orange);
  - a bypassed disclaimer (Volusia);
  - a private JSON API (Osceola);
  - IP-block avoidance through ScraperAPI (several sources);
  - WAF back-off (LienHub).

  None of these behaviours was changed in this pass.
- **Redistribution.** The product would show harvested facts to paying
  third parties. RealAuction's recorded EULA and LienHub's recorded terms
  both restrict redistribution.
- **Public-record status.** Much of the underlying information (sale
  dates, parcel numbers, opening bids, owner of record) is public record at
  the county. The **vendor's compilation and presentation** of it may carry
  separate terms.
- **Stored imagery.** 3,136 NAIP images sit in a public bucket.
- **Mapping keys.**
  - Google is a Demo Key.
  - MapTiler is on a free plan.
  - OSM tiles are embedded.

  Commercial-use terms for each are not recorded.

## 5. Personal-data questions (facts for counsel)

Nothing below was changed or deleted in this pass. Git history was not
rewritten.

| Data | Where it lives | Who can see it |
|---|---|---|
| **Owner name** (LienHub, FDOR) | `properties.owner_name`. Shown on cards and property pages, searchable in the main search box, and exported in the CSV `Owner` column | Every approved user |
| **Owner mailing address** (LienHub) | Written into `properties.address` when a certificate has no property address, so it can be shown as if it were the property's address | Every approved user |
| **Owner, applicant, sold-to and winning-bid fields** in raw harvests | Dropped at sync, but present in **GitHub Actions artifacts of a public repository** (30-day retention) | The repository is public. Whether artifact download needs sign-in or repository permission should be checked by counsel/engineering |
| **Database backup** (includes owner names and user notes) | GitHub Actions artifact, 90-day retention | Same as above |
| **Applicant / buyer names** | Committed in `data/laft_pioneer_counties.csv` (Citrus row notes: several company names and "IL IL IRA Investments LLC") | Public, in git history |
| **Customer sign-up data** | `profiles`: first and last name, company, address and phone are requested at sign-up | Administrators |
| **Notes** | `notes`. The author's email prefix is shown to every approved member | Every approved member. The Terms now say so. They previously said notes were private |
| **Account deletion** | No self-service deletion flow exists | — |
| **Email digest** | Would email favourites to users. Not deployed. There is no one-click unsubscribe | — |

**Engineering remediation options (recommendations only, none done):**

- Stop exporting `owner_name` in the CSV, or make it opt-in.
- Stop writing LienHub owner mailing addresses into `address`. Label it
  or drop it instead.
- Shorten artifact retention, or strip personal fields before upload.
- Make the repository private again, or move artifacts to private storage.
- Remove applicant names from the committed CSV going forward. Removing
  them from history would need a history rewrite, which is outside this
  task.
- Add account deletion and an export-your-data flow.
- Add a real unsubscribe before the digest ever goes live.

## 6. Positioning questions (facts for counsel)

Copy corrected in this pass is listed in the PR description. It covers:

- NAIP imagery that was labelled "Street View";
- the false "notes are private" statement;
- "title screening", "Title: Clear", "Top pick", "Yield", "profit" and
  "return" language;
- "Closed" wording that implied a sale;
- Florida statutes shown on the Texas page;
- the manifest's "title screening" and "true acquisition cost";
- "live county auction";
- "scraped on a schedule" for manually run Texas data;
- "every tracked field is present";
- the digest's $0 bid and "closing soon" wording.

Remaining positioning items for counsel:

- **Homestead fee estimate (open question).** Florida `fees()` adds half the
  assessed value on a homestead parcel on top of the county's published
  opening bid. FS 197.502(6)(c) may already fold that amount into the
  opening bid. In production, 114 of the 122 FL homestead auction rows that
  have both figures show a bid of at least half the assessed value (median
  bid ÷ (assessed ÷ 2) = 1.12). That fits the amount already being
  included, but does not prove it. The arithmetic was **not** changed. It
  is disclosed as an open question in the fee tooltip and the Terms, and
  pinned by `tests/python/test_launch_readiness_honesty.py`. It needs an
  accountant or attorney.
- **Texas redemption summary.** The Texas "Redeemable Tax Deeds" ledger
  copy summarises Tex. Tax Code §34.21 (180 days / 2 years, 25% / 50%). It
  now says it is orientation only. Counsel should confirm or remove it.
- **Scenario worksheet.** It now says it is arithmetic on user inputs, not
  an appraisal, profit forecast or advice. Counsel should decide whether
  any investment-advice or real-estate licensing question arises from
  offering it to paying customers.
- **Filter match** (value ÷ bid ≥ 12× plus a "no flags noted" manual lien
  note). Counsel should decide whether any filter that ranks properties
  needs further disclaimer.
- **Brand name.** "Tax Acquisitions" has not been checked for trademark
  conflicts.

## 7. Documents counsel will need to draft or approve

- Terms of Service for paying customers. The current in-app Terms modal is
  an internal-use disclaimer.
- Privacy Policy covering:
  - sign-up data;
  - notes;
  - owner names of record;
  - retention;
  - deletion;
  - sub-processors (Supabase, Cloudflare, GitHub, Google, MapTiler,
    Resend if the digest ships).
- Acceptable Use terms, including a prohibition on reselling exports.
- Email and marketing consent language, and an unsubscribe mechanism,
  before any digest or marketing email is sent.
- Data-source licences or written permissions, where counsel concludes
  they are needed (see `docs/provider-authorization-requests.md`; **no
  request has been sent**).
- A disclaimer set approved by counsel. It should replace the
  engineering-written disclaimers in the app, the footer and the digest.

---

## 8. Questions for counsel — not answered by engineering

1. Can the product lawfully sell access to data collected from RealAuction
   sites, given the recorded EULA language on automated access and on
   redistribution without written consent? Is written permission required
   before accepting any payment?
2. Same question for LienHub, given its recorded "robots and spiders
   expressly prohibited" and redistribution terms.
3. Does the LGBS legal-disclosures clause govern the `taxsales.lgbs.com`
   API, and does it allow commercial display?
4. Are the Orange (clicked-through disclaimer), Volusia (bypassed
   disclaimer) and Osceola (private JSON API) collection methods acceptable
   at all? Does the answer change once the product is sold?
5. Does using ScraperAPI to get past IP blocks create exposure (e.g. under
   the CFAA, Florida or Texas computer-access statutes, or contract claims)?
   Should it be discontinued before sale?
6. Does county public-record status protect display of the underlying facts
   even where the vendor's terms restrict their compilation?
7. Can owner names of record be displayed, searched and exported to paying
   customers? Under which laws, and with what notice?
8. Does writing LienHub owner mailing addresses into the address field
   create a privacy or accuracy problem?
9. Must the public-repository GitHub Actions artifacts and the committed
   applicant names be removed? Is a git history rewrite warranted?
10. What must the Privacy Policy say about notes, sign-up data, account
    deletion and sub-processors?
11. Does the email digest, if deployed, need CAN-SPAM-compliant
    identification, a physical address and a functioning unsubscribe?
12. Is the Google Maps Demo Key usable in a paid product? It is not,
    according to Google's own description of the key. What licences do
    MapTiler's free plan and OSM's tile policy allow?
13. Can NAIP imagery be stored and served publicly in a commercial
    product, and does it need attribution?
14. Is the homestead fee estimate misleading in its current, disclosed
    form? Should it be withdrawn until an accountant confirms the
    calculation?
15. Is the Texas §34.21 redemption summary acceptable as orientation text,
    or should it be removed?
16. Do the scenario worksheet, value ÷ bid filter and "Filter match" tag
    raise any investment-advice, real-estate-broker or consumer-protection
    concern once customers pay?
17. Is "Tax Acquisitions" clear to use as a trade name?
18. Which entity sells the service, and what limitation-of-liability and
    indemnity terms are needed, given that users bid real money at county
    sales?
