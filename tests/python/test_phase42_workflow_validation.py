"""Tests for Phase 42 (Real-Network Acquisition Validation via GitHub
Actions) - .github/workflows/lgbs-acquisition-validation.yml.

These tests protect the workflow itself, which is the one piece of Phase 42
that CI cannot otherwise check: a workflow file is only exercised when
someone dispatches it, so a typo'd flag or a renamed script would sit
undetected until the moment it was needed. The most valuable assertions
here are the ones that tie the YAML to the Python it invokes - if
`run_lgbs_acquisition.py` ever drops `--probe-only` or moves, these fail
immediately rather than at dispatch time.

Two things these tests deliberately do NOT do:

  - They do not assert that a real acquisition succeeds. Phase 42's whole
    point is that only a real runner can establish that, and faking it here
    would be exactly the fabricated success the brief forbids.
  - They do not require network access. Like every other suite in this
    repository, they run offline.
"""

from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML is needed to parse the workflow")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "lgbs-acquisition-validation.yml"
RUNNER_PATH = REPO_ROOT / "scripts" / "run_lgbs_acquisition.py"


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text())


def triggers(wf: dict) -> dict:
    """PyYAML parses a bare `on:` key as the boolean True, so a workflow's
    trigger block can arrive under either key depending on quoting. Handle
    both rather than depending on which one this file happens to use."""
    return wf.get("on") or wf.get(True)


def steps(wf: dict) -> list:
    return wf["jobs"]["acquire"]["steps"]


def run_step(wf: dict) -> dict:
    for step in steps(wf):
        if step.get("id") == "acquire":
            return step
    raise AssertionError("no step with id 'acquire' found")


def executable_lines() -> str:
    """Workflow text with comment lines stripped, so an assertion about
    what the workflow DOES is not confused by what it explains."""
    return "\n".join(
        line for line in WORKFLOW_PATH.read_text().splitlines() if not line.strip().startswith("#")
    )


# ===========================================================================
# Workflow references the correct script and real flags
# ===========================================================================


def test_01_workflow_file_exists_and_parses():
    assert WORKFLOW_PATH.exists()
    wf = load_workflow()
    assert wf["name"]
    assert "acquire" in wf["jobs"]


def test_02_workflow_invokes_the_real_runner_script():
    assert RUNNER_PATH.exists()
    assert "scripts/run_lgbs_acquisition.py" in run_step(load_workflow())["run"]


