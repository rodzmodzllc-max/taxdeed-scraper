"""Stale rows and source re-verification (2026-10-25).

Owner's complaint: rows that dropped off their source (Hendry FL Lands
Available) were still shown as current. Synthetic fixtures only:

  * the row-observation rule (harvesters/ledgers/health.py): NEVER_READ /
    STALE / FRESH on the row's own last_seen_at, per-ledger windows,
    updated_at never counts as an observation
  * the publication gate withholds a NEVER_READ row even when updated_at is
    recent; the inventory-status writer turns a stale presence status into
    `unknown` - never `closed`, never a result
  * scripts/stale_rows_report.py: counts only, per state x source x county
  * the LGBS TLS fix: the shipped intermediate is pinned and only ADDS to the
    default verifying context
  * ArcGIS repeat listings: identical repeats on ONE page collapse; repeats
    across pages or with different mapped values still fail closed
  * the LAFT PDF successor discovery follows the county page's own
    Lands Available link (Pasco), never another host
  * the FL auction off-list close-out: OFF by default, status 'closed' only
"""
from __future__ import annotations

import hashlib
import json
import ssl
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from harvesters.ledgers import Ledger  # noqa: E402
from harvesters.ledgers import health as LH  # noqa: E402
from harvesters.governance import inventory_status as IS  # noqa: E402
from harvesters.governance import publication_state as PS  # noqa: E402

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


# ==================== row observation ====================

@pytest.mark.parametrize("source,days_ok,days_stale", [("auction", 6, 8), ("laft", 13, 15), ("certificate", 6, 8)])
def test_row_observation_uses_the_ledger_window(source, days_ok, days_stale):
    assert LH.row_observation({"source": source, "last_seen_at": ago(days=days_ok)}, NOW) == "FRESH"
    assert LH.row_observation({"source": source, "last_seen_at": ago(days=days_stale)}, NOW) == "STALE"
    assert LH.row_observation({"source": source, "last_seen_at": None}, NOW) == "NEVER_READ"


def test_updated_at_is_never_an_observation():
    row = {"source": "laft", "last_seen_at": None, "updated_at": ago(hours=1)}
    assert LH.row_observation(row, NOW) == "NEVER_READ" and not LH.is_current(row, NOW)
    assert LH.row_observation({"source": "laft", "last_seen_at": "not a date"}, NOW) == "NEVER_READ"


def test_windows_are_one_table():
    assert PS.FRESHNESS_DAYS == {"AUCTIONS": 7, "AVAILABLE": 14, "LIENS_CERTIFICATES": 7}
    assert {k.value: v for k, v in LH.FRESHNESS_DAYS.items()} == PS.FRESHNESS_DAYS
    assert LH.NOT_CURRENT == {"NEVER_READ", "STALE"}


# ==================== publication gate ====================

def test_gate_withholds_a_never_read_row_even_with_a_recent_update():
    from test_publication_state_gate import ctx, row  # noqa: PLC0415
    fresh = PS.decide(row(), ctx())
    assert fresh.state == "CUSTOMER_PUBLISHED"
    d = PS.decide(row(last_seen_at=None, updated_at="2026-10-10T06:00:00Z"), ctx())
    assert d.state == "ADMIN_ONLY_STALE" and d.reasons == ["OBSERVATION_STALE"]
    # Hendry's shape: an AVAILABLE row never stamped, updated weeks ago.
    d = PS.decide(row(id="h1", county="Calhoun", source="laft", ledger_type="buy", source_id="fl_laft_calhoun", url_auction=None,
                      sale_date=None, last_seen_at=None, updated_at="2026-10-09T00:00:00Z"), ctx())
    assert d.state == "ADMIN_ONLY_STALE" and "OBSERVATION_STALE" in d.reasons


# ==================== inventory status ====================

def _laft(**over):
    base = {"id": "x1", "state": "FL", "county": "Hendry", "source": "laft", "source_id": "fl_laft_pdfs", "status": "active",
            "case_no": "C-1", "inventory_status": "available_otc", "inventory_status_raw": None}
    base.update(over)
    return base


