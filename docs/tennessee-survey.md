# Tennessee statewide source survey (2026-10-08)

**Method.** This survey used web search only, across all 95 counties, split by grand division. No county page was opened from the sandbox, because every county host failed DNS resolution there. Every URL below appeared in search results, but none has been read directly yet. Every date and format still needs a live read before anything is built on it. Aggregators (taxsaleresources, goliathdata, etc.) are excluded as sources.

**What Tennessee sells.** The Chancery Court Clerk & Master (C&M) runs court-ordered delinquent-tax sales of **redeemable deeds**. In Fentress County the Circuit Court Clerk runs them instead. Key terms:
- **Redemption:** generally one year from the order confirming the sale, though some courts set 90 or 180 days. The buyer is refunded with 12% a year. Source: [Blount 2026 procedures](https://www.blounttn.gov/DocumentCenter/View/26595/2026-Delinquent-Tax-Procedures-PDF).
- **Opening bid:** taxes plus interest, penalties and costs.
- **Unsold parcels:** go to the county or city. They are resold later by a land bank, a property office or a Delinquent Tax Committee, usually by sealed bid with a 10% upset bid.

**How it maps to TAXACQ's ledgers:**
- **Auctions:** the C&M sales.
- **Available:** county-owned parcels resold after a sale (land banks, surplus property).
- **Liens & Certificates:** Tennessee sells no tax-lien certificates, so this ledger stays empty for Tennessee.

## Strongest sources

| Rank | County | Ledger | Source | Why |
|---|---|---|---|---|
| 1 | Shelby | Available | [Shelby County Land Bank](https://landbank.shelbycountytn.gov) | Government listing and map of county-owned parcels at a stated price (appraised value). Defined online application. Restocked from tax-sale leftovers 2–4 times a year. Over 4,500 parcels in 2019 ([state report](https://comptroller.tn.gov/content/dam/cot/sboe/documents/tax-incentive-programs/2019LandBankReport.pdf)) |
| 2 | Shelby | Auctions | [Clerk & Master Tax Sale Information](https://www.shelbycountytn.gov/330/Tax-Sale-Information) + numbered sale-book PDFs (e.g. [TS2202](https://www.shelbycountytn.gov/DocumentCenter/View/45087/TX-2024TS2202SaleBook)) | 2–3 sales a year, with sale books listing parcel, high bid and redemption dates. Bidding is online at ZeusAuction (SRI), the vendor the county designates |
| 3 | Davidson | Auctions | [Chancery Clerk & Master tax-sale schedule](https://chanceryclerkandmaster.nashville.gov/fees/property-tax-schedule/) | Most frequent cadence in the state: up to about 8 sales a year. One PDF list per sale, with a consistent file naming pattern |
| 4 | Hamilton | Available + results | [Real Property Office](https://hamiltontn.gov/Department_RealPropertyOffice.aspx) | Sealed-bid PDF lists with minimum bids and bid-opening schedules, plus [sold lists with prices](https://www.hamiltontn.gov/pdf/RealProperty/2025sale/March/Sold-Property-List.pdf). Several sales a year |
| 5 | Hamilton | Auctions | [2026 tax sale notice](https://www.hamiltontn.gov/Clerkmasterforms/taxsale/2026TaxSale/TAX%20SALE%20INFORMATION%202026.pdf) | Annual sale in early June, with predictable yearly URLs |
| 6 | Montgomery | Auctions + results | [Tax sale page](https://montgomerytn.gov/chancery/tax-sale) | Yearly GovEase sale in September. The only county seen that publishes the properties sold |
| 7 | Rutherford | Auctions | [rcchancery.com](https://rcchancery.com/delinquent_sales) | Yearly GovEase sale, plus a searchable delinquent-tax database |
| 8 | Knox | Auctions + Available | [Trustee tax-sale page](https://www.knoxcounty.org/trustee/tax_sale_info.php) | Largest annual sale outside Memphis (about 342 parcels in June 2026, per an aggregator). Surplus is sold through Powell Auction, a vendor |
| 9 | Hawkins | Auctions + results | [C&M page](https://www.hawkinscountytn.gov/chancery_court_clerk_master.html) | GovEase sales twice a year, with a published results section |
| 10 | Morgan / Anderson / Greene / Sumner | Available | [Morgan back-tax](https://morgancountytn.gov/?p=426), [Anderson county-held PDFs](https://andersoncountytn.gov/wp-content/uploads/2024/02/Feb.2024-county-held-properties.pdf), [Greene sealed-bid PDF](https://www.greenecountytngov.com/wp-content/uploads/2025/09/Greene-County-Delinquent-Property-Tax-Sale-2025.pdf), [Sumner Delinquent Tax Committee](https://sumnercountytn.gov/sale-of-delinquent-tax-committee-parcel/) | Smaller county-held resale programs |

Other counties with an official list or notice online:
- **Blount:** [list posted about a month before the June sale, updated weekly](https://blounttn.gov/2029/Delinquent-Property-Tax-Sale).
- **Campbell:** dated [versioned PDF lists](https://campbellcountytn.gov/wp-content/uploads/2024/10/2023-DT-Tax-Sale-List-updated-04-14-26-@11.pdf).
- **Roane:** [C&M page](https://roanecountytn.gov/clerk-and-master).
- **Robertson:** [GovEase sale](https://robertsoncountytn.gov/departments/clerk_and_master/chancery_auction_sale.php).
- **Lawrence:** [GovEase notice](https://lawrencecountytn.gov/wp-content/uploads/2026/08/Notice-of-Sale-2026.pdf).
- **Sumner:** [C&M page](https://sumnerchancerycourt.com/delinquent-taxes/).
- **City of Memphis:** [real estate](https://www.memphistn.gov/real-estate).
- **Jackson–Madison County:** [surplus](https://jacksontn.gov/government/surplus_property).

**No list found online:** about 60 counties, mostly smaller and rural. Their sales appear only in local newspapers and the C&M office.

**Vendors seen.** Several counties run their sales on vendor platforms: ZeusAuction/SRI (Shelby), GovEase (Montgomery, Rutherford, Robertson, Lawrence, Hawkins, Lincoln), Powell Auction (Knox surplus), and in the past CivicSource (Hamilton). Reusing a vendor's own pages needs a terms review first. Where possible, the county's own published list is the preferred source.

## Build order

1. **Shelby** (built, see below): the Land Bank (Available). The C&M sale books turned out to be post-sale results, not an upcoming-sale list.
2. **Davidson and Hamilton**: read 2026-10-09, nothing buildable yet (see below).
3. **Montgomery, Rutherford, Knox**: read 2026-10-09, nothing buildable yet (see below).

Every Tennessee source starts unreviewed: collected for admins and never customer-published until an admin review approves it.

## Shelby County: what the live reads established (2026-10-08)

There were five value-free evidence runs (`job=evidence`, `evidence_scope=tn_shelby`, `scripts/capture_tn_shelby.py`): 37855584514, 37855783595, 37856005485, 37856189946 and 37856396525. None of them printed a row, name, address, parcel number or amount.

**Land Bank inventory (built).** `landbank.shelbycountytn.gov` is a static Next.js site. Its pages send buyers to the Land Bank's ePropertyPlus portal, `public-sctn.epropertyplus.com`. The portal's own code reads `/landmgmtpub/remote/public/property/getPublishedProperties?page=<n>&limit=<k>` anonymously. The response is `{success, size, rows}`.
- **Size:** 12,884 published parcels, all in Shelby County. Each parcelNumber is unique, a 14-character county parcel ID.
- **Coordinates:** 12,877 rows carry coordinates inside Tennessee.
- **Fields:**
  - status: `currentStatus`, `available` (Y/N), `inventoryType` (`County DTP` for 12,843 rows);
  - property: `propertyClass` (mostly Residential Vacant), `propertyAddress1`, `city` (`TBD` on 8,730 rows);
  - money: `currentAssessment` and `assessmentYear`, `askingPrice` (filled on 12,715 rows);
  - `comments`, which is free text and never mapped.
- **Rule for Available:** the portal's own fields must say the parcel is offered, meaning `currentStatus` is `FOR SALE` and `available` is `Y`. That holds for 2,039 rows. Every other status is not read:
  - closed or pending sales: SALE COMPLETE (9,229), SALE CLOSED OUT, SALE PENDING (with or without CC), SALE APPROVED PENDING CLOSING;
  - donations: DONATION PENDING, DONATION COMPLETE and its compliance monitoring;
  - redemption: IN REDEMPTION, Redeemed, Notice to Redeem;
  - holds and evaluations: Commission Hold, Hold for Litigation, IN EVALUATION;
  - other: NOT FOR SALE, Rescinded, Retired, Demolition Pending.
- **Amount:** `askingPrice` is kept as a published amount of unspecified kind (`PUBLISHED_AMOUNT_KIND_UNSPECIFIED`, financial basis `OFFER_NEGOTIATED`). It is never called a fixed price: the Land Bank's Policies & Procedures page links an *Offer to Purchase and Sales Agreement Packet*. That packet is a scanned PDF with no text layer, so its terms were not read.
- **Where it lives:** adapter `harvesters/otc/adapters/epropertyplus.py`, config `TN_SHELBY_LANDBANK` (`harvesters/otc/adapters/expansion.py`), source id `tn_shelby_landbank`. It is **UNREVIEWED**: collected for admins and never customer-published until an admin review approves it. The portal is vendor-hosted (ePropertyPlus), but this tenant is the Land Bank's own published inventory, and the Land Bank's own site points buyers to it. Reusing it still needs that review.
- **Coordinates:** the portal's own points (`LAND_BANK_GIS`, POINT).

**Clerk & Master sale books (not built).** The numbered sale-book PDFs (`TX-2024TS2202SaleBook` and others) are **post-sale** books. Their contents:
- each parcel's high bid, or "NO BID BY COUNTY. PROPERTY NOT SOLD.";
- confirmation and redemption dates.

They are results of sales already held, not an upcoming-sale list. Bidding itself is on ZeusAuction (SRI), a vendor. An Auctions source for Shelby would need the upcoming list, which these pages do not publish, and the vendor's terms reviewed. These books could later feed verified auction outcomes, the same way `data/auction_outcome_wordings.csv` does for Florida.

**City of Memphis real estate** links to Memphis open-data hub apps. They were not followed.

## Davidson and Hamilton: what the live reads established (2026-10-09)

Two value-free evidence runs (`job=evidence`, `evidence_scope=tn_davidson_hamilton`, `scripts/capture_tn_counties.py`): 37864149419 and 37864266953. The second pass collected every link on each page, including links inside tables and links to other hosts, and followed the list-like files on official hosts.

**Davidson (Clerk & Master, `chanceryclerkandmaster.nashville.gov`).** The *Property Tax Schedule* and *Delinquent Tax Sale Information* pages publish the 2026–27 sale schedule as a set of dates, roughly monthly from May 2026 to January 2027. The only files they link are:
- the court's filing-fee schedule;
- an *Authorization to Bid* form (2018, scanned);
- an *Excess Proceeds* spreadsheet (September 2026), which covers funds left over from past sales.

**No per-sale parcel list is linked from either page**, on any host, inside or outside a table. Nothing is built: an Auctions source needs the parcel list itself.

**Hamilton (Real Property Office, `hamiltontn.gov`).**
- *Current Sale Information* is two individual commercial offerings (a 28-page marketing package and an RFP), not a list of county-held tax parcels.
- The tax-sale leftovers appear only as **Sold Lists**: 2022 to September 2025, each "PROPERTY SOLD LIST FOR <month year>" with a TYPE … SALE PRICE table. These are results, and the September 2025 file has no text layer.
- The Clerk & Master's *2026 Tax Sale* notice (3 pages, an auction with a redemption period) carries no parcel table.

**Nothing is built for either county.** Building Available or Auctions from these pages would mean an empty or invented inventory.

What these reads could support later:
- Hamilton's sold lists and Davidson's excess-proceeds file as **verified results**, once a parcel-level match and a publication review exist;
- a Davidson auction source, if the Clerk & Master posts the per-sale lists before a sale. The schedule says sales run roughly monthly.

**Next Tennessee candidates:** Montgomery (publishes the properties sold), Rutherford (searchable delinquent-tax database) and Knox (largest annual sale outside Memphis). Each needs the same value-free read first.

## Montgomery, Rutherford and Knox: what the live reads established (2026-10-09)

There were three value-free evidence runs (`job=evidence`, `evidence_scope=tn_montgomery_rutherford_knox`, `scripts/capture_tn_counties.py --set montgomery_rutherford_knox`): 37866090032, 37866176217 and 37866257521. From the second pass on they sent a browser User-Agent and followed tax-sale links first, including links on followed pages.

**Montgomery.** `montgomerytn.gov/chancery/tax-sale`, its `www.` form and `mcgtn.org/chancery` all answered **403** to the GitHub runners, even with a browser User-Agent. The site blocks this traffic, so nothing can be read or built from here. The survey's lead (a GovEase sale plus a published list of properties sold) is unverified.

**Rutherford.** The Clerk & Master's *Delinquent Tax Sales* page (`rcchancery.com/delinquent_sales`) carries only headings and the site's keyword search box (`keyword`, `SEC`). It links no parcel list on an official host. Its sale runs on GovEase, which this project deliberately never follows. **Nothing is built.**

**Knox.** The Trustee's *Tax Sale* page (`trustee.knoxcounty.org/services/tax-sale`) links four documents for **Tax Sale 25**:
- the *Final Results* (4 pages, about 200 lines carrying amounts, headed by docket number);
- the Clerk & Master's *Terms and Conditions* (minimum bid and redemption terms);
- a *Decree Confirming Sale* and a *Report of Sale*, both scanned with no text layer.

These are the results of a sale already held, not an upcoming list. No current list is linked. **Nothing is built.** The results file could later feed verified auction outcomes once a Knox auction inventory exists to match against.

**State of Tennessee after five counties:** Shelby's Land Bank is the only buildable inventory found. The other large counties publish either schedules and results (Davidson, Hamilton, Knox) or nothing reachable (Montgomery behind a 403, Rutherford through GovEase). The next useful step would be a different kind of source:
- a county-held property list, like Shelby's land bank;
- or a Clerk & Master who posts the parcel list ahead of the sale (Blount and Campbell, per the survey).

## Blount and Campbell: what the live reads established (2026-10-09)

There were four value-free evidence runs (`evidence_scope=tn_blount_campbell`, `scripts/capture_tn_counties.py --set blount_campbell`): 37866753934, 37866862723, 37866978780 and 37867087742. The probe now also resolves embedded ArcGIS apps down to their layers (field names and a record count only), and reads a WordPress media index (document URL, type and date only).

**Blount.** The *Delinquent Property Tax Sale*, *Tax Sale Procedures* and *Tax Sale FAQs* pages link no parcel list. The *2026 Delinquent Tax Procedures* file is a Word document, not a list.
- The survey's note that the list is posted about a month before the June sale and updated weekly is consistent with this: in October no list is up.
- The two ArcGIS apps embedded on those pages are the county's general GIS template, with no tax-sale layer. Their layers cover boundaries, commission and school districts, parcels, address points, centerlines and service areas.
- The **Blount Parcels** layer (`services3.arcgis.com/NIOS5f3vobGvnGtD/.../BlountParcels/FeatureServer/0`, 67,339 polygons, `PARID` / `PARCELID` / `GISLINK`, `CALC_ACRE`) is a candidate enrichment source for coordinates and acreage, should Blount inventory ever be built. It is not reviewed.
- **Nothing is built** until the 2027 list is posted. A read in spring 2027 would show its structure.

**Campbell.** The list the survey found (`.../uploads/2024/10/2023-DT-Tax-Sale-List-updated-04-14-26-@11.pdf`) now returns **404**.
- The county's own site search for "tax sale" returns only the Chancery Court, Trustee and County Clerk pages.
- The WordPress media index has no document matching "tax sale".
- The Chancery Court (Clerk & Master) page links only a court-costs schedule (updated 2026), and the Trustee page links only Comptroller guidance.
- **Nothing is built**: the list was taken down and is not linked anywhere on the site.

**Tennessee after seven counties:** the Shelby Land Bank remains the only buildable inventory. The rest are:
- seasonal lists that are not up now (Blount);
- lists that were withdrawn (Campbell);
- schedules and results only (Davidson, Hamilton, Knox);
- unreachable (Montgomery behind a 403, Rutherford through GovEase).
