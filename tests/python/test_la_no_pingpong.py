"""Louisiana: the sync and the lifecycle no longer rewrite each other (2026-10-26).

Production overload: every `laft` run rewrote Louisiana's ~4,500 active rows
TWICE - scripts/sync_state_inventory.py upserted each row with the adapter's
otc_provenance / list_url / document_url, then scripts/laft_lifecycle.py
(run with --no-fresh-guard) PATCHed each row back to its own values, which
always carried a new retrieved_at. The two writers ping-ponged.

These tests run the REAL harvest -> sync -> lifecycle path, twice and more,
against an in-memory PostgREST `properties` table (FakeTable below), and
count the rows each step writes:

  * run 1 writes every row (sync inserts, lifecycle adds its provenance and
    the verified acquisition evidence);
  * run 2 on the same list writes NOTHING;
  * a run after the stored last_seen_at aged past write_diff.FRESH_HOURS
    re-stamps each row once (the sync) and nothing else;
  * a new row is written by both steps on the run it first appears, with its
    acquisition evidence; a changed row is written once.

Counts only; the fixture rows are synthetic (tests/python/fixtures/louisiana).
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(1, str(REPO))

import harvest_state_inventory as HSI  # noqa: E402
import laft_lifecycle as LL  # noqa: E402
import rest_pages as RP  # noqa: E402
import source_publication as SP  # noqa: E402
import sync_state_inventory as SYNC  # noqa: E402
import write_diff as WD  # noqa: E402
from harvesters.otc.adapters import louisiana as LA  # noqa: E402

FIX = REPO / "tests/python/fixtures/louisiana"
BASE = "https://fake.supabase.co"
IDENTITY = ("state", "source", "county", "case_no")


# ------------------------------------------------------------ fake PostgREST

def _split_list(text: str) -> list[str]:
    inner = text[1:-1] if text.startswith("(") and text.endswith(")") else text
    out, cur, quoted, i = [], "", False, 0
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner):
            cur += inner[i + 1]
            i += 2
            continue
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            out.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    out.append(cur)
    return out


def _cmp(a, b) -> int:
    ta, tb = WD._ts(a), WD._ts(b)
    if ta is not None and tb is not None:
        return (ta > tb) - (ta < tb)
    na, nb = WD._num(a), WD._num(b)
    if na is not None and nb is not None:
        return (na > nb) - (na < nb)
    return (str(a) > str(b)) - (str(a) < str(b))


def _match(row: dict, col: str, expr: str) -> bool:
    op, _, val = expr.partition(".")
    v = row.get(col)
    if op == "eq":
        return v is not None and _cmp(v, val) == 0
    if op == "in":
        return v is not None and str(v) in _split_list(val)
    if op == "is":
        return v is None if val == "null" else False
    if op in ("lt", "gt"):
        return v is not None and (_cmp(v, val) < 0 if op == "lt" else _cmp(v, val) > 0)
    raise AssertionError(f"unsupported filter {op}")


class FakeTable:
    """public.properties as PostgREST serves it: GET with filters / select /
    keyset paging, POST upsert (merge-duplicates on the identity), PATCH.
    `writes` counts row versions written (a merge or a PATCH of one row = 1)."""

    def __init__(self):
        self.rows: list[dict] = []
        self.next_id = 1
        self.writes = 0

    def _filtered(self, params: list[tuple[str, str]]) -> list[dict]:
        rows = list(self.rows)
        for k, v in params:
            if k in ("select", "order", "limit", "offset", "on_conflict"):
                continue
            if k == "or":
                parts = _split_list(v)
                rows = [r for r in rows if any(_match(r, *p.split(".", 1)) for p in parts)]
            else:
                rows = [r for r in rows if _match(r, k, v)]
        return rows

    def get(self, query: str) -> list[dict]:
        params = urllib.parse.parse_qsl(query, keep_blank_values=True)
        p = dict(params)
        if p.get("limit") == "0":
            return []                                 # column probes: every migration is applied
        rows = sorted(self._filtered(params), key=lambda r: r["id"])
        if "limit" in p:
            rows = rows[: int(p["limit"])]
        sel = p.get("select", "*")
        if sel == "*":
            return [json.loads(json.dumps(r)) for r in rows]
        cols = [c.strip() for c in sel.split(",")]
        return [json.loads(json.dumps({c: r.get(c) for c in cols})) for r in rows]

    def post(self, query: str, body: list[dict]) -> None:
        for incoming in body:
            key = tuple(incoming.get(k) for k in IDENTITY)
            hit = next((r for r in self.rows if tuple(r.get(k) for k in IDENTITY) == key), None)
            if hit is None:
                hit = {"id": self.next_id}
                self.next_id += 1
                self.rows.append(hit)
            hit.update(json.loads(json.dumps(incoming)))
            self.writes += 1

    def patch(self, query: str, body: dict) -> None:
        for r in self._filtered(urllib.parse.parse_qsl(query, keep_blank_values=True)):
            r.update(json.loads(json.dumps(body)))
            self.writes += 1


class _Resp:
    def __init__(self, data: bytes = b""):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def db(monkeypatch):
    table = FakeTable()

    def urlopen(req, timeout=None):
        url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
        parsed = urllib.parse.urlsplit(url)
        assert parsed.path == "/rest/v1/properties", parsed.path
        method = req.get_method() if isinstance(req, urllib.request.Request) else "GET"
        if method == "GET":
            return _Resp(json.dumps(table.get(parsed.query)).encode())
        body = json.loads(req.data.decode())
        (table.post if method == "POST" else table.patch)(parsed.query, body)
        return _Resp()

    real_get_json = RP.get_json
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(RP, "get_json", lambda url, headers, **kw: real_get_json(url, headers, **{**kw, "opener": urlopen}))
    real_reviews = SP.registry_with_reviews
    monkeypatch.setattr(SP, "registry_with_reviews", lambda state, **kw: real_reviews(state, reviews={}))
    monkeypatch.setenv("SUPABASE_URL", BASE)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return table



# ------------------------------------------------------------ one laft run

def _csv(extra_rows: list[str] = (), replace: tuple[str, str] | None = None) -> str:
    text = (FIX / "ebr_adjudicated_parcel_LIVE_SHAPE.csv").read_text(encoding="utf-8")
    if replace:
        assert replace[0] in text
        text = text.replace(replace[0], replace[1], 1)
    if extra_rows:
        text = text.rstrip("\n") + "\n" + "\n".join(extra_rows) + "\n"
    return text


NEW_ROW = ('555-0001-2,SAMPLE OWNER C,,,30 FIXTURE LN,SAMPLE ADDITION,2-1,3,,LOT 3 SAMPLE ADDITION,X,2024,AJ,0,1000,1000,0,'
           '9000,900,,654321')


def run_laft(table: FakeTable, tmp_path: Path, monkeypatch, csv_text: str) -> dict:
    """harvest (live mode, fixture transport) -> sync -> lifecycle, exactly as
    the workflow's Louisiana steps call them. Returns rows written per step."""
    cfg = LA.EBR_SOURCE
    meta = (FIX / "ebr_parcel_metadata_LIVE_SHAPE.json").read_text(encoding="utf-8")
    monkeypatch.setattr(HSI, "live_fetcher", lambda: (lambda url: meta if url == cfg.metadata_url else csv_text))
    out = tmp_path / "out"
    rows, harvest, status = out / "la_properties_rows.json", out / "harvest_louisiana.json", out / "harvest_louisiana_status.json"
    assert HSI.main(["--state", "LA", "--out", str(harvest), "--status", str(status), "--report", str(out / "h.json"),
                     "--properties-out", str(rows)]) == 0
    before = table.writes
    assert SYNC.main(["--state", "LA", "--rows", str(rows), "--status", str(status)]) == 0
    sync_writes = table.writes - before
    before = table.writes
    assert LL.main(["--state", "LA", "--status", str(status), "--harvest", str(harvest),
                    "--report", str(out / "lifecycle.json")]) == 0
    return {"sync": sync_writes, "lifecycle": table.writes - before}


