"""Parcel boundary storage: permission gate, geometry validation and write rules.

Nothing here reads a county or fetches geometry. The permission matrix
(data/parcel_boundary_permissions.csv) is the only way a source can be enabled,
and every source in it is DISABLED or ELIGIBLE_NOT_ENABLED today.
"""
