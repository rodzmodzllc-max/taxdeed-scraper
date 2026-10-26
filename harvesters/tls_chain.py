"""TLS for a source that serves an incomplete certificate chain (2026-10-25).

`taxsales.lgbs.com` (the LGBS listing API, tx_lgbs) began serving a new
certificate (DigiCert, not before 2026-10-07) WITHOUT its intermediate: the
TLS Certificate message carries the leaf only. Browsers fetch the missing
intermediate from the certificate's AIA URL; Python's ssl module does not,
so every request failed with CERTIFICATE_VERIFY_FAILED ("unable to get local
issuer certificate"). The LGBS walk read 0 records and stamped nothing from
2026-10-07 on (the last stamp is 2026-10-02).

This module ships the missing PUBLIC intermediate certificate
(data/tls/*.pem - DigiCert Global G2 TLS RSA SHA256 2020 CA1, issued by
DigiCert Global Root G2, fetched from DigiCert's own AIA URL
cacerts.digicert.com and pinned by SHA-256 in
tests/python/test_stale_rows_reverify.py) and adds it to the DEFAULT trust
context. Verification is unchanged: the chain must still build to a root in
the system store and the hostname must still match. Nothing here disables
verification, and adding an intermediate cannot make an untrusted chain
trusted - it only supplies the link the server omitted.
"""
from __future__ import annotations

import ssl
import urllib.request
from functools import lru_cache
from pathlib import Path

TLS_DIR = Path(__file__).resolve().parents[1] / "data" / "tls"
# sha256 of the DER encoding of each shipped intermediate.
PINNED_INTERMEDIATES = {
    "digicert_global_g2_tls_rsa_sha256_2020_ca1.pem":
        "c8025f9fc65fdfc95b3ca8cc7867b9a587b5277973957917463fc813d0b625a9",
}


def intermediates_pem() -> str:
    return "".join((TLS_DIR / name).read_text(encoding="ascii") for name in sorted(PINNED_INTERMEDIATES))


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """The default verifying context plus the shipped intermediates."""
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=intermediates_pem())
    return ctx


_REAL_URLOPEN = urllib.request.urlopen


def urlopen(req, *, timeout: float):
    """urllib.request.urlopen with ssl_context() (full verification). When a
    test has replaced urllib.request.urlopen with a double, the double is
    called with its usual (request, timeout) signature - no network either way."""
    opener = urllib.request.urlopen
    if opener is not _REAL_URLOPEN:
        return opener(req, timeout=timeout)
    return opener(req, timeout=timeout, context=ssl_context())
