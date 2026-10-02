"""Regression tests for the three data-quality findings fixed before merge
(2026-10-01):

1. Louisiana: the lifecycle read every row of a state with `limit=10000`,
   which PostgREST's max-rows silently capped at 1,000 - 9,334 of East Baton
   Rouge's 10,334 rows were never matched. `Api.get_all()` pages by id.
2. Florida certificates: last_seen_at is stamped only for counties the
   harvester's own status file marks COMPLETE / EMPTY; a source-unavailable
   or incomplete read stamps nothing and closes nothing.
3. Texas: LGBS / RealAuction are manual-only; the freshness report says so
   and never ages them by the clock or invents a read.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import laft_lifecycle as L  # noqa: E402
import stamp_seen as S  # noqa: E402
import unit_freshness as U  # noqa: E402

MAX_ROWS = 1000  # PostgREST max-rows on the production project


class CappedApi(L.Api):
    """An Api whose GET behaves like PostgREST with max-rows = 1000: honours
    order / limit / offset, never returns more than MAX_ROWS."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def get(self, query):
        self.queries.append(query)
        q = parse_qs(query)
        data = [r for r in self.rows
                if all(r.get(k) == v[0][3:] for k, v in q.items() if k in ("state", "source") and v[0].startswith("eq."))]
        if "order" in q:
            assert q["order"] == ["id.asc"]
            data = sorted(data, key=lambda r: r["id"])
        offset = int(q.get("offset", ["0"])[0])
        limit = min(int(q.get("limit", [str(MAX_ROWS)])[0]), MAX_ROWS)
        return [dict(r) for r in data[offset:offset + limit]]


def _la_rows(n):
    # Shuffled ids so the result order depends on the ORDER BY, not insertion.
    ids = list(range(1, n + 1))
    ids = ids[::2] + ids[1::2]
    return [{"id": i, "state": "LA", "source": "laft", "county": "East Baton Rouge", "case_no": f"C{i:06d}",
             "parcel": f"P{i}", "status": "active", "last_seen_at": None, "first_seen_at": None} for i in ids]


# ---------------------------------------------------------------- 1. Louisiana

def test_get_all_reads_a_population_over_max_rows_exactly_once():
    api = CappedApi(_la_rows(10334))
    got = api.get_all("state=eq.LA&source=eq.laft&select=id")
    ids = [r["id"] for r in got]
    assert len(ids) == 10334
    assert len(set(ids)) == 10334                         # no duplicates
    assert ids == sorted(ids)                             # deterministic order
    assert set(ids) == set(range(1, 10335))               # nothing skipped
    assert len(api.queries) == 11                         # 10 full pages + 1 short page
    assert all("order=id.asc" in q and "limit=1000" in q for q in api.queries)


def test_get_all_exact_multiple_of_page_ends_on_an_empty_page():
    api = CappedApi(_la_rows(2000))
    assert len(api.get_all("state=eq.LA")) == 2000
    assert len(api.queries) == 3


def test_fetch_state_rows_returns_every_louisiana_row():
    api = CappedApi(_la_rows(10334))
    rows = L.fetch_state_rows(api, "LA", ["East Baton Rouge"])
    assert len(rows) == 10334
    assert len({(r["county"], r["case_no"]) for r in rows}) == 10334
    # The source-list fields the lifecycle reads are preserved untouched.
    assert all(r["parcel"] == f"P{r['id']}" for r in rows)


def test_no_lifecycle_read_relies_on_a_large_limit():
    src = (ROOT / "scripts/laft_lifecycle.py").read_text(encoding="utf-8")
    assert not re.search(r"limit=(\d{5,}|[2-9]\d{3})", src), "a single read above max-rows is silently truncated"


# ------------------------------------------------------- 2. FL certificate stamp

