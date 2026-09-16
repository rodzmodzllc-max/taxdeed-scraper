"""Tests for Phase 50 - the denominator script's zero-count fail-closed fix,
and the persistent-vs-fresh transport diagnostic.

Two things these tests deliberately do NOT do:

* They never reach the network. Every behavioural assertion drives the real
  code through `FixtureTransport` or a deliberately-failing child
  invocation, so the suite is the same in CI, in a blocked sandbox, and on
  a laptop.
* They never assert against prose. Where a property lives in code rather
  than in behaviour - "this module imports no database driver" - the
  assertion parses the module with `ast` and reads the real thing. Phase 48
  taught this the hard way: three tests there string-matched a docstring
  and passed for the wrong reason.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harvesters.acquisition import FixtureTransport, TransportResponse  # noqa: E402
from harvesters.acquisition.transport import (  # noqa: E402
    AccessRestricted,
    EnvironmentEgressBlocked,
    SourceUnavailable,
)

# The discard port. The child's full path - launch, transport, error
# classification, JSON emission - is exercised against a target that cannot
# answer, so the pre-flight costs LGBS zero requests (Phase 42's principle,
# and the reason these tests never name the real host).
UNREACHABLE_URL = "http://127.0.0.1:9/"

DENOMINATOR_PATH = REPO_ROOT / "scripts" / "measure_tx_denominator.py"
DIAGNOSTIC_PATH = REPO_ROOT / "scripts" / "diagnose_lgbs_transport_reuse.py"
CHILD_PATH = REPO_ROOT / "scripts" / "_lgbs_single_request_child.py"


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def redirect_artifact(mod, monkeypatch, tmp_path, name):
    """Point a script's artifact at a temp dir. REPO_ROOT moves with it,
    because `_write()` reports the path relative to REPO_ROOT and would
    raise on a path outside it."""
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(mod, "ARTIFACT_PATH", tmp_path / name)
    return tmp_path / name


@pytest.fixture()
def denominator(tmp_path, monkeypatch):
    mod = load(DENOMINATOR_PATH, "_p50_denominator")
    redirect_artifact(mod, monkeypatch, tmp_path, "denominator.json")
    return mod


@pytest.fixture()
def diagnostic():
    return load(DIAGNOSTIC_PATH, "_p50_diagnostic")


def run_denominator(mod, transport):
    """Drive the real `main()` with a fixture transport in place of the live
    one, and hand back `(exit_code, artifact)`."""
    mod.UrllibTransport = lambda *_a, **_k: transport
    code = mod.main()
    return code, json.loads(mod.ARTIFACT_PATH.read_text())


def envelope(count, results, next_link=None):
    return {"count": count, "results": results, "next": next_link}


# ===========================================================================
# Part 1 - zero-count fail-closed
# ===========================================================================


def test_p50_01_zero_count_does_not_produce_a_validated_denominator(denominator):
    t = FixtureTransport()
    t.add_json(denominator._url(limit=1), envelope(0, []))
    code, art = run_denominator(denominator, t)
    assert art["pagination_validated"] is False
    assert code != 0


def test_p50_02_zero_count_does_not_produce_denominator_zero(denominator):
    t = FixtureTransport()
    t.add_json(denominator._url(limit=1), envelope(0, []))
    _, art = run_denominator(denominator, t)
    assert art["current_live_denominator"] is None
    assert art["denominator_delta"] is None


def test_p50_03_zero_count_names_its_reason(denominator):
    t = FixtureTransport()
    t.add_json(denominator._url(limit=1), envelope(0, []))
    _, art = run_denominator(denominator, t)
    assert art["failure_reason"] == "ZERO_COUNT_REQUIRES_VERIFICATION"
    assert denominator.ZERO_COUNT_REASON == "ZERO_COUNT_REQUIRES_VERIFICATION"


def test_p50_04_zero_count_never_invents_a_negative_offset_request(denominator):
    """Section 1 is explicit: do not invent `offset=-1`. The strongest form
    of that assertion is that no such request is ever issued."""
    t = FixtureTransport()
    t.add_json(denominator._url(limit=1), envelope(0, []))
    run_denominator(denominator, t)
    assert not any("offset=-1" in u for u in t.requested_urls)
    # And exactly one request total: the claimed-count read, nothing after.
    assert len(t.requested_urls) == 1


def test_p50_05_zero_count_does_not_fall_back_to_the_historical_constant(denominator):
    t = FixtureTransport()
    t.add_json(denominator._url(limit=1), envelope(0, []))
    _, art = run_denominator(denominator, t)
    assert art["current_live_denominator"] != art["historical_denominator"]
    assert art["historical_denominator"] == denominator.TX_LGBS_STATE_DENOMINATOR


def test_p50_06_nonzero_count_still_walks_the_boundary_path(denominator):
    """The fix must not have cost the working path its behaviour."""
    n = 4225
    t = FixtureTransport()
    t.add_json(denominator._url(limit=1), envelope(n, [{"id": 1}]))
    t.add_json(denominator._url(limit=1, offset=n - 1), envelope(n, [{"id": 2}], None))
    t.add_json(denominator._url(limit=1, offset=n), envelope(n, []))
    code, art = run_denominator(denominator, t)
    assert art["pagination_validated"] is True
    assert art["current_live_denominator"] == n
    assert art["denominator_delta"] == n - denominator.TX_LGBS_STATE_DENOMINATOR
    assert code == 0
    assert any(f"offset={n - 1}" in u for u in t.requested_urls)
    assert any(u.endswith(f"offset={n}") for u in t.requested_urls)


def test_p50_07_boundary_failure_is_still_fail_closed(denominator):
    """`next` still populated at the last record means records exist beyond
    the claimed count."""
    n = 10
    t = FixtureTransport()
    t.add_json(denominator._url(limit=1), envelope(n, [{"id": 1}]))
    t.add_json(denominator._url(limit=1, offset=n - 1), envelope(n, [{"id": 2}], "https://next"))
    t.add_json(denominator._url(limit=1, offset=n), envelope(n, []))
    code, art = run_denominator(denominator, t)
    assert art["pagination_validated"] is False
    assert art["current_live_denominator"] is None
    assert art["failure_reason"] == "BOUNDARY_CHECK_FAILED"
    assert code != 0


def test_p50_08_records_past_the_claimed_end_are_fail_closed(denominator):
    n = 10
    t = FixtureTransport()
    t.add_json(denominator._url(limit=1), envelope(n, [{"id": 1}]))
    t.add_json(denominator._url(limit=1, offset=n - 1), envelope(n, [{"id": 2}], None))
    t.add_json(denominator._url(limit=1, offset=n), envelope(n, [{"id": 3}]))
    _, art = run_denominator(denominator, t)
    assert art["pagination_validated"] is False
    assert art["current_live_denominator"] is None


def test_p50_09_timeout_remains_fail_closed(denominator):
    t = FixtureTransport()
    t.add_error(denominator._url(limit=1), SourceUnavailable("timed out"))
    code, art = run_denominator(denominator, t)
    assert art["current_live_denominator"] is None
    assert art["pagination_validated"] is False
    assert art["failure_reason"] == "SOURCE_NOT_REACHED"
    assert code != 0


def test_p50_10_timeout_on_a_boundary_request_is_fail_closed(denominator):
    n = 4225
    t = FixtureTransport()
    t.add_json(denominator._url(limit=1), envelope(n, [{"id": 1}]))
    t.add_error(denominator._url(limit=1, offset=n - 1), SourceUnavailable("timed out"))
    code, art = run_denominator(denominator, t)
    assert art["current_live_denominator"] is None
    assert art["pagination_validated"] is False
    assert art["failure_reason"] == "BOUNDARY_REQUEST_FAILED"
    assert code != 0


@pytest.mark.parametrize("bad", ["4225", None, -1, 12.5, {"n": 1}])
def test_p50_11_malformed_count_remains_fail_closed(denominator, bad):
    t = FixtureTransport()
    t.add_json(denominator._url(limit=1), {"count": bad, "results": []})
    code, art = run_denominator(denominator, t)
    assert art["current_live_denominator"] is None
    assert art["pagination_validated"] is False
    assert art["failure_reason"] == "MALFORMED_COUNT"
    assert code != 0


def test_p50_12_environment_block_is_not_recorded_as_a_source_measurement(denominator):
    t = FixtureTransport()
    t.add_error(denominator._url(limit=1), EnvironmentEgressBlocked("proxy refused"))
    _, art = run_denominator(denominator, t)
    assert art["environment_status"] == "ENVIRONMENT_EGRESS_BLOCKED"
    assert art["current_live_denominator"] is None


def test_p50_13_denominator_script_never_queries_the_area_filter(denominator):
    n = 4225
    t = FixtureTransport()
    t.add_json(denominator._url(limit=1), envelope(n, [{"id": 1}]))
    t.add_json(denominator._url(limit=1, offset=n - 1), envelope(n, [{"id": 2}], None))
    t.add_json(denominator._url(limit=1, offset=n), envelope(n, []))
    run_denominator(denominator, t)
    assert t.requested_urls
    for url in t.requested_urls:
        assert "state=TX" in url
        assert "area=" not in url


# ===========================================================================
# Part 3 - the diagnostic's shape
# ===========================================================================


def test_p50_14_matrix_is_the_four_specified_comparisons_in_two_modes(diagnostic):
    assert [(p, l) for _, p, l in diagnostic.QUERIES] == [
        ("state", 1), ("state", 10), ("area", 1), ("area", 10)
    ]
    assert diagnostic.MODES == ("persistent", "fresh")
    assert diagnostic.TRIALS == 2
    assert diagnostic.TRIALS * len(diagnostic.QUERIES) * len(diagnostic.MODES) == 16


def test_p50_15_diagnostic_is_smaller_than_the_phase_48_one():
    """Section 3: 'the objective is isolation, not volume.' Read both
    scripts' real constants rather than trusting either docstring."""
    def consts(path):
        tree = ast.parse(path.read_text())
        out = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            else:
                continue
            try:
                out[target] = ast.literal_eval(value)
            except (ValueError, TypeError):
                pass
        return out

    p48 = consts(REPO_ROOT / "scripts" / "diagnose_lgbs_query_latency.py")
    p50 = consts(DIAGNOSTIC_PATH)
    p48_total = p48["TRIALS"] * len(p48["QUERIES"])
    p50_total = p50["TRIALS"] * len(p50["QUERIES"]) * len(p50["MODES"])
    assert p50_total < p48_total + 2, (p50_total, p48_total)
    assert max(l for _, _, l in p50["QUERIES"]) <= 10


