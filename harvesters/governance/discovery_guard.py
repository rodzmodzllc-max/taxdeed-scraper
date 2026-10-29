"""Source permission for discovery, evidence capture and probes.

The manual evidence scripts (`scripts/capture_*.py`, `scripts/discover_sources.py`,
`scripts/probe_*.py`) read candidate and source pages to learn what exists. Each
one calls `install(label)` first. From then on every outbound HTTP request the
process makes (`requests` and `urllib`) is checked before a connection is opened:

  1. The URL is matched to the source(s) it belongs to, using only the
     repository's own records: the county source registry, the enrichment
     source catalog, the acquisition / discovery candidate tables, the
     acquisition evidence tables and the expansion and parcel-layer configs.
     Longest path prefix on the same host wins. A host shared by several
     sources with no path match counts every one of them.
  2. Every matched source must hold an in-date `discover` permission in
     data/source_permissions.csv (harvesters/governance/permissions.py). A
     permission for any other operation (fetch, store, ...) is not enough.
  3. No match, a candidate with no source id, a denial, an expired record or a
     governance error -> the request is refused with DiscoveryDenied, before
     any socket is opened. A public, working URL is never itself permission.

The project's own database host (SUPABASE_URL) is not a source and is allowed.

Denials are kept in memory and written, counts-only, to
out/public/discovery-permission-<label>.json at exit: host, reason code and
source ids. Never a path, query string, credential or row value.
"""
from __future__ import annotations

import atexit
import csv
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
OPERATION = "discover"

INDEX_TABLES = (
    # (path, url columns) - every table carries source_id, state, county.
    ("data/county_source_registry.csv", ("canonical_url", "document_url", "purchase_url")),
    ("data/enrichment_source_catalog.csv", ("url",)),
    ("data/acquisition_candidate_pages.csv", ("url",)),
    ("data/available_discovery_pages.csv", ("url",)),
    ("data/available_source_candidates.csv", ("url",)),
    ("data/purchase_path_evidence.csv", ("url", "evidence_url", "application_url")),
    ("data/purchase_path_evidence_expansion.csv", ("url", "evidence_url", "application_url")),
    # 2026-10-26 county-source sprint: FL Tax Collector county-held certificate candidates.
    ("data/county_source_candidates.csv", ("url",)),
)


@dataclass(frozen=True)
class Target:
    source_id: str
    state: str
    county: str | None
    host: str
    path: str


@dataclass
class Decision:
    allowed: bool
    reason_code: str
    host: str
    source_ids: tuple[str, ...] = ()
    reason: str = ""


try:  # keep the module importable without requests
    import requests as _requests
    _DENIED_BASE = _requests.exceptions.ConnectionError
except Exception:  # noqa: BLE001
    _requests = None
    _DENIED_BASE = OSError


class DiscoveryDenied(_DENIED_BASE):
    """Raised instead of making a refused request. It is a transport error of
    `requests` (an OSError without it), so a script's existing per-page error
    handling records the page as failed and carries on."""


def _norm(url: str) -> tuple[str, str] | None:
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    path = (parts.path or "/").rstrip("/") or "/"
    return parts.hostname.lower(), path.lower()


def _county(value) -> str | None:
    v = (value or "").strip()
    return None if not v or v.upper() in ("STATEWIDE", "ALL", "*") else v


