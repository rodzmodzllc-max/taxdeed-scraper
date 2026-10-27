"""The five county parcel layers added 2026-10-25 (owner's decision: collect
public records to fill gaps on held records; nothing sold until legal review).

Pins what makes them safe to run: county-scoped, exact identifier rules,
fields read live, no zero-value column, and a permission that is an internal
risk acceptance (never documented permission), excluded from any paid tier."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harvesters.enrichment import parcels as P, sources as S  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402

DAY = date(2026, 10, 26)
NEW = {
    "mo_stl_parcels_coordinates": ("MO", ("St. Louis City",), "ParcelId", "exact"),
    "mi_detroit_assessor_parcels": ("MI", ("Wayne",), "parcel_id", "exact"),
    "ok_oklahoma_county_parcels": ("OK", ("Oklahoma",), "pin", "exact"),
    "pa_fayette_pasda_parcels": ("PA", ("Fayette",), "TAXIDNUM", "exact"),
    "sc_horry_county_parcels": ("SC", ("Horry",), "PIN", "numeric"),
}


def cfg(sid):
    return next(c for c in S.all_sources() if c.source_id == sid)


def test_each_layer_is_county_scoped_with_an_exact_identifier_rule():
    for sid, (st, counties, id_field, rule) in NEW.items():
        c = cfg(sid)
        assert (c.state, c.counties, c.id_field, c.id_rule) == (st, counties, id_field, rule), sid
        assert c.columns_verified and c.layer_url.startswith("https://"), sid
        assert "2026-10-25" in c.notes and "matched" in c.notes, sid
        assert set(c.field_map) <= set(P.COLUMN_TYPES), sid


def test_exempt_zero_values_are_never_mapped():
    # Land-bank and county-owned parcels are tax-exempt (assessed 0): those
    # attributes are deliberately not in the maps.
    assert "amt_assessed_value" not in cfg("mi_detroit_assessor_parcels").field_map.values()
    assert "amt_taxable_value" not in cfg("mi_detroit_assessor_parcels").field_map.values()
    assert not {"currentmarket", "currentassessed", "currenttaxable"} & set(cfg("ok_oklahoma_county_parcels").field_map.values())
    assert P._coerce("assessed", 0) is None


def test_permission_is_a_risk_acceptance_outside_any_paid_tier():
    p = PERM.Permissions.from_file()
    assert p.error is None
    for sid, (st, *_rest) in NEW.items():
        for op in ("fetch", "enrich"):
            d = p.authorize(sid, op, state=st, today=DAY)
            assert d.allowed and d.basis == "INTERIM" and not d.documented, (sid, op)
            assert d.evidence_type == "INTERNAL_RISK_ACCEPTANCE" and "excluded_from_paid_tier" in d.conditions
            assert "not sold until legal review" in d.reason
        for op in ("display", "store", "redistribute"):
            assert not p.authorize(sid, op, state=st, today=DAY).allowed, (sid, op)
        assert P.enrichment_allowed(cfg(sid))[0], sid
