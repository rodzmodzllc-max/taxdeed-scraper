"""Source permission at the entry points PR #145 left open (2026-10-13).

Each test proves a denied operation cannot proceed: the entry point stops
before any request or write, and a real recorded permission still lets
today's production run through (parity). Permission records come from
data/source_permissions.csv; a denial is produced by removing a source's
records or by an empty permission set, evaluated by the real engine.
"""
from __future__ import annotations

import csv
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from harvesters.governance import permissions as PERM  # noqa: E402
from permission_fixtures import install, permissions_with  # noqa: E402


def install_without(monkeypatch, *source_ids: str):
    """The real permission set minus every record of `source_ids`."""
    with PERM.PERMISSIONS_CSV.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["source_id"] not in source_ids]
    perms = permissions_with(*rows, base=False)
    assert perms.error is None
    monkeypatch.setattr(PERM, "_DEFAULT", perms)
    return perms


def deny_all(monkeypatch):
    return install(monkeypatch, base=False)


@pytest.fixture(autouse=True)
def _real_permissions(monkeypatch):
    # enrich_property_details refuses to import without these; no request is
    # ever sent to them (no_network() fails the test on any request).
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "x")
    monkeypatch.setattr(PERM, "_DEFAULT", None)
    yield


def no_network(monkeypatch):
    """Any outbound request fails the test."""
    import urllib.request

    import requests

    def boom(*a, **k):
        raise AssertionError("a request was made after a permission denial")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(requests, "patch", boom)
    monkeypatch.setattr(requests.Session, "request", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)


# --- Lands Available lifecycle: store per county -------------------------

def _gates(*pairs):
    return {county: {"status": "COMPLETE", "observed_ok": True, "closeout_ok": True, "harvester": src,
                     "entry": {"source_id": src}} for county, src in pairs}


def test_lifecycle_parity_every_fl_laft_source_and_la_may_store():
    import laft_lifecycle as LL
    fl = _gates(*[(f"C{i}", s) for i, s in enumerate(sorted({
        "fl_laft_hillsborough", "fl_laft_html", "fl_laft_leon", "fl_laft_orange", "fl_laft_osceola",
        "fl_laft_pdfs", "fl_laft_pioneer", "fl_laft_realtdm", "fl_laft_stlucie"}))])
    assert LL.apply_store_permission(fl, "FL") == {}
    la = _gates(("East Baton Rouge", "la_ebr_adjudicated"))
    assert LL.apply_store_permission(la, "LA") == {}


def test_lifecycle_withdraws_a_denied_county_from_observe_and_close(monkeypatch):
    import laft_lifecycle as LL
    install_without(monkeypatch, "fl_laft_leon")
    gates = _gates(("Leon", "fl_laft_leon"), ("Citrus", "fl_laft_pdfs"))
    withdrawn = LL.apply_store_permission(gates, "FL")
    assert withdrawn == {"Leon": "UNKNOWN_SOURCE"} or set(withdrawn) == {"Leon"}
    assert gates["Leon"]["status"] == LL.NOT_PERMITTED and not gates["Leon"]["observed_ok"] and not gates["Leon"]["closeout_ok"]
    observed = {"Leon": {"L1": {}}, "Citrus": {"C1": {}}}
    db_rows = [{"id": 1, "county": "Leon", "case_no": "L9", "status": "active"},
               {"id": 2, "county": "Citrus", "case_no": "C9", "status": "active"}]
    plan = LL.plan_lifecycle(gates, observed, db_rows)
    assert ("Leon", "L1") not in plan.observe and ("Citrus", "C1") in plan.observe
    assert [r["county"] for r in plan.close] == ["Citrus"]
    assert plan.skipped_counties["Leon"] == LL.NOT_PERMITTED


def test_lifecycle_fails_closed_without_a_source_or_governance():
    import laft_lifecycle as LL
    gates = {"X": {"status": "COMPLETE", "observed_ok": True, "closeout_ok": True, "harvester": None, "entry": None},
             "Y": {"status": "COMPLETE", "observed_ok": True, "closeout_ok": True, "harvester": "fl_laft_pdfs", "entry": {}}}

    def broken(source_id, county):
        raise RuntimeError("governance unreadable")
    withdrawn = LL.apply_store_permission(gates, "FL", authorize=broken)
    assert withdrawn["X"] == "NO_SOURCE" and withdrawn["Y"].startswith("GOVERNANCE_UNAVAILABLE")


# --- FL stamp + carry ----------------------------------------------------

