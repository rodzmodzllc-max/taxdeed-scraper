"""scripts/legal_readiness_check.py: names the blank owner values, never invents
one, keeps billing off, and the source disclaimer says government publication
is not by itself permission for commercial reuse."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("legal_readiness_check", REPO / "scripts" / "legal_readiness_check.py")
LRC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LRC)


def test_reports_exactly_the_blank_owner_values():
    text = LRC._config_text()
    r = LRC.report()
    for key in LRC.OWNER_VALUES:
        blank = not LRC.config_value(text, key)
        if key == "supportEmail":
            blank = blank and not LRC.config_value(text, "legal.contactEmail")
        assert (key in r["missing"]) is blank, key


def test_config_value_parser():
    t = 'x = { supportEmail: "", legal: { operatorName: "Acme LLC", governingLaw: "" }, billing: { enabled: false } }'
    assert LRC.config_value(t, "legal.operatorName") == "Acme LLC"
    assert LRC.config_value(t, "legal.governingLaw") == ""
    assert LRC.config_value(t, "supportEmail") == ""
    assert LRC.billing_enabled(t) is False
    assert LRC.billing_enabled('billing: { enabled: true }') is True


def test_structure_is_complete_and_billing_off():
    r = LRC.report()
    assert r["problems"] == []
    assert r["billing_enabled"] is False                                  # billing stays out of scope


def test_disclaimer_states_publication_is_not_permission_and_review_states():
    for p in (REPO / "public" / "source-disclaimer.html", REPO / "source-disclaimer.html"):
        html = p.read_text(encoding="utf-8")
        assert LRC.REUSE_SENTENCE in html
        assert "only approved sources are offered to customers" in html and "blocked sources are never collected" in html


def test_cli_exit_codes(capsys):
    assert LRC.main([]) == 0                                              # report only
    out = capsys.readouterr().out
    assert "Billing: off" in out
    strict = LRC.main(["--strict"])
    assert strict == (1 if LRC.report()["missing"] else 0)


def test_legal_js_never_invents_a_value():
    js = (REPO / "public" / "legal.js").read_text(encoding="utf-8")
    assert '"[not configured]"' in js and "Nothing is invented" in js
