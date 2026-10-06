"""Enrichment priority + authoritative geocoding pipeline (2026-10-06).

Covers: the explicit priority rules, coordinate source selection, the plan
classes, deterministic matching (exactly one feature; no address / fuzzy /
nearby match), state-bounds refusal, stronger-coordinate preservation, the
upgrade opt-in, provenance contents, the plan / dry-run / apply gates,
failure isolation and the counts-only audit / log.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from harvesters.enrichment import geocode as G  # noqa: E402
from harvesters.enrichment import priority as PR  # noqa: E402
from harvesters.sources import coordinates as C  # noqa: E402
from scripts import enrichment_audit as EA  # noqa: E402
from scripts import geocode_authoritative as GA  # noqa: E402

TS = "2026-10-06T00:00:00+00:00"


def row(**kw):
    base = {"id": "r1", "state": "FL", "county": "Alachua", "ledger_type": "auctions", "source": "auction",
            "status": "active", "publication_status": None, "parcel": "01234-005-000", "latitude": None,
            "longitude": None, "field_provenance": {}}
    base.update(kw)
    return base


# --- priority ------------------------------------------------------------------
def test_priority_rules_are_explicit_and_ordered():
    assert PR.RULE_IDS == ("P1", "P2", "P3", "P4", "P5", "P6", "P7")
    ctx = PR.Context(verified_counties=[("MI", "Detroit")], market_counties=[("PA", "Fayette")])
    assert PR.rule_of(row(ledger_type="buy", publication_status="APPROVED"), ctx) == "P1"
    assert PR.rule_of(row(ledger_type="auctions"), ctx) == "P2"
    assert PR.rule_of(row(ledger_type="lien"), ctx) == "P3"
    hidden = dict(ledger_type="buy", publication_status="UNREVIEWED")
    assert PR.rule_of(row(state="MI", county="Detroit", **hidden), ctx) == "P4"
    assert PR.rule_of(row(state="PA", county="Fayette", **hidden), ctx) == "P5"
    assert PR.rule_of(row(state="MO", county="St. Louis City", **hidden), ctx) == "P6"   # parcel, no coordinates
    assert PR.rule_of(row(state="MO", county="St. Louis City", parcel="", **hidden), ctx) == "P7"
    assert PR.rule_of(row(status="closed"), ctx) is None


def test_priority_order_is_deterministic_and_drops_inactive():
    rows = [row(id="c", ledger_type="lien"), row(id="a", ledger_type="auctions"),
            row(id="b", ledger_type="buy", publication_status="APPROVED"), row(id="z", status="closed")]
    assert [r["id"] for r in PR.ordered(rows)] == ["b", "a", "c"]
    assert PR.ordered(list(reversed(rows))) == PR.ordered(rows)
    assert PR.summary(rows) == {"P1": 1, "P2": 1, "P3": 1, "P4": 0, "P5": 0, "P6": 0, "P7": 0}


def test_restricted_or_unreviewed_rows_never_outrank_visible_ones():
    assert not PR.customer_visible(row(publication_status="UNREVIEWED"))
    assert not PR.customer_visible(row(publication_status="BLOCKED"))
    assert PR.customer_visible(row(publication_status="APPROVED_GRANDFATHERED"))
    assert PR.customer_visible(row(publication_status=None))


def test_verified_counties_come_from_acquisition_evidence():
    v = PR.load_verified_counties()
    assert ("FL", "Calhoun") in v
    data = json.loads((REPO / "public" / "acquisition-evidence.json").read_text(encoding="utf-8"))
    assert all(s["status"] == "VERIFIED" for s in data["status"] if (s["state"], s["county"]) in v and s["state"] == "FL" and s["county"] == "Calhoun")


# --- sources & planning -----------------------------------------------------------
def test_only_authoritative_parcel_sources_are_configured():
    srcs = G.coordinate_sources()
    assert srcs and all(s.method in C.AUTHORITATIVE for s in srcs)
    assert all(s.geometry == "PARCEL_CENTROID" for s in srcs)
    assert {s.provenance_source for s in srcs} <= {"fdor_nal", "county_gis", "statewide_parcel"}
    ids = {s.source_id for s in srcs}
    assert {"fl_fdor_cadastral", "fl_santa_rosa_parcels", "co_oit_public_parcels"} <= ids
    # Flagler's county layer returns no centroid - never a coordinate source.
    assert not any("flagler" in s.source_id for s in srcs)


def test_plan_classes():
    assert G.plan_row(row())[0] == "MISSING"
    assert G.plan_row(row())[1].source_id == "fl_fdor_cadastral"
    assert G.plan_row(row(county="Santa Rosa"))[1].source_id == "fl_santa_rosa_parcels"
    fdor = row(latitude=29.6, longitude=-82.3, field_provenance={"latitude": {"source": "fdor_nal"}})
    assert G.plan_row(fdor)[0] == "ALREADY_AUTHORITATIVE"
    unrec = row(latitude=29.6, longitude=-82.3)
    assert G.plan_row(unrec)[0] == "UPGRADE_NOT_REQUESTED"
    assert G.plan_row(unrec, allow_upgrade=True)[0] == "UPGRADE"
    assert G.plan_row(row(parcel=""))[0] == "NO_IDENTIFIER"
    assert G.plan_row(row(state="WY", county="Albany"))[0] == "NO_SOURCE"
    assert G.plan_row(row(state="MO", county="St. Louis City"))[0] == "SOURCE_NOT_APPROVED"
    assert G.plan_row(row(state="TX", county="Jim Wells", case_no="12345"))[0] == "SOURCE_NOT_APPROVED"


def test_an_address_alone_never_produces_a_lookup():
    # No identifier, a full street address: the pipeline never geocodes an address.
    assert G.plan_row(row(parcel="", address="123 Main St, Gainesville, FL"))[0] == "NO_IDENTIFIER"
    src = (REPO / "harvesters" / "enrichment" / "geocode.py").read_text(encoding="utf-8")
    assert "census" not in src.lower() and "address_agrees" not in src


def test_vendor_listing_coordinates_are_upgradable_only_on_request():
    vendor = row(latitude=29.6, longitude=-82.3, field_provenance={"latitude": {"source": "vendor_listing"}})
    assert G.plan_row(vendor)[0] == "UPGRADE_NOT_REQUESTED"
    assert G.plan_row(vendor, allow_upgrade=True)[0] == "UPGRADE"


# --- deterministic matching -------------------------------------------------------
def pt(f):
    return f.get("pt")


def test_exactly_one_feature_or_nothing():
    assert G.from_feature_count([], "FL", point_of=pt).status == "NO_MATCH"
    assert G.from_feature_count([{"pt": (29.6, -82.3)}, {"pt": (29.7, -82.3)}], "FL", point_of=pt).status == "AMBIGUOUS"
    one = G.from_feature_count([{"pt": (29.6, -82.3)}], "FL", point_of=pt, matched_identifier="X1")
    assert (one.status, one.lat, one.lng, one.matched_identifier) == ("MATCHED", 29.6, -82.3, "X1")


def test_a_point_outside_the_state_is_a_parser_failure_never_a_pin():
    assert G.from_feature_count([{"pt": (40.7, -74.0)}], "FL", point_of=pt).status == "PARSER_FAILURE"
    assert G.from_feature_count([{"pt": (-82.3, 29.6)}], "FL", point_of=pt).status == "PARSER_FAILURE"   # swapped x / y
    assert G.from_feature_count([{"pt": None}], "FL", point_of=pt).status == "PARSER_FAILURE"
    assert G.classify_point("nan", 1, "FL").status == "PARSER_FAILURE"
    assert G.classify_point(29.6, -82.3, "ZZ").status == "PARSER_FAILURE"


SQUARE = {"rings": [[[-105.0, 40.0], [-104.99, 40.0], [-104.99, 40.01], [-105.0, 40.01], [-105.0, 40.0]]]}


def co_src():
    return next(s for s in G.coordinate_sources() if s.source_id == "co_oit_public_parcels")


def co_row(i, acct):
    return row(id=i, state="CO", county="Morgan", ledger_type="lien", parcel=acct)


def test_parcel_layer_lookup_matches_on_identifier_only():
    def fetch(url):
        return {"features": [
            {"attributes": {"account": "R001", "countyName": "MORGAN"}, "geometry": SQUARE},
            {"attributes": {"account": "R002", "countyName": "MORGAN"}, "geometry": SQUARE},
            {"attributes": {"account": "R002", "countyName": "MORGAN"}, "geometry": SQUARE},
        ]}
    out = G.lookup_parcel_layer(co_src(), [co_row("a", "R001"), co_row("b", "R002"), co_row("c", "R003")], fetch)
    assert out["a"].status == "MATCHED" and abs(out["a"].lat - 40.005) < 1e-6 and abs(out["a"].lng + 104.995) < 1e-6
    assert out["b"].status == "AMBIGUOUS"
    assert out["c"].status == "NO_MATCH"


def test_parcel_layer_failures_are_isolated_per_county():
    def fetch(url):
        raise OSError("down")
    out = G.lookup_parcel_layer(co_src(), [co_row("a", "R001")], fetch)
    assert out["a"].status == "SOURCE_UNAVAILABLE"
    out = G.lookup_parcel_layer(co_src(), [co_row("a", "R001")], lambda u: {"error": {"code": 500}})
    assert out["a"].status == "SOURCE_UNAVAILABLE"

    def bad(url):
        raise ValueError("not json")
    assert G.lookup_parcel_layer(co_src(), [co_row("a", "R001")], bad)["a"].status == "PARSER_FAILURE"


# --- the write decision -------------------------------------------------------------
def fdor():
    return G.FDOR_SOURCE


def test_write_fills_missing_with_full_provenance():
    action, fields = G.decide(row(), fdor(), G.Lookup("MATCHED", 29.65, -82.32, "0123400500", "PARCEL_ID"),
                              allow_upgrade=False, recorded_at=TS)
    assert action == "write"
    assert fields["latitude"] == 29.65 and fields["longitude"] == -82.32
    e = fields["field_provenance"]["latitude"]
    assert e == fields["field_provenance"]["longitude"]
    for k, v in {"source": "fdor_nal", "method": "TAX_ROLL", "geometry": "PARCEL_CENTROID", "match": "parcel_id",
                 "matched_identifier": "0123400500", "matched_field": "PARCEL_ID", "recorded_at": TS,
                 "source_id": "fl_fdor_cadastral", "pipeline": "geocode_authoritative"}.items():
        assert e[k] == v
    assert e["layer_url"].startswith("https://") and e["landing_url"].startswith("https://")
    # The written coordinate reads back as authoritative tax-roll centroid.
    after = dict(row(), **fields)
    cp = C.coordinate_provenance(after)
    assert (cp["method"], cp["geometry"], cp["authoritative"]) == ("TAX_ROLL", "PARCEL_CENTROID", True)


def test_stronger_or_equal_existing_coordinates_are_preserved():
    parcel_gis = row(latitude=29.6, longitude=-82.3, field_provenance={"latitude": {"source": "statewide_parcel"}})
    lk = G.Lookup("MATCHED", 29.65, -82.32, "X", "PARCEL_ID")
    assert G.decide(parcel_gis, fdor(), lk, allow_upgrade=True, recorded_at=TS) == ("skip", "STRONGER_OR_EQUAL_EXISTING")
    tax_roll = row(latitude=29.6, longitude=-82.3, field_provenance={"latitude": {"source": "fdor_nal"}})
    assert G.decide(tax_roll, fdor(), lk, allow_upgrade=True, recorded_at=TS) == ("skip", "STRONGER_OR_EQUAL_EXISTING")
    unrec = row(latitude=29.6, longitude=-82.3)
    assert G.decide(unrec, fdor(), lk, allow_upgrade=False, recorded_at=TS) == ("skip", "UPGRADE_NOT_REQUESTED")
    assert G.decide(unrec, fdor(), lk, allow_upgrade=True, recorded_at=TS)[0] == "write"


def test_non_matches_never_write():
    for st in ("NO_MATCH", "AMBIGUOUS", "SOURCE_UNAVAILABLE", "PARSER_FAILURE", "NO_IDENTIFIER"):
        assert G.decide(row(), fdor(), G.Lookup(st), allow_upgrade=True, recorded_at=TS) == ("skip", st)


def test_other_provenance_columns_are_kept():
    r = row(field_provenance={"market": {"source": "fdor_nal"}})
    _, fields = G.decide(r, fdor(), G.Lookup("MATCHED", 29.65, -82.32, "X", "PARCEL_ID"), allow_upgrade=False, recorded_at=TS)
    assert fields["field_provenance"]["market"] == {"source": "fdor_nal"}


# --- the pipeline -----------------------------------------------------------------
def rows_fixture():
    return [
        row(id="avail", ledger_type="buy", publication_status="APPROVED", county="Bay", parcel="11111-000-000"),
        row(id="auc", county="Bay", parcel="22222-000-000"),
        row(id="lien", ledger_type="lien", county="Bay", parcel="33333-000-000"),
        row(id="done", latitude=29.6, longitude=-82.3, field_provenance={"latitude": {"source": "fdor_nal"}}),
        row(id="unrec", latitude=29.6, longitude=-82.3, parcel="44444-000-000"),
        row(id="closed", status="closed"),
        row(id="wy", state="WY", county="Albany"),
    ]


def fl_fake(results):
    calls = []

    def fn(src, r):
        calls.append(r["id"])
        return results.get(r["id"], G.Lookup("NO_MATCH"))
    return fn, calls


def test_plan_mode_makes_no_request_and_orders_by_priority():
    fn, calls = fl_fake({})
    rep = GA.run(rows_fixture(), mode="plan", allow_upgrade=False, limit=None, ctx=PR.Context(), fl_lookup_fn=fn)
    assert calls == []
    assert rep["candidates"] == 3 and rep["plan"]["MISSING"] == 3
    assert rep["plan"]["ALREADY_AUTHORITATIVE"] == 1 and rep["plan"]["UPGRADE_NOT_REQUESTED"] == 1
    assert rep["plan"]["NO_SOURCE"] == 1 and "closed" not in json.dumps(rep)
    assert rep["by_rule"] == {"P1": 1, "P2": 1, "P3": 1}
    assert rep["looked_up"] == 0 and rep["written"] == 0


def test_dry_run_looks_up_in_priority_order_and_writes_nothing():
    fn, calls = fl_fake({"avail": G.Lookup("MATCHED", 30.2, -85.6, "X", "PARCEL_ID"),
                         "auc": G.Lookup("AMBIGUOUS"), "lien": G.Lookup("SOURCE_UNAVAILABLE")})
    writes = []
    rep = GA.run(rows_fixture(), mode="dry-run", allow_upgrade=False, limit=None, ctx=PR.Context(), fl_lookup_fn=fn,
                 write=lambda *a: writes.append(a))
    assert calls == ["avail", "auc", "lien"]
    assert writes == []
    assert (rep["matched"], rep["ambiguous"], rep["source_unavailable"], rep["would_write"], rep["written"]) == (1, 1, 1, 1, 0)


def test_limit_takes_the_highest_priority_first():
    fn, calls = fl_fake({})
    GA.run(rows_fixture(), mode="dry-run", allow_upgrade=False, limit=1, ctx=PR.Context(), fl_lookup_fn=fn)
    assert calls == ["avail"]


def test_apply_writes_and_isolates_a_failed_write():
    fn, _ = fl_fake({"avail": G.Lookup("MATCHED", 30.2, -85.6, "X", "PARCEL_ID"),
                     "auc": G.Lookup("MATCHED", 30.21, -85.61, "Y", "PARCEL_ID")})
    written = []

    def write(rid, fields):
        if rid == "avail":
            raise OSError("boom")
        written.append((rid, fields))
    rep = GA.run(rows_fixture(), mode="apply", allow_upgrade=False, limit=None, ctx=PR.Context(), fl_lookup_fn=fn, write=write)
    assert rep["write_errors"] == 1 and rep["written"] == 1 and written[0][0] == "auc"
    assert set(written[0][1]) == {"latitude", "longitude", "field_provenance"}


def test_upgrade_is_counted_separately_and_only_on_request():
    fn, calls = fl_fake({"unrec": G.Lookup("MATCHED", 29.65, -82.32, "Z", "PARCEL_ID")})
    rep = GA.run(rows_fixture(), mode="dry-run", allow_upgrade=True, limit=None, ctx=PR.Context(), fl_lookup_fn=fn)
    assert "unrec" in calls and rep["plan"]["UPGRADE"] == 1 and rep["would_write"] == 1


def test_apply_without_confirmation_is_refused(capsys, tmp_path):
    p = tmp_path / "rows.json"
    p.write_text(json.dumps(rows_fixture()), encoding="utf-8")
    assert GA.main(["--mode", "apply", "--rows", str(p), "--out", str(tmp_path)]) == 2
    assert "refused" in capsys.readouterr().out
    assert not (tmp_path / "geocode-apply.json").exists()


def test_report_and_log_are_counts_only(capsys, tmp_path):
    rows = [dict(r, id=f"secret-id-{i}") for i, r in enumerate(rows_fixture())]
    p = tmp_path / "rows.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    assert GA.main(["--mode", "plan", "--rows", str(p), "--out", str(tmp_path)]) == 0
    text = capsys.readouterr().out + (tmp_path / "geocode-plan.json").read_text(encoding="utf-8")
    assert "secret-id-" not in text
    for r in rows:
        assert not r["parcel"] or r["parcel"] not in text


# --- the audit ---------------------------------------------------------------------
def test_audit_counts_by_state_county_ledger():
    rows = rows_fixture() + [row(id="v", ledger_type="buy", publication_status="UNREVIEWED", county="Bay",
                                 latitude=30.1, longitude=-85.6, field_provenance={"latitude": {"source": "statewide_parcel"}},
                                 legal_desc="LOT 1", photo_url="")]
    rep = EA.audit(rows)
    bay_av = next(u for u in rep["units"] if u["county"] == "Bay" and u["ledger"] == "AVAILABLE")
    assert bay_av["all"]["records"] == 2 and bay_av["visible"]["records"] == 1
    assert bay_av["all"]["authoritative_coordinates"] == 1 and bay_av["all"]["imagery_capable"] == 0   # '' = checked, no image
    assert bay_av["rules"]["P1"] == 1
    assert rep["totals"]["records"] == 7   # 8 rows, the closed one is not counted
    assert "11111" not in json.dumps(rep)


# --- the workflow ---------------------------------------------------------------------
WF = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")


def test_geocode_job_is_manual_only_and_defaults_to_plan():
    assert "geocode" in re.search(r"options: \[all[^\]]*\]", WF).group(0)
    job = WF[WF.index("\n  geocode:"):]
    assert "github.event_name == 'workflow_dispatch' && github.event.inputs.job == 'geocode'" in job
    m = re.search(r"geocode_mode:.*?default: (\w[\w-]*)", WF, re.S)
    assert m and m.group(1) == "plan"
    # --confirm-apply is passed ONLY when the chosen mode is apply.
    assert 'if [ "${GEOCODE_MODE}" = "apply" ]; then ARGS="$ARGS --confirm-apply"; fi' in job
    code = "\n".join(l for l in job.splitlines() if not l.strip().startswith("#"))
    assert code.count("--confirm-apply") == 1


def test_geocode_job_is_not_part_of_all_or_any_schedule():
    job = WF[WF.index("\n  geocode:"):]
    cond = re.search(r"\n    if: (.+)", job).group(1)
    assert cond == "github.event_name == 'workflow_dispatch' && github.event.inputs.job == 'geocode'"
