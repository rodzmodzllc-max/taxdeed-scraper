"""Tests for Phase 68 - the Census geocoder builds its query from the row's
own state, keeps whatever city/ZIP context the address carries, invents
nothing for rows that lack it, and only writes a coordinate the Census
answer has confirmed sits in the row's own state AND county.

All three defects were measured in production before this was written (see
docs/phase-68-geocoder-state-context.md):

  A. Every query ended in a literal ", FL" - Texas rows were asked for as
     Florida addresses.
  B. "<county> County" was passed in the city slot, which the Census parser
     cannot resolve, so bare street lines never matched and the whole
     250-row budget went to rows that could never succeed.
  C. Nothing checked the answer: 2 of 48 geocoder-written Florida rows sat
     in the wrong county (one in Nevada).

No network and no database. requests.get / requests.patch are replaced with
fakes that record the exact query parameters and PATCH bodies, which is the
contract under test.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import urllib.parse

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "geocode_properties.py"


def _load(monkeypatch, dry_run=False):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    if dry_run:
        monkeypatch.setenv("GEOCODE_DRY_RUN", "1")
    else:
        monkeypatch.delenv("GEOCODE_DRY_RUN", raising=False)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    spec = importlib.util.spec_from_file_location("_p68_geocode", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p68_geocode"] = mod
    spec.loader.exec_module(mod)
    mod.time.sleep = lambda *_: None
    return mod


@pytest.fixture()
def geo(monkeypatch):
    return _load(monkeypatch)


class FakeResponse:
    def __init__(self, payload, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def census_match(lat, lng, state, county_basename, matched="MATCHED"):
    """Shape of one entry in result.addressMatches from the
    geographies/onelineaddress endpoint."""
    return {
        "matchedAddress": matched,
        "coordinates": {"x": lng, "y": lat},
        "addressComponents": {"state": state, "zip": "00000", "city": "X"},
        "geographies": {"Counties": [{"BASENAME": county_basename, "NAME": f"{county_basename} County"}]},
    }


class Harness:
    """Wires fake Supabase + Census responses into the module and records
    every outbound call."""

    def __init__(self, mod, monkeypatch):
        self.mod = mod
        self.supabase_rows = []          # rows returned by the FIRST tier fetch
        self.supabase_rows_tier2 = []    # rows returned by the second tier
        self.census = {}                 # query string -> list of matches
        self.fetch_params = []
        self.census_queries = []
        self.patches = []

        def fake_get(url, headers=None, params=None, timeout=None):
            if "rest/v1/properties" in url:
                self.fetch_params.append(dict(params or {}))
                tier = params.get("and", "")
                if mod.ADDRESS_NO_CONTEXT_FILTER in tier:
                    return FakeResponse(self.supabase_rows_tier2)
                return FakeResponse(self.supabase_rows)
            assert url.startswith(mod.CENSUS_ENDPOINT), url
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            query = qs["address"][0]
            self.census_queries.append(qs)
            return FakeResponse({"result": {"addressMatches": self.census.get(query, [])}})

        def fake_patch(url, headers=None, json=None, timeout=None):
            self.patches.append((url, dict(json)))
            return FakeResponse(None, status=204)

        monkeypatch.setattr(mod.requests, "get", fake_get)
        monkeypatch.setattr(mod.requests, "patch", fake_patch)


@pytest.fixture()
def harness(geo, monkeypatch):
    return Harness(geo, monkeypatch)


# ===========================================================================
# 1. Florida address -> Florida query (state from the row, county never sent)
# ===========================================================================


def test_p68_01_florida_row_queries_florida_without_county(geo):
    assert geo.build_query("3201 37TH ST W", "FL") == "3201 37TH ST W, FL"
    assert "County" not in geo.build_query("3201 37TH ST W", "FL")


def test_p68_01b_florida_query_is_sent_verbatim_to_census(harness):
    geo = harness.mod
    harness.supabase_rows = [{"id": "a1", "address": "3201 37TH ST W", "county": "Lee", "state": "FL"}]
    geo.main()
    assert harness.census_queries[0]["address"] == ["3201 37TH ST W, FL"]
    assert harness.census_queries[0]["benchmark"] == [geo.CENSUS_BENCHMARK]
    assert harness.census_queries[0]["vintage"] == [geo.CENSUS_VINTAGE]


# ===========================================================================
# 2. Texas address -> Texas query
# ===========================================================================


def test_p68_02_texas_row_queries_texas_never_florida(geo):
    q = geo.build_query("14107 HORSESHOE TRL", "TX")
    assert q == "14107 HORSESHOE TRL, TX"
    assert "FL" not in q


def test_p68_02b_texas_row_reaches_census_as_texas(harness):
    geo = harness.mod
    harness.supabase_rows = [{"id": "t1", "address": "14107 HORSESHOE TRL", "county": "Dallas", "state": "TX"}]
    geo.main()
    (qs,) = harness.census_queries
    assert qs["address"] == ["14107 HORSESHOE TRL, TX"]
    assert "FL" not in qs["address"][0]


def test_p68_02c_lowercase_state_is_normalised_not_defaulted(geo):
    assert geo.build_query("1 MAIN ST", "tx") == "1 MAIN ST, TX"


# ===========================================================================
# 3. Address with city/ZIP -> complete query, context preserved
# ===========================================================================


def test_p68_03_newline_city_zip_line_becomes_comma_context(geo):
    q = geo.build_query("10697 WILD TAMARIND DR\nTAMPA    33647", "FL")
    assert q == "10697 WILD TAMARIND DR, TAMPA 33647, FL"


def test_p68_03b_trailing_zip_is_kept_and_state_appended(geo):
    assert geo.build_query("321 GARFIELD DR 32505", "FL") == "321 GARFIELD DR 32505, FL"


def test_p68_03c_address_that_already_names_the_state_is_not_doubled(geo):
    for addr in ("1824 Dixie Ln, Holiday FL 34690", "17948 US Hwy 90, Live Oak, FL", "LAKE WALES, FL- 33898"):
        q = geo.build_query(addr, "FL")
        assert q.count(" FL") == 1, q
        assert not q.endswith(", FL, FL")
    # Texas rows from the LGBS harvester already carry ", TX 77591-3807".
    q = geo.build_query("VACANT LOT AT 322 S FULTON ST, Texas City, TX 77591-3807", "TX")
    assert q == "VACANT LOT AT 322 S FULTON ST, Texas City, TX 77591-3807"


def test_p68_03d_context_rows_are_fetched_before_bare_rows(harness):
    """The priority tier is comma OR 5-digit ZIP; the second tier is its
    exact complement, so ZIP-only addresses no longer sit behind junk."""
    geo = harness.mod
    harness.supabase_rows = []  # tier 1 empty -> tier 2 must be asked for the rest
    harness.supabase_rows_tier2 = []
    geo.main()
    first, second = harness.fetch_params
    assert first["and"] == '(address.not.is.null,or(address.like."*,*",address.match."[0-9]{5}"))'
    assert second["and"] == '(address.not.is.null,address.not.like."*,*",address.not.match."[0-9]{5}")'
    # Both tiers select the state so build_query never has to assume one.
    assert first["select"] == "id,address,county,state"
    assert second["select"] == "id,address,county,state"


# ===========================================================================
# 4. Missing city/ZIP -> safe fallback: nothing invented, county-verified only
# ===========================================================================


def test_p68_04_bare_street_is_not_given_an_invented_city(geo):
    q = geo.build_query("3703 40TH ST SW", "FL")
    assert q == "3703 40TH ST SW, FL"


def test_p68_04b_bare_street_match_written_only_when_county_verifies(harness):
    geo = harness.mod
    harness.supabase_rows = [
        {"id": "ok", "address": "7791 NW 46 ST", "county": "Miami-Dade", "state": "FL"},
        {"id": "wrong-county", "address": "644 PALM BEACH ST", "county": "Leon", "state": "FL"},
        {"id": "no-geo", "address": "1 UNVERIFIABLE RD", "county": "Lee", "state": "FL"},
    ]
    harness.census = {
        "7791 NW 46 ST, FL": [census_match(25.8153, -80.3247, "FL", "Miami-Dade")],
        # The real production case: Leon County row answered with an Osceola point.
        "644 PALM BEACH ST, FL": [census_match(28.2409, -81.2048, "FL", "Osceola")],
        # A match with coordinates but no county geography must NOT be trusted.
        "1 UNVERIFIABLE RD, FL": [{
            "matchedAddress": "1 UNVERIFIABLE RD", "coordinates": {"x": -81.9, "y": 26.6},
            "addressComponents": {"state": "FL"}, "geographies": {},
        }],
    }
    geo.main()
    assert [u for u, _ in harness.patches] == ["https://example.test/rest/v1/properties?id=eq.ok"]
    assert harness.patches[0][1] == {"latitude": 25.8153, "longitude": -80.3247}


def test_p68_04c_first_verifying_candidate_wins_when_census_returns_several(harness):
    geo = harness.mod
    harness.supabase_rows = [{"id": "multi", "address": "10 OAK ST", "county": "Lee", "state": "FL"}]
    harness.census = {"10 OAK ST, FL": [
        census_match(40.84, -115.79, "NV", "Elko"),          # the Nevada answer, rejected
        census_match(27.1, -82.4, "FL", "Sarasota"),         # right state, wrong county
        census_match(26.62, -81.87, "FL", "Lee"),            # verified
    ]}
    geo.main()
    assert harness.patches == [("https://example.test/rest/v1/properties?id=eq.multi", {"latitude": 26.62, "longitude": -81.87})]


def test_p68_04d_verify_match_normalises_county_spellings(geo):
    assert geo.verify_match(census_match(0, 0, "FL", "St. Lucie"), "FL", "St. Lucie") == (True, "verified")
    assert geo.verify_match(census_match(0, 0, "FL", "Miami-Dade"), "FL", "Miami-Dade") == (True, "verified")
    assert geo.verify_match(census_match(0, 0, "FL", "DeSoto"), "FL", "DeSoto") == (True, "verified")
    # NAME-only payloads ("Lee County") still verify.
    m = census_match(0, 0, "FL", "Lee")
    del m["geographies"]["Counties"][0]["BASENAME"]
    assert geo.verify_match(m, "FL", "Lee") == (True, "verified")
    assert geo.verify_match(census_match(0, 0, "FL", "Collier"), "FL", "Lee") == (False, "county-mismatch")


# ===========================================================================
# 5. A Texas record can never acquire a Florida state/county through this step
# ===========================================================================


def test_p68_05_texas_row_answered_with_a_florida_point_is_rejected(harness):
    geo = harness.mod
    harness.supabase_rows = [{"id": "tx", "address": "950 Birchwood Dr", "county": "Dallas", "state": "TX"}]
    # The parser's "best nationwide guess" lands in Florida - must not be written.
    harness.census = {"950 Birchwood Dr, TX": [census_match(28.0, -82.0, "FL", "Hillsborough")]}
    geo.main()
    assert harness.patches == []


def test_p68_05b_patch_body_only_ever_carries_coordinates(harness):
    geo = harness.mod
    harness.supabase_rows = [{"id": "tx2", "address": "4418 FIR ST", "county": "Nueces", "state": "TX"}]
    harness.census = {"4418 FIR ST, TX": [census_match(27.77, -97.53, "TX", "Nueces")]}
    geo.main()
    (_, body), = harness.patches
    assert set(body) == {"latitude", "longitude"}
    assert "state" not in body and "county" not in body


def test_p68_05c_row_without_state_is_skipped_never_assumed_florida(harness):
    geo = harness.mod
    harness.supabase_rows = [{"id": "nostate", "address": "1 MAIN ST", "county": "Lee", "state": None}]
    geo.main()
    assert harness.census_queries == []
    assert harness.patches == []
    with pytest.raises(ValueError):
        geo.build_query("1 MAIN ST", "")


def test_p68_05d_state_mismatch_beats_a_matching_county_name(geo):
    # Lee County exists in both Florida and Texas - the state check must run first.
    assert geo.verify_match(census_match(30.3, -96.9, "TX", "Lee"), "FL", "Lee") == (False, "state-mismatch")


# ===========================================================================
# Existing guarantees that must survive: never overwrite, dry run writes nothing
# ===========================================================================


def test_p68_06_every_fetch_targets_only_null_coordinates(harness):
    harness.mod.main()
    assert harness.fetch_params, "no fetch happened"
    for params in harness.fetch_params:
        assert params["latitude"] == "is.null"
        assert "state" not in params  # no state FILTER: FL and TX rows alike


def test_p68_07_dry_run_evaluates_everything_and_writes_nothing(monkeypatch):
    geo = _load(monkeypatch, dry_run=True)
    h = Harness(geo, monkeypatch)
    h.supabase_rows = [{"id": "d1", "address": "7791 NW 46 ST", "county": "Miami-Dade", "state": "FL"}]
    h.census = {"7791 NW 46 ST, FL": [census_match(25.8153, -80.3247, "FL", "Miami-Dade")]}
    geo.main()
    assert h.census_queries, "dry run must still exercise the geocoder"
    assert h.patches == []


def test_p68_08_no_match_leaves_row_untouched(harness):
    geo = harness.mod
    harness.supabase_rows = [{"id": "nm", "address": "UNKNOWN", "county": "Santa Rosa", "state": "FL"}]
    geo.main()
    assert harness.patches == []
