"""Parcel boundaries from the two approved parcel-geometry sources.

* geometry.py - validation, MultiPolygon normalisation, simplification,
  content hash. Mirrors public/parcel-boundary.js validateBoundary().
* sources.py  - the two boundary sources (Florida DOR county parcel files,
  UGRC Salt Lake LIR), their identifier fields and their gates.
* plan.py     - the refresh plan: exact-identifier association, the Florida
  caveats (stacked polygons, multi-parcel features, condominium units without
  a polygon), duplicate prevention, and what a failed read may change
  (nothing).

Approvals and permission records: data/source_approvals.csv,
data/source_permissions.csv. Storage and the read contract: migration
034_parcel_boundaries.sql. Writer: scripts/parcel_boundary_refresh.py.
"""
