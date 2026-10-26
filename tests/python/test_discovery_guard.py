"""Discovery, evidence-capture and probe scripts ask the permission engine
before every request (harvesters/governance/discovery_guard.py).

A refused request must never reach the network: the transport below the
guard (requests' HTTPAdapter.send, urllib's OpenerDirector handlers) fails
the test if it is ever called after a denial.
"""
from __future__ import annotations

import csv
import importlib
import io
import json
import sys
import urllib.request
import urllib.response
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from harvesters.governance import discovery_guard as DG  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402
from permission_fixtures import install as install_perms  # noqa: E402
from permission_fixtures import record  # noqa: E402

SCRIPTS = ("capture_available_sources", "capture_pioneer_statements", "capture_purchase_evidence", "capture_sc_available",
           "capture_state_sources", "capture_tn_shelby", "capture_tx_vendors", "discover_sources", "probe_fdor_starvation",
           "probe_field_fill")

IDX = [DG.Target("zz_ok", "ZZ", None, "ok.example.gov", "/list"),
       DG.Target("zz_other", "ZZ", None, "shared.example.gov", "/a"),
       DG.Target("zz_ok", "ZZ", None, "shared.example.gov", "/b"),
       DG.Target("", "ZZ", None, "nosrc.example.gov", "/")]


class _Allowed:
    allowed, reason_code = True, "ALLOWED_DOCUMENTED"


class _Denied:
    allowed, reason_code = False, "NO_RECORD"


def only(*ids):
    return lambda s, op, state, county: _Allowed() if s in ids and op == "discover" else _Denied()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(PERM, "_DEFAULT", None)
    yield
    DG.uninstall()


@pytest.fixture
def transport(monkeypatch):
    """Record every request that reaches the transport; answer 200."""
    calls = []

    def send(self, request, **kw):
        calls.append(request.url)
        r = requests.Response()
        r.status_code, r._content, r.url = 200, b"ok", request.url
        return r
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)

    class H(urllib.request.BaseHandler):
        handler_order = 1   # ahead of the proxy and HTTP(S) handlers: nothing leaves the process

        def https_open(self, req):
            calls.append(req.full_url)
            import http.client
            r = urllib.response.addinfourl(io.BytesIO(b"ok"), http.client.HTTPMessage(), req.full_url, 200)
            r.msg = "OK"
            return r
        http_open = https_open
    opener = urllib.request.build_opener(H)
    monkeypatch.setattr(urllib.request, "_opener", opener)
    return calls


# --- the decision ---------------------------------------------------------------

def test_denied_request_never_reaches_the_network(transport):
    DG.install("t", index=IDX, authorize=only(), write_report_at_exit=False)
    with pytest.raises(DG.DiscoveryDenied):
        requests.get("https://ok.example.gov/list?parcel=123")
    with pytest.raises(DG.DiscoveryDenied):
        requests.Session().post("https://ok.example.gov/list")
    with pytest.raises(DG.DiscoveryDenied):
        urllib.request.urlopen("https://ok.example.gov/list")
    assert transport == []


def test_authorized_request_still_works(transport):
    DG.install("t", index=IDX, authorize=only("zz_ok"), write_report_at_exit=False)
    assert requests.get("https://ok.example.gov/list/page2").status_code == 200
    assert urllib.request.urlopen("https://ok.example.gov/list").read() == b"ok"
    assert len(transport) == 2


@pytest.mark.parametrize("url,code", [
    ("https://unknown.example.org/x", "NO_SOURCE_FOR_HOST"),
    ("https://nosrc.example.gov/anything", "NO_SOURCE"),
    ("ftp://ok.example.gov/list", "UNSUPPORTED_URL"),
    ("not a url", "UNSUPPORTED_URL"),
])
def test_unmapped_targets_are_refused(url, code):
    g = DG.Guard("t", index=IDX, authorize=only("zz_ok", "zz_other"))
    d = g.decide(url)
    assert not d.allowed and d.reason_code == code


def test_shared_host_without_a_path_match_needs_every_source_on_it():
    g = DG.Guard("t", index=IDX, authorize=only("zz_ok"))
    assert g.decide("https://shared.example.gov/b/item").allowed          # path matches zz_ok only
    assert not g.decide("https://shared.example.gov/a").allowed            # zz_other not permitted
    assert not g.decide("https://shared.example.gov/elsewhere").allowed    # whole host -> both needed


def test_a_permission_for_another_operation_is_not_discovery(monkeypatch):
    # A real record set where zz_fetch may fetch, store and display but not discover.
    install_perms(monkeypatch, *(record(source_id="zz_fetch", jurisdiction="ZZ", operation=op)
                                 for op in ("fetch", "store", "display", "parse")), base=False)
    g = DG.Guard("t", index=[DG.Target("zz_fetch", "ZZ", None, "f.example.gov", "/")])
    d = g.decide("https://f.example.gov/list")
    assert not d.allowed and d.reason_code in ("NO_RECORD", "NOT_PERMITTED", "UNKNOWN_SOURCE")


