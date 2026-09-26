"""Launch-readiness honesty pass: regression guards.

Static checks only. They read local files, contact no source, and touch no
Supabase project.

1. Homestead fee estimate (open question, NOT silently fixed).
   fees() in public/app.js adds half the assessed value on a homesteaded
   Florida parcel on top of the published opening bid. FS 197.502(6)(c)
   may already fold that amount into the opening bid, which would make
   this a double count. Production evidence is suggestive but not proof, so
   the arithmetic is deliberately unchanged, pending accountant or attorney
   review. These tests pin today's formula, so that any change to it is
   deliberate and reviewed. They also check that the open question stays
   disclosed wherever the figure is explained.

2. Product claims corrected in this pass must not creep back: title
   screening, private notes, NAIP imagery labelled as Street View, Florida
   statutes on the Texas page, "live" auctions and "Top pick".
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUB = ROOT / "public"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


APP = read("public/app.js")


def _const(name):
    m = re.search(rf"const {name} = ([0-9.]+);", APP)
    assert m, name
    return float(m.group(1))


def _fees_body():
    m = re.search(r"function fees\(p\) \{(.*?)\n\}", APP, re.S)
    assert m, "fees() not found"
    return m.group(1)


def _python_fees(bid, assessed, homestead, include_qt=False):
    """Mirror of fees() in public/app.js for a Florida row, as it stands today."""
    dsr, rec, qt = _const("DOC_STAMP_RATE"), _const("RECORDING_FEE"), _const("QUIET_TITLE_EST")
    base = bid + (assessed / 2 if homestead else 0)
    total = base + base * dsr + rec + (qt if include_qt else 0)
    return total - bid


def test_fees_formula_is_pinned():
    body = _fees_body()
    assert 'if (regionOf(p) !== "FL") return null;' in body
    assert "const base = bid + homesteadSurcharge(p);" in body
    assert "base * DOC_STAMP_RATE + RECORDING_FEE" in body
    assert "const homesteadSurcharge = p => (p.homestead ? Number(p.assessed || 0) / 2 : 0);" in APP


def test_fees_homestead_example_documents_possible_double_count():
    # $50,000 opening bid, $80,000 assessed, homesteaded. If the clerk's
    # opening bid already includes the $40,000 half-assessed amount, the
    # correct add-on would be about $380. Today's estimate is about $40,660.
    # This test records the current figure. It is not an endorsement of it.
    assert round(_python_fees(50000, 80000, True), 2) == 40660.0
    assert round(_python_fees(50000, 80000, False), 2) == 380.0


def test_fees_open_question_is_disclosed():
    assert "OPEN QUESTION" in _fees_body()
    tip = re.search(r'const FEES_TIP = "(.*?)";', APP).group(1)
    assert "counts it twice" in tip and "review" in tip
    idx = read("public/index.html")
    assert idx.count("counted twice") >= 2  # footer + Terms


def test_texas_page_has_no_florida_fee_or_statute_copy():
    tx = read("public/tx.html")
    visible = re.sub(r"<!--.*?-->", "", tx, flags=re.S)
    for phrase in ("197.502", "197.542", "doc stamps", "documentary stamps", "half-assessed"):
        assert phrase not in visible, phrase
    assert 'id="topOnly"' not in tx and 'id="qtToggle"' not in tx


def test_filter_match_is_florida_only():
    assert 'const isTopPick = p => regionOf(p) === "FL" &&' in APP


def test_notes_are_not_described_as_private():
    for f in ("public/index.html", "public/tx.html"):
        html = read(f)
        assert "visible only to you" not in html, f
        assert "Team notes are shared" in html, f


def test_imagery_is_labelled_by_source_not_as_street_view():
    assert 'usda_naip: "Aerial image · USDA NAIP"' in APP
    assert '<span class="photo-caption">Street View</span>' not in APP


STALE = [
    "title screening", "true acquisition cost", "live county auction",
    "Top pick", "Title: Clear", "Gross Equity Spread", "Export Yield Ledger",
    "every tracked field is present", "Clerk's Official Records",
]


def _visible_strings(text):
    # Drop // line comments and /* */ blocks, so that history notes in
    # comments don't trip the check.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))


def test_stale_claims_absent_from_shipped_copy():
    for f in ("public/app.js", "public/index.html", "public/tx.html",
              "public/manifest.webmanifest", "supabase/functions/send-digest/index.ts"):
        body = _visible_strings(read(f))
        for phrase in STALE:
            assert phrase.lower() not in body.lower(), f"{phrase!r} in {f}"


def test_digest_never_prints_zero_dollar_bid():
    ts = read("supabase/functions/send-digest/index.ts")
    assert "function fmtBid(" in ts and "Not published" in ts
