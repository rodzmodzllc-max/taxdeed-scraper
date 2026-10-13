# GovEase: evidence and decision memo

**Date:** 2026-10-12. **Status:** BLOCKED, and it stays blocked. Nothing in this memo changes it. No one at GovEase or any county was contacted, and no GovEase endpoint was requested for this memo.

**The decision belongs to the owner.** This memo lays out options. It does not choose one.

## 1. Verified technical observations (repository records)

All four observations below come from the same reviewer document. That document lives in the claude.ai project, not in this repository, so none of them can be re-checked from the repository.

| Observation | Where recorded | Date |
|---|---|---|
| robots.txt on liveauctions.govease.com read `Disallow: /` | `harvesters/governance/registry.py` `_TX_GOVEASE.robots_status` | 2026-09-14 |
| Auction pages follow `liveauctions.govease.com/tx/<slug>/<id>/browse`. County slug and id enumeration, and whether a JSON API exists, were not resolved. | `harvesters/governance/verification.py` `_TX_GOVEASE_V` (`MECHANISM_CONFIRMED`, `NOT_ACQUIRED`) | 2026-09-14 |
| Texas counties on GovEase: Denton, Parker, Wichita, Wise | `verification.py` `VENDOR_CANDIDATES["govease"]`; `data/tx_county_coverage_matrix.csv` | 2026-09-14 |
| Tennessee counties on GovEase: Montgomery, Rutherford, Robertson, Lawrence, Hawkins, Lincoln | `docs/tennessee-survey.md` | 2026-10-08 |

**Not an observation of GovEase.** From this session's sandbox on 2026-10-12, the GovEase hostnames did not resolve (a DNS failure through the sandbox proxy). That reflects the sandbox's network, not GovEase's state.

## 2. Published terms

**None was retrieved.** The registry records "No Terms of Use page was located" as of 2026-09-14.

A web search on 2026-10-12 returned the items below. These are search-result snippets, not pages that were read, so they are leads to verify and not findings:

- GovEase help-centre articles say a bidder account requires agreeing to the "GovEase Terms & Conditions". Terms therefore appear to exist behind account creation.
- Counties publish their own auction-terms PDFs.
- `support@govease.com` appears in a county auction flyer. It is not verified as a contact for licensing questions.
- govease.com has a "Talk with Sales" form.
- No public API, data feed, affiliate or licensing page surfaced.

## 3. Evidence that is unavailable or stale

- **The block's source document is not in the repository.** It is `claude/govease-source-onboarding-blocked.md`, cited as `reviewer` and `doc_refs` in the registry.
- **The robots.txt observation has not been re-checked since 2026-09-14.**
- **The current terms text has never been read.**
- **Whether the four Texas counties publish their auction lists independently has not been checked.** The question is whether those lists exist anywhere other than GovEase, such as a county page or a newspaper notice.

## 4. What the current block means, and what it does not

**It means:**

- The project's own conservative rule treats a blanket robots.txt disallow, with no terms to weigh against it, as BLOCKED. The registry's wording is "a LEGAL_REVIEW_REQUIRED-grade finding treated conservatively as BLOCKED".
- No GovEase page is requested, stored, displayed or linked as a purchase path anywhere in the product.

**It does not mean:**

- GovEase refused permission. No one has asked: `verification.py` `VENDOR_CANDIDATES["govease"]` records `contract_status` and `contact_status` NOT_CONTACTED.
- A legal finding was made. Counsel has not reviewed anything about GovEase.
- GovEase's data or conduct was judged risky.
- Public accessibility, or a county linking to GovEase, grants permission. It does not; this memo assumes no right.

## 5. How the block is enforced (unchanged; tested end to end in PR #145)

The permission layer and its tests came in PR #145, merged to `main` on 2026-10-13 (merge commit `a07f1ab`). Every layer below is on `main`. PR #148 (merged as `a83da35`) added regression tests showing that stale evidence, missing terms and fallback records cannot unblock it. PR #149 (open) also refuses any discovery, evidence-capture or probe request to a GovEase host before a connection is made.

| Layer | Mechanism |
|---|---|
| Source permission | `harvesters/governance/permissions.py` hard-blocks `tx_govease` in code for every operation. `data/source_permissions.csv` records BLOCKED with evidence type `TECHNICAL_SIGNAL_ONLY`. A record that says anything else invalidates the whole file, which then denies every operation of every source. |
| Registry | `registry.py` `_TX_GOVEASE.legal_status = BLOCKED`; `county_source_registry.BLOCKED_SOURCE_IDS` |
| Ingestion gate | `gate.check_ingestion_gate("tx_govease")` is not allowed. `harvesters/otc/gate.py` refuses blocked vendors by name. |
| Harvester | `texas_harvester.harvest_govease()` raises `NotImplementedError`, and the main loop skips denied sources before calling them. |
| Links and paths | `govease.com` is on the untrusted-host lists (`harvesters/sources/acquisition_gate.py`, `scripts/laft_purchase_paths.py`, `public/app.js`). |
| Publication | A publication review approving GovEase is refused by the validator. |

**Tests in `tests/python/test_source_permissions.py`:**

- every operation is denied;
- an edited record cannot unblock it;
- removed or stale records cannot unblock it;
- every other layer still blocks it;
- a publication review cannot publish it.

## 6. Questions for counsel or the owner

1. Does a robots.txt disallow, with no published terms, warrant BLOCKED, or LEGAL_REVIEW_REQUIRED, which has the same effect today but is more accurate?
2. If GovEase's terms exist only behind account creation, may the owner create an account solely to read them? Would doing so bind the business to those terms?
3. Is linking a customer to a county's own GovEase auction page acceptable? A link copies nothing. Today the product does not link either.
4. Do the four Texas counties publish sale notices independently, so that county name and sale date could come from the county and not from GovEase?
5. If a written inquiry is authorized, who sends it, and which address is treated as authoritative?

## 7. Options (the owner decides; none is chosen here)

| Option | What happens | What it costs | Reversible |
|---|---|---|---|
| A. Keep the block as is | Nothing changes. The four Texas counties and six Tennessee counties stay uncovered. | Coverage | Yes |
| B. Internal review first | A person reads robots.txt and the public site in a normal browser, without creating an account, and records the date and what they saw. If nothing prohibits it, relabel the registry LEGAL_REVIEW_REQUIRED. No behaviour change: the hard block stays in code. | One person-hour | Yes |
| C. Authorize one written inquiry | Send the five questions in `docs/audit/source-register-2026-10-12.md` section 4.4, adapted to the answers to section 6 above. This needs the owner to lift the no-contact instruction. | Disclosure of interest to the vendor | No, a sent message cannot be withdrawn |
| D. County-first reconnaissance | Look for each Texas county's own sale notice. This needs no GovEase contact. | Research time | Yes |

**Ordering.** B and D need no external contact. If C is chosen later, doing B and D first means the inquiry can ask fewer, sharper questions.

**What changes nothing.** None of the options lifts the block by itself. Enabling any GovEase operation needs three things: a recorded owner decision, documented permission evidence, and the coordinated code, record and test change described in `docs/source-permissions.md`.
