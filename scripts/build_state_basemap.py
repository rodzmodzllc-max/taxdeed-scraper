#!/usr/bin/env python3
"""Build a state's same-origin county basemap + county centroids from the
Census-derived us-atlas topology (six-state expansion sprint).

    npm pack us-atlas@3.0.1 && tar xzf us-atlas-3.0.1.tgz
    python3 scripts/build_state_basemap.py --topology package/counties-10m.json \
        --fips 37 --code NC --name "North Carolina" --unit County

Writes public/<code>-counties.svg (or --svg), merges the state's county
centroids into public/county-centroids.json, and prints the projection
coefficients the frontend's PROJ / MINIMAP_PROJ tables need. Deterministic:
a direct equirectangular projection (longitude scaled by cos(mean
latitude)) - the same method la-parishes.svg / tx-counties.svg use - so the
coefficients are exact by construction, never a fit. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WIDTH = 1000.0
PAD = 20.0


def decode_arcs(topo: dict) -> list[list[tuple[float, float]]]:
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def ring(arcs, indexes) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for i in indexes:
        pts = arcs[i] if i >= 0 else list(reversed(arcs[~i]))
        out.extend(pts if not out else pts[1:])
    return out


def polygons(geom, arcs) -> list[list[list[tuple[float, float]]]]:
    if geom["type"] == "Polygon":
        return [[ring(arcs, r) for r in geom["arcs"]]]
    if geom["type"] == "MultiPolygon":
        return [[ring(arcs, r) for r in poly] for poly in geom["arcs"]]
    return []


def ring_area_centroid(pts):
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    return a / 2, cx, cy


def centroid(polys) -> tuple[float, float]:
    """Area-weighted centroid (lat, lng) of the county's polygons (outer
    rings add, holes subtract) in lon/lat - deterministic."""
    A = CX = CY = 0.0
    for poly in polys:
        for k, r in enumerate(poly):
            a, cx, cy = ring_area_centroid(r)
            sign = 1 if k == 0 else -1
            A += sign * abs(a)
            s = sign * (1 if a >= 0 else -1)
            CX += s * cx
            CY += s * cy
    if abs(A) < 1e-12:
        xs = [p[0] for poly in polys for p in poly[0]]
        ys = [p[1] for poly in polys for p in poly[0]]
        return round(sum(ys) / len(ys), 6), round(sum(xs) / len(xs), 6)
    return round(CY / (6 * A), 6), round(CX / (6 * A), 6)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--topology", required=True)
    ap.add_argument("--fips", required=True, help="two-digit state FIPS")
    ap.add_argument("--code", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--unit", default="County")
    ap.add_argument("--svg", default=None)
    ap.add_argument("--centroids", default=str(REPO / "public" / "county-centroids.json"))
    a = ap.parse_args(argv)
    topo = json.loads(Path(a.topology).read_text(encoding="utf-8"))
    arcs = decode_arcs(topo)
    counties = [g for g in topo["objects"]["counties"]["geometries"] if str(g["id"]).startswith(a.fips)]
    if not counties:
        raise SystemExit(f"no counties for FIPS {a.fips}")
    names = [g["properties"]["name"] for g in counties]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        # Two units with the same name (e.g. a county and an independent city)
        # would collide on data-county; name them apart explicitly.
        raise SystemExit(f"duplicate unit names {dupes} - disambiguate before building")
    all_pts = [p for g in counties for poly in polygons(g, arcs) for r in poly for p in r]
    lon_min, lon_max = min(p[0] for p in all_pts), max(p[0] for p in all_pts)
    lat_min, lat_max = min(p[1] for p in all_pts), max(p[1] for p in all_pts)
    cosphi = math.cos(math.radians((lat_min + lat_max) / 2))
    k = (WIDTH - 2 * PAD) / ((lon_max - lon_min) * cosphi)
    height = round((lat_max - lat_min) * k + 2 * PAD)

    def proj(lon, lat):
        return (lon - lon_min) * cosphi * k + PAD, (lat_max - lat) * k + PAD

    def path(polys):
        out = []
        for poly in polys:
            for r in poly:
                pts = [proj(*p) for p in r]
                out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
        return "".join(out)

    states = [g for g in topo["objects"]["states"]["geometries"] if str(g["id"]) != a.fips]
    neighbors, labels = [], []
    for g in states:
        polys = polygons(g, arcs)
        inside = [proj(*p) for poly in polys for r in poly for p in r]
        inside = [(x, y) for x, y in inside if -50 <= x <= WIDTH + 50 and -50 <= y <= height + 50]
        if len(inside) < 3:
            continue
        neighbors.append(f'<path class="neighbor-land" data-state="{g["properties"]["name"]}" d="{path(polys)}"/>')
        vis = [(x, y) for x, y in inside if 10 <= x <= WIDTH - 10 and 10 <= y <= height - 10]
        if len(vis) >= 3:
            lx, ly = sum(x for x, _ in vis) / len(vis), sum(y for _, y in vis) / len(vis)
            labels.append(f'<text class="map-label map-label-land" x="{lx:.1f}" y="{ly:.1f}">{g["properties"]["name"].upper()}</text>')
    code = a.code.upper()
    svg_id = code.lower() + "Map"
    paths = [f'<path data-county="{g["properties"]["name"]}" d="{path(polygons(g, arcs))}"/>'
             for g in sorted(counties, key=lambda g: g["properties"]["name"])]
    unit_plural = {"County": "counties", "Parish": "parishes"}.get(a.unit, a.unit.lower() + "s")
    svg = (f'<svg id="{svg_id}" viewBox="0 0 {int(WIDTH)} {height}" xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="Map of {a.name} {unit_plural}"><rect class="map-sea" x="0" y="0" width="{int(WIDTH)}" height="{height}"/>'
           f'<g class="map-neighbors" aria-hidden="true">{"".join(neighbors)}</g><g class="map-counties">{"".join(paths)}</g>'
           f'<g class="map-labels" aria-hidden="true">{"".join(labels)}</g></svg>')
    out_svg = Path(a.svg or REPO / "public" / f"{code.lower()}-counties.svg")
    out_svg.write_text(svg, encoding="utf-8")
    cent_path = Path(a.centroids)
    cent = json.loads(cent_path.read_text(encoding="utf-8"))
    cent[code] = {g["properties"]["name"]: {"fips": str(g["id"]), **dict(zip(("lat", "lng"), centroid(polygons(g, arcs))))}
                  for g in sorted(counties, key=lambda g: g["properties"]["name"])}
    cent_path.write_text(json.dumps(cent, indent=2) + "\n", encoding="utf-8")
    x_lon, x_c = cosphi * k / WIDTH, (PAD - lon_min * cosphi * k) / WIDTH
    y_lat, y_c = -k / height, (lat_max * k + PAD) / height
    print(json.dumps({"code": code, "svg": str(out_svg.relative_to(REPO)) if out_svg.is_relative_to(REPO) else str(out_svg),
                      "units": len(counties), "baseW": int(WIDTH), "baseH": height,
                      "proj": {"x": {"lon": round(x_lon, 9), "lat": 0, "c": round(x_c, 9)},
                               "y": {"lon": 0, "lat": round(y_lat, 9), "c": round(y_c, 9)}},
                      "center": [round((lon_min + lon_max) / 2, 2), round((lat_min + lat_max) / 2, 2)]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
