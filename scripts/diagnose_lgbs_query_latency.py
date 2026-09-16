#!/usr/bin/env python3
"""Phase 48. Measure, side by side, how the LGBS API responds to `?state=TX`
versus `?area=TX` at three page sizes.

Why this exists
---------------
Run 35113290312 produced two facts that do not sit together comfortably:

    ?area=TX&limit=1    -> HTTP 200, count=6325, seconds earlier
    ?state=TX&limit=1   -> timed out, twice

A request for ONE record cannot be slow because of volume. That makes the
`state=` filter itself the obvious suspect - and "obvious" is exactly the
kind of conclusion this project has learned to distrust. Run 35109232214
timed out on `offset=500`; run 35113290312 fetched that same URL in about
3.9 seconds. One observation of a slow query is not a property of the query.

So this script does not test a hypothesis. It collects comparable evidence
for six parameter combinations, repeated, and reports what happened. The
interpretation is left to the report.

Deliberate instrument choices
-----------------------------
* `max_retries=1` - ONE attempt per request. The acquisition runner uses 2,
  which is right for acquiring and wrong for measuring: a retry hides
  whether the first attempt succeeded and turns a 30s timeout into a 61s
  one. This is the diagnostic's own instrument setting; it changes nothing
  about acquisition, whose policy is untouched.
* `timeout_seconds=30` - deliberately the SAME as acquisition, so a timeout
  here means what a timeout there means.
* `TRIALS` repetitions per query - the only way to tell "consistently slow"
  from "intermittently slow", which Phase 48 Section 6 names as different
  outcomes.
* `min_interval_seconds=0.5` - slower pacing than acquisition's 0.3s.
  Eighteen requests is a small ask of someone else's server; there is no
  reason to hurry them.
* `circuit_breaker_threshold` raised above the total request count. The
  breaker exists to stop hammering a source that is already failing, and
  that is right for acquisition. For a COMPARISON it is fatal: a local
  smoke test of this script tripped the breaker after 5 consecutive
  failures, and the remaining 13 requests were refused locally without ever
  being sent - they looked like failures but measured nothing. Had that
  happened on the runner, a consistently-failing `state=TX` would have
  poisoned the `area=TX` control. Eighteen small paced requests do not
  need breaker protection; a comparison does need every cell of it
  actually attempted. Acquisition's breaker is untouched.

READ-ONLY. Six URLs, largest `limit` 100. No database driver, no DML, no
production write path, no acquisition. Writes one JSON artifact to `out/`,
which is gitignored.

Exit codes
    0  the diagnostic ran and produced comparable evidence
    2  the governance gate refused the source
    3  the environment could not reach the source at all (every request
       blocked before it left this machine) - a measurement of nothing, not
       a measurement of slowness
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harvesters.acquisition import (  # noqa: E402
    AcquisitionPurpose,
    RateLimitPolicy,
    UrllibTransport,
    check_acquisition_policy,
)
from harvesters.acquisition.transport import (  # noqa: E402
    EnvironmentEgressBlocked,
    SchemaError,
    TransportError,
)

ARTIFACT_DIR = REPO_ROOT / "out" / "acquisition"
ARTIFACT_PATH = ARTIFACT_DIR / "phase48_query_diagnostics.json"

BASE_URL = "https://taxsales.lgbs.com/api/property_sales/"
TRIALS = 3

# Section 2's six comparisons, labelled A-F exactly as specified.
QUERIES: tuple[tuple[str, str, int], ...] = (
    ("A", "state", 1),
    ("B", "state", 10),
    ("C", "state", 100),
    ("D", "area", 1),
    ("E", "area", 10),
    ("F", "area", 100),
)


def url_for(param: str, limit: int) -> str:
    return f"{BASE_URL}?{param}=TX&limit={limit}"


def one_request(transport, url: str) -> dict:
    """One attempt. Never raises - a failure is data."""
    started = time.monotonic()
    observation: dict = {
        "url": url,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "http_status": None,
        "latency_seconds": None,
        "response_bytes": None,
        "envelope_count": None,
        "results_returned": None,
        "next_link_present": None,
        "success": False,
        "error_class": None,
        "error_code": None,
        "error": None,
        "request_was_sent": True,
    }
    try:
        response = transport.get(url, timeout=30)
    except EnvironmentEgressBlocked as exc:
        observation["latency_seconds"] = round(time.monotonic() - started, 3)
        observation["error_class"] = "EnvironmentEgressBlocked"
        observation["error_code"] = getattr(exc, "error_code", None)
        observation["error"] = str(exc)[:300]
        return observation
    except TransportError as exc:
        observation["latency_seconds"] = round(time.monotonic() - started, 3)
        observation["error_class"] = type(exc).__name__
        observation["error_code"] = getattr(exc, "error_code", None)
        observation["error"] = str(exc)[:300]
        observation["http_status"] = getattr(exc, "http_status", None)
        # A breaker refusal never left this machine. Flagged so it can never
        # be counted as evidence about the source.
        observation["request_was_sent"] = "circuit breaker open" not in str(exc)
        return observation

    observation["latency_seconds"] = round(time.monotonic() - started, 3)
    observation["http_status"] = response.http_status
    observation["response_bytes"] = len(response.body or b"")
    try:
        payload = response.json()
    except SchemaError as exc:
        observation["error_class"] = "SchemaError"
        observation["error"] = str(exc)[:300]
        return observation

    if isinstance(payload, dict):
        observation["envelope_count"] = payload.get("count")
        results = payload.get("results")
        observation["results_returned"] = len(results) if isinstance(results, list) else None
        observation["next_link_present"] = bool(payload.get("next"))
    observation["success"] = True
    return observation


def summarize(label: str, param: str, limit: int, trials: list[dict]) -> dict:
    ok = [t for t in trials if t["success"]]
    unsent = [t for t in trials if not t.get("request_was_sent", True)]
    latencies = sorted(t["latency_seconds"] for t in ok if t["latency_seconds"] is not None)
    counts = {t["envelope_count"] for t in ok if t["envelope_count"] is not None}
    return {
        "label": label,
        "param": param,
        "limit": limit,
        "url": url_for(param, limit),
        "trials": len(trials),
        "successes": len(ok),
        "failures": len(trials) - len(ok) - len(unsent),
        "not_sent": len(unsent),
        "query_outcome": (
            "ALL_SUCCEEDED" if len(ok) == len(trials)
            else "ALL_FAILED" if not ok
            else "INTERMITTENT"
        ),
        "latency_min": latencies[0] if latencies else None,
        "latency_max": latencies[-1] if latencies else None,
        "latency_median": latencies[len(latencies) // 2] if latencies else None,
        "envelope_counts_seen": sorted(counts) if counts else [],
        "error_classes": sorted({t["error_class"] for t in trials if t["error_class"]}),
    }


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    artifact: dict = {
        "phase": 48,
        "source": "LGBS",
        "source_id": "tx_lgbs",
        "started_at": started,
        "instrument": {
            "attempts_per_request": 1,
            "timeout_seconds": 30,
            "min_interval_seconds": 0.5,
            "trials_per_query": TRIALS,
            "note": (
                "One attempt per request so a timeout is the source's, not the retry "
                "policy's. Acquisition still uses max_retries=2 and is unchanged."
            ),
        },
        "governance_gate": None,
        "observations": [],
        "summary": [],
        "production_data_modified": False,
    }

    policy = check_acquisition_policy(
        "tx_lgbs", purpose=AcquisitionPurpose.INTERNAL_TECHNICAL_TESTING, state="TX", use="INGEST"
    )
    artifact["governance_gate"] = policy.to_dict()
    print(f"governance_gate = {'PASS' if policy.allowed else 'REFUSED'} ({policy.registry_status})")
    if not policy.allowed:
        print(f"  refused: {policy.reason}")
        ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
        return 2

    total_requests = TRIALS * len(QUERIES)
    transport = UrllibTransport(
        RateLimitPolicy(
            max_retries=1,
            timeout_seconds=30,
            min_interval_seconds=0.5,
            # Above the total request count, so every comparison cell is
            # genuinely attempted. See the module docstring.
            circuit_breaker_threshold=total_requests + 1,
        )
    )
    artifact["instrument"]["circuit_breaker_threshold"] = total_requests + 1
    artifact["instrument"]["total_requests"] = total_requests

    print(f"{'query':<6} {'param':<6} {'limit':>5}  {'trial':>5}  {'status':>6}  "
          f"{'latency':>8}  {'bytes':>7}  {'count':>6}  result")
    by_label: dict[str, list[dict]] = {label: [] for label, _, _ in QUERIES}

    # Trial-major order: A,B,C,D,E,F then again, rather than three A's in a
    # row. If the source has a slow window, round-robin spreads every query
    # across it instead of concentrating one query inside it.
    for trial in range(1, TRIALS + 1):
        for label, param, limit in QUERIES:
            obs = one_request(transport, url_for(param, limit))
            obs["label"] = label
            obs["trial"] = trial
            by_label[label].append(obs)
            artifact["observations"].append(obs)
            status = obs["http_status"] if obs["http_status"] is not None else "-"
            latency = f"{obs['latency_seconds']:.3f}s" if obs["latency_seconds"] is not None else "-"
            nbytes = obs["response_bytes"] if obs["response_bytes"] is not None else "-"
            count = obs["envelope_count"] if obs["envelope_count"] is not None else "-"
            outcome = "ok" if obs["success"] else f"FAILED {obs['error_class']}"
            print(f"{label:<6} {param:<6} {limit:>5}  {trial:>5}  {str(status):>6}  "
                  f"{latency:>8}  {str(nbytes):>7}  {str(count):>6}  {outcome}")

    artifact["summary"] = [
        summarize(label, param, limit, by_label[label]) for label, param, limit in QUERIES
    ]

    print()
    print(f"{'query':<6} {'url':<62} {'query_outcome':<14} ok/trials  median")
    for row in artifact["summary"]:
        median = f"{row['latency_median']:.3f}s" if row["latency_median"] is not None else "-"
        print(f"{row['label']:<6} {row['url']:<62} {row['query_outcome']:<14} "
              f"{row['successes']}/{row['trials']}       {median}")

    ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nartifact written = {ARTIFACT_PATH.relative_to(REPO_ROOT)}")

    # Every single request blocked before leaving this machine means the
    # diagnostic measured nothing about LGBS. That is worth a distinct exit
    # code so it can never be read as "the source is slow".
    if all(o["error_class"] == "EnvironmentEgressBlocked" for o in artifact["observations"]):
        print("ALL requests were blocked by this environment - nothing was measured about the source.")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
