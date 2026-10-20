"""Reader for a DOR PTO county PIN shapefile (geometry plus PARCELNO only).

Used by the Florida DOR boundary source (harvesters/boundary/sources.py FL_DOR).
Reads the shapefile's own .shp / .shx / .dbf, checks the projection it was
published in, reprojects every polygon to WGS84 and yields features in the
shape plan.prepare_features() expects:

    {"properties": {"PARCELNO": "...", "FID": n},
     "geometry": {"type": "MultiPolygon", "coordinates": [...]}}

Nothing here decides a match. plan.prepare_features() and
source_approvals.match_geometries() do that, on PARCELNO only, and a PARCELNO
held by more than one feature is refused as AMBIGUOUS there.

Dependencies: pyshp and pyproj (requirements are added to the governance CI
job). Nothing is read over the network here.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterator

import pyproj

# The projection the Broward PIN file (and the other PIN files) is published in:
# NAD83(HARN) / Florida East, US survey feet, as named in the .prj file.
PUBLISHED_PRJ_NAME = "NAD_1983_HARN_StatePlane_Florida_East_FIPS_0901_Feet"
WGS84 = "EPSG:4326"
SHAPE_NULL = 0
SHAPE_POLYGON_TYPES = {5, 15, 25}  # Polygon, PolygonZ, PolygonM


class UnsupportedProjection(ValueError):
    """The .prj is not the projection this reader was written for. Refuses before any feature is read."""


def _check_projection(prj_path: Path) -> pyproj.CRS:
    text = prj_path.read_text(encoding="utf-8", errors="replace")
    if PUBLISHED_PRJ_NAME not in text:
        raise UnsupportedProjection("UNSUPPORTED_PROJECTION: the .prj is not " + PUBLISHED_PRJ_NAME)
    return pyproj.CRS.from_wkt(text)


def _signed_area(ring) -> float:
    """Shoelace area in the ring's own units. Shapefile outer rings are clockwise (negative)."""
    total = 0.0
    n = len(ring)
    for i in range(n - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _polygon_coordinates(shape, transform) -> list | None:
    """MultiPolygon coordinates in WGS84 for one shapefile polygon, or None for a null shape."""
    if shape.shapeType == SHAPE_NULL or not shape.points:
        return None
    parts = list(shape.parts) + [len(shape.points)]
    rings = []
    for start, end in zip(parts[:-1], parts[1:]):
        ring_xy = shape.points[start:end]
        if len(ring_xy) < 4:
            # A degenerate ring is kept as-is so prepare() refuses it with its own reason.
            rings.append([list(p) for p in ring_xy])
            continue
        lon_lat = [list(transform(x, y)) for x, y in ring_xy]
        rings.append((lon_lat, _signed_area(ring_xy)))
    # Group: each clockwise (negative) ring starts a polygon; counter-clockwise
    # rings are holes of the polygon they follow.
    polygons: list[list[list[list[float]]]] = []
    for item in rings:
        if isinstance(item, list):           # degenerate ring: attach as an outer ring so it is refused
            polygons.append([item])
            continue
        lon_lat, area = item
        if area < 0 or not polygons:
            polygons.append([lon_lat])
        else:
            polygons[-1].append(lon_lat)
    return polygons


def read_pin_features(shp_path: str | Path, *, expected_prj: bool = True) -> Iterator[dict]:
    """Yield one feature per shapefile record, in WGS84.

    The .shp, .shx, .dbf (and .prj, if present) are read from alongside the
    given path. The field name PARCELNO is the join key and is kept exactly
    as published (no reformatting).
    """
    import shapefile  # pyshp

    shp_path = Path(shp_path)
    prj = shp_path.with_suffix(".prj")
    if expected_prj:
        if not prj.exists():
            raise UnsupportedProjection("UNSUPPORTED_PROJECTION: no .prj beside the shapefile")
        src_crs = _check_projection(prj)
        transform = pyproj.Transformer.from_crs(src_crs, WGS84, always_xy=True).transform
    else:
        transform = lambda x, y: (x, y)  # noqa: E731  - tests only: coordinates already WGS84

    with shapefile.Reader(str(shp_path)) as reader:
        fields = [f[0] for f in reader.fields[1:]]
        if "PARCELNO" not in fields:
            raise ValueError("PARCELNO field missing from the attribute table")
        for fid, sr in enumerate(reader.iterShapeRecords()):
            props = dict(zip(fields, sr.record))
            props = {k: ("" if v is None else str(v)) for k, v in props.items()}
            polys = _polygon_coordinates(sr.shape, transform) if sr.shape.shapeType in SHAPE_POLYGON_TYPES | {SHAPE_NULL} else None
            props["FID"] = fid
            yield {"properties": props,
                   "geometry": None if polys is None else {"type": "MultiPolygon", "coordinates": polys}}


def summarize(features) -> dict:
    """Counts only - never a parcel number. Safe for logs and the register."""
    counts = Counter()
    seen: Counter = Counter()
    for f in features:
        counts["features"] += 1
        if f.get("geometry") is None:
            counts["null_geometry"] += 1
        key = (f.get("properties") or {}).get("PARCELNO", "")
        if key:
            seen[key] += 1
        else:
            counts["blank_parcelno"] += 1
    counts["distinct_parcelno"] = len(seen)
    counts["shared_parcelno_values"] = sum(1 for v in seen.values() if v > 1)
    counts["features_sharing_a_parcelno"] = sum(v for v in seen.values() if v > 1)
    counts["largest_share"] = max(seen.values(), default=0)
    return dict(counts)
