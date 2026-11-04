"""Thin-states enrichment sprint (2026-10-27; docs/enrich-thin-states-2026-10-27.md).

Pins: the new / extended layer configs (Horry SC assessor + address points,
Douglas CO locations + improvements, Oklahoma County situs, East Baton Rouge
situs and improvement value), the factory additions they rely on
(composite text columns, value patterns that mean "not published", two county
layers per county only on disjoint columns), the batched every-layer runner
(targets, checkpoint, write-only-changes, placeholder refill) and the sync
guard that stops a list's blank / placeholder from erasing an enriched value.
No request is made here: every layer response is a fixture."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "scripts"))

from harvesters.enrichment import parcels as P, sources as S  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402
import enrich_statewide_parcels as ESP  # noqa: E402
import enrichment_queue as EQ  # noqa: E402
import harvest_expansion as HX  # noqa: E402
import sync_state_inventory as SY  # noqa: E402

DAY = date(2026, 10, 27)
NOW = "2026-10-27T00:00:00+00:00"
FIX = REPO / "tests/python/fixtures/expansion"


def cfg(sid):
    return next(c for c in S.all_sources() if c.source_id == sid)


# ------------------------------------------------------------------ configs

NEW = {
    "sc_horry_assessor_parcels": ("SC", ("Horry",), "PIN", "numeric", "INTERIM"),
    "sc_horry_address_points": ("SC", ("Horry",), "PIN", "numeric", "INTERIM"),
    "co_douglas_property_locations": ("CO", ("Douglas",), "ACCOUNT_NO", "alnum", "DOCUMENTED"),
    "co_douglas_property_improvements": ("CO", ("Douglas",), "ACCOUNT_NO", "alnum", "DOCUMENTED"),
}


def test_new_layers_are_county_scoped_exact_identifier_layers_cleared_to_run():
    p = PERM.Permissions.from_file()
    assert p.error is None
    for sid, (st, counties, id_field, rule, basis) in NEW.items():
        c = cfg(sid)
        assert (c.state, c.counties, c.id_field, c.id_rule) == (st, counties, id_field, rule), sid
        assert c.columns_verified and c.publication_status == "APPROVED" and "2026-10-27" in c.notes, sid
        assert not ({"owner_name"} & c.written_columns()), sid               # an owner is never taken from these layers
        assert P.enrichment_allowed(c)[0], sid
        for op in ("fetch", "enrich"):
            d = p.authorize(sid, op, state=st, today=DAY)
            assert d.allowed and d.basis == basis, (sid, op, d.basis)
        for op in ("display", "redistribute"):
            assert not p.authorize(sid, op, state=st, today=DAY).allowed, (sid, op)
    # Horry has no licence: an internal risk acceptance, outside any paid tier - never documented permission.
    d = p.authorize("sc_horry_assessor_parcels", "enrich", state="SC", today=DAY)
    assert not d.documented and d.evidence_type == "INTERNAL_RISK_ACCEPTANCE" and "excluded_from_paid_tier" in d.conditions
    # Douglas County publishes CC BY-SA 4.0 on the items (the liens list's own licence).
    assert p.authorize("co_douglas_property_locations", "fetch", state="CO", today=DAY).evidence_type == "PUBLISHED_LICENSE"


def test_mailing_and_code_only_attributes_are_never_mapped():
    horry = cfg("sc_horry_assessor_parcels")
    assert not {"OwnerName", "OwnerStreet", "OwnerCity", "LandUseCode"} & set(horry.field_map.values())
    ok = cfg("ok_oklahoma_county_parcels")
    assert ok.field_map["address"] == "location"
    assert not {"mailingaddress1", "name1", "currentmarket", "currentassessed"} & set(ok.field_map.values())
    la = cfg("la_ebr_tax_parcels")
    assert la.field_map["address"] == "physical_address" and "owner_address" not in la.field_map.values()
    roll = cfg("la_ebr_tax_roll")
    assert roll.field_map["address"] == "parcel_address" and roll.column_year_floor["address"] == 2023
    assert not {"taxpayer_addr_1", "taxpayer_addr_2", "taxpayer_addr_3", "units"} & set(roll.field_map.values())
    douglas = cfg("co_douglas_property_improvements")
    assert douglas.field_map == {"year_built": "BUILT_YEAR"}                 # undefined square-footage columns not mapped


def test_two_county_layers_share_a_county_only_on_disjoint_columns():
    horry = [c for c in S.for_county("SC", "Horry")]
    assert [c.source_id for c in horry] == ["sc_horry_county_parcels", "sc_horry_assessor_parcels", "sc_horry_address_points"]
    cols = [c.written_columns() for c in horry]
    assert all(not (a & b) for i, a in enumerate(cols) for b in cols[i + 1:])
    clash = P.ParcelSourceConfig(source_id="sc_horry_duplicate_test", state="SC", agency="t", dataset="t",
                                 landing_url="https://e.gov", layer_url="https://e.gov/arcgis/rest/services/X/FeatureServer/0",
                                 id_field="PIN", id_rule="numeric", field_map={"address": "ADDR"}, licence="t",
                                 publication_status="APPROVED", columns_verified=True, counties=("Horry",))
    with pytest.raises(ValueError, match="overlaps sc_horry_address_points"):
        S.register(clash)
    assert all(c.source_id != "sc_horry_duplicate_test" for c in S.all_sources())


# ------------------------------------------------------------------ factory additions

def _feature(**attrs):
    return {"attributes": attrs}


def _match(c, feature, key="1"):
    return P.MatchResult("r1", "MATCHED", feature, key)


def test_composite_address_joins_the_published_parts_and_needs_a_house_number():
    c = cfg("co_douglas_property_locations")
    f = _feature(ACCOUNT_NO="R0000001", ADDRESS_NUMBER="123", PRE_DIRECTION_CODE="N", STREET_NAME="MAIN",
                 STREET_TYPE_CODE="ST", UNIT_NO="4", TOTAL_NET_ACRES=0.25, LEGAL_DESCR="LOT 1")
    fields, prov = P.plan_update(c, {"id": "r1"}, _match(c, f), recorded_at=NOW)
    assert fields == {"address": "123 N MAIN ST #4", "acreage": 0.25, "legal_desc": "LOT 1"}
    assert prov["address"]["source_id"] == "co_douglas_property_locations"
    f2 = _feature(ACCOUNT_NO="R0000002", ADDRESS_NUMBER=None, STREET_NAME="MAIN", STREET_TYPE_CODE="ST")
    assert "address" not in P.plan_update(c, {"id": "r1"}, _match(c, f2), recorded_at=NOW)[0]
    f3 = _feature(ACCOUNT_NO="R0000003", ADDRESS_NUMBER="0", STREET_NAME="MAIN")
    assert "address" not in P.plan_update(c, {"id": "r1"}, _match(c, f3), recorded_at=NOW)[0]
    with pytest.raises(ValueError, match="text column"):
        P.ParcelSourceConfig(source_id="x_test", state="CO", agency="t", dataset="t", landing_url="https://e.gov",
                             layer_url="https://e.gov/arcgis/rest/services/X/FeatureServer/0", id_field="A",
                             id_rule="alnum", field_map={}, licence="t", publication_status="APPROVED",
                             composite_map={"acreage": (("A1", ""),)})


def test_values_meaning_not_published_are_never_stored():
    ok = cfg("ok_oklahoma_county_parcels")
    unknown = _feature(pin="1234-56-789-0123", location="0 UNKNOWN  OKLAHOMA CITY", acres=1.5, legal="LOT 2")
    fields = P.plan_update(ok, {"id": "r1"}, _match(ok, unknown), recorded_at=NOW)[0]
    assert "address" not in fields and fields["acreage"] == 1.5
    real = _feature(pin="1234-56-789-0123", location="1200 N WALKER AVE", acres=None, legal=None)
    assert P.plan_update(ok, {"id": "r1"}, _match(ok, real), recorded_at=NOW)[0] == {"address": "1200 N WALKER AVE"}
    la = cfg("la_ebr_tax_parcels")
    for value, kept in (("GROOM RD", False), ("N/A", False), ("1234 MAIN ST", True)):
        f = _feature(assessment_num="123-4567-8", physical_address=value)
        assert ("address" in P.plan_update(la, {"id": "r1"}, _match(la, f), recorded_at=NOW)[0]) is kept, value


def test_tax_roll_situs_comes_from_tax_year_2023_when_later_years_leave_it_blank():
    roll = cfg("la_ebr_tax_roll")
    recs = [{"assessment_no": "123-4567-8", "tax_year": "2025", "parcel_address": None, "taxpayer_val": "1000"},
            {"assessment_no": "123-4567-8", "tax_year": "2024", "parcel_address": None},
            {"assessment_no": "123-4567-8", "tax_year": "2023", "parcel_address": "1234 MAIN ST", "structure_use": "RESIDENTIAL"},
            {"assessment_no": "999-0000-1", "tax_year": "2025", "parcel_address": None},
            {"assessment_no": "999-0000-1", "tax_year": "2023", "parcel_address": "N/A"}]
    idx = P.index_features(roll, [{"attributes": r} for r in recs])
    rows = [{"id": "a", "parcel": "123-4567-8", "county": "East Baton Rouge"}, {"id": "b", "parcel": "999-0000-1",
                                                                               "county": "East Baton Rouge"}]
    m = P.match_rows(roll, rows, idx)
    fa, pa = P.plan_update(roll, rows[0], m[0], recorded_at=NOW)
    assert fa["address"] == "1234 MAIN ST" and "tax_year=2023" in pa["address"]["record_of"]
    assert "address" not in P.plan_update(roll, rows[1], m[1], recorded_at=NOW)[0]       # "N/A" is no address


# ------------------------------------------------------------------ batched every-layer runner

def _arcgis(features):
    return lambda url: {"features": features}


def test_layers_run_county_scoped_first_and_targets_are_rows_missing_a_published_column():
    assert [c.source_id for c in ESP.layers_for_state("CO")] == [
        "co_douglas_property_locations", "co_douglas_property_improvements", "co_oit_public_parcels"]
    c = cfg("sc_horry_address_points")
    rows = [{"id": "1", "county": "Horry", "parcel": "12345678901", "address": "Parcel 12345678901"},
            {"id": "2", "county": "Horry", "parcel": "12345678902", "address": "100 OCEAN BLVD"},
            {"id": "3", "county": "Georgetown", "parcel": "12345678903", "address": None},
            {"id": "4", "county": "Horry", "parcel": None, "address": None}]
    assert [r["id"] for r in ESP.targets_for(c, rows)] == ["1"]              # placeholder = missing; other county / no id skipped


def test_batches_resume_after_the_previous_runs_last_row_and_wrap(tmp_path):
    c = cfg("sc_horry_address_points")
    targets = [{"id": f"{i:02d}"} for i in range(10)]
    ck = EQ.Checkpoint(tmp_path / "ck.json")
    first = ESP.take_batch(c, targets, 4, ck)
    assert [r["id"] for r in first] == ["00", "01", "02", "03"]
    ck.advance((c.source_id, ""), "03")
    assert [r["id"] for r in ESP.take_batch(c, targets, 4, EQ.Checkpoint(tmp_path / "ck.json"))] == ["04", "05", "06", "07"]
    ck.advance((c.source_id, ""), "07")
    assert [r["id"] for r in ESP.take_batch(c, targets, 4, ck)] == ["08", "09", "00", "01"]
    assert len(ESP.take_batch(c, targets, None, ck)) == 10                       # no limit: every target


def test_run_all_layers_dry_run_writes_nothing_and_counts_only(tmp_path):
    rows = [{"id": "1", "state": "SC", "county": "Horry", "parcel": "12345678901", "address": "Parcel 12345678901",
             "field_provenance": {}}]
    feats = [{"attributes": {"PIN": 12345678901, "ADDRESS": "100 OCEAN BLVD", "Acreage": 0.5, "LegalDescr": "LOT 9",
                             "AssessedProp": 900, "MarketProp": 15000, "MarketLand": 15000, "MarketImprv": 0,
                             "TaxableProp": 900}, "geometry": None}]
    writes = []
    reps = ESP.run_all_layers("SC", rows, _arcgis(feats), write=None, recorded_at=NOW, checkpoint=None,
                              source_ids={"sc_horry_assessor_parcels", "sc_horry_address_points"})
    by = {r["source_id"]: r for r in reps}
    assert by["sc_horry_assessor_parcels"]["fields_written"] == {"acreage": 1, "assessed": 1, "land_value": 1, "legal_desc": 1,
                                                                 "market": 1, "taxable_value": 1}
    assert by["sc_horry_address_points"]["fields_written"] == {"address": 1}
    assert writes == [] and json.dumps(reps).count("OCEAN") == 0              # reports carry counts, never a value


def test_a_placeholder_is_refilled_even_under_an_enrichment_provenance_and_an_unchanged_patch_is_never_sent():
    c = cfg("co_douglas_property_locations")
    prov = {"address": {"source": "statewide_parcel", "source_id": "co_oit_public_parcels", "recorded_at": "2026-10-20"}}
    row = {"id": "1", "state": "CO", "county": "Douglas", "parcel": "R0000001", "address": "Parcel R0000001",
           "acreage": None, "legal_desc": None, "field_provenance": prov}
    feats = [{"attributes": {"ACCOUNT_NO": "R0000001", "ADDRESS_NUMBER": "9", "STREET_NAME": "ELM", "STREET_TYPE_CODE": "CT"}}]
    writes = []
    ESP.run("CO", [row], _arcgis(feats), write=lambda i, f: writes.append(f), recorded_at=NOW, cfg=c)
    assert writes and writes[0]["address"] == "9 ELM CT"
    # The same layer again: the row now holds the value with the layer's provenance -> nothing to send.
    writes2 = []
    rep = ESP.run("CO", [row], _arcgis(feats), write=lambda i, f: writes2.append(f), recorded_at="2026-10-28T00:00:00+00:00", cfg=c)
    assert writes2 == [] and rep["rows_written"] == 0
    # A real address with a provenance of equal rank is never replaced.
    other = {"id": "2", "state": "CO", "county": "Douglas", "parcel": "R0000001", "address": "1 OTHER RD",
             "acreage": 1.0, "legal_desc": "L", "field_provenance": {"address": {"source": "county_list"}}}
    writes3 = []
    ESP.run("CO", [other], _arcgis(feats), write=lambda i, f: writes3.append(f), recorded_at=NOW, cfg=c)
    assert writes3 == []


def test_main_refuses_a_non_positive_limit_and_skips_states_without_a_cleared_layer(capsys):
    assert ESP.main(["--state", "SC", "--all-layers", "--limit", "0"]) == 2
    assert ESP.main(["--state", "FL", "--all-layers"]) == 0
    assert "skip: FL has no cleared parcel layer" in capsys.readouterr().out


# ------------------------------------------------------------------ sync guard

def test_a_lists_placeholder_never_erases_an_enriched_address():
    stored = {"address": "9 ELM CT", "acreage": 1.0,
              "field_provenance": {"address": {"source": "statewide_parcel", "source_id": "co_oit_public_parcels"},
                                   "acreage": {"source": "county_list"}}}
    row = {"address": "Parcel R0000001", "acreage": None, "legal_desc": None}
    assert SY.keep_enriched_values(row, stored) == 1
    assert row == {"address": "9 ELM CT", "acreage": None, "legal_desc": None}   # the list's own column follows the list
    own = {"address": "77 LIST ST"}
    assert SY.keep_enriched_values(own, stored) == 0 and own["address"] == "77 LIST ST"   # the list's value always wins
    assert SY.keep_enriched_values({"address": None}, {"address": "Parcel X", "field_provenance": stored["field_provenance"]}) == 0
    assert SY.keep_enriched_values({"address": None}, None) == 0


def test_sync_plan_sends_the_stored_enriched_value_back(tmp_path):
    args = ["--state", "CO", "--out-dir", str(tmp_path), "--fixture",
            f"co_morgan_county_held_certificates={FIX / 'co_morgan.html'}"]
    assert HX.main(args) == 0
    rows = json.loads((tmp_path / "co_properties_rows.json").read_text())
    target = next(r for r in rows if str(r.get("address") or "").startswith("Parcel ") or not r.get("address"))
    ident = SY.identity(dict(target, source="certificate"))
    prov = {"address": {"source": "statewide_parcel", "source_id": "co_oit_public_parcels"}}
    stored = {ident: {"address": "9 ELM CT", "field_provenance": prov}}
    sent, counts = SY.plan("CO", rows, SY.registry_rows("CO"), {"Morgan": "COMPLETE"}, stored_provenance={ident: prov},
                           stored_values=stored)
    row = next(r for r in sent if SY.identity(r) == ident)
    assert row["address"] == "9 ELM CT" and row["field_provenance"]["address"]["source"] == "statewide_parcel"
    assert counts["enriched_values_kept"] >= 1


# ------------------------------------------------------------------ workflow

def test_workflow_runs_every_layer_batched_and_evidence_never_holds_the_database_key():
    import yaml
    wf = yaml.safe_load((REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    inputs = wf[True]["workflow_dispatch"]["inputs"]
    assert {"enrich_kinds", "enrich_limit"} <= set(inputs) and len(inputs) <= 25
    exp = json.dumps(wf["jobs"]["expansion"])
    assert "enrich_statewide_parcels.py --state ${{ matrix.state }} --all-layers --limit 500" in exp
    enr = json.dumps(wf["jobs"]["enrich"])
    assert "--all-layers $LIMIT_ARG" in enr and "contains(github.event.inputs.enrich_kinds, 'parcels')" in enr
    assert "parcel-enrichment-checkpoint-" in enr
    assert "SUPABASE_SERVICE_KEY" not in json.dumps(wf["jobs"]["evidence"])
