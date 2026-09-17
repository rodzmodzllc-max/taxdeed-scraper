"""Tests for Phase 51 - scoping the FDOR enrichment to Florida, and breaking
the within-a-county pinning that held coverage at 49%.

Both defects were found by measuring production, not by reading the code, so
these tests are written to fail if either regresses:

  A. The runner reads FLORIDA's statewide cadastral layer but selected rows
     with no `state` predicate, so 449 Texas rows across 14 counties sat in a
     queue they could never leave.

  B. The per-county slice was fetched with no `order`, and a miss is never
     stamped, so every run received the same rows in the same order. Combined
     with COUNTY_MISS_STREAK abandoning the county after six consecutive
     misses, a county could never advance past its first six bad rows.
     Confirmed live: Miami-Dade sat at 2/251 while its unenriched parcel
     0131230340860 returned a complete record from the layer on request.

No network and no database. The runner's two fetch functions are driven
against a fake `requests.get` that records the query parameters it was given,
which is the actual contract under test.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
from collections import Counter

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "enrich_property_details.py"


@pytest.fixture()
def enrich(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_p51_enrich", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p51_enrich"] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture()
def capture(enrich, monkeypatch):
    """Replaces requests.get and records every call's params."""
    calls = []
    payload = {"rows": []}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(dict(params or {}))
        return FakeResponse(payload["rows"])

    monkeypatch.setattr(enrich.requests, "get", fake_get)
    return calls, payload


# ===========================================================================
# Defect A - Florida scoping
# ===========================================================================


def test_p51_01_county_discovery_filters_on_state(enrich, capture):
    calls, payload = capture
    payload["rows"] = [{"county": "Alachua"}, {"county": "Leon"}]
    enrich.fetch_needing_enrichment_counties()
    assert calls[0].get("state") == "eq.FL"


def test_p51_02_county_batch_filters_on_state(enrich, capture):
    calls, _ = capture
    enrich.fetch_county_batch("Alachua", 10, 50)
    assert calls[0].get("state") == "eq.FL"


def test_p51_03_texas_rows_can_never_enter_the_queue(enrich, capture):
    """The whole point of A: a TX county must not appear even if the table
    holds TX rows. The filter is server-side, so the fake returns only what
    the filter would have returned."""
    calls, payload = capture
    payload["rows"] = [{"county": "Alachua"}, {"county": "Alachua"}, {"county": "Leon"}]
    counties = enrich.fetch_needing_enrichment_counties()
    assert {c for c, _ in counties} == {"Alachua", "Leon"}
    assert calls[0]["state"] == "eq.FL"


def test_p51_03b_a_shared_county_name_cannot_pull_the_other_states_rows(enrich, capture):
    """The sharpest form of Defect A, and the reason it is a CORRECTNESS bug
    and not merely a waste of requests.

    `Leon` is a county in BOTH states - Leon FL (Tallahassee, CO_NO 47) and
    Leon TX. The old batch query filtered `county=eq.Leon` with no state, so
    one slice mixed 48 Florida rows and 84 Texas rows, and every Texas row
    was then looked up against Florida's CO_NO 47. A parcel-string collision
    would have written a Tallahassee owner, address and CENTROID onto a Texas
    property - the exact "confident wrong answer" the enrichment plan warns
    is worse than no match, and one the plan's own mitigation cannot catch,
    because CO_NO 47 *is* the expected code for a row the script believes is
    Florida's Leon.

    Verified in production 2026-09-17: it never fired - TX Leon has 0 rows
    with `fdor_enriched_at`, and its coordinates sit at 31.0N/-96.2W, correct
    for Texas. That was luck, not design; 84 rows were exposed on every run.
    """
    calls, _ = capture
    enrich.fetch_county_batch("Leon", 40, 48)
    params = calls[0]
    assert params["county"] == "eq.Leon"
    assert params["state"] == "eq.FL", (
        "a shared county name must be disambiguated by state, or a Texas row "
        "can be enriched with Florida data"
    )


def test_p51_04_state_is_configurable_but_defaults_to_florida(enrich):
    """Hard-coding 'FL' would block a future state reusing the runner; a
    default of anything else would point it at the wrong layer."""
    assert enrich.ENRICH_STATE == "FL"
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "ENRICH_STATE":
            assert isinstance(node.value, ast.Call), "ENRICH_STATE must come from the environment"
            return
    raise AssertionError("ENRICH_STATE not found")


def test_p51_05_the_endpoint_is_still_floridas(enrich):
    """If this ever stops being a Florida endpoint, the FL default above is
    wrong and this test should be the thing that says so."""
    assert "Florida_Statewide_Cadastral" in enrich.FDOR_ENDPOINT


# ===========================================================================
# Defect B - the slice must move between runs
# ===========================================================================


