# Verification/engineering track vs. commercial/legal track

**Status:** Phase 37/38, 2026-09-16. This document exists solely to state, in one place, the "MOST IMPORTANT RULE" this phase's instructions closed with, and to make it checkable rather than aspirational.

## The rule

> We are no longer waiting for permission to understand the full potential of the platform. Build the verification and intelligence capability now. At the same time, maintain a hard boundary between: WHAT WE CAN FIND / WHAT WE CAN VERIFY / WHAT WE CAN TECHNICALLY ACQUIRE / WHAT WE ARE AUTHORIZED TO USE / WHAT WE CAN PUT INTO PRODUCTION. The commercial/vendor work will run in parallel. Do not confuse those tracks.

Two tracks, explicitly parallel, explicitly non-blocking of each other:

- **The engineering track** (this phase's actual deliverable): `harvesters/governance/verification.py`'s `DiscoveryStatus`/`VerificationStatus`/`TechnicalAcquisitionStatus`, the FL/TX verification maps, `CountyReadinessState`. This track answers "how far have we gotten" and is allowed to keep moving on a `LEGAL_REVIEW_REQUIRED` or even `BLOCKED` source - inspecting `tx_govease`'s live URL pattern, or re-confirming `harvest_govease()` is still a stub, is legitimate engineering progress even though the source remains blocked.
- **The commercial/legal track**: `harvesters/governance/authorization.py`'s `ProviderAuthorization` records, `docs/vendor-acquisition.md`'s vendor process, `docs/provider-authorization-requests.md`'s drafted outreach. This track answers "may we actually use this" and requires a real, external, human-obtained agreement before it can move - no amount of engineering progress on the first track substitutes for it.

## Where the boundary is enforced in code, not just in this document

`SourceVerificationRecord` (engineering track) has **no `legal_status`, `commercial_use_status`, `restrictions`, or `authorization_status` field** - verified structurally by `tests/python/test_phase37_38_verification_model.py::test_01` and `test_05`. The only way engineering-track data and legal-track data ever meet is `SourceVerificationRecord.production_status_for()`, which does nothing but call Phase 37's `can_promote_source_for_use()` - it cannot assert a more permissive answer than the real gate, because it never stores one of its own.

Concretely, this means:

- Advancing `tx_govease` from `MECHANISM_CONFIRMED` to `CONTENT_VERIFIED` (actually sampling its JSON/HTML response) would be legitimate engineering work under this phase's mandate - and would change **nothing** about its `BLOCKED` registry status or its denial from `can_promote_source_for_use()`.
- Writing a real `harvest_hctax()` against `tx_hctax` (currently `ACQUIRABLE_UNTESTED`) would be legitimate engineering work - and the resulting rows still could not reach `CUSTOMER_DISPLAY` while `tx_hctax` remains `LEGAL_REVIEW_REQUIRED` in `SOURCE_REGISTRY`, because nothing in this codebase's ingestion gate, promotion gate, or this phase's new module treats "we built a harvester" as evidence of legal permission.
- Conversely, a future authorization record being added for `fl_realauction` (say, a written exception is obtained for Alachua) would **immediately, automatically** flip `can_promote_source_for_use("fl_realauction", "CUSTOMER_DISPLAY", county="Alachua")` to allowed, with **zero code change**, because the gate already checks `authorizations_for_source()` live. The commercial track resolving does not require re-running the engineering track.

## What this document is not

It is not a legal opinion, a license, or a statement that any currently-`LEGAL_REVIEW_REQUIRED`/`BLOCKED` source has become safer to use. Every source's `legal_status`/`current_commercial_authorization_status` in `SOURCE_REGISTRY`/`PROVIDER_AUTHORIZATIONS` is unchanged by this phase (Section 38 of this phase's instructions: "do not change their legal status merely because this phase has a broader research objective"). This document only makes explicit, and testable, that engineering progress and legal authorization are permitted to move at different speeds without either one waiting on the other.
