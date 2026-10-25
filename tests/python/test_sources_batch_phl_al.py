"""Sources batch 2026-10-25: Philadelphia (PA) surplus land and the Alabama
ADOR weekly county transcripts - both AVAILABLE, both UNREVIEWED, both gated.

Philadelphia is configured on the generic ArcGIS adapter and shipped under
expansion.COLLECTION_HOLD: the expansion runner reports it GATED and never
requests it. Alabama is a registered, non-activated state: the transcript
adapter refuses before any request and reports nothing COMPLETE / EMPTY
until fixture-validated. Every fixture here is SYNTHETIC (invented names,
identifiers and coordinates in the live layouts) - docs/sources-batch-2026-10-25-phl-al.md."""
import ast
import dataclasses
import json
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import harvest_expansion as HE  # noqa: E402
import source_publication as SP  # noqa: E402
from harvesters.governance import permissions as PERM, states  # noqa: E402
from harvesters.governance.county_source_registry import load_registry  # noqa: E402
from harvesters.governance.inventory_status import AVAILABLE_OFFERED_WORDINGS  # noqa: E402
from harvesters.ledgers import SOURCE_LEDGERS, Ledger  # noqa: E402
from harvesters.otc.adapters import alabama as ALA, alabama_transcripts as T, arcgis as AG, expansion as EX  # noqa: E402
from harvesters.otc.model import AmountKind, InventoryType, PurchaseUrlKind  # noqa: E402
from harvesters.sources import available_terms  # noqa: E402

AT = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
FX = ROOT / "tests/python/fixtures"
PHL_FIXTURE = FX / "batch_2026_10_25/pa_philadelphia_lama_SYNTHETIC.json"
AL_FIXTURE = FX / "alabama/transcript_04_SYNTHETIC.txt"
PHL = "pa_philadelphia_lama_available"
REG = {r.source_id: r for r in load_registry()}


def _phl_src():
    (src,) = [s for s in EX.SOURCES["PA"] if s.config.source_id == PHL]
    return src


# ============================== Philadelphia ==============================

def test_phl_config_reads_exactly_the_land_banks_own_available_filter():
    cfg = EX.PA_PHILADELPHIA_LAMA
    # The Land Bank's "Available Properties in Philadelphia" web map's definition expression, verbatim.
    assert cfg.where == ("(STATUS_1 = 'Owned - Available') OR (STATUS_1 = 'Owned - Available (Garden Agreement)') OR "
                         "(STATUS_1 = 'Owned - Available (no construction permitted)') OR (STATUS_1 = 'Owned - Available (not for SY)')")
    assert cfg.layer_url == "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/LAMAAssets/FeatureServer/0"
    assert (cfg.state, cfg.county, cfg.record_source, cfg.inventory_type) == ("PA", "Philadelphia", "laft", InventoryType.POST_SALE)
    assert cfg.columns_verified and cfg.centroid and cfg.amount_kind is AmountKind.NOT_PUBLISHED
    assert cfg.purchase_url_kind is PurchaseUrlKind.PURCHASE_INSTRUCTIONS and cfg.purchase_url != cfg.list_url
    # Only property fields: the owning agency, council district, side-yard flag and zoning are never requested.
    out = AG.query_params(cfg)["outFields"].split(",")
    assert set(out) == {"mapreg_1", "opabrt", "location", "status_1"}
    assert not {"agency", "councildistrict", "sideyardeligible", "zoning", "pin"} & set(out)
    assert cfg.fields.owner_name is None
    # The offered wordings the inventory-status writer trusts are the config's own filter.
    assert AVAILABLE_OFFERED_WORDINGS[PHL] == EX.PHL_AVAILABLE_STATUSES


def test_phl_is_registered_available_unreviewed_and_held():
    assert SOURCE_LEDGERS[PHL] == {Ledger.AVAILABLE}
    assert EX.PUBLICATION[PHL] == ("UNREVIEWED", EX.HELD_AVAILABLE) and PHL in EX.BATCH_2026_10_25_SOURCE_IDS
    assert PHL in EX.COLLECTION_HOLD
    row = REG[PHL]
    assert row.is_production and row.publication_status == "UNREVIEWED" and row.ledgers == "AVAILABLE"
    assert row.county == "Philadelphia" and row.machine_format == "JSON" and row.access_method == "JSON_ENDPOINT"
    assert not SP.publishable(row)                         # never customer-published until a review approves it
    # fetch / parse / store are recorded (interim, expiring); display is not.
    for op in ("fetch", "parse", "store"):
        d = PERM.authorize(PHL, op, state="PA", today=AT.date())
        assert d.allowed and not d.documented and d.expires_on == "2027-04-12", op
    assert not PERM.authorize(PHL, "display", state="PA", today=AT.date()).allowed


def test_phl_runnable_sources_reports_it_gated():
    reg = SP.registry_with_reviews("PA", reviews={})[0]
    run, gated = HE.runnable_sources("PA", reg)
    assert PHL not in {s.config.source_id for s in run}
    assert (PHL, "UNREVIEWED (collection hold)") in gated
    assert HE.gate("PA", reg=reg) == []                    # the rest of PA still runs


