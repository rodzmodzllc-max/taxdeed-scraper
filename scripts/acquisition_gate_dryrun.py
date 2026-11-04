#!/usr/bin/env python3
"""Read-only dry run of the acquisition-path gate over a counts-only export
of production's active AVAILABLE rows (2026-10-10).

    python3 scripts/acquisition_gate_dryrun.py            # rebuild the report
    python3 scripts/acquisition_gate_dryrun.py --check    # exit 1 if stale

Input:  data/current_state/acquisition-gate-groups-<date>.json - every active
        properties.source = 'laft' row grouped by the facts the gate reads
        (state, county, source, publication status, typed path, read-date
        bucket, list-date bucket), with a count per group. No identifier,
        address or amount.
        public/acquisition-evidence.json - the repository's acquisition
        evidence (unit statuses and county records).
Output: docs/review/acquisition-gate-dryrun-<date>.md (the review document)
        data/current_state/acquisition-gate-dryrun-<date>.json (the numbers)

"Current customer-visible" is what the deployed rules show a customer today:
in customer mode (publicationMode "enforced") the customer-published sources;
in the tester preview (production's config.js today) every source that is not
BLOCKED. The Detroit customer subset (a browser-side ~50% rule) cannot be
applied to counts, so Detroit's rows are reported as collected rows. Nothing
here reads or writes the database: the export was taken once, read-only.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harvesters.sources import acquisition_gate as G  # noqa: E402

STAMP = "2026-10-10"
GROUPS = REPO / "data" / "current_state" / f"acquisition-gate-groups-{STAMP}.json"
EVIDENCE = REPO / "public" / "acquisition-evidence.json"
OUT_MD = REPO / "docs" / "review" / f"acquisition-gate-dryrun-{STAMP}.md"
OUT_JSON = REPO / "data" / "current_state" / f"acquisition-gate-dryrun-{STAMP}.json"

# A bucket stands for the worst date inside it, so a group is never passed on
# a date it might not have.
SEEN_DAYS = {"le14d": 1, "le60d": 30, "gt60d": 100, "never": None}
LIST_DAYS = {"none": None, "le365d": 100, "gt365d": 600}


def pseudo_row(g: dict, today: date) -> dict:
    seen = SEEN_DAYS[g["seen_bucket"]]
    listed = LIST_DAYS[g["list_bucket"]]
    return {
        "source_id": g["source_id"] or None,
        "publication_status": g["publication_status"] or None,
        "status": "active",
        "last_seen_at": (today - timedelta(days=seen)).isoformat() + "T00:00:00Z" if seen is not None else None,
        "list_as_of": (today - timedelta(days=listed)).isoformat() if listed is not None else None,
        "purchase_path_type": g["path_type"] or None,
    }


def run(today: date) -> dict:
    groups = json.loads(GROUPS.read_text(encoding="utf-8"))
    ev = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    rows = []
    for g in groups["groups"]:
        unit = G.find_unit(ev["status"], g["state"], g["source_id"], g["county"])
        rec = G.find_record(ev["records"], g["state"], g["source_id"], g["county"])
        v = G.verify(pseudo_row(g, today), unit=unit, record=rec, today=today)
        rows.append({**{k: g[k] for k in ("state", "county", "source_id", "publication_status", "path_type", "seen_bucket", "list_bucket", "n")},
                     "evidence_status": v.evidence_status or ("" if unit else "NONE"), "verified": v.verified,
                     "classification": v.classification, "reasons": v.reasons})

    def visible_now(r, mode):
        if r["publication_status"] == "BLOCKED":
            return False
        return r["publication_status"] in G.PUBLISHED_STATUSES if mode == "enforced" else True

    def agg(key):
        out: dict = defaultdict(lambda: {"active": 0, "visible_customer_mode": 0, "visible_preview_mode": 0, "proposed": 0, "withheld": 0, "by_class": Counter(), "by_reason": Counter()})
        for r in rows:
            k = key(r)
            a = out[k]
            a["active"] += r["n"]
            if visible_now(r, "enforced"):
                a["visible_customer_mode"] += r["n"]
            if visible_now(r, "preview"):
                a["visible_preview_mode"] += r["n"]
            if r["verified"]:
                a["proposed"] += r["n"]
            else:
                a["withheld"] += r["n"]
                a["by_class"][r["classification"]] += r["n"]
                for reason in r["reasons"]:
                    a["by_reason"][reason] += r["n"]
        return {k: {**v, "by_class": dict(v["by_class"]), "by_reason": dict(v["by_reason"])} for k, v in sorted(out.items())}

    return {
        "exported_on": groups["exported_on"], "scope": groups["scope"], "today": today.isoformat(),
        "windows": {"observation_days": G.OBSERVATION_DAYS, "list_days": G.LIST_DAYS, "evidence_days": G.EVIDENCE_DAYS},
        "total": agg(lambda r: "all")["all"],
        "by_state": agg(lambda r: r["state"]),
        "by_state_ledger": agg(lambda r: f"{r['state']} · Available"),
        "by_source": agg(lambda r: f"{r['state']} · {r['source_id'] or '(no source id)'}"),
        "by_county": agg(lambda r: f"{r['state']} · {r['county']}"),
        "groups": rows,
    }


def fmt_counter(d: dict, labels: dict | None = None) -> str:
    if not d:
        return "-"
    return "; ".join(f"{(labels or {}).get(k, k)} {v:,}" for k, v in sorted(d.items(), key=lambda kv: -kv[1]))


def render(res: dict) -> str:
    t = res["total"]
    L = []
    L.append(f"# Acquisition-path gate: read-only dry run ({res['exported_on']})\n")
    L.append("Generated by `scripts/acquisition_gate_dryrun.py` from a counts-only export of production's "
             f"active AVAILABLE rows (`{res['scope']}`, exported {res['exported_on']}, no row written) and the repository's "
             "acquisition evidence (`public/acquisition-evidence.json`). The gate is **not enforced**: `config.js` "
             "`availableGate` is `off`. This is what enforcing it would do.\n")
    L.append(f"Windows: a record must have been read in the last {res['windows']['observation_days']} days, a source-published "
             f"list date must be within {res['windows']['list_days']} days, and the county's verified acquisition process within "
             f"{res['windows']['evidence_days']} days. A group's read / list date is taken as the worst date in its bucket, so no "
             "row is passed on a date it might not have.\n")
    L.append("## Totals\n")
    L.append("| | Rows |\n|---|---|")
    L.append(f"| Active AVAILABLE rows | {t['active']:,} |")
    L.append(f"| Customer-visible today, customer mode (approved sources) | {t['visible_customer_mode']:,} |")
    L.append(f"| Customer-visible today, tester preview (production's `publicationMode: \"preview\"`) | {t['visible_preview_mode']:,} |")
    L.append(f"| **Proposed customer-visible (gate enforced)** | **{t['proposed']:,}** |")
    L.append(f"| Withheld by the gate (admin-only) | {t['withheld']:,} |\n")
    L.append("Withheld, by class:\n")
    L.append("| Class | Rows | Meaning |\n|---|---|---|")
    meaning = {"source_not_published": "the source decision withholds it already (not this gate's finding)",
               "no_route": "the official pages were read and describe no way to acquire - genuinely no actionable route on file",
               "pending_verification": "a process exists or may exist; it is not verified yet (capture, review or a record fix)",
               "metadata_gap": "a fact the pipeline has not recorded (source id, read stamp, county record) - excluded for missing metadata, not for lack of a route",
               "stale": "the record or its list is not current"}
    for c in G.CLASS_PRECEDENCE:
        if t["by_class"].get(c):
            L.append(f"| {G.CLASS_LABELS[c]} (`{c}`) | {t['by_class'][c]:,} | {meaning[c]} |")
    L.append("")
    L.append("Every reason (a row can carry several):\n")
    L.append("| Reason | Rows |\n|---|---|")
    for r, n in sorted(t["by_reason"].items(), key=lambda kv: -kv[1]):
        L.append(f"| `{r}` - {G.REASONS[r]} | {n:,} |")
    L.append("")

    def table(title, key, data):
        L.append(f"## {title}\n")
        L.append("| " + key + " | Active | Visible now (customer mode) | Visible now (preview) | Proposed | Withheld | Withheld by class |\n|---|---|---|---|---|---|---|")
        for k, a in data.items():
            L.append(f"| {k} | {a['active']:,} | {a['visible_customer_mode']:,} | {a['visible_preview_mode']:,} | {a['proposed']:,} | {a['withheld']:,} | {fmt_counter(a['by_class'])} |")
        L.append("")
    table("By state", "State", res["by_state"])
    table("By state and ledger", "State · ledger", res["by_state_ledger"])
    table("By source", "State · source", res["by_source"])
    table("By county", "State · county", res["by_county"])
    L.append("## Every group\n")
    L.append("| State | County | Source | Publication | Typed path | Read | List date | Evidence unit | Rows | Verdict | Reasons |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for g in res["groups"]:
        L.append(f"| {g['state']} | {g['county']} | {g['source_id'] or '-'} | {g['publication_status'] or 'NULL'} | {g['path_type'] or '-'} | {g['seen_bucket']} | {g['list_bucket']} | {g['evidence_status'] or '-'} | {g['n']:,} | {'verified' if g['verified'] else g['classification']} | {', '.join(g['reasons']) or '-'} |")
    L.append("")
    L.append("Excluded candidates stay in storage and in the administrator views unchanged; the gate never deletes, closes or republishes a row.\n")
    return "\n".join(L)


def main(argv):
    today = date.fromisoformat(STAMP)
    res = run(today)
    md = render(res)
    js = json.dumps(res, indent=1, sort_keys=False) + "\n"
    if "--check" in argv:
        cur_md = OUT_MD.read_text(encoding="utf-8") if OUT_MD.exists() else ""
        cur_js = OUT_JSON.read_text(encoding="utf-8") if OUT_JSON.exists() else ""
        if cur_md != md or cur_js != js:
            print("acquisition gate dry run is stale: run scripts/acquisition_gate_dryrun.py")
            return 1
        print("acquisition gate dry run is current")
        return 0
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md, encoding="utf-8")
    OUT_JSON.write_text(js, encoding="utf-8")
    t = res["total"]
    print(f"active {t['active']:,}  visible(customer mode) {t['visible_customer_mode']:,}  visible(preview) {t['visible_preview_mode']:,}  proposed {t['proposed']:,}  withheld {t['withheld']:,}")
    for c, n in sorted(t["by_class"].items(), key=lambda kv: -kv[1]):
        print(f"  {c}: {n:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
