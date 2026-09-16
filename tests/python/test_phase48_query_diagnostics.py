"""Phase 48. Two unrelated-looking things are tested here because they came
out of the same run:

  1. The read-only query diagnostic - that it measures what it claims to,
     keeps `?state=TX` and `?area=TX` apart, and cannot quietly acquire
     anything or write anywhere.

  2. The county_coverage reporting fix - run 35113290312 acquired 213 real
     records across real Texas counties and reported an EMPTY per-county
     breakdown, because the runner had no single county to pass.

The diagnostic tests deliberately include one for the instrument itself. A
local smoke test of the first draft tripped the transport's circuit breaker
after 5 consecutive failures, and the remaining 13 requests were refused
without ever being sent - they looked like failures and measured nothing. On
the runner that would have let a consistently-failing `state=TX` poison the
`area=TX` control, which is the comparison the whole script exists to make.
A broken instrument produces confident wrong answers, so the instrument gets
a test.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "diagnose_lgbs_query_latency.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lgbs-query-diagnostics.yml"


def load_module():
    spec = importlib.util.spec_from_file_location("diagnose_lgbs_query_latency", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RecordingTransport:
    """Stands in for the network. Records every URL and returns whatever the
    test queued, so the diagnostic's own behaviour is observable."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.requested: list[str] = []

    def get(self, url: str, *, timeout: float | None = None):
        self.requested.append(url)
        entry = self.responses[url]
        if isinstance(entry, Exception):
            raise entry
        return entry


class FakeResponse:
    def __init__(self, payload: dict, *, http_status: int = 200):
        self.body = json.dumps(payload).encode("utf-8")
        self.http_status = http_status
        self.content_type = "application/json"

    def json(self):
        return json.loads(self.body)


# ===========================================================================
# 1. The six comparisons, exactly as Phase 48 Section 2 specifies
# ===========================================================================


def test_p48_01_exactly_the_six_specified_queries():
    mod = load_module()
    assert [(label, param, limit) for label, param, limit in mod.QUERIES] == [
        ("A", "state", 1),
        ("B", "state", 10),
        ("C", "state", 100),
        ("D", "area", 1),
        ("E", "area", 10),
        ("F", "area", 100),
    ]


def test_p48_02_state_and_area_urls_are_distinct_and_correctly_built():
    mod = load_module()
    assert mod.url_for("state", 1) == "https://taxsales.lgbs.com/api/property_sales/?state=TX&limit=1"
    assert mod.url_for("area", 100) == "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=100"
    assert mod.url_for("state", 1) != mod.url_for("area", 1)


def test_p48_03_largest_request_is_100_records():
    """A diagnostic has no business pulling pages. The biggest ask here is
    100 rows."""
    mod = load_module()
    assert max(limit for _, _, limit in mod.QUERIES) == 100


# ===========================================================================
# 2. The instrument
# ===========================================================================


