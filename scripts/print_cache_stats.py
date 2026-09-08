#!/usr/bin/env python3
"""Prints a cache-hit-ratio summary for this run's LAFT harvesters, from the
tiny JSON stats files scripts/harvest_cache.py's record_cache_stats() writes
(one per harvester: laft_pdf, laft_html, laft_realtdm_prices).

Why this exists (2026-09-08): the caching layer (see harvest_cache.py) has
been live since 2026-09-07, but confirming it's actually working meant
opening each of the three harvest steps' raw logs and finding the "N of M
sources were unchanged" / "N purchase-price lookup(s) served from cache"
line by hand - readable, but not something you'd notice going stale at a
glance on the Actions run page. This turns the same numbers into one
markdown table appended to $GITHUB_STEP_SUMMARY, which GitHub renders
directly on the run's summary page.

Advisory only, like sanity_check_laft.ps1/sanity_check_deeds.ps1: a missing
or unreadable stats file (a harvester errored before reaching
record_cache_stats(), or nothing populated CACHE_STATS_DIR at all) is shown
as "no data" for that row rather than failing the step, since this is pure
observability - it must never be able to fail the harvest itself.
"""
import json
import os
import sys
from pathlib import Path

STATS_DIR = Path(os.environ.get("CACHE_STATS_DIR", "out/cache_stats"))

# (stats file stem, display label) - the three harvesters
# scripts/harvest_cache.py's caching layer actually covers today.
HARVESTERS = [
    ("laft_pdf", "LAFT PDFs"),
    ("laft_html", "LAFT HTML-table"),
    ("laft_realtdm_prices", "RealTDM purchase prices"),
]


def load_stats(stem):
    path = STATS_DIR / f"{stem}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        hits, total = int(data.get("hits", 0)), int(data.get("total", 0))
        return hits, total
    except (OSError, ValueError, TypeError):
        return None


def pct(hits, total):
    return f"{(100.0 * hits / total):.0f}%" if total else "-"


def main() -> int:
    rows = []
    total_hits = total_attempted = 0
    for stem, label in HARVESTERS:
        stats = load_stats(stem)
        if stats is None:
            rows.append((label, "no data", "-", "-"))
            continue
        hits, total = stats
        total_hits += hits
        total_attempted += total
        rows.append((label, str(hits), str(total), pct(hits, total)))

    lines = [
        "## LAFT cache hit-ratio summary",
        "",
        "| Harvester | Cache hits | Attempted | Hit ratio |",
        "|---|---|---|---|",
    ]
    for label, hits, total, ratio in rows:
        lines.append(f"| {label} | {hits} | {total} | {ratio} |")
    lines.append(f"| **Overall** | **{total_hits}** | **{total_attempted}** | **{pct(total_hits, total_attempted)}** |")
    lines.append("")
    lines.append(
        "A 0% row right after the caching code changes (or after a "
        "force_harvest run) is expected - the cache has nothing to reuse "
        "yet. A persistent 0% on an ordinary scheduled run is the signal "
        "something's wrong with change detection for that harvester."
    )
    summary = "\n".join(lines)

    print(summary)
    step_summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary_path:
        try:
            with open(step_summary_path, "a", encoding="utf-8") as fh:
                fh.write(summary + "\n")
        except OSError as exc:
            print(f"(could not write GITHUB_STEP_SUMMARY: {exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
