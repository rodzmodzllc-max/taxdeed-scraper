"""Migration 038: the partial index the address geocoder's pool read needs.

Its predicate must cover the geocoder's own filter (latitude is null and
delisted_at is null), or Postgres cannot use it for that read."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "scripts/migrations/038_properties_no_coordinates_index.sql").read_text()
GEOCODER = (ROOT / "scripts/geocode_properties.py").read_text()


def statements():
    return [s for s in SQL.split("\n") if s.strip() and not s.lstrip().startswith("--")]


def test_index_is_idempotent_and_partial_on_the_geocoder_filter():
    body = " ".join(statements())
    assert "create index if not exists properties_no_coordinates_idx" in body
    assert "on public.properties (id)" in body
    assert "where latitude is null and delisted_at is null" in body


def test_no_security_or_data_statement():
    body = " ".join(statements()).lower()
    for word in ("policy", "grant", "revoke", "drop ", "update ", "delete ", "insert ", "alter "):
        assert word not in body


def test_the_geocoder_still_filters_on_the_index_predicate():
    assert '"latitude": "is.null"' in GEOCODER or "'latitude': 'is.null'" in GEOCODER
    assert "delisted_at" in GEOCODER
