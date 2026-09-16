"""Phase 45. Two things are under test here and they are deliberately kept
apart:

  1. The validation HARNESS - the workflow's new optional `limit` input and
     the shell that turns it into the runner's `--limit N`. These tests
     execute the workflow's real shell rather than string-matching it,
     because the interesting failure modes (a blank input silently becoming
     0, an invalid value falling back to 25 and looking like a successful
     run) are behaviours, not substrings.

  2. The DENOMINATOR MEASUREMENT script - specifically that it cannot quietly
     turn the historical 4,205 carry-forward into a live figure. The whole
     reason this script exists is to keep those two numbers apart, so the
     tests assert the separation structurally, not by reading comments.

Nothing here touches production code. `harvest_lgbs()` and the acquisition
runner are asserted unchanged where relevant.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml is required to parse the workflow under test")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lgbs-acquisition-validation.yml"
RUNNER = REPO_ROOT / "scripts" / "run_lgbs_acquisition.py"
MEASURE = REPO_ROOT / "scripts" / "measure_tx_denominator.py"


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def triggers() -> dict:
    d = workflow()
    return d.get(True) or d.get("on")


def steps() -> list[dict]:
    return workflow()["jobs"]["acquire"]["steps"]


def step_named(prefix: str) -> dict:
    for s in steps():
        if s.get("name", "").startswith(prefix):
            return s
    raise AssertionError(f"no step starting with {prefix!r}")


def run_mode_shell(mode: str, limit: str | None) -> subprocess.CompletedProcess:
    """Execute the acquisition step's REAL shell, stopping short of invoking
    python, and report the ARGS it would have passed. This is the only way to
    test the input handling rather than its appearance."""
    script = step_named("Run acquisition")["run"]
    script = script.replace("${{ inputs.mode }}", "$MODE")
    # Cut the actual invocation - we want the decision, not the network call.
    cut = script.index('echo "invoking')
    script = script[:cut] + 'echo "ARGS=$ARGS"\n'
    env = {"MODE": mode, "PATH": "/usr/bin:/bin"}
    if limit is not None:
        env["INPUT_LIMIT"] = limit
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)


# ===========================================================================
# 1. The limit input exists and is optional
# ===========================================================================


def test_p45_01_limit_input_exists_and_is_optional():
    inputs = triggers()["workflow_dispatch"]["inputs"]
    assert "limit" in inputs, "Phase 45 added an optional `limit` input; it is missing"
    limit = inputs["limit"]
    assert limit.get("required") is False
    assert limit.get("default") == ""


def test_p45_02_workflow_is_still_dispatch_only():
    """The harness change must not have bought a limit input at the cost of
    an automatic trigger."""
    t = triggers()
    assert list(t.keys()) == ["workflow_dispatch"]
    for forbidden in ("schedule", "push", "pull_request", "repository_dispatch", "workflow_call"):
        assert forbidden not in t


def test_p45_03_existing_inputs_survived():
    inputs = triggers()["workflow_dispatch"]["inputs"]
    # Phase 48 added `run_diagnostics`. The pin moves with it deliberately -
    # its job is to catch an input nobody meant to add, not to freeze the set.
    assert set(inputs) == {"mode", "confirm_full", "limit", "run_diagnostics"}
    assert inputs["mode"]["options"] == ["probe", "sample", "full"]
    assert inputs["mode"]["default"] == "probe"


# ===========================================================================
# 2. The limit actually propagates - executed, not string-matched
# ===========================================================================


def test_p45_04_limit_omitted_preserves_the_historical_25():
    got = run_mode_shell("sample", None)
    assert got.returncode == 0, got.stderr
    assert "ARGS=--limit 25" in got.stdout


def test_p45_05_empty_limit_preserves_the_historical_25():
    """An empty string is what GitHub sends for an untouched optional input -
    it must mean 'default', never 'zero'."""
    got = run_mode_shell("sample", "")
    assert got.returncode == 0, got.stderr
    assert "ARGS=--limit 25" in got.stdout


def test_p45_06_limit_25_is_passed_through():
    got = run_mode_shell("sample", "25")
    assert got.returncode == 0, got.stderr
    assert "ARGS=--limit 25" in got.stdout


def test_p45_07_limit_501_crosses_the_page_boundary():
    """501 is the point of the whole change: LGBS_PAGE_SIZE is 500, so this
    is the smallest limit that forces a second page."""
    got = run_mode_shell("sample", "501")
    assert got.returncode == 0, got.stderr
    assert "ARGS=--limit 501" in got.stdout


@pytest.mark.parametrize("bad", ["abc", "-1", "2.5", "25; rm -rf /", "0x20", " 25", "1e3"])
def test_p45_08_invalid_limit_fails_the_job(bad):
    """A bad limit must FAIL, not fall back to 25. A silent fallback would
    make a typo indistinguishable from a deliberate 25-record run."""
    got = run_mode_shell("sample", bad)
    assert got.returncode != 0, f"limit={bad!r} was accepted; stdout={got.stdout!r}"
    assert "ARGS=--limit" not in got.stdout


def test_p45_09_zero_and_oversized_limits_are_refused():
    for bad in ("0", "5001", "100000"):
        got = run_mode_shell("sample", bad)
        assert got.returncode != 0, f"limit={bad!r} was accepted"


def test_p45_10_limit_is_ignored_for_probe_and_full():
    probe = run_mode_shell("probe", "501")
    assert probe.returncode == 0
    assert "ARGS=--probe-only" in probe.stdout

    full = run_mode_shell("full", "501")
    assert full.returncode == 0
    assert "ARGS=--full" in full.stdout, "limit must not change what --full means"


def test_p45_11_limit_reaches_the_shell_through_env_not_interpolation():
    """`${{ inputs.limit }}` pasted into a command line is a shell-injection
    surface. It must arrive as an environment variable instead."""
    step = step_named("Run acquisition")
    assert step.get("env", {}).get("INPUT_LIMIT") == "${{ inputs.limit }}"
    assert "${{ inputs.limit }}" not in step["run"]


# ===========================================================================
# 3. Full-mode confirmation is untouched
# ===========================================================================


def test_p45_12_full_mode_still_requires_explicit_confirmation():
    guard = step_named("Guard - full mode")
    assert guard["if"] == "inputs.mode == 'full'"
    assert "confirm_full" in guard["run"]
    assert '!= "FULL"' in guard["run"]
    assert "exit 1" in guard["run"]


def test_p45_13_guard_still_precedes_the_network_step():
    names = [s.get("name", "") for s in steps()]
    guard = next(i for i, n in enumerate(names) if n.startswith("Guard - full mode"))
    acquire = next(i for i, n in enumerate(names) if n.startswith("Run acquisition"))
    preflight = next(i for i, n in enumerate(names) if n.startswith("Pre-flight"))
    assert preflight < acquire
    assert guard < acquire


# ===========================================================================
# 4. The denominator step
# ===========================================================================


def test_p45_14_denominator_step_exists_and_skips_probe():
    """Corrected in Phase 46. This originally pinned the condition as exactly
    `inputs.mode != 'probe'`, which encoded a flaw: without `always()`, a
    failed acquisition step cancels this one, and that is precisely what
    happened on run 35109232214 - the measurement was lost to a failure it
    has nothing to do with. The assertion now pins the corrected condition
    and keeps checking both halves of it."""
    step = step_named("Measure live TX denominator")
    assert step["if"] == "always() && inputs.mode != 'probe'"
    assert "always()" in step["if"], "acquisition failing must not cancel the measurement"
    assert "inputs.mode != 'probe'" in step["if"], "probe stays minimal"
    assert "scripts/measure_tx_denominator.py" in step["run"]


def test_p45_15_denominator_step_adds_no_logic_to_yaml():
    """Same rule as Phase 42: the YAML is an execution environment, not a
    second implementation."""
    step = step_named("Measure live TX denominator")
    body = "\n".join(l for l in step["run"].splitlines() if not l.strip().startswith("#"))
    for forbidden in ("curl ", "wget ", "urllib", "taxsales.lgbs.com", "state=TX"):
        assert forbidden not in body


def test_p45_16_workflow_still_uses_no_secrets():
    assert "secrets." not in WORKFLOW.read_text(encoding="utf-8")


# ===========================================================================
# 5. The measurement script cannot launder the historical constant
# ===========================================================================


def measure_tree() -> ast.Module:
    return ast.parse(MEASURE.read_text(encoding="utf-8"))


def test_p45_17_measurement_queries_state_tx_not_area_tx():
    src = MEASURE.read_text(encoding="utf-8")
    assert "state=TX" in src
    # area=TX is the acquisition query and is NOT a state filter. If the
    # measurement ever used it, the figure would include Pennsylvania.
    assert "area=TX" not in src.replace("`?area=TX`", "")


def test_p45_18_measurement_never_assigns_the_historical_constant():
    """It may READ TX_LGBS_STATE_DENOMINATOR to report a delta. It must never
    write it - that is how a carry-forward gets laundered into 'live'."""
    for node in ast.walk(measure_tree()):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assert target.id != "TX_LGBS_STATE_DENOMINATOR"
                if isinstance(target, ast.Attribute):
                    assert target.attr != "TX_LGBS_STATE_DENOMINATOR"


def test_p45_19_historical_and_live_are_separate_artifact_fields():
    src = MEASURE.read_text(encoding="utf-8")
    for field in ("historical_denominator", "current_live_denominator",
                  "denominator_delta", "measurement_timestamp",
                  "pagination_validated", "pagination_evidence"):
        assert f'"{field}"' in src, f"artifact must carry {field} as its own field"


def test_p45_20_measurement_has_no_production_write_path():
    tree = measure_tree()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                assert not any(k in (m or "").lower() for k in
                               ("supabase", "psycopg", "sqlalchemy", "asyncpg", "pg8000", "requests"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value.strip().upper()
            assert not v.startswith(("INSERT ", "UPDATE ", "DELETE ", "UPSERT ", "DROP ", "TRUNCATE "))


def test_p45_21_measurement_does_not_assume_page_one_is_the_whole_dataset():
    """The completeness proof is the point. Both offset probes must exist."""
    src = MEASURE.read_text(encoding="utf-8")
    assert "offset=claimed - 1" in src or "offset=claimed-1" in src
    assert "offset=claimed)" in src
    assert "_url(limit=1, offset=claimed - 1)" in src
    assert "_url(limit=1, offset=claimed)" in src


def test_p45_22_unverified_count_is_not_recorded_as_a_denominator():
    """If completeness cannot be confirmed, `current_live_denominator` must
    stay None rather than holding an unverified number."""
    src = MEASURE.read_text(encoding="utf-8")
    body = src[src.index("validated = bool("):]
    assert 'artifact["current_live_denominator"] = claimed' in body
    assert body.index("if validated:") < body.index('artifact["current_live_denominator"] = claimed')


def test_p45_23_url_builder_is_correct():
    import importlib.util
    spec = importlib.util.spec_from_file_location("measure_tx_denominator", MEASURE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._url(limit=1) == "https://taxsales.lgbs.com/api/property_sales/?state=TX&limit=1"
    assert mod._url(limit=1, offset=0).endswith("&offset=0"), "offset 0 must not be dropped as falsy"
    assert mod._url(limit=1, offset=4204).endswith("&offset=4204")


# ===========================================================================
# 6. Production code is untouched by this phase
# ===========================================================================


def test_p45_24_acquisition_runner_still_stamps_the_historical_constant():
    """Phase 45 deliberately did NOT change this. The runner still reports
    the carry-forward in `records_observed_at_source`; the live figure lives
    in a separate artifact. If someone 'fixes' this by assigning the measured
    value here, the two numbers become indistinguishable again."""
    src = RUNNER.read_text(encoding="utf-8")
    assert "run.tally.records_observed_at_source = TX_LGBS_STATE_DENOMINATOR" in src


def test_p45_25_harvest_lgbs_untouched_by_this_phase():
    src = (REPO_ROOT / "harvesters" / "texas_harvester.py").read_text(encoding="utf-8")
    assert "def harvest_lgbs(" in src
    assert "LGBS_PAGE_SIZE = 500" in src
    assert '"Scheduled for Auction": "auction"' in src