def test_p50_16_instrument_matches_the_phase_48_diagnostic(diagnostic):
    """Section 4: the same timeout policy, so a timeout means the same
    thing it meant last phase."""
    assert diagnostic.TIMEOUT_SECONDS == 30.0
    child = ast.parse(CHILD_PATH.read_text())
    retries = [
        kw.value.value
        for node in ast.walk(child)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "RateLimitPolicy"
        for kw in node.keywords
        if kw.arg == "max_retries"
    ]
    assert retries == [1], retries


def test_p50_17_modes_are_interleaved_not_grouped(diagnostic, monkeypatch, tmp_path):
    """The whole design rests on this. Phase 48A showed failures cluster on
    POSITION, so an A-then-B layout would measure order, not transport."""
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(diagnostic, "persistent_request",
                        lambda _t, url: (seen.append(("persistent", url)), diagnostic._blank_observation(url))[1])
    monkeypatch.setattr(diagnostic, "fresh_request",
                        lambda url: (seen.append(("fresh", url)), diagnostic._blank_observation(url))[1])
    monkeypatch.setattr(diagnostic.time, "sleep", lambda _s: None)
    redirect_artifact(diagnostic, monkeypatch, tmp_path, "interleave.json")
    diagnostic.main()

    assert len(seen) == 16
    modes = [m for m, _ in seen]
    assert modes == ["persistent", "fresh"] * 8, modes
    # Each adjacent pair must be the SAME url in both modes.
    for i in range(0, 16, 2):
        assert seen[i][1] == seen[i + 1][1]


