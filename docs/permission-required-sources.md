# Permission-Required Sources

Phase 38 Sections 20, 21, 40 and 45. Every source that is useful but not usable
without someone's written permission, and the strongest official alternative
found for each.

Nothing here is approved. `requested_at` is `null` and `status` is
`NOT_REQUESTED` everywhere, because **no provider has actually been contacted**.
Claiming otherwise would be the failure this document exists to prevent.

## Vendor / provider requests

### RealAuction / RealForeclose — Florida tax deed auctions
- **Counties:** 46 FL counties (`data/realauction_counties.csv`)
- **Fields wanted:** auction date, opening/minimum bid, case number, sale status, property identifier
- **Operations wanted:** store, normalize, display, customer display, export, API
- **Permission needed:** written authorization for automated retrieval and redistribution
- **Status:** `LEGAL_REVIEW_REQUIRED` (existing — see `docs/realauction-rights-audit.md`)
- **Alternative found:** County Clerk of Court / Value Adjustment Board, now
  identified for 64 of 67 counties (`data/fl_official_directory.csv`)
- **Alternative covers:** case number, sale date, sale status, recorded instruments
- **Alternative missing:** opening/minimum bid — no official alternative identified
- **requested_at:** null · **status:** NOT_REQUESTED

### LienHub / TaxCertSale — Florida tax certificates
- **Counties:** 32+ FL counties (`data/florida_certificate_sale_platforms.csv`)
- **Status:** APPROVED (grandfathered, never formally rights-audited) — a standing
  gap, not a clearance
- **Alternative found:** County Tax Collector, now identified for all 67 counties
- **Alternative covers:** annual tax, delinquent tax, tax certificate, payment status
- **requested_at:** null · **status:** NOT_REQUESTED

### Linebarger Goggan Blair & Sampson (`tx_lgbs`)
- **Counties:** TX, as observed (`data/tx_lgbs_observed_county_roster.csv`)
- **Status:** unchanged this phase. Technical acquisition success is **not**
  commercial authorization; `technical_status`, `verification_status`,
  `authorization_status` and `production_status` remain separate.
- **Alternative found:** County Tax Assessor-Collector (250/254) and County
  Appraisal District (246/254)
- **requested_at:** null · **status:** NOT_REQUESTED

### `tx_pbfcm`, `tx_govease`, `tx_mvba`, `tx_ctsa`
- **Status: unchanged.** Phase 38 Section 18 is explicit that these must not be
  silently revived, and this phase did not revive, re-evaluate or re-enable any
  of them. Their existing registry status stands.
- **requested_at:** null · **status:** NOT_REQUESTED

## County offices — 696 rows pending review

Every county Property Appraiser, Tax Collector, Clerk/VAB, Appraisal District
and Tax Assessor-Collector identified this phase is `LEGAL_REVIEW_REQUIRED`
because **its terms have not been reviewed** — not fetched, not read, not
assessed. Every rights column for these rows is `UNREVIEWED`. This is not a claim that any of them
prohibits use — it is the absence of a review. Section 31: permission is not
inferred from silence.

See `data/source_rights_matrix.csv` for the full list.

## Not yet evaluated

No licensed commercial provider (Section 40) was evaluated this phase, and no
vendor was contacted (Section 41). The contact list below is therefore empty by
design rather than by omission:

| provider | contact | requested_permission | status |
|---|---|---|---|
| *(none)* | — | — | NO_CONTACT_MADE |