def test_stale_presence_status_becomes_unknown_never_closed():
    obs = IS.status_for_row(_laft(last_seen_at=None), today=NOW.date())
    assert obs.status == "available_otc"
    out = IS.apply_staleness(obs, _laft(last_seen_at=None), now=NOW)
    assert out.status == "unknown" and out.basis == "LIST_PRESENCE" and "NEVER_READ" in out.note and "not closed" in out.note
    out = IS.apply_staleness(obs, _laft(last_seen_at=ago(days=20)), now=NOW)
    assert out.status == "unknown" and "STALE" in out.note
    assert IS.apply_staleness(obs, _laft(last_seen_at=ago(days=2)), now=NOW) is obs
    # a row dict without the column is not judged
    assert IS.apply_staleness(obs, {k: v for k, v in _laft().items()}, now=NOW) is obs
    # closed / results are never touched
    closed = IS.status_for_row(_laft(status="closed", last_seen_at=None), today=NOW.date())
    assert IS.apply_staleness(closed, _laft(status="closed", last_seen_at=None), now=NOW) is closed


def test_certificate_listed_and_upcoming_go_unknown_when_never_read():
    cert = {"id": "c1", "state": "FL", "county": "Lee", "source": "certificate", "status": "active", "last_seen_at": None}
    assert IS.apply_staleness(IS.status_for_row(cert, today=NOW.date()), cert, now=NOW).status == "unknown"
    auc = {"id": "a1", "state": "FL", "county": "Lee", "source": "auction", "status": "active", "sale_date": "2026-11-05",
           "last_seen_at": ago(days=10)}
    assert IS.status_for_row(auc, today=NOW.date()).status == "upcoming"
    assert IS.apply_staleness(IS.status_for_row(auc, today=NOW.date()), auc, now=NOW).status == "unknown"


def test_writer_plan_counts_not_current_rows():
    import inventory_status_writer as W  # noqa: PLC0415
    assert "last_seen_at" in W.SELECT
    rows = [_laft(id="1", last_seen_at=None), _laft(id="2", last_seen_at=ago(days=1)), _laft(id="3", last_seen_at=ago(days=30))]
    changes, counts = W.plan(rows, today=NOW.date(), now=NOW)
    assert counts["not_current"] == 2
    by_id = {c["id"]: c for c in changes}
    assert by_id["1"]["status"] == by_id["3"]["status"] == "unknown" and "2" not in by_id
    assert all(c["transition"] != "removed" and c["status"] != "closed" for c in changes)


# ==================== stale_rows_report ====================

def test_stale_rows_report_counts_only(tmp_path):
    import stale_rows_report as R  # noqa: PLC0415
    rows = [
        {"id": "1", "state": "FL", "county": "Hendry", "source": "laft", "source_id": "fl_laft_pdfs", "status": "active", "last_seen_at": None,
         "parcel": "SECRET-PARCEL-1", "address": "1 ELM ST"},
        {"id": "2", "state": "FL", "county": "Hendry", "source": "laft", "source_id": "fl_laft_pdfs", "status": "available", "last_seen_at": ago(days=20)},
        {"id": "3", "state": "FL", "county": "Hendry", "source": "laft", "source_id": "fl_laft_pdfs", "status": "active", "last_seen_at": ago(days=1)},
        {"id": "4", "state": "FL", "county": "Lee", "source": "certificate", "status": "active", "last_seen_at": None},
        {"id": "5", "state": "FL", "county": "Lee", "source": "certificate", "status": "closed", "last_seen_at": None},
        {"id": "6", "state": "TX", "county": "Leon", "source": "laft", "harvester_source": "tx_lgbs", "status": "active", "last_seen_at": ago(days=9)},
    ]
    table = R.tally(rows, NOW)
    assert table[("FL", "fl_laft_pdfs", "Hendry")] == {"never_read": 1, "stale": 1, "fresh": 1, "ledger": "AVAILABLE"}
    assert table[("FL", "certificate", "Lee")]["never_read"] == 1            # the closed row is not counted
    assert table[("TX", "tx_lgbs", "Leon")]["fresh"] == 1                   # 9 days < AVAILABLE's 14
    assert R.totals(table) == {"never_read": 2, "stale": 1, "fresh": 2}
    p = tmp_path / "rows.json"
    p.write_text(json.dumps(rows))
    out = tmp_path / "report.json"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/stale_rows_report.py"), "--rows", str(p), "--now", NOW.isoformat(),
                        "--json", str(out)], capture_output=True, text=True, check=True)
    assert "SECRET-PARCEL-1" not in r.stdout + out.read_text() and "ELM" not in r.stdout + out.read_text()
    assert "FL | fl_laft_pdfs | Hendry | AVAILABLE | 1 | 1 | 1" in r.stdout
    assert json.loads(out.read_text())["totals"] == {"never_read": 2, "stale": 1, "fresh": 2}


