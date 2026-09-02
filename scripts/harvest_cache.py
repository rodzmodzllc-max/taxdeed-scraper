#!/usr/bin/env python3
"""Shared "only do the work when the source actually changed" cache for the
LAFT harvesters.

Why this exists (2026-09-02): an audit of every harvester found that NONE of
them did any form of conditional fetching or change detection - every
scheduled run re-downloaded every source in full and re-parsed it from
scratch, even on the overwhelmingly common day where a county's Lands
Available list is byte-for-byte identical to yesterday's. For the PDF
harvester in particular the parse (pdfplumber) is far more expensive than the
download, and it was being paid every single run for every single county.

Two independent layers, cheapest first:

  1. HTTP conditional request. If the server gave us an ETag or a
     Last-Modified last time, send If-None-Match / If-Modified-Since. A
     well-behaved server answers 304 Not Modified with an empty body - no
     bytes transferred, no parse, and we reuse the rows we already have.

  2. Content hash. Plenty of county servers ignore conditional headers and
     always return 200 with the full body. That still costs the download,
     but hashing the bytes lets us skip the expensive PARSE when the content
     is identical to what we parsed last time.

Fails safe by construction: any cache miss, unreadable cache, changed hash,
changed parser version, or unexpected status code falls through to exactly
the behaviour the harvesters had before this existed - full fetch, full
parse. The cache can be deleted at any time with no consequence beyond one
slower run. It is never the source of truth for what gets synced; it only
ever answers "has this source changed since we last parsed it".

PARSER_VERSION is the deliberate escape hatch: bump it whenever a harvester's
extraction logic changes, and every cached entry is invalidated so the new
logic actually re-parses unchanged sources instead of serving rows produced
by the old parser.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

# Bump this when extraction logic changes so cached rows are not reused.
PARSER_VERSION = 1

CACHE_DIR = Path(__file__).resolve().parent / "../out/.harvest_cache"

# A cache entry older than this is refetched unconditionally even if the
# server would have said 304. This bounds how long a silent upstream change
# that somehow kept the same ETag could hide a stale list, and guarantees
# every source is genuinely re-read on a regular cadence.
MAX_ENTRY_AGE_SECONDS = int(os.environ.get("HARVEST_CACHE_MAX_AGE", str(7 * 24 * 3600)))


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def load_cache(name: str) -> dict:
    """Load a harvester's cache, or an empty one. Never raises."""
    try:
        with open(_cache_path(name), encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        if data.get("parser_version") != PARSER_VERSION:
            # Extraction logic changed - everything cached under the old
            # version is untrustworthy, so start clean.
            return {}
        entries = data.get("entries")
        return entries if isinstance(entries, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(name: str, entries: dict) -> None:
    """Persist a harvester's cache. Never raises - a cache we failed to write
    just means the next run does the full work again."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _cache_path(name).with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"parser_version": PARSER_VERSION, "entries": entries}, fh)
        tmp.replace(_cache_path(name))
    except OSError as exc:
        print(f"      (cache not saved: {exc})", flush=True)


def conditional_get(session_or_requests, url: str, entry: dict | None, *,
                    headers: dict | None = None, timeout: int = 30):
    """GET `url`, sending validators from `entry` when we have them.

    Returns (status, content, new_validators). status is one of:
      "not_modified" - server said 304; caller should reuse cached rows.
      "unchanged"    - 200 but the body hashes identically to last time;
                       caller should reuse cached rows and skip parsing.
      "changed"      - 200 with genuinely new content; caller must parse.
    """
    req_headers = dict(headers or {})
    entry = entry or {}
    fresh_enough = (time.time() - float(entry.get("fetched_at", 0))) < MAX_ENTRY_AGE_SECONDS
    if fresh_enough:
        if entry.get("etag"):
            req_headers["If-None-Match"] = entry["etag"]
        if entry.get("last_modified"):
            req_headers["If-Modified-Since"] = entry["last_modified"]

    resp = session_or_requests.get(url, headers=req_headers, timeout=timeout)

    if resp.status_code == 304:
        validators = dict(entry)
        validators["fetched_at"] = time.time()
        return "not_modified", None, validators

    resp.raise_for_status()
    digest = hashlib.sha256(resp.content).hexdigest()
    validators = {
        "etag": resp.headers.get("ETag"),
        "last_modified": resp.headers.get("Last-Modified"),
        "sha256": digest,
        "fetched_at": time.time(),
    }
    if fresh_enough and entry.get("sha256") == digest:
        return "unchanged", resp.content, validators
    return "changed", resp.content, validators
