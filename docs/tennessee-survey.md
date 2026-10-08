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

1. **Shelby** (in progress): Land Bank (Available) + C&M sale books (Auctions). This starts with a read-only structure capture (`job=evidence`, `evidence_scope=tn_shelby`, `scripts/capture_tn_shelby.py`).
2. **Davidson and Hamilton.**
3. **Montgomery, Rutherford, Knox.**

Every Tennessee source starts unreviewed: collected for admins and never customer-published until an admin review approves it.