def test_stale_rows_report_never_writes():
    src = (ROOT / "scripts/stale_rows_report.py").read_text()
    for verb in ('method="PATCH"', 'method="POST"', "method='PATCH'", "DELETE"):
        assert verb not in src


# ==================== LGBS TLS chain ====================

def test_shipped_intermediate_is_pinned_and_public():
    from harvesters import tls_chain  # noqa: PLC0415
    for name, sha in tls_chain.PINNED_INTERMEDIATES.items():
        pem = (tls_chain.TLS_DIR / name).read_text()
        assert pem.count("BEGIN CERTIFICATE") == 1 and "PRIVATE KEY" not in pem
        assert hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() == sha


def test_tls_context_keeps_full_verification():
    from harvesters import tls_chain  # noqa: PLC0415
    ctx = tls_chain.ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    assert any("DigiCert Global G2 TLS RSA SHA256 2020 CA1" in str(c.get("subject")) for c in ctx.get_ca_certs())


def test_lgbs_callers_use_the_chain():
    assert "tls.urlopen(url" in (ROOT / "harvesters/texas_harvester.py").read_text()
    assert "TLS.urlopen(req" in (ROOT / "scripts/lgbs_available_refresh.py").read_text()
    assert "tls_chain.urlopen(request" in (ROOT / "harvesters/acquisition/transport.py").read_text()
    for p in ("harvesters/tls_chain.py", "harvesters/texas_harvester.py", "scripts/lgbs_available_refresh.py"):
        text = (ROOT / p).read_text()
        assert "CERT_NONE" not in text and "check_hostname = False" not in text and "_create_unverified_context" not in text


# ==================== ArcGIS repeat listings ====================

def _arc():
    """The OFFSET path (a layer not opted into keyset reading): the Detroit
    programs config with keyset switched off, so these rules stay pinned for
    every other ArcGIS source. The Detroit layers themselves read by object
    id since 2026-10-26 (tests below)."""
    import dataclasses  # noqa: PLC0415
    from harvesters.otc.adapters import arcgis as AG  # noqa: PLC0415
    from harvesters.otc.adapters import expansion as EX  # noqa: PLC0415
    return AG, dataclasses.replace(EX.MI_DETROIT_LANDBANK_PROGRAMS, keyset=False)


def _feat(oid, pid, program="Own It Now", addr="1 Test St"):
    return {"attributes": {"ObjectId": oid, "parcel_id": pid, "program": program, "address": addr,
                           "latitude": 42.3, "longitude": -83.0, "listing_date": 1700000000000 + oid}}


def _payload(features, more=False):
    return {"objectIdFieldName": "ObjectId", "features": features, "exceededTransferLimit": more}


def test_identical_repeat_on_one_page_collapses():
    AG, cfg = _arc()
    page = _payload([_feat(1, "A1."), _feat(2, "A1."), _feat(3, "A1."), _feat(4, "B2.")])
    res = AG.fetch_all(cfg, lambda url: page, retrieved_at=NOW)
    assert res.outcome == "COMPLETE" and len(res.records) == 2 and res.duplicates_collapsed == 2


def test_repeat_with_a_different_mapped_value_fails():
    AG, cfg = _arc()
    page = _payload([_feat(1, "A1.", program="Own It Now"), _feat(2, "A1.", program="Renovation Programs")])
    res = AG.fetch_all(cfg, lambda url: page, retrieved_at=NOW)
    assert res.outcome == "FAILED" and res.records == [] and "within one page" in res.error_detail


def test_identical_repeat_across_pages_still_fails():
    AG, cfg = _arc()
    pages = iter([_payload([_feat(1, "A1.")], more=True), _payload([_feat(2, "A1.")])])
    res = AG.fetch_all(cfg, lambda url: next(pages), retrieved_at=NOW)
    assert res.outcome == "FAILED" and "across pages" in res.error_detail