def _age(table: FakeTable, hours: float) -> None:
    old = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    for r in table.rows:
        r["last_seen_at"] = old


def _active(table):
    return [r for r in table.rows if r.get("status") == "active"]


# ------------------------------------------------------------ the tests

def test_two_consecutive_runs_on_the_same_list_write_nothing_the_second_time(db, tmp_path, monkeypatch):
    first = run_laft(db, tmp_path, monkeypatch, _csv())
    n = len(_active(db))
    assert n == 2
    assert first == {"sync": n, "lifecycle": n}
    for r in _active(db):
        prov = r["otc_provenance"]
        assert prov["harvester"] == "la_ebr_adjudicated" and prov["source_match"]["identifier"] == "case_no"
        assert prov["acquisition"]["mode"] and prov["purchase_evidence_url"]          # verified evidence on run 1
        assert r["purchase_path_type"] == "county_instructions" and r["purchase_url"]
        assert prov["adapter"] == "louisiana"                                         # the adapter's notes are kept
        assert r["list_url"] == LA.EBR_SOURCE.list_url and r["document_url"] == LA.EBR_SOURCE.document_url
    snapshot = json.loads(json.dumps(db.rows))
    second = run_laft(db, tmp_path, monkeypatch, _csv())
    assert second == {"sync": 0, "lifecycle": 0}
    third = run_laft(db, tmp_path, monkeypatch, _csv())
    assert third == {"sync": 0, "lifecycle": 0}
    assert db.rows == snapshot


