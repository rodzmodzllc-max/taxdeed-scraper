"""MI-2 (2026-11-08): county layers that keep publishing an auction's rows
after the sale (Lenawee / Eaton MI) left them 'active' forever, because the
expansion sync closed only on absence. A listed auction row more than a day
past its sale date, with no result, is now written 'closed' - never 'sold'.
Synthetic rows only; no network, no database."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import inventory_status as IS  # noqa: E402
import sync_state_inventory as SY  # noqa: E402

OBS = "2026-11-08T12:00:00+00:00"
TODAY = date(2026, 11, 8)


def _adapter_row(sale_date, n="1", **kw):
    row = {"state": "MI", "source": "auction", "source_id": "mi_lenawee_tax_sale", "county": "Lenawee",
           "case_no": f"SYN-{n}", "parcel": f"SYN-{n}", "status": "active", "sale_date": sale_date,
           "otc_provenance": {"adapter": "arcgis", "source_id": "mi_lenawee_tax_sale"}}
    row.update(kw)
    return row


def _plan(rows, state="MI", units=None, stored_values=None):
    return SY.plan(state, rows, SY.registry_rows(state), units or {"Lenawee": "COMPLETE"},
                   observed_at=OBS, stored_values=stored_values)


def test_past_sale_date_rules():
    today = TODAY
    assert SY.past_sale_date(_adapter_row("2026-10-06"), today) == "2026-10-06"
    assert SY.past_sale_date(_adapter_row("2026-11-07"), today) is None          # within the one-day grace
    assert SY.past_sale_date(_adapter_row("2026-11-20"), today) is None          # upcoming
    assert SY.past_sale_date(_adapter_row(None), today) is None                  # no date: never a guess
    assert SY.past_sale_date(_adapter_row("not a date"), today) is None
    assert SY.past_sale_date(_adapter_row("2026-10-06", status="closed"), today) is None
    assert SY.past_sale_date(_adapter_row("2026-10-06", result_amount=100), today) is None
    assert SY.past_sale_date(_adapter_row("2026-10-06", source="laft"), today) is None
    assert SY.past_sale_date(_adapter_row("2026-10-06", state="TX"), today) is None
    # Dane WI: the date is a bid deadline on a standing table - still offered.
    assert SY.past_sale_date(_adapter_row("2026-10-06", source_id="wi_dane_tax_deed_auction"), today) is None


def test_listed_past_sale_rows_are_closed_never_sold_and_upcoming_rows_stay_active():
    rows = [_adapter_row("2026-10-06", "1"), _adapter_row("2026-10-06", "2"), _adapter_row("2026-12-01", "3")]
    sent, counts = _plan(rows)
    by_case = {r["case_no"]: r for r in sent}
    assert counts["closed_past_sale"] == 2
    for n in ("SYN-1", "SYN-2"):
        r = by_case[n]
        assert r["status"] == "closed" and r["delisted_at"] == OBS and r["last_seen_at"] == OBS
        assert r["otc_provenance"]["closed_past_sale"] == "2026-10-06"
        assert r.get("result_amount") is None and r.get("result_date") is None
    assert by_case["SYN-3"]["status"] == "active" and by_case["SYN-3"]["delisted_at"] is None
    assert "closed_past_sale" not in by_case["SYN-3"]["otc_provenance"]


def test_a_second_run_keeps_the_stored_delisted_at():
    stored = {("auction", "Lenawee", "SYN-1"): {"status": "closed", "delisted_at": "2026-11-01T00:00:00+00:00"}}
    sent, _ = _plan([_adapter_row("2026-10-06", "1")], stored_values=stored)
    assert sent[0]["delisted_at"] == "2026-11-01T00:00:00+00:00"


def test_a_source_sold_flag_still_wins():
    row = _adapter_row("2026-10-06", status="closed", inventory_status_raw="Sold: Yes")
    sent, counts = _plan([row])
    assert sent[0]["status"] == "closed" and "closed_past_sale" not in counts
    assert IS.status_for_row(dict(sent[0], harvester_source="mi_lenawee_tax_sale"), today=TODAY).status == "sold"


def test_inventory_status_names_the_date_never_a_result():
    sent, _ = _plan([_adapter_row("2026-10-06")])
    obs = IS.status_for_row(dict(sent[0], harvester_source="mi_lenawee_tax_sale"), today=TODAY)
    assert (obs.status, obs.basis) == ("closed", "SCHEDULED_DATE")
    assert "2026-10-06" in obs.note and "no result" in obs.note
