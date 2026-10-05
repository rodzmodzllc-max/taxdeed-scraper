"""Commercial (paid-beta) source scope - 2026-10-05.

The publication decision (county_source_registry.publication_status) says
whether a source may be shown to customers at all. Selling access is a
narrower decision, recorded per source in data/paid_beta_sources.csv:

  CUSTOMER_APPROVED            publication_status APPROVED (an explicit decision)
  REQUIRES_PUBLICATION_DECISION
                               customer-visible today only through a legacy
                               grandfathered approval or no recorded decision
                               (APPROVED_GRANDFATHERED / blank) - never sold
                               until someone decides explicitly
  TESTER_PREVIEW               collected, not approved (UNREVIEWED / RESTRICTED):
                               approved testers see it, labelled, in preview
  UNREVIEWED                   registered, not approved and not collected
  BLOCKED                      never shown to anyone

paid_beta = yes is allowed only for a CUSTOMER_APPROVED source whose
provenance, lifecycle, financial and acquisition checks are all "ok" (or
"n/a" when the source has no active rows). Nothing here approves anything:
it records which explicitly approved sources are ready to sell, and why the
rest are withheld. The tester preview (config.js publicationMode) is a
separate, viewer-level setting and never stands in for this decision.

public/commercial-scope.json (scripts/build_commercial_scope.py) carries the
result to the frontend; migration 027 seeds public.commercial_source_scope
with the same paid-beta set (a test pins them equal).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DECISIONS = REPO / "data" / "paid_beta_sources.csv"
REGISTRY = REPO / "data" / "county_source_registry.csv"

SCOPES = ("CUSTOMER_APPROVED", "REQUIRES_PUBLICATION_DECISION", "TESTER_PREVIEW", "UNREVIEWED", "BLOCKED")
CHECKS = ("provenance", "lifecycle", "financial", "acquisition")
CHECK_VALUES = ("ok", "partial", "gap", "n/a")
COLUMNS = ("source_id", "state", "paid_beta", "active_rows", *CHECKS, "reason", "decided_on")


def registry_publication() -> dict[str, tuple[str, str]]:
    """source_id -> (state, publication_status) from the registry."""
    out: dict[str, tuple[str, str]] = {}
    with open(REGISTRY, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = (r.get("source_id") or "").strip()
            if sid:
                out.setdefault(sid, ((r.get("state") or "").strip(), (r.get("publication_status") or "").strip()))
    return out


def load_decisions(path: Path = DECISIONS) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def scope_for(publication_status: str, collected: bool) -> str:
    s = (publication_status or "").strip().upper()
    if s == "BLOCKED":
        return "BLOCKED"
    if s == "APPROVED":
        return "CUSTOMER_APPROVED"
    if s in ("", "APPROVED_GRANDFATHERED"):
        return "REQUIRES_PUBLICATION_DECISION"
    return "TESTER_PREVIEW" if collected else "UNREVIEWED"


def classify(decisions: list[dict] | None = None, registry: dict | None = None) -> list[dict]:
    decisions = load_decisions() if decisions is None else decisions
    registry = registry_publication() if registry is None else registry
    by_id = {d["source_id"]: d for d in decisions}
    out = []
    for sid, (state, pub) in sorted(registry.items(), key=lambda kv: (kv[1][0], kv[0])):
        d = by_id.get(sid)
        collected = d is not None
        scope = scope_for(pub, collected)
        out.append({
            "source_id": sid,
            "state": state,
            "publication_status": pub or None,
            "commercial_scope": scope,
            "collected": collected,
            "paid_beta": bool(d and d["paid_beta"] == "yes"),
            # What an approved tester sees in preview mode today: every
            # collected source except a BLOCKED one (the Detroit subset still
            # applies in the browser).
            "tester_preview": collected and scope != "BLOCKED",
            "active_rows": int(d["active_rows"]) if d and d.get("active_rows", "").isdigit() else 0,
            "checks": {c: d[c] for c in CHECKS} if d else None,
            "reason": d["reason"] if d else "Registered, not collected.",
        })
    return out


def problems(decisions: list[dict] | None = None, registry: dict | None = None) -> list[str]:
    decisions = load_decisions() if decisions is None else decisions
    registry = registry_publication() if registry is None else registry
    errs: list[str] = []
    seen: set[str] = set()
    for d in decisions:
        sid = d.get("source_id", "")
        if tuple(d.keys()) != COLUMNS:
            errs.append(f"{sid}: columns must be exactly {COLUMNS}")
            continue
        if sid in seen:
            errs.append(f"{sid}: listed twice")
        seen.add(sid)
        if sid not in registry:
            errs.append(f"{sid}: not a registry source")
            continue
        state, pub = registry[sid]
        if d["state"] != state:
            errs.append(f"{sid}: state {d['state']} != registry {state}")
        if d["paid_beta"] not in ("yes", "no"):
            errs.append(f"{sid}: paid_beta must be yes / no")
        for c in CHECKS:
            if d[c] not in CHECK_VALUES:
                errs.append(f"{sid}: {c} must be one of {CHECK_VALUES}")
        if not d["reason"].strip():
            errs.append(f"{sid}: a reason is required")
        if d["paid_beta"] == "yes":
            if scope_for(pub, True) != "CUSTOMER_APPROVED":
                errs.append(f"{sid}: paid beta requires an explicit APPROVED publication decision (registry says {pub or 'none'})")
            failing = [c for c in CHECKS if d[c] not in ("ok", "n/a")]
            if failing:
                errs.append(f"{sid}: paid beta requires every check ok - failing {failing}")
    return errs


def paid_beta_source_ids(decisions: list[dict] | None = None) -> list[str]:
    decisions = load_decisions() if decisions is None else decisions
    return sorted(d["source_id"] for d in decisions if d["paid_beta"] == "yes")


def render() -> str:
    rows = classify()
    payload = {
        "_comment": "Generated by scripts/build_commercial_scope.py from data/paid_beta_sources.csv and data/county_source_registry.csv. Do not edit.",
        "paid_beta_publication_status": "APPROVED",
        "paid_beta_source_ids": paid_beta_source_ids(),
        "sources": rows,
    }
    return json.dumps(payload, indent=1, sort_keys=False) + "\n"