def test_an_aged_last_seen_at_is_restamped_once_and_evidence_is_kept(db, tmp_path, monkeypatch):
    run_laft(db, tmp_path, monkeypatch, _csv())
    evidence = {r["case_no"]: r["otc_provenance"]["acquisition"] for r in _active(db)}
    _age(db, WD.FRESH_HOURS + 1)
    restamp = run_laft(db, tmp_path, monkeypatch, _csv())
    assert restamp == {"sync": 2, "lifecycle": 0}                 # one re-stamp per row, by the sync
    for r in _active(db):
        assert WD.fresh(r["last_seen_at"])
        assert r["otc_provenance"]["acquisition"] == evidence[r["case_no"]]
        assert r["purchase_path_type"] == "county_instructions"
    assert run_laft(db, tmp_path, monkeypatch, _csv()) == {"sync": 0, "lifecycle": 0}


def test_a_new_row_gets_its_full_lifecycle_provenance_on_the_run_it_appears(db, tmp_path, monkeypatch):
    run_laft(db, tmp_path, monkeypatch, _csv())
    counts = run_laft(db, tmp_path, monkeypatch, _csv([NEW_ROW]))
    assert counts == {"sync": 1, "lifecycle": 1}
    new = next(r for r in db.rows if r["case_no"] == "555-0001-2")
    assert new["status"] == "active" and new["otc_provenance"]["harvester"] == "la_ebr_adjudicated"
    assert new["otc_provenance"]["acquisition"]["mode"] and new["purchase_path_type"] == "county_instructions"
    assert run_laft(db, tmp_path, monkeypatch, _csv([NEW_ROW])) == {"sync": 0, "lifecycle": 0}


def test_a_changed_row_is_written_once(db, tmp_path, monkeypatch):
    run_laft(db, tmp_path, monkeypatch, _csv())
    counts = run_laft(db, tmp_path, monkeypatch, _csv(replace=(",25000,2500,", ",26000,2600,")))
    assert counts == {"sync": 1, "lifecycle": 0}
    row = next(r for r in db.rows if r["case_no"] == "012-3456-7")
    assert float(row["market"]) == 26000 and row["otc_provenance"]["acquisition"]["mode"]
    assert run_laft(db, tmp_path, monkeypatch, _csv(replace=(",25000,2500,", ",26000,2600,"))) == {"sync": 0, "lifecycle": 0}


