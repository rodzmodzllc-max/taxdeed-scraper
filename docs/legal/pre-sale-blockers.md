# Pre-sale blockers

Prepared 2026-09-26. Evidence and background for each item are in
[`pre-sale-counsel-review.md`](pre-sale-counsel-review.md).

This list gives **no score and no percentage-ready figure**. An item leaves
the list only when the named owner resolves it.

Owner key:

- **Counsel**: a licensed attorney.
- **Owner**: the business owner.
- **Eng**: engineering.
- **Vendor**: the source or vendor's written permission.

## Must resolve before accepting money

| # | Item | Owner |
|---|---|---|
| 1 | Legal opinion on selling data collected from RealAuction sites, given the recorded automated-access and redistribution restrictions. Obtain written permission if counsel requires it. | Counsel, Vendor |
| 2 | Same for LienHub (robots/spiders prohibited, redistribution restricted). | Counsel, Vendor |
| 3 | LGBS: does its legal-disclosures clause cover the `taxsales` API, and does it allow commercial display? | Counsel, Vendor |
| 4 | Decision on the Orange disclaimer click-through, the Volusia disclaimer bypass, the Osceola private API and ScraperAPI IP-block avoidance: keep, change or discontinue. | Counsel, then Owner |
| 5 | Terms of Service, Privacy Policy and Acceptable Use for paying customers, drafted or approved by counsel. | Counsel |
| 6 | Decision on displaying, searching and exporting owner names of record, and on LienHub owner mailing addresses stored as `address`. | Counsel, then Eng |
| 7 | Replace the Google Maps **Demo Key**, which Google describes as testing-only, with a production key under a paid-use-appropriate plan, or remove the Google basemap. | Owner, Eng |
| 8 | Confirm the MapTiler plan, the OSM tile policy and NAIP storage/attribution for commercial use. | Counsel, Owner |
| 9 | Homestead fee estimate: an accountant or attorney confirms or corrects it. Until then, consider hiding the homestead part of the estimate. It is currently disclosed as unconfirmed. | Counsel or accountant, then Eng |
| 10 | A payment flow does not exist. Build it only after items 1–6 are answered. | Eng |

## Must resolve before public launch

| # | Item | Owner |
|---|---|---|
| 11 | Public-repository exposure: GitHub Actions artifacts with owner, applicant, sold-to and winning-bid fields (30 days), database backups with owner names and notes (90 days), and applicant names in `data/laft_pioneer_counties.csv`. Decide on making the repo private, stripping or shortening artifacts, and whether a history rewrite is warranted. | Counsel, Owner, Eng |
| 12 | Account deletion and data-export flow for customers. | Eng |
| 13 | Email digest: a real unsubscribe, sender identification and a postal address before it is ever deployed. It is not deployed today. | Counsel, Eng |
| 14 | Counsel-approved disclaimer text to replace the engineering-written disclaimers in the Terms modal, footer and digest. | Counsel |
| 15 | Texas redemption summary (Tex. Tax Code §34.21) confirmed or removed. | Counsel |
| 16 | Trade-name clearance for "Tax Acquisitions". | Counsel |
| 17 | A record of sub-processors (Supabase, Cloudflare, GitHub, Google, MapTiler, the email provider). | Owner, Counsel |
| 18 | Terms recorded for sources marked "Not yet verified live": Bid4Assets, the 8 non-PDF LAFT platforms, the Santa Rosa / Palm Coast GIS, Census, FEMA and FDOR. | Eng, then Counsel |

## Post-launch improvements

| # | Item | Owner |
|---|---|---|
| 19 | Capture of auction outcomes and history (PR #33 and later). **Not to be merged or activated without a separate decision.** Outcomes must never be inferred from a listing disappearing. | Owner, Eng |
| 20 | Texas valuation beyond the vendor figure (0 of 531 today). The appraisal-district enrichment is not started. | Eng, after a rights check |
| 21 | Texas coverage of legal description, coordinates and `tx_sale_status`. | Eng |
| 22 | Raise FL certificate enrichment (FDOR 40.67%, coordinates 51.47%, legal description 31.85%). | Eng |
| 23 | Record the imagery capture year (`photo_captured_year` is 0% populated today), so the age of each image can be shown. | Eng |
| 24 | Replace the "Filter match" 12× threshold with a user-set threshold, or drop it. | Owner, Eng |
