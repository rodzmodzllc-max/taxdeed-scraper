#!/usr/bin/env python3
"""Controlled tx_lgbs acquisition runner - Phase 41.

The operational entry point for a real-network `tx_lgbs` acquisition. It is
deliberately a *runner*, not a pipeline: it acquires, validates and writes
an artifact, and it has no path to the production dataset at all (Phase 41
Section 16). There is no Supabase client, no credential read, and no write
outside the artifact directory.

Order of operations, and why:

  1. **Environment probe first.** Before anything else, one request
     establishes whether this environment can reach the source at all, and
     classifies the outcome into exactly one of NETWORK_AVAILABLE /
     ENVIRONMENT_EGRESS_BLOCKED / SOURCE_UNAVAILABLE / SOURCE_REFUSED /
     SOURCE_ERROR. Attributing a local proxy policy to LGBS would poison the
     source-health record with a finding that says nothing about LGBS, so
     this classification happens before any acquisition logic runs.

  2. **Governance gate second.** The existing Phase 10A/34A/37 gates decide,
     unchanged. If `tx_lgbs` ever stops passing, this script stops - it has
     no bypass and no override flag.

  3. **Controlled sample third.** A small `--limit` run proves the path
     before any full walk. Phase 41 Section 5 requires the sample to
     succeed before expansion.

  4. **Full acquisition last**, validated against the independently measured
     4,205 Texas denominator - never against a number this run produced.

Usage:
    python3 scripts/run_lgbs_acquisition.py --probe-only
    python3 scripts/run_lgbs_acquisition.py --limit 25
    python3 scripts/run_lgbs_acquisition.py --full
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harvesters.acquisition import (  # noqa: E402
    AcquisitionPurpose,
    AcquisitionStatus,
    RateLimitPolicy,
    UrllibTransport,
    check_acquisition_policy,
)
from harvesters.acquisition.adapters import LgbsAdapter  # noqa: E402
from harvesters.acquisition.run import (  # noqa: E402
    TX_LGBS_STATE_DENOMINATOR,
    AcquisitionRun,
    RunStatus,
)
from harvesters.acquisition.transport import (  # noqa: E402
    AccessRestricted,
    AuthenticationRequired,
    EnvironmentEgressBlocked,
    SchemaError,
    SourceUnavailable,
    TransportError,
)

ARTIFACT_DIR = REPO_ROOT / "out" / "acquisition"

# The fields Phase 41 Section 13 requires field-level completeness for.
COMPLETENESS_FIELDS = (
    "case_no",
    "parcel",
    "address",
    "county",
    "auction_date",
    "min_bid",
    "cad_market_value",
    "legal_description",
    "_source_record_id",
    "_source_status",
)


def classify_environment(transport) -> tuple[str, str]:
    """Phase 41 Section 2's required five-way classification. Returns
    `(status, detail)`.

    The distinction that matters most: an egress proxy refusing CONNECT is
    ENVIRONMENT_EGRESS_BLOCKED, never SOURCE_REFUSED. The source never saw
    the request."""
    probe_url = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=1"
    try:
        response = transport.get(probe_url, timeout=20)
    except EnvironmentEgressBlocked as exc:
        return "ENVIRONMENT_EGRESS_BLOCKED", str(exc)
    except AccessRestricted as exc:
        return "SOURCE_REFUSED", str(exc)
    except AuthenticationRequired as exc:
        return "SOURCE_REFUSED", f"authentication required: {exc}"
    except SourceUnavailable as exc:
        return "SOURCE_UNAVAILABLE", str(exc)
    except SchemaError as exc:
        return "SOURCE_ERROR", str(exc)
    except TransportError as exc:
        return "SOURCE_ERROR", str(exc)

    try:
        payload = response.json()
    except SchemaError as exc:
        return "SOURCE_ERROR", f"response was not valid JSON: {exc}"
    if "results" not in payload:
        return "SOURCE_ERROR", "response envelope has no 'results' key"
    return "NETWORK_AVAILABLE", f"HTTP {response.http_status}, count={payload.get('count')}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled tx_lgbs acquisition")
    parser.add_argument("--probe-only", action="store_true", help="classify the environment and exit")
    parser.add_argument("--limit", type=int, default=None, help="controlled sample size")
    parser.add_argument("--full", action="store_true", help="full Texas acquisition")
    args = parser.parse_args()

    started = datetime.now(timezone.utc).isoformat()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    # Conservative pacing. LGBS publishes no documented rate limit, so this
    # keeps the existing 0.3s inter-page courtesy from harvest_lgbs().
    transport = UrllibTransport(RateLimitPolicy(max_retries=2, timeout_seconds=30, min_interval_seconds=0.3))

    # ---- 1. environment ------------------------------------------------
    env_status, env_detail = classify_environment(transport)
    print(f"environment_status = {env_status}")
    print(f"  detail: {env_detail[:160]}")

    # ---- 2. governance gate --------------------------------------------
    policy = check_acquisition_policy(
        "tx_lgbs", purpose=AcquisitionPurpose.PRODUCTION_ACQUISITION, state="TX", use="INGEST"
    )
    print(f"governance_gate    = {'PASS' if policy.allowed else 'REFUSED'} ({policy.registry_status})")
    if not policy.allowed:
        print(f"  refused: {policy.reason}")
        _write_artifact(started, env_status, env_detail, policy, run=None, check=None)
        return 2

    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    run.environment_status = env_status
    run.tally.records_observed_at_source = TX_LGBS_STATE_DENOMINATOR

    if env_status != "NETWORK_AVAILABLE":
        run.mark_blocked(
            f"{env_status}: {env_detail}", environment_status=env_status
        )
        check = run.finalize(expected_denominator=TX_LGBS_STATE_DENOMINATOR)
        print(f"run_status         = {run.status.value}")
        print("  no acquisition attempted - environment cannot reach the source.")
        print("  NOTE: this is NOT a source failure and must not be recorded as one.")
        _write_artifact(started, env_status, env_detail, policy, run, check)
        return 3

    if args.probe_only:
        print("probe-only: environment reachable, stopping before acquisition.")
        _write_artifact(started, env_status, env_detail, policy, run, None)
        return 0

    # ---- 3/4. acquisition ----------------------------------------------
    limit = None if args.full else (args.limit or 25)
    print(f"acquiring          = {'FULL' if limit is None else f'SAMPLE limit={limit}'}")

    adapter = LgbsAdapter(transport=transport)
    result = adapter.acquire(limit=limit, purpose=AcquisitionPurpose.PRODUCTION_ACQUISITION)
    run.record_result(result)

    # Pagination is exhausted only when the adapter walked to the end AND we
    # were not artificially limiting. A limited sample is never COMPLETE.
    run.pagination_exhausted = result.checkpoint is None and limit is None

    expected = TX_LGBS_STATE_DENOMINATOR if limit is None else None
    check = run.finalize(expected_denominator=expected)

    print(f"run_status         = {run.status.value}")
    print(f"  tally: {json.dumps(run.tally.to_dict(), indent=2)}")
    print(f"  denominator: {check.reason}")
    _write_artifact(started, env_status, env_detail, policy, run, check)
    return 0 if run.status in (RunStatus.COMPLETE, RunStatus.PARTIAL) else 4


def _write_artifact(started, env_status, env_detail, policy, run, check) -> None:
    """Artifacts only. No production write path exists in this script."""
    artifact = {
        "phase": 41,
        "source_id": "tx_lgbs",
        "started_at": started,
        "environment_status": env_status,
        "environment_detail": env_detail,
        "governance_gate": policy.to_dict() if policy else None,
        "run": run.to_dict() if run else None,
        "denominator_check": check.to_dict() if check else None,
        "county_coverage": run.county_coverage() if run else [],
        "field_completeness": run.field_completeness(COMPLETENESS_FIELDS) if run else [],
        "production_data_modified": False,
    }
    path = ARTIFACT_DIR / "phase41_lgbs_run.json"
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(f"artifact written   = {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    raise SystemExit(main())
