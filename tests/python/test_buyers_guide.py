"""Buyer's Guide data (harvesters/sources/buyers_guide.py, docs/buyers-guide-contract.md):
the researched answers follow the rules, an answer is VERIFIED in the published
file only after a capture run found its quote, county answers replace statewide
ones, and public/buyers-guide.json is current and mirrored."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harvesters.sources import buyers_guide as G

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))


def ans(**kw) -> G.Answer:
    base = dict(state="FL", county="", ledger="AUCTIONS", question="what_you_get", status="VERIFIED",
                answer="The clerk issues a tax deed.", quote="the clerk shall execute a tax deed",
                source_url="https://www.leg.state.fl.us/statutes/x", source_title="197.552", citation="F.S. 197.552",
                office="", verified_on="2026-10-29", where_to_look="", note="", line=2)
    base.update(kw)
    return G.Answer(**base)


def cap(a: G.Answer, result="FOUND", on="2026-10-30", run="1") -> dict:
    return {"answer_key": a.key, "quote_sha256": G.quote_sha(a.quote), "source_url": a.source_url, "result": result,
            "http_status": "200", "run_id": run, "captured_on": on}


def test_repository_files_have_no_problems():
    assert G.problems() == []


def test_public_json_is_current_and_mirrored():
    out = subprocess.run([sys.executable, "scripts/build_buyers_guide.py", "--check"], cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert (REPO / "buyers-guide.json").read_text() == (REPO / "public" / "buyers-guide.json").read_text()


def test_contract_shape():
    g = json.loads((REPO / "public" / "buyers-guide.json").read_text())
    assert set(g["ledgers"]) == {"AUCTIONS", "AVAILABLE", "LIENS_CERTIFICATES"}
    assert set(g["statuses"]) == {"VERIFIED", "PARTIALLY_VERIFIED", "NOT_VERIFIED", "SOURCE_RESTRICTED"}
    from harvesters.governance import states as S
    assert set(g["states"]) == set(S.PRODUCTION_STATES)
    assert g["states"]["LA"]["unit"] == "Parish" and g["states"]["FL"]["unit"] == "County"
    for st in g["states"].values():
        for led, b in st["ledgers"].items():
            assert b["offered"] in ("OFFERED", "NOT_OFFERED", "COUNTY_DEPENDENT", "NOT_VERIFIED", "SOURCE_RESTRICTED")
            ids = {q["id"] for q in g["questions"][led]}
            for a in b["answers"]:
                assert a["q"] in ids
                if a["status"] in ("VERIFIED", "PARTIALLY_VERIFIED"):
                    assert a["quote"] and a["source_url"].startswith("https://") and a["verified_on"]
                else:
                    assert "answer" not in a and "quote" not in a and a["where_to_look"]


def test_researched_answer_is_not_verified_without_a_capture():
    a = ans()
    e = G.published(a, {}, "where")
    assert e["status"] == "NOT_VERIFIED" and "answer" not in e and a.source_url in e["where_to_look"]


def test_found_capture_publishes_the_answer_with_the_capture_date():
    a = ans()
    e = G.published(a, G.capture_index([cap(a)]), "")
    assert e["status"] == "VERIFIED" and e["answer"] == a.answer and e["verified_on"] == "2026-10-30"


def test_later_capture_wins_and_blocked_is_source_restricted():
    a = ans()
    caps = G.capture_index([cap(a, "FOUND", "2026-10-30", "1"), cap(a, "BLOCKED", "2026-11-05", "2")])
    assert G.published(a, caps, "")["status"] == "SOURCE_RESTRICTED"
    caps = G.capture_index([cap(a, "NOT_FOUND", "2026-10-30", "1"), cap(a, "FOUND", "2026-11-05", "2")])
    assert G.published(a, caps, "")["status"] == "VERIFIED"


def test_capture_of_another_quote_or_url_does_not_count():
    a = ans()
    other = cap(ans(quote="a different sentence"))
    assert G.published(a, G.capture_index([other]), "")["status"] == "NOT_VERIFIED"
    moved = {**cap(a), "source_url": "https://www.leg.state.fl.us/old"}
    assert G.published(a, G.capture_index([moved]), "")["status"] == "NOT_VERIFIED"


def test_partial_capture_is_partially_verified():
    a = ans(quote="the clerk shall execute ... a tax deed")
    assert G.published(a, G.capture_index([cap(a, "PARTIAL")]), "")["status"] == "PARTIALLY_VERIFIED"


@pytest.mark.parametrize("page,expected", [
    ("Then THE CLERK  shall execute\na tax deed to the buyer.", "FOUND"),
    ("the clerk shall execute a tax deed", "FOUND"),
    ("the clerk shall execute", "NOT_FOUND"),
])
def test_match_quote(page, expected):
    assert G.match_quote("The clerk shall execute a tax deed", page) == expected


def test_match_quote_pieces_and_typography():
    q = "Bidders must register … a deposit of 5%"
    assert G.match_quote(q, "Bidders must register online. A deposit of 5% is due.") == "FOUND"
    assert G.match_quote(q, "Bidders must register online.") == "PARTIAL"
    assert G.match_quote("the owner’s “right”", "The owner's \"right\"") == "FOUND"


@pytest.mark.parametrize("change,needle", [
    (dict(answer="Pay 10% now."), "number '10'"),
    (dict(answer="You should hire a lawyer."), "advice wording"),
    (dict(quote=""), "needs answer, quote and source_url"),
    (dict(source_url="http://x.gov"), "must be https"),
    (dict(verified_on=""), "research read date"),
    (dict(status="NOT_VERIFIED", verified_on=""), "carry no answer"),
    (dict(question="made_up"), "unknown question"),
    (dict(ledger="ALL"), "ALL row may only answer"),
    (dict(quote="parcel 123456789012 the clerk shall execute a tax deed"), "long digit run"),
    (dict(quote="x" * 601), "longer than"),
])
def test_rules_refuse(change, needle):
    assert any(needle in p for p in G.problems([ans(**change)], captures=[])), needle


def test_number_written_as_in_the_quote_passes():
    a = ans(answer="A deposit of five % is due.", quote="Deposit must be five % of the final bid")
    assert G.problems([a], captures=[]) == []
    a = ans(answer="Documentary stamps are $.70 per $100.", quote="documentary stamps (.70 cents per $100)")
    assert G.problems([a], captures=[]) == []


def test_county_answer_replaces_statewide_and_all_rows_yield_to_ledger_rows():
    rows = [ans(question="pay_after_win", answer="State rule.", quote="state rule"),
            ans(county="Lee", question="pay_after_win", answer="Lee rule.", quote="lee rule", citation="", line=3),
            ans(county="Lee", ledger="ALL", question="office", answer="Clerk.", quote="clerk", citation="", line=4),
            ans(county="Lee", ledger="AUCTIONS", question="office", answer="Lee clerk.", quote="lee clerk", citation="", line=5)]
    caps = [cap(a) for a in rows]
    g = G.build(answers=rows, captures=caps)
    assert G.answer_for(g, "FL", "Lee", "AUCTIONS", "pay_after_win")["answer"] == "Lee rule."
    assert G.answer_for(g, "FL", "Polk", "AUCTIONS", "pay_after_win")["answer"] == "State rule."
    assert G.answer_for(g, "FL", "Lee", "AUCTIONS", "office")["answer"] == "Lee clerk."
    assert G.answer_for(g, "FL", "Lee", "AVAILABLE", "office")["answer"] == "Clerk."   # ALL -> each tracked ledger


def test_record_captures_from_a_log(tmp_path):
    import record_buyers_guide_captures as R
    a = ans()
    log = f"2026-10-30T01:00:00Z BGCAP\t{a.key}\t{G.quote_sha(a.quote)}\tFOUND\t200\nnoise\n" \
          f"2026-10-30T01:00:01Z BGCAP\tXX||AUCTIONS|gone\t{'0' * 64}\tFOUND\t200\n"
    p = tmp_path / "c.csv"
    p.write_text(",".join(G.CAPTURE_COLUMNS) + "\n")
    assert R.record(log, "77", "2026-10-30", path=p, answers=[a]) == 1
    assert R.record(log, "77", "2026-10-30", path=p, answers=[a]) == 1   # same run replaced, not doubled
    rows = G.load_captures(p)
    assert len(rows) == 1 and rows[0]["source_url"] == a.source_url and rows[0]["result"] == "FOUND"


def test_capture_script_prints_no_page_text(monkeypatch, capsys):
    import capture_buyers_guide as C
    a = ans()
    monkeypatch.setattr(G, "load_answers", lambda *x, **k: [a])
    monkeypatch.setattr(C, "fetch", lambda s, u: ("", 200, "SECRET PAGE WORDS ... the clerk shall execute a tax deed"))
    import permission_gate
    monkeypatch.setattr(permission_gate, "install_discovery_guard", lambda label: None)
    assert C.main([]) == 0
    out = capsys.readouterr().out
    assert f"BGCAP\t{a.key}\t{G.quote_sha(a.quote)}\tFOUND\t200" in out and "SECRET" not in out


def test_guide_pages_map_to_the_state_guide_source():
    from harvesters.governance import discovery_guard as DG
    rows = G.load_answers()
    url = next(a.source_url for a in rows if a.state == "FL" and "leg.state.fl.us" in a.source_url)
    d = DG.Guard("t").decide(url)
    assert d.allowed and "buyers_guide_fl" in d.source_ids


def test_lead_mode_prints_keyword_sentences_of_unread_pages(monkeypatch, capsys):
    import capture_buyers_guide as C
    a = ans(question="deposit", status="NOT_VERIFIED", answer="", quote="", verified_on="",
            source_url="https://county.example.gov/rules")
    monkeypatch.setattr(G, "load_answers", lambda *x, **k: [a, ans()])
    page = "Welcome to the sale site. A deposit of 5% is required before bidding. Parking is free downstairs today."
    monkeypatch.setattr(C, "fetch", lambda s, u: ("", 200, page))
    import permission_gate
    monkeypatch.setattr(permission_gate, "install_discovery_guard", lambda label: None)
    assert C.main(["--leads"]) == 0
    out = capsys.readouterr().out
    assert f"BGLEAD\t{a.key}\tREAD\t200" in out
    assert f"BGTEXT\t{a.key}\tA deposit of 5% is required before bidding." in out
    assert "Parking" not in out and "BGCAP" not in out
