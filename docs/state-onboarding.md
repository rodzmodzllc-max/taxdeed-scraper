# State / county source onboarding

**Status:** Phase 35 (County Source-of-Truth Catalog), 2026-09-15. Generalizes `docs/source-registry.md`'s existing "Future source onboarding process" (written against the single Harris County/`tx_hctax` case) into a repeatable pipeline that now has to serve two states and hundreds of counties, without collapsing the careful discovery-vs-authorization-vs-ingestion distinctions Phases 10A/34A/34B/35 each built.

## The stages, and which phase's data structure owns each one

```
1. CATALOG        -> harvesters/governance/source_catalog.py (Phase 35)
                      "what sources exist for this county, in this category,
                      and what do we currently know about them"
                      Most entries stop here. No automation, no ingestion.

1.5 TERMS REVIEW   -> data/phase36_terms_review.csv, loaded via
                      harvesters/governance/source_catalog.py::load_terms_review()
                      (Phase 36)
                      "for this specific catalog entry, what did we actually
                      find when we looked at its terms of use / license /
                      access controls, and what is the evidence" - narrower
                      than the full step-2 rights reconnaissance below (it is
                      research, not yet a registry decision), but the first
                      point where "we found the right website" (stage 1) is
                      explicitly distinguished from "we know what it
                      permits." A row here is never better than
                      LEGAL_REVIEW_REQUIRED - it cannot itself approve a
                      source, only escalate an unresolved finding honestly
                      instead of leaving it as a bare, ambiguous UNKNOWN.

2. REGISTRY        -> harvesters/governance/registry.py (Phase 10A)
                      "this specific source_id is one this project actually
                      harvests, or is actively considering harvesting, in
                      Python code" - a much smaller set than the catalog.
                      legal_status starts at DISCOVERED/UNDER_REVIEW/
                      LEGAL_REVIEW_REQUIRED here, never APPROVED on arrival.

3. AUTHORIZATION   -> harvesters/governance/authorization.py (Phase 34A/34B)
                      "for this specific source_id, at this specific
                      provider/county deployment, has an actual documented
                      authorization been recorded covering this specific
                      use" - a per-use, per-scope refinement layered on top
                      of (2), never a replacement for it.

4. INGESTION       -> harvesters/texas_harvester.py + scripts/sync-*.py,
                      gated by check_ingestion_gate() / check_authorized_use()
                      "this source_id's data actually flows into
                      public.properties today" - the only stage where a
                      real harvester exists and real customer-facing rows
                      are produced.
```

A catalog entry moving from stage 1 to stage 2 is a deliberate, human-reviewed decision — not something that happens by a source merely appearing in `data/fl_county_coverage_matrix.csv`/`data/tx_county_coverage_matrix.csv`, or by acquiring a stage-1.5 terms-review row. As of Phase 36, 27 catalog-adjacent sources have a stage-1.5 terms-review finding; none of them has moved to stage 2 as a result — every one of Phase 35's catalog rows not already in `SOURCE_REGISTRY` still sits at stage 1 (or stage 1.5, for the 27 reviewed), never stage 2, until a human deliberately runs the six-step process below.

## The six-step promotion process (from stage 1 to a working, authorized ingestion path)

Unchanged in substance from `docs/source-registry.md`'s original Harris County template, restated here so it reads as a general process rather than a single case study:

