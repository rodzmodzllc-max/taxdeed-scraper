"""Florida data-accuracy defects found 2026-11-07/08 (synthetic fixtures only).

FL-D1  ledgers / Home say "N hidden by you" (rows this account hid).
FL-D3  the deeds job's FEMA flood step is scoped to Florida.
FL-D4  (already fixed on main as LA-2; see test_la_data_accuracy.py).
FL-D5  St. Lucie rows sharing a case number are no longer silently dropped.
FL-D6  deeds unit freshness uses the registry's source ids.
FL-D8  source_health counts an EMPTY read as complete.
FL-D11 the PDF identifier gate logs its rejection reasons (counts only).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

WORKFLOW = REPO / ".github/workflows/harvest-and-sync.yml"

# The St. Lucie harvester imports playwright at module load; only parsing is
# tested here (same stub as test_laft_harvester_gates.py).
try:
    import playwright.sync_api  # noqa: F401
except ImportError:
    import types
    _pw, _sa = types.ModuleType("playwright"), types.ModuleType("playwright.sync_api")
    _sa.sync_playwright = None
    sys.modules.setdefault("playwright", _pw)
    sys.modules.setdefault("playwright.sync_api", _sa)


def _steps(job: str) -> list[dict]:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return wf["jobs"][job]["steps"]


def _step(job: str, name_part: str) -> dict:
    hits = [s for s in _steps(job) if name_part in str(s.get("name", ""))]
    assert len(hits) == 1, (job, name_part, [s.get("name") for s in hits])
    return hits[0]


# ---------------------------------------------------------------- FL-D1

def test_d1_ledgers_and_home_name_rows_hidden_by_this_account():
    src = (REPO / "public/app.js").read_text(encoding="utf-8")
    assert "function hiddenByYouCount(kind)" in src and "${hiddenByYouLineHtml(kind)}" in src
    assert 'if (action === "openhidden") { openHiddenModal(); return; }' in src
    assert 'class="home-ledger-hidden" data-hidden-ledger=' in src
    # The root mirror is the deployed copy.
    assert (REPO / "app.js").read_text(encoding="utf-8") == src


# ---------------------------------------------------------------- FL-D3

def test_d3_deeds_flood_step_is_scoped_to_florida():
    step = _step("deeds", "Backfill FEMA flood hazard")
    assert step["run"].strip().endswith("scripts/enrich_flood_zone.py")
    assert step["env"]["ENRICH_STATE"] == "FL"


def test_d3_every_flood_step_names_its_states():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job, spec in wf["jobs"].items():
        for s in spec.get("steps", []):
            if "enrich_flood_zone.py" in str(s.get("run", "")):
                assert (s.get("env") or {}).get("ENRICH_STATE"), (job, s.get("name"))


# FL-D4 (snapshot read by keyset) is fixed and tested on main as LA-2:
# tests/python/test_la_data_accuracy.py.


# ---------------------------------------------------------------- FL-D5

def _grid(rows: list[list[str]], extra: str = "") -> str:
    head = "<tr>" + "".join(f"<td>{h}</td>" for h in
                            ["Applicant", "Case Number", "Certificate Number", "Issue Year", "Parcel ID",
                             "Sale Date", "Current Status", "Opening Bid", "Property Owners"]) + "</tr>"
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<html><table id='dgResults'>{head}{body}{extra}</table></html>"


def _row(case, cert, parcel):
    return ["APPL", case, cert, "2020", parcel, "01/01/2026", "LA", "$100.00", "OWNER"]


def test_d5_distinct_parcels_under_one_case_are_all_kept():
    import harvest_laft_stlucie as H
    html = _grid([_row("C1", "X1", "P1"), _row("C1", "X2", "P2"), _row("C2", "X3", "P3")])
    rows, outcome = H._parse_results_with_outcome(html)
    assert [r["case_no"] for r in rows] == ["C1/P1", "C1", "C2"]   # the last row keeps the stored identity
    assert len({r["case_no"] for r in rows}) == 3
    assert outcome["shared_case"] == {"cases": 1, "rows": 2, "distinct_parcels": 2, "distinct_certificates": 2,
                                      "duplicate_rows_dropped": 0, "rows_renamed": 1}
    assert outcome["rows"] == 3


def test_d5_one_parcel_listed_twice_is_one_property():
    import harvest_laft_stlucie as H
    html = _grid([_row("C1", "X1", "P1"), _row("C1", "X2", "P1")])
    rows, outcome = H._parse_results_with_outcome(html)
    assert len(rows) == 1 and rows[0]["case_no"] == "C1" and rows[0]["certificate_no"] == "X2"
    assert outcome["shared_case"]["duplicate_rows_dropped"] == 1 and outcome["rows"] == 1


def test_d5_grid_rows_with_another_cell_count_are_counted():
    import harvest_laft_stlucie as H
    html = _grid([_row("C1", "X1", "P1")], extra="<tr><td>1</td><td>2</td></tr>")
    rows, outcome = H._parse_results_with_outcome(html)
    assert len(rows) == 1 and outcome["skipped_rows"] == 1


# ---------------------------------------------------------------- FL-D6

def test_d6_deeds_unit_freshness_uses_registry_source_ids():
    run = _step("deeds", "Per-unit freshness (deed auction counties)")["run"]
    assert "harvest_all_status.json:fl_realauction" in run
    assert "--county-source Okaloosa=fl_bid4assets_okaloosa" in run and "fl_deeds" not in run
    import csv
    reg = list(csv.DictReader((REPO / "data/county_source_registry.csv").open(encoding="utf-8")))
    ids = {(r["county"], r["source_id"]) for r in reg if r["state"] == "FL"}
    assert ("Alachua", "fl_realauction") in ids and ("Okaloosa", "fl_bid4assets_okaloosa") in ids


def test_d6_county_source_override_end_to_end(tmp_path):
    status = tmp_path / "s.json"
    status.write_text(json.dumps([{"county": "Alachua", "status": "COMPLETE", "rowCount": 4, "reason": "ok"},
                                  {"county": "Okaloosa", "status": "COMPLETE", "rowCount": 0, "reason": "ok"},
                                  {"county": "Pasco", "status": "COMPLETE", "rowCount": 1, "source_id": "fl_laft_pdfs"}]),
                      encoding="utf-8")
    persist, report = tmp_path / "p.json", tmp_path / "r.json"
    env = {"PATH": "/usr/bin:/bin", "HTTPS_PROXY": "http://127.0.0.1:9"}
    r = subprocess.run([sys.executable, str(REPO / "scripts/unit_freshness.py"), "--status", f"{status}:fl_realauction",
                        "--county-source", "Okaloosa=fl_bid4assets_okaloosa", "--persist", str(persist), "--report", str(report)],
                       capture_output=True, text=True, cwd=REPO, env=env)
    assert r.returncode == 0, r.stderr
    rec = json.loads(persist.read_text(encoding="utf-8"))
    # An entry's own source_id always wins over both defaults.
    assert set(rec) == {"FL|fl_realauction|Alachua", "FL|fl_bid4assets_okaloosa|Okaloosa", "FL|fl_laft_pdfs|Pasco"}


# ---------------------------------------------------------------- FL-D8

def test_d8_empty_is_a_complete_read():
    import source_health as sh
    status = [{"county": "A", "status": "COMPLETE"}, {"county": "B", "status": "EMPTY"},
              {"county": "C", "status": "INCOMPLETE"}, {"county": "D", "status": "FAILED"}]
    assert sh.units_from_status(status) == (["A", "B"], ["C", "D"])
    assert sh.units_from_status({"sources": {"x": {"status": "EMPTY"}}}) == (["x"], [])


# ---------------------------------------------------------------- FL-D11

def test_d11_rejection_reasons_are_codes_never_values():
    import laft_status as LS
    assert LS.identifier_rejection_reason("12-34") is None
    assert LS.identifier_rejection_reason("IDNUMBER") == "no_digit"
    assert LS.identifier_rejection_reason("12\n34") == "line_break"
    assert LS.identifier_rejection_reason("1" * 41) == "too_long"
    assert LS.record_rejection_reason({"parcel": "PARCEL", "case_no": "1"}) == "parcel_no_digit"
    assert LS.record_rejection_reason({"case_no": "x" * 61 + "1"}) == "case_no_too_long"
    assert LS.record_rejection_reason({"parcel": "1", "case_no": "2"}) is None


def test_d11_pdf_table_rejections_are_counted_per_reason():
    import harvest_laft_pdfs as H
    log = H.RejectLog()
    H._reject(log, {"parcel": "Parcel #"})
    H._reject(log, {"parcel": "Parcel #"})
    H._reject(log, {"case_no": "12\n34"})
    assert len(log) == 3 and dict(log.reasons) == {"parcel_no_digit": 2, "case_no_line_break": 1}
    plain: list = []
    H._reject(plain, {"parcel": "x"})
    assert plain == [1]
    src = (REPO / "scripts/harvest_laft_pdfs.py").read_text(encoding="utf-8")
    assert 'outcome["rejected_reasons"] = dict(sorted(rejected.reasons.items()))' in src


def test_d11_pasco_registry_url_is_the_list_read_on_2026_11_07():
    import csv
    reg = [r for r in csv.DictReader((REPO / "data/county_source_registry.csv").open(encoding="utf-8"))
           if r["state"] == "FL" and r["county"] == "Pasco" and r["source_id"] == "fl_laft_pdfs"]
    assert len(reg) == 1 and re.search(r"Taxes%2020261028\.pdf$", reg[0]["document_url"])