@pytest.mark.parametrize("mutate,code", [
    ({}, None),                                                                          # in date -> allowed
    # Windows stay within an interim allowance's maximum length (210 days).
    ({"expires_on": "2020-01-01", "effective_on": "2019-07-01", "evidence_date": "2019-07-01",
      "last_verified_on": "2019-07-01"}, "EXPIRED"),
    ({"effective_on": "2099-01-01", "expires_on": "2099-06-01"}, "NOT_YET_EFFECTIVE"),
    ({"status": "BLOCKED", "evidence_type": "PROHIBITION_FOUND"}, "BLOCKED"),
    # LINK_ONLY never authorizes discovery: the record itself is refused as invalid.
    ({"status": "LINK_ONLY", "evidence_type": "TERMS_SILENT"}, "CONFIG_INVALID"),
])
def test_discover_record_states(monkeypatch, mutate, code):
    install_perms(monkeypatch, record(source_id="zz_d", jurisdiction="ZZ", operation="discover", **mutate), base=False)
    g = DG.Guard("t", index=[DG.Target("zz_d", "ZZ", None, "d.example.gov", "/")])
    d = g.decide("https://d.example.gov/")
    if code is None:
        assert d.allowed
    else:
        assert not d.allowed and d.reason_code == code


def test_invalid_governance_configuration_denies(monkeypatch):
    monkeypatch.setattr(PERM, "_DEFAULT", PERM.Permissions([], error="unreadable"))
    g = DG.Guard("t", index=[DG.Target("zz_d", "ZZ", None, "d.example.gov", "/")])
    assert not g.decide("https://d.example.gov/").allowed

    def boom(*a):
        raise RuntimeError("no governance")
    g = DG.Guard("t", index=[DG.Target("zz_d", "ZZ", None, "d.example.gov", "/")], authorize=boom)
    d = g.decide("https://d.example.gov/")
    assert not d.allowed and d.reason_code.startswith("GOVERNANCE_UNAVAILABLE")


def test_project_database_host_is_not_a_source(monkeypatch, transport):
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    DG.install("t", index=IDX, authorize=only(), write_report_at_exit=False)
    assert requests.get("https://abc.supabase.co/rest/v1/properties").status_code == 200


# --- the real repository today --------------------------------------------------

OWNER_VENDORS = {"tx_pbfcm", "tx_mvba", "tx_govease"}  # discover recorded with the owner's decision of 2026-10-26
VENDOR_HOSTS = {"www.pbfcm.com", "mvbalaw.com", "www.mvbataxsales.com", "liveauctions.govease.com"}


def test_only_owner_recorded_sources_hold_a_discover_permission():
    # Evidence capture needs an owner-recorded discover permission per source. On file: the three
    # Texas vendors the owner unblocked on 2026-10-26, and the interim one-read record for TaxSys'
    # county-held reports (whose hosts are in no index table).
    allowing = [r for r in PERM.Permissions.from_file().records if r.operation == "discover" and r.status != "BLOCKED"]
    from harvesters.otc.adapters import expansion as EX  # noqa: PLC0415 - + the new-sources sprint (2026-10-26)
    assert {r.source_id for r in allowing} == OWNER_VENDORS | {"fl_taxsys_county_held"} | set(EX.NEW_SOURCE_IDS)
    assert all(r.evidence_type == "INTERNAL_RISK_ACCEPTANCE" and r.expires_on == "2027-04-12" for r in allowing)
    g = DG.Guard("t")
    new_hosts = {t.host for t in g.index if t.source_id in EX.NEW_SOURCE_IDS}
    hosts = sorted({t.host for t in g.index})
    assert hosts and not any(g.decide(f"https://{h}/").allowed for h in hosts if h not in VENDOR_HOSTS | new_hosts)


@pytest.mark.parametrize("url", ["https://www.govease.com/", "https://countytaxsaleapp.org/",
                                 "https://taxsales.lgbs.com/api/property_sales/", "https://lienhub.com/doc/terms"])
def test_blocked_and_restricted_vendors_are_refused(url):
    assert not DG.Guard("t").decide(url).allowed


def test_index_covers_the_registry_and_configs():
    hosts = {t.host for t in DG.build_index()}
    assert "morgancounty.colorado.gov" in hosts                     # registry canonical_url
    assert any(h.endswith("arcgis.com") for h in hosts)             # expansion / parcel layers


# --- the report -----------------------------------------------------------------

def test_report_carries_no_path_query_or_values(tmp_path, transport):
    g = DG.install("t", index=IDX, authorize=only(), write_report_at_exit=False)
    for u in ("https://ok.example.gov/list?owner=JANE+DOE&parcel=123", "https://unknown.example.org/secret/path?token=abc"):
        with pytest.raises(DG.DiscoveryDenied):
            requests.get(u)
    p = g.write_report(tmp_path)
    text = p.read_text()
    for leak in ("JANE", "123", "secret", "token", "/list", "abc"):
        assert leak not in text
    data = json.loads(text)
    assert data["denied"] == 2 and data["allowed"] == 0
    assert {h["host"] for h in data["hosts"]} == {"ok.example.gov", "unknown.example.org"}


# --- every script installs the guard before doing anything else ----------------

@pytest.mark.parametrize("name", SCRIPTS)
def test_script_installs_the_guard_first(name, monkeypatch, transport):
    import permission_gate as PG
    seen = []

    def fake_install(label):
        seen.append(label)
        raise SystemExit(99)   # stop at the first statement: nothing after it ran
    monkeypatch.setattr(PG, "install_discovery_guard", fake_install)
    monkeypatch.setattr(sys, "argv", [f"{name}.py"])
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "x")
    mod = importlib.import_module(name)
    with pytest.raises(SystemExit) as e:
        try:
            mod.main()
        except TypeError:
            mod.main([])
    assert e.value.code == 99 and seen == [name] and transport == []


@pytest.mark.parametrize("name", SCRIPTS)
def test_guard_is_the_first_statement_of_main(name):
    import ast
    tree = ast.parse((ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    body = [n for n in main.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))]
    assert isinstance(body[0], ast.Import) and body[0].names[0].name == "permission_gate"
    call = body[1].value
    assert call.func.attr == "install_discovery_guard" and call.args[0].value == name
