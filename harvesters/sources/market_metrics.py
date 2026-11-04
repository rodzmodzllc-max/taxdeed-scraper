"""Market measurement for commercial testing: explicit rules, no score.

A "market" is one state x ledger (AVAILABLE / AUCTION / LIEN); a "county
market" is one state x county x ledger. Both are measured from
data/market_audit_snapshot.json (counts only, read-only production audit:
"units" and "county_units", the county sums equal the state units) and the
repository's own evidence: verified acquisition counties
(public/acquisition-evidence.json) and documented caveats
(data/market_caveats.csv; a caveat names a state x ledger, optionally narrowed
to one county). County markets are classified by the same rules.

Every market gets the underlying metrics and one tier from rules that can be
read in a sentence each:

  HELD         no customer-visible record (the source is not cleared for
               customers). Preserved for admins; never shown as a market.
  NOT_CURRENT  visible, but the inventory is a finished sale.
  FOCUS        visible, and every FOCUS rule holds:
                 identity     >= 95% of visible records carry a parcel / account id
                 coordinates  >= 75% carry coordinates (imagery-capable)
                 path         >= 80% carry their ledger's published path
                              (the sale page for auctions; the certificate
                              sale page or acquisition evidence for liens;
                              verified acquisition evidence for Available)
                 current      no freshness / dated-list / source-review caveat
  BROWSE       visible, and at least one FOCUS rule fails; the failed rules
               are listed by name.

The shortlist is deterministic and shows its ordering keys: FOCUS markets by
visible records, then BROWSE markets by number of failed rules and visible
records; NOT_CURRENT and HELD markets are not prioritized. Raw size never
promotes a market past a failed rule.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO / "data" / "market_audit_snapshot.json"
CAVEATS = REPO / "data" / "market_caveats.csv"

THRESHOLDS = {"identity": 0.95, "coordinates": 0.75, "path": 0.80}
BLOCKING_CAVEATS = frozenset({"freshness", "dated_list", "source_review"})
TIERS = ("FOCUS", "BROWSE", "NOT_CURRENT", "HELD")
RULE_LABELS = {
    "identity": "fewer than 95% of visible records carry a parcel / account identifier",
    "coordinates": "fewer than 75% of visible records carry coordinates",
    "path": "fewer than 80% of visible records carry the ledger's published path",
    "current": "a freshness, dated-list or source-review caveat applies",
}


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


@dataclass
class Market:
    state: str
    ledger: str
    unit: dict
    caveats: list = field(default_factory=list)
    verified_counties: int = 0
    tier: str = ""
    failed: list = field(default_factory=list)
    county: str = ""          # set for a county market (state x county x ledger)

    @property
    def name(self) -> str:
        base = f"{self.state} {self.ledger.title()}"
        return f"{base} · {self.county}" if self.county else base

    @property
    def visible(self) -> int:
        return int(self.unit.get("visible") or 0)

    def share(self, metric: str) -> float:
        """metric over active records (visible for visible markets)."""
        d = self.unit["active"]
        return (self.unit.get(metric) or 0) / d if d else 0.0

    def path_metric(self) -> str:
        """The ledger's published path: the sale page for auctions; for liens
        the certificate sale page or acquisition evidence, whichever the
        source gives; for Available only verified acquisition evidence (an
        Available list page is not a purchase path)."""
        if self.ledger == "AUCTION":
            return "auction_url"
        if self.ledger == "LIEN":
            return max(("acquisition_evidence", "auction_url"), key=lambda k: self.unit.get(k) or 0)
        return "acquisition_evidence"

    def metrics(self) -> dict:
        u = self.unit
        a = u["active"]
        return {
            "counties": u.get("counties", 1), "active": a, "visible": u["visible"],
            "coordinates_pct": _pct(u["coordinates"], a),
            "authoritative_coordinates_pct": _pct(u["authoritative_coordinates"], a),
            "identity_pct": _pct(u["parcel"], a),
            "legal_description_pct": _pct(u["legal_description"], a),
            "assessed_value_pct": _pct(u["assessed_value"], a),
            "taxable_value_pct": _pct(u["taxable_value"], a),
            "acreage_pct": _pct(u["acreage"], a),
            "land_use_pct": _pct(u["land_use"], a),
            "path_metric": self.path_metric(),
            "path_pct": _pct(u[self.path_metric()], a),
            # Live USDA NAIP needs coordinates and no '' "checked, no image" sentinel.
            "imagery_capable_pct": _pct(u.get("imagery_capable", u["coordinates"]), a),
            "stored_imagery_pct": _pct(u["stored_imagery"], a),
            "verified_acquisition_counties": self.verified_counties,
        }


def load_snapshot(path: Path = SNAPSHOT) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_caveats(path: Path = CAVEATS) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def verified_counties_by_state(repo: Path = REPO) -> dict[str, int]:
    from harvesters.enrichment.priority import load_verified_counties
    out: dict[str, int] = {}
    for st, _county in load_verified_counties(repo):
        out[st] = out.get(st, 0) + 1
    return out


def verified_county_set(repo: Path = REPO) -> set[tuple[str, str]]:
    from harvesters.enrichment.priority import load_verified_counties
    return set(load_verified_counties(repo))


def _caveats_for(caveats, state: str, ledger: str, county: str = "") -> list:
    """A caveat names a state x ledger; an optional county column narrows it to
    one county (the state market still carries it)."""
    out = []
    for c in caveats:
        if c["state"] != state or c["ledger"] != ledger:
            continue
        cc = (c.get("county") or "").strip()
        if county and cc and cc != county:
            continue
        out.append(c)
    return out


def _wanted(value: str, allowed) -> bool:
    return not allowed or value in {str(a).strip() for a in allowed}


def classify(m: Market) -> Market:
    if m.visible == 0:
        m.tier, m.failed = "HELD", ["not_customer_visible"]
        return m
    if any(c["kind"] == "not_current" for c in m.caveats):
        m.tier, m.failed = "NOT_CURRENT", ["not_current"]
        return m
    failed = []
    if m.share("parcel") < THRESHOLDS["identity"]:
        failed.append("identity")
    if m.share("coordinates") < THRESHOLDS["coordinates"]:
        failed.append("coordinates")
    if m.share(m.path_metric()) < THRESHOLDS["path"]:
        failed.append("path")
    if any(c["kind"] in BLOCKING_CAVEATS for c in m.caveats):
        failed.append("current")
    m.failed = failed
    m.tier = "FOCUS" if not failed else "BROWSE"
    return m


def markets(snapshot: dict | None = None, caveats: list | None = None, verified: dict | None = None,
            states=None, ledgers=None) -> list[Market]:
    """State x ledger markets, optionally filtered by state / ledger."""
    snapshot = snapshot if snapshot is not None else load_snapshot()
    caveats = caveats if caveats is not None else load_caveats()
    verified = verified if verified is not None else verified_counties_by_state()
    out = []
    for u in snapshot["units"]:
        if not (_wanted(u["state"], states) and _wanted(u["ledger"], ledgers)):
            continue
        m = Market(u["state"], u["ledger"], u, caveats=_caveats_for(caveats, u["state"], u["ledger"]),
                   verified_counties=verified.get(u["state"], 0) if u["ledger"] == "AVAILABLE" else 0)
        out.append(classify(m))
    return out


def county_markets(snapshot: dict | None = None, caveats: list | None = None, verified: set | None = None,
                   states=None, counties=None, ledgers=None) -> list[Market]:
    """State x county x ledger markets from snapshot["county_units"], classified
    by the same rules (a state x ledger caveat applies to each of its counties),
    optionally filtered by state / county / ledger."""
    snapshot = snapshot if snapshot is not None else load_snapshot()
    caveats = caveats if caveats is not None else load_caveats()
    verified = verified if verified is not None else verified_county_set()
    out = []
    for u in snapshot.get("county_units") or []:
        if not (_wanted(u["state"], states) and _wanted(u["county"], counties) and _wanted(u["ledger"], ledgers)):
            continue
        m = Market(u["state"], u["ledger"], dict(u, counties=1), county=u["county"],
                   caveats=_caveats_for(caveats, u["state"], u["ledger"], u["county"]),
                   verified_counties=int((u["state"], u["county"]) in verified) if u["ledger"] == "AVAILABLE" else 0)
        out.append(classify(m))
    return out


def counties_of(m: Market, county_ms: list[Market]) -> list[Market]:
    """A state x ledger market's county markets: FOCUS first, then by failed
    rules, then visible and active records - the same keys as the shortlist."""
    mine = [c for c in county_ms if c.state == m.state and c.ledger == m.ledger]
    return sorted(mine, key=lambda c: (TIERS.index(c.tier), len(c.failed), -c.visible, -int(c.unit["active"]), c.county))


def market_test_counties(m: Market, county_ms: list[Market]) -> list[Market]:
    """The counties of a market that are listed for market testing: visible,
    and failing no rule the market itself does not fail (a county never weaker
    than the market it represents)."""
    return [c for c in counties_of(m, county_ms) if c.visible and set(c.failed) <= set(m.failed)]


def shortlist(ms: list[Market], n: int = 5) -> dict:
    focus = sorted((m for m in ms if m.tier == "FOCUS"), key=lambda m: (-m.visible, m.name))
    browse = sorted((m for m in ms if m.tier == "BROWSE"), key=lambda m: (len(m.failed), -m.visible, m.name))
    held = sorted((m for m in ms if m.tier in ("NOT_CURRENT", "HELD")), key=lambda m: (-int(m.unit["active"]), m.name))
    ranked = focus + browse
    return {"strongest": ranked[:n], "secondary": ranked[n:2 * n], "not_prioritized": held[:n],
            "also_not_prioritized": held[n:] + ranked[2 * n:]}


def visibility(m: Market) -> str:
    """How a market's inventory is exposed - never hidden for being large."""
    if m.tier == "HELD":
        return "admins only until the source is cleared for customers; counted, never shown to customers"
    if m.tier == "NOT_CURRENT":
        return "reachable through state / county navigation; never featured as a current opportunity"
    if m.tier == "FOCUS":
        return "customer-visible; reachable through state / county navigation"
    return "customer-visible; reachable through state / county navigation; gaps named on every record"
