"""Record trust + quality sprint (2026-10-10).

- Record origins: harvesters/quality/record_origins.py == app.js
  recordOriginsFromFacts (shared vectors), and the JS tables mirror Python.
- Record invariants: each code fires on the row that breaks it and not on a
  clean row; benchmark metrics respect amount-kind semantics.
- The committed benchmark results are current (scripts/record_quality_benchmark.py --check).
- Every data-action control in the shipped pages has a handler.
- The deployable public bundle carries no secret / privileged credential.
- The certificate decision says a certificate does not transfer the property.
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from harvesters.quality import record_invariants as ri  # noqa: E402
from harvesters.quality import record_origins as ro  # noqa: E402

APP = (REPO / "public/app.js").read_text(encoding="utf-8")
CASES = json.loads((REPO / "tests/python/fixtures/record_origin_cases.json").read_text(encoding="utf-8"))["cases"]


# ---- record origins --------------------------------------------------------

@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_origin_vectors(case):
    assert ro.classify(case["facts"]) == case["expect"]


def _js_obj(name):
    m = re.search(r"var " + name + r" = " + name + r" \|\| (\{.*?\}|\[.*?\]);", APP, re.S)
    assert m, name
    txt = m.group(1)
    txt = re.sub(r"(\w+):", r'"\1":', txt) if txt.startswith("{") else txt
    return json.loads(txt)


def test_js_tables_mirror_python():
    assert _js_obj("RECORD_ORIGIN_LABELS") == ro.STATE_LABELS
    assert _js_obj("RECORD_ORIGIN_FIELDS") == list(ro.FIELDS)
    assert set(_js_obj("RECORD_ORIGIN_LIST_NATIVE")) == set(ro.LIST_NATIVE)
    assert _js_obj("RECORD_ORIGIN_SRC") == ro.SRC_ORIGIN
    assert set(_js_obj("RECORD_ORIGIN_STALE_SENSITIVE")) == set(ro.STALE_SENSITIVE)
    assert _js_obj("RECORD_ORIGIN_FIELD_LABELS") == ro.FIELD_LABELS


def test_unknown_origin_is_never_published():
    assert ro.classify_field("amount", True, "some_new_source", False) == "NOT_VERIFIED"
    assert ro.classify_field("coordinates", True, "", False) == "NOT_VERIFIED"
    assert ro.classify_field("identity", False, "list", True) == "NOT_PUBLISHED"
    assert ro.classify_field("flood", False, "fema", False) == "NOT_AVAILABLE"


def test_no_score_or_confidence_in_origins():
    block = APP[APP.index("// ==================== record origins"):APP.index("function provenanceCardHtml(p)")]
    code = "\n".join(l for l in block.splitlines() if not l.strip().startswith("//"))
    assert not re.search(r"score|confidence|rating|percent", code, re.I)


# ---- invariants ------------------------------------------------------------

CLEAN = {"id": 1, "state": "FL", "source": "auction", "ledger_type": "auctions", "county": "Bay", "case_no": "2026-00012",
         "parcel": "12-345-678", "status": "active", "min_bid": 1500, "sale_date": "2026-11-02",
         "url_auction": "https://bay.realtaxdeed.com/", "first_seen_at": "2026-09-01T00:00:00Z", "last_seen_at": "2026-10-09T12:00:00Z"}


def test_clean_row_has_no_violations():
    assert ri.row_violations(CLEAN) == []
    assert not any(ri.check([CLEAN]).values())


@pytest.mark.parametrize("patch,code", [
    ({"ledger_type": "buy"}, "LEDGER_MISMATCH"),
    ({"inventory_status": "certificate_listed"}, "STATUS_OUTSIDE_LEDGER"),
    ({"inventory_status": "sold", "inventory_status_basis": "LIST_PRESENCE"}, "RESULT_WITHOUT_PUBLISHED_BASIS"),
    ({"result_amount": 9000, "inventory_status": "active"}, "RESULT_AMOUNT_WITHOUT_RESULT"),
    ({"source": "laft", "ledger_type": "buy", "purchase_amount_kind": "QUOTED_ON_APPLICATION", "purchase_amount": 500}, "QUOTE_WITH_AMOUNT"),
    ({"delisted_at": "2026-10-01T00:00:00Z"}, "ACTIVE_BUT_DELISTED"),
    ({"last_seen_at": "2026-08-01T00:00:00Z"}, "SEEN_ORDER"),
    ({"parcel": "SEE ATTACHED LIST OF PARCELS"}, "IMPLAUSIBLE_IDENTIFIER"),
    ({"source": "certificate", "ledger_type": "lien", "case_no": "", "certificate_no": None}, "CERTIFICATE_WITHOUT_IDENTITY"),
])
def test_each_invariant_fires(patch, code):
    assert code in ri.row_violations({**CLEAN, **patch})


def test_published_result_is_not_a_violation():
    assert ri.row_violations({**CLEAN, "inventory_status": "sold", "inventory_status_basis": "SOURCE_STATUS", "result_amount": 9000}) == []


def test_duplicates_counted_once_per_extra_row():
    assert ri.check([CLEAN, dict(CLEAN, id=2), dict(CLEAN, id=3)])["DUPLICATE_IDENTITY"] == 2


def test_amount_semantics_in_metrics():
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    quoted = {**CLEAN, "id": 2, "case_no": "Q1", "source": "laft", "ledger_type": "buy", "purchase_amount_kind": "QUOTED_ON_APPLICATION", "min_bid": 0, "bid": 0}
    sentinel = {**CLEAN, "id": 3, "case_no": "S1", "min_bid": 0}
    assert ri.has_published_amount(CLEAN) and not ri.has_published_amount(quoted) and not ri.has_published_amount(sentinel)
    m = {(u["ledger"], u["county"]): u for u in ri.county_metrics([CLEAN, quoted, sentinel], now)}
    a = m[("AUCTIONS", "Bay")]
    assert (a["active"], a["published_amount"], a["fresh"], a["source_link"]) == (2, 1, 2, 2)
    assert m[("AVAILABLE", "Bay")]["published_amount"] == 0


def test_delisted_rows_are_not_active():
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    gone = {**CLEAN, "status": "closed", "delisted_at": "2026-10-01T00:00:00Z"}
    (u,) = ri.county_metrics([gone], now)
    assert u["active"] == 0 and u["rows"] == 1 and not u["violations"]


# ---- benchmark -------------------------------------------------------------

def test_benchmark_results_are_current():
    r = subprocess.run([sys.executable, "scripts/record_quality_benchmark.py", "--snapshot", "data/market_audit_snapshot.json",
                        "--out", "docs/record-quality-benchmark-results.md", "--check"], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_benchmark_rows_mode_requires_export_time(tmp_path):
    f = tmp_path / "rows.json"
    f.write_text(json.dumps([CLEAN]), encoding="utf-8")
    bad = subprocess.run([sys.executable, "scripts/record_quality_benchmark.py", "--rows", str(f)], cwd=REPO, capture_output=True, text=True)
    assert bad.returncode != 0
    ok = subprocess.run([sys.executable, "scripts/record_quality_benchmark.py", "--rows", str(f), "--now", "2026-10-10T00:00:00Z"],
                        cwd=REPO, capture_output=True, text=True)
    assert ok.returncode == 0 and "| FL | Bay | Auctions | 1 |" in ok.stdout


def test_benchmark_snapshot_never_estimates_missing_metrics():
    text = (REPO / "docs/record-quality-benchmark-results.md").read_text(encoding="utf-8")
    assert "Not in this snapshot" in text and "measured on 2026-10-06" in text


# ---- every control works ---------------------------------------------------

def test_every_data_action_has_a_handler():
    shipped = [APP, (REPO / "public/explore.js").read_text(encoding="utf-8")] + \
              [p.read_text(encoding="utf-8") for p in (REPO / "public").glob("*.html")]
    actions = set()
    for text in shipped:
        actions |= set(re.findall(r'data-action="([a-z0-9_-]+)"', text))
    assert actions, "no data-action controls found"
    handlers = "\n".join(l for t in shipped[:2] for l in t.splitlines() if re.search(r"action ===|case |dataset\.action", l))
    missing = sorted(a for a in actions if not re.search(r"""["']""" + re.escape(a) + r"""["']""", handlers))
    assert not missing, f"controls without a handler: {missing}"