def build_index(repo: Path = REPO) -> list[Target]:
    """Every (source, URL) the repository records. Rows with no source id are
    kept so a match on them is a denial, not a silent fall-through."""
    out: list[Target] = []
    for rel, cols in INDEX_TABLES:
        p = repo / rel
        if not p.is_file():
            continue
        with p.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                for c in cols:
                    n = _norm(r.get(c) or "")
                    if n:
                        out.append(Target((r.get("source_id") or "").strip(), (r.get("state") or "").strip().upper(),
                                          _county(r.get("county")), *n))
    # Buyer's Guide pages (scripts/capture_buyers_guide.py): every official
    # page an answer cites belongs to that state's guide source,
    # buyers_guide_<state>, so its discover permission is what allows the read.
    bg = repo / "data" / "buyers_guide_answers.csv"
    if bg.is_file():
        with bg.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                st = (r.get("state") or "").strip().upper()
                n = _norm(r.get("source_url") or "")
                if n and st:
                    out.append(Target(f"buyers_guide_{st.lower()}", st, _county(r.get("county")), *n))
    try:
        import sys
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from harvesters.otc.adapters import expansion as E  # noqa: PLC0415
        for srcs in E.SOURCES.values():
            for s in srcs:
                cfg = s.config
                sid = getattr(cfg, "source_id", "") or ""
                state = (getattr(cfg, "state", "") or "").upper()
                county = _county(getattr(cfg, "county", None))
                urls = [s.url] + [getattr(cfg, a, None) for a in dir(cfg) if a.endswith("url") and not a.startswith("_")]
                for u in urls:
                    n = _norm(u if isinstance(u, str) else "")
                    if n:
                        out.append(Target(sid, state, county, *n))
        from harvesters.enrichment import sources as PS  # noqa: PLC0415
        for cfg in PS.all_sources():
            for u in (cfg.landing_url, cfg.layer_url):
                n = _norm(u or "")
                if n:
                    out.append(Target(cfg.source_id, (cfg.state or "").upper(), None, *n))
    except Exception:  # noqa: BLE001 - a config that fails to load adds no index entries (fail closed)
        pass
    return out


