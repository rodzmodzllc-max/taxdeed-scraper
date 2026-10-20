"""Boundary geometry: validation, MultiPolygon normalisation, simplification
and the content hash.

`validate()` mirrors public/parcel-boundary.js validateBoundary(), so what is
stored is exactly what the front end accepts (pinned by
tests/python/test_parcel_boundaries.py). Simplification reuses
source_approvals.simplify_ring() (Douglas-Peucker; a ring stays closed, keeps
at least four positions and never collapses to zero area).

Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import math

from harvesters.governance.source_approvals import simplify_ring

# About 0.5 m at Florida / Utah latitudes. Enough to drop the vertex noise of
# county parcel files while keeping every corner a viewer can see on an
# aerial at parcel scale (the property page renders roughly 1-2 m per pixel).
SIMPLIFY_TOLERANCE_DEG = 0.000005
# 7 decimals of a degree is about 1 cm: far below the simplification step.
COORD_DECIMALS = 7


def _ring_area(ring) -> float:
    return sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1)) / 2


def _ring_problem(ring) -> str | None:
    if not isinstance(ring, list) or len(ring) < 4:
        return "short_ring"
    for pos in ring:
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
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


def to_multipolygon(geo) -> dict | None:
    """A GeoJSON Polygon becomes a one-part MultiPolygon; a MultiPolygon is
    returned as is; anything else (points, lines, collections, Esri JSON) is
    refused with None - never converted by guesswork."""
    if not isinstance(geo, dict):
        return None
    t = geo.get("type")
    if t == "MultiPolygon":
        return {"type": "MultiPolygon", "coordinates": geo.get("coordinates")}
    if t == "Polygon":
        return {"type": "MultiPolygon", "coordinates": [geo.get("coordinates")]}
    return None


def _round(ring):
    return [[round(float(p[0]), COORD_DECIMALS), round(float(p[1]), COORD_DECIMALS)] for p in ring]


def simplify(geo: dict, tolerance: float = SIMPLIFY_TOLERANCE_DEG) -> dict:
    """The simplified, rounded MultiPolygon. Every part and every ring (holes
    included) is kept; only vertices inside the tolerance go. When rounding or
    simplification would leave an invalid ring, that ring keeps its rounded
    original vertices."""
    out = []
    for poly in geo["coordinates"]:
        rings = []
        for ring in poly:
            r = _round(ring)
            if r[0] != r[-1]:
                r.append(list(r[0]))
            s = _round(simplify_ring(r, tolerance)) if len(r) >= 4 else r
            rings.append(s if _ring_problem(s) is None else r)
        out.append(rings)
    return {"type": "MultiPolygon", "coordinates": out}


def vertex_count(geo: dict) -> int:
    return sum(len(ring) for poly in geo["coordinates"] for ring in poly)


def content_sha256(geo: dict) -> str:
    """Hash of the canonical GeoJSON, so an unchanged geometry is recognised
    and never rewritten."""
    return hashlib.sha256(json.dumps(geo, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def prepare(raw_geometry) -> dict:
    """{'ok': True, 'geometry', 'sha256', 'vertices_in', 'vertices_out'} or
    {'ok': False, 'reason'} for one feature's raw GeoJSON geometry."""
    mp = to_multipolygon(raw_geometry)
    if mp is None:
        return {"ok": False, "reason": "unsupported_type" if raw_geometry is not None else "missing"}
    v = validate(mp)
    if not v["ok"]:
        return v
    simple = simplify(mp)
    v2 = validate(simple)
    if not v2["ok"]:
        return {"ok": False, "reason": "simplification_" + v2["reason"]}
    return {"ok": True, "geometry": simple, "sha256": content_sha256(simple),
            "vertices_in": vertex_count(mp), "vertices_out": vertex_count(simple)}