# ==================== ArcGIS keyset (object-id) reading ====================

def _keyset_layer(features, page_size=2, meta=None):
    """A fake layer honouring `where ... AND ObjectId > N`, orderByFields and
    resultRecordCount, plus the `?f=json` metadata request."""
    import re  # noqa: PLC0415
    from urllib.parse import parse_qs, urlsplit  # noqa: PLC0415
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith("?f=json"):
            return meta if meta is not None else {"objectIdField": "ObjectId"}
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert "resultOffset" not in q and q["orderByFields"] == "ObjectId"
        m = re.search(r"ObjectId > (\d+)", q["where"])
        after = int(m.group(1)) if m else -1
        rest = sorted((f for f in features if f["attributes"]["ObjectId"] > after), key=lambda f: f["attributes"]["ObjectId"])
        n = int(q["resultRecordCount"])
        return {"objectIdFieldName": "ObjectId", "features": rest[:n], "exceededTransferLimit": len(rest) > n}
    return fetch, calls


def test_detroit_layers_read_by_object_id():
    from harvesters.otc.adapters import expansion as EX  # noqa: PLC0415
    assert EX.MI_DETROIT_LANDBANK_LOTS.keyset is True and EX.MI_DETROIT_LANDBANK_PROGRAMS.keyset is True


def test_keyset_batches_start_after_the_last_id_and_read_everything():
    import dataclasses  # noqa: PLC0415
    AG, _ = _arc()
    from harvesters.otc.adapters import expansion as EX  # noqa: PLC0415
    cfg = dataclasses.replace(EX.MI_DETROIT_LANDBANK_PROGRAMS, page_size=2)
    feats = [_feat(i, f"P{i}.") for i in (3, 7, 9, 12, 20)]
    fetch, calls = _keyset_layer(feats)
    res = AG.fetch_all(cfg, fetch, retrieved_at=NOW)
    assert res.outcome == "COMPLETE" and sorted(r.case_no for r in res.records) == ["P12.", "P20.", "P3.", "P7.", "P9."]
    wheres = [c for c in calls if "query?" in c]
    assert "ObjectId%20%3E%207" in wheres[1] and "ObjectId%20%3E%2012" in wheres[2]


def test_keyset_identical_repeat_across_batches_collapses():
    """With object-id batches nothing can shift between requests, so the same
    listing in two batches is the layer publishing it twice (run 374's
    Detroit failure): one record, counted as collapsed."""
    import dataclasses  # noqa: PLC0415
    AG, _ = _arc()
    from harvesters.otc.adapters import expansion as EX  # noqa: PLC0415
    cfg = dataclasses.replace(EX.MI_DETROIT_LANDBANK_PROGRAMS, page_size=2)
    a = _feat(1, "A1."); b = _feat(2, "B2."); a2 = _feat(3, "A1."); a2["attributes"]["listing_date"] = a["attributes"]["listing_date"]
    fetch, _calls = _keyset_layer([a, b, a2])
    res = AG.fetch_all(cfg, fetch, retrieved_at=NOW)
    assert res.outcome == "COMPLETE" and len(res.records) == 2 and res.duplicates_collapsed == 1


def test_keyset_repeat_with_different_values_and_missing_ids_fail():
    import dataclasses  # noqa: PLC0415
    AG, _ = _arc()
    from harvesters.otc.adapters import expansion as EX  # noqa: PLC0415
    cfg = dataclasses.replace(EX.MI_DETROIT_LANDBANK_PROGRAMS, page_size=2)
    fetch, _c = _keyset_layer([_feat(1, "A1.", program="Own It Now"), _feat(5, "A1.", program="Renovation Programs")])
    res = AG.fetch_all(cfg, fetch, retrieved_at=NOW)
    assert res.outcome == "FAILED" and res.records == []
    fetch, _c = _keyset_layer([], meta={"fields": [{"name": "x", "type": "esriFieldTypeString"}]})
    res = AG.fetch_all(cfg, fetch, retrieved_at=NOW)
    assert res.outcome == "FAILED" and "object-id" in res.error_detail


# ==================== LAFT PDF successor discovery ====================

