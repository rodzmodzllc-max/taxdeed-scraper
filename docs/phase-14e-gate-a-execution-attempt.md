# Phase 14E: Fresh Gate A Re-Verification & Gate B Execution Attempt

**Status:** 2026-09-14, same day as Phase 14D. **Gate A: GREEN** (live-re-verified, in full, against production project `cqnnnvpbocafuvpzfbzu`). **Gate B: NOT COMPLETED** — execution was authorized and attempted per this phase's own instructions, but the first statement (`schema-v9-dor-use-code.sql`) was denied by this sandbox's own tool-access classifier before any SQL reached production. **No production SQL executed. No production data or schema changed.**

This document is the record of that attempt, requested as "PHASE 14C — FRESH GATE A" (reusing the Phase 14C name in the instruction, though it functions as a new phase given Phase 14D — the corrective phase Phase 14C itself called for — is already complete and committed at `76ee5e8`). Companion to `docs/phase-14d-migration-reconciliation.md` (the corrected migration package this phase re-verified) and `docs/phase-14c-production-migration-verification.md` Section 14 (the same live findings, appended there for continuity).

## 1. What this phase verified live (Gate A)

Every item was independently re-queried against production this session — nothing was carried forward from Phase 14C's or Phase 14D's snapshots without a fresh check, per this phase's own instructions ("Query the live database wherever possible... Do not rely on previous reports for current production state"). Full detail in `docs/phase-14c-production-migration-verification.md` Section 14; summary:

- **Live schema**: exactly 49 columns on `public.properties` (resolves the "47 vs 49" inconsistency Phase 14D flagged — 49 is correct). `outcome`, `sold_price`, `dor_use_code` all confirmed absent.
- **005 compatibility**: every column Phase 14D's corrected 005 references exists live except `dor_use_code` — confirming the `schema-v9` → `005` dependency is exact, not approximate.
- **Row count**: 3,929. **Duplicates**: 0. **Unique constraint**: `properties_state_source_county_case_no_key`, `UNIQUE (state, source, county, case_no)` — present.
- **RLS**: enabled, not forced, one PERMISSIVE policy (`"properties: approved only"`, `cmd = ALL`, `is_approved()`).
- **Grants**: `anon`/`authenticated`/`service_role` all hold blanket `SELECT`/`INSERT`/`UPDATE`/`DELETE`/`REFERENCES`/`TRIGGER`/`TRUNCATE` on `public.properties` today (broader than previously fully enumerated — `TRUNCATE` on `anon`/`authenticated` is a new finding, a pre-existing over-grant unrelated to and untouched by 005/005a). Column-level grants show no narrowing yet (005a has genuinely not run).
- **`get_properties()`**: still the pre-005 `select *` body, `security invoker`, matching tracked migration 003 exactly. `EXECUTE` broadly granted (`service_role`, `authenticated`, `anon`, `postgres`, `PUBLIC`).
- **`digest_candidates()`**: still absent live. New finding: `supabase/functions/send-digest/index.ts` does call it — but `mcp__Supabase__list_edge_functions` shows **zero Edge Functions deployed** to this project, so nothing live actually invokes it. Non-blocking, more precisely characterized than before.
- **Geometry**: no `geom` column exists; `properties_sync_geom()` remains defined but attached to no trigger. Unchanged, non-blocking.
- **Tests**: 151/151, re-run this phase, unchanged.

All 18 items this phase's own Gate A checklist required were satisfied. **Gate A = GREEN.**

## 2. Gate B: execution attempt and stop

Per this phase's own instructions ("If and ONLY if Gate A is GREEN, you may proceed... Do not ask for permission again inside this task"), the migration sequence was started using `mcp__Supabase__apply_migration` (the tool this environment's own Supabase MCP server documents as the correct one for DDL, in preference to `execute_sql`):

```
apply_migration(project_id="cqnnnvpbocafuvpzfbzu", name="schema_v9_dor_use_code", query=<the two statements from schema-v9-dor-use-code.sql>)
```

This call was **denied by this sandbox's own tool-access classifier**, reason `[Production Deploy]`. No SQL reached production; `public.properties` was not altered. Per this session's standing rule ("never work around a tool-access denial") and the classifier's own returned guidance, this was not retried with `execute_sql` or any other tool as a workaround — that would defeat the intent of the denial, not just its mechanism. `005` and `005a` were therefore never attempted either, since the corrected execution order requires `schema-v9` to succeed first.

This is a different outcome from Phase 14C's session, where the same class of Supabase tool calls (`list_tables`, `execute_sql`) succeeded after being denied in Phase 14A/14B — tool-access grants in this environment have varied session-to-session throughout this project's history, and this session's own read access (`execute_sql`, `list_edge_functions`) succeeded while its write/DDL access (`apply_migration`) did not. Read and write/DDL access are evidently gated separately by this classifier.

## 3. What this means

Gate A being GREEN is not diminished by this — it is a genuine, freshly-verified finding, independent of whether execution could proceed this session. The corrected migration package (`docs/phase-14d-migration-reconciliation.md`, commit `76ee5e8`) remains ready to execute in the documented order (`schema-v9-dor-use-code.sql` → `005` → `005a`) the next time a session in this environment has both read and DDL/write access to the production Supabase project. No new Gate A re-verification should be required for that attempt unless meaningful time has passed or this document's own findings are otherwise suspected stale — but re-checking costs little and this project's own history (`CLAUDE.md`) already establishes that live state can silently diverge from tracked assumptions, so a fresh check is still cheap insurance.

## 4. What this phase did and did not do

**Did:** re-verified Gate A live and in full (Section 1); attempted Gate B step 1 and recorded the exact denial (Section 2); appended the live findings to `docs/phase-14c-production-migration-verification.md` (Section 14) for continuity with that document's own Gate A checklist; wrote this document.

**Did not do:** execute any production SQL; create, alter, or drop any Supabase object; change any RLS policy or grant; modify production data; dispatch any GitHub Actions workflow; add or activate any Texas source or county; change any source's legal status; push to origin; modify `harvesters/governance/registry.py`; weaken or delete any test.

## 5. Recommended next action

Not Phase 15. The next concrete step is simply retrying the same `schema-v9-dor-use-code.sql` → `005` → `005a` sequence in a future session where this environment's tool-access classifier grants DDL/write access to the production Supabase project (the same kind of session-to-session variance Phase 14C already demonstrated for read access) — Gate A does not need to be redesigned or re-scoped, only re-attempted with working write access, ideally with a quick freshness check first per Section 3 above. The `TRUNCATE` over-grant on `anon`/`authenticated` (Section 1) and the `digest_candidates()`/`send-digest` drift (Section 1) are both named here as real, separate findings worth a future phase's own explicit review — neither blocks or is touched by the schema-v9/005/005a chain.
