"""Test helpers for the source-permission gate (harvesters/governance/permissions.py).

Two narrow tools, never a blanket allow:

* `allow_fixture_layers(monkeypatch, P, ids)` - tests of the parcel-layer
  MATCHING mechanics use invented layer ids (t_layer, xx_parcels, ...) that have
  no permission record. This stands the permission check in for those ids only;
  every other id, including every real source, still goes through the real check.

* `install(monkeypatch, *extra_rows)` - the repository's real permission set
  plus fixture records, evaluated by the real engine (validation included), as
  the process default. Used where a test needs a permission to exist.
"""
from __future__ import annotations

import csv
import io

from harvesters.governance import permissions as PERM


def allow_fixture_layers(monkeypatch, parcels_module, ids) -> None:
    ids = frozenset(ids)
    real = parcels_module.PERMISSION_CHECK
    assert not ids & PERM.Permissions.from_file().source_ids(), "only invented fixture ids may be stubbed"
    monkeypatch.setattr(parcels_module, "PERMISSION_CHECK", lambda cfg: (True, "") if cfg.source_id in ids else real(cfg))


def record(**kw) -> dict:
    base = {c: "" for c in PERM.COLUMNS}
    base.update(dataset="*", status="OWNER_PERMISSION_REQUIRED", evidence_type="INTERNAL_RISK_ACCEPTANCE",
                evidence_ref="test fixture", evidence_date="2026-01-01", reviewer="test", effective_on="2026-01-01",
                expires_on="2099-01-01", last_verified_on="2026-01-01", reason="test fixture")
    base.update(kw)
    return base


def permissions_with(*extra_rows: dict, base: bool = True) -> PERM.Permissions:
    rows = []
    if base:
        with PERM.PERMISSIONS_CSV.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    rows += list(extra_rows)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=PERM.COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    records = PERM.parse(csv.DictReader(io.StringIO(buf.getvalue())))
    problems = PERM.validate(records)
    return PERM.Permissions(records, error="; ".join(problems) if problems else None)


def install(monkeypatch, *extra_rows: dict, base: bool = True) -> PERM.Permissions:
    perms = permissions_with(*extra_rows, base=base)
    monkeypatch.setattr(PERM, "_DEFAULT", perms)
    return perms