def policy_kwargs() -> dict:
    """The RateLimitPolicy(...) the script actually constructs, read with
    ast. Substring matching would trip over the docstring, which mentions
    acquisition's max_retries=2 while explaining why this differs - the
    first draft of this test did exactly that."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "RateLimitPolicy"):
            return {kw.arg: kw.value for kw in node.keywords}
    raise AssertionError("the script constructs no RateLimitPolicy")


def test_p48_04_one_attempt_per_request():
    """Acquisition retries; a measurement must not. Two attempts would turn
    a 30s timeout into a 61s one and hide whether the first attempt worked."""
    kwargs = policy_kwargs()
    assert isinstance(kwargs["max_retries"], ast.Constant)
    assert kwargs["max_retries"].value == 1


def test_p48_05_timeout_matches_acquisition_so_a_timeout_means_the_same_thing():
    kwargs = policy_kwargs()
    assert kwargs["timeout_seconds"].value == 30


def test_p48_06_circuit_breaker_cannot_poison_the_comparison():
    """The regression the local smoke test caught: with the default
    threshold of 5, a consistently-failing query silently cancels every
    later measurement, including the control."""
    kwargs = policy_kwargs()
    assert "circuit_breaker_threshold" in kwargs, (
        "without a raised threshold the breaker trips after 5 consecutive failures "
        "and silently cancels the rest of the comparison"
    )
    expr = kwargs["circuit_breaker_threshold"]
    assert isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add)
    assert isinstance(expr.left, ast.Name) and expr.left.id == "total_requests"


def test_p48_07_repeated_trials_so_intermittent_is_distinguishable():
    mod = load_module()
    assert mod.TRIALS >= 3, "one observation cannot separate 'always slow' from 'sometimes slow'"


def test_p48_08_unsent_requests_are_flagged_not_counted_as_source_failures():
    mod = load_module()
    breaker_refusal = Exception("circuit breaker open after 5 consecutive failures; not requesting x")
    from harvesters.acquisition.transport import SourceUnavailable

    t = RecordingTransport({"u": SourceUnavailable(
        "circuit breaker open after 5 consecutive failures; not requesting u")})
    obs = mod.one_request(t, "u")
    assert obs["success"] is False
    assert obs["request_was_sent"] is False, "a breaker refusal never reached the source"

    t2 = RecordingTransport({"u": SourceUnavailable("u: timed out")})
    obs2 = mod.one_request(t2, "u")
    assert obs2["request_was_sent"] is True, "a real timeout DID reach the network"


# ===========================================================================
# 3. What an observation records
# ===========================================================================


def test_p48_09_a_successful_observation_records_the_required_fields():
    mod = load_module()
    payload = {"count": 4205, "next": "https://example.invalid/next", "results": [{"uid": "u1"}]}
    t = RecordingTransport({"u": FakeResponse(payload)})

    obs = mod.one_request(t, "u")

    assert obs["success"] is True
    assert obs["http_status"] == 200
    assert obs["envelope_count"] == 4205
    assert obs["results_returned"] == 1
    assert obs["next_link_present"] is True
    assert obs["response_bytes"] == len(json.dumps(payload).encode("utf-8"))
    assert obs["latency_seconds"] is not None


def test_p48_10_a_failed_observation_records_the_error_without_raising():
    """A failure is the data. The diagnostic must never abort on one."""
    from harvesters.acquisition.transport import SourceUnavailable

    mod = load_module()
    t = RecordingTransport({"u": SourceUnavailable("u: timed out")})

    obs = mod.one_request(t, "u")

    assert obs["success"] is False
    assert obs["error_class"] == "SourceUnavailable"
    assert "timed out" in obs["error"]
    assert obs["latency_seconds"] is not None


def test_p48_11_summary_separates_all_failed_from_intermittent():
    mod = load_module()
    ok = {"success": True, "latency_seconds": 1.0, "envelope_count": 10, "error_class": None,
          "request_was_sent": True}
    bad = {"success": False, "latency_seconds": 30.0, "envelope_count": None,
           "error_class": "SourceUnavailable", "request_was_sent": True}

    assert mod.summarize("A", "state", 1, [ok, ok, ok])["query_outcome"] == "ALL_SUCCEEDED"
    assert mod.summarize("A", "state", 1, [bad, bad, bad])["query_outcome"] == "ALL_FAILED"
    assert mod.summarize("A", "state", 1, [ok, bad, ok])["query_outcome"] == "INTERMITTENT"


# ===========================================================================
# 4. Safety - it acquires nothing and writes nowhere
# ===========================================================================


def test_p48_12_no_database_driver_and_no_dml():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                assert not any(k in (m or "").lower() for k in
                               ("supabase", "psycopg", "sqlalchemy", "asyncpg", "pg8000", "requests"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value.strip().upper()
            assert not v.startswith(("INSERT ", "UPDATE ", "DELETE ", "UPSERT ", "DROP ", "TRUNCATE "))


def test_p48_13_it_does_not_acquire_or_normalize_anything():
    src = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("LgbsAdapter", "AcquisitionRun", "normalize(", ".acquire("):
        assert forbidden not in src, f"a diagnostic must not {forbidden}"


def test_p48_14_it_checks_the_governance_gate_before_requesting():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "check_acquisition_policy" in src
    assert "INTERNAL_TECHNICAL_TESTING" in src
    assert src.index("check_acquisition_policy") < src.index("UrllibTransport(")


def test_p48_15_area_tx_is_never_called_a_denominator():
    """Section 3. `?area=TX` includes PA contamination and is not the Texas
    denominator - this script must not hand anyone a number that could be
    mistaken for one."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "current_live_denominator" not in src
    assert "TX_LGBS_STATE_DENOMINATOR" not in src


# ===========================================================================
# 5. The workflow
# ===========================================================================


def test_p48_16_diagnostics_workflow_is_dispatch_only_and_secretless():
    yaml = pytest.importorskip("yaml")
    d = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    trig = d.get(True) or d.get("on")
    assert list(trig.keys()) == ["workflow_dispatch"]
    for forbidden in ("schedule", "push", "pull_request", "repository_dispatch"):
        assert forbidden not in trig
    assert "secrets." not in WORKFLOW.read_text(encoding="utf-8")


