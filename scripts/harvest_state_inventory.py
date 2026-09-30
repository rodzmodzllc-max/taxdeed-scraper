#!/usr/bin/env python3
"""State inventory harvester for the search-evidence-configured adapters
(Arkansas COSL and Louisiana EBR - AVAILABLE ledger; Arizona Maricopa State CP -
LIENS & CERTIFICATES ledger) - GATED.

    python3 scripts/harvest_state_inventory.py --state AR --fixture Dallas=<saved.html>
    python3 scripts/harvest_state_inventory.py --state LA --fixture <saved.csv>
    python3 scripts/harvest_state_inventory.py --state AZ --fixture <saved.csv>
    python3 scripts/harvest_state_inventory.py --state AR          # live: exit 2, zero requests, until can_run() allows

Same contract as scripts/harvest_alabama_state_land.py: fixture mode never
touches the network (it is how a saved live file gets validated); live mode
refuses unless the state is activated (harvesters/governance/states.py)
AND the source is live-verified, fixture-validated and enabled - every one
of which is false today. Writes the harvest-row file, the state's OWN
status file and a counts-only report; wired into no workflow; no schedule.
Public log discipline: unit names, statuses, counts and URLs only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(REPO))
from laft_status import StatusRecorder  # noqa: E402
from harvesters.otc.adapters import arizona as AZ, arkansas as AR, louisiana as LA  # noqa: E402

OUT_DIR = REPO / "out"
USER_AGENT = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper; GitHub Actions)"
PARSER_VERSION = "1"

ADAPTERS = {"AR": AR, "AZ": AZ, "LA": LA}


def source_of(state: str):
    return {"AR": AR.COSL_SOURCE, "AZ": AZ.MARICOPA_SOURCE, "LA": LA.EBR_SOURCE}[state]


def run_fixtures(state: str, specs: list[str], *, retrieved_at: datetime):
    mod, cfg = ADAPTERS[state], source_of(state)
    result = mod.HarvestResult() if hasattr(mod, "HarvestResult") else None
    from harvesters.otc.adapters.common import HarvestResult
    result = HarvestResult()
    for spec in specs:
        unit, sep, path = spec.partition("=")
        if not sep:
            unit, path = None, spec
        p = Path(path)
        url = f"file://{p.resolve()}"
        if state == "AR":
            county = (unit or "").strip()
            if county not in AR.ARKANSAS_COUNTIES:
                raise SystemExit(f"--fixture: {county!r} is not one of the 75 Arkansas counties (use County=PATH)")
            recs, outcome = AR.parse_list_html(cfg, p.read_bytes(), county=county, retrieved_at=retrieved_at, url=url)
            result.outcomes.append(AR.classify_outcome(cfg, county, recs, outcome, url=url))
        else:
            recs, outcome = mod.parse_csv(cfg, p.read_text(encoding="utf-8"), retrieved_at=retrieved_at)
            result.outcomes.append(mod.classify_outcome(cfg, recs, outcome, url=url))
        result.records.extend(recs)
    return result


def live_fetcher():
    import requests  # noqa: PLC0415 - only after the gate passed
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    def fetch_text(url: str) -> str:
        resp = session.get(url, timeout=45)
        resp.raise_for_status()
        return resp.text
    return fetch_text


def record_outcomes(recorder: StatusRecorder, outcomes) -> None:
    for oc in outcomes:
        kw = dict(source_url=oc.url)
        if oc.status == "COMPLETE":
            recorder.complete(oc.county, oc.row_count, **kw)
        elif oc.status == "EMPTY":
            recorder.empty(oc.county, oc.empty_signal or "empty_marker", **kw)
        elif oc.status == "INCOMPLETE":
            recorder.incomplete(oc.county, oc.category or "UNKNOWN", oc.reason or oc.status, row_count=oc.row_count, parse_ok=bool(oc.row_count), **kw)
        else:
            recorder.failed(oc.county, oc.category or "UNKNOWN", oc.reason, **kw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True, choices=sorted(ADAPTERS))
    ap.add_argument("--fixture", action="append", default=[], metavar="[Unit=]PATH")
    ap.add_argument("--counties", nargs="*", default=None, help="AR live mode: only these counties")
    ap.add_argument("--out", default=None)
    ap.add_argument("--status", default=None)
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)
    state, mod, cfg = args.state, ADAPTERS[args.state], source_of(args.state)
    out = Path(args.out or OUT_DIR / mod.HARVEST_FILE_NAME)
    status = Path(args.status or os.environ.get(f"{state}_STATUS_PATH") or OUT_DIR / mod.STATUS_FILE_NAME)
    report = Path(args.report or OUT_DIR / "public" / f"{state.lower()}-harvest.json")
    retrieved_at = datetime.now(timezone.utc)

    if args.fixture:
        result, mode = run_fixtures(state, args.fixture, retrieved_at=retrieved_at), "fixture"
    else:
        decision = mod.can_run(cfg)
        if not decision.allowed:
            print(f"::error title=harvest_{state.lower()}::{decision.reason} - 0 requests made, nothing written")
            return 2
        fetch = live_fetcher()
        result = mod.harvest(cfg, fetch, retrieved_at=retrieved_at, counties=args.counties) if state == "AR" else mod.harvest(cfg, fetch, retrieved_at=retrieved_at)
        mode = "live"

    recorder = StatusRecorder(cfg.source_id, source_class="GOVERNMENT_DIRECT", source_id=cfg.source_id, parser_version=PARSER_VERSION,
                              path=status, state=state)
    record_outcomes(recorder, result.outcomes)
    recorder.write()
    rows = [r.to_harvest_row() for r in result.records]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    counts: dict[str, int] = {}
    for oc in result.outcomes:
        counts[oc.status] = counts.get(oc.status, 0) + 1
    rep = {"mode": mode, "state": state, "source_id": cfg.source_id, "rows": len(rows), "units": {oc.county: oc.status for oc in result.outcomes},
           "status_counts": counts, "requests": result.requests, "units_offered": result.units_offered,
           "unresolved_units": result.unresolved_units, "parser_fixture_validated": cfg.parser_fixture_validated,
           "note": "unit names, statuses and counts only; never a row value"}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for oc in result.outcomes:
        extra = f" ({oc.category}: {oc.reason})" if oc.category else ""
        print(f"  {oc.county}: {oc.status} {oc.row_count} row(s){extra}")
    print(recorder.summary_line())
    print(f"{state} ({mode}): {len(rows)} row(s) from {len(result.outcomes)} unit(s), {result.requests} request(s); "
          f"parser fixture-validated: {cfg.parser_fixture_validated}")
    print(f"Saved: {out}; status: {status}; report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
