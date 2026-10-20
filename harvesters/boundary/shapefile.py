"""A small, strict reader for ESRI shapefiles (.shp + .dbf + .prj, loose or in
a .zip), enough for parcel polygons. Standard library only.

* Geometry: polygon shapes only (types 5 / 15 / 25; Z and M values are
  ignored). A null shape is reported as such, never as an empty polygon.
* Attributes: only the DBF fields the caller names are decoded; every other
  column is skipped unread. A character field is kept as its exact text
  with only the DBF's own right-padding removed, so leading zeros and inner
  spacing survive. A field the caller names that is NOT a character field
  is refused (`wanted_char_fields`): a numeric DBF field drops leading zeros,
  and an identifier must never pass through one.
* The DBF header's last-update date is returned (a dataset date, not a read
  time).
* Any structural inconsistency (record counts that disagree, a truncated
  record, an unknown shape type) raises ShapefileError: the read is
  incomplete, and the caller writes nothing for it.
"""
from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

POLYGON_TYPES = {5, 15, 25}
NULL_SHAPE = 0


class ShapefileError(ValueError):
    """The files are not a complete, consistent polygon shapefile."""


@dataclass(frozen=True)
class DbfField:
    name: str
    type: str
    length: int
    decimals: int
    offset: int


@dataclass
class Shapefile:
    name: str                        # stem of the .shp
    prj: str                         # the .prj text ('' when absent)
    dbf_date: date | None            # the DBF header's last-update date
    fields: dict[str, DbfField]
    records: list[dict]              # decoded wanted fields, one dict per record
    shapes: list[list[list[tuple[float, float]]] | None]   # per record: parts (rings) or None for a null shape


def _members(path: Path) -> dict[str, bytes]:
    """{'.shp': bytes, '.dbf': bytes, '.prj': bytes, '.cpg': bytes, '_stem': name} from a .zip
    (exactly one .shp inside) or from a .shp path with its siblings."""
    path = Path(path)
    out: dict[str, bytes] = {}
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            shps = [n for n in z.namelist() if n.lower().endswith(".shp")]
            if len(shps) != 1:
                raise ShapefileError(f"{path.name}: expected exactly one .shp in the archive, found {len(shps)}")
            stem = shps[0][:-4]
            for ext in (".shp", ".dbf", ".prj", ".cpg"):
                for n in z.namelist():
                    if n.lower() == (stem + ext).lower():
                        out[ext] = z.read(n)
            out["_stem"] = Path(stem).name.encode()
    else:
        stem = path.with_suffix("")
        for ext in (".shp", ".dbf", ".prj", ".cpg"):
            for cand in (stem.with_suffix(ext), stem.with_suffix(ext.upper())):
                if cand.exists():
                    out[ext] = cand.read_bytes()
                    break
        out["_stem"] = stem.name.encode()
    for ext in (".shp", ".dbf"):
        if ext not in out:
            raise ShapefileError(f"{path.name}: {ext} is missing")
    return out


def _read_dbf(data: bytes, wanted: tuple[str, ...], encoding: str):
    if len(data) < 32:
        raise ShapefileError("DBF header is truncated")
    yy, mm, dd = data[1], data[2], data[3]
    try:
        dbf_date = date(1900 + yy, mm, dd) if mm and dd else None
    except ValueError:
        dbf_date = None
    n_records, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields: dict[str, DbfField] = {}
    pos, offset = 32, 1
    while pos < header_len - 1 and data[pos] != 0x0D:
        raw = data[pos:pos + 32]
        if len(raw) < 32:
            raise ShapefileError("DBF field descriptor is truncated")
        name = raw[:11].split(b"\x00")[0].decode("ascii", "replace").strip()
        ftype = chr(raw[11])
        length, decimals = raw[16], raw[17]
        fields[name.upper()] = DbfField(name, ftype, length, decimals, offset)
        offset += length
        pos += 32
    if offset != record_len:
        raise ShapefileError(f"DBF record length {record_len} does not match its fields ({offset})")
    if len(data) < header_len + n_records * record_len:
        raise ShapefileError("DBF is truncated: fewer records than its header states")
    want = {w.upper() for w in wanted}
    records: list[dict] = []
    deleted: list[bool] = []
    for i in range(n_records):
        rec = data[header_len + i * record_len: header_len + (i + 1) * record_len]
        deleted.append(rec[:1] == b"*")
        row = {}
        for key in want:
            f = fields.get(key)
            if f is None:
                continue
            raw = rec[f.offset:f.offset + f.length]
            # Only the DBF's own right-padding is removed (and NUL padding some
            # writers use); leading characters are part of the value.
            row[f.name] = raw.decode(encoding, "replace").rstrip(" \x00")
        records.append(row)
    return dbf_date, fields, records, deleted


