"""The boundary refresh plan.

Built on the approved-source rules in harvesters/governance/source_approvals.py
(match_geometries, plan_geometry_refresh): exact-identifier association only,
one geometry per property, a read that is not COMPLETE changes nothing, and
nothing is ever deleted because it is missing from a read. On top of them,
the caveats parcel files are known for (the Florida DOR Readme names them as
topics; the rules below apply to every source):

* stacked polygons / several features for one identifier -> AMBIGUOUS;
* one feature whose identifier field lists several parcels -> refused
  (MULTI_PARCEL_FEATURE), never attached to any of them;
* one feature claimed by two records (duplicate records) -> AMBIGUOUS for all;
* a condominium unit or any record with no polygon of its own -> UNMATCHED;
* a feature with no usable geometry -> INVALID_GEOMETRY for its record;
* a property that already holds another source's boundary keeps it.

Pure functions, no I/O.
"""
from __future__ import annotations

import re
from collections import Counter

from harvesters.enrichment.parcels import normalize_id
from harvesters.governance.source_approvals import GeometryMatch, match_geometries, plan_geometry_refresh

from . import geometry
from .sources import BoundarySource, attribution

MULTI_PARCEL_SEPARATORS = re.compile(r"[,;|&/]|\s+AND\s+", re.I)


def _key(src: BoundarySource):
    return lambda v: normalize_id(v, src.id_rule) or ""


def prepare_features(raw_features: list[dict], src: BoundarySource) -> tuple[list[dict], dict]:
    """Usable features ({'attributes', 'geometry', 'sha256', 'feature_id'})
    and counts of the ones refused."""
    good: list[dict] = []
    refused: Counter = Counter()
    invalid_keys: set[str] = set()
    norm = _key(src)
    for f in raw_features:
        attrs = dict(f.get("properties") or f.get("attributes") or {})
        raw_key = attrs.get(src.feature_key_field)
        if raw_key is not None and MULTI_PARCEL_SEPARATORS.search(str(raw_key)):
            refused["MULTI_PARCEL_FEATURE"] += 1
            continue
        fid = attrs.get(src.feature_id_field) if src.feature_id_field else None
        if fid is None:
            fid = f.get("id")
        if fid is None or str(fid).strip() == "":
            refused["NO_FEATURE_ID"] += 1
            continue
        prep = geometry.prepare(f.get("geometry"))
        if not prep["ok"]:
            refused["INVALID_GEOMETRY"] += 1
            if norm(raw_key):
                invalid_keys.add(norm(raw_key))
            continue
        good.append({"attributes": attrs, "geometry": prep["geometry"], "sha256": prep["sha256"],
                     "feature_id": str(fid), "vertices_in": prep["vertices_in"], "vertices_out": prep["vertices_out"]})
    refused["_invalid_keys"] = invalid_keys  # type: ignore[assignment]
    return good, refused


def plan_refresh(records: list[dict], raw_features: list[dict], stored: dict, src: BoundarySource, *,
                 read_status: str, observed_at: str) -> dict:
    """What a refresh of `src` would write for `records`.

    records: property rows ({id, state, county, <record_key>}).
    stored:  property_id -> {source_id, content_sha256} for those properties
             (any source).
    Returns {'rows': [...to upsert...], 'counts': {...}, 'read_status'}.
    A read that is not COMPLETE returns no rows at all."""
    counts: Counter = Counter()
    if (read_status or "").upper() != "COMPLETE":
        counts["skipped_read_not_complete"] = 1
        return {"rows": [], "counts": dict(counts), "read_status": read_status}

    features, refused = prepare_features(raw_features, src)
    invalid_keys = refused.pop("_invalid_keys")
    counts.update(refused)
    norm = _key(src)

    # Another source's boundary is never replaced by this one.
    other = {pid for pid, row in stored.items() if row.get("source_id") != src.source_id}
    eligible = [r for r in records if r.get("id") not in other]
    counts["kept_other_source"] = len(records) - len(eligible)

    matches = match_geometries(eligible, features, record_key=src.record_key, feature_key=src.feature_key_field,
                               normalize=norm)
    claims = Counter(m.feature["feature_id"] for m in matches if m.outcome == "MATCHED")
    fixed: list[GeometryMatch] = []
    for m in matches:
        if m.outcome == "MATCHED" and claims[m.feature["feature_id"]] > 1:
            fixed.append(GeometryMatch(m.property_id, m.key, "AMBIGUOUS"))
        elif m.outcome == "UNMATCHED" and m.key in invalid_keys:
            fixed.append(GeometryMatch(m.property_id, m.key, "INVALID_GEOMETRY"))
        else:
            fixed.append(m)
    for m in fixed:
        counts[m.outcome.lower()] += 1

    # plan_geometry_refresh compares geometries; give it the content hashes.
    by_pid = {r.get("id"): r for r in eligible}
    hashed = [GeometryMatch(m.property_id, m.key, m.outcome, {"geometry": m.feature["sha256"], "_f": m.feature})
              if m.outcome == "MATCHED" else GeometryMatch(m.property_id, m.key,
                                                           "UNMATCHED" if m.outcome == "INVALID_GEOMETRY" else m.outcome)
              for m in fixed]
    own = {pid: {"geometry": row.get("content_sha256")} for pid, row in stored.items() if pid not in other}
    plan = plan_geometry_refresh(own, hashed, source_id=src.source_id, read_status="COMPLETE", observed_at=observed_at)
    feature_of = {m.property_id: m.feature["_f"] for m in hashed if m.outcome == "MATCHED"}
    credit = attribution(src.source_id).get("credit", "")
    rows = []
    for kind in ("insert", "replace"):
        for item in plan[kind]:
            pid = item["property_id"]
            f, rec = feature_of[pid], by_pid[pid]
            rows.append({
                "property_id": pid, "state": rec.get("state") or src.state, "county": rec.get("county") or "",
                "parcel": str(rec.get(src.record_key) or ""), "source_id": src.source_id,
                "source_dataset": src.dataset, "source_feature_id": f["feature_id"],
                "geometry": f["geometry"], "content_sha256": f["sha256"], "match_method": "EXACT_PARCEL_ID",
                "simplify_tolerance_deg": geometry.SIMPLIFY_TOLERANCE_DEG, "source_observed_at": observed_at,
                "attribution": credit, "change": kind,
            })
    counts["insert"] = len(plan["insert"])
    counts["replace"] = len(plan["replace"])
    counts["unchanged"] = len(plan["unchanged"])
    counts["kept_not_in_read"] = len(plan["kept_not_in_read"])
    counts["deleted"] = 0
    claimed = {norm(r.get(src.record_key)) for r in eligible}
    counts["unclaimed_features"] = sum(1 for f in features if norm(f["attributes"].get(src.feature_key_field)) not in claimed)
    return {"rows": rows, "counts": dict(counts), "read_status": read_status}
