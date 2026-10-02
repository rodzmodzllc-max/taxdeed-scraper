"""Customer-value release visibility gate (2026-10-02): the frontend's
review-required source list is the unified source model's, and the auction
sale-process answer never calls itself a purchase path."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harvesters.sources.model import REVIEW_OVERRIDES  # noqa: E402

APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")


def _block(name: str) -> str:
    m = re.search(r"const " + name + r" = \{(.*?)\n\};", APP, re.S)
    assert m, name
    return m.group(1)


def test_frontend_review_required_sources_equal_the_source_model():
    keys = set(re.findall(r"^\s*(\w+):", _block("REVIEW_REQUIRED_SOURCES"), re.M))
    assert keys == set(REVIEW_OVERRIDES)


def test_auction_process_is_county_level_and_never_a_purchase_path():
    body = APP[APP.index("function auctionProcessHtml"):APP.index("function typedPurchasePath")]
    assert "County-level guidance" in body
    assert "purchase path" not in body.lower()


def test_every_ledger_export_carries_the_source_review_status():
    assert APP.count('["Source Review Status", p => sourceReviewText(p)]') == 3