PASCO_PAGE = """<html><body>
<a href="public_records/tax-deeds/List%20of%20Lands%20Available%20for%20Taxes%2020261014.pdf">List of Lands</a>
<a href="public_records/tax-deeds/Unclaimed%20Tax%20Deed%20Surplus%20Affidavit.pdf">Surplus</a>
<a href="https://elsewhere.example.com/Lands-Available.pdf">Other host</a>
</body></html>"""


def test_successor_follows_the_county_pages_own_lands_available_link():
    import harvest_laft_pdfs as H  # noqa: PLC0415
    page = "https://app.pascoclerk.com/appdot-public-statistical-reports-taxdeeds.asp"
    dead = "https://app.pascoclerk.com/public_records/tax-deeds/List%20of%20Lands%20Available%20for%20Taxes%2020260706.pdf"
    got = H.discover_successor_pdf(PASCO_PAGE, dead, page_url=page)
    assert got == "https://app.pascoclerk.com/public_records/tax-deeds/List%20of%20Lands%20Available%20for%20Taxes%2020261014.pdf"
    # the same link is not a successor of itself; another host is never followed
    assert H.discover_successor_pdf(PASCO_PAGE, got, page_url=page) is None
    # without a page url only the Municode rule applies (unchanged behaviour)
    assert H.discover_successor_pdf(PASCO_PAGE, dead) is None


PASCO_SOURCE_PAGE = """<html><body>
<a href="/201/Tax-Deed-Sales">Tax Deed Sales</a>
<a href="http://app.pascoclerk.com/appdot-public-statistical-reports-taxdeeds.asp">Lists of Lands</a>
<a href="/202/Purchasing-Property-off-the-Lists-of-Lan">Purchasing Property off the Lists of Lands</a>
<a href="https://lists-of-lands.example.com/x">Lists of Lands elsewhere</a>
</body></html>"""


def test_one_hop_to_the_countys_own_list_index():
    import harvest_laft_pdfs as H  # noqa: PLC0415
    page = "https://www.pascoclerk.com/202/Purchasing-Property-off-the-Lists-of-Lan"
    dead = "https://app.pascoclerk.com/public_records/tax-deeds/List%20of%20Lands%20Available%20for%20Taxes%2020260706.pdf"
    assert H.discover_successor_pdf(PASCO_SOURCE_PAGE, dead, page_url=page) is None
    # the page itself and another site are never followed; http is upgraded
    assert H.discover_list_index_pages(PASCO_SOURCE_PAGE, page, dead) == [
        "https://app.pascoclerk.com/appdot-public-statistical-reports-taxdeeds.asp"]


def test_successor_fetch_follows_one_index_hop(monkeypatch):
    import harvest_laft_pdfs as H  # noqa: PLC0415
    page_url = "https://www.pascoclerk.com/202/Purchasing-Property-off-the-Lists-of-Lan"
    index_url = "https://app.pascoclerk.com/appdot-public-statistical-reports-taxdeeds.asp"
    dead = "https://app.pascoclerk.com/public_records/tax-deeds/List%20of%20Lands%20Available%20for%20Taxes%2020260706.pdf"
    new = "https://app.pascoclerk.com/public_records/tax-deeds/List%20of%20Lands%20Available%20for%20Taxes%2020261014.pdf"

    class Resp:
        def __init__(self, url, text, code=200):
            self.url, self.text, self.status_code = url, text, code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise H.requests.exceptions.HTTPError(response=self)

    pages = {page_url: Resp(page_url, PASCO_SOURCE_PAGE), index_url: Resp(index_url, PASCO_PAGE)}
    gets = []
    monkeypatch.setattr(H.requests, "get", lambda u, **k: gets.append(u) or pages[u])

    def cond(_req, u, _entry, **_k):
        if u == dead:
            raise H.requests.exceptions.HTTPError(response=Resp(u, "", 404))
        return 200, b"%PDF", {}

    monkeypatch.setattr(H, "conditional_get", cond)
    status, content, _v, used, origin = H._fetch_with_successor(dead, page_url, None)
    assert used == new and content == b"%PDF" and gets == [page_url, index_url] and origin == page_url


# ==================== FL auction off-list close-out ====================

def _auction(i, county, sale, seen):
    return {"id": f"id{i}", "county": county, "case_no": f"C{i}", "status": "active", "sale_date": sale, "last_seen_at": seen}


