"""Migration 040 (2026-11-17): the Free preview drops certificates their source
has not confirmed in 7 days - the app's own unconfirmedCertificate() rule.
Everything else is 039 unchanged (re-checked by 039's own tests on this file)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
M39 = (ROOT / "scripts" / "migrations" / "039_preview_listings.sql").read_text(encoding="utf-8")
M40 = (ROOT / "scripts" / "migrations" / "040_preview_certificate_freshness.sql").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")


def code(sql: str) -> str:
    return re.sub(r"\s+", " ", " ".join(ln.split("--", 1)[0] for ln in sql.splitlines())).lower().strip()


def test_adds_only_the_certificate_freshness_rule():
    rule = "and (p.source <> 'certificate' or p.last_seen_at >= now() - interval '7 days')"
    c39, c40 = code(M39), code(M40)
    assert rule in c40 and rule not in c39
    stripped = c40.replace(rule + " ", "")
    # comment text aside, the function, its grants and revokes are 039's
    for part in ("returns table(", "security definer", "set search_path = public, pg_temp",
                 "limit least(greatest(coalesce(p_limit, 60), 0), 60)",
                 "revoke all on function public.get_preview_listings(text, text, integer, integer) from public, anon;",
                 "grant execute on function public.get_preview_listings(text, text, integer, integer) to authenticated, service_role;"):
        assert part in stripped, part
    assert c39[c39.index("create or replace function"):c39.index("comment on function")] == \
        stripped[stripped.index("create or replace function"):stripped.index("comment on function")]


def test_the_app_applies_the_same_rule():
    assert "function unconfirmedCertificate(p)" in APP
    assert "if (unconfirmedCertificate(p)) return false;" in APP
