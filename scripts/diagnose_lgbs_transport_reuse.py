#!/usr/bin/env python3
"""Phase 50. Does an LGBS request behave differently when it is issued from
a process that has issued no previous request?

The observation this is built around
------------------------------------
Phase 48A, run 35117982458: one Python process issued 18 paced requests.
The first five succeeded in 9.06 seconds. The next thirteen, spread over
399.2 seconds at roughly two requests a minute, all hit the 30s ceiling
with no recovery at all. Seconds after the last of those timed out, a
SEPARATE process - the acquisition probe step - reached the same host
successfully (HTTP 200).

That is a correlation with process/session reuse. It is not a mechanism,
and this script is not built to prove one. It is built to make the
comparison fair, which the Phase 48A data could not.

Why the design is interleaved, not grouped
------------------------------------------
Phase 48A's decisive finding was that failures clustered on POSITION in the
request sequence, not on the query. Any A-then-B design inherits exactly
that confound: whichever group runs second is tested deeper into the
sequence and looks worse for reasons that have nothing to do with the
variable. So the two modes alternate request by request, PERSISTENT then
FRESH within each pair, on the same URL. Each pair is adjacent in time, so
a position effect hits both modes almost equally and cancels out of the
comparison. Group A and Group B are reported separately; they are not run
separately.

One honest caveat, stated up front
----------------------------------
`UrllibTransport` is built on `urllib.request.urlopen`, which does not pool
or keep alive connections - every call already opens a new TCP connection.
So the PERSISTENT mode is not persistent at the socket level. What it
actually carries between requests is the transport object's own state (its
circuit breaker and pacing) plus whatever the process and the OS hold: DNS
cache, TLS session tickets, ephemeral port state, resolver handles. The
FRESH-process mode discards all of that. This script therefore compares
"same process" against "new process", which is the real variable available
here, and the report must not describe it as a connection-reuse test.

Deliberate instrument choices
-----------------------------
* 4 URLs x 2 trials x 2 modes = 16 requests, deliberately smaller than
  Phase 48A. Section 3: "the objective is isolation, not volume." Only
  limits 1 and 10 - the cheapest requests that still return an envelope.
* `max_retries=1`, `timeout_seconds=30` - identical to the Phase 48
  diagnostic and to the child, so a timeout means here what it meant there.
* A wall-clock budget. Sixteen requests all hitting a 30s ceiling would run
  eight minutes and re-create the very thing Section 3 asked us not to
  build. When the budget is spent the remaining cells are recorded as
  `request_was_sent: false` with `NOT_ATTEMPTED_BUDGET_EXHAUSTED`, so a
  cell that was never tried can never be mistaken for a failure.
* The circuit breaker is raised above the request count in the persistent
  transport, for the same reason as Phase 48: a breaker refusal measures
  the breaker, not the source, and would poison the comparison.

READ-ONLY. GET only. No database driver, no DML, no Supabase, no
production write path, no acquisition, no source-policy change. One JSON
artifact to `out/`, which is gitignored.

Exit codes
    0  the diagnostic ran and produced comparable evidence
    2  the governance gate refused the source
    3  every request was blocked before leaving this machine - a
       measurement of nothing, not a measurement of the source
"""

from __future__ import annotations

import json
import os
import subprocess
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
ARTIFACT_PATH = ARTIFACT_DIR / "phase50_transport_diagnostics.json"
CHILD_SCRIPT = Path(__file__).resolve().parent / "_lgbs_single_request_child.py"

BASE_URL = "https://taxsales.lgbs.com/api/property_sales/"
TRIALS = 2
TIMEOUT_SECONDS = 30.0
MIN_INTERVAL_SECONDS = 0.5
# Section 3's four comparisons, at the two cheapest page sizes.
QUERIES: tuple[tuple[str, str, int], ...] = (
    ("Q1", "state", 1),
    ("Q2", "state", 10),
    ("Q3", "area", 1),
    ("Q4", "area", 10),
)
MODES = ("persistent", "fresh")
# Comfortably under the workflow's 30-minute ceiling and under Phase 48A's
# 6m48s, while leaving room for every cell to be attempted when the source
# is answering normally.
WALL_CLOCK_BUDGET_SECONDS = 300.0