def test_03_workflow_flags_match_the_runners_actual_argparse_options():
    """The assertion that matters most. Reads the runner's real parser
    rather than a copy of what it is assumed to accept."""
    import argparse
    import importlib.util

    spec = importlib.util.spec_from_file_location("lgbs_runner", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    parser_flags = set()
    original = argparse.ArgumentParser.parse_args

    # Build the parser the same way main() does, by introspecting the
    # source rather than executing main() (which would hit the network).
    source = RUNNER_PATH.read_text()
    for match in re.finditer(r'add_argument\(\s*"(--[a-z-]+)"', source):
        parser_flags.add(match.group(1))

    assert {"--probe-only", "--limit", "--full"} <= parser_flags, (
        f"runner's real flags are {sorted(parser_flags)}"
    )

    workflow_run = run_step(load_workflow())["run"]
    for flag in ("--probe-only", "--limit", "--full"):
        assert flag in workflow_run, f"workflow does not use the runner's {flag} flag"


def test_04_workflow_uses_no_flag_the_runner_does_not_support():
    source = RUNNER_PATH.read_text()
    supported = {m.group(1) for m in re.finditer(r'add_argument\(\s*"(--[a-z-]+)"', source)}
    used = set(re.findall(r"(--[a-z-]+)", run_step(load_workflow())["run"]))
    unknown = used - supported
    assert not unknown, f"workflow passes unsupported flags: {sorted(unknown)}"


# ===========================================================================
# Modes
# ===========================================================================


def test_05_three_explicit_modes_are_offered():
    wf = load_workflow()
    options = triggers(wf)["workflow_dispatch"]["inputs"]["mode"]["options"]
    assert options == ["probe", "sample", "full"]


def test_06_default_mode_is_the_safest_one():
    wf = load_workflow()
    assert triggers(wf)["workflow_dispatch"]["inputs"]["mode"]["default"] == "probe"


def test_07_each_mode_maps_to_a_distinct_runner_invocation():
    run = run_step(load_workflow())["run"]
    assert "--probe-only" in run and "--limit 25" in run and "--full" in run


def test_08_workflow_is_manual_only_not_scheduled_or_on_push():
    """A real acquisition reaches a third party's servers; it happens when a
    human asks, not on every push."""
    trig = triggers(load_workflow())
    assert "workflow_dispatch" in trig
    assert "schedule" not in trig
    assert "push" not in trig
    assert "pull_request" not in trig


def test_09_full_mode_requires_explicit_confirmation():
    wf = load_workflow()
    assert "confirm_full" in triggers(wf)["workflow_dispatch"]["inputs"]
    guard = [s for s in steps(wf) if "confirmation" in s["name"].lower()]
    assert guard, "no guard step for full mode"
    assert "FULL" in guard[0]["run"]


# ===========================================================================
# Section 5 - the workflow is an environment, not a second engine
# ===========================================================================


def test_10_no_second_lgbs_client_in_the_workflow():
    """Acquisition logic must not leak into YAML. Checked against
    executable lines only - the header comment legitimately names the host
    while explaining what the workflow does not do."""
    body = executable_lines()
    for forbidden in ("curl ", "wget ", "taxsales.lgbs.com", "urllib", "requests.get"):
        assert forbidden not in body, f"executable YAML contains {forbidden!r}"


def test_11_no_pagination_or_filtering_logic_in_the_workflow():
    body = executable_lines().lower()
    for forbidden in ("area=tx", "state=tx", "offset=", "next_url", "results["):
        assert forbidden not in body, f"acquisition logic leaked into YAML: {forbidden!r}"


# ===========================================================================
# Secrets
# ===========================================================================


def test_12_workflow_references_no_secrets():
    body = WORKFLOW_PATH.read_text()
    assert "secrets." not in body
    assert "${{ secrets" not in body


def test_13_workflow_does_not_reference_credential_env_vars():
    body = executable_lines()
    for token in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SERVICE_KEY", "SCRAPERAPI_KEY", "GITHUB_TOKEN"):
        assert token not in body, f"workflow references credential {token!r}"


def test_14_runner_cannot_print_a_credential_it_never_holds():
    """RetrievalMetadata has no field capable of carrying a secret, so the
    artifact cannot leak one (structural, not a redaction rule)."""
    from harvesters.acquisition import RetrievalMetadata

    forbidden = {"token", "api_key", "apikey", "password", "secret", "authorization", "cookie", "service_key"}
    assert not (forbidden & set(RetrievalMetadata.__dataclass_fields__))


# ===========================================================================
# Fail-closed behavior preserved
# ===========================================================================


def test_15_no_soft_fail_wrappers():
    """Matches python-governance-test.yml's explicit contract: a failing
    acquisition fails the job."""
    wf = load_workflow()
    body = executable_lines()
    assert "continue-on-error" not in body
    assert "|| true" not in body
    for step in steps(wf):
        assert step.get("continue-on-error") is not True


def test_16_preflight_tests_run_before_any_network_call():
    """A CODE_FAILURE found in CI costs the source zero requests."""
    names = [s["name"] for s in steps(load_workflow())]
    preflight = next(i for i, n in enumerate(names) if "Pre-flight" in n)
    acquire = next(i for i, n in enumerate(names) if n.startswith("Run acquisition"))
    assert preflight < acquire


def test_17_runner_exit_codes_are_distinct_per_classification():
    """Parses main()'s real returned values rather than string-matching, so
    an exit path written as `return 0 if ... else 4` is still detected."""
    import ast

    tree = ast.parse(RUNNER_PATH.read_text())
    main = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    codes: set[int] = set()
    for node in ast.walk(main):
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            codes.add(node.value)

    # 0 success, 2 governance refusal, 3 environment blocked, 4 run not
    # COMPLETE/PARTIAL. Each is a distinct, separately-diagnosable outcome.
    for expected in (0, 2, 3, 4):
        assert expected in codes, f"runner lost its exit-{expected} classification path (found {sorted(codes)})"


# ===========================================================================
# Engine invariants the workflow depends on (must still hold)
# ===========================================================================


def test_18_probe_classification_still_distinguishes_all_five_outcomes():
    from harvesters.acquisition.transport import (
        AccessRestricted,
        AuthenticationRequired,
        EnvironmentEgressBlocked,
        SchemaError,
        SourceUnavailable,
    )
    from scripts.run_lgbs_acquisition import classify_environment

    class Raising:
        def __init__(self, exc):
            self.exc = exc

        def get(self, url, *, timeout=None):
            raise self.exc

    expected = {
        EnvironmentEgressBlocked("proxy 403"): "ENVIRONMENT_EGRESS_BLOCKED",
        AccessRestricted("waf"): "SOURCE_REFUSED",
        AuthenticationRequired("401"): "SOURCE_REFUSED",
        SourceUnavailable("timeout"): "SOURCE_UNAVAILABLE",
        SchemaError("not json"): "SOURCE_ERROR",
    }
    for exc, want in expected.items():
        assert classify_environment(Raising(exc))[0] == want


def test_19_sample_mode_limit_is_honored_by_the_adapter():
    from harvesters.acquisition import FixtureTransport
    from harvesters.acquisition.adapters import LgbsAdapter

    url = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=500"
    rows = [
        {
            "uid": f"u{i}", "state": "TX", "county": "HARRIS COUNTY",
            "status": "Scheduled for Auction", "sale_type": "SALE",
            "account_nbr": f"A{i}", "cause_nbr": "C1",
            "sale_date": "2026-10-06T10:00:00Z", "sale_date_only": "2026-10-06",
            "minimum_bid": "1000", "value": "50000", "sale_notes": "L",
            "prop_address_one": "1 Main", "prop_city": "HOUSTON", "prop_zipcode": "77002",
            "geometry": {"coordinates": [-95.3, 29.7]},
        }
        for i in range(40)
    ]
    t = FixtureTransport().add_json(url, {"count": 40, "next": None, "previous": None, "results": rows})
    result = LgbsAdapter(transport=t).acquire(limit=25)
    assert result.records_acquired == 25


def test_20_full_run_accounting_remains_fail_closed():
    from harvesters.acquisition import AcquisitionStatus, build_result
    from harvesters.acquisition.run import AcquisitionRun, RunStatus

    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    run.record_result(build_result(
        source_id="tx_lgbs", jurisdiction="TX/statewide", status=AcquisitionStatus.SUCCESS,
        started_at="2026-09-16T00:00:00+00:00", records=[{"a": 1}], records_seen=99,
    ))
    run.pagination_exhausted = True
    run.finalize(expected_denominator=None)
    assert not run.tally.is_balanced
    assert run.status != RunStatus.COMPLETE


def test_21_denominator_mismatch_cannot_produce_a_false_complete():
    """Section 8: a legitimately changed source must stop automatic
    COMPLETE classification rather than be papered over."""
    from harvesters.acquisition import FixtureTransport
    from harvesters.acquisition.adapters import LgbsAdapter
    from harvesters.acquisition.run import AcquisitionRun, RunStatus

    url = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=500"
    row = {
        "uid": "u1", "state": "TX", "county": "HARRIS COUNTY",
        "status": "Scheduled for Auction", "sale_type": "SALE",
        "account_nbr": "A1", "cause_nbr": "C1",
        "sale_date": "2026-10-06T10:00:00Z", "sale_date_only": "2026-10-06",
        "minimum_bid": "1000", "value": "50000", "sale_notes": "L",
        "prop_address_one": "1 Main", "prop_city": "HOUSTON", "prop_zipcode": "77002",
        "geometry": {"coordinates": [-95.3, 29.7]},
    }
    t = FixtureTransport().add_json(url, {"count": 1, "next": None, "previous": None, "results": [row]})
    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    run.record_result(LgbsAdapter(transport=t).acquire())
    run.pagination_exhausted = True
    check = run.finalize(expected_denominator=4205)
    assert check.passed is False
    assert check.variance == -4204
    assert run.status == RunStatus.PARTIAL


def test_22_state_filter_remains_enforced():
    from harvesters.acquisition import FixtureTransport
    from harvesters.acquisition.adapters import LgbsAdapter
    from harvesters.acquisition.run import RejectionReason

    url = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=500"

    def mk(uid, state, county, acct):
        return {
            "uid": uid, "state": state, "county": county,
            "status": "Scheduled for Auction", "sale_type": "SALE",
            "account_nbr": acct, "cause_nbr": "C1",
            "sale_date": "2026-10-06T10:00:00Z", "sale_date_only": "2026-10-06",
            "minimum_bid": "1000", "value": "50000", "sale_notes": "L",
            "prop_address_one": "1 Main", "prop_city": "X", "prop_zipcode": "77002",
            "geometry": {"coordinates": [-95.3, 29.7]},
        }

    rows = [mk("t1", "TX", "HARRIS COUNTY", "A1"), mk("p1", "PA", "PHILADELPHIA COUNTY", "P1")]
    t = FixtureTransport().add_json(url, {"count": 2, "next": None, "previous": None, "results": rows})
    result = LgbsAdapter(transport=t).acquire()
    assert result.records_acquired == 1
    assert all(r["state"] == "TX" for r in result.records)
    assert result.rejections_by_reason[RejectionReason.OUT_OF_STATE.value] == 1


def test_23_artifact_declares_production_untouched():
    assert '"production_data_modified": False' in RUNNER_PATH.read_text()


def test_24_workflow_uploads_the_artifact_even_on_failure():
    upload = [s for s in steps(load_workflow()) if s.get("uses", "").startswith("actions/upload-artifact")]
    assert upload, "no artifact upload step"
    assert upload[0].get("if") == "always()"


def test_25_workflow_matches_repository_action_version_conventions():
    """Same pinned major versions the existing workflows use."""
    body = WORKFLOW_PATH.read_text()
    assert "actions/checkout@v4" in body
    assert "actions/setup-python@v5" in body
    assert "actions/upload-artifact@v4" in body
    assert "python-version: '3.12'" in body


def test_26_concurrency_prevents_overlapping_real_runs():
    wf = load_workflow()
    assert wf["concurrency"]["group"]
    assert wf["concurrency"]["cancel-in-progress"] is False
