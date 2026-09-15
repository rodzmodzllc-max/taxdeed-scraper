"""Field/data provenance and classification - Phase 10A Step 5 and Step 6.

Models the pipeline Phase 10A Step 5 specifies:

    SOURCE -> RAW -> NORMALIZED -> ENRICHED -> DERIVED -> CUSTOMER -> EXPORT/API

A `Provenance` record is attached to a value (a single field, or - as used
by harvesters/texas_harvester.py's main(), see that file's own comment - a
whole harvested row, since this repo's rows are currently harvested and
transformed as a unit, not field-by-field) and moved forward through the
pipeline with `advance()`. The one invariant this module enforces in code,
not just in a comment: **`advance()` and `derive()` can only ADD
restrictions, never remove them** - a restricted source field cannot
accidentally become unrestricted just because it was normalized, enriched,
or combined with another field (Phase 10A Step 6's explicit requirement).

This module has no knowledge of TexasSaleRow, Supabase, or any specific
harvester - it is intentionally generic so a future Florida/other-state
governance integration could reuse it unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from .restrictions import Restriction


class PipelineStage(str, Enum):
    SOURCE = "SOURCE"
    RAW = "RAW"
    NORMALIZED = "NORMALIZED"
    ENRICHED = "ENRICHED"
    DERIVED = "DERIVED"
    CUSTOMER = "CUSTOMER"
    EXPORT_API = "EXPORT_API"


# The order values are expected to move through the pipeline in - used only
# by _assert_forward_or_same() below as a sanity check against accidentally
# moving a value BACKWARD (e.g. calling advance(stage=RAW) on something
# already ENRICHED), which would be a programming error in a future caller,
# not a legitimate transformation.
_STAGE_ORDER = {
    PipelineStage.SOURCE: 0,
    PipelineStage.RAW: 1,
    PipelineStage.NORMALIZED: 2,
    PipelineStage.ENRICHED: 3,
    PipelineStage.DERIVED: 4,
    PipelineStage.CUSTOMER: 5,
    PipelineStage.EXPORT_API: 6,
}


class FieldClassification(str, Enum):
    PUBLIC = "PUBLIC"
    PUBLIC_RESTRICTED = "PUBLIC_RESTRICTED"
    PERSONAL = "PERSONAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    SENSITIVE = "SENSITIVE"
    LICENSE_RESTRICTED = "LICENSE_RESTRICTED"
    DERIVED = "DERIVED"


@dataclass(frozen=True)
class Provenance:
    """Lineage for one field or row.

    - `source_id` / `source_url` / `source_field`: where this value
      ultimately came from (for a DERIVED value with multiple parents,
      these describe the PRIMARY/first parent for convenience - use
      `origin_source_ids()` below to get the full set across all parents).
    - `retrieved_at`: ISO 8601 timestamp of the original retrieval - never
      updated by advance()/derive(), so it always answers "when was the
      underlying fact actually fetched," independent of how many pipeline
      stages it has since moved through.
    - `is_source_provided`: True for a value that came directly from the
      source (RAW/NORMALIZED/ENRICHED stages, most of the time); False for
      a value this project computed itself (DERIVED stage, e.g. a yield
      calculation) - this distinction is what Phase 9.5's Section 10
      ("derived data") flagged as a genuinely open legal question this
      project does not resolve on its own; this field exists so the
      question stays answerable in code, not so this module answers it.
    - `restrictions`: the UNION of every restriction from the originating
      source(s) - see `advance()`/`derive()` for the enforcement of "only
      grows, never shrinks."
    - `derived_from`: for a DERIVED-stage value, the parent Provenance
      record(s) it was computed from. Empty for anything that is not
      itself derived from other tracked values.
    """

    source_id: str
    source_url: str
    source_field: str | None
    retrieved_at: str
    stage: PipelineStage
    classification: FieldClassification
    restrictions: tuple[Restriction, ...] = field(default_factory=tuple)
    is_source_provided: bool = True
    derived_from: tuple["Provenance", ...] = field(default_factory=tuple)


def _assert_forward_or_same(old_stage: PipelineStage, new_stage: PipelineStage) -> None:
    if _STAGE_ORDER[new_stage] < _STAGE_ORDER[old_stage]:
        raise ValueError(
            f"provenance cannot move backward through the pipeline: {old_stage.value} -> {new_stage.value}"
        )


def advance(
    provenance: Provenance,
    *,
    stage: PipelineStage,
    classification: FieldClassification | None = None,
    additional_restrictions: tuple[Restriction, ...] = (),
) -> Provenance:
    """Move a value forward one or more pipeline stages (e.g. RAW ->
    NORMALIZED, or NORMALIZED -> ENRICHED). `source_id`/`source_url`/
    `source_field`/`retrieved_at`/`is_source_provided`/`derived_from` are
    always carried forward unchanged - only `stage`, optionally
    `classification`, and the restriction set may change, and the
    restriction set may only GROW (existing restrictions are always kept;
    `additional_restrictions` is unioned in, never used to replace)."""
    _assert_forward_or_same(provenance.stage, stage)
    merged_restrictions = tuple(sorted(set(provenance.restrictions) | set(additional_restrictions), key=lambda r: r.value))
    return replace(
        provenance,
        stage=stage,
        classification=classification if classification is not None else provenance.classification,
        restrictions=merged_restrictions,
    )


def derive(
    parents: list[Provenance],
    *,
    source_field: str | None = None,
    classification: FieldClassification = FieldClassification.DERIVED,
) -> Provenance:
    """Build a DERIVED-stage Provenance for a value computed FROM one or
    more parent values (e.g. a bid-to-value ratio computed from a
    min_bid field and a cad_market_value field, potentially from two
    DIFFERENT sources once cross-source enrichment is in play).

    The union of every parent's restrictions carries forward onto the
    derived value - Phase 9.5 Section 10 flagged this exact question
    ("is a derived metric the source's data or this project's own
    analysis, for rights purposes?") as genuinely open and NOT resolved by
    this project; this function's behavior encodes the conservative answer
    (a restriction is never laundered away by deriving a new value from
    restricted data), consistent with every other "silence/ambiguity is
    never treated as permission" decision in this project's reconnaissance
    docs.
    """
    if not parents:
        raise ValueError("derive() requires at least one parent Provenance")

    merged_restrictions = tuple(
        sorted({r for p in parents for r in p.restrictions}, key=lambda r: r.value)
    )
    primary = parents[0]
    latest_retrieval = max(p.retrieved_at for p in parents)

    return Provenance(
        source_id=primary.source_id,
        source_url=primary.source_url,
        source_field=source_field,
        retrieved_at=latest_retrieval,
        stage=PipelineStage.DERIVED,
        classification=classification,
        restrictions=merged_restrictions,
        is_source_provided=False,
        derived_from=tuple(parents),
    )


def origin_source_ids(provenance: Provenance) -> frozenset[str]:
    """Walk `derived_from` recursively and return every originating
    source_id a value's lineage ultimately traces back to. For a
    non-derived value this is just `{provenance.source_id}`; for a value
    derived from two different sources, both source_ids are returned -
    this is how a derived field "retains lineage to its originating
    source(s)" (Phase 10A Step 12, test 10) in a way that's actually
    checkable rather than asserted."""
    if not provenance.derived_from:
        return frozenset({provenance.source_id})
    ids: set[str] = set()
    for parent in provenance.derived_from:
        ids |= origin_source_ids(parent)
    return frozenset(ids)