class _Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run_stamp(tmp_path, monkeypatch, harvest, status):
    sent = []

    def fake_urlopen(req, timeout=0):
        sent.append((req.get_method(), req.full_url, json.loads(req.data)))
        q = parse_qs(urlsplit(req.full_url).query)
        n = len(q["case_no"][0][4:-1].split('","'))
        return _Resp(json.dumps([{}] * n).encode())

    monkeypatch.setattr(S.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    hp, sp = tmp_path / "harvest_certificates.json", tmp_path / "harvest_certificates_status.json"
    if harvest is not None:
        hp.write_text(json.dumps(harvest), encoding="utf-8")
    if status is not None:
        sp.write_text(json.dumps(status), encoding="utf-8")
    S.main(["--state", "FL", "--source", "certificate", "--harvest", str(hp), "--case-key", "case_no", "--status", str(sp)])
    return sent


def test_a_successful_certificate_read_records_the_read_timestamp(tmp_path, monkeypatch, capsys):
    harvest = [{"county": "Lee", "case_no": "100"}, {"county": "Lee", "case_no": "101"}, {"county": "Polk", "case_no": "7"}]
    status = [{"county": "Lee", "status": "COMPLETE", "rowCount": 2}, {"county": "Polk", "status": "COMPLETE", "rowCount": 1}]
    sent = _run_stamp(tmp_path, monkeypatch, harvest, status)
    assert [m for m, _, _ in sent] == ["PATCH", "PATCH"]
    for _, url, body in sent:
        assert set(body) == {"last_seen_at"}                       # a read stamp only: never status / closed
        q = parse_qs(urlsplit(url).query)
        assert q["state"] == ["eq.FL"] and q["source"] == ["eq.certificate"]
    assert "3 stored row(s) stamped" in capsys.readouterr().out


def test_a_single_certificate_serialized_as_an_object_is_still_stamped(tmp_path, monkeypatch):
    # PowerShell ConvertTo-Json writes a one-element array as a bare object.
    sent = _run_stamp(tmp_path, monkeypatch, {"county": "Lee", "case_no": "100"}, {"county": "Lee", "status": "COMPLETE"})
    assert len(sent) == 1


def test_source_unavailable_run_stamps_nothing_and_closes_nothing(tmp_path, monkeypatch, capsys):
    # The 2026-10-01 production run: LienHub 403 on all 32 counties, no harvest file.
    status = [{"county": c, "status": "INCOMPLETE", "rowCount": 0, "reason": "403 (Forbidden)"} for c in ("Lee", "Polk")]
    assert _run_stamp(tmp_path, monkeypatch, None, status) == []
    assert "nothing stamped" in capsys.readouterr().out


def test_incomplete_county_rows_are_not_stamped_even_if_present(tmp_path, monkeypatch):
    harvest = [{"county": "Lee", "case_no": "100"}, {"county": "Polk", "case_no": "7"}]
    status = [{"county": "Lee", "status": "COMPLETE"}, {"county": "Polk", "status": "INCOMPLETE"}]
    sent = _run_stamp(tmp_path, monkeypatch, harvest, status)
    assert len(sent) == 1 and parse_qs(urlsplit(sent[0][1]).query)["county"] == ["eq.Lee"]


def test_missing_status_file_fails_closed(tmp_path, monkeypatch):
    assert _run_stamp(tmp_path, monkeypatch, [{"county": "Lee", "case_no": "100"}], None) == []


def test_stamp_seen_never_writes_a_status():
    src = (ROOT / "scripts/stamp_seen.py").read_text(encoding="utf-8")
    assert '{"last_seen_at": seen_at}' in src
    assert "notfound" not in src and '"status":' not in src


# ------------------------------------------------------------------ 3. Texas

def _jobs():
    return yaml.safe_load((ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))["jobs"]


def test_texas_job_is_manual_only_and_the_freshness_set_matches():
    texas = _jobs()["texas"]
    assert "github.event_name == 'workflow_dispatch'" in texas["if"]
    run = "\n".join(s.get("run", "") for s in texas["steps"])
    assert "texas_harvester.py" in run
    # No scheduled job runs the Texas harvester.
    for name, job in _jobs().items():
        if name != "texas":
            assert "texas_harvester.py" not in "\n".join(s.get("run", "") for s in job.get("steps", []))
    assert set(U.MANUAL_ONLY_SOURCES) == {"tx_lgbs", "tx_realauction"}


def test_manual_only_units_are_never_stale_by_the_clock_and_keep_their_read():
    old = "2026-09-29T16:37:00+00:00"
    record = {
        "TX|tx_lgbs|Harris": {"state": "TX", "source_id": "tx_lgbs", "county": "Harris", "ledgers": "AUCTIONS|AVAILABLE",
                              "last_attempt_at": old, "last_attempt_status": "COMPLETE", "last_success_at": old},
        "FL|fl_laft|Lee": {"state": "FL", "source_id": "fl_laft", "county": "Lee", "ledgers": "AVAILABLE",
                           "last_attempt_at": old, "last_attempt_status": "COMPLETE", "last_success_at": old},
    }
    rep = U.public_report(record, {}, at="2026-10-01T20:00:00+00:00")
    tx = next(u for u in rep["units"] if u["source_id"] == "tx_lgbs")
    fl = next(u for u in rep["units"] if u["source_id"] == "fl_laft")
    assert tx["manual_only"] is True and tx["stale"] is False
    assert tx["last_success_at"] == old                   # never advanced or invented
    assert "manual_only" not in fl and fl["stale"] is True
    assert rep["by_ledger"]["AUCTIONS"] == {"units": 1, "current": 0, "stale": 0, "failing": 0, "backoff": 0, "source_unavailable": 0, "manual_only": 1}
    assert rep["by_ledger"]["AVAILABLE"]["manual_only"] == 1 and rep["by_ledger"]["AVAILABLE"]["current"] == 1
    assert "tx_lgbs" in rep["manual_only_sources"]