def test_close_out_and_reactivation_are_unchanged(db, tmp_path, monkeypatch):
    run_laft(db, tmp_path, monkeypatch, _csv([NEW_ROW]))
    run_laft(db, tmp_path, monkeypatch, _csv())                       # the new row left a COMPLETE list
    gone = next(r for r in db.rows if r["case_no"] == "555-0001-2")
    assert gone["status"] == "closed" and gone["delisted_at"]
    run_laft(db, tmp_path, monkeypatch, _csv([NEW_ROW]))              # listed again
    back = next(r for r in db.rows if r["case_no"] == "555-0001-2")
    assert back["status"] == "active" and back["delisted_at"] is None
    assert back["otc_provenance"]["acquisition"]["mode"]


# ------------------------------------------------------------ the pieces

def test_write_diff_ignores_nested_read_stamps_only():
    stored = {"otc_provenance": {"a": 1, "retrieved_at": "2026-10-25T00:00:00+00:00",
                                 "source_match": {"value": "1", "read_at": "2026-10-25T00:00:00+00:00"}}}
    row = {"otc_provenance": {"a": 1, "retrieved_at": "2026-10-26T00:00:00+00:00",
                              "source_match": {"value": "1", "read_at": "2026-10-26T00:00:00+00:00"}}}
    assert WD.unchanged(row, stored)
    assert not WD.unchanged({"otc_provenance": {**row["otc_provenance"], "a": 2}}, stored)
    assert not WD.unchanged({"otc_provenance": {**row["otc_provenance"], "source_match": {"value": "2", "read_at": "x"}}}, stored)
    assert not WD.unchanged(row, stored, ignore_paths=frozenset())


def test_lifecycle_merges_onto_the_stored_dict_and_keeps_evidence_without_a_path():
    stored = {"adapter": "louisiana", "acquisition": {"mode": "x"}, "purchase_evidence_url": "https://e", "harvester": "h"}
    merged = LL.merge_otc(stored, {"harvester": "h", "retrieved_at": "t"})
    assert merged["adapter"] == "louisiana" and merged["acquisition"] == {"mode": "x"} and merged["retrieved_at"] == "t"
    merged = LL.merge_otc(stored, {"acquisition": {"mode": "y"}, "purchase_path_observed_on": "2026-10-01"})
    assert merged["acquisition"] == {"mode": "y"} and "purchase_evidence_url" not in merged   # the group moves as a unit


def test_sync_leaves_lifecycle_keys_to_the_lifecycle_once_it_stamped_the_row():
    stored = {"harvester_source": "la_ebr_adjudicated", "otc_provenance": {"harvester": "la", "purchase_url": "lifecycle",
                                                                          "adapter": "louisiana"}}
    row = {"status": "active", "otc_provenance": {"purchase_url": "adapter", "adapter": "louisiana", "identifier": "x"}}
    prov, _, _ = SYNC.merge_acquisition(row, stored)
    assert prov["purchase_url"] == "lifecycle" and prov["identifier"] == "x"
    prov, _, _ = SYNC.merge_acquisition(row, {"otc_provenance": {"purchase_url": "older adapter"}})
    assert prov["purchase_url"] == "adapter"                      # never stamped by the lifecycle: the adapter's value


def test_keyset_read_accepts_select_star():
    # PR #217's sync reads the stored rows with select=* (write only what
    # changed); read_all refused it ("keyset paging needs `id`"), so every
    # sync_state_inventory.py run against a database stopped before writing.
    seen = []
    rows = RP.read_all(BASE, "properties", {}, {"select": "*", "state": "eq.LA"},
                       fetch=lambda qs: seen.append(qs) or [{"id": 1}])
    assert rows == [{"id": 1}] and "select=*" in seen[0]
    with pytest.raises(ValueError):
        RP.read_all(BASE, "properties", {}, {"select": "county"}, fetch=lambda qs: [])


def test_the_path_groups_agree_and_the_workflow_drops_the_opt_out():
    assert tuple(LL.PATH_PROVENANCE_KEYS) == tuple(SYNC.ACQUISITION_KEYS)
    wf = (REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    line = next(l for l in wf.splitlines() if "laft_lifecycle.py --state LA" in l)
    assert "--no-fresh-guard" not in line
