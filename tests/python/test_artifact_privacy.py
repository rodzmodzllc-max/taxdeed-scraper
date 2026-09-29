"""Public GitHub artifacts must never carry row values (owner names,
addresses, notes, e-mail addresses, a database backup).

Enforced two ways:

1. STATIC, over EVERY workflow file: each actions/upload-artifact step may
   upload only `out/public/` and `out/private/`, and the same job must run
   scripts/artifact_evidence.py earlier (that script is the only writer of
   those directories). A new workflow that uploads `out/anything.json`
   directly fails here.

2. UNIT, over scripts/artifact_evidence.py: given raw files carrying owner
   names, addresses, note bodies and e-mails, the evidence file contains
   none of those VALUES while still carrying the operational facts the
   brief lists (run id, timestamps, row counts, source/county names,
   success/failure, completeness, hashes). With a key, the raw files come
   back byte-identical after decryption; without one, nothing private is
   written and the evidence says so.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))
SCRIPT = REPO / "scripts" / "artifact_evidence.py"
ALLOWED_PATHS = {"out/public/", "out/private/"}

sys.path.insert(0, str(REPO / "scripts"))
import artifact_evidence as ae  # noqa: E402


def _jobs():
    for wf in WORKFLOWS:
        data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        for job, spec in (data.get("jobs") or {}).items():
            yield wf.name, job, spec.get("steps") or []


def _upload_steps():
    for wf, job, steps in _jobs():
        for i, step in enumerate(steps):
            if str(step.get("uses", "")).startswith("actions/upload-artifact"):
                yield wf, job, i, steps


# ==================== STATIC: every workflow ====================


def test_w01_every_upload_step_uploads_only_the_public_and_private_dirs():
    found = 0
    for wf, job, i, steps in _upload_steps():
        found += 1
        paths = [p.strip() for p in str(steps[i]["with"]["path"]).splitlines() if p.strip()]
        assert set(paths) == ALLOWED_PATHS, f"{wf}:{job} uploads {paths}"
    assert found >= 7, "expected the five harvest-and-sync jobs plus the FDOR backfill and LGBS acquisition uploads"


def test_w02_every_uploading_job_runs_the_evidence_script_first_with_always():
    for wf, job, i, steps in _upload_steps():
        earlier = steps[:i]
        prep = [s for s in earlier if "scripts/artifact_evidence.py" in str(s.get("run", ""))]
        assert prep, f"{wf}:{job} uploads without running artifact_evidence.py first"
        assert prep[-1].get("if") == "always()", f"{wf}:{job} evidence step must run even when the harvest failed"
        assert "ARTIFACT_PUBLIC_KEY" in json.dumps(prep[-1].get("env") or {}), f"{wf}:{job} evidence step lacks the key env"
        assert steps[i].get("if") == "always()"


def test_w03_no_workflow_uploads_a_raw_harvest_backup_or_log_path_directly():
    for wf in WORKFLOWS:
        text = wf.read_text(encoding="utf-8")
        for step in yaml.safe_load(text).get("jobs", {}).values():
            for s in step.get("steps") or []:
                if str(s.get("uses", "")).startswith("actions/upload-artifact"):
                    p = str(s["with"]["path"])
                    for banned in ("out/backup/", "harvest_", "acquisition", ".log", "fdor_backfill"):
                        assert banned not in p, f"{wf.name}: {banned} in upload path"


def test_w04_status_files_are_passed_verbatim_where_the_harvester_writes_one():
    text = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
    for status in ("out/harvest_all_status.json", "out/harvest_certificates_status.json",
                   "out/harvest_texas_status.json", "out/backup/manifest.json"):
        assert f"--status {status}" in text, status


def test_w05_backup_export_script_unchanged_in_scope_and_never_exports_profiles_by_default():
    src = (REPO / "scripts" / "export_backup.py").read_text(encoding="utf-8")
    assert 'DEFAULT_TABLES = ["properties", "notes", "county_calendar"]' in src
    assert 'EXPORT_INCLUDE_PROFILES' in src


def test_w06_fdor_apply_decrypts_and_never_falls_back_to_plaintext():
    text = (REPO / ".github" / "workflows" / "backfill-fdor-phase52.yml").read_text(encoding="utf-8")
    assert "ARTIFACT_PRIVATE_KEY" in text
    assert "plan/private/fdor_backfill_dry-run.json.gpg" in text
    assert "cannot decrypt the dry-run plan" in text


def test_w07_documented_in_production_configuration():
    doc = (REPO / "docs" / "production-configuration.md").read_text(encoding="utf-8")
    for needle in ("ARTIFACT_PUBLIC_KEY", "ARTIFACT_PRIVATE_KEY", "out/public/", "evidence.json", "What stays public"):
        assert needle in doc, needle


# ==================== UNIT: the evidence script ====================

PII = {
    "owner": "Jane Q. Ownerperson",
    "address": "1234 Very Specific Lane, Ocala FL 34470",
    "note": "call the owner about the fence dispute",
    "email": "customer.person@example.com",
}


def _fixture(tmp: Path) -> tuple[Path, Path, Path, Path]:
    raw_json = tmp / "harvest_laft.json"
    raw_json.write_text(json.dumps([
        {"county": "Marion", "state": "FL", "owner_name": PII["owner"], "address": PII["address"], "bid": 1200},
        {"county": "Marion", "state": "FL", "owner_name": "Other Person", "address": "2 Other St", "bid": 900},
        {"county": "Lake", "state": "FL", "owner_name": "Third", "address": "3 Third St", "bid": 800},
    ]), encoding="utf-8")
    raw_csv = tmp / "harvest_laft.csv"
    with open(raw_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["county", "owner_name", "address"])
        w.writerow(["Marion", PII["owner"], PII["address"]])
    notes = tmp / "notes.json"
    notes.write_text(json.dumps([{"id": "n1", "author_email": PII["email"], "body": PII["note"]}]), encoding="utf-8")
    status = tmp / "harvest_laft_status.json"
    status.write_text(json.dumps([{"county": "Marion", "status": "COMPLETE", "rowCount": 2, "reason": "ok"},
                                  {"county": "Lake", "status": "INCOMPLETE", "rowCount": 1, "reason": "curl exit 7"}]), encoding="utf-8")
    return raw_json, raw_csv, notes, status


def _run(tmp: Path, args: list[str], key: str | None = None) -> tuple[int, dict, str]:
    env = {k: v for k, v in os.environ.items() if k != "ARTIFACT_PUBLIC_KEY"}
    env.update({"GITHUB_RUN_ID": "424242", "GITHUB_WORKFLOW": "Harvest", "GITHUB_SHA": "abc123"})
    if key is not None:
        env["ARTIFACT_PUBLIC_KEY"] = key
    pub, priv = tmp / "public", tmp / "private"
    r = subprocess.run([sys.executable, str(SCRIPT), "--public-dir", str(pub), "--private-dir", str(priv), *args],
                       cwd=tmp, capture_output=True, text=True, env=env)
    ev = json.loads((pub / "laft-evidence.json").read_text()) if (pub / "laft-evidence.json").exists() else {}
    return r.returncode, ev, r.stdout + r.stderr


def test_u01_evidence_carries_operational_facts_and_no_row_values(tmp_path):
    raw_json, raw_csv, notes, status = _fixture(tmp_path)
    rc, ev, out = _run(tmp_path, ["--job", "laft", "--status", str(status), str(raw_json), str(raw_csv), str(notes)])
    assert rc == 0, out
    text = json.dumps(ev)
    for value in PII.values():
        assert value not in text, value
    assert "Other Person" not in text and "2 Other St" not in text
    # Operational evidence is all there.
    assert ev["run"]["id"] == "424242" and ev["run"]["sha"] == "abc123"
    assert ev["generated_at"]
    assert ev["status_files"][0]["content"][1]["status"] == "INCOMPLETE"
    by_path = {f["path"]: f for f in ev["files"]}
    j = by_path[str(raw_json)]
    assert j["rows"] == 3 and j["rows_by_county"] == {"Lake": 1, "Marion": 2} and j["rows_by_state"] == {"FL": 3}
    assert set(j["fields"]) == {"county", "state", "owner_name", "address", "bid"}
    assert len(j["sha256"]) == 64 and j["bytes"] == raw_json.stat().st_size
    assert by_path[str(raw_csv)]["rows"] == 1 and by_path[str(raw_csv)]["fields"] == ["county", "owner_name", "address"]
    assert by_path[str(notes)]["fields"] == ["author_email", "body", "id"]


def test_u02_without_a_key_nothing_private_is_written_and_the_run_warns_but_passes(tmp_path):
    raw_json, raw_csv, notes, status = _fixture(tmp_path)
    rc, ev, out = _run(tmp_path, ["--job", "laft", "--status", str(status), str(raw_json)])
    assert rc == 0
    assert ev["private_copies"]["configured"] is False and ev["private_copies"]["files"] == []
    assert not (tmp_path / "private").exists()
    assert "::warning" in out and "ARTIFACT_PUBLIC_KEY" in out


@pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg not installed")
def test_u03_with_a_key_raw_files_round_trip_through_the_encrypted_copies(tmp_path):
    raw_json, raw_csv, notes, status = _fixture(tmp_path)
    home = tempfile.mkdtemp()
    os.chmod(home, 0o700)
    env = {**os.environ, "GNUPGHOME": home}
    subprocess.run(["gpg", "--batch", "--quick-gen-key", "--passphrase", "", "tdw-test <tdw@example.invalid>", "default", "default", "never"],
                   check=True, capture_output=True, env=env)
    pub = subprocess.run(["gpg", "--batch", "--armor", "--export", "tdw@example.invalid"], check=True, capture_output=True, text=True, env=env).stdout
    rc, ev, out = _run(tmp_path, ["--job", "laft", "--status", str(status), str(raw_json), str(notes)], key=pub)
    assert rc == 0, out
    pc = ev["private_copies"]
    assert pc["configured"] and pc["ok"] and len(pc["files"]) == 2 and pc["errors"] == []
    for entry in pc["files"]:
        enc = Path(entry["path"])
        assert enc.exists() and enc.suffix == ".gpg"
        # Ciphertext does not contain the plaintext PII.
        blob = enc.read_bytes()
        for value in PII.values():
            assert value.encode() not in blob
        dec = subprocess.run(["gpg", "--batch", "--quiet", "--decrypt", str(enc)], check=True, capture_output=True, env=env).stdout
        assert dec == Path(entry["source"]).read_bytes()
    # The status file itself is never encrypted (it is public evidence) and is not double-counted.
    assert not (tmp_path / "private" / "harvest_laft_status.json.gpg").exists()
    shutil.rmtree(home, ignore_errors=True)


def test_u04_a_bad_key_fails_loudly_rather_than_uploading_nothing_silently(tmp_path):
    raw_json, raw_csv, notes, status = _fixture(tmp_path)
    rc, ev, out = _run(tmp_path, ["--job", "laft", str(raw_json)], key="-----BEGIN PGP PUBLIC KEY BLOCK-----\nnot a key\n-----END PGP PUBLIC KEY BLOCK-----")
    if shutil.which("gpg") is None:
        pytest.skip("gpg not installed")
    assert rc == 1
    assert "::error" in out
    assert ev["private_copies"]["ok"] is False


def test_u05_group_keys_are_operational_dimensions_only():
    assert set(ae.GROUP_KEYS) <= {"county", "state", "source", "harvester_source", "host", "status"}
    for pii_key in ("owner_name", "address", "author_email", "body", "email", "phone", "name"):
        assert pii_key not in ae.GROUP_KEYS
