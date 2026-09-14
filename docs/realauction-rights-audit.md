# Texas RealAuction / RealForeclose — Rights Audit

**Date reviewed:** 2026-09-14 (Phase 10B)
**Status of this document:** DOCUMENTATION ONLY. No legal determination is made here. No account was created, no terms were accepted, no technical control was bypassed, no payment was made, no auction was participated in. Every finding below is separated into KNOWN / UNKNOWN / LEGAL_REVIEW_REQUIRED / BLOCKED, per Phase 10B's explicit instruction not to infer permission from silence.
**Registry entry:** `tx_realauction` in `harvesters/governance/registry.py`. **Current production status is `APPROVED` and this document does NOT change that** — see [Recommended registry status](#21-recommended-registry-status), and `docs/commercial-data-inventory.md` for how this distinguishes from a formally rights-cleared source.

---

## 1. Source identity

RealAuction.com, LLC ("RealAuction") — a Plantation, FL-based online auction software vendor for municipal/county property, tax-lien, and tax-deed sales ("the largest online foreclosure software provider in the country" per its own site, operating since 2004). This project's `harvest_realauction()` targets 24 Texas county-hosted instances of RealAuction's platform, on two hostname patterns: `<county>.texas.sheriffsaleauctions.com` (most counties) and `<county>.texas.realforeclose.com` (Montgomery, Travis).

## 2. Official/public source locations reviewed

- `https://www.realauction.com/` — the vendor's own corporate site.
- `https://dallas.texas.sheriffsaleauctions.com/` and its calendar/auction-preview pages.
- `https://smith.texas.sheriffsaleauctions.com/` and its auction-preview page.
- `https://montgomery.texas.realforeclose.com/` (the alternate hostname pattern).
- Web search for `realauction.com` terms of service / privacy policy / acceptable-use language.

No account was created, no login was attempted, and no page requiring authentication was reached.

## 3. Access method

`harvest_realauction()` walks each county's public calendar page, then an AJAX endpoint (`index.cfm?zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD...`) that returns `AITEM_`-delimited property blocks — all unauthenticated, matching the pattern this same platform already uses for Florida's production harvesting (`harvest_all_counties.ps1`). This audit attempted to review the same public pages directly.

## 4. Technical accessibility — mixed finding, KNOWN in production practice but BLOCKED by this audit's own tooling

**Two different things are true at once here, and this document keeps them explicitly separate, per this project's standing rule:**

- **In actual production practice**: `harvest_realauction()` has successfully retrieved data from these exact hostnames via plain unauthenticated HTTP requests, confirmed live and end-to-end through a real GitHub Actions run (`workflow_dispatch` run #128, 2026-09-14, per `harvesters/texas_harvester.py`'s own module docstring) — no CAPTCHA, WAF, login, or rate-limit block was ever encountered by that harvester.
- **In this audit's own reconnaissance, this phase**: every single fetch attempted against every RealAuction-hosted hostname tested — `dallas.texas.sheriffsaleauctions.com` (root page, calendar page, and `robots.txt` itself), `smith.texas.sheriffsaleauctions.com` (auction-preview page and `robots.txt`), and `montgomery.texas.realforeclose.com` (root page) — was refused by this session's web-fetch tool with `ROBOTS_DISALLOWED`. This includes the refusal to even retrieve `robots.txt`'s own literal text, which means **this audit cannot quote the exact robots.txt content** — only that whatever it contains was restrictive enough that this tool's own robots-respecting fetch logic declined every path tried, consistently, across three different counties and both of the platform's two Texas hostname patterns.

**This is a genuinely new, previously-undocumented finding.** `harvesters/texas_harvester.py`'s own module docstring, and this project's Phase 10A registry notes, both already flagged RealAuction's `robots_status` as "Not formally reviewed" — this phase is the first actual attempt to review it, and the result is a consistent, platform-wide robots-disallow signal this project's production harvester has never checked for or respected (Python's `urllib.request`, which `harvest_realauction()` uses, does not consult `robots.txt` at all — it simply makes the HTTP request). That is: **production has been operating in a way that, if this session's tool's robots.txt read is representative of the real file, would not be considered robots.txt-compliant** — not because anyone decided to ignore it, but because nothing in this project's Texas RealAuction integration has ever checked it, at any point before this phase.

This is classified **LEGAL_REVIEW_REQUIRED** for the automated-access question specifically (Section 8), and is the single most significant new finding of this audit — escalated directly to the user in this phase's final response (see "SOURCE REGISTRY IMPACT"), not resolved here.

## 5. Terms reviewed — UNKNOWN

`www.realauction.com`'s own homepage was fetched and its footer contains only social-media links and two `mailto:` contact addresses (`sales@realauction.com`, `customerservice@realauction.com`) — **no Terms of Use, Terms of Service, Privacy Policy, or legal/disclaimer page was found linked from the vendor's own corporate site**, and this audit could not reach any individual county instance's own footer/legal links (Section 4's robots-blocked finding prevented it). A general web search for RealAuction terms/acceptable-use language returned no directly relevant, authoritative result — only unrelated third-party pages (BBB profile, LinkedIn, an unrelated county FAQ PDF that did not contain automation-specific language on inspection). **No Terms of Use text was reviewed for this vendor at all, on either the corporate site or any county instance** — a materially different (and more incomplete) position than LGBS's audit, which at least found and read real published text.

## 6. Robots reviewed — see Section 4

Every path tested, on every hostname tested, was refused by this session's own robots-respecting tooling. The literal file content could not be obtained through any tool available in this environment (bash-based fetching to work around a WebFetch refusal is explicitly against this project's own operating rules and was not attempted). Recorded as a strong restrictive-access *signal*, explicitly not converted into a legal/commercial conclusion, per this project's standing rule of keeping technical-access signals and rights conclusions separate.

## 7. Commercial-use findings — UNKNOWN

No Terms of Use was found or reviewed anywhere for this vendor (Section 5) — there is nothing to report a commercial-use finding FROM. This is an absence of evidence, not evidence of absence, and is not read as permission.

## 8. Automation findings — LEGAL_REVIEW_REQUIRED

The central finding of this audit (Section 4): a robots.txt-driven automated-access signal that this project's own production harvester has never checked, on a source currently registered `APPROVED`. No Terms of Use was reviewed to check for a parallel or conflicting statement.

## 9. Storage findings — UNKNOWN

Not addressed by anything reviewed (no Terms of Use was reached).

## 10. Redistribution findings — UNKNOWN

Same as above.

## 11. Customer-display findings — UNKNOWN

Same as above.

## 12. API/export findings — UNKNOWN / NOT APPLICABLE

RealAuction publishes no distinct JSON/REST API for this data the way LGBS does — the harvester parses an AJAX-delivered HTML-fragment response (`AITEM_`-delimited blocks), which is itself just a different transport for the same calendar/listing pages, not a separately documented API product. No API-specific terms exist to review.

## 13. Image/document findings — UNKNOWN

Not tested this phase (the property-listing pages were not successfully retrieved at all — Section 4). Florida's long-running use of this same platform has never reported images/documents being part of the harvested fields, and neither does this project's TX field inventory (`REALAUCTION_FIELD_LABELS` in `harvesters/texas_harvester.py` — address/cause/account/value/bid fields only, no image or document URLs) — so this is likely not applicable in practice, but this audit did not confirm that directly this phase and does not assert it as KNOWN.

## 14. Attribution findings — UNKNOWN

Not addressed by anything reviewed.

## 15. Rate-limit findings — UNKNOWN

No stated rate limit was found (no Terms of Use was reached to check). `harvest_realauction()` already applies its own 0.2-second courtesy delay between AJAX pages, a project precaution, not a documented source requirement.

## 16. Historical-retention findings — UNKNOWN

Not addressed by anything reviewed.

## 17. Account requirements — KNOWN (for participation) / UNKNOWN (for data retrieval)

RealAuction's platform is fundamentally a bidder-facing auction system — actually bidding requires a registered account and (per this platform's well-known general design, consistent with its Florida instances already in this project's production use) a deposit. This audit did not create an account and did not attempt to bid. Whether the specific act of *retrieving the public calendar/listing data* (as opposed to bidding) requires or implies acceptance of any account-holder terms is unresolved — the harvester itself has never authenticated, and nothing this audit found suggests the listing pages themselves are gated behind login (consistent with years of successful unauthenticated production harvesting for Florida on the same platform).

## 18. Auction participation terms — NOT APPLICABLE

This project does not bid or participate in auctions through this source — it only retrieves publicly listed pre-auction information. Auction-participation terms (deposit requirements, bidder registration rules, etc.) are out of scope for what this project actually does with this source.

## 19. Capability matrix

| # | Capability | Technically Accessible | Permission Known | Status |
|---|---|---|---|---|
| 1 | Human public viewing | Yes (in production practice; this audit's own tooling was refused by robots.txt — Section 4) | N/A | CLEAR |
| 2 | Automated retrieval | Yes in production practice; robots.txt signal (this audit) suggests otherwise | No — and a possible conflict between practice and signal | LEGAL_REVIEW_REQUIRED |
| 3 | Raw response storage | Yes (in practice) | No | LEGAL_REVIEW_REQUIRED |
| 4 | Normalized storage | Yes (in practice) | No | LEGAL_REVIEW_REQUIRED |
| 5 | Historical retention | Yes (in practice) | No | UNKNOWN |
| 6 | Transformation | Yes (in practice) | No | UNKNOWN |
| 7 | Combining with other sources | Yes (in practice) | No | UNKNOWN |
| 8 | Derived analytics | Yes (in practice) | No | UNKNOWN |
| 9 | Internal commercial use | Yes (in practice) | No | LEGAL_REVIEW_REQUIRED |
| 10 | Customer display | Yes (in practice, already happening in production) | No | LEGAL_REVIEW_REQUIRED |
| 11 | Customer export | Yes (technically, not yet built) | No | UNKNOWN |
| 12 | API redistribution | Yes (technically, not yet built) | No | UNKNOWN |
| 13 | Raw HTML redistribution | N/A — this project never stores/serves raw HTML from this source, only parsed fields | N/A | UNKNOWN |
| 14 | Images | Not confirmed either way this phase (Section 13) | No | UNKNOWN |
| 15 | Documents | Not confirmed either way this phase (Section 13) | No | UNKNOWN |
| 16 | Attribution | N/A | No requirement found (nothing reviewed) | UNKNOWN |
| 17 | Caching | Yes (in practice) | No | UNKNOWN |
| 18 | Rate-limited automated access | Yes — project applies its own 0.2s courtesy delay | No stated limit found (nothing reviewed) | UNKNOWN |

No row above was converted from UNKNOWN to CLEAR. Rows 2-4, 9, and 10 are marked LEGAL_REVIEW_REQUIRED rather than UNKNOWN specifically because Section 4's robots.txt signal is a concrete, if incomplete, piece of restrictive evidence — a meaningfully different (and more urgent) situation than a capability with genuinely no information available either way, which is marked UNKNOWN instead.

## 20. Legal-review items

1. What does the actual robots.txt content say on these hostnames, obtained through a means this project's own tooling permits (e.g., a human directly viewing `https://dallas.texas.sheriffsaleauctions.com/robots.txt` in a browser)? This audit could not determine the literal text.
2. If robots.txt does disallow automated access broadly, does that change this project's position on `tx_realauction`, given this exact platform is already used in Florida production for years without this question ever having been raised there either?
3. Does RealAuction (the vendor) or any individual Texas county publish a Terms of Use anywhere this audit's tooling limitations prevented it from finding? A human directly browsing one of these sites could check this in minutes; this audit could not.
4. Is there a meaningful legal distinction between "a public auction-listing calendar, which participation in requires an account" and "a public informational webpage" for purposes of automated retrieval rights — and does that distinction matter here given this project never participates in the auction itself?

## 21. Recommended registry status

**No change made to `tx_realauction`'s `legal_status` in this phase — it remains `APPROVED`.** As with LGBS, Phase 10B's hard rules forbid deactivating a production harvester based solely on this audit's own interpretation, and forbid this document from making a legal determination. Per Step 7's explicit instruction: **the current `APPROVED` status is a production-practice approval, not a formally rights-cleared one — approval basis requires legal review**, and this phase's own robots.txt finding (Section 4) is a stronger, more concrete reason for that statement than existed before this audit. `harvesters/governance/registry.py`'s `tx_realauction` entry has been updated (Phase 10B, this same commit) to state this explicitly, with `doc_refs` now citing this document, without changing `legal_status` or the ingestion gate's behavior. **This finding is escalated to the user directly in this phase's final response** for an explicit human decision — it is, in this auditor's own assessment, the single most actionable finding of this entire phase, precisely because it is concrete (a robots.txt signal, not just an absence of information) and because it touches an already-shipped, already-running production source.

## 22. Production impact

None from this document alone. `tx_realauction` continues to gate-pass as `APPROVED`; `harvest_realauction()` is unmodified; production behavior is unchanged. This audit's tooling limitation (Section 4/6 — unable to retrieve the literal robots.txt text) means the most important next step is not a code change but a five-minute human check: open `https://dallas.texas.sheriffsaleauctions.com/robots.txt` directly in a browser and read what it actually says.

## 23. Date reviewed

2026-09-14 (Phase 10B).
