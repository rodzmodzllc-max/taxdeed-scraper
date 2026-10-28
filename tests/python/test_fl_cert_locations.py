"""Florida tax-certificate locations (2026-10-27).

Production, read-only, 2026-10-27: Florida certificate rows lacked
coordinates in several counties. The causes, per county, and what this
change does about each:

* Hillsborough (LienHub "A" + 10-digit folio): the folio matches the FDOR
  layer's ALT_KEY exactly (rule added 2026-10-25), but the layer answers a
  share of valid queries with a transient ArcGIS error payload (code 400
  "Invalid query parameters") and one such answer abandoned the county's
  whole slice. `_query_layer` now re-asks the SAME question a bounded number
  of times; a persistent error still raises.
* Sarasota (Tax Collector PDF rows): the 10-digit account equals the layer's
  PARCEL_ID unchanged; the rows were first synced 2026-10-27 and no FDOR or
  geocoding run had reached them. No matching change is needed.
* Every geocoding match on the tax roll now records the layer's own PARCEL_ID
  (`matched_parcel_id`), so a record located by an alternate key can join a
  DOR parcel outline.
* Santa Rosa's county layer: two features sharing one PAR_NUM are AMBIGUOUS,
  never resolved by taking the first.

Every identifier here is synthetic, in the shape of the real one. Nothing is
fetched.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.boundary import fl_dor  # noqa: E402
from harvesters.enrichment import geocode as G  # noqa: E402

SCRIPT = REPO / "scripts" / "enrich_property_details.py"
TS = "2026-10-27T00:00:00+00:00"

# Synthetic identifiers, same shapes as production.
HILLS_CERT = "A0123456789"              # LienHub: "A" + 10-digit folio
HILLS_FOLIO = "0123456789"              # the layer's ALT_KEY
HILLS_PARCEL_ID = "1928000AA000000000010U"
SARASOTA_ACCOUNT = "0987654321"         # 10 digits, equals the layer's PARCEL_ID
TRANSIENT = {"error": {"code": 400, "message": "Cannot perform query. Invalid query parameters."}}


@pytest.fixture()
def enrich(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    monkeypatch.setenv("ENRICH_REPORT", str(tmp_path / "public" / "fdor-enrichment.json"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    spec = importlib.util.spec_from_file_location("_cert_loc_enrich", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cert_loc_enrich"] = mod
    spec.loader.exec_module(mod)
    sleeps = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(mod.random, "randrange", lambda *_: 0)
    monkeypatch.setattr(mod, "_permitted", lambda *a, **k: True)
    mod._sleeps = sleeps
    return mod


class Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def layer(monkeypatch, mod, answers):
    """answers: where-key ("PARCEL_ID:x" / "ALT_KEY:x") -> list of payloads
    returned in order (the last one repeats). Unlisted keys: no feature."""
    asked = []

    def fake_get(url, params=None, timeout=None, headers=None):
        assert url == mod.FDOR_ENDPOINT
        m = re.search(r"(PARCEL_ID|ALT_KEY)='([^']*)' AND CO_NO=(\d+)", params["where"])
        key = f"{m.group(1)}:{m.group(2)}"
        asked.append((key, params["where"]))
        seq = answers.get(key)
        if not seq:
            return Resp({"features": []})
        n = sum(1 for k, _ in asked if k == key) - 1
        return Resp(seq[min(n, len(seq) - 1)])

    monkeypatch.setattr(mod.requests, "get", fake_get)
    return asked


def feature(parcel_id, alt_key="", lat=27.9, lng=-82.4):
    return {"features": [{"attributes": {"PARCEL_ID": parcel_id, "ALT_KEY": alt_key, "JV": 10000},
                          "centroid": {"x": lng, "y": lat}}]}


# --- transient layer errors ------------------------------------------------------

def test_a_transient_error_payload_is_re_asked_unchanged_and_the_answer_used(enrich, monkeypatch):
    asked = layer(monkeypatch, enrich, {f"ALT_KEY:{HILLS_FOLIO}": [TRANSIENT, TRANSIENT, feature(HILLS_PARCEL_ID, HILLS_FOLIO)]})
    attrs, centroid, cand = enrich.lookup_fdor("Hillsborough", HILLS_CERT)
    assert cand == enrich.ALT_KEY_PREFIX + HILLS_FOLIO and attrs["PARCEL_ID"] == HILLS_PARCEL_ID
    alt = [w for k, w in asked if k.startswith("ALT_KEY:")]
    assert len(alt) == 3 and len(set(alt)) == 1          # the question never changes between attempts
    assert enrich.LAYER_RETRY_STATS["recovered"] == 1
    assert [s for s in enrich._sleeps if s] == [enrich.FDOR_RETRY_BACKOFF_SECONDS, 2 * enrich.FDOR_RETRY_BACKOFF_SECONDS]


def test_a_persistent_error_still_raises_after_the_bounded_attempts(enrich, monkeypatch):
    asked = layer(monkeypatch, enrich, {f"PARCEL_ID:{SARASOTA_ACCOUNT}": [TRANSIENT]})
    with pytest.raises(enrich.FdorUnavailable):
        enrich.lookup_fdor("Sarasota", SARASOTA_ACCOUNT)
    assert len(asked) == enrich.FDOR_LAYER_ATTEMPTS
    assert enrich.LAYER_RETRY_STATS["exhausted"] == 1


def test_a_retry_never_turns_a_miss_into_a_match(enrich, monkeypatch):
    # An error, then an empty answer: a miss, not a match and not an error.
    layer(monkeypatch, enrich, {f"PARCEL_ID:{SARASOTA_ACCOUNT}": [TRANSIENT, {"features": []}]})
    assert enrich.lookup_fdor("Sarasota", SARASOTA_ACCOUNT) == (None, None, None)


def test_a_retried_ambiguous_answer_stays_ambiguous(enrich, monkeypatch):
    two = {"features": [{"attributes": {"PARCEL_ID": "X", "ALT_KEY": HILLS_FOLIO}},
                        {"attributes": {"PARCEL_ID": "Y", "ALT_KEY": HILLS_FOLIO}}]}
    layer(monkeypatch, enrich, {f"ALT_KEY:{HILLS_FOLIO}": [TRANSIENT, two]})
    assert enrich.lookup_fdor("Hillsborough", HILLS_CERT) == (None, None, enrich.AMBIGUOUS_MATCH)


def test_sarasota_tax_collector_account_matches_parcel_id_on_the_first_spelling(enrich, monkeypatch):
    asked = layer(monkeypatch, enrich, {f"PARCEL_ID:{SARASOTA_ACCOUNT}": [feature(SARASOTA_ACCOUNT, lat=27.3, lng=-82.5)]})
    attrs, centroid, cand = enrich.lookup_fdor("Sarasota", SARASOTA_ACCOUNT)
    assert cand == SARASOTA_ACCOUNT and centroid == {"x": -82.5, "y": 27.3}
    assert [k for k, _ in asked] == [f"PARCEL_ID:{SARASOTA_ACCOUNT}"]
    assert "CO_NO=68" in asked[0][1]                     # county-scoped


def test_the_run_summary_counts_recovered_layer_errors(enrich, monkeypatch, capsys):
    rows = [{"id": "h1", "source": "certificate", "parcel": HILLS_CERT, "county": "Hillsborough", "address": "x"}]

    def fake_get(url, headers=None, params=None, timeout=None):
        params = params or {}
        if "rest/v1/properties" in url:
            if params.get("select") == "county":
                return Resp([{"county": "Hillsborough"}])
            return Resp([] if "source.eq.laft" in params.get("and", "") else rows)
        m = re.search(r"(PARCEL_ID|ALT_KEY)='([^']*)'", params["where"])
        if m.group(1) == "ALT_KEY":
            fake_get.n += 1
            return Resp(TRANSIENT if fake_get.n == 1 else feature(HILLS_PARCEL_ID, HILLS_FOLIO))
        return Resp({"features": []})
    fake_get.n = 0
    patches = []
    monkeypatch.setattr(enrich.requests, "get", fake_get)
    monkeypatch.setattr(enrich.requests, "patch", lambda url, headers=None, json=None, timeout=None: (patches.append(json), Resp(None))[1])
    enrich.main()
    out = capsys.readouterr().out
    assert "layer errors recovered by a retry 1" in out and "source unavailable 0" in out
    assert len(patches) == 1 and patches[0]["latitude"] == 27.9
    entry = patches[0]["field_provenance"]["latitude"]
    assert entry["matched_parcel_id"] == HILLS_PARCEL_ID and entry["matched_field"] == "ALT_KEY"
    assert HILLS_CERT not in out and HILLS_FOLIO not in out   # counts only in the log


# --- Santa Rosa county layer: ambiguity ----------------------------------------------

def test_santa_rosa_two_features_for_one_par_num_are_ambiguous(enrich, monkeypatch):
    two = {"features": [{"attributes": {"PAR_NUM": "011N270000001000000"}, "centroid": {"x": -87.0, "y": 30.6}},
                        {"attributes": {"PAR_NUM": "011N270000001000000"}, "centroid": {"x": -87.1, "y": 30.7}}]}
    seen = []

    def fake_get(url, params=None, timeout=None, headers=None):
        seen.append(params)
        return Resp(two)
    monkeypatch.setattr(enrich.requests, "get", fake_get)
    assert enrich.lookup_santa_rosa_gis("011N270000001000000") == (None, None, enrich.AMBIGUOUS_MATCH)
    assert seen[0]["resultRecordCount"] == "2"


# --- geocoding provenance carries the layer's PARCEL_ID ---------------------------------

def test_geocoding_records_the_layer_parcel_id_so_an_outline_can_join(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    from scripts import geocode_authoritative as GA
    import scripts.enrich_property_details as EP
    monkeypatch.setattr(EP, "lookup_fdor", lambda county, parcel: (
        {"PARCEL_ID": HILLS_PARCEL_ID, "ALT_KEY": HILLS_FOLIO}, {"x": -82.4, "y": 27.9}, EP.ALT_KEY_PREFIX + HILLS_FOLIO))
    row = {"id": "h1", "state": "FL", "county": "Hillsborough", "source": "certificate", "status": "active",
           "parcel": HILLS_CERT, "latitude": None, "longitude": None, "field_provenance": {}}
    lk = GA.fl_lookup(G.FDOR_SOURCE, row)
    assert (lk.status, lk.matched_identifier, lk.matched_field, lk.parcel_id) == ("MATCHED", HILLS_FOLIO, "ALT_KEY", HILLS_PARCEL_ID)
    action, fields = G.decide(row, G.FDOR_SOURCE, lk, allow_upgrade=False, recorded_at=TS)
    assert action == "write" and fields["field_provenance"]["latitude"]["matched_parcel_id"] == HILLS_PARCEL_ID
    after = dict(row, **fields)
    assert fl_dor.nal_parcel_id(after) == (HILLS_PARCEL_ID, "")


def test_a_county_layer_match_records_no_tax_roll_parcel_id():
    lk = G.Lookup("MATCHED", 30.6, -87.0, "011N270000001000000", "PAR_NUM", parcel_id="")
    action, fields = G.decide({"state": "FL", "county": "Santa Rosa", "field_provenance": {}}, G.SANTA_ROSA_SOURCE, lk,
                              allow_upgrade=False, recorded_at=TS)
    assert action == "write" and "matched_parcel_id" not in fields["field_provenance"]["latitude"]


def test_certificate_rows_are_geocoding_candidates_from_the_tax_roll():
    for county, parcel, sid in (("Sarasota", SARASOTA_ACCOUNT, "fl_sarasota_tc_certificates"),
                                ("Hillsborough", HILLS_CERT, "fl_lienhub_certificates")):
        cls, src = G.plan_row({"id": "c", "state": "FL", "county": county, "source": "certificate",
                               "ledger_type": "lien", "status": "active", "parcel": parcel, "source_id": sid,
                               "latitude": None, "longitude": None, "field_provenance": {}})
        assert (cls, src.source_id) == ("MISSING", "fl_fdor_cadastral")


# --- 2026-10-28: certificate identifiers that name no land parcel -------------
# Synthetic identifiers in the real shapes; nothing is fetched.
WALTON_MINERAL = "07-2N-B3-MINR0-001-0000"     # Walton mineral-rights account
WALTON_PARCEL = "07-2N-23-12345-001-0010"      # an ordinary Walton parcel, same dashes


def _cert(**kw):
    base = {"id": "c1", "state": "FL", "county": "Walton", "ledger_type": "lien", "source": "certificate",
            "status": "active", "parcel": WALTON_MINERAL, "latitude": None, "longitude": None,
            "field_provenance": {}}
    base.update(kw)
    return base


def test_walton_mineral_rights_account_is_not_a_parcel():
    assert G.non_parcel_reason("FL", "Walton", WALTON_MINERAL)
    assert G.non_parcel_reason("FL", "Walton", WALTON_MINERAL.lower())
    assert G.plan_row(_cert()) == ("NOT_A_PARCEL", None)
    assert "NOT_A_PARCEL" in G.PLAN_CLASSES


def test_ordinary_walton_parcel_is_still_looked_up():
    assert G.non_parcel_reason("FL", "Walton", WALTON_PARCEL) is None
    cls, src = G.plan_row(_cert(parcel=WALTON_PARCEL))
    assert cls == "MISSING" and src.source_id == "fl_fdor_cadastral"


def test_mineral_shape_is_scoped_to_walton_only():
    # The same text in another county is an ordinary identifier lookup.
    assert G.non_parcel_reason("FL", "Okaloosa", WALTON_MINERAL) is None
    assert G.plan_row(_cert(county="Okaloosa"))[0] == "MISSING"


def test_shapes_shared_with_real_parcels_are_never_skipped():
    # Santa Rosa "...M", Volusia 12-digit and Alachua "ddddd ddd ddd" numbers
    # share their shape with parcels that do match: they stay lookups.
    assert G.plan_row(_cert(county="Santa Rosa", parcel="123N450000001000020M"))[0] == "MISSING"
    assert G.plan_row(_cert(county="Volusia", parcel="123456000781"))[0] == "MISSING"
    assert G.plan_row(_cert(county="Alachua", parcel="98765 432 101"))[0] == "MISSING"


def test_not_a_parcel_rows_cost_no_lookup():
    from harvesters.enrichment import priority as PR
    from scripts import geocode_authoritative as GA

    calls = []
    rep = GA.run([_cert()], mode="dry-run", allow_upgrade=False, limit=None, ctx=PR.Context(),
                 fl_lookup_fn=lambda src, r: calls.append(r) or G.Lookup("NO_MATCH"))
    assert calls == []
    assert rep["plan"] == {"NOT_A_PARCEL": 1} and rep["candidates"] == 0
