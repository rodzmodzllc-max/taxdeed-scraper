"""Phase 69 - the FDOR enrichment miss streak is counted per source within a
county's slice, so a run of unmatchable certificate identifiers can no longer
stop the auction rows behind them from ever being attempted.

The defect, measured in production on 2026-09-22 (docs/phase-69-fdor-
starvation.md): Escambia's unenriched slice, in the exact `id` order
fetch_county_batch() uses, was 31 certificate rows (LienHub account numbers,
never matchable in the statewide layer) followed by its 6 auction rows. With
one county-wide streak of COUNTY_MISS_STREAK = 6, every run looked up six
certificates, abandoned the county, and never reached an auction row - yet a
read-only probe showed all 6 auction rows match the layer under the
production rules. Volusia (50/50) and Santa Rosa (12/12) showed the same.

These tests replay that sequence against a fake layer. No network, no
database: requests.get / requests.patch are replaced, and the field mapping
(build_update_fields) is stubbed because scheduling is the contract here.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "enrich_property_details.py"

# Escambia's measured order (2026-09-22): 31 certificates, then A A c A A c c A c c A.
ESCAMBIA_PATTERN = "c" * 31 + "AAcAAccAccA"


@pytest.fixture()
def enrich(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "not-a-real-key")
    spec = importlib.util.spec_from_file_location("_p69_enrich", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p69_enrich"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(mod.random, "randrange", lambda *_: 0)  # window starts at row 1
    monkeypatch.setattr(mod, "build_update_fields", lambda row, attrs, centroid: {"prop_type": "x"})
    return mod


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def rows_from_pattern(county, pattern):
    """'c' -> certificate row with an account-style id the layer never has;
    'A' -> auction row whose parcel the layer holds."""
    rows = []
    for i, ch in enumerate(pattern):
        if ch == "A":
            rows.append({"id": f"{county}-a{i}", "source": "auction", "parcel": f"HIT-{i:04d}", "county": county})
        elif ch == "L":
            rows.append({"id": f"{county}-l{i}", "source": "laft", "parcel": f"HIT-{i:04d}", "county": county})
        else:
            rows.append({"id": f"{county}-c{i}", "source": "certificate", "parcel": f"11-{i:04d}-000", "county": county})
    return rows


class Harness:
    def __init__(self, mod, monkeypatch, county, rows):
        self.mod = mod
        self.rows = rows
        self.lookups = []      # every FDOR request, in order (parcel candidate)
        self.patches = []      # every PATCH (row id)

        def fake_get(url, headers=None, params=None, timeout=None):
            params = params or {}
            if "rest/v1/properties" in url:
                if params.get("select") == "county":
                    return FakeResponse([{"county": county} for _ in rows])
                if params.get("limit") == "0":
                    return FakeResponse([])  # the script's schema presence check (Phase 52 columns)
                assert "source" in params["select"], "main() needs each row's source to keep per-ledger streaks"
                return FakeResponse(rows[int(params["offset"]):int(params["offset"]) + int(params["limit"])])
            if url == mod.FDOR_ENDPOINT:
                where = params["where"]
                self.lookups.append(where)
                if "PARCEL_ID='HIT-" in where:
                    return FakeResponse({"features": [{"attributes": {"PARCEL_ID": "x"}, "centroid": {"x": -87.2, "y": 30.4}}]})
                return FakeResponse({"features": []})
            raise AssertionError(f"unexpected GET {url}")

        def fake_patch(url, headers=None, json=None, timeout=None):
            self.patches.append(url.rsplit("eq.", 1)[1])
            return FakeResponse(None, status=204)

        monkeypatch.setattr(mod.requests, "get", fake_get)
        monkeypatch.setattr(mod.requests, "patch", fake_patch)

    def tried_rows(self, prefix=""):
        """Distinct ROWS the layer was asked about (normalize_candidates()
        spends several candidate strings per row - dash-stripped, 'R'-suffixed
        - so candidates are collapsed back to their row key)."""
        keys = set()
        for where in self.lookups:
            cand = re.search(r"PARCEL_ID='([^']*)'", where).group(1)
            key = re.sub(r"[^A-Za-z0-9]", "", cand).rstrip("R")
            if key.startswith(prefix):
                keys.add(key)
        return keys


def test_p69_01_escambia_sequence_reaches_every_auction_row_in_the_slice(enrich, monkeypatch):
    """The exact production sequence. Window = first 40 of 42 rows, so the
    auction rows at positions 32, 33, 35, 36 and 39 are inside it (the 42nd
    is not). Before Phase 69: 6 certificate lookups, 0 auction rows attempted,
    0 written - on every run."""
    rows = rows_from_pattern("Escambia", ESCAMBIA_PATTERN)
    h = Harness(enrich, monkeypatch, "Escambia", rows)
    enrich.main()
    in_window_auction = [r["id"] for r in rows[:40] if r["source"] == "auction"]
    assert len(in_window_auction) == 5
    assert h.patches == in_window_auction
    # Certificates were tried exactly COUNTY_MISS_STREAK times and then skipped
    # without spending a request; each miss costs one request per candidate.
    cert_rows_tried = h.tried_rows("11")
    assert len(cert_rows_tried) == enrich.COUNTY_MISS_STREAK
    assert len(cert_rows_tried) < 31


def test_p69_02_runaway_protection_still_holds_per_ledger(enrich, monkeypatch):
    """A county where BOTH ledgers miss is still capped: no ledger is asked
    more than COUNTY_MISS_STREAK times, and the whole slice costs at most
    (number of ledgers present) x COUNTY_MISS_STREAK row lookups."""
    rows = rows_from_pattern("Leon", "c" * 20 + "A" * 20)
    for r in rows:  # make the auction rows miss too
        r["parcel"] = r["parcel"].replace("HIT-", "MISS-")
    h = Harness(enrich, monkeypatch, "Leon", rows)
    enrich.main()
    assert h.patches == []
    assert len(h.tried_rows("11")) == enrich.COUNTY_MISS_STREAK
    assert len(h.tried_rows("MISS")) == enrich.COUNTY_MISS_STREAK
    assert len(h.tried_rows()) == 2 * enrich.COUNTY_MISS_STREAK


def test_p69_03_a_hit_resets_only_its_own_ledger(enrich, monkeypatch):
    """Certificate misses accumulate independently of auction hits: after six
    certificate misses the certificate ledger is skipped even though auction
    rows keep hitting in between; the auction ledger is never skipped."""
    rows = rows_from_pattern("Lake", "cAcAcAcAcAcAcAcA")
    h = Harness(enrich, monkeypatch, "Lake", rows)
    enrich.main()
    auction_ids = [r["id"] for r in rows if r["source"] == "auction"]
    assert h.patches == auction_ids  # all 8 auction rows written
    assert len(h.tried_rows("11")) == enrich.COUNTY_MISS_STREAK  # 7th and 8th certificate skipped


def test_p69_04_certificates_still_get_their_turn_when_they_match(enrich, monkeypatch):
    """The change never skips a legitimate row: a certificate that matches
    resets the certificate streak exactly as before."""
    rows = rows_from_pattern("Duval", "cccccAccccc")
    rows[3]["parcel"] = "HIT-CERT"  # 4th certificate matches
    h = Harness(enrich, monkeypatch, "Duval", rows)
    enrich.main()
    assert set(h.patches) == {rows[3]["id"], rows[5]["id"]}
    # three misses, a hit (streak back to 0), then five more misses -> not exhausted, all tried
    assert len(h.tried_rows("11")) + len(h.tried_rows("HITCERT")) == 10


def test_p69_05_misses_remain_unstamped_and_idempotent(enrich, monkeypatch):
    """Idempotency is untouched: a miss is never PATCHed, so it is retried on
    the next run; a hit is stamped in the same PATCH as its data."""
    rows = rows_from_pattern("Volusia", "cA")
    h = Harness(enrich, monkeypatch, "Volusia", rows)
    enrich.main()
    assert h.patches == [rows[1]["id"]]


def test_p69_06_per_county_report_counts_rows_actually_looked_up(enrich, monkeypatch, capsys):
    rows = rows_from_pattern("Escambia", ESCAMBIA_PATTERN)
    Harness(enrich, monkeypatch, "Escambia", rows)
    enrich.main()
    out = capsys.readouterr().out
    # 6 certificate lookups + 5 auction lookups = 11 attempted, 5 matched; the
    # old line would have read "5/40".
    assert "  Escambia: 5/11" in out
    assert "certificate: 6 consecutive misses - skipping this ledger's remaining rows" in out