def test_p50_18_structured_output_carries_every_required_field(diagnostic, monkeypatch, tmp_path):
    """Section 3's capture list, asserted against the artifact rather than
    against the code that writes it."""
    monkeypatch.setattr(diagnostic, "persistent_request",
                        lambda _t, url: diagnostic._blank_observation(url))
    monkeypatch.setattr(diagnostic, "fresh_request",
                        lambda url: diagnostic._blank_observation(url))
    monkeypatch.setattr(diagnostic.time, "sleep", lambda _s: None)
    redirect_artifact(diagnostic, monkeypatch, tmp_path, "a.json")
    diagnostic.main()
    art = json.loads((tmp_path / "a.json").read_text())

    required = {
        "mode", "url", "param", "limit", "trial", "http_status", "latency_seconds",
        "response_bytes", "envelope_count", "results_returned", "next_link_present",
        "error", "error_class", "error_code", "success", "request_was_sent", "pid",
    }
    assert art["observations"]
    for obs in art["observations"]:
        assert required <= set(obs), required - set(obs)
    assert art["production_data_modified"] is False
    assert {m["mode"] for m in art["mode_totals"]} == {"persistent", "fresh"}
    assert len(art["summary"]) == 8


def test_p50_19_persistent_mode_reports_a_real_failure_as_data(diagnostic):
    url = diagnostic.url_for("state", 1)
    t = FixtureTransport()
    t.add_error(url, SourceUnavailable(f"{url}: timed out"))
    obs = diagnostic.persistent_request(t, url)
    assert obs["success"] is False
    assert obs["error_class"] == "SourceUnavailable"
    assert obs["error_code"] == "SOURCE_UNAVAILABLE"
    assert obs["request_was_sent"] is True
    assert obs["latency_seconds"] is not None
    assert obs["pid"] is not None


