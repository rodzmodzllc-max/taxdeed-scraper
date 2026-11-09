"""Migration 039 documents count_properties() as a raw row count (FL-AVAIL-8).

It must stay a comment: get_properties() pages every status, so the count
that sizes those pages must count every status too."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "scripts/migrations/039_count_properties_raw_count_comment.sql").read_text()
M024 = (ROOT / "scripts/migrations/024_customer_monitoring_foundation.sql").read_text()


def statements():
    return " ".join(s for s in SQL.split("\n") if s.strip() and not s.lstrip().startswith("--")).lower()


def test_comment_names_the_function_and_says_raw_count():
    body = statements()
    assert "comment on function public.count_properties(text, text) is" in body
    assert "raw row count" in body
    assert "not a customer inventory count" in body


def test_comment_only():
    body = statements()
    for word in ("create ", "replace", "policy", "grant", "revoke", "drop ", "update ", "delete ", "insert ", "alter "):
        assert word not in body


def test_the_counted_rows_still_match_get_properties_paging():
    # 024's body has no status filter, matching get_properties' every-status pages.
    start = M024.index("create or replace function public.count_properties")
    body = M024[start:M024.index("$$;", start)]
    assert "status" not in body
