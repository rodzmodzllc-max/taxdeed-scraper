"""scripts/backfill_source_ids.py: fill-blank only, proven by the row's own
auction host, FL only, idempotent, and wired after each FL sync."""
import sys
from pathlib import Path
from urllib.parse import parse_qs

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import backfill_source_ids as B  # noqa: E402


def _q(qs):
    return {k: v[0] for k, v in parse_qs(qs).items()}


def test_auction_rules_fill_only_blank_florida_rows_on_a_realauction_host():
    queries = B.rule_queries("auction")
    assert len(queries) == 2
    hosts = set()
    for qs, payload in queries:
        q = _q(qs)
        assert q["state"] == "eq.FL" and q["source"] == "eq.auction"
        assert q["source_id"] == "is.null"                      # never replaces a stored id
        assert payload == {"source_id": "fl_realauction"}       # nothing but the id
        hosts.add(q["url_auction"])
    assert hosts == {"like.https://*.realtaxdeed.com/*", "like.https://*.realforeclose.com/*"}


def test_a_row_without_a_realauction_url_is_never_given_an_id():
    # Okaloosa (Bid4Assets) and a row with no auction URL match no rule: no
    # county-based or catch-all rule exists for auctions.
    for qs, _payload in B.rule_queries("auction"):
        assert "url_auction" in _q(qs)
        assert "bid4assets" not in qs


def test_certificate_rule_is_the_lienhub_sync_only_and_state_scoped():
    [(qs, payload)] = B.rule_queries("certificate")
    q = _q(qs)
    assert q == {"state": "eq.FL", "source": "eq.certificate", "source_id": "is.null"}
    assert payload == {"source_id": "fl_lienhub_certificates"}


def test_authority_fill_is_blank_only_and_keyed_by_the_id():
    for source in ("auction", "certificate"):
        for qs, payload in B.authority_queries(source):
            q = _q(qs)
            assert q["source_authority"] == "is.null" and q["state"] == "eq.FL"
            assert q["source_id"].startswith("eq.") and payload == {"source_authority": "VENDOR_AUCTION"}


def test_no_credentials_means_no_request(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setattr(B, "_req", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no request")))
    assert B.main(["--source", "auction"]) == 0
    assert "nothing applied" in capsys.readouterr().out


def test_dry_run_counts_and_never_patches(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    calls = []

    def fake(method, url, key, body=None, prefer=""):
        calls.append(method)
        return ("0-0/7", b"")
    monkeypatch.setattr(B, "_req", fake)
    assert B.main(["--source", "auction", "--dry-run"]) == 0
    assert set(calls) == {"HEAD"}
    out = capsys.readouterr().out
    assert '"fl_realauction": 14' in out and "VENDOR_AUCTION" in out    # two host rules x 7; counts only


def test_apply_patches_only_when_a_blank_exists(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    patched = []

    def fake(method, url, key, body=None, prefer=""):
        if method == "PATCH":
            patched.append((url, body))
            return (None, b"")
        return ("*/0" if "realforeclose" in url or "source_authority" in url else "0-1/2", b"")
    monkeypatch.setattr(B, "_req", fake)
    assert B.main(["--source", "auction"]) == 0
    assert len(patched) == 1 and "realtaxdeed" in patched[0][0] and patched[0][1] == {"source_id": "fl_realauction"}


def test_workflow_runs_the_backfill_after_each_florida_sync():
    wf = yaml.safe_load((ROOT / ".github/workflows/harvest-and-sync.yml").read_text())
    runs = {}
    for job, spec in wf["jobs"].items():
        steps = spec.get("steps", [])
        for i, st in enumerate(steps):
            if "backfill_source_ids.py" in str(st.get("run", "")):
                runs[st["run"].split("--source ")[1].strip()] = (job, st, steps[i - 1])
    assert set(runs) == {"auction", "certificate"}
    for source, (_job, st, prev) in runs.items():
        assert st.get("continue-on-error") is True and st["if"] == "steps.sync.outcome == 'success'"
        assert "stamp_seen.py" in prev["run"] and f"--source {source}" in prev["run"]
