"""Interim allowances: dated, scoped, enforced, and fail closed at expiry.

Boundaries of one interim record (effective 2026-09-14, expires 2027-04-12,
the window every repository interim record carries): before / on the
effective day, during, on the expiry day (inclusive), the day after, a missing
or invalid date, an over-long window, an unmet condition, and an expired
county record that must not fall back to an in-date state record. Then the
real file: every interim record is complete, inside the cap, and has an
enforcing call site; the generated inventory is current.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from harvesters.governance import interim_permissions as IP  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402
from permission_fixtures import permissions_with, record  # noqa: E402

EFF, EXP = date(2026, 9, 14), date(2027, 4, 12)


def interim(**kw):
    return record(**{"source_id": "src_i", "jurisdiction": "FL", "operation": "fetch", **kw})


def decide(p, today, county=None):
    return p.authorize("src_i", "fetch", state="FL", county=county, today=today)


# --- the time boundaries ---------------------------------------------------------

@pytest.mark.parametrize("today,allowed,code", [
    (date(2026, 9, 13), False, "NOT_YET_EFFECTIVE"),   # the day before it takes effect
    (EFF, True, "ALLOWED_INTERIM"),                     # its first day
    (date(2026, 12, 31), True, "ALLOWED_INTERIM"),      # during
    (EXP, True, "ALLOWED_INTERIM"),                     # the expiry day is inclusive
    (date(2027, 4, 13), False, "EXPIRED"),              # the day after
    (date(2030, 1, 1), False, "EXPIRED"),               # long after
])
def test_interim_record_boundaries(today, allowed, code):
    p = permissions_with(interim(), base=False)
    assert p.error is None
    d = decide(p, today)
    assert (d.allowed, d.reason_code) == (allowed, code)
    if allowed:
        assert d.basis == "INTERIM" and "not a grant" in d.reason
    else:
        assert d.basis == "DENIED"


def test_interim_allowance_is_never_documented_permission():
    d = decide(permissions_with(interim(), base=False), EFF)
    assert d.allowed and d.basis == "INTERIM" and not d.documented


@pytest.mark.parametrize("bad", [
    {"expires_on": ""},                      # missing expiry
    {"effective_on": ""},                    # missing effective date
    {"expires_on": "2027-13-01"},            # not a date
    {"effective_on": "14/09/2026"},          # not ISO
    {"expires_on": "2026-09-14"},            # expiry not after effective
    {"reviewer": ""},                        # an allowing record names its reviewer
    {"expires_on": "2027-04-13"},            # 211 days: over the interim cap
    {"effective_on": "2026-01-01", "evidence_date": "2026-01-01"},  # 466 days
])
def test_invalid_or_overlong_interim_record_denies_everything(bad):
    p = permissions_with(interim(**bad), base=False)
    assert p.error, bad
    d = decide(p, date(2026, 12, 31))
    assert not d.allowed and d.reason_code == "CONFIG_INVALID"
    # ...and an unrelated, valid record in the same file denies too.
    p2 = permissions_with(interim(**bad), record(source_id="src_other", jurisdiction="FL", operation="fetch"), base=False)
    assert p2.authorize("src_other", "fetch", state="FL", today=date(2026, 12, 31)).reason_code == "CONFIG_INVALID"


def test_cap_is_exact_at_210_days():
    assert PERM.INTERIM_MAX_DAYS == 210 and (EXP - EFF).days == 210
    assert permissions_with(interim(), base=False).error is None
    # The cap applies to interim evidence only - a documented licence is not capped.
    documented = record(source_id="src_d", jurisdiction="FL", operation="fetch", status="APPROVED",
                        evidence_type="PUBLISHED_LICENSE", effective_on="2026-01-01", evidence_date="2026-01-01",
                        expires_on="2027-10-12")
    assert permissions_with(documented, base=False).error is None


def test_unmet_condition_denies_inside_the_window():
    p = permissions_with(interim(conditions="excluded_from_paid_tier"), base=False)
    p_unmet = PERM.Permissions(p.records, checkers={"excluded_from_paid_tier": lambda r: False})
    p_met = PERM.Permissions(p.records, checkers={"excluded_from_paid_tier": lambda r: True})
    assert decide(p_unmet, date(2026, 12, 31)).reason_code == "CONDITION_UNMET"
    assert decide(p_met, date(2026, 12, 31)).allowed
    # Expiry is checked before conditions: a met condition never revives an expired record.
    assert decide(p_met, date(2027, 4, 13)).reason_code == "EXPIRED"
    p_unknown = PERM.Permissions(p.records, checkers={})
    assert decide(p_unknown, date(2026, 12, 31)).reason_code == "UNKNOWN_CONDITION"


def test_expired_county_record_never_falls_back_to_the_state_record():
    county = interim(jurisdiction="FL:Orange", effective_on="2026-01-01", evidence_date="2026-01-01",
                     expires_on="2026-06-30")
    state = interim()
    p = permissions_with(county, state, base=False)
    assert p.error is None
    assert decide(p, date(2026, 12, 31), county="Orange").reason_code == "EXPIRED"
    assert decide(p, date(2026, 12, 31), county="Seminole").allowed
    assert decide(p, date(2026, 12, 31)).allowed


def test_expired_state_record_never_falls_back_to_a_national_record():
    us = record(source_id="src_i", jurisdiction="US", operation="fetch")
    fl = interim(effective_on="2026-01-01", evidence_date="2026-01-01", expires_on="2026-06-30")
    p = permissions_with(us, fl, base=False)
    assert p.error is None
    assert decide(p, date(2026, 12, 31)).reason_code == "EXPIRED"
    assert p.authorize("src_i", "fetch", state="TX", today=date(2026, 12, 31)).allowed


def test_expiry_is_evaluated_per_call_not_cached():
    p = permissions_with(interim(), base=False)
    assert decide(p, EXP).allowed
    assert decide(p, date(2027, 4, 13)).reason_code == "EXPIRED"
    assert decide(p, EXP).allowed


# --- the repository's interim records ------------------------------------------------

def test_every_repository_interim_record_is_scoped_dated_and_capped():
    perms = PERM.Permissions.from_file()
    assert perms.error is None
    recs = IP.interim_records(perms)
    assert len(recs) >= 100
    for r in recs:
        where = f"line {r.line} {r.source_id}"
        assert r.source_id and r.jurisdiction and r.operation in PERM.OPERATIONS and r.dataset, where
        assert r.evidence_ref and r.evidence_date and r.reviewer, where
        eff, exp = date.fromisoformat(r.effective_on), date.fromisoformat(r.expires_on)
        assert date.fromisoformat(r.evidence_date) <= eff < exp, where
        assert (exp - eff).days <= PERM.INTERIM_MAX_DAYS, where
        # Not renewed or extended in this sprint: every interim record still ends 2027-04-12.
        assert r.expires_on == "2027-04-12", where
        assert r.status in PERM.OPEN_STATUSES and r.evidence_type in PERM.INTERIM_EVIDENCE, where


def test_every_repository_interim_record_stops_allowing_after_2027_04_12():
    perms = PERM.Permissions.from_file()
    for r in IP.interim_records(perms):
        county = r.jurisdiction.split(":", 1)[1] if ":" in r.jurisdiction else None
        state = r.jurisdiction.split(":", 1)[0]
        state = "FL" if state == "US" else state
        dataset = None if r.dataset == "*" else r.dataset
        after = perms.authorize(r.source_id, r.operation, state=state, county=county, dataset=dataset,
                                today=date(2027, 4, 13))
        assert not after.allowed, (r.line, r.source_id, after.reason_code)


def test_every_interim_record_has_an_enforcing_call_site():
    entries = IP.inventory()
    missing = [(e["source_id"], e["operation"]) for e in entries if "NO_CALL_SITE_FOUND" in e["findings"]]
    assert not missing
    for e in entries:
        for site in e["call_sites"]:
            assert (ROOT / site.split(" ")[0]).is_file(), site


def test_known_interim_sources_point_at_their_gates():
    by_src = {}
    for e in IP.inventory():
        by_src.setdefault(e["source_id"], set()).update(s.split(" ")[0] for s in e["call_sites"])
    assert "scripts/geocode_properties.py" in by_src["census_geocoder"]
    assert "harvesters/enrichment/geocode.py" in by_src["fl_fdor_cadastral"]
    assert "harvesters/enrichment/parcels.py" in by_src["co_oit_public_parcels"]


def test_inventory_findings_are_reported_not_hidden():
    entries = IP.inventory()
    flagged = [e for e in entries if "REVIEWER_IS_NOT_A_DECISION" in e["findings"]]
    assert flagged and all("no reviewer decision on file" in e["reviewer"] for e in flagged)


def test_generated_inventory_is_current_and_deterministic():
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_interim_permissions.py"), "--check"],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    doc = json.loads((ROOT / "data" / "current_state" / "interim-permissions.json").read_text(encoding="utf-8"))
    assert doc["config_error"] is None and doc["interim_max_days"] == PERM.INTERIM_MAX_DAYS
    assert doc["summary"]["records"] == len(doc["entries"])
    text = json.dumps(doc)
    assert "days_remaining" not in text and "generated_at" not in text