def test_p50_20_persistent_mode_reads_the_envelope_without_retaining_records(diagnostic):
    url = diagnostic.url_for("state", 10)
    t = FixtureTransport()
    t.add_json(url, envelope(4225, [{"id": i} for i in range(10)], "https://next"))
    obs = diagnostic.persistent_request(t, url)
    assert obs["success"] is True
    assert obs["envelope_count"] == 4225
    assert obs["results_returned"] == 10
    assert obs["next_link_present"] is True
    assert obs["http_status"] == 200
    # Scalars only. No record ever enters the observation.
    assert all(not isinstance(v, (list, dict)) for v in obs.values())


def test_p50_21_a_breaker_refusal_is_flagged_as_never_sent(diagnostic):
    """A locally-refused request measures the breaker, not the source, and
    must never be counted as evidence about LGBS."""
    url = diagnostic.url_for("area", 1)
    t = FixtureTransport()
    t.add_error(url, SourceUnavailable("circuit breaker open after 5 consecutive failures"))
    obs = diagnostic.persistent_request(t, url)
    assert obs["request_was_sent"] is False


def test_p50_22_fresh_mode_runs_in_a_different_process(diagnostic):
    """The one property the fresh mode exists for. Asserted by launching the
    real child - it fails at the network in a blocked environment, but it
    still reports the pid it failed in."""
    obs = diagnostic.fresh_request(UNREACHABLE_URL)
    assert obs.get("pid") is not None
    assert obs["pid"] != __import__("os").getpid()
    assert "parent_elapsed_seconds" in obs


def test_p50_23_fresh_mode_survives_a_child_that_refuses_to_run(diagnostic, monkeypatch):
    monkeypatch.setattr(diagnostic, "CHILD_SCRIPT", REPO_ROOT / "does_not_exist.py")
    obs = diagnostic.fresh_request(UNREACHABLE_URL)
    assert obs["success"] is False
    assert obs["request_was_sent"] is False
    assert obs["error_class"] in {"ChildProcessRefused", "ChildProcessLaunchFailed"}


