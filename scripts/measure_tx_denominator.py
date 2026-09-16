#!/usr/bin/env python3
"""Phase 45. Independently measure the CURRENT live Texas denominator for
`tx_lgbs`, and prove the measurement is complete rather than assuming it.

Why this is a separate script and not a flag on the acquisition runner
---------------------------------------------------------------------
`TX_LGBS_STATE_DENOMINATOR = 4205` is a HISTORICAL carry-forward measured
in Phase 40. Every phase since has had to repeat the warning that it is not
a live figure, because the acquisition runner stamps it into
`records_observed_at_source` unconditionally and nothing re-measures it -
not even `--full`, which merely reconciles the acquired count AGAINST the
constant.

The fix is not to overwrite the constant. It is to measure the live figure
somewhere the two cannot be confused. This script therefore:

  * imports `TX_LGBS_STATE_DENOMINATOR` read-only, purely to report a delta;
  * never assigns to it, and never writes into the acquisition artifact;
  * writes its own artifact, with `historical_denominator` and
    `current_live_denominator` as separate, separately-labelled fields.

If those two numbers ever get merged into one field, this script has failed
at its only job.

The query
--------
`?state=TX` - the one query that filters on each record's OWN state. The
acquisition path uses `?area=TX`, which is NOT a state filter: Phase 40
measured it at 6,309, of which 2,104 were Philadelphia, PA. That is exactly
why the denominator has to be measured by a different query than the one
acquisition uses.

Completeness
------------
The envelope's `count` claims to be the total across all pages, not the
size of page one. This script does not take that on trust - "do not assume
the first response page is the complete denominator". It verifies the claim
against the source's own pagination semantics with two further single-record
requests:

  1. `offset = count - 1`  must return exactly one record, and `next` must
     be null. That is the last record; if `next` were populated, records
     exist beyond the claimed count.
  2. `offset = count`      must return zero records. If anything comes back,
     the dataset extends past the claimed count.

Three requests total, one record each. If both checks hold, `count` is the
complete denominator and `pagination_validated` is true. If either fails,
the measurement is reported as NOT validated and the figure is not treated
as a denominator.

This script performs NO acquisition, retains NO records, imports no
database driver, and contains no DML. It reads three single-record
responses and writes one JSON file to `out/` (gitignored).
"""

from __future__ import annotations

import json
import sys
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
from harvesters.acquisition.run import TX_LGBS_STATE_DENOMINATOR  # noqa: E402  (read-only)
from harvesters.acquisition.transport import (  # noqa: E402
    AccessRestricted,
    AuthenticationRequired,
    EnvironmentEgressBlocked,
    SchemaError,
    SourceUnavailable,
    TransportError,
)

ARTIFACT_DIR = REPO_ROOT / "out" / "acquisition"
ARTIFACT_PATH = ARTIFACT_DIR / "phase45_tx_denominator.json"

BASE_URL = "https://taxsales.lgbs.com/api/property_sales/"
STATE_QUERY = "state=TX"


def _url(*, limit: int = 1, offset: int | None = None) -> str:
    url = f"{BASE_URL}?{STATE_QUERY}&limit={limit}"
    if offset is not None:
        url += f"&offset={offset}"
    return url


def _fetch(transport, url: str) -> tuple[str, str, dict | None]:
    """Returns `(status, detail, payload)`. Status uses the same five-way
    vocabulary as the acquisition runner, so an environment block is never
    recorded as a source failure."""
    try:
        response = transport.get(url, timeout=30)
    except EnvironmentEgressBlocked as exc:
        return "ENVIRONMENT_EGRESS_BLOCKED", str(exc), None
    except AccessRestricted as exc:
        return "SOURCE_REFUSED", str(exc), None
    except AuthenticationRequired as exc:
        return "SOURCE_REFUSED", f"authentication required: {exc}", None
    except SourceUnavailable as exc:
        return "SOURCE_UNAVAILABLE", str(exc), None
    except (SchemaError, TransportError) as exc:
        return "SOURCE_ERROR", str(exc), None

    try:
        payload = response.json()
    except SchemaError as exc:
        return "SOURCE_ERROR", f"response was not valid JSON: {exc}", None
    if not isinstance(payload, dict) or "results" not in payload:
        return "SOURCE_ERROR", "response envelope has no 'results' key", None
    return "NETWORK_AVAILABLE", f"HTTP {response.http_status}", payload


