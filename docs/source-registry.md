# Source registry

**Status:** Phase 10A (Commercial Source Governance Infrastructure), 2026-09-14. First formal source registry this project has had — every prior reconnaissance phase (Phase 1 through 9.6) recorded a source's status in its own `claude/*.md` document in the "tax florida app" claude.ai Project, described explicitly in several of those docs as "the de facto registry" by convention, not by any structured/queryable data. Those documents remain the detailed evidence trail and are not superseded by this page — this page is the first place that evidence is also represented as data a program can check.

## Where the registry actually lives

`harvesters/governance/registry.py` — a plain Python module, not a database table. `SOURCE_REGISTRY: dict[str, SourceRecord]`, keyed by `source_id` (the same string already used as `harvester_source` on every `TexasSaleRow`, e.g. `"tx_lgbs"`).

This was a deliberate choice, not an oversight: Phase 10A Step 15 (Migration Safety) forbids executing a production database migration in this phase, and a real registry table would need one (see [Migration considerations](#migration-considerations-not-executed) below). A Python module gets the actual behavior — a harvester or sync script can `import` it and get a real answer — without touching Supabase at all. If a future phase wants a queryable/admin-editable registry, that's a genuine, separate schema decision, documented but not made here.

## Fields on every `SourceRecord`

Every field from Phase 10A Step 2's list has a slot — none renamed, none dropped:

`source_id`, `source_name`, `state`, `jurisdiction`, `source_url`, `source_type`, `official_or_vendor`, `access_method`, `automation_status`, `legal_status`, `commercial_use_status`, `storage_status`, `customer_display_status`, `redistribution_status`, `api_export_status`, `historical_retention_status`, `document_image_rights_status`, `attribution_required`, `rate_limit`, `robots_status`, `terms_status`, `review_date`, `reviewer`, `notes`, `restrictions`, `source_version`, `change_state`, plus `doc_refs` (the `claude/*.md` documents this entry transcribes — every entry cites at least one, except the three grandfathered Florida entries, which honestly cite none — see [Approval states](#approval-states)).

The seven `*_status` fields (`commercial_use_status` through `document_image_rights_status`) are free text, not a second enum. Phase 9.5's own vocabulary for Harris ("NO RESTRICTION FOUND; NO PERMISSION FOUND") doesn't compress cleanly into a 6-value enum without losing the actual finding — `legal_status` (the `SourceStatus` enum) is what the ingestion gate mechanically checks; the free-text fields are the preserved "why."

## Approval states

```
DISCOVERED
UNDER_REVIEW
APPROVED
APPROVED_WITH_RESTRICTIONS
LEGAL_REVIEW_REQUIRED
BLOCKED
DISABLED
TERMS_CHANGED
```

Only `APPROVED` and `APPROVED_WITH_RESTRICTIONS` let the ingestion gate (`harvesters/governance/gate.py`) proceed — see `docs/data-licensing.md` for the full enforcement model. A source can move backward too (e.g. `APPROVED` → `TERMS_CHANGED` if a vendor changes terms after approval); the model doesn't enforce a strict linear transition.

## Current registry contents (as of 2026-09-14)

| source_id | state | legal_status | notes |
|---|---|---|---|
| `tx_lgbs` | TX | `APPROVED` | Shipped 2026-09-09, production-verified 2026-09-14. Registered APPROVED to reflect existing, already-shipped production status — no formal Phase-8/9.5-style rights document exists for this vendor specifically (flagged below, not a block). |
| `tx_realauction` | TX | `APPROVED` | Same shape as `tx_lgbs` — shipped and production-verified 2026-09-14. |
| `tx_hctax` (Harris County, hctax.net) | TX | `LEGAL_REVIEW_REQUIRED` | **Intentional — do not upgrade or downgrade based on interpretation** (Phase 10A Step 10's explicit instruction). Twelve open rights questions recorded in `claude/harris-hctax-rights-resolution-package.md`; none sent to the county as of this entry. No `harvest_hctax()` exists anywhere in this codebase. |
| `tx_pbfcm` | TX | `BLOCKED` | Explicit anti-reproduction/redistribution clause in `disclosure.html` — see `claude/pbfcm-source-reconnaissance-blocked.md`. |
| `tx_mvba` | TX | `BLOCKED` | See `claude/mvba-source-reconnaissance-blocked.md`. |
| `tx_ctsa` | TX | `BLOCKED` | Paywall + anti-competitive-use clause — see `claude/ctsa-source-reconnaissance.md`. |
| `tx_govease` | TX | `BLOCKED` | Blanket `robots.txt: Disallow: /`, no locatable Terms of Use — see `claude/govease-source-onboarding-blocked.md`. |
| `fl_realauction` | FL | `APPROVED` | **Grandfathered** — long-standing production source predating this governance framework. See [Grandfathered Florida entries](#grandfathered-florida-entries). |
| `fl_laft_pdfs` | FL | `APPROVED` | Grandfathered, same caveat. |
| `fl_lienhub_certificates` | FL | `APPROVED` | Grandfathered, same caveat. |

Call `harvesters.governance.registry.all_sources()` (optionally `all_sources(state="TX")`) for the live, current list rather than trusting this table to stay perfectly in sync with the code — this page is documentation, `registry.py` is the source of truth.

## Grandfathered Florida entries

`fl_realauction`, `fl_laft_pdfs`, and `fl_lienhub_certificates` are registered `APPROVED` to prove the registry is genuinely state-agnostic (Phase 10A Step 2), not because a Phase-8/9.5-style rights audit was ever performed for Florida's sources. Their `notes` field says this explicitly and their `doc_refs` is honestly empty. This is not a request to re-review Florida — Florida's harvesters are PowerShell scripts that don't import this Python package at all (see `docs/commercial-data-inventory.md`'s regression section), so nothing about Florida's actual behavior depends on what this registry says. It's flagged here as a backfill-review candidate for whoever next has bandwidth for a Florida-focused rights pass, not as an open risk to production.

## Migration considerations (not executed)

If a future phase wants the registry to live in Supabase instead of (or in addition to) this Python module — for example, to let a non-engineer update a source's status from an admin panel — it would need a new table, something like:

```sql
create table if not exists public.source_registry (
  source_id text primary key,
  source_name text not null,
  state text not null,
  jurisdiction text not null,
  source_url text not null,
  source_type text not null,
  official_or_vendor text not null,
  access_method text not null,
  automation_status text not null,
  legal_status text not null,  -- check constraint against the 8 SourceStatus values
  commercial_use_status text not null,
  storage_status text not null,
  customer_display_status text not null,
  redistribution_status text not null,
  api_export_status text not null,
  historical_retention_status text not null,
  document_image_rights_status text not null,
  attribution_required boolean not null default false,
  rate_limit text,
  robots_status text not null,
  terms_status text not null,
  review_date date not null,
  reviewer text not null,
  notes text,
  restrictions text[] not null default '{}',
  source_version text not null default '1',
  change_state text not null default 'stable',
  doc_refs text[] not null default '{}',
  updated_at timestamptz not null default now()
);
```

**This was not created or executed in Phase 10A**, per Step 15's explicit instruction — identified here, not run. Dependencies before it could be: (1) a decision on whether `harvesters/governance/registry.py`'s Python dict becomes a cache of this table or is retired entirely in favor of it; (2) RLS design (read access for the app's admin panel, write access restricted to admins — following this project's existing `is_approved()`/`is_admin` pattern from `schema-v6-approvals.sql`); (3) a migration-runner decision, since this project's own `CLAUDE.md` documents that browser-automation tooling cannot type raw DDL into the Supabase SQL Editor — the same constraint every other migration in this repo (`002`/`003`/`004`, `schema-v4` through `v9`) has had to route around by having a human run it directly. Rollback consideration: purely additive (a new table), so rollback is a straightforward `drop table if exists public.source_registry;` with no risk to `properties` or any other existing table.

## The catalog vs. the registry (Phase 35)

Phase 35 (County Source-of-Truth Catalog) built a second, deliberately separate data set: `harvesters/governance/source_catalog.py`, backed by `data/fl_county_coverage_matrix.csv` (67 rows) and `data/tx_county_coverage_matrix.csv` (254 rows). **This is not a second registry and does not compete with `SOURCE_REGISTRY` above.** The catalog answers "what sources exist for county X, and what do we currently know about each one" at the *discovery/classification* stage — most of its rows will never become a `SourceRecord` here. A catalog entry is promoted into this registry only through the same deliberate, human-reviewed process `docs/state-onboarding.md` describes (the same six steps this page's own "Future source onboarding process" section below already established for Harris County) — Phase 35 did not shortcut that, and nothing the catalog records is wired into any harvester or the ingestion gate. See `docs/data-completeness.md` for what the catalog actually found and what it explicitly still does not know.

## The terms-review ledger (Phase 36)

Phase 36 (Source Terms and Commercial-Use Verification) added a third, still-separate data set: `data/phase36_terms_review.csv` (27 rows as of 2026-09-15), loaded via `harvesters.governance.source_catalog.load_terms_review()`. **This is not a third registry either.** Where the Phase 35 catalog answers "does a source exist for this county" (site-identity only), the terms-review ledger answers a narrower, later question for a subset of the highest-value sources the catalog found: "what did we actually find when we looked at this specific source's terms of use, license, or access controls, and what evidence backs that finding." Every row cites its own evidence — an executed agreement, a live-fetched terms page, a robots.txt result, or an explicit statute — never "it's public" or "it's a .gov site" alone (Phase 36 Section 9's evidence standard).

Of the 27 sources reviewed: 20 are `LEGAL_REVIEW_REQUIRED` (a real review happened and found no affirmative commercial-use permission, sometimes an explicit restriction), 7 are `DISCOVERED` (this phase could not actually review them — usually a JavaScript-rendered portal with no extractable static content — and are honestly left at the weaker, no-review-happened status rather than misrepresented as reviewed-and-unclear). **Zero rows are `APPROVED` or `APPROVED_WITH_RESTRICTIONS`.** Phase 36's own research did not, by itself, establish new commercial-use rights for any source — see `claude/phase-36-source-terms-commercial-verification.md` for the full source-by-source findings. `assert_every_terms_review_row_has_evidence()` enforces that no row above `DISCOVERED` is missing its `evidence_reference` at all times, including in CI-run tests.

A terms-review row does not, by itself, promote anything from the Phase 35 catalog into `SOURCE_REGISTRY` above — it is additional evidence gathered *before* that promotion decision (step 2, "Rights reconnaissance", in the process below), not a replacement for it.

## Future source onboarding process

Based on how Harris County (`tx_hctax`) was actually worked through this project's own phases, generalized:

1. **Technical reconnaissance** (this project's existing pattern — see `claude/harris-hctax-implementation-readiness.md` as the template): confirm the source is real, map its data flow, inventory its fields, test identity/uniqueness, test pagination/completeness, assess technical stability. Produces a technical-readiness verdict, independent of legal status.
2. **Rights reconnaissance** (see `claude/harris-hctax-legal-commercial-gate.md` as the template): Terms of Use review (automated access / storage / commercial use / customer display / API-export / historical retention / images-documents, each evaluated separately), robots.txt review (kept separate from legal conclusions), a rights matrix by asset, a per-activity commercial-use evaluation, a derived-data analysis. Produces a `LEGAL_REVIEW_REQUIRED` classification by default — never `APPROVED` from reconnaissance alone.
3. **A `SourceRecord` is added to `harvesters/governance/registry.py`** with `legal_status=SourceStatus.LEGAL_REVIEW_REQUIRED` (or `DISCOVERED`/`UNDER_REVIEW` for an earlier-stage source) and every field populated from steps 1-2's findings, `doc_refs` citing the actual documents.
4. **If pursuing clarification from the source itself** (see `claude/harris-hctax-rights-resolution-package.md` as the template): prepare draft outbound communications and a response decision framework *before* contact is made, for human review and human sending — never send anything automatically.
5. **Only once an actual resolution exists** (a counsel opinion, a source's written response, or a business decision to accept a defined risk) does `legal_status` change to `APPROVED` or `APPROVED_WITH_RESTRICTIONS` — and whichever restrictions the resolution implies get encoded in `restrictions`, not left implicit.
6. **Only then** does a harvester implementation phase begin — and the ingestion gate (`docs/data-licensing.md`) means a harvester written *before* step 5 completes still can't actually ingest anything, even if someone jumps ahead and writes the code.