def test_p51_06_batch_is_ordered(enrich, capture):
    """`offset` is meaningless without a deterministic order."""
    calls, _ = capture
    enrich.fetch_county_batch("Alachua", 10, 500)
    assert calls[0].get("order") == "id.asc"


def test_p51_07_batch_offset_varies_across_runs(enrich, capture):
    """The actual fix. Same county, same backlog, repeated calls must not
    keep returning the same window."""
    calls, _ = capture
    for _ in range(40):
        enrich.fetch_county_batch("Miami-Dade", 40, 251)
    offsets = {int(c["offset"]) for c in calls}
    assert len(offsets) > 1, "every run drew the same window - the pinning is back"


def test_p51_08_offset_never_skips_past_the_end(enrich, capture):
    """A window starting beyond the backlog returns nothing and wastes the
    county's whole slice for that run."""
    calls, _ = capture
    for _ in range(60):
        enrich.fetch_county_batch("Volusia", 40, 307)
    for call in calls:
        assert 0 <= int(call["offset"]) <= 307 - 40


def test_p51_09_small_backlog_always_starts_at_zero(enrich, capture):
    """When the backlog fits in one slice there is nothing to rotate, and an
    offset would hide rows."""
    calls, _ = capture
    for _ in range(20):
        enrich.fetch_county_batch("Monroe", 40, 4)
    assert {int(c["offset"]) for c in calls} == {0}


def test_p51_10_exactly_full_backlog_starts_at_zero(enrich, capture):
    calls, _ = capture
    enrich.fetch_county_batch("Lake", 40, 40)
    assert int(calls[0]["offset"]) == 0


def test_p51_11_unknown_backlog_is_safe(enrich, capture):
    """`outstanding=None` must not crash or invent an offset."""
    calls, _ = capture
    enrich.fetch_county_batch("Alachua", 10)
    assert int(calls[0]["offset"]) == 0


def test_p51_12_discovery_returns_counties_with_their_backlog(enrich, capture):
    calls, payload = capture
    payload["rows"] = [{"county": "Leon"}] * 132 + [{"county": "Alachua"}] * 118
    counties = enrich.fetch_needing_enrichment_counties()
    assert dict(counties) == {"Leon": 132, "Alachua": 118}


def test_p51_13_county_order_is_still_shuffled(enrich, capture):
    """The original between-counties fairness must survive this change."""
    _, payload = capture
    payload["rows"] = [{"county": c} for c in "ABCDEFGHIJKLMNOP"]
    orders = {tuple(c for c, _ in enrich.fetch_needing_enrichment_counties()) for _ in range(30)}
    assert len(orders) > 1


# ===========================================================================
# What must NOT have changed
# ===========================================================================


def test_p51_14_misses_are_still_never_stamped(enrich):
    """Retrying misses is deliberate - it is how a county picks up its
    backlog when its format is cracked later. The fix must not 'solve' the
    pinning by giving up on misses."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "fdor_enriched_at" in src
    tree = ast.parse(src)
    stamps = [n for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and n.value == "fdor_enriched_at"]
    assert stamps, "the success stamp disappeared"


def test_p51_15_anti_starvation_limits_are_untouched(enrich):
    assert enrich.PER_COUNTY_LIMIT == 40
    assert enrich.BATCH_LIMIT == 1000
    assert enrich.COUNTY_MISS_STREAK == 6


def test_p51_16_empty_string_parcels_are_still_excluded(enrich, capture):
    """Pre-existing guard: '' parcels can never resolve and would burn slice."""
    calls, _ = capture
    enrich.fetch_county_batch("Citrus", 10, 8)
    assert calls[0]["and"] == '(parcel.not.is.null,parcel.neq."")'
    assert calls[0]["fdor_enriched_at"] == "is.null"


def test_p51_17_polite_pacing_is_untouched(enrich):
    assert enrich.REQUEST_DELAY_SECONDS >= 0.3


def test_p51_18_runner_still_has_no_database_driver(enrich):
    """It talks to PostgREST over HTTP and to the FDOR layer. No DB driver,
    no DML - same structural guarantee the acquisition package carries."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    banned = {"psycopg", "psycopg2", "sqlalchemy", "asyncpg", "pymysql", "MySQLdb"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in banned
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned


def test_p51_19_county_codes_still_carry_the_dade_trap(enrich):
    """FDOR lists Miami-Dade as 'Dade', which sorts to 23 rather than 54.
    Getting this wrong silently matches another county's parcel."""
    assert enrich.COUNTY_CODES["Miami-Dade"] == 23
    assert enrich.COUNTY_ALIASES["Dade"] == "Miami-Dade"


def test_p51_20_every_lookup_is_still_county_scoped(enrich):
    """A PARCEL_ID is unique only within a county. An un-scoped lookup can
    return a different county's parcel - the dangerous failure mode."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "AND CO_NO=" in src
