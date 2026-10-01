#!/usr/bin/env python3
"""Per-property purchase / application links from the county lists, by rule
(production-readiness program, 2026-09-30).

WHY. migration 017's purchase_url / purchase_url_kind are stamped by
scripts/laft_lifecycle.py from (1) a link the harvester row itself carries
or (2) a source-level path verified in the registry. No FL harvester ever
carried one, because none captured the anchors in a list's cells. This
module is the missing half:

  capture_links(table, base_url)   the <a href> of every cell, per row,
                                   resolved against the page - what the
                                   list actually publishes, kept beside
                                   the row in the harvest artifact
  link_evidence(...)               a VALUE-FREE summary per county (header
                                   labels that carry links, link text, host
                                   + digit-masked path shape, counts) - the
                                   evidence a human needs to verify what a
                                   link IS before a rule is written
  apply_rules(record, links, ...)  purchase_url + purchase_url_kind on the
                                   record, ONLY when an ENABLED, VERIFIED
                                   rule in data/laft_purchase_link_rules.csv
                                   matches the link's column / text / host,
                                   and the link is https, not the list page,
                                   not the document, not a bare homepage

The rules table ships with NO enabled rule: no county page has been read
from this repository, so no link's meaning has been verified. Until a rule
is verified (a human opens the link, confirms it is the county's purchase
/ application path for that parcel, records the date and evidence) the
evidence file is the only output, and every row keeps "No online purchase
link on file". A rule can never be enabled without verified_on and
evidence (the loader refuses it).

Public log discipline: nothing here prints or writes a parcel, case
number, name or full URL of a specific property - the evidence file holds
hosts, digit-masked path shapes, labels and counts only.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RULES_PATH = REPO / "data" / "laft_purchase_link_rules.csv"
EVIDENCE_PATH = REPO / "out" / "public" / "laft-link-evidence.json"

PURCHASE_URL_KINDS = ("purchase_instructions", "offer_form", "bid_form", "application_form", "online_purchase")
# Purchase-path MODES (2026-09-30, AVAILABLE commercialization): what the
# SOURCE publishes as the way to buy, at source level
# (county_source_registry.purchase_path_mode). The online modes carry a URL
# (purchase_url + purchase_url_kind); in_person_only / phone_mail carry no
# URL and MUST cite the source wording (purchase_path_evidence); none = the
# source says there is no path; unknown = nothing verified (the default,
# and what every Florida production source carries until its page is read).
PURCHASE_PATH_MODES = ("online_property", "online_instructions", "application", "in_person_only", "phone_mail", "none", "unknown")
MODE_FOR_KIND = {"online_purchase": "online_property", "offer_form": "online_property", "bid_form": "online_property",
                 "purchase_instructions": "online_instructions", "application_form": "application"}
NON_URL_MODES = frozenset({"in_person_only", "phone_mail", "none", "unknown"})
# Hosts that can never be a purchase path: search engines and the blocked
# Texas vendors (harvesters/governance/registry.py). A URL is also refused
# when it is a bare homepage, the list page or the document itself.
UNTRUSTED_HOST_SUFFIXES = ("google.com", "bing.com", "duckduckgo.com", "yahoo.com", "search.brave.com",
                           "pbfcm.com", "mvbalaw.com", "govease.com", "ctsa.com",
                           # Delinquent-tax counsel publishes the Texas LISTING; it is never the
                           # official acquisition page (Acquisition-path sprint, 2026-10-01).
                           "lgbs.com")
# The kinds the app presents as an action for THIS parcel (app.js
# PROPERTY_PURCHASE_KINDS / laft_lifecycle.PROPERTY_PURCHASE_KINDS);
# purchase_instructions and application_form are process pages.
PROPERTY_KINDS = frozenset({"offer_form", "bid_form", "online_purchase"})
MATCH_KINDS = ("column", "text", "host_path")
RULE_COLUMNS = ["state", "source_id", "county", "match_kind", "match_value", "purchase_url_kind", "enabled",
                "verified_on", "evidence", "notes"]

_DIGITS = re.compile(r"\d+")
_TRUE = frozenset({"1", "true", "yes", "y"})


@dataclass(frozen=True)
class Rule:
    state: str
    source_id: str
    county: str            # a county name, or "*" for every county of the source
    match_kind: str        # column: the header label the link sits under; text: the link's own text; host_path: host + path prefix
    match_value: str
    purchase_url_kind: str
    enabled: bool
    verified_on: str
    evidence: str
    notes: str = ""

    def matches(self, link: "Link", *, state: str, source_id: str, county: str) -> bool:
        if self.state != state or self.source_id != source_id or self.county not in ("*", county):
            return False
        if self.match_kind == "column":
            return _norm(link.header) == _norm(self.match_value)
        if self.match_kind == "text":
            return _norm(link.text) == _norm(self.match_value)
        if self.match_kind == "host_path":
            parts = urlsplit(link.href)
            return (parts.hostname or "").lower() + parts.path == self.match_value
        return False


@dataclass(frozen=True)
class Link:
    header: str     # the header label of the cell the anchor sits in ("" when the table has none)
    text: str       # the anchor's own text
    href: str       # absolute URL (resolved against the page)


def _norm(label: str) -> str:
    key = re.sub(r"[^a-z0-9 ]", " ", (label or "").strip().lower())
    return re.sub(r"\s+", " ", key).strip()


def load_rules(path: Path | str = RULES_PATH) -> list[Rule]:
    """Every rule in the CSV, validated. An enabled rule without verified_on
    AND evidence, an unknown kind, a non-https host_path or a bad state
    code is refused outright - a typo cannot enable a link."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[Rule] = []
    with open(p, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != RULE_COLUMNS:
            raise ValueError(f"{p.name}: columns must be {RULE_COLUMNS}, got {reader.fieldnames}")
        for i, r in enumerate(reader, 2):
            rule = Rule(state=(r["state"] or "").strip(), source_id=(r["source_id"] or "").strip(), county=(r["county"] or "").strip() or "*",
                        match_kind=(r["match_kind"] or "").strip(), match_value=(r["match_value"] or "").strip(),
                        purchase_url_kind=(r["purchase_url_kind"] or "").strip(), enabled=(r["enabled"] or "").strip().lower() in _TRUE,
                        verified_on=(r["verified_on"] or "").strip(), evidence=(r["evidence"] or "").strip(), notes=(r["notes"] or "").strip())
            problems = rule_problems(rule)
            if problems:
                raise ValueError(f"{p.name} line {i}: " + "; ".join(problems))
            out.append(rule)
    return out


def rule_problems(rule: Rule) -> list[str]:
    problems: list[str] = []
    if not re.match(r"^[A-Z]{2}$", rule.state):
        problems.append(f"state {rule.state!r}")
    if not rule.source_id:
        problems.append("source_id required")
    if rule.match_kind not in MATCH_KINDS:
        problems.append(f"match_kind {rule.match_kind!r}")
    if not rule.match_value:
        problems.append("match_value required")
    if rule.purchase_url_kind not in PURCHASE_URL_KINDS:
        problems.append(f"purchase_url_kind {rule.purchase_url_kind!r}")
    if rule.match_kind == "host_path" and ("/" not in rule.match_value or rule.match_value.startswith(("http:", "https:"))):
        problems.append("host_path is 'host/path-prefix' without a scheme")
    if rule.enabled and not (re.match(r"^\d{4}-\d{2}-\d{2}$", rule.verified_on) and rule.evidence):
        problems.append("an enabled rule needs verified_on (YYYY-MM-DD) and evidence")
    return problems


# ---------------------------------------------------------------------------
# Capture: what the list publishes
# ---------------------------------------------------------------------------
def capture_links(table, base_url: str | None) -> list[list[Link]]:
    """One list of Links per <tr> of a BeautifulSoup table (parallel to the
    text rows the harvesters build with _table_to_rows: same <tr> order,
    same cell order). The header label is the <th>/<td> text of the first
    row at that cell index. Relative hrefs are resolved against base_url;
    with no base_url a relative href is dropped (never guessed)."""
    trs = table.find_all("tr")
    header: list[str] = []
    if trs:
        header = [c.get_text(" ", strip=True) for c in trs[0].find_all(["th", "td"])]
    out: list[list[Link]] = []
    for tr in trs:
        links: list[Link] = []
        for i, cell in enumerate(tr.find_all(["th", "td"])):
            for a in cell.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                absolute = urljoin(base_url, href) if base_url else (href if href.startswith(("http://", "https://")) else "")
                if not absolute:
                    continue
                links.append(Link(header=header[i] if i < len(header) else "", text=a.get_text(" ", strip=True), href=absolute))
        out.append(links)
    return out


def links_as_dicts(links: list[Link]) -> list[dict]:
    return [{"header": l.header, "text": l.text, "href": l.href} for l in links]


def links_from_dicts(items) -> list[Link]:
    out: list[Link] = []
    for d in items or []:
        if isinstance(d, dict) and d.get("href"):
            out.append(Link(header=str(d.get("header") or ""), text=str(d.get("text") or ""), href=str(d["href"])))
    return out


def masked_path(href: str) -> str:
    """host + path with every digit run replaced by '#': the SHAPE of a link
    with no identifier in it ('/TaxDeed/Detail/12345' -> '/TaxDeed/Detail/#')."""
    parts = urlsplit(href)
    path = _DIGITS.sub("#", parts.path or "/")
    query = "?" + "&".join(sorted(k for k in (p.split("=")[0] for p in parts.query.split("&")) if k)) if parts.query else ""
    return f"{(parts.hostname or '').lower()}{path}{query}"


def link_evidence(links_by_row: list[list[Link]], *, list_url: str | None, document_url: str | None) -> dict:
    """Value-free summary of what a county's list publishes as links."""
    headers: dict[str, int] = {}
    texts: dict[str, int] = {}
    shapes: dict[str, int] = {}
    rows_with_links = 0
    total = 0
    for links in links_by_row:
        if links:
            rows_with_links += 1
        for l in links:
            if l.href in (list_url, document_url):
                continue
            total += 1
            headers[l.header or "(no header)"] = headers.get(l.header or "(no header)", 0) + 1
            key = _DIGITS.sub("#", l.text)[:60] or "(no text)"
            texts[key] = texts.get(key, 0) + 1
            shape = masked_path(l.href)
            shapes[shape] = shapes.get(shape, 0) + 1
    return {"rows": len(links_by_row), "rows_with_links": rows_with_links, "links": total,
            "headers": dict(sorted(headers.items())), "link_texts": dict(sorted(texts.items())),
            "link_shapes": dict(sorted(shapes.items()))}


# ---------------------------------------------------------------------------
# Apply: only a verified rule turns a link into a purchase path
# ---------------------------------------------------------------------------
def untrusted_reason(href: str, *, list_url: str | None = None, document_url: str | None = None) -> str | None:
    """Why a URL cannot be a purchase path, or None when it is acceptable.
    Nothing here makes a URL a purchase path - only an evidence-backed rule
    or a registry row does; this is the refusal side."""
    if not isinstance(href, str) or not href.startswith("https://"):
        return "not https"
    if href in (list_url, document_url):
        return "the list page or the document itself"
    parts = urlsplit(href)
    host = (parts.hostname or "").lower()
    if not host:
        return "no host"
    if parts.path in ("", "/") and not parts.query:
        return "a bare homepage"
    if any(host == s or host.endswith("." + s) for s in UNTRUSTED_HOST_SUFFIXES):
        return f"untrusted host {host} (search engine or blocked vendor)"
    if parts.path.lower().startswith(("/search", "/results")) and parts.query and any(k in parts.query.lower() for k in ("q=", "query=", "search=")):
        return "a search-results page"
    return None


def acceptable_purchase_url(href: str, *, list_url: str | None, document_url: str | None) -> bool:
    return untrusted_reason(href, list_url=list_url, document_url=document_url) is None


def mode_problems(mode: str, *, purchase_url: str, purchase_url_kind: str, evidence: str) -> list[str]:
    """Validation of a source-level purchase-path mode against its URL, kind
    and evidence (used by the registry validator)."""
    problems: list[str] = []
    mode = (mode or "").strip() or "unknown"
    if mode not in PURCHASE_PATH_MODES:
        return [f"purchase_path_mode {mode!r}"]
    if mode in NON_URL_MODES:
        if mode in ("in_person_only", "phone_mail", "none") and not (evidence or "").strip():
            problems.append(f"purchase_path_mode {mode} must cite the source wording (purchase_path_evidence)")
        if purchase_url and mode != "unknown":
            problems.append(f"purchase_path_mode {mode} with a purchase_url")
    else:
        if not purchase_url or not purchase_url_kind:
            problems.append(f"purchase_path_mode {mode} needs purchase_url + purchase_url_kind")
        elif MODE_FOR_KIND.get(purchase_url_kind) != mode:
            problems.append(f"purchase_path_mode {mode} does not match purchase_url_kind {purchase_url_kind!r}")
        reason = untrusted_reason(purchase_url) if purchase_url else None
        if reason:
            problems.append(f"purchase_url is {reason}")
    return problems


def apply_rules(record: dict, links: list[Link], rules: list[Rule], *, state: str, source_id: str,
                list_url: str | None, document_url: str | None) -> str:
    """Sets record['purchase_url'] / ['purchase_url_kind'] / ['purchase_url_basis']
    from the first enabled rule that matches an acceptable link. Returns
    the basis text ('none' when nothing applied). Never overwrites a link
    the harvester already set."""
    if record.get("purchase_url"):
        return "already set by the harvester"
    county = str(record.get("county") or "")
    for rule in rules:
        if not rule.enabled:
            continue
        for link in links:
            if rule.matches(link, state=state, source_id=source_id, county=county) and \
                    acceptable_purchase_url(link.href, list_url=list_url, document_url=document_url):
                record["purchase_url"] = link.href
                record["purchase_url_kind"] = rule.purchase_url_kind
                record["purchase_url_basis"] = (f"rule {rule.match_kind}={rule.match_value!r} verified {rule.verified_on}: "
                                                f"{'property-level' if rule.purchase_url_kind in PROPERTY_KINDS else 'source-level'} "
                                                f"{rule.purchase_url_kind} link published on the list row")
                return record["purchase_url_basis"]
    return "none"


def write_evidence(entries: dict, path: Path | str = EVIDENCE_PATH) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"note": "labels, link text, hosts and digit-masked path shapes with counts only; never a row value or a full property URL",
                             "counties": entries}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p
