# Acquisition engine

**Status:** Phase 39 (Acquisition Engine & Full Data Activation), 2026-09-16. Companion to `docs/source-adapters.md` (the adapter inventory), `docs/acquisition-status.md` (what is acquirable today), `docs/two-state-data-architecture.md` (the five-layer model), and `docs/provider-authorization.md` (the authorization layer this engine defers to and never overrides).

## 1. What it is

`harvesters/acquisition/` turns the Phase 37/38 verified source map into a reusable technical acquisition system. It owns exactly one layer of the five:

```
DISCOVERY -> VERIFICATION -> [ TECHNICAL ACQUISITION ] -> AUTHORIZATION -> PRODUCTION
                               ^ this package
```

It never decides the last two. `policy.py` delegates every authorization question to `harvesters/governance/` (Phases 10A/34A/34B/37/37-38) and is structurally incapable of returning a more permissive answer than those layers already give.

## 2. Why the design looks like this

The decisive constraint is that **fetching is injected, not hard-wired**. Every adapter receives a `Transport` and calls it; no adapter touches `urllib` directly.

That choice was forced by a measured fact rather than chosen on style. This development sandbox's outbound HTTPS is filtered by an organization egress policy that returns `403 Forbidden` at the proxy for every property-data host tested this phase — `taxsales.lgbs.com`, `www.gis.hctx.net`, `mapit.tarrantcounty.com`, `services9.arcgis.com`, `comptroller.texas.gov`, `floridarevenue.com`. That is an **environment** limitation, not a source restriction: the same hosts answered normally through this session's sanctioned, robots-respecting web-fetch tool, and the same code runs against them from GitHub Actions in production today.

The engine records that distinction rather than smearing it. `EnvironmentEgressBlocked` is a separate error class from `AccessRestricted`, because attributing a sandbox policy to a *source* would silently corrupt this project's source-health and verification records with a finding that says nothing about the source at all. Running the real transport here produces:

```
status : SOURCE_UNAVAILABLE
error  : ENVIRONMENT_EGRESS_BLOCKED: local environment egress policy refused
         https://taxsales.lgbs.com/... (Tunnel connection failed: 403 Forbidden);
         this says nothing about the source itself
```

The second consequence of injected transport is that the whole engine is testable against deterministic fixtures, which Section 49 requires anyway ("do not make the test suite depend on external websites"). The same adapter code runs against `UrllibTransport` in production and `FixtureTransport` in CI.

## 3. The contract

The pattern this repository already had — and which `SourceAdapter` formalizes rather than replaces — is the **fetch/normalize split** that `scripts/enrich_property_details_tx.py` arrived at independently:

```
_fetch_hcad(parcel_id)            -> raw ArcGIS attributes   (network)
hcad_attributes_to_generic(attrs) -> generic dict            (pure)
normalize_cad_response(generic)   -> properties-table fields (pure)
```

That split is why those normalizers were already testable without a network, and why this phase could verify HCAD's live field contract without touching any parsing code. `SourceAdapter` adds the three things that were missing: an injected transport, a structured result, and a policy check that runs *before* any request.

```python
class SourceAdapter:
    def discover(self)      -> AcquisitionPolicyDecision
    def verify(self)        -> AcquisitionResult
    def acquire(self, ...)  -> AcquisitionResult   # template: policy first, always
    def normalize(self, raw)-> dict | None
    def health_check(self)  -> AcquisitionResult
```

An adapter may never reach the network directly, decide its own legal status, return a bare list or `None`, or invent a field the source did not publish.

## 4. Result model

Every attempt produces one `AcquisitionResult` with a **specific** status. There is deliberately no generic `FAILED` member on `AcquisitionStatus` — a caller that genuinely cannot determine a reason must use `TECHNICAL_FAILURE` and populate `error_code`/`error_message`, and can never paper over a known-but-unrecorded reason, because no generic value exists to hide behind.

`SUCCESS`, `PARTIAL_SUCCESS`, `NO_DATA`, `SOURCE_UNAVAILABLE`, `TECHNICAL_FAILURE`, `SCHEMA_FAILURE`, `RATE_LIMITED`, `AUTHENTICATION_REQUIRED`, `ACCESS_RESTRICTED`, `LEGAL_RESTRICTION`, `NOT_APPLICABLE`.

