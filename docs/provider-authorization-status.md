# Provider authorization status

**Status:** Phase 34A built this page, 2026-09-15; Phase 34B (same date) reviewed it against the new enforcement wiring and confirms neither status below changed - the review below adds the enforcement/lifecycle detail Phase 34B Section 17 asks for. The current, authoritative statement of what this project has and has not established for its two Florida vendor-platform sources. Supersedes the "Not formally reviewed"/robots.txt-and-WAF-only framing in `claude/phase-33-5-florida-production-source-rights-audit.md` now that actual agreement terms are on file - that document's findings are preserved, not erased, and remain correct as far as they went; this page reflects what the actual license text (as supplied) adds on top of them.

## Lifecycle position (Phase 34B Section 17)

Both records below sit at the same point in the authorization lifecycle - Section 17 asks that "requested / received / reviewed / approved / restricted / expired / revoked" be clearly distinguished, so, explicitly, for both `_LIENHUB_GRANT_STREET` and `_REALAUCTION_ALACHUA`/`_REALAUCTION_VOLUSIA`:

| Lifecycle step | LienHub | RealAuction (Alachua/Volusia) |
|---|---|---|
| Requested (a request was sent to the provider) | No - `request_status=REQUEST_NOT_STARTED`, `requested_by=None`, `request_date=None` | No - same |
| Received (a provider response/document was received) | No - `document.is_pending=True`, no response received | No - same |
| Reviewed (the supplied terms were read and transcribed) | Yes - `reviewed_by`/`reviewed_at` populated, `document.scope_summary` transcribes the supplied terms | Yes - same |
| Approved (any use dimension authorized) | No - every `scope.<dim>.authorized=False` | No - same |
| Restricted (`APPROVED_WITH_RESTRICTIONS`, some but not all dimensions authorized) | No - not in a granted status at all | No - same |
| Expired (`effective_authorization_status()` computes `EXPIRED`) | No - no `expiration_date` is set, so this can never trigger | No - same |
| Revoked | No - `authorization_status` has never been `REVOKED` | No - same |

In short: both records have been **reviewed** (the supplied terms are on file, structured, and transcribed) but never **requested, received, approved, restricted, expired, or revoked** - they sit at `LEGAL_REVIEW_REQUIRED`, the state for "we have terms to review and they do not establish authorization," not any later lifecycle state. Phase 34B did not move either record forward on its own initiative, consistent with the standing rule against inflating status without a real event to justify it.

## Enforcement status (Phase 34B)

Phase 34B added real production wiring (`harvesters/governance/authorization.py`'s `authorized_for_customer_output()`, wired into `scripts/sync-texas-to-supabase.py`) that *would* block both sources from customer-facing display if either were ever routed through that script - today neither is, since Florida's pipeline is entirely separate PowerShell/Python that does not import this governance package at all (see `docs/provider-authorization.md`'s "Production enforcement" section for the full picture and the named gap). So the practical, honest statement is: both sources are *governed on paper and enforced in tests* against this new boundary, but *not yet live-enforced* in Florida's actual production pipeline - unchanged from the position before Phase 34B, since Florida's pipeline was equally unreachable by the Phase 34A framework and by the pre-existing Phase 11 gate before it.

## LienHub / Grant Street Group

**Current status: `LEGAL_REVIEW_REQUIRED`**

**Reason:** the supplied LienHub User Agreement restricts automated monitoring/copying and redistribution, and limits the license scope to specified tax-certificate-related activities. Specifically, as supplied: the agreement is between Grant Street Group and participating Florida Tax Collectors; LienHub information is subject to proprietary rights; use is licensed only for specified tax-certificate-related activities; copying, saving, publishing, disseminating, distributing, disclosing, modifying, reselling, or redistributing proprietary information is restricted except where expressly permitted; third-party access/credential sharing is restricted; robots, spiders, or similar devices to monitor or copy pages/content/information are expressly prohibited; software/devices interfering with the portal are prohibited; a narrow exception permits copying transaction evidence for internal recordkeeping under specified conditions; the agreement may be amended; Grant Street may suspend or revoke privileges; accuracy/completeness/timeliness is disclaimed.

Written authorization/commercial licensing is needed before treating automated commercial use as authorized. This is not a claim that the source is blocked or illegal - it is a statement that the agreement, as supplied, does not establish authorization for the intended automated commercial use, and that written permission has not been sought or received.

**Structured record:** `harvesters/governance/authorization.py`, `_LIENHUB_GRANT_STREET` (`authorization_id="fl_lienhub_certificates__provider__grant_street_group"`).

## RealAuction

**Current status: `LEGAL_REVIEW_REQUIRED`**

**Reason:** the supplied county EULAs (Alachua, Volusia) restrict automated access, copying, use, sale, and distribution absent express written approval. Specifically, as supplied: the license is for accessing/using information for the purpose of purchasing or attempting to purchase property through that county's own sale process; information presented by RealAuction cannot be used, altered, sold, or distributed without RealAuction's express written consent; automated software/program/device access is prohibited without RealAuction's prior written approval; robots/spiders/similar devices to monitor or copy pages/content/information are prohibited; automated site processes and mouse-click automation are restricted; certain registration/sales records may constitute public records under Florida law; terms may be amended.

Written authorization is needed before treating automated commercial use as authorized - for either county specifically, and this finding is not extended to any of the ~44 other Florida counties RealAuction also serves under the `fl_realauction` source_id, which have no supplied agreement and no authorization record at all.

**Structured records:** `harvesters/governance/authorization.py`, `_REALAUCTION_ALACHUA` (`authorization_id="fl_realauction__county__alachua"`) and `_REALAUCTION_VOLUSIA` (`authorization_id="fl_realauction__county__volusia"`).

## What this status does and does not mean

The supplied agreements do not establish authorization for the intended automated commercial use. That is the precise, supportable statement - not "this source is illegal," not "scraping is definitely illegal," and not "government public records cannot be commercially used." Both agreements distinguish (Phase 34A Section 3):

1. **Public-record status of underlying information** - both agreements themselves note that certain registration/sales records may constitute public records under Florida law. That status, if it applies, concerns the *information* the county government itself holds, independent of the vendor platform.
2. **RealAuction/LienHub platform access permissions** - what the EULA/User Agreement licenses for using the vendor's own portal.
3. **Automated collection permission** - both agreements, as supplied, restrict or prohibit this specifically.
4. **Commercial use** - narrower than, and not established by, platform access permission.
5. **Customer display** - not established by either agreement as supplied.
6. **Redistribution/export** - restricted (LienHub) or requiring express written consent (RealAuction) as supplied.
7. **API redistribution** - not addressed as a distinct grant in either agreement as supplied; treated as unauthorized absent one.

These seven are kept as seven separate questions throughout this project's governance model (`harvesters/governance/authorization.py`'s `AuthorizationScope`), never collapsed into a single "is this source okay" boolean. Public-record status of the underlying information is not itself inferred to authorize automated platform access, and years of prior unchallenged operation is not inferred to establish authorization either - both are exactly the inferences Phase 34A's instructions warned against making, and neither was made here.

## What would change this status

Only an actual, documented resolution: a written response from the provider granting some or all of the requested uses, a counsel opinion, or an explicit accepted-risk business decision made by the project owner with the agreement's actual terms in hand. Continued production operation, more reconnaissance, or the passage of time does not, on its own, move either status forward. See `docs/provider-authorization-requests.md` for the templates that would begin that process, not yet sent.
