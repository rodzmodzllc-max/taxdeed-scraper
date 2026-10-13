"""Boundary geometry: validation, point match and the write decision.

Mirrors public/parcel-boundary.js (validateBoundary / pointMatchesBoundary) so
that what is stored is what the front end will accept. Pinned by
tests/python/test_parcel_boundary_permissions.py.
"""
from __future__ import annotations

import hashlib
import json
import math

POINT_TOLERANCE_DEG = 0.0005


def _ring_problem(ring) -> str | None:
    if not isinstance(ring, list) or len(ring) < 4:
        return "short_ring"
    for pos in ring:
        if not isinstance(pos, list) or len(pos) < 2:
            return "malformed"
        x, y = pos[0], pos[1]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (x, y)):
            return "malformed"
        if not (-180 <= x <= 180 and -90 <= y <= 90):
            return "out_of_range"
    if ring[0][0] != ring[-1][0] or ring[0][1] != ring[-1][1]:
        return "open_ring"
    if _ring_area(ring) == 0:
        return "zero_area"
    return None


def _ring_area(ring) -> float:
    return sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1)) / 2


def validate(geo) -> dict:
    """{'ok': True, 'polygons', 'bbox'} or {'ok': False, 'reason'}. MultiPolygon only."""
    if geo is None:
        return {"ok": False, "reason": "missing"}
    if isinstance(geo, str):
        try:
            geo = json.loads(geo)
        except ValueError:
            return {"ok": False, "reason": "malformed"}
    if not isinstance(geo, dict):
        return {"ok": False, "reason": "malformed"}
    if geo.get("type") != "MultiPolygon":
        return {"ok": False, "reason": "unsupported_type"}
    coords = geo.get("coordinates")
    if not isinstance(coords, list) or not coords:
        return {"ok": False, "reason": "empty"}
    xs, ys = [], []
    for poly in coords:
        if not isinstance(poly, list) or not poly:
            return {"ok": False, "reason": "malformed"}
        for ring in poly:
            problem = _ring_problem(ring)
            if problem:
                return {"ok": False, "reason": problem}
            xs += [p[0] for p in ring]
            ys += [p[1] for p in ring]
    return {"ok": True, "polygons": coords,
            "bbox": {"minX": min(xs), "minY": min(ys), "maxX": max(xs), "maxY": max(ys)}}


def point_matches(lng: float, lat: float, bbox: dict) -> bool:
    t = POINT_TOLERANCE_DEG
    return bbox["minX"] - t <= lng <= bbox["maxX"] + t and bbox["minY"] - t <= lat <= bbox["maxY"] + t


def content_sha256(geo: dict) -> str:
    """Hash of the canonical GeoJSON, so an unchanged geometry is recognised."""
    return hashlib.sha256(json.dumps(geo, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def decide_write(existing: dict | None, incoming: dict) -> str:
    """Never overwrite good geometry with weaker or older data.

    existing / incoming carry: source_id, source_observed_at (ISO date string),
    content_sha256, valid (bool). Returns one of:
      skip_invalid, insert, unchanged, replace, keep_existing_other_source, keep_newer_existing
    """
    if not incoming.get("valid"):
        return "skip_invalid"
    if existing is None:
        return "insert"
    if existing["content_sha256"] == incoming["content_sha256"]:
        return "unchanged"
    if existing["source_id"] != incoming["source_id"]:
        return "keep_existing_other_source"
    if incoming["source_observed_at"] > existing["source_observed_at"]:
        return "replace"
    return "keep_newer_existing"
