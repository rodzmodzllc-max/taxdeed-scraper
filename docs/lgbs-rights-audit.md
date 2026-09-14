# LGBS (Linebarger Goggan Blair & Sampson) — Rights Audit

**Date reviewed:** 2026-09-14 (Phase 10B)
**Status of this document:** DOCUMENTATION ONLY. No legal determination is made here. No account was created, no terms were accepted, no technical control was bypassed, no payment was made. Every finding below is separated into KNOWN / UNKNOWN / LEGAL_REVIEW_REQUIRED / BLOCKED, per Phase 10B's explicit instruction not to infer permission from silence.
**Registry entry:** `tx_lgbs` in `harvesters/governance/registry.py`. **Current production status is `APPROVED` and this document does NOT change that** — see [Recommended registry status](#21-recommended-registry-status) for why, and `docs/commercial-data-inventory.md` for how this distinguishes from a formally rights-cleared source.

---

## 1. Source identity

Linebarger Goggan Blair & Sampson, LLP ("Linebarger" / "LGBS") — a Texas-based law firm (principal office: Terrace 2, 2700 Via Fortuna Dr., Suite 500, Austin, TX 78746) that serves as delinquent-tax collection counsel for numerous Texas taxing jurisdictions (and, per its own site, Philadelphia County, PA as well). The harvested source is `taxsales.lgbs.com`, a subdomain distinct from the firm's main marketing site `www.lgbs.com` — this distinction matters throughout this audit (see Section 6).

## 2. Official/public source locations reviewed

- `https://taxsales.lgbs.com/` — the tax-sale listing application itself (a JavaScript-rendered single-page app; its server-delivered HTML carries only a page title, "Tax Sale Properties | Linebarger Goggan Blair & Sampson, LLP," with the actual listing content loaded client-side).
- `https://taxsales.lgbs.com/api/property_sales/` — the JSON API `harvest_lgbs()` actually calls (confirmed live: `GET .../api/property_sales/?area=TX&limit=5` returns a standard DRF-paginated JSON body with `count`/`next`/`previous`/`results` keys and no embedded terms/license/disclaimer text of any kind).
- `https://taxsales.lgbs.com/robots.txt`
- `https://www.lgbs.com/` — the firm's main site (same legal entity, different subdomain).
- `https://www.lgbs.com/privacy-policy/`
- `https://www.lgbs.com/legal-disclosures/`
- `https://www.lgbs.com/disclosures-2/` (a second, consumer-debt-collection-focused disclosures page also linked from search results — reviewed for completeness, found not relevant to this audit's questions; see Section 7).

No account was created, no login was attempted, and no page requiring authentication was reached at any point.

## 3. Access method

`harvest_lgbs()` calls the JSON API directly (`https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=500`, walking `next` links) — it does not render the SPA or execute any JavaScript. This audit reviewed the same API endpoint directly, plus the surrounding site's published legal pages.

## 4. Technical accessibility — KNOWN

The API is unauthenticated and returns data immediately with no login, CAPTCHA, or paywall (matches `harvesters/texas_harvester.py`'s own module docstring, and was independently re-confirmed this phase with a fresh, low-volume request). `taxsales.lgbs.com/robots.txt` was fetched and its entire content is:

```
User-agent: *
```

No `Disallow` line of any kind — the most permissive robots.txt posture found anywhere in this project's Texas reconnaissance to date (contrast with `tx_govease`'s blanket `Disallow: /`, and Harris County's mixed/ambiguous signal). This is a genuine, positive technical-access signal, though — consistent with this project's standing rule — it is recorded as exactly that (a crawling-convention signal) and not converted into a legal/commercial conclusion.

## 5. Terms reviewed — KNOWN, with a material scope ambiguity (LEGAL_REVIEW_REQUIRED)

**No Terms of Use page was found anywhere on `taxsales.lgbs.com` itself** — it is a bare SPA shell with no footer content in its server-rendered HTML, and a site-restricted web search (`site:taxsales.lgbs.com`) returned no indexed terms/disclosures/privacy page for that subdomain specifically.

**`www.lgbs.com/legal-disclosures/` (the firm's main site, a different subdomain) DOES contain an affirmative reproduction/redistribution prohibition**, quoted verbatim from this phase's own fetch:

> "Reproduction, republication, retransmission, and/or distribution of material contained within this web site is prohibited unless the prior permission of Linebarger has been obtained."

This is materially similar in substance to PBFCM's own `disclosure.html` clause (already the basis for PBFCM's `BLOCKED` classification in Phase 8) and to MVBA's equivalent finding. **The open question this audit cannot resolve on its own: does "this web site" in that clause refer to `www.lgbs.com` specifically, or to the firm's entire web presence including the `taxsales.lgbs.com` subdomain the harvester actually uses?** Arguments exist both ways and this document does not pick one:

- *For it applying firm-wide*: both subdomains belong to the same legal entity and brand; a firm's general legal-disclosures page is often intended to cover everything it publishes under its name, and `taxsales.lgbs.com`'s own bare SPA shell has no terms of its own to conflict with or supersede it.
- *Against it applying to the subdomain used*: `taxsales.lgbs.com` is a functionally and technically distinct product (a data API, not marketing content) with its own permissive robots.txt, no linked reference back to `www.lgbs.com`'s disclosures page anywhere in its own pages, and no clickwrap or banner of any kind before the API returns data.

**This is classified LEGAL_REVIEW_REQUIRED**, not BLOCKED and not APPROVED — the clause is real and its plain language is a genuine prohibition, but its scope as applied to the specific subdomain/API this project actually uses is genuinely unresolved by anything published. Per Phase 10B Step 7's explicit instruction, this finding is surfaced for human decision rather than used to silently reclassify `tx_lgbs`'s production status (see Section 21).

`www.lgbs.com/privacy-policy/` was also reviewed: it addresses personal-information handling only ("Anonymous Information" "may be used for any purpose"; "We will not sell, rent, transfer or otherwise disclose your Personal Information to third parties...") and says nothing about automated access, commercial reuse of published tax-sale data, or redistribution — **not relevant to this audit's questions** (this project does not collect or process personal information about individuals from this source; the harvested data is property/tax-sale information).

## 6. Robots reviewed — KNOWN

Covered fully in Section 4. `User-agent: *` with no `Disallow` line — an open posture, the most permissive found for any Texas source reconnoitered to date.

## 7. Commercial-use findings

- **KNOWN**: no commercial-use language of any kind exists on `taxsales.lgbs.com` itself (bare SPA shell, no terms page).
- **LEGAL_REVIEW_REQUIRED**: whether `www.lgbs.com/legal-disclosures/`'s reproduction/redistribution prohibition extends to commercial use of `taxsales.lgbs.com`'s API data — see Section 5.
- **UNKNOWN**: whether Linebarger, as delinquent-tax collection counsel (not the taxing jurisdiction itself), has any contractual restriction from ITS OWN clients (the counties/districts it represents) on redistributing the sale-listing data it publishes — no such document is public, and this project has no visibility into Linebarger's own client contracts.

## 8. Automation findings

- **KNOWN**: robots.txt does not disallow automated access (Section 4/6).
- **UNKNOWN**: no Terms of Use anywhere (on either subdomain) explicitly addresses automated retrieval, bots, or crawlers by name, one way or the other.
- **UNKNOWN**: no stated rate limit, request-volume guidance, or acceptable-use policy for the API was found.

## 9. Storage findings — LEGAL_REVIEW_REQUIRED

Not separately addressed anywhere; falls under the same scope-ambiguity as Section 5's redistribution clause, since storing a copy is a predicate to any redistribution question. No storage-specific language (retention limits, caching restrictions) was found on either subdomain.

## 10. Redistribution findings — LEGAL_REVIEW_REQUIRED (see Section 5)

The central open finding of this audit. Not resolved here.

## 11. Customer-display findings — LEGAL_REVIEW_REQUIRED

Not separately addressed by any published text; would be governed by however Section 5's scope question resolves, since displaying normalized data to paying customers is a form of the same redistribution question.

## 12. API/export findings

- **KNOWN**: the API itself (`/api/property_sales/`) carries no embedded terms, license, or usage-restriction text of any kind (Section 2's direct check of the JSON response).
- **LEGAL_REVIEW_REQUIRED**: whether operating a derivative product on top of this API (as opposed to a human occasionally viewing `taxsales.lgbs.com` in a browser) is within the scope of what Linebarger intends by publishing it — no statement either way was found.

## 13. Image/document findings — UNKNOWN / NOT APPLICABLE

No images or documents are published through the `/api/property_sales/` endpoint (confirmed by this project's own existing harvester code and by this phase's direct inspection of the JSON structure) — there is nothing to evaluate rights for.

## 14. Attribution findings — UNKNOWN

No attribution requirement, source-citation requirement, or trademark-notice requirement was found anywhere on either subdomain.

## 15. Rate-limit findings — UNKNOWN

No stated rate limit was found. `harvest_lgbs()` already applies a 0.3-second courtesy delay between paginated requests (see `harvesters/texas_harvester.py`), which is this project's own precaution, not a documented source requirement.

## 16. Historical-retention findings — UNKNOWN

No language addressing whether historical snapshots of sale-listing data may be retained was found on either subdomain.

## 17. Capability matrix

See Section 6 of `docs/realauction-rights-audit.md` — the combined matrix for both sources lives there per Phase 10B Step 6's single-matrix format; this document's own copy is reproduced below for LGBS specifically.

| # | Capability | Technically Accessible | Permission Known | Status |
|---|---|---|---|---|
| 1 | Human public viewing | Yes | N/A | CLEAR |
| 2 | Automated retrieval | Yes (robots.txt open; no CAPTCHA/auth) | No affirmative statement either way | LEGAL_REVIEW_REQUIRED |
| 3 | Raw response storage | Yes | No | LEGAL_REVIEW_REQUIRED |
| 4 | Normalized storage | Yes | No | LEGAL_REVIEW_REQUIRED |
| 5 | Historical retention | Yes | No | LEGAL_REVIEW_REQUIRED |
| 6 | Transformation | Yes | No | LEGAL_REVIEW_REQUIRED |
| 7 | Combining with other sources | Yes | No | LEGAL_REVIEW_REQUIRED |
| 8 | Derived analytics | Yes | No | LEGAL_REVIEW_REQUIRED |
| 9 | Internal commercial use | Yes (technically) | No | LEGAL_REVIEW_REQUIRED |
| 10 | Customer display | Yes (technically) | No — the `legal-disclosures` scope question directly bears here | LEGAL_REVIEW_REQUIRED |
| 11 | Customer export | Yes (technically) | No | LEGAL_REVIEW_REQUIRED |
| 12 | API redistribution | Yes (technically) | No | LEGAL_REVIEW_REQUIRED |
| 13 | Raw HTML redistribution | N/A — no meaningful HTML is served (bare SPA shell; the data is JSON) | N/A | UNKNOWN |
| 14 | Images | N/A — not published by this source | N/A | UNKNOWN |
| 15 | Documents | N/A — not published by this source | N/A | UNKNOWN |
| 16 | Attribution | N/A | No requirement found | UNKNOWN |
| 17 | Caching | Yes | No | LEGAL_REVIEW_REQUIRED |
| 18 | Rate-limited automated access | Yes | No stated limit; project applies its own courtesy delay | UNKNOWN |

No row above was converted from UNKNOWN to CLEAR. Every capability touching storage/display/export/redistribution is LEGAL_REVIEW_REQUIRED specifically because of the unresolved `www.lgbs.com/legal-disclosures/` scope question (Section 5) — not because evidence is silent (evidence exists; its applicability to the subdomain in use is what's unresolved), which is a meaningfully different and more urgent finding than a source with no relevant language at all.

## 18. Known facts

- `taxsales.lgbs.com`'s `robots.txt` is fully open (`User-agent: *`, no disallow).
- `taxsales.lgbs.com`'s API returns no embedded terms/license text.
- `taxsales.lgbs.com` itself has no findable Terms of Use page.
- `www.lgbs.com/legal-disclosures/` (a different subdomain, same legal entity) contains an affirmative reproduction/redistribution prohibition.
- `www.lgbs.com/privacy-policy/` addresses personal data only, not relevant to this project's use.
- This source has been in this project's production pipeline since 2026-09-09, shipped and verified before any rights-specific review of it was ever performed.

## 19. Unknowns

Whether `www.lgbs.com/legal-disclosures/`'s prohibition scope extends to `taxsales.lgbs.com`; any rate limit; any attribution requirement; any historical-retention restriction; any contractual restriction Linebarger's own government clients may have placed on it.

## 20. Legal-review items

1. Does the `www.lgbs.com/legal-disclosures/` reproduction/redistribution prohibition extend to `taxsales.lgbs.com` and its `/api/property_sales/` endpoint?
2. If it does, does that retroactively affect data already ingested into production, or only future retrieval?
3. Is there any indication (from Linebarger directly, or from its government clients) of an intended distinction between "a human browsing the site" and "a commercial product retrieving and redistributing the API's data"?

## 21. Recommended registry status

**No change made to `tx_lgbs`'s `legal_status` in this phase — it remains `APPROVED`.** This audit found a genuine, material, previously-undocumented ambiguity (Section 5) that is significant enough to flag prominently, but Phase 10B's own hard rules forbid activating or deactivating a production harvester "based solely on your interpretation" and forbid this document from making a legal determination. Per Step 7's explicit instruction, this is recorded as: **the current `APPROVED` status is a production-practice approval, not a formally rights-cleared one — approval basis requires legal review.** `harvesters/governance/registry.py`'s `tx_lgbs` entry has been updated (Phase 10B, this same commit) to state this explicitly in `commercial_use_status`/`redistribution_status`/`notes`, and `doc_refs` now cites this document — without changing `legal_status` or the ingestion gate's behavior. This finding is escalated to the user directly in this phase's final response (see "SOURCE REGISTRY IMPACT") for an explicit human decision, rather than acted on here.

## 22. Production impact

None from this document alone. `tx_lgbs` continues to gate-pass as `APPROVED`; `harvest_lgbs()` is unmodified; production behavior is unchanged. The impact of this audit is entirely informational until a human reviews Section 5's finding and decides whether `tx_lgbs` should move to `LEGAL_REVIEW_REQUIRED`, stay `APPROVED` on the reasoning that the prohibition doesn't extend to the subdomain in use, or move to `APPROVED_WITH_RESTRICTIONS` with a specific restriction encoded once the scope question is actually answered.

## 23. Date reviewed

2026-09-14 (Phase 10B).