def _closeout_fixture():
    rows = [
        _auction(1, "Lee", "2026-11-05", ago(hours=1)),        # read this run
        _auction(2, "Lee", "2026-11-05", None),                # never read, absent -> close
        _auction(3, "Lee", "2026-11-05", ago(days=5)),         # off the list 5 days -> close
        _auction(4, "Lee", "2026-11-05", ago(hours=20)),       # within 36 h -> keep
        _auction(5, "Lee", "2026-10-01", None),                # past-dated: the sync's own rule, not this one
        _auction(6, "Lee", None, None),                        # no sale date -> keep
        _auction(7, "Orange", "2026-11-05", None),             # county INCOMPLETE -> keep
        _auction(8, "Orange", "2026-11-05", ago(hours=1)),
        _auction(9, "Lee", "2026-11-05", None),                # never stamped but IN this run's harvest -> keep
        _auction(10, "Polk", "2026-11-05", None),              # COMPLETE but no row stamped this run -> county skipped
        _auction(11, "Polk", "2026-11-05", ago(days=4)),
    ]
    status = [{"county": "Lee", "status": "COMPLETE", "rowCount": 3}, {"county": "Orange", "status": "INCOMPLETE", "rowCount": 1},
              {"county": "Polk", "status": "COMPLETE", "rowCount": 1}]
    harvest = [{"county": "Lee", "case": "C1"}, {"county": "Lee", "case": "C9"}, {"county": "Orange", "case": "C8"},
               {"county": "Polk", "case": "C99"}]
    return rows, status, harvest


def test_offlist_closeout_plan():
    import auction_offlist_closeout as C  # noqa: PLC0415
    rows, status, harvest = _closeout_fixture()
    ids, rep = C.plan(rows, complete=C.complete_counties(status), harvested=C.harvested_cases(harvest), now=NOW)
    assert sorted(ids) == ["id2", "id3"]
    assert rep["by_county"] == {"Lee": 2}
    assert rep["counts"]["county_not_complete"] == 2 and rep["counts"]["on_current_list"] == 2
    assert rep["counts"]["county_newest_read_not_this_run"] == 2 and rep["counts"]["seen_within_grace"] == 1


def test_offlist_closeout_is_off_by_default(tmp_path, monkeypatch):
    import auction_offlist_closeout as C  # noqa: PLC0415
    rows, status, harvest = _closeout_fixture()
    for name, data in (("rows.json", rows), ("status.json", status), ("harvest.json", harvest)):
        (tmp_path / name).write_text(json.dumps(data))
    calls = []
    monkeypatch.setattr(C, "close", lambda *a, **k: calls.append(a) or 0)
    monkeypatch.delenv(C.FLAG, raising=False)
    args = ["--rows", str(tmp_path / "rows.json"), "--status", str(tmp_path / "status.json"),
            "--harvest", str(tmp_path / "harvest.json"), "--now", NOW.isoformat(), "--apply"]
    assert C.main(args) == 0 and calls == []
    r = subprocess.run([sys.executable, str(ROOT / "scripts/auction_offlist_closeout.py"), *args], capture_output=True, text=True,
                       check=True, env={"PATH": "/usr/bin:/bin"})
    assert "plan-only" in r.stdout and "would close 2" in r.stdout and "C2" not in r.stdout


def test_offlist_closeout_writes_status_closed_only():
    src = (ROOT / "scripts/auction_offlist_closeout.py").read_text()
    assert 'json.dumps({"status": "closed"})' in src
    for forbidden in ("result_amount", "result_date", "result_party", "winning_bid", "sold"):
        assert f'"{forbidden}"' not in src
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text()
    assert "AUCTION_OFFLIST_CLOSE: ${{ vars.AUCTION_OFFLIST_CLOSE }}" in wf
    assert "scripts/auction_offlist_closeout.py --status out/harvest_all_status.json" in wf


def test_offlist_closeout_missing_status_closes_nothing(tmp_path, capsys):
    import auction_offlist_closeout as C  # noqa: PLC0415
    assert C.main(["--status", str(tmp_path / "none.json"), "--harvest", str(tmp_path / "none2.json")]) == 0
    assert "fail closed" in capsys.readouterr().out
