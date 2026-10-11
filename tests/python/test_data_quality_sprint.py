"""Data-quality sprint, Fix 1 (2026-10-10): protect the two baselines verified
read-only in production.

* Horry SC (run 37971480332, commit 09ee30b incl. e7040d2, SC job
  113958930434): 51 active rows, 0 bid / purchase_amount discrepancies
  (down from 23), every amount at 2 dp, no missing amount.
* Tennessee Shelby (TN job 113958930478): portal 12,884 rows, 2,038 offered,
  10,846 not offered, COMPLETE, 0 malformed / duplicate ids, 2,038 synced,
  0 closed, 1 row without coordinates, 1 row NOT_PUBLISHED, all UNREVIEWED.

The figures above live (counts only) in
data/current_state/verified-baselines-2026-10-10.json. These tests run the
real code paths on synthetic inputs in the live shapes; nothing here reaches
the network or a database.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import harvest_expansion as HE  # noqa: E402
import source_publication as SP  # noqa: E402
import sync_state_inventory as SY  # noqa: E402
from harvesters.otc.adapters import epropertyplus as EPP, expansion as EX  # noqa: E402
from harvesters.otc.adapters.tabular import TabularListAdapter  # noqa: E402
from harvesters.otc.model import AmountKind, to_cents  # noqa: E402

AT = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
OBS = "2026-10-10T12:00:00+00:00"
TN_FX = ROOT / "tests/python/fixtures/tennessee/tn_shelby_landbank.json"
BASELINE = ROOT / "data/current_state/verified-baselines-2026-10-10.json"
TN_SID, HORRY_SID = "tn_shelby_landbank", "sc_horry_forfeited_land"


# ------------------------------------------------------------------ baseline file

def test_verified_baseline_file_is_counts_only_and_internally_consistent():
    b = json.loads(BASELINE.read_text(encoding="utf-8"))
    h, t = b["horry_sc"], b["tennessee_shelby"]
    assert h["evidence"]["run"] == "37971480332" and h["evidence"]["job"] == "113958930434"
    assert h["active_rows"] == 51 and h["bid_amount_discrepancies"] == 0 and h["bid_amount_discrepancies_before"] == 23
    assert h["amounts_not_2dp"] == 0 and h["missing_amounts"] == 0
    assert t["evidence"]["job"] == "113958930478"
    assert t["portal_rows"] == t["offered"] + t["not_offered"] == 12884
    assert t["offered"] == t["synced"] == 2038 and t["closed"] == 0
    assert t["malformed_ids"] == t["duplicate_ids"] == 0 and t["read_status"] == "COMPLETE"
    assert t["without_coordinates"] == 1 and t["amount_not_published"] == 1
    assert t["publication_status"] == {"UNREVIEWED": 2038}
    # Counts only: no parcel, address, owner, case number or amount field anywhere.
    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    assert not {"parcel", "address", "owner_name", "case_no", "purchase_amount", "bid"} & set(keys(b))


# ------------------------------------------------------------------ Horry SC

def _horry_rows(cells):
    a = TabularListAdapter(EX.SC_HORRY_FLC)
    rows = [["PIN", "ITEM #", "DESCRIPTION", "MINIMUM BID"]] + cells
    return [r.to_properties_row() for r in a._records(rows, retrieved_at=AT, document_name=None)]


HORRY_CELLS = [["12345678901", "1", "LOT 1", "1234.5650000000001"],
               ["12345678902", "2", "LOT 2", "412.33999999999997"],
               ["12345678903", "3", "LOT 3", "0.30000000000000004"],
               ["12345678904", "4", "LOT 4", "900"]]


def _sc_reg():
    return SP.registry_with_reviews("SC", reviews={})[0]


def test_horry_bid_and_amount_agree_to_the_cent_and_are_2dp():
    out = _horry_rows(HORRY_CELLS)
    assert len(out) == 4
    for r in out:
        assert r["bid"] == r["purchase_amount"]
        assert round(r["purchase_amount"], 2) == r["purchase_amount"]
        assert abs(r["bid"] - r["purchase_amount"]) == 0
    assert [r["purchase_amount"] for r in out] == [1234.57, 412.34, 0.3, 900.0]


def test_horry_missing_amount_stays_missing_never_zero_as_a_price():
    out = _horry_rows([["12345678905", "5", "LOT 5", ""], ["12345678906", "6", "LOT 6", "N/A"]])
    for r in out:
        assert r["purchase_amount"] is None and r["purchase_amount_kind"] == AmountKind.NOT_PUBLISHED.value
        assert r["bid"] == 0                # the legacy sentinel, read through purchase_amount_kind


@pytest.mark.parametrize("x", [1234.565, 412.33999999999997, 0.1 + 0.2, 2.675, 900.0, 0.0])
def test_rounding_is_idempotent(x):
    assert to_cents(to_cents(x)) == to_cents(x)


def test_horry_rerun_of_the_same_input_is_idempotent():
    units = {(HORRY_SID, "Horry"): "COMPLETE", "Horry": "COMPLETE"}
    a, ca = SY.plan("SC", _horry_rows(HORRY_CELLS), _sc_reg(), units, observed_at=OBS)
    stored_first = {SY.identity(r): r["first_seen_at"] for r in a}
    stored_prov = {SY.identity(r): r["field_provenance"] for r in a}
    b, cb = SY.plan("SC", _horry_rows(HORRY_CELLS), _sc_reg(), units, observed_at=OBS,
                    stored_first_seen=stored_first, stored_provenance=stored_prov)
    assert a == b and ca == cb
    assert {r["last_seen_at"] for r in a} == {OBS}       # the read's own time, one value


def test_horry_sync_never_overwrites_unrelated_fields():
    """The sync sends only the list's own columns plus its lifecycle stamps:
    an enrichment column (flood, imagery, coordinates from a parcel layer)
    is never in the payload, so a re-read never nulls it; an enrichment
    provenance entry is kept verbatim."""
    rows = _horry_rows(HORRY_CELLS)
    stored = {SY.identity(r): {"flood_zone": {"source": "fema_nfhl", "recorded_at": "2026-10-01T00:00:00+00:00"},
                               "latitude": {"source": "statewide_parcel", "recorded_at": "2026-10-01T00:00:00+00:00"}}
              for r in rows}
    sent, _ = SY.plan("SC", rows, _sc_reg(), {(HORRY_SID, "Horry"): "COMPLETE"}, observed_at=OBS,
                      stored_provenance=stored)
    for r in sent:
        for col in ("flood_zone", "photo_url", "photo_source", "latitude", "longitude", "land_use", "taxable_value"):
            assert col not in r, col
        assert r["field_provenance"]["flood_zone"]["source"] == "fema_nfhl"
        assert r["field_provenance"]["latitude"]["source"] == "statewide_parcel"
        assert r["field_provenance"]["purchase_amount"]["source"] == "county_list"


# ------------------------------------------------------------------ Tennessee Shelby

def _pages():
    return json.loads(TN_FX.read_text(encoding="utf-8"))


def _fetch(pages):
    def fj(url):
        n = int(url.split("page=")[1].split("&")[0])
        return pages[min(n, len(pages)) - 1]
    return fj


def _tn_reg():
    return SP.registry_with_reviews("TN", reviews={})[0]


def _with_row(pages, row):
    p = copy.deepcopy(pages)
    p[-1]["rows"].append(row)
    for page in p:
        page["size"] += 1
    return p


def test_tn_only_offered_rows_identifiers_unique_and_normalised():
    res = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(_pages()), retrieved_at=AT)
    ids = [r.case_no for r in res.records]
    assert res.outcome == "COMPLETE" and len(ids) == len(set(ids))
    assert all(len(i) == 14 and i == i.strip().upper() and i.isalnum() for i in ids)
    assert all(r.parcel == r.case_no and r.source_status_text == "FOR SALE" for r in res.records)
    assert res.excluded_status + len(res.records) + res.rejected_ids + res.duplicates == res.rows_read


def test_tn_whitespace_in_a_portal_id_is_normalised_to_the_same_identity():
    pages = _pages()
    first = next(r for r in pages[0]["rows"] if r["currentStatus"] == "FOR SALE" and r["available"] == "Y")
    dup = dict(first, parcelNumber=f"  {first['parcelNumber']} ", id=999999)
    res = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(_with_row(pages, dup)), retrieved_at=AT)
    assert res.duplicates == 1 and [r.case_no for r in res.records].count(first["parcelNumber"]) == 1


def test_tn_offered_row_with_an_unrecognised_id_makes_the_read_incomplete_and_closes_nothing(tmp_path):
    """Defect fixed 2026-10-10: a rejected OFFERED id used to leave the read
    COMPLETE, and close-out treats COMPLETE as the whole list - a stored row
    the portal still offers under a reformatted id would have been closed."""
    pages = _pages()
    first = next(r for r in pages[0]["rows"] if r["currentStatus"] == "FOR SALE" and r["available"] == "Y")
    bad = dict(first, parcelNumber="070-012-0000-0003", id=999998)
    res = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(_with_row(pages, bad)), retrieved_at=AT)
    assert res.outcome == "INCOMPLETE" and res.rejected_ids == 1 and len(res.records) == 2
    assert "070-012" not in (res.error_detail or "")               # counts only, never the id
    fx = tmp_path / "bad.json"
    fx.write_text(json.dumps(_with_row(pages, bad)))
    out = tmp_path / "tn"
    assert HE.main(["--state", "TN", "--fixture", f"{TN_SID}={fx}", "--out-dir", str(out)]) == 0
    units = SY.units_for(out / "harvest_tn_status.json")
    assert SY.unit_status(units, TN_SID, "Shelby") == "INCOMPLETE"
    rows = json.loads((out / "tn_properties_rows.json").read_text())
    sent, counts = SY.plan("TN", rows, _tn_reg(), units, observed_at=OBS)
    assert counts["upsert"] == 2                                   # the good rows are still refreshed
    still_listed = {"id": "x", "state": "TN", "status": "active", "harvester_source": TN_SID, "source": "laft",
                    "county": "Shelby", "case_no": "07001200000003"}
    assert SY.plan_close("TN", rows, [still_listed], units, {TN_SID}) == []


@pytest.mark.parametrize("status", ["FAILED", "INCOMPLETE", None])
def test_tn_failed_incomplete_or_unread_closes_nothing(status):
    rows = []
    gone = {"id": "x", "state": "TN", "status": "active", "harvester_source": TN_SID, "source": "laft",
            "county": "Shelby", "case_no": "07001200000099"}
    units = {} if status is None else {(TN_SID, "Shelby"): status, "Shelby": status}
    assert SY.plan_close("TN", rows, [gone], units, {TN_SID}) == []


def test_tn_complete_read_syncs_every_offered_row_unreviewed():
    res = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(_pages()), retrieved_at=AT)
    rows = [r.to_properties_row() for r in res.records]
    sent, counts = SY.plan("TN", rows, _tn_reg(), {(TN_SID, "Shelby"): "COMPLETE"}, observed_at=OBS)
    assert counts["upsert"] == len(res.records) and counts["skipped_unit_not_read"] == 0
    assert {r["publication_status"] for r in sent} == {"UNREVIEWED"}
    assert all(r["list_url"] and r["last_seen_at"] == OBS and r["first_seen_at"] == OBS for r in sent)
    assert all(r["field_provenance"]["parcel"]["source"] == "county_list" for r in sent)


def test_tn_missing_amount_stays_explicitly_unpublished():
    res = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(_pages()), retrieved_at=AT)
    unpublished = [r for r in res.records if r.amount is None]
    assert len(unpublished) == 1
    row = unpublished[0].to_properties_row()
    assert row["purchase_amount"] is None and row["purchase_amount_kind"] == "NOT_PUBLISHED"
    assert unpublished[0].provenance["amount"] == "no amount on the row"
    for zero in ("0", 0, "", None, "N/A", -5):
        p = _pages()
        p[0]["rows"][0]["askingPrice"] = zero
        recs = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(p), retrieved_at=AT).records
        first = next(r for r in recs if r.provenance["portal_property_id"] == p[0]["rows"][0]["id"])
        assert first.amount is None and first.amount_kind is AmountKind.NOT_PUBLISHED


def test_tn_missing_coordinate_keeps_the_record_without_inventing_one():
    res = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(_pages()), retrieved_at=AT)
    no_coord = [r for r in res.records if r.latitude is None]
    assert len(no_coord) == 1 and not no_coord[0].validate()
    row = no_coord[0].to_properties_row()
    assert row.get("latitude") is None and row.get("longitude") is None
    assert "coordinates" not in no_coord[0].provenance
    for lat, lng in ((0, 0), ("", ""), (None, None), (95, -90), ("x", "y")):
        p = _pages()
        p[0]["rows"][0].update(latitude=lat, longitude=lng)
        recs = EPP.fetch_all(EX.TN_SHELBY_LANDBANK, _fetch(p), retrieved_at=AT).records
        first = next(r for r in recs if r.provenance["portal_property_id"] == p[0]["rows"][0]["id"])
        assert first.latitude is None and first.longitude is None and not first.validate()
    sent, counts = SY.plan("TN", [r.to_properties_row() for r in res.records], _tn_reg(),
                           {(TN_SID, "Shelby"): "COMPLETE"}, observed_at=OBS)
    assert counts["upsert"] == len(res.records)                    # still synced
    assert "latitude" not in sent[[r["case_no"] for r in sent].index(no_coord[0].case_no)]["field_provenance"]


# ------------------------------------------------------------------ Fix 3: source matrix

def test_source_quality_matrix_is_current_and_counts_only():
    import source_quality_report as SQ
    snap = ROOT / "data/current_state/source-quality-2026-10-10.json"
    assert SQ.main(["--snapshot", str(snap), "--out", str(ROOT / "docs/source-quality-matrix.md"), "--check"]) == 0
    data = json.loads(snap.read_text(encoding="utf-8"))
    allowed = {"state", "county", "source_id", "ledger", "publication", "last_seen_max"}
    for r in data["rows"]:
        for k, v in r.items():
            assert k in allowed or isinstance(v, int), k            # every other field is a count
        assert r["active"] >= max(r[k] for k in ("parcel", "coords", "flood_checked", "amount", "source_link"))
    sql = (ROOT / "scripts/sql/source_quality_matrix.sql").read_text(encoding="utf-8").lower()
    assert not any(w in sql for w in ("insert ", "update ", "delete ", "alter ", "drop ", "create "))


def test_source_matrix_reports_every_cell_with_its_denominator():
    import source_quality_report as SQ
    rows = [{"state": "TN", "county": "Shelby", "source_id": SID_TN, "ledger": "laft", "active": 4, "parcel": 4,
             "coords": 3, "flood_checked": 0, "amount": 3, "source_link": 4, "list_as_of": 0, "path_typed": 0,
             "provenance": 4, "never_seen": 0, "seen_gt36h": 0, "past_sale": 0, "parcel_no_digit": 0, "dup_parcel": 0,
             "bid_amount_mismatch": 0, "link_not_https": 0, "list_as_of_future": 0, "seen_order_bad": 0,
             "publication": "UNREVIEWED", "last_seen_max": "2026-10-09T18:19:42+00:00"}]
    text = SQ.render({"measured_at": "t", "evidence": "e", "baseline_commit": "0000000", "rows": rows})
    assert "| 4 | 4/4 | 3/4 | 0/4 | 3/4 |" in text and "UNREVIEWED" in text


SID_TN = "tn_shelby_landbank"


# ------------------------------------------------------------------ Fix 3/4: Texas cause numbers

def test_texas_vendor_rows_store_the_cause_in_parcel_and_the_frontend_knows_it():
    """harvesters/texas_harvester.py maps the tax-suit Cause Number to `parcel`
    and the CAD account to `case_no`; production 2026-10-10 had 32 LGBS causes
    each on 2-26 different active rows. app.js must use the account as the
    parcel identity (cross-ledger matching, labels) and call the cause a cause."""
    th = (ROOT / "harvesters/texas_harvester.py").read_text(encoding="utf-8")
    assert "cause_number: str | None = None  # legal tax-suit cause/case number - maps to DB `parcel`" in th
    assert '"parcel": raw.get("cause_nbr")' in (ROOT / "scripts/lgbs_available_refresh.py").read_text(encoding="utf-8")
    app = (ROOT / "public/app.js").read_text(encoding="utf-8")
    assert '["tx_lgbs", "tx_realauction"].indexOf(p.harvester_source || p.source_id || "")' in app
    assert "const raw = p && parcelOf(p) ? String(parcelOf(p)) : \"\";" in app        # parcelKey
    assert 'prop.push(row("Tax suit cause #", esc(causeOf(p)), "mono"));' in app
    assert app == (ROOT / "app.js").read_text(encoding="utf-8")                      # root mirror


# ------------------------------------------------------------------ Horry: the discrepancy rule itself

@pytest.mark.parametrize("a, b, want", [
    (1234.565, 1234.57, False),          # numeric scale only: the 23-row false positive of 2026-10-09
    (0.1 + 0.2, 0.3, False),
    (1234.5600000000002, 1234.56, False),
    (1234.56, 1234.57, True),            # a real cent is detected
    (900.0, 901.0, True),
    (None, 900.0, None), (900.0, None, None), (None, None, None),   # missing is never "equal"
])
def test_amounts_disagree(a, b, want):
    from harvesters.otc.model import amounts_disagree
    assert amounts_disagree(a, b) is want


def test_a_second_sync_of_horry_rows_reports_no_discrepancy():
    """Rows as stored after one sync (bid numeric(12,2), purchase_amount as sent)
    compared on the next run: no false discrepancy, ever."""
    from harvesters.otc.model import amounts_disagree
    for run in range(2):
        for r in _horry_rows(HORRY_CELLS):
            stored_bid = float(f"{r['bid']:.2f}")          # what numeric(12,2) keeps
            assert amounts_disagree(stored_bid, r["purchase_amount"]) is False, run
    sql = (ROOT / "scripts/sql/source_quality_matrix.sql").read_text()
    assert "round(bid::numeric, 2) <> round(purchase_amount::numeric, 2)" in sql
