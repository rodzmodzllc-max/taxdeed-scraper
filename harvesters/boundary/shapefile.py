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

import hashlib
import shutil
from collections import Counter
from pathlib import Path
from typing import Iterator

import pyproj

# The projection the Broward PIN file is published in: NAD83(HARN) / Florida
# East, US survey feet, as named in the .prj file. Other counties publish in the
# other Florida State Plane zones (West, North) or Florida GDL Albers; all of
# them are accepted on a NAD83 datum. Anything else (WGS84, NAD27, UTM, an
# unreadable .prj) is refused before any feature is read.
PUBLISHED_PRJ_NAME = "NAD_1983_HARN_StatePlane_Florida_East_FIPS_0901_Feet"
NAD83_DATUM_MARKERS = ("NAD83", "North American Datum 1983")
WGS84 = "EPSG:4326"
SHAPE_NULL = 0
SHAPE_POLYGON_TYPES = {5, 15, 25}  # Polygon, PolygonZ, PolygonM
IDENTIFIER_FIELD = "PARCELNO"
# The only attributes ever kept: the join key, and the county number when a
# file carries one (to check the file is the county it was given as). A PAR
# file's assessment columns are never kept.
KEPT_FIELDS = ("PARCELNO", "CO_NO")
SHAPEFILE_PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg")


class UnsupportedProjection(ValueError):
    """The .prj is not a projection this reader was written for. Refuses before any feature is read."""


class UnsupportedFormat(ValueError):
    """The attribute table cannot be joined safely (missing or non-character PARCELNO)."""


def _check_projection(prj_path: Path) -> pyproj.CRS:
    text = prj_path.read_text(encoding="utf-8", errors="replace")
    try:
        crs = pyproj.CRS.from_wkt(text)
    except pyproj.exceptions.CRSError as exc:
        raise UnsupportedProjection("UNSUPPORTED_PROJECTION: the .prj cannot be read") from exc
    datum = crs.datum.name if crs.datum else ""
    if not (crs.is_projected and "Florida" in crs.name and any(m in datum for m in NAD83_DATUM_MARKERS)):
        raise UnsupportedProjection("UNSUPPORTED_PROJECTION: not a NAD83 Florida State Plane / GDL Albers projection")
    return crs


def dbf_date(shp_path: str | Path) -> str | None:
    """The DBF header's own last-update date (YYYY-MM-DD), or None."""
    dbf = Path(shp_path).with_suffix(".dbf")
    try:
        head = dbf.read_bytes()[:4]
        y, m, d = 1900 + head[1], head[2], head[3]
        import datetime  # noqa: PLC0415
        return datetime.date(y, m, d).isoformat()
    except (OSError, IndexError, ValueError):
        return None


def extract_zip(zip_path: str | Path, out_dir: str | Path) -> Path:
    """Extract only the shapefile parts of a county ZIP, refusing any path that
    leaves out_dir. Returns the one .shp."""
    import zipfile  # noqa: PLC0415
    out_dir = Path(out_dir)
    shp_names = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise RuntimeError("unsafe path in ZIP")
            if not name.lower().endswith(SHAPEFILE_PARTS):
                continue
            target = out_dir / Path(name).name
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)   # streamed: a county .shp is over 1 GB
            if name.lower().endswith(".shp"):
                shp_names.append(target)
    if len(shp_names) != 1:
        raise RuntimeError("expected exactly one .shp in the ZIP")
    return shp_names[0]


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
            # A degenerate ring is kept (reprojected like any other) so prepare() refuses it with its own reason.
            rings.append([list(transform(x, y)) for x, y in ring_xy])
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


def read_pin_features(shp_path: str | Path, *, expected_prj: bool = True, keep=None) -> Iterator[dict]:
    """Yield one feature per shapefile record, in WGS84.

    The .shp, .shx, .dbf (and .prj, if present) are read from alongside the
    given path. The field name PARCELNO is the join key and is kept exactly
    as published (no reformatting; only the DBF's right-padding is removed).
    Only PARCELNO and CO_NO are kept; every other column is dropped.

    keep: optional predicate on the kept attributes. A feature it rejects is
    yielded WITHOUT reprojection: geometry None, `skipped` True and `raw_sha`
    (a hash of the file's own coordinates), so a caller can still recognise one
    polygon published under several PARCELNOs without holding the whole
    county in memory.
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

    _check_complete(shp_path)
    with shapefile.Reader(str(shp_path)) as reader:
        fields = [f[0] for f in reader.fields[1:]]
        types = {f[0]: str(f[1]) for f in reader.fields[1:]}
        if IDENTIFIER_FIELD not in fields:
            raise UnsupportedFormat("PARCELNO field missing from the attribute table")
        if types[IDENTIFIER_FIELD] != "C":
            # A numeric field would have dropped leading zeros: the formatting
            # problem the Readme warns about. Refuse rather than join.
            raise UnsupportedFormat("PARCELNO is not a character field")
        shapes = reader.iterShapes()
        for fid, record in enumerate(reader.iterRecords()):
            props = {k: ("" if v is None else str(v)) for k, v in zip(fields, record) if k in KEPT_FIELDS}
            # One malformed shape (e.g. a PolygonZ with no points, seen in a
            # 2026 county file) must not fail the whole county: it is reported
            # as malformed and the read goes on. The shapes stream is read in
            # step with the records; after a malformed one it is resumed at
            # the next record by index.
            try:
                shape = next(shapes)
            except StopIteration:
                raise UnsupportedFormat("fewer shapes than attribute records")
            except Exception:  # noqa: BLE001 - pyshp raises its own types for a bad shape
                shape = None
                shapes = _shapes_from(reader, fid + 1)
            if shape is None:
                props["FID"] = fid
                out = {"properties": props, "geometry": None, "malformed": True}
                if keep is not None:
                    out["raw_sha"] = hashlib.sha256(b"malformed:%d" % fid).digest()
                    out["skipped"] = not keep(props)
                yield out
                continue
            if keep is not None:
                pts = shape.points if shape.shapeType != SHAPE_NULL else []
                raw_sha = hashlib.sha256(repr((list(getattr(shape, "parts", [])), pts)).encode()).digest()
                if not keep(props):
                    props["FID"] = fid
                    yield {"properties": props, "geometry": None, "skipped": True, "raw_sha": raw_sha}
                    continue
            polys = _polygon_coordinates(shape, transform) if shape.shapeType in SHAPE_POLYGON_TYPES | {SHAPE_NULL} else None
            props["FID"] = fid
            out = {"properties": props,
                   "geometry": None if polys is None else {"type": "MultiPolygon", "coordinates": polys}}
            if keep is not None:
                out["raw_sha"] = raw_sha
            yield out


def _check_complete(shp_path: Path) -> None:
    """A truncated or padded .shp (an interrupted download) fails the read: the
    header's own file length (16-bit words, big-endian, bytes 24-27) must equal
    the file's size. A single malformed shape inside a complete file does not."""
    size = shp_path.stat().st_size
    with open(shp_path, "rb") as fh:
        head = fh.read(28)
    if len(head) < 28 or int.from_bytes(head[24:28], "big") * 2 != size:
        raise UnsupportedFormat("TRUNCATED_FILE: the .shp is not the length its header states")


def _shapes_from(reader, start: int):
    """Shapes from record index `start` on, each read by index (after a
    malformed shape the sequential stream cannot be resumed). A further
    malformed shape yields None."""
    i = start
    while True:
        try:
            yield reader.shape(i)
        except IndexError:
            return
        except Exception:  # noqa: BLE001
            yield None
        i += 1


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
