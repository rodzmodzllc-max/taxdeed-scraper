"""Boundary permission matrix: one row per parcel source, decided per use.

A registry APPROVED status is an enrichment decision (attributes, centroid
points). It is NOT permission to store or display a polygon, so this matrix is
separate and a source is enabled only when every condition below holds.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MATRIX = REPO / "data" / "parcel_boundary_permissions.csv"

POLICIES = {"DISABLED", "ELIGIBLE_NOT_ENABLED", "APPROVED"}


@dataclass(frozen=True)
class BoundaryPermission:
    source_id: str
    state: str
    enrichment_status: str
    boundary_policy: str
    geometry_verified: bool
    licence_evidence: str
    reason: str

    def enabled(self) -> bool:
        return self.boundary_policy == "APPROVED" and self.geometry_verified and bool(self.licence_evidence.strip())


def load_matrix(path: Path = MATRIX) -> dict[str, BoundaryPermission]:
    rows: dict[str, BoundaryPermission] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["boundary_policy"] not in POLICIES:
                raise ValueError(f"{r['source_id']}: unknown boundary_policy {r['boundary_policy']!r}")
            if r["source_id"] in rows:
                raise ValueError(f"duplicate source_id {r['source_id']}")
            rows[r["source_id"]] = BoundaryPermission(
                source_id=r["source_id"], state=r["state"], enrichment_status=r["enrichment_status"],
                boundary_policy=r["boundary_policy"], geometry_verified=r["geometry_verified"] == "yes",
                licence_evidence=r["licence_evidence"], reason=r["reason"])
    return rows


def enabled_sources(matrix: dict[str, BoundaryPermission]) -> list[str]:
    return sorted(s for s, p in matrix.items() if p.enabled())


def is_boundary_enabled(source_id: str, matrix: dict[str, BoundaryPermission] | None = None) -> bool:
    matrix = load_matrix() if matrix is None else matrix
    perm = matrix.get(source_id)
    return bool(perm and perm.enabled())
