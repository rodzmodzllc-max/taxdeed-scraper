"""Data-quality sprint, Fix 2 (2026-10-10): Tennessee Shelby enrichment that
never publishes anything.

A acquisition evidence typed by what was verified - never by a URL's existence
B list_as_of only from a date the portal itself publishes
C parcel enrichment only through an approved deterministic source (none yet)
D the one row without a portal point: authoritative match only, no address geocode
E flood through the existing FEMA path, with budget no longer starved by
  Tennessee having one county
F the publication gate: enrichment or a COMPLETE harvest never approves a source
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import source_publication as SP  # noqa: E402
import sync_state_inventory as SY  # noqa: E402
from harvesters.enrichment import geocode as G  # noqa: E402
from harvesters.enrichment import parcels as P  # noqa: E402
from harvesters.enrichment.sources import for_county, for_state  # noqa: E402
from harvesters.otc.adapters import epropertyplus as EPP, expansion as EX  # noqa: E402
from harvesters.sources import acquisition_evidence_status as AES  # noqa: E402

AT = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
FX = ROOT / "tests/python/fixtures/tennessee/tn_shelby_landbank.json"
SID = "tn_shelby_landbank"
SCRIPTS = ROOT / "scripts"


def _pages():
    return json.loads(FX.read_text(encoding="utf-8"))


def _fetch(pages):
    def fj(url):
        n = int(url.split("page=")[1].split("&")[0])
        return pages[min(n, len(pages)) - 1]
    return fj


def _records(cfg=EX.TN_SHELBY_LANDBANK, pages=None):
    return EPP.fetch_all(cfg, _fetch(pages or _pages()), retrieved_at=AT).records


# ------------------------------------------------------------- A acquisition

def _units():
    return {(u["state"], u["source_id"], u["county"]): u
            for u in json.loads((ROOT / "public/acquisition-evidence.json").read_text())["status"]}


def test_shelby_acquisition_is_needs_review_from_a_capture_never_verified():
    u = _units()[("TN", SID, "Shelby")]
    assert u["status"] == "NEEDS_REVIEW" and u["basis"] == "capture"
    assert u["run_id"] == "37856189946 37856396525" and "not read" in u["reason"]
    assert u["authority_type"] == "county_land_bank" and u["authority"] == "Shelby County Land Bank"
    assert u["candidates"] == [{"url": "https://landbank.shelbycountytn.gov", "doc_kind": "SOURCE_PAGE"}]
    assert not u.get("document_url")            # the packet's address was never recorded - never guessed
    assert all(not AES.outcome_problems(o) for o in AES.load_outcomes())


def test_shelby_rows_carry_no_purchase_link():
    for r in _records():
        row = r.to_properties_row()
        assert row.get("purchase_url") is None and row.get("purchase_path_type") in (None, "")
        assert row["list_url"] == EX.TN_SHELBY_LANDBANK.list_url


def _unit(status="NEEDS_REVIEW", path_type=""):
    return AES.UnitStatus(state="TN", source_id=SID, county="Shelby", status=status, basis="capture", path_type=path_type)


LIST = "https://public-sctn.epropertyplus.com/landmgmtpub/app/base/landing"


@pytest.mark.parametrize("row, unit, want", [
    # valid, verified
    ({"purchase_path_type": "direct_property_url", "purchase_path_scope": "property",
      "purchase_url": "https://county.example.gov/buy/123"}, None, "property_specific"),
    ({"purchase_path_type": "direct_property_url", "purchase_path_scope": "source",
      "purchase_url": "https://county.example.gov/offer"}, None, "listing_level"),
    ({"purchase_path_type": "application_download", "purchase_path_scope": "source",
      "purchase_url": "https://county.example.gov/form.pdf"}, None, "application_process"),
    ({"purchase_path_type": "in_person", "purchase_path_scope": "source"}, None, "application_process"),
    ({"list_url": LIST}, _unit("VERIFIED", "application_page"), "application_process"),
    # missing: the official list only, or nothing
    ({"list_url": LIST}, _unit(), "source_list_only"),
    ({"list_url": LIST}, None, "source_list_only"),
    ({}, None, "no_verified_online_path"),
    # malformed: a URL type without an https URL is nothing verified
    ({"purchase_path_type": "direct_property_url", "purchase_path_scope": "property",
      "purchase_url": "http://county.example.gov/buy/123"}, None, "no_verified_online_path"),
    ({"purchase_path_type": "direct_property_url", "purchase_path_scope": "property",
      "purchase_url": "https://"}, None, "no_verified_online_path"),
    ({"purchase_path_type": "application_page", "purchase_url": "not a url", "list_url": "ftp://x"}, None,
     "no_verified_online_path"),
    # unverified: a URL the engine never typed is not a path, whatever it says
    ({"purchase_url": "https://county.example.gov/buy/123", "list_url": LIST}, None, "source_list_only"),
    ({"purchase_path_type": "none_published", "list_url": LIST}, None, "source_list_only"),
])
def test_evidence_type(row, unit, want):
    assert AES.evidence_type(row, unit) == want
    assert want in AES.EVIDENCE_TYPES


def test_unverified_types_say_no_online_purchase_link():
    for t in ("source_list_only", "no_verified_online_path"):
        assert "No online purchase link on file" in AES.EVIDENCE_TYPE_LABELS[t] or \
               "no online purchase link on file" in AES.EVIDENCE_TYPE_LABELS[t]


def test_every_shelby_row_is_source_list_only():
    unit = AES.UnitStatus(**{k: v for k, v in _units()[("TN", SID, "Shelby")].items()
                             if k in AES.UnitStatus.__dataclass_fields__})
    assert {AES.evidence_type(r.to_properties_row(), unit) for r in _records()} == {"source_list_only"}


# ------------------------------------------------------------- B list_as_of

def test_shelby_publishes_no_list_date_so_none_is_stored():
    assert EX.TN_SHELBY_LANDBANK.list_as_of_field is None
    for r in _records():
        assert r.list_as_of is None and r.to_properties_row()["list_as_of"] is None
        assert r.provenance["list_as_of"] == "not stated by the portal - never the read time"
        assert r.retrieved_at.date().isoformat() not in json.dumps(r.to_properties_row().get("list_as_of"))


@pytest.mark.parametrize("raw, want", [
    ("2026-10-07", date(2026, 10, 7)),                     # present
    ("10/07/2026", date(2026, 10, 7)),
    ("2026-10-07T23:30:00-05:00", date(2026, 10, 7)),      # timezone: the date as the source wrote it
    ("2026-10-08T01:30:00Z", date(2026, 10, 8)),
    ("2026-10-07T23:30:00", None),                         # naive datetime: ambiguous
    (1759881600000, None),                                 # epoch: ambiguous
    ("", None), (None, None), ("TBD", None),               # absent
    ("2026-13-40", None), ("07/32/2026", None), ("yesterday", None),   # malformed
])
def test_list_date(raw, want):
    assert EPP.list_date(raw) == want


def test_a_configured_portal_date_field_is_used_and_never_the_read_time():
    import dataclasses
    cfg = dataclasses.replace(EX.TN_SHELBY_LANDBANK, list_as_of_field="listDate")
    pages = _pages()
    pages[0]["rows"][0]["listDate"] = "2026-09-30"
    pages[0]["rows"][1]["listDate"] = "garbage"
    a, b = _records(cfg, pages)
    assert a.list_as_of == date(2026, 9, 30) and "listDate" in a.provenance["list_as_of"] and not a.validate()
    assert b.list_as_of is None and b.provenance["list_as_of"].startswith("not stated")


# ------------------------------------------------------------- C parcel enrichment

def test_no_tennessee_parcel_source_is_configured_or_cleared():
    assert for_state("TN") is None and for_county("TN", "Shelby") == []
    import enrich_statewide_parcels as ESP
    assert ESP.run("TN", [{"id": "x", "county": "Shelby", "parcel": "07001200000010"}], lambda u: pytest.fail("request"),
                   recorded_at="2026-10-10T00:00:00+00:00")["skipped"] == "no statewide parcel source configured"


def test_an_unapproved_tennessee_layer_would_be_refused_before_any_request(capsys):
    import enrich_statewide_parcels as ESP
    cfg = P.ParcelSourceConfig(source_id="tn_hypothetical_parcels", state="TN", agency="test", dataset="test",
                               landing_url="https://example.gov", layer_url="https://example.gov/arcgis/rest/services/P/FeatureServer/0",
                               id_field="PARID", id_rule=next(iter(P.ID_RULES)), field_map={"land_use": "LUC"},
                               licence="not reviewed", publication_status="UNREVIEWED", columns_verified=True)
    assert P.enrichment_allowed(cfg) == (False, "publication status UNREVIEWED - reuse not cleared")
    rep = ESP.run("TN", [{"id": "x", "county": "Shelby", "parcel": "07001200000010"}],
                  lambda u: pytest.fail("no request before clearance"), recorded_at="2026-10-10T00:00:00+00:00", cfg=cfg)
    assert rep["skipped"].startswith("publication status UNREVIEWED")
    assert ESP.main(["--state", "TN"]) == 0
    assert "skip: TN statewide parcel source not cleared (none configured)" in capsys.readouterr().out


# ------------------------------------------------------------- D missing coordinate

def _row(**kw):
    base = {"id": "5ba08fb4-0d61-4b47-a118-fb0a1d34b5ea", "state": "TN", "county": "Shelby", "source": "laft",
            "harvester_source": SID, "parcel": "07001200000010", "latitude": None, "longitude": None,
            "field_provenance": {}}
    base.update(kw)
    return base


def test_the_row_without_a_point_has_no_authoritative_source_today():
    assert G.sources_for("TN", "Shelby") == []
    assert G.plan_row(_row()) == ("NO_SOURCE", None)


def _src():
    return G.CoordinateSource(source_id="tn_test_parcels", state="TN", method="PARCEL_GIS", geometry="PARCEL_CENTROID",
                              provenance_source="statewide_parcel", agency="test", dataset="test",
                              layer_url="https://example.gov/0", landing_url="https://example.gov",
                              publication_status="APPROVED", verified=True, counties=("Shelby",))


@pytest.mark.parametrize("features, want", [
    ([{"pt": (35.1, -90.0)}], "MATCHED"),               # exactly one feature on the parcel id
    ([], "NO_MATCH"),                                    # none: nothing written, nothing copied from a neighbour
    ([{"pt": (35.1, -90.0)}, {"pt": (35.2, -90.1)}], "AMBIGUOUS"),
    ([{"pt": (40.0, -75.0)}], "PARSER_FAILURE"),          # outside Tennessee
])
def test_authoritative_match_outcomes(features, want):
    lk = G.from_feature_count(features, "TN", point_of=lambda f: f["pt"], matched_identifier="07001200000010")
    assert lk.status == want
    kind, out = G.decide(_row(), _src(), lk, allow_upgrade=False, recorded_at="2026-10-10T00:00:00+00:00")
    if want == "MATCHED":
        assert kind == "write" and (out["latitude"], out["longitude"]) == (35.1, -90.0)
        assert out["field_provenance"]["latitude"]["method"] == "PARCEL_GIS"
    else:
        assert kind == "skip" and out == want


def _geo(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_dq_geocode", SCRIPTS / "geocode_properties.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_address_geocoder_never_reads_an_authoritative_point_source(monkeypatch):
    geo = _geo(monkeypatch)
    seen = []

    class R:
        status_code = 200
        text = "[]"
        def raise_for_status(self): pass
        def json(self): return []
    monkeypatch.setattr(geo.requests, "get", lambda url, headers, params, timeout: (seen.append(dict(params)), R())[1])
    geo.read_pool(10)
    assert seen and all(p["or"] == "(harvester_source.is.null,harvester_source.not.in.(tn_shelby_landbank))" for p in seen)
    assert set(geo.NO_ADDRESS_GEOCODE_SOURCES) <= {s for s, v in __import__(
        "harvesters.sources.coordinates", fromlist=["x"]).SOURCE_COORDINATES.items() if v[0] == "LAND_BANK_GIS"}


# ------------------------------------------------------------- E flood

def _flood(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_dq_flood", SCRIPTS / "enrich_flood_zone.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plan_slices_gives_a_one_county_state_the_unused_budget(monkeypatch):
    f = _flood(monkeypatch)
    assert f.plan_slices([(("TN", "Shelby"), 2037)], 500, 40) == [(("TN", "Shelby"), 500, 2037)]
    # Every unit gets its fair first slice before any unit gets more.
    units = [(("FL", "Bay"), 10), (("TN", "Shelby"), 2037), (("SC", "Horry"), 60)]
    plan = f.plan_slices(units, 200, 40)
    # Pass 2 is round robin, 40 at a time: Horry is filled to its 60, Shelby takes the rest.
    assert plan == [(("FL", "Bay"), 10, 10), (("TN", "Shelby"), 130, 2037), (("SC", "Horry"), 60, 60)]
    assert sum(n for _, n, _ in plan) <= 200
    # Budget smaller than one slice each: pass 1 order wins, nothing extra.
    assert f.plan_slices(units, 30, 40) == [(("FL", "Bay"), 10, 10), (("TN", "Shelby"), 20, 2037)]
    # Never more than a unit's own backlog, never more than the budget.
    assert f.plan_slices([(("FL", "Bay"), 3)], 500, 40) == [(("FL", "Bay"), 3, 3)]
    assert f.plan_slices([], 500, 40) == []


def test_flood_run_spends_the_budget_on_shelby_and_writes_only_answers(monkeypatch):
    f = _flood(monkeypatch)
    monkeypatch.setattr(f, "BATCH_LIMIT", 50)
    monkeypatch.setattr(f, "PER_COUNTY_LIMIT", 10)
    monkeypatch.setattr(f, "REQUEST_DELAY_SECONDS", 0)
    monkeypatch.setattr(f, "schema_is_ready", lambda: True)
    monkeypatch.setattr(f, "fetch_counties_needing_flood", lambda: [(("TN", "Shelby"), 2037)])
    asked = []
    monkeypatch.setattr(f, "fetch_county_batch", lambda unit, limit, outstanding=None: (
        asked.append(limit), [{"id": f"r{i}", "latitude": 35.1, "longitude": -90.0} for i in range(limit)])[1])
    answers = iter([({"FLD_ZONE": "X", "SFHA_TF": "F"}, True), (None, True), (None, False)] * 20)
    monkeypatch.setattr(f, "lookup_flood_zone", lambda lat, lng: next(answers))
    writes = {}
    monkeypatch.setattr(f, "patch_property", lambda pid, fields: writes.__setitem__(pid, fields))
    assert f.main() == 0
    assert asked == [50]                                   # was 10 (the per-county cap) before
    zones = [w["flood_zone"] for w in writes.values()]
    assert len(writes) < 50 and set(zones) <= {"X", f.UNMAPPED}       # a failed lookup writes nothing
    assert all("publication_status" not in w for w in writes.values())


# ------------------------------------------------------------- F publication gate

def test_a_complete_harvest_never_approves_the_source():
    reg = SP.registry_with_reviews("TN", reviews={})[0]
    rows = [r.to_properties_row() for r in _records()]
    sent, counts = SY.plan("TN", rows, reg, {(SID, "Shelby"): "COMPLETE"},
                           observed_at="2026-10-10T12:00:00+00:00")
    assert {r["publication_status"] for r in sent} == {"UNREVIEWED"}
    assert counts["written_review_pending"] == len(sent)
    assert not SP.publishable(reg[SID]) and EX.PUBLICATION[SID][0] == "UNREVIEWED"


@pytest.mark.parametrize("script", ["enrich_flood_zone.py", "geocode_properties.py", "enrich_statewide_parcels.py",
                                    "geocode_authoritative.py", "enrich_property_photos_naip.py"])
def test_enrichment_never_writes_publication_status(script):
    src = (SCRIPTS / script).read_text(encoding="utf-8")
    assert not re.search(r"""["']publication_status["']\s*:""", src), script


def test_frontend_keeps_preview_mode_and_the_withheld_wording():
    cfg = (ROOT / "config.js").read_text(encoding="utf-8")
    assert re.search(r'publicationMode:\s*"preview"', cfg)
    app = (ROOT / "public/app.js").read_text(encoding="utf-8")
    assert "withheld - source not approved for customer publication" in app and "Source review: " in app
    assert "function isCustomerPublishable" in app


# ------------------------------------------------------------- Part 2: source semantics

def test_shelby_semantics_decide_the_available_ledger_not_the_status_string():
    from harvesters.ledgers import SOURCE_LEDGERS, Ledger
    sem = EX.TN_SHELBY_SEMANTICS
    cfg = EX.TN_SHELBY_LANDBANK
    assert sem["ledger"] == "AVAILABLE" and SOURCE_LEDGERS[SID] == {Ledger.AVAILABLE}
    assert cfg.record_source == "laft" and cfg.inventory_type.value == "POST_SALE"
    assert "Land Bank" in sem["publisher"] and "County DTP" in sem["inventory"]
    assert set(sem["fields"]) >= {f for f, _ in cfg.offered}            # the classification's own fields
    assert sem["auction"].startswith("none")                              # never AUCTIONS
    # FOR SALE alone is never enough: SALE PENDING with available Y, and FOR SALE with N, are excluded.
    pages = _pages()
    statuses = {(r["currentStatus"], r["available"]) for pg in pages for r in pg["rows"]}
    assert ("SALE PENDING", "Y") in statuses and ("FOR SALE", "N") in statuses
    recs = _records()
    assert {r.source_status_text for r in recs} == {"FOR SALE"} and len(recs) == 2
    assert {r.provenance["portal_inventory_type"] for r in recs} == {"County DTP"}
    for r in recs:
        row = r.to_properties_row()
        assert row["source"] == "laft" and row.get("sale_date") is None   # no auction date is invented


def test_no_tennessee_certificate_or_auction_source_exists():
    tn = [s.config for s in EX.SOURCES["TN"]]
    assert [c.source_id for c in tn] == [SID]
    assert all(c.record_source == "laft" for c in tn)
