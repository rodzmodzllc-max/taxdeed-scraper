#!/usr/bin/env python3
"""Turn a job's raw output into (a) a public evidence file that carries no row
values and (b) encrypted copies of the raw files, so a public GitHub Actions
artifact never exposes owner names, addresses, notes, e-mail addresses or a
database backup.

Why (2026-09-29 SaaS launch-readiness audit): this repository is public, and
artifacts of a public repository can be downloaded by anyone with a GitHub
account. Every harvest job uploaded its raw harvest (LAFT rows carry owner
names and addresses) and the backup job uploaded `properties`, `notes`
(customer text + author e-mail) and `county_calendar` in the clear, for 90
days. The operational value of those artifacts - proving what a run saw,
re-running a sync offline, recovering from a bad sync - does not need the
row values to be public. It needs counts, hashes, completeness and, for
recovery, a copy only the operator can open.

What this writes
  out/public/<job>-evidence.json     always. Run identity (run id, attempt,
                                     workflow, commit), the per-source
                                     completeness/status file VERBATIM (it
                                     holds county names, statuses, counts and
                                     transport-level reasons - no row data),
                                     and per raw file: byte size, SHA-256,
                                     row count, the FIELD NAMES present and
                                     row counts by county/state/source. Never
                                     a field VALUE from a row.
  out/private/<name>.gpg             one per raw file, only when the
                                     ARTIFACT_PUBLIC_KEY environment variable
                                     holds an ASCII-armored OpenPGP public
                                     key (a repository VARIABLE, not a secret - a public key needs no secrecy; see
                                     docs/production-configuration.md). The
                                     matching private key never touches
                                     GitHub. Without the key nothing private
                                     is uploaded and the evidence file says
                                     so; the job stays green but prints a
                                     warning annotation.

The workflow then uploads out/public/ and out/private/ - nothing else.
tests/python/test_artifact_privacy.py enforces that on every workflow.

Usage
  artifact_evidence.py --job deeds [--status out/harvest_all_status.json]
                       [--status-name ...] RAW_GLOB [RAW_GLOB ...]
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PUBLIC_DIR = Path("out/public")
PRIVATE_DIR = Path("out/private")
GROUP_KEYS = ("county", "state", "source", "harvester_source", "host", "status")
MAX_ROWS_TO_SCAN = 200_000


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rows_summary(rows: list) -> dict:
    """Field names and grouped counts only. No value of any non-grouping
    field is ever copied; grouping keys are limited to the operational
    dimensions in GROUP_KEYS (county/state/source/...)."""
    dict_rows = [r for r in rows[:MAX_ROWS_TO_SCAN] if isinstance(r, dict)]
    # str(): a ragged CSV row yields a None key from DictReader.
    fields = sorted({str(k) for r in dict_rows for k in r.keys()})
    out: dict = {"rows": len(rows), "fields": fields}
    for key in GROUP_KEYS:
        if any(key in r for r in dict_rows):
            counter = Counter(str(r.get(key)) for r in dict_rows)
            out[f"rows_by_{key}"] = dict(sorted(counter.items()))
    return out


def describe_file(path: Path) -> dict:
    info: dict = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_of(path)}
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                info["kind"] = "json-rows"
                info.update(_rows_summary(data))
            elif isinstance(data, dict):
                info["kind"] = "json-object"
                info["top_level_keys"] = sorted(data.keys())
                for k, v in data.items():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        info.setdefault("lists", {})[k] = _rows_summary(v)
            else:
                info["kind"] = "json-scalar"
        elif suffix == ".csv":
            with open(path, newline="", encoding="utf-8", errors="replace") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
            info["kind"] = "csv-rows"
            info.update(_rows_summary(rows))
            info["fields"] = list(reader.fieldnames or [])
        else:
            info["kind"] = "opaque"
            with open(path, "rb") as fh:
                info["lines"] = sum(1 for _ in fh)
    except Exception as exc:  # a malformed file is still evidence: hash + size
        info["kind"] = "unreadable"
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def load_status(path: Path) -> dict:
    """The per-source completeness file, verbatim. These are written by the
    harvesters themselves (harvest_all_status.json, harvest_texas_status.json,
    backup manifest.json, ...) and hold county/source names, statuses, counts,
    hashes and transport-level reasons - operational evidence, no row data."""
    try:
        return {"path": str(path), "sha256": sha256_of(path), "content": json.loads(path.read_text(encoding="utf-8"))}
    except Exception as exc:
        return {"path": str(path), "error": f"{type(exc).__name__}: {exc}"}


def _gpg() -> str | None:
    return shutil.which("gpg") or shutil.which("gpg2")


def encrypt_files(files: list[Path], armored_key: str) -> dict:
    gpg = _gpg()
    if not gpg:
        return {"configured": True, "ok": False, "error": "gpg not available on this runner", "files": []}
    with tempfile.TemporaryDirectory() as home:
        os.chmod(home, 0o700)
        env = {**os.environ, "GNUPGHOME": home}
        imp = subprocess.run([gpg, "--batch", "--import"], input=armored_key.encode(), capture_output=True, env=env)
        if imp.returncode != 0:
            return {"configured": True, "ok": False, "error": "public key import failed: " + imp.stderr.decode(errors="replace").strip()[:300], "files": []}
        lst = subprocess.run([gpg, "--batch", "--with-colons", "--list-keys"], capture_output=True, text=True, env=env)
        fprs = [l.split(":")[9] for l in lst.stdout.splitlines() if l.startswith("fpr:")]
        if not fprs:
            return {"configured": True, "ok": False, "error": "no fingerprint after import", "files": []}
        recipient = fprs[0]
        PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
        written, errors = [], []
        for f in files:
            target = PRIVATE_DIR / (f.name + ".gpg")
            enc = subprocess.run(
                [gpg, "--batch", "--yes", "--trust-model", "always", "--recipient", recipient,
                 "--output", str(target), "--encrypt", str(f)],
                capture_output=True, text=True, env=env)
            if enc.returncode == 0 and target.exists():
                written.append({"path": str(target), "source": str(f), "bytes": target.stat().st_size, "sha256": sha256_of(target)})
            else:
                errors.append({"source": str(f), "error": enc.stderr.strip()[:300]})
        return {"configured": True, "ok": not errors, "recipient_fingerprint": recipient, "files": written, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    global PUBLIC_DIR, PRIVATE_DIR
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--job", required=True, help="job name, used in the evidence filename")
    ap.add_argument("--status", action="append", default=[], help="per-source status/manifest JSON to include verbatim (repeatable)")
    ap.add_argument("--public-dir", default="out/public")
    ap.add_argument("--private-dir", default="out/private")
    ap.add_argument("raw", nargs="*", help="raw output files or globs to hash, summarize and (if a key is set) encrypt")
    args = ap.parse_args(argv)

    PUBLIC_DIR = Path(args.public_dir)
    PRIVATE_DIR = Path(args.private_dir)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    raw_files: list[Path] = []
    for pattern in args.raw:
        for match in sorted(glob.glob(pattern, recursive=True)):
            p = Path(match)
            if p.is_file() and p not in raw_files:
                raw_files.append(p)
    status_files = [Path(s) for s in args.status if Path(s).is_file()]
    # A status file named on the command line is included verbatim AND, if
    # it also matched a raw glob, is not encrypted twice.
    raw_files = [p for p in raw_files if p not in status_files]

    evidence = {
        "job": args.job,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run": {k: os.environ.get(v) for k, v in {
            "id": "GITHUB_RUN_ID", "attempt": "GITHUB_RUN_ATTEMPT", "workflow": "GITHUB_WORKFLOW",
            "job": "GITHUB_JOB", "sha": "GITHUB_SHA", "ref": "GITHUB_REF", "event": "GITHUB_EVENT_NAME",
        }.items()},
        "status_files": [load_status(p) for p in status_files],
        "files": [describe_file(p) for p in raw_files],
        "privacy": (
            "This file carries run identity, completeness/status, byte sizes, SHA-256 hashes, "
            "row counts, field NAMES and counts by county/state/source. It never carries a row value. "
            "Raw files are retained only as OpenPGP-encrypted copies under out/private/ when "
            "ARTIFACT_PUBLIC_KEY is configured."
        ),
    }

    key = os.environ.get("ARTIFACT_PUBLIC_KEY", "").strip()
    if key and raw_files:
        evidence["private_copies"] = encrypt_files(raw_files, key)
    elif key:
        evidence["private_copies"] = {"configured": True, "ok": True, "files": [], "note": "no raw files matched"}
    else:
        evidence["private_copies"] = {"configured": False, "ok": True, "files": [],
                                      "note": "ARTIFACT_PUBLIC_KEY not set - raw files were NOT retained as an artifact"}
        print("::warning title=Raw output not retained::ARTIFACT_PUBLIC_KEY is not configured, so this run's raw files "
              "are not uploaded (a public repository's artifacts are public). Only the evidence summary is uploaded. "
              "See docs/production-configuration.md.")

    out_path = PUBLIC_DIR / f"{args.job}-evidence.json"
    out_path.write_text(json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    n_rows = sum(int(f.get("rows", 0) or 0) for f in evidence["files"])
    print(f"evidence: {out_path} ({len(raw_files)} raw file(s), {n_rows} rows summarized, "
          f"{len(evidence['status_files'])} status file(s), private copies: "
          f"{'yes' if evidence['private_copies'].get('files') else 'no'})")

    if evidence["private_copies"].get("configured") and not evidence["private_copies"].get("ok"):
        print(f"::error title=Encrypted copy failed::{evidence['private_copies'].get('error') or evidence['private_copies'].get('errors')}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
