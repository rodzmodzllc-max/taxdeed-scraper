#!/usr/bin/env python3
"""Alabama state-held tax-delinquent land harvester (Alabama Department of
Revenue, Property Tax Division / State Land Commissioner) - GATED.

Two modes, one output shape:

  --fixture [County=]PATH   parse a SAVED results page (or a statewide
                            page whose rows carry a County column) with
                            no network at all. This is how the first live
                            capture gets validated: save the page, run it
                            here, compare. Repeatable.
  (no --fixture)            the live flow: the search page -> its county
                            options -> one results page per county. It
                            REFUSES - exit 2, zero requests - unless
                            harvesters.otc.adapters.alabama.can_run(ADOR_SOURCE)
                            allows it, which needs the state activated
                            (harvesters/governance/states.py) AND the source
                            live-verified, fixture-validated and enabled.
                            Every one of those is false today.

Output (both modes):
  out/harvest_alabama.json         rows in the harvest-row shape
                                   scripts/laft_lifecycle.py reads (state
                                   "AL", county, case_no = CS number as
                                   published, parcel, owner_name = the name
                                   assessed at sale, bid "" + bid_kind
                                   QUOTED_ON_APPLICATION, url_auction = the
                                   results page, purchase_url/kind, provenance)
  out/harvest_alabama_status.json  per-county status entries (scripts/laft_status.py
                                   vocabulary) - its OWN file, never the FL
                                   one: county names repeat across states
                                   (Escambia, Jackson, Franklin ...). Point
                                   the lifecycle at it: --state AL --status ...
  out/public/alabama-harvest.json  counts only (never a row value)

Until the parser is fixture-validated against the live source, every
county is INCOMPLETE (rows observed, completeness not asserted) and a zero
is never EMPTY - see alabama.classify_outcome() - so nothing downstream
can close a row on the strength of an unverified parser.

This script is NOT wired into any workflow and has no schedule. Public
log discipline: county names, statuses, counts and URLs only - never a CS
number, parcel, name or address.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(REPO))
from laft_status import StatusRecorder  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.otc.adapters import alabama as ala  # noqa: E402

OUT_DIR = REPO / "out"
OUT_JSON = OUT_DIR / ala.HARVEST_FILE_NAME
STATUS_PATH = OUT_DIR / ala.STATUS_FILE_NAME
REPORT_PATH = OUT_DIR / "public" / "alabama-harvest.json"
HARVESTER = ala.ADOR_SOURCE.source_id
PARSER_VERSION = "1"
USER_AGENT = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper; GitHub Actions)"


def parse_fixture_spec(spec: str) -> tuple[str | None, Path]:
    """'Autauga=/path/page.html' -> ('Autauga', path); '/path/page.html' ->
    (None, path) - a statewide page whose rows carry their county."""
    county, sep, path = spec.partition("=")
    if sep and county.strip():
        name = county.strip()
        if name not in ala.ALABAMA_COUNTIES:
            raise SystemExit(f"--fixture: {name!r} is not one of the 67 Alabama counties")
        return name, Path(path)
    return None, Path(spec)


def run_fixtures(specs: list[str], *, retrieved_at: datetime, list_as_of: date | None) -> ala.HarvestResult:
    result = ala.HarvestResult()
    for spec in specs:
        county, path = parse_fixture_spec(spec)
        html = path.read_bytes()
        url = f"file://{path.resolve()}"
        recs, report, outcome = ala.parse_search_results_html(ala.ADOR_SOURCE, html, retrieved_at=retrieved_at,
                                                              list_as_of=list_as_of, default_county=county)
        result.requests += 0  # a fixture is never a request
        result.records.extend(recs)
        if county is not None:
            result.outcomes.append(ala.classify_outcome(ala.ADOR_SOURCE, county, recs, report, outcome, url=url))
        else:
            # A statewide page: one outcome per county the rows named, so
            # the status file stays per county like every other harvester's.
            by_county: dict[str, list] = {}
            for r in recs:
                by_county.setdefault(r.county, []).append(r)
            if not by_county:
                result.outcomes.append(ala.classify_outcome(ala.ADOR_SOURCE, states.STATEWIDE_UNIT, recs, report, outcome, url=url))
            for name, group in sorted(by_county.items()):
                result.outcomes.append(ala.classify_outcome(ala.ADOR_SOURCE, name, group, report, outcome, url=url))
    return result


def live_fetcher():
    """The transport, created only after the gate passed. requests is
    imported here, not at module level, so a refused run never loads an
    HTTP client."""
    import requests  # noqa: PLC0415
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    def fetch_text(url: str) -> str:
        resp = session.get(url, timeout=45)
        resp.raise_for_status()
        return resp.text
    return fetch_text


def record_outcomes(recorder: StatusRecorder, outcomes: list[ala.CountyOutcome]) -> None:
    for oc in outcomes:
        kw = dict(source_url=oc.url)
        if oc.status == "COMPLETE":
            recorder.complete(oc.county, oc.row_count, **kw)
        elif oc.status == "EMPTY":
            recorder.empty(oc.county, oc.empty_signal or "empty_marker", **kw)
        elif oc.status == "INCOMPLETE":
            recorder.incomplete(oc.county, oc.category or "UNKNOWN", oc.reason or oc.status, row_count=oc.row_count,
                                parse_ok=bool(oc.row_count), **kw)
        else:
            recorder.failed(oc.county, oc.category or "UNKNOWN", oc.reason, **kw)


def summarize(result: ala.HarvestResult) -> dict:
    counts: dict[str, int] = {}
    for oc in result.outcomes:
        counts[oc.status] = counts.get(oc.status, 0) + 1
    unmapped = sorted({c for oc in result.outcomes for c in oc.unmapped_columns})
    report_totals: dict[str, int] = {}
    seen: set[int] = set()
    for oc in result.outcomes:
        # A statewide page yields one outcome per county but ONE report;
        # count it once.
        if oc.report is None or id(oc.report) in seen:
            continue
        seen.add(id(oc.report))
        for k, v in vars(oc.report).items():
            if isinstance(v, int):
                report_totals[k] = report_totals.get(k, 0) + v
    return {
        "harvester": HARVESTER, "state": ala.STATE, "rows": len(result.records),
        "counties": {oc.county: oc.status for oc in result.outcomes},
        "status_counts": counts, "requests": result.requests,
        "counties_offered": result.counties_offered, "unmatched_county_options": result.unmatched_options,
        "unmapped_columns": unmapped, "parse_counters": report_totals,
        "parser_fixture_validated": ala.ADOR_SOURCE.parser_fixture_validated,
        "note": "counts, county names, statuses and header labels only; never a row value",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixture", action="append", default=[], metavar="[County=]PATH",
                    help="parse a saved results page instead of fetching (repeatable); no network")
    ap.add_argument("--list-as-of", default=None, help="the list's own date (YYYY-MM-DD) when the page states one; never today")
    ap.add_argument("--counties", nargs="*", default=None, help="live mode: only these counties")
    ap.add_argument("--out", default=str(OUT_JSON))
    ap.add_argument("--status", default=os.environ.get("ALABAMA_STATUS_PATH") or str(STATUS_PATH))
    ap.add_argument("--report", default=str(REPORT_PATH))
    args = ap.parse_args(argv)

    list_as_of = date.fromisoformat(args.list_as_of) if args.list_as_of else None
    retrieved_at = datetime.now(timezone.utc)
    cfg = ala.ADOR_SOURCE

    if args.fixture:
        result = run_fixtures(args.fixture, retrieved_at=retrieved_at, list_as_of=list_as_of)
        mode = "fixture"
    else:
        decision = ala.can_run(cfg)
        if not decision.allowed:
            print(f"::error title=harvest_alabama::{decision.reason} - 0 requests made, nothing written")
            return 2
        fetch_text = live_fetcher()
        result = ala.harvest(cfg, fetch_text, retrieved_at=retrieved_at, counties=args.counties)
        mode = "live"

    recorder = StatusRecorder(HARVESTER, source_class=cfg.source_authority.value, source_id=cfg.source_id,
                              parser_version=PARSER_VERSION, path=args.status, state=ala.STATE)
    record_outcomes(recorder, result.outcomes)
    recorder.write()

    rows = [ala.to_harvest_row(r) for r in result.records]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")

    report = {"mode": mode, **summarize(result)}
    rp = Path(args.report)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for oc in result.outcomes:
        extra = f" ({oc.category}: {oc.reason})" if oc.category else ""
        print(f"  {oc.county}: {oc.status} {oc.row_count} row(s){extra}")
    print(recorder.summary_line())
    print(f"Alabama ({mode}): {len(rows)} row(s) from {len(result.outcomes)} county page(s), {result.requests} request(s); "
          f"parser fixture-validated: {cfg.parser_fixture_validated}")
    print(f"Saved: {out}; status: {args.status}; report: {rp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