PERSISTENT = "persistent"
FRESH = "fresh"
BUDGET_EXHAUSTED = "NOT_ATTEMPTED_BUDGET_EXHAUSTED"

# Anything outside this set is dropped from the child's environment. An
# allowlist rather than a denylist: a new secret added to CI later must not
# silently start reaching the child because nobody remembered to ban it.
#
# The proxy and CA variables are in the list ON PURPOSE, and a local smoke
# test is why. With them scrubbed, the parent's request went through this
# sandbox's egress proxy and was classified ENVIRONMENT_EGRESS_BLOCKED,
# while the child went DIRECT and got an HTTP 403 - two different network
# paths, which would have made the whole persistent-vs-fresh comparison
# meaningless, and which is also precisely the "bypass a technical
# restriction" that Section 4 forbids. The child must take the same route
# out as the parent or it is not a controlled experiment. These are network
# -path settings, not database credentials; the credential filter below
# still applies to every name, and GitHub-hosted runners set none of them.
CHILD_ENV_ALLOWLIST = (
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP",
    "SYSTEMROOT", "COMSPEC", "PATHEXT", "PYTHONHASHSEED",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
)

# Belt and braces over the allowlist: a variable whose NAME looks like a
# credential is dropped even if it somehow appears above. Section 4 says the
# child must not hold database credentials, and the cheapest way to
# guarantee that is to never hand it one.
CREDENTIAL_NAME_MARKERS = (
    "SUPABASE", "KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD",
    "CREDENTIAL", "DSN", "DATABASE", "CONN_STR", "CONNECTION_STRING", "AUTH",
)


def url_for(param: str, limit: int) -> str:
    return f"{BASE_URL}?{param}=TX&limit={limit}"


