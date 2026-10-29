"""Buyer's Guide data (harvesters/sources/buyers_guide.py): every research
row follows data/buyers_guide/README.md, a county row replaces the statewide
row, and public/buyers-guide.json is current."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from harvesters.sources import buyers_guide as G

REPO = Path(__file__).resolve().parents[2]


def row(**kw) -> G.Row:
    base = dict(state="FL", county="", ledger="AUCTIONS", topic="deed_type", answer="A tax deed.",
                status="VERIFIED", kind="LAW", quote="the clerk shall execute a tax deed",
                source_url="https://www.leg.state.fl.us/statutes/", source_title="197.552",
                citation="F.S. 197.552", verified_on="2026-10-29", note="", file="FL.csv")
    base.update(kw)
    return G.Row(**base)


def test_repository_research_files_have_no_problems():
    assert G.problems() == []


def test_public_json_is_current():
    out = subprocess.run([sys.executable, "scripts/build_buyers_guide.py", "--check"], cwd=REPO,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_root_copy_matches_public():
    assert (REPO / "buyers-guide.json").read_text() == (REPO / "public" / "buyers-guide.json").read_text()


def test_valid_row_passes():
    assert G.problems([row()], directory=REPO / "nonexistent") == []


def test_rules_refuse_bad_rows():
    d = REPO / "nonexistent"
    cases = {
        "needs the quote": row(quote=""),
        "needs a citation": row(citation=""),
        "must be https": row(source_url="http://x.gov"),
        "carry no answer": row(status="NOT_VERIFIED", verified_on=""),
        "unknown topic": row(topic="made_up"),
        "statewide-only topic written for a county": row(county="Lee"),
        "county-only topic written statewide": row(topic="county_office", ledger="ALL"),
        "state does not match": row(file="TX.csv"),
        "needs verified_on": row(verified_on="soon"),
        "quote longer": row(quote="x" * 601),
    }
    for needle, r in cases.items():
        assert any(needle in p for p in G.problems([r], directory=d)), needle
    dup = G.problems([row(), row(file="FL-more.csv")], directory=d)
    assert any("duplicate" in p for p in dup)


def test_not_verified_row_with_blank_answer_passes():
    r = row(status="NOT_VERIFIED", answer="", verified_on="", quote="")
    assert G.problems([r], directory=REPO / "nonexistent") == []


def test_county_row_overrides_statewide():
    rows = [row(topic="payment_deadline", answer="State rule.", kind="LAW"),
            row(county="Lee", topic="payment_deadline", answer="Lee rule.", kind="PROCEDURE", citation="",
                file="FL-auctions.csv"),
            row(county="Lee", topic="county_office", ledger="ALL", answer="Clerk.", kind="PROCEDURE",
                citation="", file="FL-auctions.csv")]
    guide = G.build(rows)
    assert G.answer_for(guide, "FL", "Lee", "AUCTIONS", "payment_deadline")["answer"] == "Lee rule."
    assert G.answer_for(guide, "FL", "Polk", "AUCTIONS", "payment_deadline")["answer"] == "State rule."
    assert G.answer_for(guide, "FL", "Lee", "AUCTIONS", "county_office")["answer"] == "Clerk."
    assert G.answer_for(guide, "TX", "Harris", "AUCTIONS", "payment_deadline") is None
    assert guide["counts"]["VERIFIED"] == 3
