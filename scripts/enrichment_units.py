"""Shared work-unit helpers for the coordinate-keyed backfills (FEMA flood
hazard, NAIP aerial imagery).

A unit is (state, county), never a bare county name: county names repeat
across states (York SC / York ..., Douglas CO / Douglas ..., Albany WY /
Albany ...), and a name-only unit both merged two states' backlogs into one
capped slice and let one state's rows starve another's. `ENRICH_STATE`
(comma-separated postal codes) narrows a run to some states - the manual
backfill dispatch uses it; the scheduled steps leave it unset.
"""
from __future__ import annotations

import os
import random
from collections import Counter
from typing import Iterable


def state_filter() -> list[str]:
    raw = os.environ.get("ENRICH_STATE", "")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def state_param(states: list[str]) -> dict:
    """PostgREST filter for the selected states (none = every state)."""
    if not states:
        return {}
    return {"state": "in.(" + ",".join(states) + ")"}


def outstanding_units(rows: Iterable[dict], *, shuffle: bool = True) -> list[tuple[tuple[str, str], int]]:
    """((state, county), outstanding rows) for every unit with work left."""
    counts = Counter((r.get("state") or "", r.get("county")) for r in rows if r.get("county"))
    units = sorted(counts)
    if shuffle:
        random.shuffle(units)
    return [(u, counts[u]) for u in units]


def unit_params(unit: tuple[str, str]) -> dict:
    state, county = unit
    params = {"county": f"eq.{county}"}
    if state:
        params["state"] = f"eq.{state}"
    return params


def label(unit: tuple[str, str]) -> str:
    state, county = unit
    return f"{county}, {state}" if state else county
