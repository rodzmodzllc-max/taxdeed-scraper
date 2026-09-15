"""Provider authorization framework - Phase 34A (Provider Authorization &
Commercial Data License Framework).

Repository audit finding (Phase 34A Step 1): before this module, this
project's governance package (registry.py/gate.py/restrictions.py,
Phase 10A) only ever asked ONE question - "is this source_id's
`legal_status` one of the two INGESTION_ALLOWED_STATUSES?" - a single,
whole-source, provider-agnostic yes/no. Phase 33.5's own audit of the
three grandfathered Florida sources found that question is too coarse for
what a real commercial license actually grants: a provider's agreement may
license viewing a specific county's auction listings for the purpose of
bidding, while saying nothing about (or expressly prohibiting) automated
retrieval, storage, customer display, export, or API redistribution of
that same data. Treating "the source is APPROVED" as "every one of those
seven activities is therefore permitted" would be exactly the kind of
technical-accessibility-as-legal-permission conflation this project's own
standing rule (docs/data-licensing.md's "core rule") forbids.

This module answers a DIFFERENT, narrower, additive question:
"for source_id X, in county/deployment Y, has an actual documented
authorization been recorded that covers use Z specifically?" It sits
ALONGSIDE gate.py's existing check_ingestion_gate(), not on top of or in
place of it - `check_authorized_use()` below requires BOTH the existing
ingestion gate to pass AND a real, per-use authorization record to exist
and cover the requested use. Nothing in this module weakens or bypasses
check_ingestion_gate() (Phase 34A Step 12's explicit instruction); it can
only ever be stricter than the existing gate, never looser.

NOT wired into any production call site as of this phase, on purpose -
the same deliberate, documented gap this codebase already carries for
gate.py's own filter_rows_for_customer_output()/project_row_for_
customer_output() (see docs/data-licensing.md's "Remaining risks" #1):
Florida's actual PowerShell/Python harvesting pipeline does not import
this governance package at all, and this phase does not change that
(Phase 34A Step 21 explicitly forbids rewriting Florida's harvesters).
This module exists so a FUTURE integration point has a ready, tested
enforcement function to call, and so the two real agreements supplied
this phase (LienHub's User Agreement, RealAuction's Alachua/Volusia
EULAs) have an actual, structured, auditable home instead of living only
as prose in a claude/*.md report.

Design note on Phase 34A Step 5's "do not create four separate tables if
the existing architecture has a cleaner normalized approach": this
project's "existing architecture" for governance is a set of frozen
Python dataclasses referenced by source_id (registry.py), not a set of
SQL tables - there is no Supabase schema for source governance today and
this phase does not add one (see the module docstring's "No database
migration executed" note, echoed in the Phase 34A report). Rather than
four separate top-level registries (provider_authorizations /
authorization_documents / authorization_requests / authorization_scope,
as sketched in the instructions), this module normalizes to ONE record
type - ProviderAuthorization - with three small, nested, reusable value
types (AuthorizationDocument, AuthorizationScope, AuditLogEntry) embedded
in it, exactly the same shape discipline registry.py's own SourceRecord
already uses (one flat-ish record per source, referenced by source_id
elsewhere, rather than a join across several tables). A ProviderAuthorization
references its source_id rather than duplicating any of that SourceRecord's
fields (Step 5's "do not duplicate information unnecessarily" instruction).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

from .gate import check_ingestion_gate, project_row_for_api_export, project_row_for_customer_output
from .registry import SourceStatus


class AuthorizationStatus(str, Enum):
    """The controlled state machine Phase 34A Step 6 requires. Deliberately
    NOT a boolean, and deliberately NOT collapsible into one - see
    `AUTHORIZATION_GRANTED_STATUSES` below for the only two states under
    which ANY per-use flag may legitimately be True.

    Includes every state Step 6 lists "at minimum", plus TERMS_CHANGED
    (Step 14 explicitly calls for this state, or an equivalent, to exist;
    rather than invent a second, parallel vocabulary this module reuses
    the exact spelling registry.py's own SourceStatus.TERMS_CHANGED
    already uses, for the same concept applied one level down, at the
    authorization-record granularity instead of the whole-source
    granularity)."""

    REQUEST_NOT_STARTED = "REQUEST_NOT_STARTED"
    DRAFT = "DRAFT"
    CONTACTED = "CONTACTED"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    APPROVED_WITH_RESTRICTIONS = "APPROVED_WITH_RESTRICTIONS"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    LEGAL_REVIEW_REQUIRED = "LEGAL_REVIEW_REQUIRED"
    TERMS_CHANGED = "TERMS_CHANGED"
    NOT_YET_EFFECTIVE = "NOT_YET_EFFECTIVE"  # Phase 34B Section 13: an effective_date in the future denies, same as EXPIRED denies past it


# The ONLY two states under which any individual AuthorizationScope flag is
# permitted to be `authorized=True` - enforced by ProviderAuthorization's
# own __post_init__ validation below, not left to callers to remember.
# Mirrors registry.py's INGESTION_ALLOWED_STATUSES exactly, one level down.
AUTHORIZATION_GRANTED_STATUSES = frozenset(
    {
        AuthorizationStatus.APPROVED,
        AuthorizationStatus.APPROVED_WITH_RESTRICTIONS,
    }
)
# Every other AuthorizationStatus member (REQUEST_NOT_STARTED, DRAFT,
# CONTACTED, AWAITING_RESPONSE, RECEIVED, UNDER_REVIEW, DECLINED, EXPIRED,
# REVOKED, LEGAL_REVIEW_REQUIRED, TERMS_CHANGED, NOT_YET_EFFECTIVE) denies -
# there is deliberately no second "always deny" set to keep in sync with
# this one; `not in AUTHORIZATION_GRANTED_STATUSES` is the single source of
# truth `check_authorized_use()` and `ProviderAuthorization.__post_init__`
# both consult.


@dataclass(frozen=True)
class UsePermission:
    """One yes/no/not-yet-asked pair for a single dimension of use
    (Phase 34A Step 7's "requested vs authorized" distinction). Asking for
    permission is not the same event as receiving it - `requested=True,
    authorized=False` is the default, expected state for every dimension
    of a brand-new authorization record, and stays that way until a real,
    documented grant changes it."""

    requested: bool = False
    authorized: bool = False


@dataclass(frozen=True)
class AuthorizationScope:
    """The full per-use permission matrix Phase 34A Step 5/7 lists,
    one UsePermission per dimension. `api_access` (does an official
    API/feed exist that this project may use at all) is kept distinct
    from `api_redistribution` (may THIS project re-expose the data
    through its OWN customer-facing API) - the two are genuinely
    different grants, matching Step 5's field list keeping them
    separate."""

    automated_access: UsePermission = field(default_factory=UsePermission)
    commercial_use: UsePermission = field(default_factory=UsePermission)
    storage: UsePermission = field(default_factory=UsePermission)
    historical_storage: UsePermission = field(default_factory=UsePermission)
    normalization: UsePermission = field(default_factory=UsePermission)
    derived_data: UsePermission = field(default_factory=UsePermission)
    customer_display: UsePermission = field(default_factory=UsePermission)
    customer_export: UsePermission = field(default_factory=UsePermission)
    api_access: UsePermission = field(default_factory=UsePermission)
    api_redistribution: UsePermission = field(default_factory=UsePermission)
    image_use: UsePermission = field(default_factory=UsePermission)
    document_use: UsePermission = field(default_factory=UsePermission)

    def get(self, use: str) -> UsePermission:
        """Look up one dimension by its field name (e.g. "automated_access"),
        the same string vocabulary check_authorized_use() takes. Raises
        ValueError for an unrecognized use name rather than silently
        returning a default-False UsePermission, so a typo'd `use` argument
        fails loudly instead of quietly always denying."""
        if not hasattr(self, use) or use not in ALL_USE_DIMENSIONS:
            raise ValueError(f"'{use}' is not a recognized authorization-scope dimension. Valid: {sorted(ALL_USE_DIMENSIONS)}")
        return getattr(self, use)


ALL_USE_DIMENSIONS = frozenset(
    {
        "automated_access",
        "commercial_use",
        "storage",
        "historical_storage",
        "normalization",
        "derived_data",
        "customer_display",
        "customer_export",
        "api_access",
        "api_redistribution",
        "image_use",
        "document_use",
    }
)


@dataclass(frozen=True)
class AuthorizationDocument:
    """A REFERENCE to a contract/agreement/EULA - never the document's own
    text or a fabricated path (Phase 34A Step 15's explicit instruction).
    `is_pending=True` (the default) means no actual file is on file in
    this repository yet; `document_location` MUST stay `None` in that
    case. This phase (34A) was given the substantive TERMS of the LienHub
    User Agreement and the RealAuction Alachua/Volusia EULAs as prose
    inside the user's own instructions - not as uploaded files this
    repository can reference by path - so every AuthorizationDocument this
    phase creates is `is_pending=True` with `document_location=None`,
    `scope_summary` carrying a transcription of what was supplied, and
    `document_name` naming what the document IS without claiming a
    repository location for it that does not exist."""

    document_name: str | None = None
    document_location: str | None = None  # repo-relative path, ONLY if the file is actually present
    document_hash: str | None = None
    effective_date: str | None = None
    expiration_date: str | None = None
    reviewer: str | None = None
    review_date: str | None = None
    scope_summary: str | None = None
    is_pending: bool = True

    def __post_init__(self) -> None:
        if not self.is_pending and not self.document_location:
            raise ValueError(
                "AuthorizationDocument.is_pending=False (i.e. 'a real document is on file') requires a "
                "document_location - never claim a document is on file without a path to it."
            )


@dataclass(frozen=True)
class AuditLogEntry:
    """One immutable audit-trail entry (Phase 34A Step 16). A
    ProviderAuthorization's `audit_log` tuple is append-only in practice
    (nothing in this module offers a way to mutate or delete an existing
    entry) - the full history of how a status was reached stays on the
    record, not just its current snapshot."""

    event: str  # created|requested|contacted|document_received|reviewed|approved|restricted|declined|expired|revoked|terms_changed
    who: str
    when: str  # ISO date
    old_status: str | None
    new_status: str | None
    reason: str
    document_reference: str | None = None


@dataclass(frozen=True)
class ProviderAuthorization:
    """One authorization record - Phase 34A Step 5's full field list,
    normalized into this single dataclass (see module docstring for why
    this is one record type, not four). `source_id` REFERENCES
    registry.SOURCE_REGISTRY rather than duplicating any of that record's
    fields.

    Scope hierarchy (Phase 34A Step 4): Provider -> Platform/deployment ->
    County/jurisdiction -> Source -> Permitted use. `provider` and
    `deployment_scope` carry the top two levels; `county` (nullable - None
    means provider-wide/statewide, never "unknown" by omission - an
    absent county is always deliberate) carries the third; `source_id`
    the fourth; `scope` (an AuthorizationScope) the fifth. A record scoped
    to one county authorizes ONLY that county - see
    `authorizations_for_source()`'s docstring and
    `test_provider_authorization.py`'s county-isolation tests for the
    guarantee this makes structurally impossible to bypass by accident.
    """

    authorization_id: str
    source_id: str
    provider: str
    government_entity: str | None
    state: str
    county: str | None  # None = provider-level/statewide record, not a specific county's deployment
    deployment_scope: str  # "provider" | "platform" | "county" - which level of Step 4's hierarchy this record represents
    requested_by: str | None
    request_date: str | None
    contact_name: str | None
    contact_email: str | None
    request_status: AuthorizationStatus
    authorization_status: AuthorizationStatus
    document: AuthorizationDocument
    agreement_url: str | None
    agreement_version: str | None
    agreement_date: str | None
    effective_date: str | None
    expiration_date: str | None
    review_due_date: str | None
    scope: AuthorizationScope
    attribution_required: bool | None
    rate_limit: str | None
    retention_requirement: str | None
    privacy_restrictions: str | None
    technical_restrictions: str | None
    written_permission: bool
    reviewed_by: str | None
    reviewed_at: str | None
    notes: str
    terms_version: str | None = None
    terms_hash: str | None = None
    last_terms_check: str | None = None
    audit_log: tuple[AuditLogEntry, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Fail-closed structural guarantee (Phase 34A Step 6's "CONTACTED
        # does NOT mean APPROVED, RECEIVED does NOT mean APPROVED"),
        # enforced here so it can never be violated by a future registry
        # entry forgetting to check it manually: no per-use flag may be
        # `authorized=True` unless this record's own status is one of the
        # two AUTHORIZATION_GRANTED_STATUSES.
        if self.authorization_status not in AUTHORIZATION_GRANTED_STATUSES:
            for use in ALL_USE_DIMENSIONS:
                perm: UsePermission = getattr(self.scope, use)
                if perm.authorized:
                    raise ValueError(
                        f"authorization_id={self.authorization_id!r}: scope.{use}.authorized=True is not "
                        f"permitted while authorization_status={self.authorization_status.value!r} - only "
                        f"{sorted(s.value for s in AUTHORIZATION_GRANTED_STATUSES)} may carry any authorized use. "
                        "Requesting or receiving a document is not the same event as being granted permission."
                    )
        if self.written_permission and self.document.is_pending:
            raise ValueError(
                f"authorization_id={self.authorization_id!r}: written_permission=True requires an actual "
                "document on file (document.is_pending=False with a document_location) - never assert written "
                "permission exists without a reference to what was written."
            )
        # Phase 34B data-integrity guard: a record whose effective_date is
        # AFTER its own expiration_date describes a window that never
        # exists - catch this at construction time rather than letting
        # effective_authorization_status() silently pick one interpretation.
        if self.effective_date and self.expiration_date and self.effective_date > self.expiration_date:
            raise ValueError(
                f"authorization_id={self.authorization_id!r}: effective_date ({self.effective_date}) is after "
                f"expiration_date ({self.expiration_date}) - this authorization window never exists."
            )


def effective_authorization_status(
    record: ProviderAuthorization, *, as_of: str | None = None
) -> AuthorizationStatus:
    """Phase 34A Step 13/14, extended by Phase 34B Section 13: compute the
    status that actually governs TODAY (or `as_of`, for testing a specific
    date), which may differ from the status literally stored on the
    record - checked in this order:

      1. REVOKED always wins (terminal) - a revoked record is REVOKED no
         matter what its dates say.
      2. A future `effective_date` (the authorization window has not
         started yet) -> NOT_YET_EFFECTIVE, regardless of the stored
         status. `ProviderAuthorization.__post_init__` already guarantees
         effective_date <= expiration_date when both are set, so this
         check and the next one are mutually exclusive on valid data.
      3. A past `expiration_date` -> EXPIRED, regardless of the stored
         status.
      4. Otherwise, the stored `authorization_status` is returned
         unchanged.

    Step 13's "the source must no longer be treated as commercially
    authorized" (and, symmetrically, "not yet" for a future-dated one) is
    enforced HERE, at read time, rather than depending on some future
    background job remembering to flip a stored field. `check_authorized_
    use()` below always calls this function, never the raw stored field."""
    if record.authorization_status == AuthorizationStatus.REVOKED:
        return AuthorizationStatus.REVOKED
    today = date.fromisoformat(as_of) if as_of else datetime.utcnow().date()
    if record.effective_date and today < date.fromisoformat(record.effective_date):
        return AuthorizationStatus.NOT_YET_EFFECTIVE
    if record.expiration_date and today > date.fromisoformat(record.expiration_date):
        return AuthorizationStatus.EXPIRED
    return record.authorization_status


@dataclass(frozen=True)
class UseDecision:
    """The result of check_authorized_use() below - mirrors gate.py's own
    GateDecision shape deliberately, so a caller already familiar with
    that pattern reads this one the same way. `checked_at` (Phase 34B
    Section 16) is a real wall-clock timestamp of when THIS decision was
    computed - independent of `as_of` (which simulates "as of what date",
    for testing) - so a logged denial carries enough to diagnose WHEN it
    was checked, on top of source/county/use/status/reason. Nothing on
    this dataclass is a secret, credential, or personal-data field -
    source_id/county/use/status/reason/timestamp only."""

    source_id: str
    use: str
    county: str | None
    allowed: bool
    ingestion_gate_allowed: bool
    authorization_status: AuthorizationStatus | None
    reason: str
    checked_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


def authorizations_for_source(source_id: str) -> tuple[ProviderAuthorization, ...]:
    """Every authorization record for a given source_id, at any
    deployment_scope/county. A source_id can have zero (nothing has been
    requested yet), one (a single provider-wide agreement), or several
    (one per county, e.g. fl_realauction's Alachua and Volusia records
    below) authorization records."""
    return tuple(r for r in PROVIDER_AUTHORIZATIONS.values() if r.source_id == source_id)


def authorization_for_scope(source_id: str, county: str | None) -> ProviderAuthorization | None:
    """The single authorization record matching source_id AND county
    EXACTLY (None matches only a provider-level/statewide record, never a
    county-specific one, and a specific county matches only that same
    county's own record, never a different county's or the provider-level
    one). This exactness is what makes 'a county-specific authorization
    does not automatically authorize another county' and 'a provider
    authorization does not automatically authorize every deployment'
    (Phase 34A Step 17's two required test scenarios) true by construction
    rather than by convention: this lookup never widens or substitutes a
    different scope than the one asked for. Returns None - fail-closed,
    exactly like registry.get_source() does for an unknown source_id - if
    no record matches both fields."""
    matches = [r for r in authorizations_for_source(source_id) if r.county == county]
    if len(matches) > 1:
        # Defensive: the registry below never actually creates two records
        # for the same (source_id, county) pair, but if it ever did, fail
        # closed rather than picking one arbitrarily.
        return None
    return matches[0] if matches else None


def check_authorized_use(
    source_id: str, use: str, *, county: str | None = None, as_of: str | None = None
) -> UseDecision:
    """The combined decision Phase 34A Step 12 requires: BOTH the existing
    ingestion gate (registry.py's legal_status, via gate.check_ingestion_gate
    - completely unmodified by this phase, per Step 12's 'do not weaken the
    existing gate') AND a real, matching, currently-effective authorization
    record's per-use flag must say yes. Fails closed at every step:

      1. Unknown `use` name -> raises ValueError immediately (a caller
         typo must never silently resolve to "denied looks the same as
         allowed", so this is the one place this module raises rather
         than returning a decision).
      2. Ingestion gate denies (source_id unknown, or legal_status not in
         INGESTION_ALLOWED_STATUSES) -> denied, full stop; no
         authorization record is even consulted, because Step 12 is
         explicit that the EXISTING gate must not be weakened - this new,
         narrower gate can only add restrictions, never lift the
         old one's.
      3. No authorization record exists for (source_id, county) exactly
         -> denied ("REQUEST_NOT_STARTED"-equivalent - Step 6's "do not
         assume that asking for permission grants permission" extends
         naturally to "not having asked yet" too).
      4. The matching record's effective_authorization_status() (which
         already folds in EXPIRED/REVOKED - Step 13) is not one of
         AUTHORIZATION_GRANTED_STATUSES -> denied.
      5. The matching record's scope.<use>.authorized is not True ->
         denied - an APPROVED_WITH_RESTRICTIONS record authorizes only
         the specific dimensions it says it does, never every dimension
         by default.
      6. Otherwise -> allowed.
    """
    if use not in ALL_USE_DIMENSIONS:
        raise ValueError(f"'{use}' is not a recognized authorization-scope dimension. Valid: {sorted(ALL_USE_DIMENSIONS)}")

    gate_decision = check_ingestion_gate(source_id)
    if not gate_decision.allowed:
        return UseDecision(
            source_id=source_id,
            use=use,
            county=county,
            allowed=False,
            ingestion_gate_allowed=False,
            authorization_status=None,
            reason=(
                f"ingestion gate denies '{source_id}' ({gate_decision.reason}) - the existing gate is never "
                "weakened by this module, so no authorization record is even consulted"
            ),
        )

    record = authorization_for_scope(source_id, county)
    if record is None:
        return UseDecision(
            source_id=source_id,
            use=use,
            county=county,
            allowed=False,
            ingestion_gate_allowed=True,
            authorization_status=None,
            reason=(
                f"no authorization record exists for source_id={source_id!r}, county={county!r} - "
                "missing != approved, same fail-closed guarantee as the ingestion gate itself"
            ),
        )

    effective_status = effective_authorization_status(record)
    if effective_status not in AUTHORIZATION_GRANTED_STATUSES:
        return UseDecision(
            source_id=source_id,
            use=use,
            county=county,
            allowed=False,
            ingestion_gate_allowed=True,
            authorization_status=effective_status,
            reason=(
                f"authorization_id={record.authorization_id!r} is {effective_status.value} - "
                "CONTACTED/RECEIVED/UNDER_REVIEW/etc. never imply APPROVED"
            ),
        )

    permission = record.scope.get(use)
    if not permission.authorized:
        return UseDecision(
            source_id=source_id,
            use=use,
            county=county,
            allowed=False,
            ingestion_gate_allowed=True,
            authorization_status=effective_status,
            reason=(
                f"authorization_id={record.authorization_id!r} is {effective_status.value} but does not "
                f"authorize '{use}' specifically (requested={permission.requested}, authorized=False)"
            ),
        )

    return UseDecision(
        source_id=source_id,
        use=use,
        county=county,
        allowed=True,
        ingestion_gate_allowed=True,
        authorization_status=effective_status,
        reason=f"authorization_id={record.authorization_id!r} is {effective_status.value} and authorizes '{use}'",
    )


# ---------------------------------------------------------------------------
# Phase 34B: production-boundary wrappers.
#
# These three functions are the actual "narrowest reliable shared
# ingestion/sync boundary" Phase 34B Section 1/3 asks this phase to find -
# each one composes the EXISTING, unmodified Phase 10A/11 gate function
# with this module's new per-use authorization check, with one governing
# design rule that makes wiring them into real production code safe:
#
#   A source_id with ZERO ProviderAuthorization records anywhere (today:
#   every TX source - tx_lgbs, tx_realauction, tx_hctax, etc. - and every
#   FL source other than fl_realauction/fl_lienhub_certificates) has NOT
#   opted into the Phase 34A/34B framework, and these functions are a
#   byte-for-byte no-op for it - the exact same decision the existing
#   gate.py function alone would have made. A source_id that HAS at least
#   one authorization record on file (today: fl_realauction,
#   fl_lienhub_certificates) is held to the stricter standard: the
#   specific use must be affirmatively authorized for the specific county
#   asked about, or the row/use is denied.
#
# This is what "changing normal behavior for currently authorized sources"
# (Section 1) is prohibited from doing, and what these functions are
# built to structurally guarantee they never do - see
# test_new_customer_output_check_is_a_no_op_for_sources_with_no_authorization_records
# in tests/python/test_provider_authorization.py for the regression test
# that proves it against the two real production TX sources.
# ---------------------------------------------------------------------------


def authorized_for_ingestion(source_id: str, *, county: str | None = None) -> bool:
    """The 'raw acquisition' boundary (Section 3) - whether a harvester
    should be allowed to run for this source_id at all. Deliberately
    stays at check_ingestion_gate()'s existing, coarser question (is
    legal_status APPROVED/APPROVED_WITH_RESTRICTIONS) for a source that
    has not opted into the new framework - Section 3's own instruction
    not to "unnecessarily prohibit internal discovery/diagnostic activity"
    means raw acquisition is deliberately held to a lighter standard than
    customer-facing exposure below; a source can be legitimately harvested
    for internal/diagnostic purposes (e.g. building the county coverage
    matrices in claude/phase-33-source-compliance-audit.md) without yet
    having a full per-use commercial authorization on file. For a source
    that HAS entered the new framework, this still requires
    'automated_access' to be authorized for the given county specifically
    - so fl_realauction/fl_lienhub_certificates, once/if this function is
    ever actually wired into a harvester entry point, would correctly
    deny automated harvesting today."""
    if not authorizations_for_source(source_id):
        return check_ingestion_gate(source_id).allowed
    return check_authorized_use(source_id, "automated_access", county=county).allowed


def authorized_for_customer_output(row: dict, source_id: str, *, county: str | None = None) -> dict | None:
    """The 'customer-facing exposure' boundary (Section 4) - the row a
    customer would actually see (frontend card view, or CSV export, in
    this codebase's own architecture where the exported file and the
    displayed card come from the same `public.properties` row - see
    docs/data-licensing.md's own note that this app has no application
    server separate from that table). Returns the row exactly as
    gate.project_row_for_customer_output() would have (including its
    existing field-shape stripping for NO_RAW_HTML/NO_IMAGES/NO_DOCUMENTS
    restrictions - Section 7's source-vs-field distinction is already
    handled there, not reinvented here), or None if either that function
    or this module's own authorization check rejects it.
    See the module-level note above for why this is a verified no-op for
    any source_id with zero authorization records (today: every TX source)."""
    projected = project_row_for_customer_output(row, source_id)
    if projected is None:
        return None
    if not authorizations_for_source(source_id):
        return projected
    if not check_authorized_use(source_id, "customer_display", county=county).allowed:
        return None
    return projected


def authorized_for_api_export(row: dict, source_id: str, *, county: str | None = None) -> dict | None:
    """The 'export/API redistribution' boundary (Section 5/6) - stricter
    than authorized_for_customer_output() above (a row can be fine to
    display in-app but not fine to hand to the customer as a file or
    through an API - Section 6's explicit 'do not confuse customer_display
    with api_redistribution'). Checks BOTH 'customer_export' AND
    'api_redistribution' for a source that has entered the framework
    (this codebase's one real export today, the CSV download button in
    public/app.js, is customer_export; api_redistribution covers a
    future distinct API surface, per gate.project_row_for_api_export()'s
    own docstring) - a row must be authorized for whichever surface it is
    actually headed to, so the CALLER is expected to pass the one that
    matches its own context; this function checks both because neither
    surface exists as separate production code paths yet to disambiguate
    by call site, so it is deliberately conservative here (denies if
    EITHER is unauthorized) rather than picking one arbitrarily."""
    projected = project_row_for_api_export(row, source_id)
    if projected is None:
        return None
    if not authorizations_for_source(source_id):
        return projected
    export_decision = check_authorized_use(source_id, "customer_export", county=county)
    api_decision = check_authorized_use(source_id, "api_redistribution", county=county)
    if not (export_decision.allowed and api_decision.allowed):
        return None
    return projected


# ---------------------------------------------------------------------------
# Authorization records - transcribed from the actual agreements supplied
# this phase. Every AuthorizationDocument below is is_pending=True with
# document_location=None (Step 15: no file is actually in this repository -
# the terms were supplied as prose in the Phase 34A instructions, not as an
# uploaded file this repository can reference by path). Every
# `written_permission` below is False and every use-dimension is
# `authorized=False` - nothing supplied this phase constitutes, or is being
# represented as, an actual grant (Step 24's "WE FOUND IT != WE CAN...").
# ---------------------------------------------------------------------------

_LIENHUB_GRANT_STREET = ProviderAuthorization(
    authorization_id="fl_lienhub_certificates__provider__grant_street_group",
    source_id="fl_lienhub_certificates",
    provider="Grant Street Group",
    government_entity="Participating Florida Tax Collectors (per-county, the agreement's own stated other party)",
    state="FL",
    county=None,  # provider-wide User Agreement, not a per-county deployment record
    deployment_scope="provider",
    requested_by=None,
    request_date=None,
    contact_name=None,
    contact_email=None,
    request_status=AuthorizationStatus.REQUEST_NOT_STARTED,
    authorization_status=AuthorizationStatus.LEGAL_REVIEW_REQUIRED,
    document=AuthorizationDocument(
        document_name="LienHub User Agreement (Grant Street Group)",
        document_location=None,
        document_hash=None,
        effective_date=None,
        expiration_date=None,
        reviewer="Phase 34A repository implementation",
        review_date="2026-09-15",
        scope_summary=(
            "Transcribed from the terms summary supplied in the Phase 34A instructions, not from a file in "
            "this repository. Key terms: the agreement is between Grant Street Group and participating "
            "Florida Tax Collectors; LienHub information is proprietary; copying/saving/publishing/"
            "disseminating/distributing/disclosing/modifying/reselling/redistributing proprietary "
            "information is restricted except where expressly permitted; robots/spiders/similar automated "
            "devices to monitor or copy pages/content/information are EXPRESSLY PROHIBITED; software/devices "
            "interfering with the portal are prohibited; a narrow exception permits copying transaction "
            "evidence for internal recordkeeping under specified conditions; the agreement may be amended; "
            "Grant Street may suspend/revoke privileges; accuracy/completeness/timeliness is disclaimed."
        ),
        is_pending=True,
    ),
    agreement_url="https://lienhub.com/doc/terms",
    agreement_version=None,
    agreement_date=None,
    effective_date=None,
    expiration_date=None,
    review_due_date=None,
    scope=AuthorizationScope(
        automated_access=UsePermission(requested=False, authorized=False),
        commercial_use=UsePermission(requested=False, authorized=False),
        storage=UsePermission(requested=False, authorized=False),
        historical_storage=UsePermission(requested=False, authorized=False),
        normalization=UsePermission(requested=False, authorized=False),
        derived_data=UsePermission(requested=False, authorized=False),
        customer_display=UsePermission(requested=False, authorized=False),
        customer_export=UsePermission(requested=False, authorized=False),
        api_access=UsePermission(requested=False, authorized=False),
        api_redistribution=UsePermission(requested=False, authorized=False),
        image_use=UsePermission(requested=False, authorized=False),
        document_use=UsePermission(requested=False, authorized=False),
    ),
    attribution_required=None,
    rate_limit="No published rate limit found in the supplied terms; the automated-access prohibition itself is the controlling restriction (see technical_restrictions).",
    retention_requirement="Not addressed in the supplied terms beyond the narrow internal-recordkeeping exception for transaction evidence.",
    privacy_restrictions=None,
    technical_restrictions=(
        "Robots/spiders/similar automated devices to monitor or copy pages/content/information are EXPRESSLY "
        "PROHIBITED by the agreement as supplied. This project's own harvest_lienhub_certificates.ps1 is "
        "exactly such a device - see claude/phase-33-5-florida-production-source-rights-audit.md's independent "
        "finding that this same harvester's own commit history documents working around an observed WAF/"
        "bot-block, which is now corroborated by this agreement's own express prohibition."
    ),
    written_permission=False,
    reviewed_by="Phase 34A repository implementation",
    reviewed_at="2026-09-15",
    notes=(
        "This record does NOT establish that fl_lienhub_certificates' current automated harvesting is "
        "authorized - the opposite: the supplied agreement's own terms expressly prohibit the exact kind of "
        "automated access this project's harvester performs. authorization_status is LEGAL_REVIEW_REQUIRED, "
        "not DECLINED/BLOCKED, because this project has not sought or received an express written exception "
        "to that general prohibition (the agreement's own 'except where expressly permitted' carve-out) - "
        "that exception is exactly what docs/provider-authorization-requests.md's LienHub template exists to "
        "ask for. See docs/provider-authorization-status.md."
    ),
    terms_version=None,
    terms_hash=None,
    last_terms_check="2026-09-15",
    audit_log=(
        AuditLogEntry(
            event="created",
            who="Phase 34A repository implementation",
            when="2026-09-15",
            old_status=None,
            new_status=AuthorizationStatus.LEGAL_REVIEW_REQUIRED.value,
            reason=(
                "Transcribed from the LienHub User Agreement terms summary supplied in the Phase 34A "
                "instructions. The agreement's express prohibition on automated access means current "
                "automated commercial use is not authorized by this record."
            ),
            document_reference=None,
        ),
    ),
)

_REALAUCTION_ALACHUA = ProviderAuthorization(
    authorization_id="fl_realauction__county__alachua",
    source_id="fl_realauction",
    provider="RealAuction.com, LLC",
    government_entity="Alachua County Clerk of the Circuit Court (per the EULA's own stated sale process)",
    state="FL",
    county="Alachua",
    deployment_scope="county",
    requested_by=None,
    request_date=None,
    contact_name=None,
    contact_email=None,
    request_status=AuthorizationStatus.REQUEST_NOT_STARTED,
    authorization_status=AuthorizationStatus.LEGAL_REVIEW_REQUIRED,
    document=AuthorizationDocument(
        document_name="RealAuction End User License Agreement - Alachua County",
        document_location=None,
        document_hash=None,
        effective_date=None,
        expiration_date=None,
        reviewer="Phase 34A repository implementation",
        review_date="2026-09-15",
        scope_summary=(
            "Transcribed from the terms summary supplied in the Phase 34A instructions, not from a file in "
            "this repository. Key terms: the license is for accessing/using information for the purpose of "
            "purchasing or attempting to purchase property through Alachua County's sale process; "
            "information presented by RealAuction cannot be used, altered, sold, or distributed without "
            "RealAuction's express written consent; automated software/program/device access is prohibited "
            "without RealAuction's prior written approval; robots/spiders/similar devices to monitor or copy "
            "pages/content/information are prohibited; automated site processes and mouse-click automation "
            "are restricted; certain registration/sales records may constitute public records under Florida "
            "law; terms may be amended."
        ),
        is_pending=True,
    ),
    agreement_url=None,
    agreement_version=None,
    agreement_date=None,
    effective_date=None,
    expiration_date=None,
    review_due_date=None,
    scope=AuthorizationScope(
        automated_access=UsePermission(requested=False, authorized=False),
        commercial_use=UsePermission(requested=False, authorized=False),
        storage=UsePermission(requested=False, authorized=False),
        historical_storage=UsePermission(requested=False, authorized=False),
        normalization=UsePermission(requested=False, authorized=False),
        derived_data=UsePermission(requested=False, authorized=False),
        customer_display=UsePermission(requested=False, authorized=False),
        customer_export=UsePermission(requested=False, authorized=False),
        api_access=UsePermission(requested=False, authorized=False),
        api_redistribution=UsePermission(requested=False, authorized=False),
        image_use=UsePermission(requested=False, authorized=False),
        document_use=UsePermission(requested=False, authorized=False),
    ),
    attribution_required=None,
    rate_limit="No published rate limit found in the supplied terms; the prior-written-approval requirement for automated access itself is the controlling restriction.",
    retention_requirement=None,
    privacy_restrictions=None,
    technical_restrictions=(
        "Automated software/program/device access, and robots/spiders/similar devices to monitor or copy "
        "pages/content/information, are prohibited absent RealAuction's prior written approval, per the "
        "EULA as supplied. This project's own harvest_all_counties.ps1 is exactly such a device. See "
        "claude/phase-33-5-florida-production-source-rights-audit.md's independent robots.txt-disallow "
        "finding on this same vendor's Florida hosts, now corroborated by this EULA's own express term."
    ),
    written_permission=False,
    reviewed_by="Phase 34A repository implementation",
    reviewed_at="2026-09-15",
    notes=(
        "Scoped to Alachua County ONLY (Phase 34A Step 4's provider/platform/county hierarchy) - this record "
        "does not authorize, and must never be read as authorizing, any other RealAuction-platform county "
        "(there are ~45 others under fl_realauction's single source_id). See "
        "test_realauction_alachua_authorization_does_not_extend_to_other_counties in "
        "tests/python/test_provider_authorization.py for the structural guarantee. The license as supplied "
        "is for participating in this county's own sale process, not for automated commercial data "
        "collection - authorization_status is LEGAL_REVIEW_REQUIRED because that distinction has not been "
        "resolved by an actual written exception. See docs/provider-authorization-status.md."
    ),
    terms_version=None,
    terms_hash=None,
    last_terms_check="2026-09-15",
    audit_log=(
        AuditLogEntry(
            event="created",
            who="Phase 34A repository implementation",
            when="2026-09-15",
            old_status=None,
            new_status=AuthorizationStatus.LEGAL_REVIEW_REQUIRED.value,
            reason=(
                "Transcribed from the RealAuction Alachua County EULA terms summary supplied in the Phase "
                "34A instructions. The EULA's own automated-access prohibition means current automated "
                "commercial use is not authorized by this record."
            ),
            document_reference=None,
        ),
    ),
)

_REALAUCTION_VOLUSIA = ProviderAuthorization(
    authorization_id="fl_realauction__county__volusia",
    source_id="fl_realauction",
    provider="RealAuction.com, LLC",
    government_entity="Volusia County Clerk of the Circuit Court and Comptroller (per the EULA's own stated sale process)",
    state="FL",
    county="Volusia",
    deployment_scope="county",
    requested_by=None,
    request_date=None,
    contact_name=None,
    contact_email=None,
    request_status=AuthorizationStatus.REQUEST_NOT_STARTED,
    authorization_status=AuthorizationStatus.LEGAL_REVIEW_REQUIRED,
    document=AuthorizationDocument(
        document_name="RealAuction End User License Agreement - Volusia County",
        document_location=None,
        document_hash=None,
        effective_date=None,
        expiration_date=None,
        reviewer="Phase 34A repository implementation",
        review_date="2026-09-15",
        scope_summary=(
            "Transcribed from the terms summary supplied in the Phase 34A instructions, not from a file in "
            "this repository. Same substantive terms as the Alachua County record above (both EULAs were "
            "described identically in the Phase 34A instructions): license for accessing/using information "
            "to purchase or attempt to purchase property through Volusia County's sale process; no use/"
            "alteration/sale/distribution without RealAuction's express written consent; automated access/"
            "robots/spiders prohibited absent prior written approval; certain records may be public records; "
            "terms may be amended."
        ),
        is_pending=True,
    ),
    agreement_url=None,
    agreement_version=None,
    agreement_date=None,
    effective_date=None,
    expiration_date=None,
    review_due_date=None,
    scope=AuthorizationScope(
        automated_access=UsePermission(requested=False, authorized=False),
        commercial_use=UsePermission(requested=False, authorized=False),
        storage=UsePermission(requested=False, authorized=False),
        historical_storage=UsePermission(requested=False, authorized=False),
        normalization=UsePermission(requested=False, authorized=False),
        derived_data=UsePermission(requested=False, authorized=False),
        customer_display=UsePermission(requested=False, authorized=False),
        customer_export=UsePermission(requested=False, authorized=False),
        api_access=UsePermission(requested=False, authorized=False),
        api_redistribution=UsePermission(requested=False, authorized=False),
        image_use=UsePermission(requested=False, authorized=False),
        document_use=UsePermission(requested=False, authorized=False),
    ),
    attribution_required=None,
    rate_limit="No published rate limit found in the supplied terms; the prior-written-approval requirement for automated access itself is the controlling restriction.",
    retention_requirement=None,
    privacy_restrictions=None,
    technical_restrictions=(
        "Automated software/program/device access, and robots/spiders/similar devices to monitor or copy "
        "pages/content/information, are prohibited absent RealAuction's prior written approval, per the "
        "EULA as supplied. This project's own harvest_all_counties.ps1 is exactly such a device."
    ),
    written_permission=False,
    reviewed_by="Phase 34A repository implementation",
    reviewed_at="2026-09-15",
    notes=(
        "Scoped to Volusia County ONLY - does not authorize, and must never be read as authorizing, any "
        "other RealAuction-platform county. Volusia is also independently notable for a separate, "
        "PDF-disclaimer-gate finding on its LAFT source (fl_laft_pdfs) documented in "
        "claude/phase-33-5-florida-production-source-rights-audit.md - unrelated to this RealAuction record "
        "(different source_id entirely) but the same county, worth not conflating."
    ),
    terms_version=None,
    terms_hash=None,
    last_terms_check="2026-09-15",
    audit_log=(
        AuditLogEntry(
            event="created",
            who="Phase 34A repository implementation",
            when="2026-09-15",
            old_status=None,
            new_status=AuthorizationStatus.LEGAL_REVIEW_REQUIRED.value,
            reason=(
                "Transcribed from the RealAuction Volusia County EULA terms summary supplied in the Phase "
                "34A instructions. The EULA's own automated-access prohibition means current automated "
                "commercial use is not authorized by this record."
            ),
            document_reference=None,
        ),
    ),
)


PROVIDER_AUTHORIZATIONS: dict[str, ProviderAuthorization] = {
    r.authorization_id: r
    for r in (
        _LIENHUB_GRANT_STREET,
        _REALAUCTION_ALACHUA,
        _REALAUCTION_VOLUSIA,
    )
}
