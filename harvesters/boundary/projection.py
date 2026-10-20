"""Coordinate systems of parcel shapefiles: read the file's own .prj and
convert its coordinates to longitude / latitude.

Only what Florida parcel files are delivered in is supported, and anything
else is REFUSED rather than guessed:

* a geographic system (GEOGCS) on NAD83 / NAD83(HARN) / NAD83(2011) / WGS84;
* PROJCS with PROJECTION Albers (equal-area conic, two standard parallels),
  Lambert_Conformal_Conic (two standard parallels) or Transverse_Mercator,
  on the GRS 1980 / WGS 84 ellipsoid, in meters or (US survey / international)
  feet.

NAD83 realizations are treated as WGS84: the difference is under about 2 m in
Florida, below what a simplified parcel outline over aerial imagery shows. The
change notice says so. NAD27 and any other datum are refused.

The inverse formulas are Snyder, "Map Projections - A Working Manual" (USGS
Professional Paper 1395): Albers 14-18..14-21 / 3-16, Lambert conformal conic
15-9..15-11 / 7-9, transverse Mercator 8-18..8-25. tests/python/
test_fl_dor_boundaries.py checks them against PROJ (pyproj) where installed.

Standard library only.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

# A datum name is accepted when it names NAD 1983 (any realization) or
# WGS 1984, and never when it names 1927.
ACCEPTED_DATUM_MARKERS = ("NORTH_AMERICAN_1983", "NORTH_AMERICAN_DATUM_1983", "NAD_1983", "NAD83", "WGS_1984", "WGS84")
ACCEPTED_ELLIPSOIDS = {"GRS_1980": (6378137.0, 298.257222101), "GRS 1980": (6378137.0, 298.257222101),
                       "WGS_1984": (6378137.0, 298.257223563), "WGS 84": (6378137.0, 298.257223563)}
PROJECTIONS = {"albers": "albers", "albers_conic_equal_area": "albers",
               "lambert_conformal_conic": "lcc", "lambert_conformal_conic_2sp": "lcc",
               "transverse_mercator": "tm"}


class UnsupportedProjection(ValueError):
    """The .prj names a datum, ellipsoid, projection or parameter set this
    reader does not support. The file is refused, never read approximately."""


@dataclass(frozen=True)
class Crs:
    kind: str                      # geographic | albers | lcc | tm
    datum: str
    a: float = 6378137.0
    inv_f: float = 298.257222101
    unit_m: float = 1.0            # meters per linear unit
    params: tuple = ()             # sorted (name, value) pairs, degrees / linear units

    def param(self, *names, default=None):
        d = dict(self.params)
        for n in names:
            if n in d:
                return d[n]
        if default is not None:
            return default
        raise UnsupportedProjection(f"missing parameter {names[0]}")


def _quoted(tag: str, wkt: str) -> list[str]:
    return re.findall(tag + r'\[\s*"([^"]+)"', wkt, re.I)


def parse_prj(wkt: str) -> Crs:
    text = (wkt or "").strip()
    if not text:
        raise UnsupportedProjection("no .prj: the coordinate system is unknown")
    datums = _quoted("DATUM", text)
    datum = datums[0].upper() if datums else ""
    if "1927" in datum or not any(m in datum.replace(" ", "_") for m in ACCEPTED_DATUM_MARKERS):
        raise UnsupportedProjection(f"datum {datum or '(none)'} is not NAD83 / WGS84")
    sph = re.search(r'SPHEROID\[\s*"([^"]+)"\s*,\s*([0-9.eE+-]+)\s*,\s*([0-9.eE+-]+)', text, re.I)
    if not sph:
        raise UnsupportedProjection("no SPHEROID")
    a, inv_f = float(sph.group(2)), float(sph.group(3))
    if abs(a - 6378137.0) > 0.001 or not (298.2572 < inv_f < 298.2573):
        raise UnsupportedProjection(f"ellipsoid {sph.group(1)} is not GRS 1980 / WGS 84")
    if not text.upper().startswith("PROJCS"):
        if not text.upper().startswith("GEOGCS"):
            raise UnsupportedProjection("neither PROJCS nor GEOGCS")
        return Crs("geographic", datum, a, inv_f)
    proj = _quoted("PROJECTION", text)
    kind = PROJECTIONS.get(proj[0].lower()) if proj else None
    if not kind:
        raise UnsupportedProjection(f"projection {proj[0] if proj else '(none)'} is not supported")
    params = tuple(sorted((m.group(1).lower(), float(m.group(2)))
                          for m in re.finditer(r'PARAMETER\[\s*"([^"]+)"\s*,\s*([0-9.eE+-]+)', text, re.I)))
    # The projected linear unit is the LAST UNIT of the PROJCS (the GEOGCS
    # carries its own angular unit earlier).
    units = re.findall(r'UNIT\[\s*"([^"]+)"\s*,\s*([0-9.eE+-]+)', text, re.I)
    if not units:
        raise UnsupportedProjection("no linear UNIT")
    unit_name, unit_m = units[-1][0].lower(), float(units[-1][1])
    if not (abs(unit_m - 1.0) < 1e-12 or abs(unit_m - 0.3048006096012192) < 1e-12 or abs(unit_m - 0.3048) < 1e-12):
        raise UnsupportedProjection(f"linear unit {unit_name} ({unit_m} m) is not meter / foot")
    crs = Crs(kind, datum, a, inv_f, unit_m, params)
    if kind in ("albers", "lcc"):
        sp1 = crs.param("standard_parallel_1")
        sp2 = crs.param("standard_parallel_2", default=sp1)
        if kind == "lcc" and sp1 == sp2 and "standard_parallel_2" not in dict(params):
            raise UnsupportedProjection("Lambert conformal conic with one standard parallel is not supported")
    return crs


def _e(crs: Crs):
    f = 1 / crs.inv_f
    e2 = 2 * f - f * f
    return e2, math.sqrt(e2)


def _m(phi, e2):
    return math.cos(phi) / math.sqrt(1 - e2 * math.sin(phi) ** 2)


def _q(phi, e2, e):
    s = math.sin(phi)
    return (1 - e2) * (s / (1 - e2 * s * s) - (1 / (2 * e)) * math.log((1 - e * s) / (1 + e * s)))


def _t(phi, e):
    s = math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - e * s) / (1 + e * s)) ** (e / 2)


def _albers_inverse(crs: Crs, x, y):
    e2, e = _e(crs)
    a = crs.a
    lat0 = math.radians(crs.param("latitude_of_origin", "latitude_of_center"))
    lon0 = math.radians(crs.param("central_meridian", "longitude_of_center"))
    p1 = math.radians(crs.param("standard_parallel_1"))
    p2 = math.radians(crs.param("standard_parallel_2"))
    m1, m2 = _m(p1, e2), _m(p2, e2)
    q0, q1, q2 = _q(lat0, e2, e), _q(p1, e2, e), _q(p2, e2, e)
    n = (m1 * m1 - m2 * m2) / (q2 - q1)
    c = m1 * m1 + n * q1
    rho0 = a * math.sqrt(c - n * q0) / n
    xp, yp = x, rho0 - y
    rho = math.copysign(math.hypot(xp, yp), n)
    theta = math.atan2(xp * (1 if n > 0 else -1), yp * (1 if n > 0 else -1))
    q = (c - (rho * n / a) ** 2) / n
    phi = math.asin(max(-1.0, min(1.0, q / 2)))
    for _ in range(25):
        s = math.sin(phi)
        d = ((1 - e2 * s * s) ** 2 / (2 * math.cos(phi))) * (
            q / (1 - e2) - s / (1 - e2 * s * s) + (1 / (2 * e)) * math.log((1 - e * s) / (1 + e * s)))
        phi += d
        if abs(d) < 1e-14:
            break
    return math.degrees(lon0 + theta / n), math.degrees(phi)


def _lcc_inverse(crs: Crs, x, y):
    e2, e = _e(crs)
    a = crs.a
    lat0 = math.radians(crs.param("latitude_of_origin"))
    lon0 = math.radians(crs.param("central_meridian"))
    p1 = math.radians(crs.param("standard_parallel_1"))
    p2 = math.radians(crs.param("standard_parallel_2"))
    m1, m2 = _m(p1, e2), _m(p2, e2)
    t0, t1, t2 = _t(lat0, e), _t(p1, e), _t(p2, e)
    n = (math.log(m1) - math.log(m2)) / (math.log(t1) - math.log(t2))
    big_f = m1 / (n * t1 ** n)
    rho0 = a * big_f * t0 ** n
    xp, yp = x, rho0 - y
    rho = math.copysign(math.hypot(xp, yp), n)
    theta = math.atan2(xp * (1 if n > 0 else -1), yp * (1 if n > 0 else -1))
    t = (rho / (a * big_f)) ** (1 / n)
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(25):
        s = math.sin(phi)
        nxt = math.pi / 2 - 2 * math.atan(t * ((1 - e * s) / (1 + e * s)) ** (e / 2))
        if abs(nxt - phi) < 1e-14:
            phi = nxt
            break
        phi = nxt
    return math.degrees(theta / n + lon0), math.degrees(phi)


def _meridian(phi, a, e2):
    e4, e6 = e2 * e2, e2 * e2 * e2
    return a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                - (35 * e6 / 3072) * math.sin(6 * phi))


def _tm_inverse(crs: Crs, x, y):
    e2, _ = _e(crs)
    a = crs.a
    k0 = crs.param("scale_factor", default=1.0)
    lat0 = math.radians(crs.param("latitude_of_origin", default=0.0))
    lon0 = math.radians(crs.param("central_meridian"))
    ep2 = e2 / (1 - e2)
    m = _meridian(lat0, a, e2) + y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    s1, c1, tn = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    big_c = ep2 * c1 * c1
    big_t = tn * tn
    n1 = a / math.sqrt(1 - e2 * s1 * s1)
    r1 = a * (1 - e2) / (1 - e2 * s1 * s1) ** 1.5
    d = x / (n1 * k0)
    phi = phi1 - (n1 * tn / r1) * (d ** 2 / 2 - (5 + 3 * big_t + 10 * big_c - 4 * big_c ** 2 - 9 * ep2) * d ** 4 / 24
                                   + (61 + 90 * big_t + 298 * big_c + 45 * big_t ** 2 - 252 * ep2 - 3 * big_c ** 2)
                                   * d ** 6 / 720)
    lam = lon0 + (d - (1 + 2 * big_t + big_c) * d ** 3 / 6
                  + (5 - 2 * big_c + 28 * big_t - 3 * big_c ** 2 + 8 * ep2 + 24 * big_t ** 2) * d ** 5 / 120) / c1
    return math.degrees(lam), math.degrees(phi)


def to_lonlat(crs: Crs, x: float, y: float) -> tuple[float, float]:
    """One coordinate of the file's own system as (longitude, latitude)."""
    if crs.kind == "geographic":
        return float(x), float(y)
    fe = crs.param("false_easting", default=0.0) * crs.unit_m
    fn = crs.param("false_northing", default=0.0) * crs.unit_m
    xm, ym = x * crs.unit_m - fe, y * crs.unit_m - fn
    if crs.kind == "albers":
        return _albers_inverse(crs, xm, ym)
    if crs.kind == "lcc":
        return _lcc_inverse(crs, xm, ym)
    return _tm_inverse(crs, xm, ym)
