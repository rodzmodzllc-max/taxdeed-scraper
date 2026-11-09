"""Louisiana data-accuracy fixes (2026-11-08). Synthetic fixtures only.

* LA-1 / LA-3: the Louisiana lifecycle and inventory-status reads ran out of
  the default retry on a statement-timeout HTTP 500 while the expansion legs
  wrote (runs 42364763870, 42018857948). They now use rest_pages' patient
  profile (seven attempts, capped, jittered waits); the workflow retries the
  lifecycle once and warns when it still failed.
* LA-2: change detection read property_change_snapshots by OFFSET; it now
  reads by keyset on property_id through rest_pages.read_all.
* LA-5: a FAIR MARKET VALUE published as 0 is not a value (never stored).
* LA-7: same-number rows on the Parish's list are counted, and the kept record
  is marked AMBIGUOUS when they differ.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.error
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(1, str(REPO))

import detect_property_changes as DPC  # noqa: E402
import harvest_state_inventory as HSI  # noqa: E402
import inventory_status_writer as ISW  # noqa: E402
import laft_lifecycle as LL  # noqa: E402
import rest_pages as RP  # noqa: E402
import sync_state_inventory as SYNC  # noqa: E402
from harvesters.otc.adapters import louisiana as LA  # noqa: E402

T = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


# ------------------------------------------------------------------ patient retry

class _Resp:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def _flaky(failures: int, body, code: int = 500):
    calls = []

    def opener(req, timeout=None):
        calls.append(req.full_url)
        if len(calls) <= failures:
            raise urllib.error.HTTPError(req.full_url, code, "err", {}, None)
        return _Resp(body)
    return opener, calls


def test_wait_seconds_doubles_caps_and_jitters():
    assert [RP.wait_seconds(a, 5.0) for a in (1, 2, 3)] == [5.0, 10.0, 20.0]
    assert RP.wait_seconds(6, 5.0, max_wait=60) == 60
    assert RP.wait_seconds(1, 5.0, jitter=0.5, rand=lambda: 1.0) == 7.5
    assert RP.wait_seconds(1, 5.0, jitter=0.5, rand=lambda: 0.0) == 5.0


def test_patient_profile_outlasts_the_failure_that_beat_the_default_retry():
    # Six 500s in a row: the default profile (4 attempts) raises, the patient
    # one (7 attempts) returns the rows.
    opener, _ = _flaky(6, [{"id": 1}])
    with pytest.raises(urllib.error.HTTPError):
        RP.get_json("https://x/rest/v1/properties", {}, opener=opener, sleep=lambda s: None)
    opener, calls = _flaky(6, [{"id": 1}])
    waits = []
    assert RP.get_json_patient("https://x/rest/v1/properties", {}, opener=opener, sleep=waits.append, rand=lambda: 0.5) == [{"id": 1}]
    assert len(calls) == 7 and len(waits) == 6
    assert max(waits) <= RP.PATIENT_MAX_WAIT_SECONDS * (1 + RP.PATIENT_JITTER) and waits[0] == 5.0 * 1.25
    assert sum(waits) < 300                                         # bounded: never waits for ever


def test_patient_profile_never_retries_a_4xx():
    opener, calls = _flaky(1, [], code=400)
    with pytest.raises(urllib.error.HTTPError):
        RP.get_json_patient("https://x/rest/v1/properties", {}, opener=opener, sleep=lambda s: None)
    assert len(calls) == 1


def test_lifecycle_identity_read_survives_a_loaded_database(monkeypatch):
    opener, calls = _flaky(5, [])
    monkeypatch.setattr(RP, "get_json_patient", lambda url, h, **kw: RP.get_json(
        url, h, attempts=RP.PATIENT_ATTEMPTS, sleep=lambda s: None, opener=opener))
    api = LL.Api("https://x.example", "k", dry_run=True)
    assert LL.fetch_state_rows(api, "LA", ["East Baton Rouge"]) == []
    assert len(calls) == 6 and "select=id" in calls[-1]


def test_lifecycle_and_inventory_writer_use_the_patient_profile():
    for name in ("laft_lifecycle.py", "inventory_status_writer.py"):
        src = (REPO / "scripts" / name).read_text(encoding="utf-8")
        assert "RP.get_json_patient(" in src, name
    src = (REPO / "scripts/inventory_status_writer.py").read_text(encoding="utf-8")
    assert "patient=True" in src and "RP.send_idempotent(" in src


def test_inventory_writer_patch_retries_a_transient_500(monkeypatch):
    sent = []

    def opener(req, timeout=None):
        sent.append(req.get_method())
        if len(sent) == 1:
            raise urllib.error.HTTPError(req.full_url, 500, "err", {}, None)
        return _Resp(None)
    monkeypatch.setattr(ISW.urllib.request, "urlopen", opener)
    real_send = RP.send_idempotent
    monkeypatch.setattr(RP, "send_idempotent", lambda make, **kw: real_send(make, **{**kw, "sleep": lambda s: None}))
    api = ISW.Api("https://x.example", "k")
    api.patch("properties", "id=in.(1)", {"inventory_status": "active"})
    assert sent == ["PATCH", "PATCH"] and api.requests_made == 1


# ------------------------------------------------------------------ LA-2 keyset snapshots

def test_keyset_query_on_another_key():
    qs = dict(urllib.parse.parse_qsl(RP.keyset_query({"select": "property_id,snapshot", "state": "eq.LA"}, "abc", 2, key="property_id")))
    assert qs == {"select": "property_id,snapshot", "state": "eq.LA", "order": "property_id.asc", "limit": "2", "property_id": "gt.abc"}
    with pytest.raises(ValueError):
        RP.read_all("https://x", "t", {}, {"select": "snapshot"}, key="property_id", fetch=lambda q: [])


def test_snapshot_read_pages_by_property_id_not_offset():
    pages = [[{"property_id": "a", "snapshot": {}}, {"property_id": "b", "snapshot": {}}], [{"property_id": "c", "snapshot": {}}]]
    queries = []

    def fetch(qs):
        queries.append(dict(urllib.parse.parse_qsl(qs)))
        return pages[len(queries) - 1]
    rows = RP.read_all("https://x", "property_change_snapshots", {}, {"select": "property_id,snapshot", "state": "eq.LA"},
                       page=2, key="property_id", fetch=fetch)
    assert [r["property_id"] for r in rows] == ["a", "b", "c"]
    assert "property_id" not in queries[0] and queries[1]["property_id"] == "gt.b"
    assert all("offset" not in q for q in queries)


def test_change_detection_snapshot_read_uses_the_keyset_population_read():
    src = (REPO / "scripts/detect_property_changes.py").read_text(encoding="utf-8")
    main = src[src.index("def main("):]
    assert 'api.population("property_change_snapshots"' in main and 'key="property_id"' in main
    assert 'api.paged(f"property_change_snapshots' not in src


def test_change_detection_population_forwards_the_key(monkeypatch):
    seen = {}
    monkeypatch.setattr(RP, "read_all", lambda root, table, headers, params, **kw: seen.update(table=table, **kw) or [])
    DPC.Api("https://x.example", "k").population("property_change_snapshots", {"select": "property_id,snapshot"}, key="property_id")
    assert seen == {"table": "property_change_snapshots", "key": "property_id", "patient": True}


# ------------------------------------------------------------------ workflow

def _la_steps():
    wf = yaml.safe_load((REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    return {s.get("name"): s for s in wf["jobs"]["laft"]["steps"]}


def test_workflow_retries_the_lifecycle_and_surfaces_a_failure():
    steps = _la_steps()
    first = steps["Louisiana - lifecycle (last_seen_at, gated close-out)"]
    retry = steps["Retry Louisiana lifecycle (after a failed attempt)"]
    report = steps["Report Louisiana lifecycle failure"]
    assert first["id"] == "la_lifecycle" and first["continue-on-error"] is True
    assert "steps.la_lifecycle.outcome == 'failure'" in retry["if"] and "laft_lifecycle.py --state LA" in retry["run"]
    assert "la_lifecycle_retry.outcome != 'success'" in report["if"] and "::warning" in report["run"]
    assert "GITHUB_STEP_SUMMARY" in report["run"] and "continue-on-error" not in report
    inv = steps["Report Louisiana inventory-status failure"]
    assert "steps.la_inventory_status.outcome == 'failure'" in inv["if"] and "::warning" in inv["run"]


# ------------------------------------------------------------------ LA-5 / LA-7 adapter

def _csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(LA.EBR_PARCEL_HEADER)
    for r in rows:
        w.writerow([r.get(h, "") for h in LA.EBR_PARCEL_HEADER])
    return buf.getvalue()


def _row(number, **kw):
    base = {"ASSESSMENT NO.": number, "OWNER NAME": "FIXTURE OWNER", "PHYSICAL ADDRESS": "1 FIXTURE ST",
            "LEGAL DESCRIPTION": "LOT 1 FIXTURE", "STATUS": "AJ", "FAIR MARKET VALUE": "0", "ASSESSED VALUE": "1000"}
    base.update(kw)
    return base


def _parse(rows):
    return LA.parse_csv(LA.EBR_PARCEL_SOURCE, _csv(rows), retrieved_at=T, list_as_of=date(2026, 5, 6))


def test_market_value_published_as_zero_is_not_stored():
    recs, out = _parse([_row("001-0000-1"), _row("001-0000-2", **{"FAIR MARKET VALUE": "25,000"}),
                        _row("001-0000-3", **{"FAIR MARKET VALUE": ""})])
    r = {x.case_no: x for x in recs}
    assert r["001-0000-1"].market is None and "published as 0" in r["001-0000-1"].provenance["market"]
    assert r["001-0000-2"].market == 25000 and r["001-0000-2"].provenance["market"].endswith("(tax roll)")
    assert r["001-0000-3"].market is None and r["001-0000-3"].provenance["market"] == "not published on the row"
    assert out["market_published_as_zero"] == 1
    row = r["001-0000-1"].to_properties_row()
    assert "market" in row and row["market"] is None            # sent as NULL: clears a stored placeholder 0
    assert "market" not in r["001-0000-3"].to_properties_row()   # an absent value writes nothing
    assert r["001-0000-1"].assessed == 1000                      # assessed is unchanged
    # The sync's keep-enriched guard does not put the list's own stored 0 back.
    stored = {"market": 0, "field_provenance": {"market": {"source": "county_list"}}}
    assert SYNC.keep_enriched_values(dict(row), stored) == 0


def test_duplicate_rows_are_counted_and_differing_ones_marked_ambiguous():
    recs, out = _parse([
        _row("002-0000-1"), _row("002-0000-1"),                                      # identical duplicate
        _row("002-0000-2"), _row("002-0000-2", **{"ASSESSED VALUE": "2000"}),         # differing duplicate
        _row("002-0000-2"),
        _row("002-0000-3"),
    ])
    assert len(recs) == 3
    assert out["duplicate_identifier_numbers"] == 2 and out["duplicate_identifier_rows"] == 3
    assert out["duplicate_identifiers_differing"] == 1 and out["superseded_tax_year_rows"] == 0
    r = {x.case_no: x for x in recs}
    assert r["002-0000-2"].provenance["duplicate_rows"].startswith("AMBIGUOUS") and r["002-0000-2"].assessed == 1000
    assert "identical" in r["002-0000-1"].provenance["duplicate_rows"]
    assert "duplicate_rows" not in r["002-0000-3"].provenance
    assert LA.classify_outcome(LA.EBR_PARCEL_SOURCE, recs, out).status == "COMPLETE"


def test_duplicate_counts_reach_the_counts_only_harvest_report():
    oc = LA.classify_outcome(LA.EBR_PARCEL_SOURCE, *_parse([_row("003-0000-1"), _row("003-0000-1")]))
    rep = {oc.county: {k: oc.report[k] for k in HSI.DUPLICATE_KEYS if k in oc.report}}
    assert rep == {LA.PARISH: {"duplicate_identifier_numbers": 1, "duplicate_identifier_rows": 1,
                               "duplicate_identifiers_differing": 0}}
    src = (REPO / "scripts/harvest_state_inventory.py").read_text(encoding="utf-8")
    assert '"duplicates":' in src