def _blank_observation(url: str) -> dict:
    return {
        "url": url,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "pid": None,
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


def persistent_request(transport, url: str) -> dict:
    """One attempt on the SHARED transport, in THIS process. Never raises."""
    observation = _blank_observation(url)
    observation["pid"] = os.getpid()
    started = time.monotonic()
    try:
        response = transport.get(url, timeout=TIMEOUT_SECONDS)
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
        records = payload.get("results")
        observation["results_returned"] = len(records) if isinstance(records, list) else None
        observation["next_link_present"] = bool(payload.get("next"))
    observation["success"] = True
    return observation


def child_environment() -> dict:
    """The child's environment, allowlisted. It cannot hold a credential it
    was never given, which is a stronger guarantee than trusting it not to
    use one."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k in CHILD_ENV_ALLOWLIST
        and not any(marker in k.upper() for marker in CREDENTIAL_NAME_MARKERS)
    }
    # The child inserts the repo root on sys.path itself, but PYTHONPATH
    # makes that explicit and survives a different working directory.
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env


def fresh_request(url: str) -> dict:
    """One attempt in a BRAND NEW process that shares nothing with this one.
    Never raises."""
    observation = _blank_observation(url)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, str(CHILD_SCRIPT), url, str(TIMEOUT_SECONDS)],
            capture_output=True,
            text=True,
            # Generous margin over the child's own timeout, so THIS bound is
            # never the thing that fires. If it ever does, that is a harness
            # fault and is labelled as one below - not as a source timeout.
            timeout=TIMEOUT_SECONDS + 30.0,
            env=child_environment(),
            cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired:
        observation["latency_seconds"] = round(time.monotonic() - started, 3)
        observation["error_class"] = "ChildProcessTimeout"
        observation["error"] = "the child process exceeded the parent's harness bound"
        return observation
    except OSError as exc:
        observation["latency_seconds"] = round(time.monotonic() - started, 3)
        observation["error_class"] = "ChildProcessLaunchFailed"
        observation["error"] = str(exc)[:300]
        observation["request_was_sent"] = False
        return observation

    if completed.returncode != 0:
        observation["latency_seconds"] = round(time.monotonic() - started, 3)
        observation["error_class"] = "ChildProcessRefused"
        observation["error"] = (completed.stderr or completed.stdout or "")[:300]
        observation["request_was_sent"] = False
        return observation
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        observation["latency_seconds"] = round(time.monotonic() - started, 3)
        observation["error_class"] = "ChildProcessUnreadable"
        observation["error"] = (completed.stdout or "")[:300]
        observation["request_was_sent"] = False
        return observation

    # The child measured its own latency around the request alone. The
    # parent's elapsed time additionally contains interpreter startup, so
    # the child's figure is the comparable one and is what is kept.
    payload["parent_elapsed_seconds"] = round(time.monotonic() - started, 3)
    return payload


def summarize(mode: str, label: str, param: str, limit: int, trials: list[dict]) -> dict:
    ok = [t for t in trials if t.get("success")]
    unsent = [t for t in trials if not t.get("request_was_sent", True)]
    latencies = sorted(t["latency_seconds"] for t in ok if t.get("latency_seconds") is not None)
    counts = {t["envelope_count"] for t in ok if t.get("envelope_count") is not None}
    attempted = len(trials) - len(unsent)
    return {
        "mode": mode,
        "label": label,
        "param": param,
        "limit": limit,
        "url": url_for(param, limit),
        "trials": len(trials),
        "attempted": attempted,
        "successes": len(ok),
        "failures": attempted - len(ok),
        "not_sent": len(unsent),
        "query_result": (
            "NOT_ATTEMPTED" if attempted == 0
            else "ALL_SUCCEEDED" if len(ok) == attempted
            else "ALL_FAILED" if not ok
            else "INTERMITTENT"
        ),
        "latency_min": latencies[0] if latencies else None,
        "latency_max": latencies[-1] if latencies else None,
        "latency_median": latencies[len(latencies) // 2] if latencies else None,
        "envelope_counts_seen": sorted(counts) if counts else [],
        "error_classes": sorted({t["error_class"] for t in trials if t.get("error_class")}),
    }


def mode_totals(observations: list[dict], mode: str) -> dict:
    rows = [o for o in observations if o["mode"] == mode]
    sent = [o for o in rows if o.get("request_was_sent", True)]
    ok = [o for o in sent if o.get("success")]
    return {
        "mode": mode,
        "requests": len(rows),
        "attempted": len(sent),
        "successes": len(ok),
        "failures": len(sent) - len(ok),
        "not_sent": len(rows) - len(sent),
        "success_rate_of_attempted": round(len(ok) / len(sent), 3) if sent else None,
    }


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    total_requests = TRIALS * len(QUERIES) * len(MODES)

    artifact: dict = {
        "phase": 50,
        "source": "LGBS",
        "source_id": "tx_lgbs",
        "started_at": started,
        "parent_pid": os.getpid(),
        "instrument": {
            "attempts_per_request": 1,
            "timeout_seconds": TIMEOUT_SECONDS,
            "min_interval_seconds": MIN_INTERVAL_SECONDS,
            "trials_per_query": TRIALS,
            "modes": list(MODES),
            "total_requests": total_requests,
            "circuit_breaker_threshold": total_requests + 1,
            "wall_clock_budget_seconds": WALL_CLOCK_BUDGET_SECONDS,
            "interleaved": True,
            "note": (
                "Modes alternate request by request on the same URL so a "
                "position effect hits both equally. urllib opens a new TCP "
                "connection per call, so 'persistent' means same PROCESS, "
                "not a reused socket."
            ),
        },
        "governance_gate": None,
        "observations": [],
        "summary": [],
        "mode_totals": [],
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

    transport = UrllibTransport(
        RateLimitPolicy(
            max_retries=1,
            timeout_seconds=TIMEOUT_SECONDS,
            min_interval_seconds=MIN_INTERVAL_SECONDS,
            circuit_breaker_threshold=total_requests + 1,
        )
    )

    print(f"{'mode':<11} {'query':<6} {'param':<6} {'limit':>5} {'trial':>5} {'pid':>7} "
          f"{'status':>6} {'latency':>8} {'bytes':>7} {'count':>6}  result")

    by_cell: dict[tuple[str, str], list[dict]] = {(m, q[0]): [] for m in MODES for q in QUERIES}
    run_started = time.monotonic()

    for trial in range(1, TRIALS + 1):
        for label, param, limit in QUERIES:
            url = url_for(param, limit)
            for mode in MODES:
                spent = time.monotonic() - run_started
                if spent >= WALL_CLOCK_BUDGET_SECONDS:
                    obs = _blank_observation(url)
                    obs["request_was_sent"] = False
                    obs["error_class"] = BUDGET_EXHAUSTED
                    obs["error"] = (
                        f"wall-clock budget of {WALL_CLOCK_BUDGET_SECONDS}s spent after "
                        f"{spent:.1f}s; this cell was never attempted and is not evidence "
                        "about the source"
                    )
                else:
                    obs = persistent_request(transport, url) if mode == PERSISTENT else fresh_request(url)
                    if mode == FRESH:
                        # The parent owns spacing; the child has none.
                        time.sleep(MIN_INTERVAL_SECONDS)

                obs["mode"] = mode
                obs["label"] = label
                obs["param"] = param
                obs["limit"] = limit
                obs["trial"] = trial
                by_cell[(mode, label)].append(obs)
                artifact["observations"].append(obs)

                status = obs["http_status"] if obs["http_status"] is not None else "-"
                latency = (f"{obs['latency_seconds']:.3f}s"
                           if obs.get("latency_seconds") is not None else "-")
                nbytes = obs["response_bytes"] if obs["response_bytes"] is not None else "-"
                count = obs["envelope_count"] if obs["envelope_count"] is not None else "-"
                pid = obs["pid"] if obs["pid"] is not None else "-"
                if obs["success"]:
                    result = "ok"
                elif not obs.get("request_was_sent", True):
                    result = f"NOT SENT {obs['error_class']}"
                else:
                    result = f"FAILED {obs['error_class']}"
                print(f"{mode:<11} {label:<6} {param:<6} {limit:>5} {trial:>5} {str(pid):>7} "
                      f"{str(status):>6} {latency:>8} {str(nbytes):>7} {str(count):>6}  {result}")

    artifact["summary"] = [
        summarize(mode, label, param, limit, by_cell[(mode, label)])
        for mode in MODES
        for label, param, limit in QUERIES
    ]
    artifact["mode_totals"] = [mode_totals(artifact["observations"], m) for m in MODES]

    print()
    print(f"{'mode':<11} {'query':<6} {'url':<62} {'query_result':<14} ok/attempted")
    for row in artifact["summary"]:
        print(f"{row['mode']:<11} {row['label']:<6} {row['url']:<62} "
              f"{row['query_result']:<14} {row['successes']}/{row['attempted']}")

    print()
    for row in artifact["mode_totals"]:
        rate = "-" if row["success_rate_of_attempted"] is None else f"{row['success_rate_of_attempted']:.3f}"
        print(f"{row['mode']:<11} attempted={row['attempted']:>2} ok={row['successes']:>2} "
              f"failed={row['failures']:>2} not_sent={row['not_sent']:>2} rate={rate}")

    ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nartifact written = {ARTIFACT_PATH.relative_to(REPO_ROOT)}")

    sent = [o for o in artifact["observations"] if o.get("request_was_sent", True)]
    if sent and all(o["error_class"] == "EnvironmentEgressBlocked" for o in sent):
        print("ALL requests were blocked by this environment - nothing was measured about the source.")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