def _read_shp(data: bytes):
    if len(data) < 100:
        raise ShapefileError("SHP header is truncated")
    file_code, = struct.unpack(">i", data[0:4])
    file_len_words, = struct.unpack(">i", data[24:28])
    shape_type, = struct.unpack("<i", data[32:36])
    if file_code != 9994:
        raise ShapefileError("not a shapefile (bad file code)")
    if shape_type not in POLYGON_TYPES:
        raise ShapefileError(f"shape type {shape_type} is not a polygon shapefile")
    if file_len_words * 2 != len(data):
        raise ShapefileError("SHP is truncated or padded: its header length does not match the file")
    shapes = []
    pos = 100
    while pos < len(data):
        if pos + 8 > len(data):
            raise ShapefileError("SHP record header is truncated")
        _recno, content_words = struct.unpack(">ii", data[pos:pos + 8])
        content = data[pos + 8: pos + 8 + content_words * 2]
        if len(content) != content_words * 2:
            raise ShapefileError("SHP record is truncated")
        pos += 8 + content_words * 2
        rtype, = struct.unpack("<i", content[:4])
        if rtype == NULL_SHAPE:
            shapes.append(None)
            continue
        if rtype not in POLYGON_TYPES:
            raise ShapefileError(f"record shape type {rtype} in a polygon file")
        num_parts, num_points = struct.unpack("<ii", content[36:44])
        parts = list(struct.unpack(f"<{num_parts}i", content[44:44 + 4 * num_parts]))
        pts_at = 44 + 4 * num_parts
        flat = struct.unpack(f"<{2 * num_points}d", content[pts_at:pts_at + 16 * num_points])
        points = [(flat[2 * i], flat[2 * i + 1]) for i in range(num_points)]
        rings = []
        for k, start in enumerate(parts):
            end = parts[k + 1] if k + 1 < num_parts else num_points
            rings.append(points[start:end])
        shapes.append(rings)
    return shapes


def read(path, *, wanted_fields: tuple[str, ...], wanted_char_fields: tuple[str, ...] = ()) -> Shapefile:
    """Read a polygon shapefile. `wanted_fields` are decoded; the ones in
    `wanted_char_fields` must exist and be character (C) fields."""
    m = _members(Path(path))
    encoding = "latin-1"
    if ".cpg" in m:
        cpg = m[".cpg"].decode("ascii", "replace").strip().lower()
        encoding = {"utf-8": "utf-8", "utf8": "utf-8", "65001": "utf-8"}.get(cpg, "latin-1")
    dbf_date, fields, records, deleted = _read_dbf(m[".dbf"], wanted_fields, encoding)
    for name in wanted_char_fields:
        f = fields.get(name.upper())
        if f is None:
            raise ShapefileError(f"field {name} is missing from the DBF")
        if f.type != "C":
            raise ShapefileError(f"field {name} is a {f.type!r} DBF field, not character: identifiers would lose "
                                 "their formatting")
    shapes = _read_shp(m[".shp"])
    if len(shapes) != len(records):
        raise ShapefileError(f"SHP has {len(shapes)} records but the DBF has {len(records)}")
    keep = [i for i, d in enumerate(deleted) if not d]
    return Shapefile(name=m["_stem"].decode("utf-8", "replace"), prj=m.get(".prj", b"").decode("latin-1").strip(),
                     dbf_date=dbf_date, fields=fields, records=[records[i] for i in keep],
                     shapes=[shapes[i] for i in keep])


def rings_to_multipolygon(rings: list[list[tuple[float, float]]]) -> list[list[list[tuple[float, float]]]] | None:
    """Shapefile rings -> MultiPolygon parts. Outer rings are clockwise and
    holes counter-clockwise (the shapefile rule); each hole goes to the outer
    ring that contains it. A hole inside no outer ring makes the shape
    invalid (None) - it is never promoted to an outer ring by guesswork."""
    def area(r):
        return sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1)) / 2

    def inside(pt, ring):
        x, y = pt
        hit = False
        for i in range(len(ring) - 1):
            (x1, y1), (x2, y2) = ring[i], ring[i + 1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                hit = not hit
        return hit

    closed = []
    for r in rings:
        r = list(r)
        if len(r) >= 3 and r[0] != r[-1]:
            r.append(r[0])
        closed.append(r)
    outers = [r for r in closed if len(r) >= 4 and area(r) < 0]
    holes = [r for r in closed if len(r) >= 4 and area(r) > 0]
    if not outers:
        return None
    polys = [[o] for o in outers]
    for h in holes:
        host = next((p for p in polys if inside(h[0], p[0])), None)
        if host is None:
            return None
        host.append(h)
    return polys

