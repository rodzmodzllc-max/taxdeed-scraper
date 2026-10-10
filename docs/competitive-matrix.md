# Competitive matrix (2026-10-10)

The purpose is to steer implementation, not to make marketing claims. Nothing here says TAXACQ is "better" than any product. It records what each product's own pages state, what TAXACQ's code and production snapshot actually show, and what still needs a hands-on trial.

## How the competitor column was gathered, and its limit

- **No vendor page was read live.** From this environment every vendor domain failed to resolve or was refused by the egress proxy (lienscoutpro.com, liensuite.com, marketplacepro.net, bid4assets.com and others).
- **The competitor column therefore comes from web-search index results restricted to each vendor's own domain.** These are a search model's summaries of indexed pages, and some are old (for example LienScout pricing about 633 days old; United Tax Liens pages 1,700 or more days old).
- **"Indexed" means:** the vendor's own domain says so, per the search index. It must be confirmed on the live page before anyone repeats it.
- **"Claimed" means:** a marketing assertion that cannot be checked, such as coverage totals or "AI" accuracy.
- **"Unknown" means:** nothing was found. That is not proof the feature is absent.
- **No cell is "Confirmed".** Re-run this from a browser that can reach the pages, or during a trial.
- **"Florida Tax Certs" could not be found** under that name, so it is not listed.

## Matrix

**Products (columns):**
- **LSP:** LienScout Pro
- **LS:** LienSuite
- **MPP:** Marketplace Pro (United Tax Liens)
- **BL:** Bidlytics
- **Venues:** RealAuction, GovEase, Bid4Assets, LienHub, Zeus / SRI. These are sale platforms for their own sales, not cross-venue research tools.

| # | Dimension | LSP | LS | MPP | BL | Venues | TAXACQ (measured in this repo / production snapshot) |
|---|---|---|---|---|---|---|---|
| 1 | Coverage / source diversity | Claimed (25 counties, 5 states) | Claimed (counts inconsistent across its own pages: 317 to 1,017 counties) | Claimed (3M+ properties) | Unknown | Indexed (own sales only) | 14 states registered. Coverage is per source, in `data/county_source_registry.csv` and `public/source-inventory.json`. A sample of county volumes is measured in `docs/record-quality-benchmark-results.md`. |
| 2 | Freshness / reliability | Unknown | Claimed ("the moment it's posted") | Unknown | Unknown | LienHub indexed (9 am posting) | Every record shows its last read. Harvest health is tracked per county: COMPLETE / EMPTY / INCOMPLETE / FAILED / SOURCE_UNAVAILABLE (`scripts/laft_status.py`, `unit_freshness.py`). A failed read never closes records. |
| 3 | Auction lifecycle + sale results | Indexed (calendar) | Indexed (calendar) | Indexed (calendar) | Unknown | Indexed (bidding; winnings for the bidder) | Auction calendar. Results are shown only where the venue published them (`data/auction_outcome_wordings.csv`). A listing that leaves a feed is never called sold. |
| 4 | Post-sale / OTC availability + acquisition path | Unknown | Unknown | Claimed (OTC, in a competitor's review only) | Unknown | LienHub indexed (county-held certificate purchase) | A separate Available ledger, sourced only from lists that themselves state availability. Each record shows a verified, county-level acquisition record (steps, forms, contact), or "Not yet verified". |
| 5 | Lien / certificate research | Indexed (redemption watcher) | Claimed (lien signals) | Indexed | Unknown | Indexed (on each venue) | A separate Liens & Certificates ledger with certificate identity, published rate and dates. It states that a certificate does not transfer the property (added this sprint). |
| 6 | Parcel intelligence | Claimed (scores) | Indexed (skip trace, heirs) | Indexed (photos, zoning) | Claimed (AI title / repair risk) | Unknown | Tax-roll and parcel-layer matches by exact identifier only. FEMA flood zone. Land use and values, each with recorded provenance. No score and no estimate. |
| 7 | Maps / imagery | Unknown | Indexed (map, Street View) | Unknown | Unknown | Unknown | County map plus parcel pins, Google and MapTiler basemaps, and USDA NAIP aerial imagery, with the imagery's basis stated. |
| 8 | Source transparency / provenance | Unknown | Unknown | Unknown | Unknown | Unknown | Per-field provenance, a source-truth section, publication review status, and (this sprint) "What this record is based on" for every ledger. |
| 9 | Due-diligence workflow | Indexed (checklists) | Indexed (deal CRM) | Unknown | Claimed | Venue rules PDFs | A due-diligence checklist with evidence states, an acquisition checklist and a county dossier. |
| 10 | Saved research + monitoring | Indexed (30/7/1-day reminders) | Indexed (auction tracker emails) | Unknown | Indexed (market alerts) | Bid4Assets: weekly email (indexed) | Watchlist, saved searches and research lists. Alert generation and storage need migration 024; **email delivery of alerts does not exist yet**. |
| 11 | Historical observations / outcomes | Indexed (portfolio) | Unknown | Indexed (asset tab) | Unknown | Own portfolio (indexed) | Lifecycle history per record (first seen, status changes, removed ≠ sold) and a cross-ledger parcel timeline. |
| 12 | Price / ease of use | Indexed: $49–$199/mo, 14-day trial | Indexed: $79/mo; single county $27–$39 | Not published | Indexed: $39.90–$79.90/mo | Bid4Assets: free registration (indexed) | Billing is built but switched off (`config.js billing.enabled: false`). No public price. |

## What TAXACQ can credibly claim, and what it cannot

**Can claim (code and tests show it):**
- **Three separate ledgers with independent lifecycles.** A certificate is never a property sale, and a listing that leaves a feed is never a sale.
- **Per-record origin of every key fact.** Published, matched from a public dataset, derived by a rule, stale, not published, or origin not recorded.
- **Explicit "not published" / "not yet verified" states** in place of scores, estimates or inferred results.
- **Acquisition paths backed by quoted county evidence**, where verified.

No indexed competitor page shows per-field provenance, but **that is unknown, not proven absent**. Stating it as a differentiator needs a hands-on trial of each product.

**Cannot claim yet:**
- Broader coverage than any named competitor.
- Faster refresh than any named competitor.
- Customer preference or willingness to pay. No tester sessions have been run (see `docs/customer-testing-script.md`).

## Highest-value gaps this matrix points to

1. **Monitoring delivery.** Competitors advertise sale-date reminders and email alerts. TAXACQ stores saved searches, but alert delivery depends on migration 024 (unapplied) and a sender that does not exist yet.
2. **Coverage depth in the focus counties** (see the benchmark). Several counties carry identity and source links but no verified acquisition path or authoritative coordinates.
3. **Hands-on trials of LienScout Pro, LienSuite and Bidlytics,** to move the matrix from "Indexed" to "Confirmed".
