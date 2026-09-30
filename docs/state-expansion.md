# State expansion: live source evidence and activation blockers (2026-09-30)

Starting point: main `6feae53`. Production-active states: **FL, TX** (2).
Active production rows at the start: 3,386
(FL auction 1,077 · FL certificate 1,611 · FL laft 155 · TX auction 122 · TX laft 421).

Everything below was read LIVE from GitHub Actions by the manual evidence
job (`job=evidence`, `evidence_scope=state_sources`,
`scripts/capture_state_sources.py`) in runs 36752875012 and 36753767965.
Only structure is captured: titles, headings, table headers and body-row
counts, form field names, and licence / terms text. For CSVs the capture
keeps the header plus value *shapes*, with every digit and letter masked.
No row value is printed, and nothing is written to any database.

## 1. Inventory (A–G)

| State | Source | Class | Exact blocker |
|---|---|---|---|
| FL | 47 RealAuction deed + 32 LienHub certificate + 51 LAFT sources | **A** production, active | - |
| TX | 24 RealAuction + 8 struck-off sources | **A** production, active | - |
| TX | 14 LGBS / vendor sources | **E** blocked | blocked vendor policy (not touched) |
| AL | ADOR state-held tax land (`al_ador_state_land`) | **C** partial + **F** | Source moved: `/property-tax/delinquent-search/` answers **404**. The process page (200) says "Below is a listing by county of tax delinquent properties currently in State inventory. The transcripts are updated weekly", and a price comes only through an electronic application. The new listing location was not in the captured links. ADOR's pages publish no terms of use or reuse licence (Legal Division and Open Records pages only). |
| AR | COSL Post Auction Sales List (`ar_cosl_post_auction`) | **C** partial + **F** | `PostAuctionView` and `?county=DALLAS` return 200 but carry **no table** ("Post Auction Sales Lists / DALLAS County" headings only). The page says purchases moved to the online auction at `auction.cosl.org` ("View and bid on parcels that are available for post-auction sale"). That makes the inventory an online auction, not the fixed-price list the adapter models. The adapter's source must be re-established there. Terms (`/Home/Policies`) are a warranty disclaimer only, with no reuse grant. |
| LA | East Baton Rouge adjudicated property (`la_ebr_adjudicated`) | **B/C** implemented, **stale** | Licence is explicitly **Public Domain** (Socrata `licenseId=PUBLIC_DOMAIN`, provenance official, attribution EBR Assessor's Office). The CSV is live (13,948+ rows in the first 3 MB, 16 columns exactly as the adapter expects, PROPERTY NUMBER shape `999-9999-9`). **But `rowsUpdatedAt` is 2024-02-27** (Last-Modified the same), despite "Update Frequency: Annually". It carries 6 tax years, with 5,694 distinct property numbers in the first 3 MB. A list untouched for 2.5 years cannot establish that a parcel is available *now*, so publishing it as current AVAILABLE inventory would misstate availability. |
| AZ | Maricopa State CP listing (`az_maricopa_state_cp`) | **C** partial + **F** | `soa.treasurer.maricopa.gov` **and** `ftp.treasurer.maricopa.gov` do not resolve (DNS), so the CSV is unreachable. The Treasurer pages are a client-rendered app with no server content. The county's Site Terms are a disclaimer / hold-harmless with no reuse grant. |
| MN | Wright County "Tax Forfeited Parcels" ArcGIS layer | **G** + **F** | Technically workable: 80 features, last edit 2026-09-02. Fields: PID, legal, municipality, forfeiture year, EMV, **Auction Starting Price**, Purchasing Information, **Status**, Public Surplus page. No `licenseInfo` on the item; terms not reviewed. Sales run through Public Surplus (a vendor). |
| MN | Hubbard County "TFL Sales" layer | **G** + **F** | 16 features, last edit 2026-04-10, fields Parcel_Number / Sales_Status / Minimum_Bid. No licence on the item. |
| MN | Hennepin, St. Louis, Carlton, Itasca county pages | **G** + **F** | Pages read. Hennepin: "Properties for sale are listed on our tax-forfeited land inventory site"; the minimum bid is the sum of taxes, assessments, penalties, interest and costs. St. Louis publishes over-the-counter "Available" lists as documents. Carlton points to `mnbid.mn.gov`. No reuse licence found on any of them. |

## 2. Why nothing was activated

Every candidate fails `governance_approved` (terms reviewed; registry
`governance_status` APPROVED), and so its publication status stays
UNREVIEWED. The one explicit reuse grant found is LA's Public Domain
licence, and that dataset is 2.5 years stale.

This project's rules say a government website is not commercial
permission. `publication.publication_problems()` refuses APPROVED on
anything that is not governance-approved and PRODUCTION_VERIFIED.
Setting `governance_approved` without a reviewed decision would bypass
exactly that gate, so no state was activated, no registry row was
promoted, and migration 020 was not applied.

## 3. What each state needs, precisely

- **LA / EBR**: the owner decides whether a Public Domain list *as of
  2024-02-27* may be shown, labelled with its list date, as "adjudicated
  inventory as of 2024-02-27". It must never be shown as "available now".
  If yes, the implementation needs:
  - migration 020 (ADJUDICATED_PROPERTY is not storable today);
  - one row per property number (the latest tax year);
  - the list date as `list_as_of`;
  - an `la.html` page with its basemap.
- **AR**: read `auction.cosl.org`'s listing structure and terms (next
  evidence run). The adapter's inventory type becomes an auction
  (Auctions ledger), not POST_SALE fixed price.
- **AL**: locate the per-county transcript links on the Land Sales page
  (next evidence run with `--follow`), then a terms decision.
- **AZ**: the CSV hosts need to resolve (or a replacement URL from the
  Treasurer), then a terms decision. The Liens & Certificates ledger only.
- **MN**: a terms / publication decision per county layer. Wright and
  Hubbard are ready to implement through the existing generic ArcGIS
  adapter (`harvesters/otc/adapters/arcgis.py`). Minnesota tax-forfeited
  land sold over the counter at a listed price is the same concept as
  Florida's Lands Available list.
