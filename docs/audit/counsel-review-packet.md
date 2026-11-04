# Counsel review packet: four documents

**Prepared:** 2026-10-12. **Status:** draft for counsel; **not sent**.

**Purpose.** Ask counsel whether the operations TAXACQ performs today are permitted under each document, and if not, what would make them permitted.

**What this packet is not.** It is not a legal conclusion. It quotes only what the repository holds. Where it holds a summary rather than the document, it says so.

**Until an authorized reviewer records a decision**, every source below keeps its current restriction. In `data/source_permissions.csv` each is `LEGAL_REVIEW_REQUIRED` on an interim, expiring, grandfathered basis. That record is enforced by `harvesters/governance/permissions.py` (PR #145). Counsel's answer is recorded by changing that record together with `harvesters/governance/authorization.py`.

## How much of each document the repository actually holds

| Document | Copy in repository | Text available here |
|---|---|---|
| Alachua RealAuction EULA | No | A summary "supplied in the Phase 34A instructions", recorded in `authorization.py` (`fl_realauction__county__alachua`) |
| Volusia RealAuction EULA | No | The same kind of summary (`fl_realauction__county__volusia`), described as substantively identical to Alachua's |
| LienHub User Agreement | No | A summary (`fl_lienhub_certificates__provider__grant_street_group`). The recorded URL returned HTTP 403 on 2026-09-15. |
| Linebarger legal-disclosures | No | One sentence, quoted verbatim from a fetch recorded in `docs/lgbs-rights-audit.md` (2026-09-14) |

**Counsel should obtain and read the current official text of each document.** The summaries below exist to frame the questions, not to stand in for the documents.

---

## 1. RealAuction End User License Agreement: Alachua County

| | |
|---|---|
| **Document / URL** | Not recorded. `authorization.py` has `agreement_url = None`. The sale site is `alachua.realtaxdeed.com` (`data/county_source_registry.csv`, fl_realauction / Alachua). |
| **Version / date** | Unknown. `agreement_version` and `agreement_date` are not recorded. Last terms check: 2026-09-15. |
| **Parties, as summarized** | RealAuction.com, LLC; Alachua County Clerk of the Circuit Court (the county's sale process) |
| **Evidence on file** | `harvesters/governance/authorization.py` `_REALAUCTION_ALACHUA` (scope summary, notes, technical_restrictions); `data/phase36_terms_review.csv` (Alachua row); `docs/realauction-rights-audit.md`; `docs/provider-authorization-status.md` |

**Use restrictions needing interpretation.** These are quoted from the recorded summary, not the EULA:

- "the license is for accessing/using information for the purpose of purchasing or attempting to purchase property through Alachua County's sale process"
- "information presented by RealAuction cannot be used, altered, sold, or distributed without RealAuction's express written consent"
- "automated software/program/device access is prohibited without RealAuction's prior written approval"
- "robots/spiders/similar devices to monitor or copy pages/content/information are prohibited"
- "automated site processes and mouse-click automation are restricted"
- "certain registration/sales records may constitute public records under Florida law"
- "terms may be amended"

**What TAXACQ does today**, through `scripts/harvest_all_counties.ps1`, twice daily:

- an anonymous HTTP read of the county sale calendar and sale-day pages, with no account and no login;
- parsing case number, parcel, opening bid, sale date and status;
- storing them in the product database;
- showing them to approved subscribers with a link back to the county sale page;
- reading the closed / canceled results feed (`scripts/auction_outcomes.py`) and storing the published result wording and amount.

Bidder identity is never stored.

**Unresolved questions:**

1. Does a EULA that a bidder accepts bind an anonymous reader who never registers or accepts it?
2. Is the anonymous calendar and result data "information presented by RealAuction", or the Clerk's public record that RealAuction hosts? Which party can grant reuse?
3. Does the Florida public-records point ("certain registration/sales records may constitute public records") change the answer for sale date, case number, parcel and opening bid?
4. Is a scheduled script reading public pages "automated software/program/device access" within the EULA, absent registration?
5. Is redisplaying factual sale data to paying subscribers "use ... sold, or distributed" within the EULA?
6. May historical results be retained?
7. If written approval is needed, from RealAuction, the Clerk, or both?

**Could not be retrieved or verified:** the EULA text, its URL, its version, and whether it is shown to anonymous visitors. RealAuction hosts are not reachable from this sandbox.

## 2. RealAuction End User License Agreement: Volusia County

| | |
|---|---|
| **Document / URL** | Not recorded. The sale site is `volusia.realtaxdeed.com` (`county_source_registry.csv`). |
| **Version / date** | Unknown. Last terms check: 2026-09-15. |
| **Parties, as summarized** | RealAuction.com, LLC; Volusia County Clerk of the Circuit Court and Comptroller |
| **Evidence on file** | `authorization.py` `_REALAUCTION_VOLUSIA`; `data/phase36_terms_review.csv` (Volusia row) |

**Use restrictions needing interpretation.** The summary records "Same substantive terms as the Alachua County record". It lists use limited to the county's sale process; no use, alteration, sale or distribution without RealAuction's express written consent; automated access, robots and spiders prohibited without prior written approval; certain records may be public records; terms may be amended.

**What TAXACQ does today.** The same as Alachua.

**A separate Volusia matter, not this EULA.** The Volusia Lands Available PDF read passes a disclaimer step (pre-sale blocker item 4, `docs/legal/pre-sale-blockers.md`). It has its own county record in `data/source_permissions.csv` (`fl_laft_pdfs` / `FL:Volusia`).

**Unresolved questions:**

1. Questions 1–7 above, for Volusia.
2. Is the Volusia EULA in fact identical to Alachua's? The repository says only that both were described identically.
3. Does an answer for these two counties say anything about the other 44 RealAuction counties? `authorization.py` says it must not be read that way.

**Could not be retrieved or verified:** as for Alachua.

## 3. LienHub User Agreement (Grant Street Group)

| | |
|---|---|
| **Document / URL** | `https://lienhub.com/doc/terms`, the recorded `agreement_url`. It returned HTTP 403 when checked on 2026-09-15 (`data/phase36_terms_review.csv`). |
| **Version / date** | Unknown. Last terms check: 2026-09-15. |
| **Parties, as summarized** | Grant Street Group; participating Florida Tax Collectors |
| **Evidence on file** | `authorization.py` `_LIENHUB_GRANT_STREET`; `harvesters/governance/registry.py` `_FL_LIENHUB`; `docs/provider-authorization-status.md`; `docs/provider-authorization-requests.md`, which holds an unsent request template |

**Use restrictions needing interpretation.** Quoted from the recorded summary:

- "LienHub information is proprietary"
- "copying/saving/publishing/disseminating/distributing/disclosing/modifying/reselling/redistributing proprietary information is restricted except where expressly permitted"
- "robots/spiders/similar automated devices to monitor or copy pages/content/information are EXPRESSLY PROHIBITED"
- "software/devices interfering with the portal are prohibited"
- "a narrow exception permits copying transaction evidence for internal recordkeeping under specified conditions"
- "Grant Street may suspend/revoke privileges"

**What TAXACQ does today.** `scripts/harvest_lienhub_certificates.ps1` reads each county's county-held certificate list daily. It parses certificate number, parcel, face amount and legal description, stores them, and shows them to approved subscribers.

**Since 2026-10-01 every read returns HTTP 403**, for all 32 counties. No row has been re-read since. The permission record never authorizes working around a block.

**Unresolved questions:**

1. Is the county-held certificate list "proprietary information" of Grant Street, or the Tax Collector's public record that LienHub hosts?
2. Does the robots/spiders prohibition reach a scheduled read of a public listing page, without registration?
3. Does the 403 since 2026-10-01 express a decision to exclude this reader? Should collection stop formally, not just in practice?
4. If permission is possible, should it come from Grant Street, each Tax Collector, or both?
5. May already-stored certificate rows stay visible to subscribers while this is resolved?

**Could not be retrieved or verified:** the agreement text (403 on 2026-09-15; not reachable from this sandbox), its version, and whether it applies to non-registered visitors.

## 4. Linebarger Goggan Blair & Sampson: legal-disclosures clause

| | |
|---|---|
| **Document / URL** | `https://www.lgbs.com/legal-disclosures/`, recorded in `docs/lgbs-rights-audit.md` |
| **Version / date** | No version recorded. The quote comes from a fetch recorded in that audit, committed 2026-09-14. |
| **Evidence on file** | `docs/lgbs-rights-audit.md` (sections on the clause and its scope); `harvesters/governance/registry.py` `_TX_LGBS` |

**The clause, quoted verbatim as recorded:**

> "Reproduction, republication, retransmission, and/or distribution of material contained within this web site is prohibited unless the prior permission of Linebarger has been obtained."

**What TAXACQ does today.** The data comes from `taxsales.lgbs.com`, a different subdomain that has no terms of its own. The work runs only when a person dispatches the `texas` job, never on a schedule. LGBS is not being retried after the 2026-09-29 read.

- `harvesters/texas_harvester.py` reads the listing JSON API: account, cause number, minimum bid, sale date, status and listing URL.
- `scripts/lgbs_available_refresh.py` stamps last-seen and records fields for Texas Available rows.

Rows are labelled "vendor listing". The acquisition path is never attributed to lgbs.com.

**Unresolved questions** (the audit's own three legal-review items, restated):

1. Does a clause on `www.lgbs.com` cover the API data served from `taxsales.lgbs.com`?
2. Are sale listings that the taxing units must publish "material contained within this web site", or public notice the firm publishes as their counsel?
3. Is showing factual fields (sale date, account, minimum bid), with attribution and a link back, "republication" or "distribution"?
4. Who grants permission: Linebarger, the taxing units, or both?

**Could not be retrieved or verified:** the current page text, beyond the recorded sentence, and whether it has changed since 2026-09-14.

---

## Review checklist (one line per decision; counsel completes)

| # | Document | Question | Counsel's answer | Operations it decides | Date | Reviewer |
|---|---|---|---|---|---|---|
| 1 | Alachua EULA | Binds an anonymous, non-registered reader? | | fetch, parse | | |
| 2 | Alachua EULA | Calendar / result data: RealAuction's information or the Clerk's public record? | | store, display | | |
| 3 | Alachua EULA | Subscriber display = "sold or distributed"? | | display | | |
| 4 | Alachua EULA | Historical results retention permitted? | | store (closed_results) | | |
| 5 | Alachua EULA | Who may grant written approval? | | all | | |
| 6 | Volusia EULA | Same as 1–5; confirm the text matches Alachua's | | all | | |
| 7 | Both EULAs | Any bearing on the other 44 RealAuction counties? | | all (FL:*) | | |
| 8 | LienHub UA | Public listing = "proprietary information"? | | fetch, store, display | | |
| 9 | LienHub UA | Robots clause reaches a public, non-registered read? | | fetch | | |
| 10 | LienHub UA | Treat the 403 as exclusion and stop formally? | | fetch | | |
| 11 | LienHub UA | Keep already-stored rows visible meanwhile? | | display | | |
| 12 | Linebarger clause | Scope reaches taxsales.lgbs.com? | | fetch, store, display | | |
| 13 | Linebarger clause | Statutory notice vs. firm material? | | display | | |
| 14 | Linebarger clause | Factual fields with attribution = republication? | | display | | |

**After counsel answers,** engineering records each decision:

- in `data/source_permissions.csv` (status, evidence type, evidence reference, reviewer, dates);
- in `harvesters/governance/authorization.py` when a written permission is granted.

Then run `tests/python/test_source_permissions.py`. A `WRITTEN_PERMISSION` record without a matching granted authorization is refused by validation.
