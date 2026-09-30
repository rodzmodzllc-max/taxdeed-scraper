"""Auction-outcome evidence sprint (2026-09-30): a verified outcome is written
only from a source-published, reviewed wording on a deterministically
matched, property-specific item; everything else stays honestly unknown.

Every source document here is SYNTHETIC (tests/python/fixtures/realauction/,
marked as such); the wordings are those the approved source was observed to
publish (data/auction_outcome_wordings.csv cites the capture runs)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import auction_outcomes as AO  # noqa: E402
import realauction_results as RR  # noqa: E402

FIX = REPO / "tests" / "python" / "fixtures" / "realauction"
APP = (REPO / "public" / "app.js").read_text(encoding="utf-8")
WF = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
NOW = "2026-09-30T15:00:00+00:00"
URL = "https://jackson.realtaxdeed.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=09/29/2026"


def W(raw, result, amount_label=""):
    return AO.Wording("realauction", raw, result, amount_label, True, "2026-09-30", "36729752890")


WORDS = {w.key(): w for w in [W("Auction Sold", "sold", "Amount"), W("Canceled per County", "cancelled"),
                              W("Redeemed", "redeemed"), W("Withdrawn", "withdrawn"), W("Struck Off", "struck_off")]}


def ev(i="e1", case="2024 TD 0001", county="Jackson", day="2026-09-29", parcel="21-4N-10-0000-0030-0120", **kw):
    base = {"id": i, "property_id": "p" + i, "county": county, "case_no": case, "scheduled_sale_date": day,
            "lifecycle": "scheduled", "outcome": "unknown", "outcome_raw": None, "parcel": parcel}
    base.update(kw)
    return base


def rec(case="2024 TD 0001", parcel="21-4N-10-0000-0030-0120", raw="Auction Sold", label="Amount", amount="$12,300.00",
        county="Jackson", day="2026-09-29"):
    return AO.ResultRecord("realauction", county, day, case, parcel, raw, label, amount, URL)


def read(*records, ok=True, error=None, county="Jackson", day="2026-09-29"):
    return AO.DayRead(county, day, ok, error, list(records), True, URL)


def plan(reads, events, words=WORDS, last=None):
    return AO.plan_outcomes(reads, events, words, observed_at=NOW, run_id="r1", last_closed=last)


# ==================== no inference ====================

def test_01_passed_sale_date_alone_writes_nothing():
    p = plan([read()], [ev(scheduled_sale_date="2026-09-01")])
    assert p.observations == [] and p.patches == []


def test_02_03_disappearance_is_never_sold_or_redeemed():
    # The event is absent from the closed listing: nothing is written for it.
    p = plan([read(rec(case="OTHER"))], [ev()])
    assert p.patches == [] and all(o["event_id"] != "e1" for o in p.observations)
    assert "sold" not in json.dumps(p.patches) and "redeemed" not in json.dumps(p.patches)


# ==================== deterministic matching ====================

def test_04_exact_case_number_produces_the_outcome():
    p = plan([read(rec())], [ev()])
    (eid, patch), = p.patches
    assert eid == "e1" and patch["outcome"] == "sold" and patch["lifecycle"] == "completed"
    assert patch["outcome_raw"] == "Auction Sold" and patch["outcome_observed_at"] == NOW
    obs, = p.observations
    assert obs["feed"] == "closed" and obs["evidence_url"] == URL and obs["raw_status"] == "Auction Sold"


def test_05_exact_parcel_matches_only_when_no_case_is_published():
    m = AO.match_record(rec(case=""), [ev()])
    assert m.event["id"] == "e1" and m.key == "parcel"
    m2 = AO.match_record(rec(case=""), [ev(), ev(i="e2", case="X")])   # two events share the parcel
    assert m2.event is None and m2.reason == "ambiguous parcel"


def test_06_fuzzy_owner_or_address_cannot_match():
    # Case differs by one character, parcel absent, same county/day: no match.
    assert AO.match_record(rec(case="2024 TD 0002", parcel=""), [ev()]).event is None
    # A near-identical parcel is not the parcel.
    assert AO.match_record(rec(case="", parcel="21-4N-10-0000-0030-0121"), [ev()]).event is None
    src = (REPO / "scripts" / "auction_outcomes.py").read_text()
    body = src.split("def match_record")[1].split("def published_amount")[0]
    code = re.sub(r'"""[\s\S]*?"""', "", body)   # the docstring names what is NOT consulted
    assert not re.search(r"difflib|fuzz|levenshtein|owner|address|legal", code)


def test_06b_conflicting_parcel_refuses_the_case_match():
    m = AO.match_record(rec(parcel="99-99"), [ev()])
    assert m.event is None and "differs" in m.reason
    p = plan([read(rec(parcel="99-99"))], [ev()])
    assert p.patches == [] and p.stats["refused_conflict"] == 1


def test_07_record_without_any_identifier_cannot_produce_an_outcome():
    p = plan([read(rec(case="", parcel=""))], [ev()])
    assert p.patches == [] and p.observations == []
    assert p.stats["unmatched_reasons"] == {"the record publishes no case number or parcel": 1}


# ==================== evidence validity ====================

def test_08_login_page_is_not_evidence():
    assert AO.evidence_refusal(URL, page_text="<form>User Name ... User Password</form>") == "login page"
    assert RR.is_login_page("<input name=x> User Name User Password") is True
    f = RR.FetchResult(host="h", sale_date="09/29/2026", url=URL, ok=False, login_page=True)
    assert AO.records_from_realauction("Jackson", "2026-09-29", f).ok is False


def test_09_search_engine_result_is_not_evidence():
    assert AO.evidence_refusal("https://www.google.com/search?q=jackson+tax+deed") == "search engine result"
    p = plan([AO.DayRead("Jackson", "2026-09-29", True, None,
                         [AO.ResultRecord("realauction", "Jackson", "2026-09-29", "2024 TD 0001", "", "Auction Sold", "", "",
                                          "https://www.bing.com/search?q=x")], True, "https://www.bing.com/")], [ev()])
    assert p.patches == []


def test_10_homepage_is_not_evidence():
    assert AO.evidence_refusal("https://jackson.realtaxdeed.com/") == "homepage"
    assert AO.evidence_refusal("http://jackson.realtaxdeed.com/index.cfm?x=1") == "not https"
    assert AO.evidence_refusal(URL) is None


# ==================== explicit results ====================

@pytest.mark.parametrize("raw,outcome,lifecycle", [
    ("Auction Sold", "sold", "completed"), ("Struck Off", "struck_off", "completed"),
    ("Withdrawn", "unknown", "withdrawn"), ("Canceled per County", "unknown", "cancelled"),
    ("Redeemed", "redeemed", "cancelled")])
def test_11_to_15_each_published_result_is_captured(raw, outcome, lifecycle):
    p = plan([read(rec(raw=raw, label="", amount=""))], [ev()])
    (_eid, patch), = p.patches
    assert (patch["outcome"], patch["lifecycle"], patch["outcome_raw"]) == (outcome, lifecycle, raw)


def test_15b_redemption_only_when_published():
    # Unmapped wording ("Canceled per Bankruptcy" is not in this table) is never redemption.
    p = plan([read(rec(raw="Canceled per Bankruptcy", label="", amount=""))], [ev()])
    assert p.patches == [] and p.observations[0]["outcome"] == "unknown"
    assert p.observations[0]["raw_status"] == "Canceled per Bankruptcy"


def test_16_published_amount_is_captured_only_beside_its_label():
    (_e, patch), = plan([read(rec())], [ev()]).patches
    assert patch["winning_bid"] == 12300.0


def test_17_unpublished_amount_stays_null():
    (_e, patch), = plan([read(rec(label="", amount=""))], [ev()]).patches
    assert "winning_bid" not in patch
    (_e, patch2), = plan([read(rec(label="Opening Bid", amount="$500.00"))], [ev()]).patches
    assert "winning_bid" not in patch2   # a different label is not the sale amount
    (_e, patch3), = plan([read(rec(raw="Canceled per County", label="Amount", amount="$9.00"))], [ev()]).patches
    assert "winning_bid" not in patch3   # an amount beside a non-sale result is never a sale amount


def test_18_19_bid_count_and_bidder_are_never_written():
    p = plan([read(rec())], [ev()])
    for _e, patch in p.patches:
        assert not ({"bid_count", "winning_bidder_ref"} & set(patch))
    assert all(o["bid_count"] is None for o in p.observations)
    with pytest.raises(AO.OutcomeError):
        AO.check_patch({"outcome": "sold", "lifecycle": "completed", "outcome_raw": "x", "outcome_observed_at": NOW,
                        "winning_bidder_ref": "3rd Party Bidder"})
    # The purchaser category the source prints (ST) is never read into a record.
    assert "\"ST\"" not in (REPO / "scripts" / "auction_outcomes.py").read_text()


# ==================== lifecycle ====================

def test_20_temporary_source_failure_preserves_the_verified_outcome():
    verified = ev(outcome="sold", lifecycle="completed", outcome_raw="Auction Sold")
    p = plan([read(ok=False, error="HTTP 503")], [verified])
    assert p.patches == [] and p.observations == [] and p.stats["days_unavailable"] == 1
    # A later "no wording" check never downgrades it either.
    p2 = plan([read(rec(raw="", label="", amount=""))], [verified])
    assert p2.patches == [] and p2.observations == []


def test_21_verified_result_supersedes_unknown_by_appending():
    last = {"e1": {"outcome": "unknown", "raw_status": None, "lifecycle": "scheduled"}}
    p = plan([read(rec())], [ev()], last=last)
    assert len(p.observations) == 1 and p.patches[0][1]["outcome"] == "sold"
    # nothing is deleted or updated in the observation table by construction
    src = (REPO / "scripts" / "auction_outcomes.py").read_text()
    assert "DELETE" not in src and '"PATCH", f"auction_event_observations' not in src


def test_21b_an_unchanged_recheck_appends_nothing():
    last = {"e1": {"outcome": "unknown", "raw_status": None, "lifecycle": "scheduled"}}
    p = plan([read(rec(raw="", label="", amount=""))], [ev()], last=last)
    assert p.observations == []
    same = ev(outcome="sold", lifecycle="completed", outcome_raw="Auction Sold")
    assert plan([read(rec())], [same]).patches == []


def test_24_provenance_survives_lifecycle_changes():
    (_e, patch), = plan([read(rec(raw="Canceled per County", label="", amount=""))], [ev()]).patches
    obs = plan([read(rec(raw="Canceled per County", label="", amount=""))], [ev()]).observations[0]
    assert patch["outcome_raw"] and obs["evidence_url"].startswith("https://") and obs["feed"] == "closed"


# ==================== wording table ====================

def test_wording_table_is_valid_and_every_enabled_row_cites_an_observation():
    words = AO.load_wordings()
    for w in words.values():
        assert w.enabled and AO._DATE.match(w.verified_on) and w.evidence_run.strip()
        assert w.result in AO.RESULTS


def test_wording_table_refuses_unreviewed_rows(tmp_path):
    p = tmp_path / "w.csv"
    p.write_text(",".join(AO.WORDING_COLUMNS) + "\nrealauction,Auction Sold,sold,,true,,,\n")
    with pytest.raises(AO.OutcomeError):
        AO.load_wordings(p)
    p.write_text(",".join(AO.WORDING_COLUMNS) + "\nrealauction,Canceled,cancelled,Amount,true,2026-09-30,1,\n")
    with pytest.raises(AO.OutcomeError):
        AO.load_wordings(p)   # an amount label only on a sale
    p.write_text(",".join(AO.WORDING_COLUMNS) + "\nrealauction,Gone,vanished,,true,2026-09-30,1,\n")
    with pytest.raises(AO.OutcomeError):
        AO.load_wordings(p)   # the result vocabulary is finite


# ==================== RealAuction adapter (synthetic fixtures) ====================

def _fetch(area_file, update_file):
    body = (FIX / area_file).read_text()
    upd = (FIX / update_file).read_text() if update_file else None
    f = RR.FetchResult(host="jackson.realtaxdeed.com", sale_date="09/29/2026", url=URL, ok=True, pages=1)
    f.items = RR.parse_items(body)
    f.aids = RR.rlist_ids(body)
    f.update_raw = upd
    return f


def test_fixture_files_are_marked_synthetic():
    for f in FIX.iterdir():
        if f.suffix == ".json":
            assert "SYNTHETIC" in json.loads(f.read_text()).get("_fixture", ""), f.name


def test_realauction_adapter_joins_items_to_status_by_the_sites_own_id():
    r = AO.records_from_realauction("Jackson", "2026-09-29", _fetch("closed_area.json", "status_refresh.json"))
    assert r.ok and [x.case_no for x in r.records] == ["2024 TD 0001", "2024 TD 0002", "2024 TD 0003"]
    assert [x.raw_wording for x in r.records] == ["Auction Sold", "Canceled per County", ""]
    assert r.records[0].amount_label == "Amount" and r.records[0].amount_text == "$12,300.00"


def test_realauction_adapter_without_status_refresh_is_unavailable_not_unknown():
    r = AO.records_from_realauction("Jackson", "2026-09-29", _fetch("closed_area.json", None))
    assert r.ok is False and "status refresh" in r.error


def test_realauction_fixture_end_to_end():
    r = AO.records_from_realauction("Jackson", "2026-09-29", _fetch("closed_area.json", "status_refresh.json"))
    evs = [ev("e1", "2024 TD 0001", parcel="21-4N-10-0000-0030-0120"), ev("e2", "2024 TD 0002", parcel="21-4N-10-0000-0030-0130"),
           ev("e3", "2024 TD 0003", parcel="")]
    p = plan([r], evs)
    got = {e: patch for e, patch in p.patches}
    assert got["e1"]["outcome"] == "sold" and got["e1"]["winning_bid"] == 12300.0
    assert got["e2"]["lifecycle"] == "cancelled" and got["e2"]["outcome"] == "unknown"
    assert "e3" not in got and any(o["event_id"] == "e3" and o["outcome"] == "unknown" for o in p.observations)


# ==================== ledger separation / safety ====================

def test_22_a_failed_auction_never_writes_the_available_ledger():
    src = (REPO / "scripts" / "auction_outcomes.py").read_text()
    assert "properties?" in src and "PATCH\", f\"properties" not in src
    assert "source=eq.laft" not in src and "inventory_status" not in src


def test_28_no_lgbs_govease_and_no_new_state():
    src = (REPO / "scripts" / "auction_outcomes.py").read_text() + (REPO / "scripts" / "realauction_results.py").read_text()
    assert not re.search(r"lgbs|govease|bid4assets", src, re.I)
    assert "state=eq.FL" in src and "state=eq.TX" not in src


def test_outcomes_step_is_wired_after_the_event_writer_and_manual_job_exists():
    assert "scripts/auction_outcomes.py" in WF
    assert WF.index("scripts/auction_events_writer.py --source fl") < WF.index("scripts/auction_outcomes.py")
    assert "outcomes" in WF.split("options: [")[1].split("]")[0]


# ==================== capture redaction ====================

def test_26_capture_skeleton_never_prints_identifiers():
    frag = ('1513190" aid="1513190"><a href="https://qpublic.schneidercorp.com/Application.aspx?Q=192963963&KeyValue=21-4N-10-0000-0030-0120" '
            'onClick = "return x();">21-4N-10-0000-0030-0120</a> Case #:@F CAD_DTA"> 2024 TD 1')
    out = RR.mask_text(frag, RR._KEEP_WORDS)
    assert not re.search(r"\d", out) and "KeyValue" not in out and "qpublic" not in out
    shape = RR.json_shape({"ADATA": {"AITEM": [{"AID": "1513190", "A": "Auction Sold", "D": "$1,300.00", "ST": "JOHN SMITH LLC"}]}})
    s = json.dumps(shape)
    assert "JOHN" not in s and "1513190" not in s and "Auction Sold" in s
    assert RR.vocab_or_shape("3rd Party Bidder") == "3rd Party Bidder"
