#!/usr/bin/env python3
"""Live check of the admin role against the real Supabase project (2026-09-30).

Optional, run by a person from their own machine AFTER the Admin user exists.
Nothing here runs in CI and nothing is stored. Credentials come only from the
environment (see .env.example) and are never printed:

    ADMIN_EMAIL        the Admin account's sign-in address
    ADMIN_PASSWORD     its password (set in Supabase Auth by the owner)
    NORMAL_EMAIL       optional: a normal account to check, e.g. the owner's
    NORMAL_PASSWORD    optional: its password

It signs in through Supabase Auth's own password grant (the same call the app
makes), then asks PostgREST - under row-level security, with that user's
token - for the user's own profiles.is_admin. It checks:

  * the Admin account authenticates and the server says is_admin = true;
  * a deliberately wrong password is rejected by the server;
  * the normal account (when given) authenticates and the server says
    is_admin = false.

Output is PASS / FAIL lines only - no address, no password, no token.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def project() -> tuple[str, str]:
    """The public project URL and publishable key, from the root config.js
    (both are public by design - row-level security gates everything)."""
    text = (REPO / "config.js").read_text(encoding="utf-8")
    url = re.search(r'supabaseUrl:\s*"([^"]+)"', text)
    key = re.search(r'supabasePublishableKey:\s*"([^"]+)"', text)
    if not url or not key:
        raise SystemExit("config.js does not carry supabaseUrl / supabasePublishableKey")
    return url.group(1).rstrip("/"), key.group(1)


def _post(url: str, key: str, path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"apikey": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def sign_in(url: str, key: str, email: str, password: str) -> dict | None:
    status, data = _post(url, key, "/auth/v1/token?grant_type=password", {"email": email, "password": password})
    return data if status == 200 and data.get("access_token") else None


def server_is_admin(url: str, key: str, session: dict) -> bool:
    uid = session["user"]["id"]
    req = urllib.request.Request(f"{url}/rest/v1/profiles?select=is_admin&id=eq.{uid}",
                                 headers={"apikey": key, "Authorization": f"Bearer {session['access_token']}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        rows = json.loads(resp.read().decode() or "[]")
    return bool(rows) and rows[0].get("is_admin") is True


def main() -> int:
    admin_email, admin_password = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if not admin_email or not admin_password:
        print("SKIP: ADMIN_EMAIL / ADMIN_PASSWORD not set in the environment")
        return 0
    url, key = project()
    failures = 0

    def check(ok: bool, label: str) -> None:
        nonlocal failures
        print(("PASS " if ok else "FAIL ") + label)
        failures += 0 if ok else 1

    session = sign_in(url, key, admin_email, admin_password)
    check(session is not None, "admin authenticates with Supabase Auth")
    if session:
        check(server_is_admin(url, key, session), "server (RLS) reports the admin account as is_admin = true")
    check(sign_in(url, key, admin_email, admin_password + "-wrong") is None, "a wrong admin password is rejected by the server")
    normal_email, normal_password = os.environ.get("NORMAL_EMAIL"), os.environ.get("NORMAL_PASSWORD")
    if normal_email and normal_password:
        ns = sign_in(url, key, normal_email, normal_password)
        check(ns is not None, "normal account authenticates")
        if ns:
            check(not server_is_admin(url, key, ns), "server (RLS) reports the normal account as is_admin = false")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