def test_stamp_seen_parity_and_denial(monkeypatch, tmp_path):
    import stamp_seen as SS
    assert SS.store_permitted("FL", "auction") and SS.store_permitted("FL", "certificate")
    install_without(monkeypatch, "fl_lienhub_certificates")
    no_network(monkeypatch)
    harvest = tmp_path / "h.json"
    harvest.write_text("[]", encoding="utf-8")
    assert SS.main(["--state", "FL", "--source", "certificate", "--harvest", str(harvest)]) == SS.PERMISSION_DENIED_EXIT


def test_stamp_seen_refuses_an_unmapped_ledger(monkeypatch, tmp_path):
    import stamp_seen as SS
    no_network(monkeypatch)
    assert not SS.store_permitted("FL", "laft") and not SS.store_permitted("TX", "auction")
    assert SS.main(["--state", "FL", "--source", "laft", "--harvest", str(tmp_path / "none.json")]) == SS.PERMISSION_DENIED_EXIT


# --- Auction event sightings ---------------------------------------------

def test_auction_events_writer_parity_and_denial(monkeypatch):
    import auction_events_writer as AW
    assert AW.store_permitted("fl") and AW.store_permitted("tx")
    assert not AW.store_permitted("zz")
    install_without(monkeypatch, "tx_lgbs")
    no_network(monkeypatch)
    monkeypatch.setattr(AW, "build_store", lambda dry: (_ for _ in ()).throw(AssertionError("store built after denial")))
    assert AW.main(["--source", "tx"]) == AW.PERMISSION_DENIED_EXIT


# --- Acquisition paths written onto rows ---------------------------------

def test_apply_acquisition_paths_skips_rows_of_a_denied_source(monkeypatch):
    import apply_acquisition_paths as AP
    permitted = AP.store_permitted_for("LA")
    assert permitted({"source_id": "la_ebr_adjudicated"})
    assert AP.store_permitted_for("TX")({"source_id": "tx_lgbs"})
    assert not permitted({"source_id": ""}) and not permitted({})
    install_without(monkeypatch, "tx_lgbs")
    assert not AP.store_permitted_for("TX")({"harvester_source": "tx_lgbs"})
    calls = []
    p = AP.store_permitted_for("TX", decide=lambda s: calls.append(s) or True)
    assert p({"source_id": "a"}) and p({"source_id": "a"}) and calls == ["a"]
    broken = AP.store_permitted_for("TX", decide=lambda s: 1 / 0)
    assert not broken({"source_id": "a"})


# --- FDOR and the two county fallbacks -----------------------------------

def _fresh_enricher():
    import enrich_property_details as EPD
    EPD = importlib.reload(EPD)
    return EPD


@pytest.mark.parametrize("fn,args,source", [
    ("lookup_fdor", ("Leon", "1234567"), "fl_fdor_cadastral"),
    ("lookup_santa_rosa_gis", ("1234567",), "fl_santa_rosa_parcels"),
    ("lookup_flagler_gis", ("1234567",), "fl_palm_coast_flagler_parcels"),
])
def test_fdor_lookups_refuse_before_any_request(monkeypatch, fn, args, source):
    EPD = _fresh_enricher()
    install_without(monkeypatch, source)
    no_network(monkeypatch)
    monkeypatch.setattr(EPD, "_query_layer", lambda *a, **k: (_ for _ in ()).throw(AssertionError("FDOR queried")))
    with pytest.raises(EPD.SourceNotPermitted):
        getattr(EPD, fn)(*args)


def test_fdor_lookup_requires_both_datasets(monkeypatch):
    EPD = _fresh_enricher()
    with PERM.PERMISSIONS_CSV.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)
                if not (r["source_id"] == "fl_fdor_cadastral" and r["dataset"] == "parcel_centroid")]
    monkeypatch.setattr(PERM, "_DEFAULT", permissions_with(*rows, base=False))
    no_network(monkeypatch)
    with pytest.raises(EPD.SourceNotPermitted):
        EPD.lookup_fdor("Leon", "1234567")


def test_fdor_lookup_parity_reaches_the_layer(monkeypatch):
    EPD = _fresh_enricher()
    seen = []
    monkeypatch.setattr(EPD, "_query_layer", lambda where: seen.append(where) or [])
    EPD.lookup_fdor("Leon", "1234567")
    assert seen, "a permitted FDOR lookup must still query the layer"