def _write(artifact: dict) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(f"artifact written           = {ARTIFACT_PATH.relative_to(REPO_ROOT)}")


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    artifact: dict = {
        "phase": 45,
        "source": "LGBS",
        "source_id": "tx_lgbs",
        "query": f"?{STATE_QUERY}",
        "measurement_timestamp": started,
        "historical_denominator": TX_LGBS_STATE_DENOMINATOR,
        "historical_denominator_origin": "Phase 40 carry-forward - NOT measured by this run",
        "current_live_denominator": None,
        "denominator_delta": None,
        "pagination_validated": False,
        "pagination_evidence": [],
        "environment_status": None,
        "governance_gate": None,
        "production_data_modified": False,
    }

    transport = UrllibTransport(
        RateLimitPolicy(max_retries=2, timeout_seconds=30, min_interval_seconds=0.3)
    )

    # Governance first, exactly as the acquisition runner does. Measurement
    # is INTERNAL_TECHNICAL_TESTING, not production acquisition - it takes
    # no records - but the gate is still checked rather than assumed.
    policy = check_acquisition_policy(
        "tx_lgbs", purpose=AcquisitionPurpose.INTERNAL_TECHNICAL_TESTING, state="TX", use="INGEST"
    )
    artifact["governance_gate"] = policy.to_dict()
    print(f"governance_gate            = {'PASS' if policy.allowed else 'REFUSED'} ({policy.registry_status})")
    if not policy.allowed:
        print(f"  refused: {policy.reason}")
        artifact["environment_status"] = "NOT_ATTEMPTED"
        _write(artifact)
        return 2

    # ---- 1. claimed count ------------------------------------------------
    status, detail, payload = _fetch(transport, _url(limit=1))
    artifact["environment_status"] = status
    print(f"environment_status         = {status}")
    print(f"  detail: {detail[:160]}")
    if payload is None:
        print("  denominator NOT measured - the source was never reached.")
        print("  NOTE: this is an environment/source condition, not a measurement of zero.")
        _write(artifact)
        return 3

    claimed = payload.get("count")
    if not isinstance(claimed, int) or claimed < 0:
        artifact["environment_status"] = "SOURCE_ERROR"
        print(f"  envelope 'count' was not a non-negative integer: {claimed!r}")
        _write(artifact)
        return 4
    print(f"claimed_count (?state=TX)  = {claimed}")
    artifact["pagination_evidence"].append(
        {"check": "page_1_count", "url": _url(limit=1), "claimed_count": claimed,
         "results_returned": len(payload.get("results") or [])}
    )

    if claimed == 0:
        # An empty dataset is measurable and complete, but it is a finding,
        # not a routine result - say so rather than reporting a tidy zero.
        artifact["current_live_denominator"] = 0
        artifact["denominator_delta"] = 0 - TX_LGBS_STATE_DENOMINATOR
        artifact["pagination_validated"] = True
        print("  source reports ZERO Texas records - this is a finding, not a normal measurement.")
        _write(artifact)
        return 0

    # ---- 2. last record must terminate the walk --------------------------
    status, detail, last = _fetch(transport, _url(limit=1, offset=claimed - 1))
    if last is None:
        artifact["environment_status"] = status
        print(f"  completeness check 1 failed to fetch: {status} {detail[:120]}")
        _write(artifact)
        return 3
    last_results = last.get("results") or []
    last_next = last.get("next")
    check_last_ok = len(last_results) == 1 and not last_next
    artifact["pagination_evidence"].append(
        {"check": "offset_count_minus_1_is_last_record", "url": _url(limit=1, offset=claimed - 1),
         "results_returned": len(last_results), "next_is_null": not last_next, "passed": check_last_ok}
    )
    print(f"offset={claimed - 1:<18} -> results={len(last_results)} next_null={not last_next}")

    # ---- 3. one past the end must be empty -------------------------------
    status, detail, past = _fetch(transport, _url(limit=1, offset=claimed))
    if past is None:
        artifact["environment_status"] = status
        print(f"  completeness check 2 failed to fetch: {status} {detail[:120]}")
        _write(artifact)
        return 3
    past_results = past.get("results") or []
    check_past_ok = len(past_results) == 0
    artifact["pagination_evidence"].append(
        {"check": "offset_count_is_past_the_end", "url": _url(limit=1, offset=claimed),
         "results_returned": len(past_results), "passed": check_past_ok}
    )
    print(f"offset={claimed:<18} -> results={len(past_results)}")

    validated = bool(check_last_ok and check_past_ok)
    artifact["pagination_validated"] = validated

    if validated:
        artifact["current_live_denominator"] = claimed
        artifact["denominator_delta"] = claimed - TX_LGBS_STATE_DENOMINATOR
        print(f"current_live_denominator   = {claimed}   [LIVE MEASURED]")
        print(f"historical_denominator     = {TX_LGBS_STATE_DENOMINATOR}   [Phase 40 carry-forward]")
        print(f"denominator_delta          = {artifact['denominator_delta']}")
        print("pagination_validated       = YES")
    else:
        # Deliberately leave current_live_denominator as None. A count whose
        # completeness could not be confirmed is not a denominator, and
        # recording it as one is exactly the kind of quiet overclaim this
        # script exists to prevent.
        print("pagination_validated       = NO - 'count' could not be confirmed complete;")
        print("  current_live_denominator left NOT_MEASURED rather than recording an unverified figure.")

    _write(artifact)
    return 0 if validated else 4


if __name__ == "__main__":
    raise SystemExit(main())
