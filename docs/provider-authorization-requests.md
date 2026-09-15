# Provider authorization request templates

**Status:** Phase 34A, 2026-09-15. **These templates have NOT been sent.** No provider has been contacted as part of this phase (Section 9: repository implementation only - no emails, no web forms, no accounts, no accepted terms, no agreements signed, no purchases, no representation that authorization exists). They exist so a human can review, edit, and send them when ready. Each template ends with an explicit statement of what this project will not do, regardless of any response received.

Filling in and sending either template, and recording whatever response comes back, is a **remaining human action** - see the "Remaining human actions" section of `claude/phase-34a-provider-authorization-framework.md`.

---

## Template: LienHub / Grant Street Group

**To:** Grant Street Group (LienHub) - contact channel to be determined by the sender; `lienhub.com/doc/support` / `support.grantstreet.com` are the two support surfaces this project has located, not verified as the correct commercial-licensing contact.
**Re:** Commercial data-license inquiry - LienHub County-Held Tax Certificate Sales

> We operate a Florida property-tax-sale research platform and currently review certificate-sale listings on LienHub as part of our own due-diligence process. Before automating or commercializing any use of LienHub's data, we want to confirm what is actually authorized under your User Agreement and would appreciate clarification on the following:
>
> 1. Does Grant Street Group offer an official API or structured bulk-data feed for LienHub certificate-sale listings, separate from the interactive web portal?
> 2. Under what terms, if any, would automated (non-interactive, programmatic) retrieval of publicly-listed certificate-sale data be authorized?
> 3. Is commercial SaaS use - incorporating this data into a paid product used by our own subscribers - permitted, and under what license or fee structure?
> 4. What are your position on: storage of retrieved data; historical retention beyond the currently-listed window; normalization/reformatting of the data; derived analytics computed from it?
> 5. Under what conditions, if any, may retrieved data be displayed to our own customers?
> 6. Under what conditions, if any, may retrieved data be included in an export (e.g., a CSV a customer downloads) or a customer-facing API we operate?
> 7. Is there a published or negotiable rate limit for automated access, and would attribution to LienHub/Grant Street Group be required?
> 8. Does LienHub publish or make available any images or documents (as opposed to structured field data), and if so, what governs their reuse?
> 9. Is there a licensing fee structure for the uses described above, and what would the process be for obtaining written authorization?
> 10. Are there existing technical integration options (API keys, data-feed agreements, partner programs) we should be using instead of interactive-portal access?
>
> We want to be direct about our own operating constraints: **we will not bypass CAPTCHA; we will not bypass authentication; we will not bypass WAF or other access controls; we will not evade rate limits; and we will not circumvent any technical restriction**, regardless of your response to this inquiry. We are asking in order to operate within whatever terms you're able to offer, not to justify continuing anything you tell us is not permitted.

---

## Template: RealAuction

**To:** RealAuction.com, LLC - contact channel to be determined by the sender; `sales@realauction.com` / `customerservice@realauction.com` are the two addresses found on the vendor's own public site (Phase 10B), not verified as the correct commercial-licensing contact.
**Re:** Commercial data-license inquiry - RealAuction/RealForeclose tax-deed auction listings (Florida)

> We operate a Florida property-tax-sale research platform and currently review tax-deed auction listings on RealAuction-hosted county sites (e.g. Alachua, Volusia, and other Florida county instances) as part of our own due-diligence process. Before automating or commercializing any use of this data, we want to confirm what is actually authorized under your End User License Agreement(s) and would appreciate clarification on the following:
>
> 1. Does RealAuction offer an official API, commercial data feed, or bulk feed for auction-listing data, separate from the interactive per-county web portals?
> 2. Under what terms, if any, would automated (non-interactive, programmatic) retrieval of publicly-listed auction data be authorized?
> 3. Is commercial SaaS use - incorporating this data into a paid product used by our own subscribers - permitted, and under what license or fee structure?
> 4. What is your position on: storage of retrieved data; historical retention beyond the currently-listed auction window; derived analytics computed from it?
> 5. Under what conditions, if any, may retrieved data be displayed to our own customers, included in a customer export, or exposed through a customer-facing API we operate?
> 6. Is authorization granted or denied at the RealAuction/corporate level, at the individual-county-deployment level, or both - i.e., if authorization is granted for one county, does it extend to others, or is each county instance a separate determination?
> 7. Would attribution to RealAuction be required, and is there a published or negotiable rate limit for automated access?
> 8. Does any RealAuction-hosted county site publish images or documents (as opposed to structured field data) as part of the listing, and if so, what governs their reuse?
> 9. Is there a licensing fee structure for the uses described above, and what would the process be for obtaining written authorization?
>
> We want to be direct about our own operating constraints: **we will not bypass CAPTCHA; we will not bypass authentication; we will not bypass WAF or other access controls; we will not evade rate limits; and we will not circumvent any technical restriction**, regardless of your response to this inquiry. We are asking in order to operate within whatever terms you're able to offer, not to justify continuing anything you tell us is not permitted.

---

## After a response is received

1. Record the response as a new `AuditLogEntry` (`event="document_received"` or `event="reviewed"`) on the relevant `ProviderAuthorization` record in `harvesters/governance/authorization.py`.
2. If a written agreement or license results, store a *reference* to it (`AuthorizationDocument.document_location`, pointing to wherever the actual file is kept - **not** committed into this public-facing source repository unless the agreement itself says that's acceptable) and set `document.is_pending=False`.
3. Only then may `authorization_status` move to `APPROVED`/`APPROVED_WITH_RESTRICTIONS`, and only for the specific `AuthorizationScope` dimensions the response actually grants - never all twelve by default.
4. Update `SOURCE_REGISTRY`'s corresponding `current_commercial_authorization_status` field (`harvesters/governance/registry.py`) to match.
5. Re-run `pytest tests/python/` to confirm nothing regressed.

None of this happens automatically - it is a deliberate, human-reviewed sequence, not a status a form submission can trigger on its own.