# ---- public bundle carries no secret ---------------------------------------

SECRET_PATTERNS = {
    "supabase secret key": re.compile(r"sb_secret_[A-Za-z0-9_-]{10,}"),
    "service-role JWT": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*c2VydmljZV9yb2xl[A-Za-z0-9_-]*\."),
    "stripe secret": re.compile(r"\b(sk|rk)_(live|test)_[A-Za-z0-9]{10,}"),
    "stripe webhook secret": re.compile(r"\bwhsec_[A-Za-z0-9]{10,}"),
    "resend key": re.compile(r"\bre_[A-Za-z0-9]{8,}_[A-Za-z0-9]{8,}"),
    "github token": re.compile(r"\b(ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}"),
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def _deployable():
    files = [p for p in (REPO / "public").rglob("*") if p.is_file()]
    files.append(REPO / "config.js")
    return files


def test_public_bundle_has_no_secrets():
    hits = []
    for p in _deployable():
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".ico", ".webp", ".woff", ".woff2"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, rx in SECRET_PATTERNS.items():
            if rx.search(text):
                hits.append(f"{p.relative_to(REPO)}: {name}")
    assert not hits, hits


def test_public_bundle_has_no_source_maps_or_env_files():
    names = [p.name for p in _deployable()]
    assert not [n for n in names if n.endswith(".map") or n.startswith(".env") or n == "sync-config.local.json"]


def test_client_uses_only_the_publishable_key():
    cfg = (REPO / "config.js").read_text(encoding="utf-8")
    keys = re.findall(r'supabase\w*Key:\s*"([^"]+)"', cfg)
    assert keys and all(k.startswith("sb_publishable_") for k in keys)
    assert "service_role" not in APP


# ---- certificate is not the property ---------------------------------------

def test_certificate_decision_states_no_ownership_transfer():
    assert 'q("ownership", "Does buying it transfer the property?"' in APP
    note = re.search(r'var CERTIFICATE_OWNERSHIP_NOTE = CERTIFICATE_OWNERSHIP_NOTE \|\| "([^"]+)";', APP).group(1)
    assert "does not transfer ownership" in note and "lien" in note