def test_p48_17_diagnostics_cannot_run_beside_an_acquisition_run():
    """Two concurrent probes of the same host would contaminate the latency
    measurement this workflow exists to take."""
    yaml = pytest.importorskip("yaml")
    d = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert d["concurrency"]["group"] == "lgbs-acquisition-validation"


def test_p48_18_the_acquisition_workflow_was_not_touched_by_this_phase():
    """The diagnostic is a separate file precisely so the acquisition
    workflow's pinned modes and full-mode guard stay exactly as they were."""
    yaml = pytest.importorskip("yaml")
    acq = REPO_ROOT / ".github" / "workflows" / "lgbs-acquisition-validation.yml"
    d = yaml.safe_load(acq.read_text(encoding="utf-8"))
    trig = d.get(True) or d.get("on")
    assert trig["workflow_dispatch"]["inputs"]["mode"]["options"] == ["probe", "sample", "full"]
    guard = next(s for s in d["jobs"]["acquire"]["steps"]
                 if s.get("name", "").startswith("Guard - full mode"))
    assert guard["if"] == "inputs.mode == 'full'"


# ===========================================================================
# 6. county_coverage - the Phase 47 reporting gap
# ===========================================================================


def county_run(records: list[dict]):
    """Drive the real AcquisitionRun with a real AcquisitionResult."""
    from harvesters.acquisition.result import AcquisitionStatus, build_result
    from harvesters.acquisition.run import AcquisitionRun

    result = build_result(
        source_id="tx_lgbs",
        jurisdiction="TX/statewide",
        status=AcquisitionStatus.SUCCESS,
        started_at="2026-09-16T00:00:00+00:00",
        records=tuple(records),
        records_seen=len(records),
    )
    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    run.record_result(result)          # no county= - exactly as the runner calls it
    return run


def test_p48_19_statewide_run_now_reports_per_county_rows():
    """Before: empty, for 213 real records. After: one row per county."""
    run = county_run([
        {"county": "Harris", "case_no": "A1"},
        {"county": "Harris", "case_no": "A2"},
        {"county": "Dallas", "case_no": "B1"},
    ])
    rows = {r["county"]: r for r in run.county_coverage()}

    assert set(rows) == {"Harris", "Dallas"}
    assert rows["Harris"]["records_acquired"] == 2
    assert rows["Dallas"]["records_acquired"] == 1


def test_p48_20_per_county_totals_agree_with_the_tally():
    run = county_run([{"county": "Harris", "case_no": f"A{i}"} for i in range(5)]
                     + [{"county": "Bexar", "case_no": "B1"}])
    total = sum(r["records_acquired"] for r in run.county_coverage())
    assert total == run.tally.records_acquired == 6


def test_p48_21_an_explicit_county_still_buckets_the_whole_result():
    """The single-county path (ArcGIS per-county acquisition) is unchanged."""
    from harvesters.acquisition.result import AcquisitionStatus, build_result
    from harvesters.acquisition.run import AcquisitionRun

    result = build_result(
        source_id="tx_hcad", jurisdiction="TX/Harris", status=AcquisitionStatus.SUCCESS,
        started_at="2026-09-16T00:00:00+00:00",
        records=({"county": "Harris"}, {"county": "Harris"}), records_seen=2,
    )
    run = AcquisitionRun(source_id="tx_hcad", state="TX")
    run.record_result(result, county="Harris")
    rows = run.county_coverage()
    assert len(rows) == 1 and rows[0]["county"] == "Harris"
    assert rows[0]["records_acquired"] == 2


def test_p48_22_records_without_a_county_are_not_bucketed_under_a_placeholder():
    """An invented 'UNKNOWN' county would then be compared against a roster
    denominator that has no such entry. A gap is more honest."""
    run = county_run([{"county": "Harris"}, {"case_no": "no-county"}, {"county": ""}])
    rows = run.county_coverage()
    assert [r["county"] for r in rows] == ["Harris"]
    assert sum(r["records_acquired"] for r in rows) == 1
    assert run.tally.records_acquired == 3, "the tally still counts all three"


def test_p48_23_county_reporting_does_not_touch_the_tally_or_the_status():
    """The fix is reporting-only. Nothing about accounting or gates moves."""
    from harvesters.acquisition.run import RunStatus

    run = county_run([{"county": "Harris"}, {"county": "Dallas"}])
    before = dict(run.tally.to_dict())
    run.county_coverage()
    assert run.tally.to_dict() == before
    run.pagination_exhausted = True
    run.tally.records_observed_at_source = 2
    run.finalize(expected_denominator=2)
    assert run.status == RunStatus.COMPLETE
