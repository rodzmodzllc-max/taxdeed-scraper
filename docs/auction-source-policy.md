# Auction source acquisition policy

**Status:** Phase 33 (Commercial Source-of-Truth, Scraping Compliance, and Lawful Acquisition Audit), 2026-09-15. This page classifies every auction/tax-sale source this project has reconnoitered (Phase 8 through Phase 33) into the five acquisition modes Phase 33 defines, built directly from `harvesters/governance/registry.py`'s existing `legal_status` values — it does not re-review any source or change any status; it is a second view of the same registry data, organized by acquisition strategy rather than by source ID.

## The five modes

| Mode | Definition | May: harvest / store / normalize / display / export / API |
|---|---|---|
| **A — Direct API/bulk** | Rights established, structured machine access | Per source policy, once `legal_status` is `APPROVED` or `APPROVED_WITH_RESTRICTIONS` with an actual rights finding behind it |
| **B — Official public database** | Government-run, use only to the extent permitted | Same as Mode A, government sources get no special exemption from the same gate |
| **C — Link-out** | Source can be shown to customers; automated copying/storage rights are not established | Metadata only (see [Permitted metadata for link-only sources](#permitted-metadata-for-link-only-sources) below); no full-record ingestion |
| **D — License required** | Useful but commercial use requires a license | None until a license exists; treated as BLOCKED for ingestion until then |
| **E — Blocked** | Do not use | None |

Mode is a *strategy* label, not a new field on `SourceRecord` — it is derived mechanically from `legal_status` (see the mapping below) so it can never drift out of sync with the registry the ingestion gate actually checks.

## Current mapping (12 registered sources, as of Phase 33)

| source_id | legal_status | Mode | Why |
|---|---|---|---|
| `tx_lgbs` | `APPROVED` | **A** | Shipped, production-verified JSON API; commercial-use scope question open but not yet resolved against it (see `docs/lgbs-rights-audit.md`) |
| `tx_realauction` | `APPROVED` | **A** | Shipped, production-verified; robots.txt question open (see `docs/realauction-rights-audit.md`) |
| `fl_realauction` | `APPROVED` | **A** | Grandfathered production source, same vendor family as `tx_realauction` |
| `fl_laft_pdfs` | `APPROVED` | **A** | Grandfathered production source (per-county PDFs, official/government-published) |
| `fl_lienhub_certificates` | `APPROVED` | **A** | Grandfathered production source |
| `tx_hctax` | `LEGAL_REVIEW_REQUIRED` | **C** (interim) | Fully technically ready (see `claude/harris-hctax-implementation-readiness.md`), but no permission established — treated as link-out only until a resolution exists. See [Harris County interim posture](#harris-county-interim-posture) below. |
| `fl_dor_statewide` | `LEGAL_REVIEW_REQUIRED` | **C** (interim) | Free, official, no restriction found *and* no permission found — same interim treatment as Harris |
| `tx_comptroller_directory` | `DISCOVERED` | **C** (interim) | Confirmed to exist; not reviewed for rights at all yet |
| `tx_pbfcm` | `BLOCKED` | **E** | Explicit, affirmative anti-reproduction/redistribution clause (`disclosure.html`) |
| `tx_mvba` | `BLOCKED` | **E** | Explicit non-commercial-use-only clause |
| `tx_ctsa` | `BLOCKED` | **E** | Paywall + explicit anti-competitive-use clause |
| `tx_govease` | `BLOCKED` | **E** | Blanket `robots.txt: Disallow: /`, no locatable Terms of Use |

No source in this registry is currently Mode D (license required) — none of the four BLOCKED vendors has been approached about licensing; that would be a business decision, not a reconnaissance finding, and none has been made.

## Permitted metadata for link-only sources

Per Phase 33 Section 9, a Mode C source may have the platform maintain only lawfully-established metadata necessary for property intelligence — auction date, county, case number, property identifier, auction status, the official source URL, the source's own record ID, and a last-checked timestamp — and only once that metadata's own acquisition/storage/display rights are independently established (not inherited from "the source exists and is public"). **As of Phase 33, no Mode C source has that independent establishment yet** — `tx_hctax`, `fl_dor_statewide`, and `tx_comptroller_directory` all remain `LEGAL_REVIEW_REQUIRED`/`DISCOVERED`, which the ingestion gate (`harvesters/governance/gate.py`) already rejects outright (see `INGESTION_ALLOWED_STATUSES`). This section describes the *target* shape for when/if one of these resolves favorably, not a currently-active data flow. No metadata-only harvester exists in this codebase for any Mode C source today.

## Harris County interim posture

`tx_hctax` is this project's most-developed Mode C candidate: full technical readiness (Phase 9), a formal rights review finding "no restriction, no permission" (Phase 9.5), and a drafted-but-unsent outreach package with 12 specific rights questions and a response-classification framework (Phase 9.6). Phase 33 did not send that outreach and did not change `tx_hctax`'s status — per `docs/source-registry.md`'s "Future source onboarding process," only an actual resolution (a response, a counsel opinion, or an accepted-risk business decision) can move a `LEGAL_REVIEW_REQUIRED` source to `APPROVED`/`APPROVED_WITH_RESTRICTIONS`, never further reconnaissance alone.

## Non-registered auction candidates

`claude/county-first-fallback-reconnaissance.md` (Phase 8) investigated 23 jurisdictions blocked at the vendor level and found exactly two county-first candidates worth registry entries: Harris County (now `tx_hctax`, above) and Johnson County (Constable PDFs — never advanced to a registry entry because the PDFs' authorship, county vs. PBFCM counsel, was never resolved; PBFCM's own `disclosure.html` restriction would attach if PBFCM authored them). Johnson County is intentionally left unregistered rather than guessed into either direction — see the coverage matrix's `UNKNOWN` entry for Johnson County.