def test_fdor_backfill_job_stops_without_permission(monkeypatch):
    import backfill_fdor_phase52_fields as BF
    BF = importlib.reload(BF)
    assert BF.fdor_permitted()
    deny_all(monkeypatch)
    no_network(monkeypatch)
    monkeypatch.setattr(BF.prod, "SUPABASE_URL", "https://example.invalid")
    monkeypatch.setattr(BF.prod, "SERVICE_KEY", "x")
    with pytest.raises(SystemExit) as e:
        BF.main()
    assert e.value.code == BF.PERMISSION_DENIED_EXIT


def test_fdor_backfill_skips_a_denied_fallback(monkeypatch):
    import backfill_fdor_phase52_fields as BF
    BF = importlib.reload(BF)
    install_without(monkeypatch, "fl_santa_rosa_parcels")
    monkeypatch.setattr(BF.prod, "lookup_fdor", lambda county, parcel: (None, None, None))
    monkeypatch.setattr(BF.prod, "lookup_santa_rosa_gis", lambda p: (_ for _ in ()).throw(AssertionError("fallback queried")))
    attrs, _c, _cand, path = BF.production_lookup({"county": "Santa Rosa", "parcel": "1"})
    assert attrs is None and path == "fdor"


# --- Texas CAD fetchers (draft, no record) -------------------------------

@pytest.mark.parametrize("fn", ["_fetch_hcad", "_fetch_tad"])
def test_texas_cad_fetchers_refuse_without_a_record(monkeypatch, fn):
    import enrich_property_details_tx as TXE
    no_network(monkeypatch)
    with pytest.raises(TXE.SourceNotPermitted):
        getattr(TXE, fn)("123")


# --- Alabama (registered, not activated) ---------------------------------

def test_alabama_live_mode_is_denied_even_if_activation_passes(monkeypatch, tmp_path, capsys):
    import harvest_alabama_state_land as HA
    no_network(monkeypatch)
    monkeypatch.setattr(HA.ala, "can_run", lambda cfg: type("D", (), {"allowed": True, "reason": ""})())
    monkeypatch.setattr(HA, "live_fetcher", lambda: (_ for _ in ()).throw(AssertionError("fetcher built")))
    rc = HA.main(["--status", str(tmp_path / "s.json"), "--out", str(tmp_path / "o.json"),
                  "--report", str(tmp_path / "r.json")])
    assert rc == 3 and not (tmp_path / "o.json").exists()
    assert "not permitted" in capsys.readouterr().out


# --- Coverage map: every entry point named here is wired -----------------

GATED = {
    "scripts/laft_lifecycle.py": "apply_store_permission(",
    "scripts/stamp_seen.py": "store_permitted(",
    "scripts/auction_events_writer.py": "store_permitted(",
    "scripts/apply_acquisition_paths.py": "store_permitted_for(",
    "scripts/enrich_property_details.py": "_require_lookup_permission(",
    "scripts/backfill_fdor_phase52_fields.py": "fdor_permitted(",
    "scripts/enrich_property_details_tx.py": "_require_cad_permission(",
    "scripts/harvest_alabama_state_land.py": "PG.allowed(",
}


@pytest.mark.parametrize("path,marker", sorted(GATED.items()))
def test_entry_point_names_its_gate(path, marker):
    # The behaviour is proven by the tests above; this pins that the gate
    # stays in the file when it is edited.
    assert marker in (ROOT / path).read_text(encoding="utf-8"), f"{path} lost its permission gate {marker}"


def test_report_is_counts_only(tmp_path):
    # The lifecycle's withdrawal is reported as county name + reason code.
    import laft_lifecycle as LL
    gates = _gates(("Leon", "fl_laft_leon"))
    withdrawn = LL.apply_store_permission(gates, "FL", authorize=lambda s, c: type("D", (), {"allowed": False, "reason_code": "NO_RECORD"})())
    assert json.loads(json.dumps(withdrawn)) == {"Leon": "NO_RECORD"}


# --- FDOR in the source inventory: no unsupported approval ---------------

def test_inventory_builtin_sources_cite_permission_records_not_assertions():
    from harvesters.sources import inventory as INV
    builtins = {s.source_id: s for s in INV._builtin_sources()}
    for sid, s in builtins.items():
        assert s.evidence.startswith("data/source_permissions.csv"), sid
        assert "public-domain" not in s.evidence and "docstring" not in s.evidence, sid
    fdor = builtins["fl_statewide_cadastral"].evidence
    assert "interim" in fdor and "not documented permission" in fdor and "documented (" not in fdor


def test_inventory_basis_for_a_source_without_records_says_denied():
    from harvesters.sources import inventory as INV
    assert "every operation is denied" in INV.permission_basis("zz_nonexistent_source")


# --- Florida PowerShell guard: allowed / missing / expired / conditional ---