class Guard:
    def __init__(self, label: str, *, index: list[Target] | None = None, authorize=None,
                 allow_hosts: tuple[str, ...] = ()):
        self.label = label
        self.index = build_index() if index is None else list(index)
        self._authorize = authorize
        self.allow_hosts = {h.lower() for h in allow_hosts if h}
        self.allowed = 0
        self.denials: list[dict] = []
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str, str | None], tuple[bool, str]] = {}

    def _permit(self, t: Target) -> tuple[bool, str]:
        if not t.source_id:
            return False, "NO_SOURCE"
        key = (t.source_id, t.state, t.county)
        if key not in self._cache:
            try:
                if self._authorize is not None:
                    d = self._authorize(t.source_id, OPERATION, t.state or None, t.county)
                else:
                    from harvesters.governance import permissions as PERM  # noqa: PLC0415
                    d = PERM.authorize(t.source_id, OPERATION, state=t.state or None, county=t.county)
                self._cache[key] = (bool(d.allowed), "" if d.allowed else (d.reason_code or "DENIED"))
            except Exception as exc:  # noqa: BLE001 - no governance means no permission
                self._cache[key] = (False, f"GOVERNANCE_UNAVAILABLE:{type(exc).__name__}")
        return self._cache[key]

    def decide(self, url: str) -> Decision:
        n = _norm(url)
        if n is None:
            return Decision(False, "UNSUPPORTED_URL", "")
        host, path = n
        if host in self.allow_hosts:
            return Decision(True, "PROJECT_INTERNAL", host)
        same_host = [t for t in self.index if t.host == host]
        if not same_host:
            return Decision(False, "NO_SOURCE_FOR_HOST", host)
        prefixed = [t for t in same_host if path == t.path or path.startswith(t.path.rstrip("/") + "/") or t.path == "/"]
        if prefixed:
            longest = max(len(t.path) for t in prefixed)
            candidates = [t for t in prefixed if len(t.path) == longest]
        else:
            candidates = same_host
        ids = tuple(sorted({t.source_id or "(none)" for t in candidates}))
        for t in candidates:
            ok, why = self._permit(t)
            if not ok:
                return Decision(False, why, host, ids, f"{t.source_id or '(no source id)'} has no in-date {OPERATION} permission")
        return Decision(True, "ALLOWED", host, ids)

    def check(self, url: str) -> Decision:
        d = self.decide(url)
        with self._lock:
            if d.allowed:
                self.allowed += 1
            else:
                self.denials.append({"host": d.host, "reason_code": d.reason_code, "source_ids": list(d.source_ids)})
        if not d.allowed:
            raise DiscoveryDenied(f"DISCOVERY_DENIED[{d.reason_code}] {d.host} - no request made")
        return d

    def summary(self) -> dict:
        by_reason: dict[str, int] = {}
        hosts: dict[str, dict] = {}
        for x in self.denials:
            by_reason[x["reason_code"]] = by_reason.get(x["reason_code"], 0) + 1
            h = hosts.setdefault(x["host"], {"host": x["host"], "denied": 0, "reason_codes": set(), "source_ids": set()})
            h["denied"] += 1
            h["reason_codes"].add(x["reason_code"])
            h["source_ids"].update(x["source_ids"])
        return {"label": self.label, "operation": OPERATION, "allowed": self.allowed, "denied": len(self.denials),
                "denied_by_reason": dict(sorted(by_reason.items())),
                "hosts": [{"host": h["host"], "denied": h["denied"], "reason_codes": sorted(h["reason_codes"]),
                           "source_ids": sorted(h["source_ids"])} for h in sorted(hosts.values(), key=lambda v: v["host"])],
                "note": "counts, hosts, reason codes and source ids only; never a path, query, credential or row value"}

    def write_report(self, out_dir: Path | None = None) -> Path:
        out_dir = out_dir or (Path(os.environ.get("DISCOVERY_REPORT_DIR", "")) or REPO / "out" / "public")
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / f"discovery-permission-{self.label}.json"
        p.write_text(json.dumps(self.summary(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return p


_ACTIVE: Guard | None = None
_ORIG: dict[str, object] = {}


def _project_hosts() -> tuple[str, ...]:
    n = _norm(os.environ.get("SUPABASE_URL", ""))
    return (n[0],) if n else ()


def _patch() -> None:
    if _ORIG:
        return
    if _requests is not None:
        orig_request = _requests.sessions.Session.request

        def guarded_request(self, method, url, *a, **kw):
            if _ACTIVE is not None:
                _ACTIVE.check(str(url))
            return orig_request(self, method, url, *a, **kw)
        _ORIG["requests"] = orig_request
        _requests.sessions.Session.request = guarded_request
    import urllib.request as ur
    orig_open = ur.OpenerDirector.open

    def guarded_open(self, fullurl, *a, **kw):
        if _ACTIVE is not None:
            _ACTIVE.check(fullurl if isinstance(fullurl, str) else fullurl.full_url)
        return orig_open(self, fullurl, *a, **kw)
    _ORIG["urllib"] = orig_open
    ur.OpenerDirector.open = guarded_open


def install(label: str, *, index: list[Target] | None = None, authorize=None, write_report_at_exit: bool = True) -> Guard:
    """Guard every outbound request of this process. Idempotent per process:
    a second call replaces the active guard."""
    global _ACTIVE
    g = Guard(label, index=index, authorize=authorize, allow_hosts=_project_hosts())
    _ACTIVE = g
    _patch()
    if write_report_at_exit:
        def _final():
            if _ACTIVE is g:
                s = g.summary()
                print(f"discovery_guard[{label}]: {s['allowed']} request(s) allowed, {s['denied']} refused "
                      f"{s['denied_by_reason'] or ''} (operation '{OPERATION}', data/source_permissions.csv)", flush=True)
                try:
                    g.write_report()
                except OSError:
                    pass
        atexit.register(_final)
    return g


def uninstall() -> None:
    """Restore the original transports (tests)."""
    global _ACTIVE
    _ACTIVE = None
    if "requests" in _ORIG and _requests is not None:
        _requests.sessions.Session.request = _ORIG.pop("requests")
    if "urllib" in _ORIG:
        import urllib.request as ur
        ur.OpenerDirector.open = _ORIG.pop("urllib")


def active() -> Guard | None:
    return _ACTIVE