Two invariants are enforced in `__post_init__` rather than left to discipline: a result may never claim more records than it holds, and `SUCCESS` with zero records is unrepresentable (that is `NO_DATA`'s job — a source that was reached and published nothing must stay distinguishable from one that could not be reached).

## 5. Responsible request behavior

`RateLimitPolicy` carries timeout, minimum interval, jitter, retry ceiling, exponential backoff with a cap, concurrency limit and a circuit-breaker threshold as **data per source**, replacing the scattered `time.sleep(0.3)` / `time.sleep(0.2)` / 4-9s-jittered-delay conventions each existing harvester invented locally.

`AccessRestricted` and `AuthenticationRequired` are never retried. Retrying a refusal is precisely the behavior Section 15 prohibits.

Explicitly absent from this module, and never to be added: user-agent rotation, proxy or identity rotation, CAPTCHA solving, WAF evasion, authentication bypass, robots circumvention. A source that cannot be reached without one of those is recorded as `TECHNICAL_ACQUISITION_BLOCKED` with its reason — that is the intended outcome, not a problem to engineer around.

Note one pre-existing practice this engine does **not** adopt or extend: `harvest_realauction()` and `harvest_all_counties.ps1` set spoofed desktop-Chrome User-Agent strings. That is a documented pre-existing behavior of those harvesters (see `registry.py`'s `fl_realauction` entry); `UrllibTransport` identifies this project honestly instead.

## 6. Governance separation

`policy.py` implements Section 17's distinction between two purposes:

- **`INTERNAL_TECHNICAL_TESTING`** — verifying an endpoint exists, responds, and returns expected fields. Permitted for a source whose *commercial* authorization is unresolved, because an unresolved commercial question is not a prohibition on looking.
- **`PRODUCTION_ACQUISITION`** — pulling records intended to flow toward the customer-facing system. Requires the full Phase 37 promotion gate to allow the relevant use, for that county, today.

**The limit on that distinction is the most important rule in the module.** A source that is `BLOCKED`, `DISABLED` or `TERMS_CHANGED` in `SOURCE_REGISTRY` is refused for **both** purposes. Internal testing does not unlock `tx_pbfcm`, `tx_mvba`, `tx_ctsa` or `tx_govease`. The testing allowance applies only where no prohibition has actually been found and the open question is commercial.

Worked example, from the real test suite:

```
tx_hctax, PRODUCTION_ACQUISITION -> LEGAL_RESTRICTION (zero requests made)
tx_hctax, INTERNAL_TECHNICAL_TESTING -> SUCCESS, 1 record, full provenance,
                                        raw_storage_status = RESTRICTED
can_promote_source_for_use("tx_hctax", "CUSTOMER_DISPLAY").allowed -> False
```

All three are true simultaneously. That is the point.

## 7. Provenance and identity

Every normalized record carries five prefixed keys (`_source_id`, `_source_record_id`, `_retrieved_at`, `_source_timestamp`, `_normalization_version`), asserted by the test suite. Source-native values are preserved beside normalized ones (`_source_status`, `_source_sale_type`, `_source_attributes`) so normalization never destroys what the source actually said.

`idempotency_key()` uses the source's own record identifier, never a hash of mutable content — a re-published record with a corrected bid must dedupe to the same key, not look like a new record. It falls back to the `(state, source, county, case_no)` triple that migration 004's uniqueness constraint already uses, so the engine's notion of identity cannot diverge from the database's.

## 8. What was deliberately not built

- **No schema change, no migration, no production data modification.** Checkpoints are a JSON file, not a table, because they are operational state rather than product data.
- **No DOCUMENT_PDF adapter.** `fl_laft_pdfs` already has a working production implementation (`scripts/harvest_laft_pdfs.py`); re-implementing it behind this contract with no behavioral gain would violate Section 10's "do not rewrite the Florida harvesters merely for architectural cleanliness."
- **No HTML_PUBLIC_SEARCH adapter.** The mechanism behind `fl_realauction`/`tx_realauction`/`fl_lienhub_certificates` — all of which are `LEGAL_REVIEW_REQUIRED` for production use and already served by working harvesters. Their blocker is legal, not technical; building a new acquisition path for them would spend engineering effort where it changes nothing.
- **No frontend or API change.** Acquisition never expands customer access (Section 40).
- **No `harvest_govease()` implementation.** Section 23's "do not implement a speculative scraper simply to eliminate the stub" — it remains a documented stub, and its `BLOCKED` status is unchanged.

## 9. Migration path for the existing harvesters

Nothing in this phase changed `harvesters/texas_harvester.py`, `scripts/enrich_property_details_tx.py`, `scripts/enrich_property_details.py`, or any Florida PowerShell script. The adapters *call into* the existing verified normalizers rather than replacing them, so there is exactly one implementation of each parse rule.

The one place a helper was reimplemented instead of imported is FDOR's `_num` sentinel rule: `scripts/enrich_property_details.py` calls `sys.exit(1)` at module scope when Supabase credentials are unset, so importing it would terminate any process that merely touches the adapter — including the test suite. The adapter reproduces that script's documented semantics exactly, and two tests assert agreement against the script's own source text so the two cannot drift silently. Moving those helpers into an importable module is a clean, behavior-preserving refactor for a future phase; it was not done here because Section 10 forbids touching the working Florida pipeline for architectural reasons alone.
