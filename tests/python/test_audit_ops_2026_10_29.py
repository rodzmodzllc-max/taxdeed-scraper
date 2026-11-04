"""Audit fixes, operations area (2026-10-29): B6, B10, B23, B25, B26, B43, F34.

Every test here fails on the code before the fix and passes after it. No
network, no database: I/O is injected or monkeypatched.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "scripts"))

from harvesters.otc.adapters import epropertyplus as EPP  # noqa: E402
from harvesters.otc.adapters import expansion as X  # noqa: E402
from harvesters.otc.adapters.tabular import TabularListAdapter  # noqa: E402
import enrichment_units as EU  # noqa: E402
import harvest_expansion as HX  # noqa: E402
import rest_pages as RP  # noqa: E402
import schedule_watchdog as W  # noqa: E402
import sync_state_inventory as SY  # noqa: E402
import unit_freshness as U  # noqa: E402

FIX = REPO / "tests/python/fixtures/expansion"
NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


# ----------------------------------------------------------------- B6

class _FakeRegistry:
    def __init__(self, existing: set[tuple]):
        self.existing = existing
        self.patched, self.inserted = [], []

    def patch(self, match, body):
        key = (match["state"], match["source_id"], match["county"])
        if key in self.existing:
            self.patched.append(key)
            return 1
        return 0

    def insert(self, row):
        self.inserted.append(row)


def _csv_units():
    return U.registry_units(REPO / "data/county_source_registry.csv")


def test_b6_a_unit_missing_from_the_registry_table_is_inserted_from_its_csv_row():
    units = _csv_units()
    mo = [u for u in units.values() if u["state"] == "MO"]
    assert mo, "the CSV registry carries the Missouri sources"
    entries = [U.normalize_entry({"county": u["county"], "status": "COMPLETE", "row_count": 5, "source_id": u["source_id"],
                                  "checked_at": "2026-10-28T18:14:43+00:00"}, default_state="MO", default_source=None)
               for u in mo]
    record, _ = U.merge({}, entries, at="2026-10-28T18:16:14+00:00")
    api = _FakeRegistry(existing={(mo[0]["state"], mo[0]["source_id"], mo[0]["county"])})
    res = U.apply_registry(api, record, units)
    assert res == {"patched": 1, "inserted": len(mo) - 1, "insert_failed": 0}
    row = api.inserted[0]
    # The CSV's governance / publication columns, plus this run's freshness.
    assert row["state"] == "MO" and row["verification_status"] == "PRODUCTION_VERIFIED"
    assert row["publication_status"] and row["governance_status"] and row["evidence_ref"]
    assert row["last_success_at"] == "2026-10-28T18:14:43+00:00" and row["last_success_row_count"] == 5
    assert "purchase_path_mode" not in row and "purchase_path_evidence" not in row      # not table columns


def test_b6_every_production_csv_row_makes_a_valid_insert():
    # The CHECK constraints of public.county_source_registry (read 2026-10-29).
    for r in csv.DictReader(io.StringIO((REPO / "data/county_source_registry.csv").read_text(encoding="utf-8"))):
        if r["verification_status"] != "PRODUCTION_VERIFIED":
            continue
        row = U.registry_insert_row(r, {})
        assert set(row) <= set(U.REGISTRY_TABLE_COLUMNS)
        for col in ("state", "county", "access_method", "machine_format", "verification_status", "governance_status",
                    "last_checked", "evidence_ref"):
            assert row.get(col), (r["source_id"], col)
        assert (row["purchase_url"] is None) == (row["purchase_url_kind"] is None), r["source_id"]
        assert (row.get("publishing_unit", "COUNTY") == "STATE") == (row["county"] == "STATEWIDE"), r["source_id"]


# ----------------------------------------------------------------- B26

def test_b26_one_state_is_an_eq_filter_not_in():
    assert EU.state_param(["MO"]) == {"state": "eq.MO"}
    assert EU.state_param(["SC", "WY"]) == {"state": "in.(SC,WY)"}
    assert EU.state_param([]) == {}


# ----------------------------------------------------------------- B10

_OCONEE = """<table><tr><th>Item Number</th><th>Owner Name</th><th>Map Number</th><th>Description</th><th>Total Tax Due</th></tr>
<tr><td>26001</td><td>A OWNER</td><td>100-00-00-001</td><td>LOT 1</td><td>$100.00</td></tr>
<tr><td>26002</td><td></td><td>100-00-00-002</td><td></td><td></td></tr>
</table>"""


def test_b10_an_identity_only_row_is_flagged_and_the_read_is_incomplete(tmp_path):
    ad = TabularListAdapter(X.SC_OCONEE)
    recs = ad.parse_html_table(_OCONEE, retrieved_at=NOW)
    assert len(recs) == 2 and ad.identity_only_rows == 1
    assert recs[1].provenance.get("identity_only_row") is True and "identity_only_row" not in recs[0].provenance
    page = tmp_path / "oconee.html"
    page.write_text(_OCONEE, encoding="utf-8")
    src = next(s for s in X.SOURCES["SC"] if s.config.source_id == "sc_oconee_tax_sale_list")
    status, got, cat, detail, _ = HX.run_source(src, None, None, retrieved_at=NOW, fixture=str(page))
    assert status == "INCOMPLETE" and len(got) == 2 and "only their identifier" in detail


def test_b10_sparse_lists_that_do_not_expect_data_cells_are_unchanged():
    cfg = X.SC_OCONEE.__class__(**{**X.SC_OCONEE.__dict__, "data_cells_expected": False})
    ad = TabularListAdapter(cfg)
    recs = ad.parse_html_table(_OCONEE, retrieved_at=NOW)
    assert ad.identity_only_rows == 0 and all("identity_only_row" not in r.provenance for r in recs)


def test_b10_sync_keeps_the_lists_own_earlier_values_on_an_identity_only_row():
    stored = {"purchase_amount": 100.0, "purchase_amount_kind": "PUBLISHED_AMOUNT_KIND_UNSPECIFIED",
              "legal_desc": "LOT 2", "owner_name": "B OWNER",
              "field_provenance": {"purchase_amount": {"source": "county_list"}, "legal_desc": {"source": "county_list"}}}
    row = {"purchase_amount": None, "purchase_amount_kind": "NOT_PUBLISHED", "legal_desc": None, "owner_name": None,
           "otc_provenance": {"adapter": "tabular", "identity_only_row": True}}
    assert SY.keep_enriched_values(row, stored) == 3
    assert (row["purchase_amount"], row["purchase_amount_kind"], row["legal_desc"], row["owner_name"]) == \
        (100.0, "PUBLISHED_AMOUNT_KIND_UNSPECIFIED", "LOT 2", "B OWNER")
    # A row that carried its data cells follows the list, blanks included.
    full = {"purchase_amount": None, "legal_desc": None, "otc_provenance": {"adapter": "tabular"}}
    assert SY.keep_enriched_values(full, stored) == 0 and full["purchase_amount"] is None


# ----------------------------------------------------------------- B23

def test_b23_key_alignment_never_nulls_a_parcel_layer_value(tmp_path):
    args = ["--state", "CO", "--out-dir", str(tmp_path), "--fixture",
            f"co_morgan_county_held_certificates={FIX / 'co_morgan.html'}"]
    assert HX.main(args) == 0
    rows = json.loads((tmp_path / "co_properties_rows.json").read_text())
    assert len(rows) >= 2
    a, b = rows[0], rows[1]
    a["acreage"] = 1.5                    # the list publishes acreage on this row ...
    b.pop("acreage", None)                # ... and not on this one
    ident = SY.identity(dict(b, source=b.get("source") or "certificate"))
    prov = {"acreage": {"source": "statewide_parcel", "source_id": "co_oit_public_parcels"}}
    stored = {ident: {"acreage": 40.0, "field_provenance": prov}}
    sent, counts = SY.plan("CO", rows, SY.registry_rows("CO"), {"Morgan": "COMPLETE"}, stored_provenance={ident: prov},
                           stored_values=stored)
    got = next(r for r in sent if SY.identity(r) == ident)
    assert got["acreage"] == 40.0 and counts.get("enriched_values_kept_after_alignment", 0) >= 1
    assert next(r for r in sent if SY.identity(r) == SY.identity(dict(a, source=a.get("source") or "certificate")))["acreage"] == 1.5


# ----------------------------------------------------------------- F34

def _epp_row(pid, lat, lng):
    return {"parcelNumber": pid, "available": "Y", "county": "WAYNE", "latitude": lat, "longitude": lng,
            "askingPrice": 500, "propertyAddress1": None, "id": pid}


def test_f34_a_point_shared_by_three_parcels_is_not_stored_as_their_location():
    rows = [_epp_row(f"8010001004{i}000", 42.20476, -83.48521) for i in range(3)] + \
           [_epp_row("80100010999000", 42.30001, -83.10001), _epp_row("80100010998000", 42.30001, -83.10001)]
    recs, counts = EPP.parse_rows(X.MI_WAYNE_COUNTY_LANDBANK, rows, retrieved_at=NOW)
    assert counts["shared_point_withheld"] == 3
    shared = [r for r in recs if r.parcel.startswith("80100010040")]
    assert all(r.latitude is None and r.longitude is None for r in shared)
    assert all("not stored" in r.provenance["coordinates"] for r in shared)
    pair = [r for r in recs if r.parcel in ("80100010999000", "80100010998000")]
    assert all(r.latitude == 42.30001 for r in pair)          # two parcels on one point are kept


# ----------------------------------------------------------------- B25

def _run(rid, created, names_ok):
    return {"id": rid, "created_at": created, "status": "completed", "event": "workflow_dispatch"}, \
        [{"name": W.JOB_NAME_PREFIXES[k] + " x", "conclusion": c} for k, c in names_ok.items()]


def test_b25_a_late_schedule_skips_jobs_a_catch_up_already_completed():
    r1, j1 = _run(1, "2026-10-28T13:35:35Z", {"laft": "success", "expansion": "success", "certificates": "failure",
                                               "texas": "success", "backup": "success", "deeds": "success"})
    r0, j0 = _run(0, "2026-10-28T09:00:00Z", {"laft": "success"})   # before the 11:37 slot: covers nothing
    late = datetime(2026, 10, 28, 17, 20, tzinfo=timezone.utc)
    got = W.covered_jobs("37 11 * * *", late, [r0, r1, {"id": 9, "created_at": "2026-10-28T17:20:05Z"}],
                         {0: j0, 1: j1}, self_id=9)
    assert got == ["backup", "expansion", "laft", "texas"]            # a failed catch-up job still runs
    assert W.covered_jobs("13 4 * * *", late, [r1], {1: j1}) == ["deeds"]
    assert W.covered_jobs("not a cron", late, [r1], {1: j1}) == []


def test_b25_every_scheduled_job_waits_for_the_guard_and_skips_what_it_names():
    wf = yaml.safe_load((REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    guard = wf["jobs"]["schedule_guard"]
    assert guard["if"] == "github.event_name == 'schedule'" and guard["permissions"]["actions"] == "read"
    assert "--guard" in json.dumps(guard["steps"])
    for job in sorted(W.ALL_JOBS):
        j = wf["jobs"][job]
        assert j["needs"] == "schedule_guard", job
        assert j["if"].startswith("${{ !cancelled() && (") and \
            f"!contains(needs.schedule_guard.outputs.covered, '{job}')" in j["if"], job


def test_b25_guard_main_fails_open_and_writes_an_empty_output(tmp_path, monkeypatch):
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert W.main(["--guard", "37 11 * * *"]) == 0
    assert out.read_text() == "covered=\n"


# ----------------------------------------------------------------- B43

class _Resp:
    def __init__(self, body=b"[]"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def _err(code):
    return urllib.error.HTTPError("https://x.test", code, "err", {}, io.BytesIO(b"{}"))


def test_b43_an_idempotent_write_rides_out_a_503_and_a_read_timeout():
    seq = [_err(503), TimeoutError("read"), _Resp(b"ok")]
    sleeps = []

    def opener(req, timeout):
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    assert RP.send_idempotent(lambda: object(), sleep=sleeps.append, opener=opener) == b"ok"
    assert sleeps == [RP.WRITE_BACKOFF_SECONDS, 2 * RP.WRITE_BACKOFF_SECONDS]


def test_b43_a_4xx_or_an_excluded_500_is_never_retried():
    for code, statuses in ((400, RP.RETRY_STATUSES), (500, RP.RETRY_STATUSES - {500})):
        calls = []

        def opener(req, timeout, code=code):
            calls.append(1)
            raise _err(code)
        with pytest.raises(urllib.error.HTTPError):
            RP.send_idempotent(lambda: object(), sleep=lambda s: None, opener=opener, retry_statuses=statuses)
        assert len(calls) == 1


def test_b43_close_rows_retries_a_transient_failure(monkeypatch):
    seq = [_err(503), _Resp()]

    def fake(req, timeout=None):
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    orig = RP.send_idempotent
    monkeypatch.setattr(RP, "send_idempotent", lambda make, **kw: orig(make, **{**kw, "opener": fake, "sleep": lambda s: None}))
    SY.close_rows("https://x.test", "k", [{"id": "1", "status": "closed"}])
    assert seq == []