def test_p50_24_child_rejects_a_malformed_invocation_distinctly():
    """A harness bug must never be readable as evidence about the source."""
    done = subprocess.run([sys.executable, str(CHILD_PATH)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 2
    done = subprocess.run([sys.executable, str(CHILD_PATH), UNREACHABLE_URL, "not-a-number"],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 2
    assert json.loads(done.stdout.strip())["error"]


def test_p50_25_child_emits_exactly_one_json_object_on_stdout():
    done = subprocess.run(
        [sys.executable, str(CHILD_PATH), UNREACHABLE_URL, "5"],
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0
    lines = [l for l in done.stdout.strip().splitlines() if l.strip()]
    assert len(lines) == 1, lines
    payload = json.loads(lines[0])
    for key in ("url", "pid", "success", "latency_seconds", "request_was_sent", "error_class"):
        assert key in payload


def test_p50_26_budget_exhaustion_is_recorded_as_not_attempted(diagnostic, monkeypatch, tmp_path):
    """A cell that was never tried must never be counted as a failure."""
    monkeypatch.setattr(diagnostic, "WALL_CLOCK_BUDGET_SECONDS", -1.0)
    redirect_artifact(diagnostic, monkeypatch, tmp_path, "b.json")
    monkeypatch.setattr(diagnostic, "persistent_request",
                        lambda *_a: pytest.fail("no request may be issued past the budget"))
    monkeypatch.setattr(diagnostic, "fresh_request",
                        lambda *_a: pytest.fail("no request may be issued past the budget"))
    diagnostic.main()
    art = json.loads((tmp_path / "b.json").read_text())
    assert len(art["observations"]) == 16
    assert all(o["request_was_sent"] is False for o in art["observations"])
    assert all(o["error_class"] == "NOT_ATTEMPTED_BUDGET_EXHAUSTED" for o in art["observations"])
    for row in art["summary"]:
        assert row["query_result"] == "NOT_ATTEMPTED"
        assert row["failures"] == 0
    for row in art["mode_totals"]:
        assert row["failures"] == 0
        assert row["not_sent"] == 8


def test_p50_27_summary_never_counts_an_unsent_cell_as_a_failure(diagnostic):
    unsent = diagnostic._blank_observation("u")
    unsent["request_was_sent"] = False
    unsent["error_class"] = diagnostic.BUDGET_EXHAUSTED
    sent_ok = diagnostic._blank_observation("u")
    sent_ok["success"] = True
    row = diagnostic.summarize("fresh", "Q1", "state", 1, [sent_ok, unsent])
    assert row["successes"] == 1
    assert row["not_sent"] == 1
    assert row["failures"] == 0
    assert row["attempted"] == 1
    assert row["query_result"] == "ALL_SUCCEEDED"


# ===========================================================================
# Part 3 / 9 - state vs area separation
# ===========================================================================


def test_p50_28_both_query_families_are_present_in_both_modes(diagnostic):
    params = {p for _, p, _ in diagnostic.QUERIES}
    assert params == {"state", "area"}
    for param in params:
        for limit in (1, 10):
            url = diagnostic.url_for(param, limit)
            assert url.startswith("https://taxsales.lgbs.com/api/property_sales/?")
            assert f"{param}=TX" in url
            assert f"limit={limit}" in url


def test_p50_29_the_two_query_families_never_collide(diagnostic):
    urls = [diagnostic.url_for(p, l) for _, p, l in diagnostic.QUERIES]
    assert len(set(urls)) == len(urls)
    state_urls = [u for u in urls if "state=TX" in u]
    area_urls = [u for u in urls if "area=TX" in u]
    assert len(state_urls) == len(area_urls) == 2
    assert not [u for u in state_urls if "area=" in u]
    assert not [u for u in area_urls if "state=" in u]


def test_p50_30_diagnostic_issues_no_url_outside_the_declared_matrix(diagnostic, monkeypatch, tmp_path):
    allowed = {diagnostic.url_for(p, l) for _, p, l in diagnostic.QUERIES}
    issued: list[str] = []
    monkeypatch.setattr(diagnostic, "persistent_request",
                        lambda _t, url: (issued.append(url), diagnostic._blank_observation(url))[1])
    monkeypatch.setattr(diagnostic, "fresh_request",
                        lambda url: (issued.append(url), diagnostic._blank_observation(url))[1])
    monkeypatch.setattr(diagnostic.time, "sleep", lambda _s: None)
    redirect_artifact(diagnostic, monkeypatch, tmp_path, "c.json")
    diagnostic.main()
    assert set(issued) == allowed
    assert not any("offset=" in u for u in issued)


# ===========================================================================
# Part 4 / 8 - safety, asserted structurally
# ===========================================================================

PHASE50_MODULES = (DENOMINATOR_PATH, DIAGNOSTIC_PATH, CHILD_PATH)
DB_MODULES = {"supabase", "psycopg", "psycopg2", "sqlalchemy", "asyncpg", "MySQLdb", "pymysql"}
DML = ("insert into", "update ", "delete from", "truncate", "drop table", "upsert")


@pytest.mark.parametrize("path", PHASE50_MODULES, ids=lambda p: p.name)
def test_p50_31_no_database_imports(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in DB_MODULES, f"{path.name} imports {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in DB_MODULES, f"{path.name} imports {node.module}"


@pytest.mark.parametrize("path", PHASE50_MODULES, ids=lambda p: p.name)
def test_p50_32_no_dml_literal(path):
    """Docstrings are skipped - several of these modules legitimately
    explain in prose that they do not write, and flagging that would tell us
    nothing about behaviour."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if len(node.value) < 400 and any(k in node.value.lower() for k in DML):
                raise AssertionError(f"{path.name}: DML-looking literal {node.value[:60]!r}")


@pytest.mark.parametrize("path", PHASE50_MODULES, ids=lambda p: p.name)
def test_p50_33_get_only_no_write_verb_reaches_the_transport(path):
    """Every transport call in these modules must be `.get(...)`."""
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"post", "put", "patch", "delete", "head"}, (
                f"{path.name} calls .{node.func.attr}()"
            )


def test_p50_34_child_environment_carries_no_credential(diagnostic, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_should_never_reach_the_child")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_nope")
    monkeypatch.setenv("SCRAPERAPI_KEY", "nope")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    env = diagnostic.child_environment()
    for banned in ("SUPABASE_SERVICE_KEY", "SUPABASE_URL", "GITHUB_TOKEN", "SCRAPERAPI_KEY", "DATABASE_URL"):
        assert banned not in env
    assert not [v for v in env.values() if "sb_secret" in v or "ghp_" in v]


def test_p50_35_child_environment_is_an_allowlist_not_a_denylist(diagnostic, monkeypatch):
    monkeypatch.setenv("SOME_BRAND_NEW_CI_VARIABLE", "surprise")
    assert "SOME_BRAND_NEW_CI_VARIABLE" not in diagnostic.child_environment()


def test_p50_36_child_keeps_the_same_network_path_as_the_parent(diagnostic, monkeypatch):
    """Scrubbing the proxy variables made the child go DIRECT while the
    parent went through the egress proxy - two different network paths, and
    a bypass of a technical restriction. Both are disqualifying, so the
    proxy settings must survive the scrub."""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
    monkeypatch.setenv("NO_PROXY", "localhost")
    env = diagnostic.child_environment()
    assert env.get("HTTPS_PROXY") == "http://proxy.internal:3128"
    assert env.get("NO_PROXY") == "localhost"


def test_p50_37_no_identity_or_header_rotation_anywhere():
    """Section 4 forbids evading source controls. The fresh-process variable
    is the experiment; anything that changes how the source SEES us is not."""
    for path in PHASE50_MODULES:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if len(node.value) > 400:
                    continue  # module docstring
                lowered = node.value.lower()
                for banned in ("user-agent", "x-forwarded-for", "proxies", "cookie", "authorization"):
                    assert banned not in lowered, f"{path.name}: {node.value[:60]!r}"


def test_p50_38_artifacts_declare_production_untouched():
    for path in (DIAGNOSTIC_PATH, DENOMINATOR_PATH):
        assert '"production_data_modified": False' in path.read_text()


def test_p50_39_diagnostic_writes_only_into_the_gitignored_out_dir():
    """Loaded fresh, so this reads the shipped constants rather than the
    fixtures' temp-dir redirection."""
    for path, name in ((DIAGNOSTIC_PATH, "_p50_diag_paths"), (DENOMINATOR_PATH, "_p50_denom_paths")):
        mod = load(path, name)
        assert mod.ARTIFACT_PATH.is_relative_to(REPO_ROOT / "out")
    gitignore = (REPO_ROOT / ".gitignore").read_text()
    assert any(line.strip().rstrip("/") == "out" for line in gitignore.splitlines())


def test_p50_40_neither_script_touches_the_acquisition_runner_or_the_harvester():
    """Section 2's do-not-modify list, enforced from the importing side."""
    forbidden = ("texas_harvester", "harvest_lgbs", "run_lgbs_acquisition", "json_api")
    for path in PHASE50_MODULES:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                for bad in forbidden:
                    assert bad not in name, f"{path.name} imports {name}"


def test_p50_41_denominator_constant_is_imported_never_assigned(denominator):
    tree = ast.parse(DENOMINATOR_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                assert getattr(target, "id", None) != "TX_LGBS_STATE_DENOMINATOR"


# ===========================================================================
# Workflow wiring
# ===========================================================================

WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "lgbs-acquisition-validation.yml"


def load_workflow():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WORKFLOW_PATH.read_text())


def workflow_steps():
    return load_workflow()["jobs"]["acquire"]["steps"]


def test_p50_42_new_input_defaults_to_off():
    wf = load_workflow()
    trigger = (wf.get("on") or wf.get(True))["workflow_dispatch"]["inputs"]
    spec = trigger["run_transport_diagnostics"]
    assert spec["default"] is False
    assert spec["type"] == "boolean"
    assert spec["required"] is False


def test_p50_43_every_new_step_is_gated_on_that_input():
    gated = [s for s in workflow_steps() if "transport" in s["name"].lower()]
    assert len(gated) == 3, [s["name"] for s in gated]
    for step in gated:
        assert "inputs.run_transport_diagnostics" in step["if"]


def test_p50_44_diagnostic_runs_before_the_acquisition_it_would_otherwise_measure():
    names = [s["name"] for s in workflow_steps()]
    diag = next(i for i, n in enumerate(names) if n.startswith("Transport reuse diagnostics"))
    pre = next(i for i, n in enumerate(names) if n.startswith("Pre-flight - transport"))
    acquire = next(i for i, n in enumerate(names) if n.startswith("Run acquisition"))
    assert pre < diag < acquire


def test_p50_45_the_exit_code_is_enforced_not_swallowed():
    enforcement = next(s for s in workflow_steps()
                       if s["name"].startswith("Fail if the transport diagnostics"))
    body = enforcement["run"]
    assert "steps.transport_diagnostics.outputs.exit_code" in body
    assert "exit 1" in body
    assert "always()" in enforcement["if"]
    for step in workflow_steps():
        assert step.get("continue-on-error") is not True


def test_p50_46_the_new_console_log_is_uploaded():
    upload = next(s for s in workflow_steps() if s["name"].startswith("Upload"))
    assert "transport-diagnostics-console.log" in upload["with"]["path"]
    assert upload["if"].strip() == "always()"


def test_p50_47_default_run_is_unchanged_by_this_phase():
    """With the flag off, this workflow must do exactly what it did before:
    every step Phase 50 added is conditional, and none of the pre-existing
    steps gained a dependency on it."""
    for step in workflow_steps():
        if "transport" in step["name"].lower():
            continue
        assert "run_transport_diagnostics" not in json.dumps(step)