def test_phl_live_mode_prints_gated_and_makes_zero_requests_to_it(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    requested = []

    class _Session:
        headers: dict = {}

        def get(self, url, **kw):
            requested.append(url)
            raise ConnectionError("no network in tests")

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(Session=_Session))
    rc = HE.main(["--state", "PA", "--out-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"PA {PHL} GATED publication=UNREVIEWED (collection hold) - 0 requests" in out
    assert requested and not any("LAMAAssets" in u or "phillylandbank" in u for u in requested)
    assert all("fayettecountypa.org" in u for u in requested)   # only the other PA source was attempted


def test_phl_fixture_parses_through_the_runner_without_owner_or_agency(tmp_path):
    status, recs, cat, _, _ = HE.run_source(_phl_src(), None, None, retrieved_at=AT, fixture=str(PHL_FIXTURE))
    assert status == "COMPLETE" and cat is None and len(recs) == 3
    assert [r.case_no for r in recs] == ["000N000001", "000N000002", "000N000003"]
    assert [r.parcel for r in recs] == ["000000001", "000000002", None]          # whitespace stripped; blank kept blank
    assert [r.source_status_text for r in recs] == list(EX.PHL_AVAILABLE_STATUSES[:1] + EX.PHL_AVAILABLE_STATUSES[2:])
    for r in recs:
        assert r.validate() == [] and r.owner_name is None and r.amount is None
        assert 39.86 <= r.latitude <= 40.14 and -75.29 <= r.longitude <= -74.95
        assert "centroid" in r.provenance["coordinates"]
        row = r.to_properties_row()
        assert row["state"] == "PA" and row["county"] == "Philadelphia" and row["source"] == "laft"
        assert "agency" not in json.dumps(r.provenance)
    # Through main's fixture mode: rows written, nothing synced.
    rc = HE.main(["--state", "PA", "--fixture", f"{PHL}={PHL_FIXTURE}", "--out-dir", str(tmp_path)])
    assert rc == 0 and len(json.loads((tmp_path / "pa_properties_rows.json").read_text())) == 3


def test_phl_transport_failure_is_failed_never_zero():
    def boom(url):
        raise ConnectionError("down")
    res = AG.fetch_all(EX.PA_PHILADELPHIA_LAMA, boom, retrieved_at=AT)
    assert res.outcome == "FAILED" and res.records == []


# ============================== Alabama transcripts ==============================

def _lines():
    return AL_FIXTURE.read_text(encoding="utf-8").splitlines()


def test_al_transcript_files_are_the_land_sales_pages_own_mapping():
    assert len(T.TRANSCRIPT_FILES) == 68
    assert {c for c, _ in T.TRANSCRIPT_FILES.values()} == ALA.ALABAMA_COUNTIES
    assert T.TRANSCRIPT_FILES["01"] == ("Jefferson", "Jefferson-Birmingham")
    assert T.TRANSCRIPT_FILES["68"] == ("Jefferson", "Jefferson-Bessemer")
    assert T.TRANSCRIPT_FILES["02"][0] == "Mobile" and T.TRANSCRIPT_FILES["04"][0] == "Autauga"   # not alphabetical
    assert T.transcript_url("04").endswith("/property-tax-transcripts/WWW_TRANS_04.PDF")
    with pytest.raises(ValueError):
        T.transcript_url("69")


def test_al_synthetic_transcript_parses_without_names_or_amounts():
    p = T.parse_lines(T.TRANSCRIPT_SOURCE, "04", _lines(), retrieved_at=AT)
    assert [r.case_no for r in p.records] == [f"0000000{i}" for i in range(1, 8)]
    assert p.headers_seen == 2 and p.list_as_of.isoformat() == "2026-10-19"
    assert (p.record_lines, p.amount_lines, p.missing_amount_line, p.orphan_lines, p.rejected) == (7, 6, 1, 0, 0)
    by = {r.case_no: r for r in p.records}
    assert by["00000001"].legal_desc == "LOT 1 BLK 1 TEST ADDITION"
    assert by["00000002"].legal_desc == "BEG AT A TEST POINT TH N 100 FT TH E 50 FT TO THE POB"   # amount line's tail kept
    assert by["00000003"].parcel == "000000000000000003"                                        # name glued to CO. still read
    assert by["00000005"].legal_desc == "LOT 5 BLK 2 TEST ADDITION CONTINUED ON A SECOND LINE"   # amount after a description line
    assert by["00000006"].legal_desc is None
    assert by["00000007"].legal_desc == "LOT 7 BLK 3 TEST ADDITION MORE OF THE SEVENTH DESCRIPTION"
    for r in p.records:
        assert r.validate() == [] and r.county == "Autauga" and r.state == "AL"
        assert r.amount is None and r.amount_kind is AmountKind.QUOTED_ON_APPLICATION
        assert r.owner_name is None and r.inventory_type is InventoryType.STATE_HELD_TAX_LAND
        assert r.list_url == T.transcript_url("04") and r.purchase_url == ALA.ADOR_LAND_SALES_URL
        assert r.purchase_url_kind is PurchaseUrlKind.PURCHASE_INSTRUCTIONS
        blob = json.dumps(r.to_harvest_row(), default=str)
        assert "SYNTHETIC OWNER" not in blob and "GLUED NAME" not in blob          # the NAME column is never carried
        assert "123.45" not in blob and "1,234.56" not in blob                     # nor the tax-sale amount


def test_al_nothing_complete_or_empty_until_fixture_validated():
    cfg = T.TRANSCRIPT_SOURCE
    assert not cfg.parser_fixture_validated and not cfg.live_verified and not cfg.enabled
    p = T.parse_lines(cfg, "04", _lines(), retrieved_at=AT)
    o = T.classify_outcome(cfg, "04", p)
    assert (o.status, o.category, o.row_count) == ("INCOMPLETE", "UNKNOWN", 7)
    empty = T.parse_lines(cfg, "04", _lines()[:4], retrieved_at=AT)
    assert T.classify_outcome(cfg, "04", empty).status == "INCOMPLETE"
    assert T.classify_outcome(cfg, "04", empty).category == "UNCONFIRMED_EMPTY"
    # A validated parser (hypothetical) may say COMPLETE / EMPTY - and still never on drift.
    ok = dataclasses.replace(cfg, parser_fixture_validated=True)
    assert T.classify_outcome(ok, "04", p).status == "COMPLETE"
    assert T.classify_outcome(ok, "04", empty).status == "EMPTY"
    wrong = T.parse_lines(ok, "05", _lines(), retrieved_at=AT)       # every CO. says 04, the file is 05
    assert wrong.records == [] and wrong.county_mismatch == 7
    assert T.classify_outcome(ok, "05", wrong).status == "INCOMPLETE"
    assert T.classify_outcome(ok, "04", T.parse_lines(ok, "04", [], retrieved_at=AT)).category == "PARSE_FORMAT_CHANGE"


def test_al_transcripts_refuse_before_any_request():
    assert not states.is_activated("AL")
    calls = []
    verified = dataclasses.replace(T.TRANSCRIPT_SOURCE, live_verified=True, parser_fixture_validated=True, enabled=True)
    for cfg in (T.TRANSCRIPT_SOURCE, verified):
        assert not T.can_run(cfg).allowed and "not activated" in T.can_run(cfg).reason
        with pytest.raises(RuntimeError, match="may not run"):
            T.harvest(cfg, lambda url: calls.append(url) or b"", retrieved_at=AT)
    assert calls == []
    with pytest.raises(ValueError):
        dataclasses.replace(T.TRANSCRIPT_SOURCE, enabled=True)          # enabled before verification is refused


def test_al_module_has_no_transport_and_names_only_the_agency_host():
    src = (ROOT / "harvesters/otc/adapters/alabama_transcripts.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for n in names:
                assert not (n or "").startswith(("requests", "urllib", "http", "playwright", "socket")), n
    assert set(re.findall(r"https://([^/\s\"']+)", src)) == {ALA.ADOR_HOST}


def test_al_transcripts_registry_terms_and_permissions():
    row = REG[T.SOURCE_ID]
    assert row.state == "AL" and row.county == "STATEWIDE" and not row.is_production and not row.runnable
    assert row.verification_status == "MANUAL_REVIEW_REQUIRED" and row.governance_status == "TERMS_NOT_VERIFIED"
    assert row.publication_status == "UNREVIEWED" and not row.harvester and row.machine_format == "PDF"
    assert SOURCE_LEDGERS[T.SOURCE_ID] == {Ledger.AVAILABLE}
    terms = {(r["state"], r["source_id"]): r for r in available_terms.load()}
    assert terms[("AL", T.SOURCE_ID)]["basis"] == "QUOTED_ON_REQUEST"
    assert terms[("PA", PHL)]["basis"] == "OFFER_NEGOTIATED"
    # A recorded fetch permission never opens a non-activated state.
    assert PERM.authorize(T.SOURCE_ID, "fetch", state="AL", today=AT.date()).allowed
    assert not T.can_run(T.TRANSCRIPT_SOURCE).allowed
    for sid in (T.SOURCE_ID, PHL):
        recs = [r for r in PERM.load() if r.source_id == sid]
        assert sorted(r.operation for r in recs) == ["fetch", "parse", "store"]
        assert all(r.evidence_type == "INTERNAL_RISK_ACCEPTANCE" and r.conditions == ("excluded_from_paid_tier",)
                   and r.reason.endswith("not sold until legal review.") for r in recs)


def test_no_committed_fixture_carries_a_real_looking_identifier():
    text = AL_FIXTURE.read_text(encoding="utf-8")
    assert all(re.fullmatch(r"0+\d", cs) for cs in re.findall(r"\b\d{8}\b", text))
    phl = json.loads(PHL_FIXTURE.read_text(encoding="utf-8"))
    assert all("SYNTHETIC" in f["attributes"]["location"] for f in phl["features"])