1. **Technical reconnaissance** — confirm the source is real, map its data flow, inventory its fields, test identity/uniqueness, test pagination/completeness, assess technical stability. Produces a technical-readiness verdict, independent of legal status. (Template: `claude/harris-hctax-implementation-readiness.md`.)
2. **Rights reconnaissance** — Terms of Use review (automated access / storage / commercial use / customer display / API-export / historical retention / images-documents, each evaluated separately), robots.txt review (kept separate from legal conclusions), a rights matrix by asset, a per-activity commercial-use evaluation, a derived-data analysis. Produces a `LEGAL_REVIEW_REQUIRED` classification by default — never `APPROVED` from reconnaissance alone. (Template: `claude/harris-hctax-legal-commercial-gate.md`.)
3. **A `SourceRecord` is added to `SOURCE_REGISTRY`** (stage 1 → stage 2) with `legal_status=LEGAL_REVIEW_REQUIRED` (or `DISCOVERED`/`UNDER_REVIEW` for an earlier-stage source) and every field populated from steps 1–2's findings, `doc_refs` citing the actual documents.
4. **A `ProviderAuthorization` record is added to `PROVIDER_AUTHORIZATIONS`** (stage 2 → stage 3) once an actual provider/county-scoped agreement's terms are on file — even if, as with LienHub and RealAuction Alachua/Volusia, the record's own conclusion is still `LEGAL_REVIEW_REQUIRED`. This step does not require step 5 below to have happened; the two evolve independently.
5. **If pursuing clarification from the source itself**, prepare draft outbound communications and a response decision framework *before* contact is made, for human review and human sending — never send anything automatically. (Template: `claude/harris-hctax-rights-resolution-package.md`, `docs/provider-authorization-requests.md`.)
6. **Only once an actual resolution exists** (a counsel opinion, a source's written response, or a business decision to accept a defined risk) does `legal_status`/`authorization_status` change to `APPROVED` or `APPROVED_WITH_RESTRICTIONS` — and whichever restrictions the resolution implies get encoded explicitly, not left implicit. **Only then** does a harvester implementation phase begin (stage 3 → stage 4) — and the ingestion gate means a harvester written *before* this step completes still cannot actually ingest anything, even if someone jumps ahead and writes the code.

## What Phase 35 specifically added at stage 1

- A confirmed, verified, deterministic URL pattern for the Texas Comptroller's per-county directory page (`https://comptroller.texas.gov/taxes/property-tax/county-directory/<county-lowercase-no-spaces>.php`), generated for all 254 Texas counties and individually fetched/verified for 42 of them (every county already referenced by this project's existing RealAuction/LGBS/GovEase/MVBA data).
- Individually verified Property Appraiser websites for the 12 highest-population Florida counties.
- Confirmation that the Florida DOR's `LocalOfficials.aspx` directory and the Texas Comptroller's county-directory index both exist and cover all counties in their respective states, but as interactive dropdown/lookup interfaces rather than a single bulk-listable page — meaning per-county extraction for the remaining 55 Florida and 212 Texas counties is real, bounded, future work, not an unknown quantity.

None of this moves any source from stage 1 to stage 2. See `claude/phase-35-county-source-of-truth-catalog.md` for the full findings and `docs/data-completeness.md` for the exact, current completeness numbers.

## What Phase 36 specifically added at stage 1.5

- A 27-row terms-review ledger (`data/phase36_terms_review.csv`) covering the highest-priority sources from Phases 33–35: the LienHub and RealAuction provider/platform level, 4 individual RealAuction county deployments (Alachua, Volusia, Miami-Dade, Brevard in Florida; Travis in Texas), 12 individually reviewed Florida Property Appraiser sites, 2 statewide resources per state (Florida DOR's Data Portal; Texas's Comptroller Property Tax Reports and TNRIS/StratMap GIS layer), and 6 Texas Appraisal Districts.
- A structural distinction, enforced by tests, between a source **actually reviewed this phase and found inconclusive** (escalates to `LEGAL_REVIEW_REQUIRED`, per Phase 36 Section 11's rule that an unresolved commercial-use/automated-access/customer-display/redistribution finding is never left as a bare `UNKNOWN`) and a source **not reviewable at all this phase** (a JavaScript portal with no extractable content — stays honestly at `DISCOVERED`, since no review actually happened).
- Confirmation that the `SOURCE_REGISTRY`-level `APPROVED` status of `fl_realauction`/`fl_laft_pdfs`/`fl_lienhub_certificates` (grandfathered, Phase 10A) was **not** touched, upgraded, or reinterpreted by this new evidence — Phase 36 is read-only research, same as Phase 35, and the same six-step promotion process below still governs whether any of this evidence ever becomes a registry change.

See `claude/phase-36-source-terms-commercial-verification.md` for the full source-by-source findings and evidence references.
