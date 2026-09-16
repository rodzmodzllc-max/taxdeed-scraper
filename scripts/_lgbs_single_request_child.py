#!/usr/bin/env python3
"""Phase 50. Perform exactly ONE read-only GET against the LGBS API in a
fresh process and print the result as a single JSON object on stdout.

This exists for one reason: Phase 48A observed five successful requests
followed by thirteen consecutive timeouts from a single long-lived Python
process, and then a DIFFERENT process reaching the same source
successfully seconds later. That is a correlation with process/session
reuse, and the only way to test it is to issue the comparison requests from
processes that share nothing.

What this child is NOT
----------------------
It is not a second LGBS client. It builds the same `UrllibTransport` from
the same `RateLimitPolicy` fields the parent diagnostic uses, against a URL
the parent hands it, and it does nothing else. There is no pagination, no
filtering, no normalization, no retry policy of its own, and no record
retention: the response body's SIZE and the envelope's scalar metadata are
reported, the records themselves are counted and discarded.

It does NOT rotate proxies, IP addresses, identities, user agents or
headers, and does not bypass any technical restriction. A fresh process is
the variable under test, not a workaround. Everything the source can use to
recognise this client is identical between the parent and this child.

It holds no credentials. The parent launches it with a scrubbed
environment, and this module imports no database driver and contains no
DML, which `tests/python/test_phase50_transport_diagnostics.py` asserts
with `ast` rather than by substring.

Contract with the parent
------------------------
    argv[1]  the absolute URL to GET
    argv[2]  timeout in seconds (float)

    stdout   exactly one JSON object, always - a failure is data, not an
             exception. The parent never has to parse a traceback.
    exit 0   the child ran. Whether the REQUEST succeeded is the `success`
             field's job, not the exit code's.
    exit 2   the child was called wrongly (bad argv). Distinct, because a
             harness bug must never be readable as evidence about LGBS.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harvesters.acquisition import RateLimitPolicy, UrllibTransport  # noqa: E402
from harvesters.acquisition.transport import (  # noqa: E402
    EnvironmentEgressBlocked,
    SchemaError,
    TransportError,
)


def perform(url: str, timeout: float) -> dict:
    """One attempt, in this process. Never raises."""
    observation: dict = {
        "url": url,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
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
    # Same instrument as the parent: one attempt, so a timeout is the
    # source's and not a retry policy's. min_interval is 0 because a
    # process that issues exactly one request has nothing to pace against;
    # the PARENT owns the spacing between requests.
    transport = UrllibTransport(
        RateLimitPolicy(
            max_retries=1,
            timeout_seconds=timeout,
            min_interval_seconds=0.0,
            jitter_seconds=0.0,
            circuit_breaker_threshold=2,
        )
    )
    started = time.monotonic()
    try:
        response = transport.get(url, timeout=timeout)
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
        # Counted, then dropped. This child retains nothing.
        observation["results_returned"] = len(records) if isinstance(records, list) else None
        observation["next_link_present"] = bool(payload.get("next"))
    observation["success"] = True
    return observation


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(json.dumps({"error": "usage: _lgbs_single_request_child.py <url> <timeout_seconds>"}))
        return 2
    try:
        timeout = float(argv[2])
    except ValueError:
        print(json.dumps({"error": f"timeout was not a number: {argv[2]!r}"}))
        return 2
    print(json.dumps(perform(argv[1], timeout), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
