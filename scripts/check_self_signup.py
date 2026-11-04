#!/usr/bin/env python3
"""Smoke-check the deployed self-signup Edge Function without creating anyone.

Sends only payloads the function must refuse BEFORE it touches the auth admin
API, and checks the answers and the CORS headers a browser needs:
  1. preflight from the site's origin  -> Access-Control-Allow-Origin echoes it
  2. POST from the site, empty body     -> 400 missing/invalid field, JSON, ACAO
  3. POST from a foreign origin         -> 403 origin_not_allowed
Exit 0 when all hold, 1 otherwise. Prints status codes and error codes only.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

FN = "https://cqnnnvpbocafuvpzfbzu.supabase.co/functions/v1/self-signup"


def call(method, origin, body=None):
    req = urllib.request.Request(FN, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Origin": origin, "Content-Type": "application/json",
                                          "Access-Control-Request-Method": "POST"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", default="https://rodz-taxdeeds.pages.dev")
    a = ap.parse_args()
    ok = True

    st, h, _ = call("OPTIONS", a.origin)
    acao = {k.lower(): v for k, v in h.items()}.get("access-control-allow-origin")
    print(f"preflight {st} allow-origin-matches={acao == a.origin}")
    ok &= st in (200, 204) and acao == a.origin

    st, h, b = call("POST", a.origin, {"email": "not-an-email", "password": ""})
    acao = {k.lower(): v for k, v in h.items()}.get("access-control-allow-origin")
    try:
        code = json.loads(b).get("error")
    except ValueError:
        code = None
    print(f"invalid payload {st} error={code} allow-origin-matches={acao == a.origin}")
    ok &= st == 400 and code in ("invalid_email", "missing_fields", "weak_password") and acao == a.origin

    st, _, b = call("POST", "https://not-this-site.example", {})
    try:
        code = json.loads(b).get("error")
    except ValueError:
        code = None
    print(f"foreign origin {st} error={code}")
    ok &= st == 403 and code == "origin_not_allowed"

    print("SELF-SIGNUP OK" if ok else "SELF-SIGNUP CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