PS1 = ["harvest_all_counties.ps1", "harvest_okaloosa_bid4assets.ps1", "harvest_lienhub_certificates.ps1",
       "sync-harvest-to-supabase.ps1", "sync-certificates-to-supabase.ps1", "sync-laft-to-supabase.ps1"]


def _guard_cli(name):
    from ps1_permission_guard import guard_args
    args = guard_args((ROOT / "scripts" / name).read_text(encoding="utf-8"))
    return [sys.executable, str(ROOT / "scripts" / "source_permission_check.py"), *args], args


def _write_variant(tmp_path, args, mutate):
    sources = {args[i + 1] for i, x in enumerate(args) if x == "--source"}
    with PERM.PERMISSIONS_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        if r["source_id"] in sources:
            r = mutate(dict(r))
            if r is None:
                continue
        out.append(r)
    path = tmp_path / "variant.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PERM.COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    return path


@pytest.mark.parametrize("name", PS1)
@pytest.mark.parametrize("case,mutate,code", [
    ("missing", lambda r: None, "UNKNOWN_SOURCE"),
    ("expired", lambda r: {**r, "expires_on": "2020-01-01", "effective_on": "2019-01-01", "evidence_date": "2019-01-01",
                           "last_verified_on": "2019-01-01"}, "EXPIRED"),
    ("condition_unmet", lambda r: {**r, "conditions": "attribution_text_recorded", "attribution": ""}, "CONDITION_UNMET"),
    ("blocked", lambda r: {**r, "status": "BLOCKED", "evidence_type": "PROHIBITION_FOUND"}, "BLOCKED"),
])
def test_powershell_guard_denies(name, case, mutate, code, tmp_path):
    import subprocess
    cli, args = _guard_cli(name)
    variant = _write_variant(tmp_path, args, mutate)
    res = subprocess.run([*cli, "--permissions", str(variant)], capture_output=True, text=True, cwd=str(ROOT))
    assert res.returncode == 3, (case, res.stdout, res.stderr)
    decisions = [json.loads(line) for line in res.stdout.splitlines() if line.startswith("{")]
    denied = [d for d in decisions if not d["allowed"]]
    assert denied, case
    assert {d["reason_code"] for d in denied} == {code}, (case, [d["reason_code"] for d in denied])


@pytest.mark.parametrize("name", PS1)
def test_powershell_guard_allows_with_the_real_records(name):
    import subprocess
    cli, _ = _guard_cli(name)
    res = subprocess.run(cli, capture_output=True, text=True, cwd=str(ROOT))
    assert res.returncode == 0, res.stdout + res.stderr


# --- GovEase: stays blocked with stale evidence, missing terms or a fallback ---

def test_govease_stays_blocked_if_the_registry_entry_loses_its_terms_and_block(monkeypatch):
    # Even if the registry entry were edited to drop its terms finding and its
    # BLOCKED status (stale or missing evidence), the permission engine still
    # refuses: the block is in code, not in the registry text.
    import dataclasses

    from harvesters.governance import registry as REG
    entry = REG.SOURCE_REGISTRY["tx_govease"]
    softened = dataclasses.replace(entry, terms_status="", robots_status="", legal_status=REG.SourceStatus.APPROVED)
    monkeypatch.setitem(REG.SOURCE_REGISTRY, "tx_govease", softened)
    for op in PERM.OPERATIONS:
        d = PERM.Permissions.from_file().authorize("tx_govease", op, state="TX")
        assert not d.allowed and d.reason_code == "HARD_BLOCKED", op


@pytest.mark.parametrize("perms_factory", [
    lambda: PERM.Permissions.from_file(Path("/nonexistent/source_permissions.csv")),   # no file
    lambda: PERM.Permissions([], error="unreadable"),                                    # load error
    lambda: PERM.Permissions([]),                                                        # empty set
])
@pytest.mark.parametrize("kw", [dict(state="TX"), dict(state="TX", county="Denton"), dict(state="TX", dataset="*"),
                                dict(state="US"), dict(state=None)])
def test_govease_has_no_default_fallback(perms_factory, kw):
    d = perms_factory().authorize("tx_govease", "fetch", **kw)
    assert not d.allowed


def test_govease_denied_by_every_entry_point_helper():
    import permission_gate as PG
    import source_publication as SP
    assert not PG.allowed("tx_govease", ("fetch",), state="TX", label="t")
    for op in ("fetch", "store", "display", "link"):
        assert not SP.permitted("tx_govease", op, "TX").allowed
    import laft_status
    assert not laft_status.permission("tx_govease", "fetch", state="TX").allowed
