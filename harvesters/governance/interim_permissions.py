"""Every interim allowance in data/source_permissions.csv, validated.

An interim allowance is a record whose status is open (LEGAL_REVIEW_REQUIRED,
OWNER_PERMISSION_REQUIRED or UNKNOWN) and whose evidence is
GRANDFATHERED_PRACTICE or INTERNAL_RISK_ACCEPTANCE. It lets today's practice
continue until its expiry date; it is never documented permission, and
permissions.authorize() denies it the day after `expires_on`.

`inventory()` returns one entry per interim record, with:
  - the record itself (source, dataset, jurisdiction, operation, conditions,
    evidence, reviewer, dates);
  - `call_sites`: the repository files that enforce that source - files that
    name the source next to a permission check, plus the shared gates that
    apply to it by class (registry sources, Lands Available, parcel layers,
    coordinate sources). Read from the code, never asserted by hand;
  - `findings`: what a reviewer should know, e.g. a reviewer column that names
    a document, not a decision, or no call site found.

Nothing here allows, renews or changes a record.
"""
from __future__ import annotations

import csv
from pathlib import Path

from . import permissions as PERM

REPO = Path(__file__).resolve().parents[2]
SCAN_DIRS = ("scripts", "harvesters")
GATE_MARKERS = ("authorize(", "allowed(", "permission_gate(", "source_permission_check", "_permitted(",
                "_require_lookup_permission(", "STORE_SOURCES", "require(", "permission(")
NO_DECISION_MARKERS = ("no reviewer decision on file",)


def interim_records(perms: PERM.Permissions) -> list[PERM.PermissionRecord]:
    return [r for r in perms.records if r.status in PERM.OPEN_STATUSES and r.evidence_type in PERM.INTERIM_EVIDENCE]


def _files(repo: Path) -> list[tuple[str, str]]:
    out = []
    for d in SCAN_DIRS:
        for p in sorted((repo / d).rglob("*")):
            if p.suffix in (".py", ".ps1") and "__pycache__" not in p.parts and p.name != "interim_permissions.py":
                try:
                    out.append((p.relative_to(repo).as_posix(), p.read_text(encoding="utf-8")))
                except (OSError, UnicodeDecodeError):
                    continue
    return out


def _class_gates(source_id: str, repo: Path) -> list[str]:
    gates = []
    reg = repo / "data" / "county_source_registry.csv"
    if reg.is_file():
        with reg.open(newline="", encoding="utf-8") as fh:
            ids = {r.get("source_id") for r in csv.DictReader(fh)}
        if source_id in ids:
            gates += ["scripts/source_publication.py (collectable / publishable)",
                      "harvesters/governance/publication_state.py (display)"]
    for name in ("county_source_candidates.csv", "acquisition_candidate_pages.csv"):
        cand = repo / "data" / name
        if not cand.is_file():
            continue
        with cand.open(newline="", encoding="utf-8") as fh:
            if source_id in {r.get("source_id") for r in csv.DictReader(fh)}:
                # discover-only candidates: every request is checked by URL against the record
                gates.append("harvesters/governance/discovery_guard.py (discover, by URL)")
                break
    if source_id.startswith("fl_laft_") or source_id == "la_ebr_adjudicated":
        gates.append("scripts/laft_lifecycle.py (apply_store_permission)")
    try:
        from harvesters.enrichment import sources as PS  # noqa: PLC0415
        if any(c.source_id == source_id for c in PS.all_sources()):
            gates.append("harvesters/enrichment/parcels.py (enrichment_allowed)")
        from harvesters.enrichment import geocode as GC  # noqa: PLC0415
        if any(getattr(s, "source_id", None) == source_id for s in getattr(GC, "COORDINATE_SOURCES", ())) or \
                source_id in ("fl_fdor_cadastral", "fl_santa_rosa_parcels"):
            gates.append("harvesters/enrichment/geocode.py (CoordinateSource.usable)")
    except Exception:  # noqa: BLE001 - a config that fails to load lists no class gate
        pass
    return gates


def call_sites(source_id: str, files: list[tuple[str, str]], repo: Path = REPO) -> list[str]:
    """Files that name the source within three lines of a permission check,
    then the shared gates that apply to it by class."""
    named = []
    for rel, text in files:
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if source_id not in ln:
                continue
            window = "\n".join(lines[max(0, i - 3): i + 4])
            if any(m in window for m in GATE_MARKERS):
                named.append(rel)
                break
    return sorted(set(named)) + [g for g in _class_gates(source_id, repo) if g.split(" ")[0] not in named]


