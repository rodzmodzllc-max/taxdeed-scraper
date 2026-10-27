"""Read one county's published parcel file (a zipped shapefile) for the
enrichment factory's `county_file` transport (TX enrichment, 2026-10-27).

The Texas Geographic Information Office (TxGIO) publishes the StratMap land
parcels as one zipped shapefile per county. Its map service refuses every
query ("Requested operation is not supported by this service", read
2026-10-27), so the file is the only machine-readable path. This module:

  * opens the zip's attribute table (.dbf) and keeps ONLY the records whose
    identifier - normalized by the county's measured rule - is one of the
    requested keys (the rest of the county is never kept in memory);
  * returns them as factory features ({"attributes": {...}}), so the normal
    index / exact-match / ambiguity rules of parcels.py decide everything;
  * when the config asks for a centroid AND the file's .prj declares
    geographic WGS 84 coordinates, adds the matched record's polygon rings
    (the parcel's own geometry, never a geocode). Any other projection: no
    geometry, so no coordinates are derived.

No network I/O here: the caller hands in a local zip path.
"""
from __future__ import annotations

import tempfile
import zipfile
from contextlib import ExitStack
from typing import Iterable

from .parcels import ParcelSourceConfig, normalize_id

__all__ = ["read_county_zip", "is_wgs84_geographic", "shape_rings"]


def is_wgs84_geographic(prj_text: str) -> bool:
    t = (prj_text or "").upper()
    return t.startswith("GEOGCS[") and "WGS_1984" in t and "PROJCS" not in t


def shape_rings(shape) -> list[list[list[float]]]:
    """Esri-JSON-style rings from a pyshp polygon shape."""
    pts = [list(p[:2]) for p in (shape.points or [])]
    parts = list(shape.parts or []) + [len(pts)]
    return [pts[parts[i]:parts[i + 1]] for i in range(len(parts) - 1) if parts[i + 1] - parts[i] >= 3]


def _member(names: list[str], ext: str) -> str | None:
    found = [n for n in names if n.lower().endswith(ext)]
    return found[0] if len(found) == 1 else None


def read_county_zip(zip_path, cfg: ParcelSourceConfig, county: str, keys: Iterable[str]) -> list[dict]:
    """Features (attributes, and rings when allowed) for the records of
    `county`'s file whose identifier normalizes to one of `keys`. Raises
    ValueError when the zip is not one shapefile (a changed format is a
    failed read, never an empty one)."""
    import shapefile  # pyshp; installed by the workflow step

    wanted = {k for k in keys if k}
    fields_, rule = cfg.id_fields(county), cfg.id_rule_for(county)
    with zipfile.ZipFile(zip_path) as z, tempfile.TemporaryDirectory() as tmp:
        names = z.namelist()
        dbf_name, shp_name, shx_name, prj_name = (_member(names, e) for e in (".dbf", ".shp", ".shx", ".prj"))
        if not dbf_name:
            raise ValueError("county file holds no single .dbf attribute table")
        geo = bool(cfg.centroid and shp_name and shx_name and prj_name
                   and is_wgs84_geographic(z.read(prj_name).decode("utf-8", "replace")))
        # Extracted to disk, never read into memory: one county's table can
        # exceed a gigabyte (Dallas, 2026).
        paths = {n: z.extract(n, tmp) for n in ([dbf_name, shp_name, shx_name] if geo else [dbf_name])}
        with ExitStack() as stack:
            fh = {n: stack.enter_context(open(p, "rb")) for n, p in paths.items()}
            if geo:
                reader = shapefile.Reader(dbf=fh[dbf_name], shp=fh[shp_name], shx=fh[shx_name])
            else:
                reader = shapefile.Reader(dbf=fh[dbf_name])
            names_ = [f[0] for f in reader.fields[1:]]
            missing = [f for f in fields_ if f not in names_]
            if missing:
                raise ValueError(f"county file lacks identifier attribute(s) {missing}")
            out = []
            for i, rec in enumerate(reader.iterRecords()):
                attrs = dict(zip(names_, rec))
                if not any(normalize_id(attrs.get(f), rule) in wanted for f in fields_):
                    continue
                attrs = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in attrs.items()}
                ft = {"attributes": attrs}
                if geo:
                    ft["geometry"] = {"rings": shape_rings(reader.shape(i))}
                out.append(ft)
    return out
