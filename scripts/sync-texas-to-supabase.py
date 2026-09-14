#!/usr/bin/env python3
"""Pushes harvesters/texas_harvester.py's output (out/harvest_texas.json) into
the same `properties` table the FL sync scripts write to, with state='TX'.

Mirrors sync-certificates-to-supabase.ps1 / sync-harvest-to-supabase.ps1's
safe-merge design, in Python rather than PowerShell (matching this repo's
existing Python-for-TX / PowerShell-for-FL split - see
enrich_property_details_tx.py, tx_use_codes.py, tx_yield_calc.py): only ever
sends the columns the harvester actually knows, so re-syncing never clobbers
hand research. Deliberately OMITTED from every payload, same as the FL
scripts: owner_name, status, lien_level, lien_note, prop_type, homestead,
url_streetview, url_zillow, url_taxcoll, url_title, tx_category,
redemption_period_months, redemption_expiration_date,
max_statutory_return_usd - those are enrichment-time or hand-research
fields, not harvest-time fields (see texas_harvester.py's module docstring).

Conflict target is `on_conflict=state,source,county,case_no` from day one -
NOT the older FL-only `on_conflict=source,county,case_no` target the three
FL sync scripts still fall back to. No fallback needed here: unlike the FL
scripts (which have to keep working against a Supabase project that might
predate 004_widen_unique_constraint_for_state.sql), Texas rows only ever
start existing once Texas harvesting itself starts, which is after that
migration has been run - see the `texas` job's own comment in
.github/workflows/harvest-and-sync.yml. If this still hits a 42P10 error,
that means the migration genuinely hasn't been run yet against whatever
Supabase project this points at - the fix is to run it (see that
migration's own header comment on why it can't be typed into the Supabase
SQL Editor via browser automation), not to fall back to the narrower
conflict target, which would silently reopen the exact FL/TX same-named-
county collision that migration exists to prevent.

`case_no` is LGBS's (or any future TX vendor's) own CAD parcel/account
number, not a legal case/cause number - see texas_harvester.py's module
docstring ("harvest_lgbs() shipped" note) for why a per-parcel-unique id was
required for this table's (state, source, county, case_no) uniqueness
constraint, and why the legal cause number goes into `parcel` instead.

`bid` (used by every card/spread/value-ratio calculation in public/app.js)
and `min_bid` (the Texas-specific "TX Min Bid" export column) are both set
from the same harvested minimum-bid figure - that number plays both roles
honestly: it is both "the amount you'd need to bid" (bid's cross-state
meaning) and Texas's own court-ordered statutory minimum (min_bid's
TX-specific meaning), not two different figures.

Run harvesters/texas_harvester.py first, then this.

UPDATED 2026-09-14 (Phase 10A - Commercial Source Governance
Infrastructure): this script re-checks harvesters/governance's ingestion
gate for each row's `harvester_source`, right before that row is added to
the upsert payload. This is DEFENSE IN DEPTH, not the primary enforcement
point (that's texas_harvester.py's main(), which skips a non-approved
vendor's harvest_*() function entirely - see that file's own Phase 10A
comment) - it exists so that if out/harvest_texas.json is ever produced by
some other path, or hand-edited, or left over from before a source's
status changed, a row from a LEGAL_REVIEW_REQUIRED/BLOCKED/DISABLED/
TERMS_CHANGED source still cannot reach Supabase's `properties` table
through this script.

UPDATED 2026-09-14 (Phase 11 - Customer/API Data-Restriction Enforcement):
closes the specific gap Phase 10A's own report named ("customer/API
enforcement functions built/tested but NOT wired into frontend"). This
application has no application server: `public/app.js` reads
`public.properties` directly (via the `get_properties()` RPC or a plain
`.select("*")`), the CSV export in app.js reads from the same
already-fetched rows, and `supabase/functions/send-digest`'s
`digest_candidates` RPC (service_role, bypassing RLS) also reads straight
from `properties`. None of those three surfaces can invoke this Python
governance package - they run in the browser or in a separate Deno
runtime - and Phase 11's hard rules forbid a Supabase schema
change/migration this phase, so no read-time enforcement point can be
added to any of them without one. Given that constraint, this table has
no field-level RLS, so a row that reaches it is immediately, unfilterably
customer-visible to every approved app user through EVERY one of those
three surfaces at once - meaning the row this script builds below IS the
literal customer-facing representation in this codebase's actual
architecture, and this script is therefore the one real, exercisable
enforcement boundary for field-level restrictions too, not just whole-
source ones. `harvesters/governance/gate.py`'s new
`project_row_for_customer_output()` is called on every row below (see the
row-building loop) - it performs the SAME whole-source check as
check_ingestion_gate() below plus a customer-display-blocking-restriction
check, THEN strips any individual restricted-content-shaped field
(raw HTML / images / documents) from an otherwise-permitted row. As of
this phase this is a verified NO-OP for tx_lgbs/tx_realauction (both
APPROVED, zero restrictions - see
tests/python/test_customer_api_enforcement.py's regression tests) - zero
behavior change for either of those two production sources today; the
mechanism exists and is tested so the day either source (or a future
source) is registered APPROVED_WITH_RESTRICTIONS, enforcement is already
wired rather than needing to be built under time pressure. See
docs/customer-api-data-enforcement.md for the full architecture writeup,
including the honest limitation this leaves: the write-time-only
enforcement described here is the best available given the no-migration
constraint, not a claim of independent read-time enforcement.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
JSON_PATH = HERE / "../out/harvest_texas.json"

# See the module docstring's Phase 10A note above. Inserted (rather than
# relying on cwd) so this script works the same whether it's run from the
# repo root (as .github/workflows/harvest-and-sync.yml's `texas` job does)
# or from anywhere else.
sys.path.insert(0, str(HERE / ".."))
from harvesters.governance.gate import check_ingestion_gate, project_row_for_customer_output  # noqa: E402

BATCH_SIZE = 40  # matches the FL sync scripts' batch size

# RESTORED 2026-09-14: migrations 002_add_texas_support.sql,
# 003_ledger_type_and_state_isolation.sql, and
# 004_widen_unique_constraint_for_state.sql were run against production
# (Marc, via the Supabase SQL Editor, per
# claude/migration-002-003-004-execution-plan.md) and independently
# reconfirmed live afterwards: `harvester_source` (and its sibling
# ledger_type) now exist in `select column_name from
# information_schema.columns where table_name='properties'`, the new
# properties_state_source_county_case_no_key UNIQUE(state, source, county,
# case_no) constraint replaced the old 3-column one, and all 3,366
# pre-existing rows landed unchanged (zero data loss). See that migration
# doc for the full verification queries. `harvester_source` is safe to send
# again - flip back to False (and see the git history of this file for why)
# only if a live information_schema check ever shows the column missing
# again, e.g. against a different/earlier Supabase project.
SEND_HARVESTER_SOURCE = True

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _num(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_date_or_none(value):
    if not value or not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        return None
    return value


def main() -> None:
    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY")  # never log, never commit - see CLAUDE.md
    if not supabase_url or not service_key:
        print(
            "SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not "
            "set - check the workflow's secrets.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not JSON_PATH.exists():
        print(f"No {JSON_PATH} - harvester found nothing this run. Nothing to sync.", file=sys.stderr)
        return

    harvest = json.loads(JSON_PATH.read_text())
    if not harvest:
        print("harvest_texas.json is empty - nothing to sync.", file=sys.stderr)
        return

    # De-duplicate on (county, case_no) - the same conflict-target key the
    # upsert below uses. Postgres's ON CONFLICT DO UPDATE rejects a batch
    # that would update the same conflict-target row twice in one statement
    # ("ON CONFLICT DO UPDATE command cannot affect row a second time"),
    # which failed sync-certificates-to-supabase.ps1's ENTIRE run the one
    # time LienHub published a duplicate row (see that script's own
    # comment) - not just the duplicated rows. Keep the last-seen row per
    # key, same as that fix.
    deduped: dict[tuple[str, str], dict] = {}
    skipped = 0
    skipped_gate = 0
    skipped_customer_restriction = 0
    gate_rejections: dict[str, int] = {}
    for p in harvest:
        case_no = p.get("account_number")
        county = p.get("county")
        source = p.get("source")
        if not case_no or not county or not source:
            skipped += 1
            continue

        # Phase 10A defense-in-depth check (see module docstring) - a row
        # from a non-APPROVED/APPROVED_WITH_RESTRICTIONS vendor is dropped
        # here even if it somehow made it into harvest_texas.json.
        harvester_source = p.get("harvester_source")
        gate_decision = check_ingestion_gate(harvester_source)
        if not gate_decision.allowed:
            skipped_gate += 1
            gate_rejections[harvester_source or "(missing)"] = gate_rejections.get(harvester_source or "(missing)", 0) + 1
            continue

        address = (p.get("address") or "").strip() or f"Account {case_no}"
        min_bid = _num(p.get("min_bid"))
        bid = min_bid if min_bid is not None else 0

        row = {
            "state": "TX",
            "source": source,
            "county": county,
            "case_no": case_no,
            "parcel": p.get("cause_number") or None,
            "address": address,
            "bid": bid,
            "min_bid": min_bid,
            "assessed": _num(p.get("cad_market_value")),
            "sale_date": _iso_date_or_none(p.get("auction_date")),
            "legal_desc": p.get("legal_description") or None,
        }
        if SEND_HARVESTER_SOURCE:
            row["harvester_source"] = p.get("harvester_source") or None
        # latitude/longitude get the safe-merge treatment PER ROW, not just
        # script-wide: scripts/geocode_properties.py only ever fills these
        # in when they are still NULL, so sending an explicit null here for
        # a row LGBS didn't publish coordinates for would silently erase a
        # value that script already backfilled on an earlier run. Omit the
        # keys entirely when we don't have real coordinates, rather than
        # sending null.
        lat, lon = _num(p.get("latitude")), _num(p.get("longitude"))
        if lat is not None and lon is not None:
            row["latitude"] = lat
            row["longitude"] = lon

        # Phase 11: project the row through the same governance layer's
        # customer-output check (whole-row block on a customer-display-
        # blocking restriction, plus field-shape stripping - see this
        # file's module docstring and harvesters/governance/gate.py). Not
        # redundant with the check_ingestion_gate() call above: that gate
        # checks only legal_status; this checks legal_status AND
        # restrictions AND fields. For tx_lgbs/tx_realauction (both
        # APPROVED, zero restrictions) this is a verified no-op - `row` is
        # returned unchanged - see the Phase 11 regression tests.
        projected_row = project_row_for_customer_output(row, harvester_source)
        if projected_row is None:
            skipped_customer_restriction += 1
            continue

        deduped[(county, case_no)] = projected_row

    dupe_count = len(harvest) - skipped - skipped_gate - skipped_customer_restriction - len(deduped)
    if dupe_count > 0:
        print(
            f"De-duplicated {dupe_count} row(s) sharing a (county, case_no) key with another row in this harvest.",
            file=sys.stderr,
        )
    if skipped_gate > 0:
        print(
            f"Ingestion gate rejected {skipped_gate} row(s) (source not APPROVED/APPROVED_WITH_RESTRICTIONS): "
            f"{gate_rejections} - see harvesters/governance/registry.py for each source's current status.",
            file=sys.stderr,
        )
    if skipped_customer_restriction > 0:
        print(
            f"Customer-output projection blocked {skipped_customer_restriction} row(s) whose source passed the "
            "ingestion gate but carries a customer-display-blocking restriction (no_customer_display / "
            "no_redistribution / source_only_display / field_specific_restriction) - see "
            "harvesters/governance/gate.py's project_row_for_customer_output(). Not expected for "
            "tx_lgbs/tx_realauction today (both carry zero restrictions).",
            file=sys.stderr,
        )

    rows = list(deduped.values())
    if not rows:
        print(
            f"Nothing to sync ({skipped} skipped for missing case_no/county/source, "
            f"{skipped_gate} skipped by the ingestion gate, "
            f"{skipped_customer_restriction} skipped by customer-output projection).",
            file=sys.stderr,
        )
        return
    print(f"Prepared {len(rows)} properties ({skipped} skipped for missing case_no/county/source).", file=sys.stderr)

    endpoint = f"{supabase_url}/rest/v1/properties?on_conflict=state,source,county,case_no"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    # PostgREST's bulk upsert requires every object in one POST body to have
    # IDENTICAL keys - it builds a single INSERT from the shape of the first
    # row in the array, and rejects the whole batch with PGRST102 ("All
    # object keys must match") the moment one row in that same batch has a
    # different key set. CONFIRMED LIVE 2026-09-14 (workflow run #130): rows
    # 1-400 synced fine across 10 batches that each happened to be
    # internally homogeneous, then batch 11 (rows 400-436) mixed rows that
    # do/don't have latitude+longitude (the intentional per-row omission
    # above) and PGRST102'd, losing that entire batch even though every row
    # in it was otherwise well-formed. Fix: split into two homogeneous
    # groups - rows WITH latitude/longitude and rows WITHOUT - and batch/
    # sync each group separately. Never add an explicit null for the
    # missing-coordinate group instead (that would defeat the safe-merge
    # comment above by erasing coordinates geocode_properties.py already
    # backfilled).
    with_geo = [r for r in rows if "latitude" in r]
    without_geo = [r for r in rows if "latitude" not in r]

    sent = 0
    for label, group in (("with coordinates", with_geo), ("without coordinates", without_geo)):
        if not group:
            continue
        for i in range(0, len(group), BATCH_SIZE):
            batch = group[i : i + BATCH_SIZE]
            body = json.dumps(batch).encode("utf-8")
            req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    resp.read()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if "42P10" in detail or "no unique or exclusion constraint" in detail:
                    print(
                        "SYNC FAILED: Postgres reports no unique constraint matches "
                        "on_conflict=state,source,county,case_no - "
                        "004_widen_unique_constraint_for_state.sql has not been run "
                        "against this Supabase project yet. Run it (see that "
                        "migration's header comment), then re-run this sync.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"SYNC FAILED on '{label}' batch starting at row {i}: {exc.code} {detail}",
                        file=sys.stderr,
                    )
                sys.exit(1)
            sent += len(batch)
            print(f"  synced {sent} / {len(rows)} ({label})", file=sys.stderr)

    counties = len({r["county"] for r in rows})
    print(f"Done. {sent} Texas properties upserted to Supabase (existing hand research untouched).", file=sys.stderr)
    print(f"Counties covered: {counties}", file=sys.stderr)


if __name__ == "__main__":
    main()