def inventory(perms: PERM.Permissions | None = None, repo: Path = REPO) -> list[dict]:
    perms = perms or PERM.Permissions.from_file()
    files = _files(repo)
    sites_cache: dict[str, list[str]] = {}
    out = []
    for r in sorted(interim_records(perms), key=lambda r: (r.source_id, r.jurisdiction, r.dataset, r.operation)):
        if r.source_id not in sites_cache:
            sites_cache[r.source_id] = call_sites(r.source_id, files, repo)
        sites = sites_cache[r.source_id]
        findings = []
        if any(m in (r.reviewer or "") for m in NO_DECISION_MARKERS):
            findings.append("REVIEWER_IS_NOT_A_DECISION")
        if not sites:
            findings.append("NO_CALL_SITE_FOUND")
        if not r.expires_on:
            findings.append("NO_EXPIRY")
        out.append({
            "source_id": r.source_id, "dataset": r.dataset, "jurisdiction": r.jurisdiction, "operation": r.operation,
            "status": r.status, "evidence_type": r.evidence_type, "evidence_ref": r.evidence_ref,
            "evidence_date": r.evidence_date, "reviewer": r.reviewer, "effective_on": r.effective_on,
            "expires_on": r.expires_on, "conditions": list(r.conditions), "call_sites": sites, "findings": findings,
        })
    return out


def build(perms: PERM.Permissions | None = None, repo: Path = REPO) -> dict:
    """The generated inventory: deterministic (no "days remaining", no run
    date), so `--check` only changes when a record or a call site does."""
    perms = perms or PERM.Permissions.from_file()
    entries = inventory(perms, repo)
    by_expiry: dict[str, int] = {}
    by_finding: dict[str, int] = {}
    for e in entries:
        by_expiry[e["expires_on"] or "(none)"] = by_expiry.get(e["expires_on"] or "(none)", 0) + 1
        for f in e["findings"]:
            by_finding[f] = by_finding.get(f, 0) + 1
    return {
        "config_error": perms.error,
        "interim_max_days": PERM.INTERIM_MAX_DAYS,
        "summary": {"records": len(entries), "sources": len({e["source_id"] for e in entries}),
                    "by_expiry": dict(sorted(by_expiry.items())), "by_finding": dict(sorted(by_finding.items()))},
        "entries": entries,
    }


def render_markdown(doc: dict) -> str:
    s = doc["summary"]
    out = [
        "# Interim source permissions",
        "",
        "Generated by `scripts/build_interim_permissions.py` from `data/source_permissions.csv`",
        "(`harvesters/governance/interim_permissions.py`). Do not edit by hand.",
        "",
        "An interim allowance is an open status (owner permission / legal review required, unknown)",
        "recorded on grandfathered practice or internal risk acceptance. It is **not permission**: it lets",
        "current practice continue until `expires_on`, and `permissions.authorize()` denies it from the day",
        "after (`EXPIRED`), with no fallback to a broader record. A window longer than",
        f"{doc['interim_max_days']} days is a configuration error that denies every request.",
        "",
        f"- Records: {s['records']} across {s['sources']} sources",
        "- By expiry: " + ", ".join(f"{k} ({v})" for k, v in s["by_expiry"].items()),
        "- Findings: " + (", ".join(f"{k} ({v})" for k, v in s["by_finding"].items()) or "none"),
        f"- Configuration: {'valid' if not doc['config_error'] else 'INVALID - every request is denied'}",
        "",
        "`REVIEWER_IS_NOT_A_DECISION`: the record's reviewer column says no reviewer decision is on file;",
        "the allowance rests on recorded practice only. `NO_CALL_SITE_FOUND`: no enforcing call site was",
        "found in the code for that source.",
        "",
        "| Source | Jurisdiction | Dataset | Operation | Status | Evidence | Effective | Expires | Conditions | Call sites | Findings |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e in doc["entries"]:
        out.append("| " + " | ".join([
            e["source_id"], e["jurisdiction"], e["dataset"], e["operation"], e["status"], e["evidence_type"],
            e["effective_on"], e["expires_on"] or "(none)", ", ".join(e["conditions"]) or "-",
            "<br>".join(e["call_sites"]) or "-", ", ".join(e["findings"]) or "-",
        ]).replace("\n", " ") + " |")
    return "\n".join(out) + "\n"
