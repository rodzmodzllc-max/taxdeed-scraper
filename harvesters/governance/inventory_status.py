"""Inventory / lifecycle status of a property row, normalized across sources
(production-readiness program, 2026-09-30).

`properties.status` is a pipeline word (active / closed / dropped /
notfound / available) that only says whether the row is still on the
feed or list it was read from. Customers need the lifecycle state the
SOURCE actually supports - and nothing more. This module is the one
vocabulary and the per-source, deterministic mappings that produce it.
Every status carries its BASIS (what kind of evidence produced it) and
the source's own wording verbatim, so a reader can always tell a
source-published state from a list-presence observation.

THE RULE: a row that merely disappeared is `closed` ("left the list /
feed") or, for a past-dated auction, `unknown` ("sale date passed, result
not published"). Sold, redeemed, cancelled, withdrawn and struck_off are
asserted ONLY from a status the source itself published (basis
SOURCE_STATUS). Nothing here infers a result from absence, from a date,
from a bid, or from a row count.

Vocabulary (also migration 021's check constraint, byte-for-byte):
  upcoming          a sale is scheduled for a future date (auction ledgers)
  active            on the current feed/list, no finer state published
  sold              the source says it sold
  redeemed          the source says the owner redeemed it
  withdrawn         the source says it was withdrawn from sale
  cancelled         the source says the sale was cancelled
  struck_off        the source says it was struck off to a taxing unit
  state_held        held by a state agency, available by application (AL)
  resale_inventory  held for a future resale (TX "Available for Future Sale")
  available_otc     purchasable now over the counter at a published process (FL Lands Available)
  closed            left the list / feed (an observation, not an outcome)
  unknown           the source published no state that this vocabulary covers, or a sale date passed with no result published

Bases:
  SOURCE_STATUS   the source's own status wording (raw kept verbatim)
  LIST_PRESENCE   whether the row was on the list/feed at the last COMPLETE/EMPTY read
  SCHEDULED_DATE  the relation between today and the source's scheduled sale date
  NOT_PUBLISHED   the source publishes no state for this row
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

INVENTORY_STATUSES = ("upcoming", "active", "sold", "redeemed", "withdrawn", "cancelled", "struck_off",
                      "state_held", "resale_inventory", "available_otc", "closed", "unknown")
BASES = ("SOURCE_STATUS", "LIST_PRESENCE", "SCHEDULED_DATE", "NOT_PUBLISHED")

# Statuses that assert a RESULT. Only a SOURCE_STATUS basis may produce one.
RESULT_STATUSES = frozenset({"sold", "redeemed", "withdrawn", "cancelled", "struck_off"})

# properties.status words that mean "no longer on the feed/list" (app.js
# GONE_STATUSES, migration 006's trigger list, laft_lifecycle.GONE_STATUSES).
GONE_PIPELINE_STATUSES = frozenset({"closed", "dropped", "sold", "notfound"})

# LGBS's raw sale statuses (harvesters/texas_harvester.py LGBS_STATUS_TO_LEDGER
# names exactly these four; any other wording the vendor publishes is kept
# verbatim and normalized to `unknown` - never guessed).
LGBS_STATUS_MAP = {
    "scheduled for auction": "upcoming",
    "scheduled for online auction": "upcoming",
    "available for future sale": "resale_inventory",
    "struck off to jurisdiction": "struck_off",
}

# harvesters/otc/adapters/alabama.py AlabamaStatus -> vocabulary.
ALABAMA_STATUS_MAP = {
    "AVAILABLE_FOR_SALE": "state_held",
    "SOLD": "sold",
    "REDEEMED": "redeemed",
    "WITHDRAWN": "withdrawn",
    "UNKNOWN": "unknown",
}


@dataclass(frozen=True)
class StatusObservation:
    status: str
    basis: str
    raw: str | None = None          # the source's own wording, verbatim (never a name, amount or identifier)
    note: str = ""                  # why, in one line (goes to inventory_status_basis)

    def __post_init__(self) -> None:
        if self.status not in INVENTORY_STATUSES:
            raise ValueError(f"unknown inventory status {self.status!r}")
        if self.basis not in BASES:
            raise ValueError(f"unknown basis {self.basis!r}")
        if self.status in RESULT_STATUSES and self.basis != "SOURCE_STATUS":
            raise ValueError(f"{self.status} may only come from the source's own status (basis SOURCE_STATUS), not {self.basis}")

    def basis_text(self) -> str:
        return f"{self.basis}: {self.note}" if self.note else self.basis


def _pipeline_status(value) -> str:
    return str(value or "active").strip().lower()


def fl_laft_status(row: dict, *, sold_column_present: bool = False) -> StatusObservation:
    """A Florida Lands Available row. `sold_column_present` = the county's
    list carried a non-blank 'Sold To' / 'Purchaser' cell for this parcel
    (the harvesters read that column; harvest_laft_html/pdfs drop such rows
    from the AVAILABLE inventory, and the lifecycle passes the fact here).
    Otherwise the list's presence is all the county publishes."""
    if sold_column_present:
        return StatusObservation("sold", "SOURCE_STATUS", raw="Sold To",
                                 note="the county list's own 'Sold To' column carries a value for this parcel")
    ps = _pipeline_status(row.get("status"))
    if ps in GONE_PIPELINE_STATUSES:
        return StatusObservation("closed", "LIST_PRESENCE", raw=None,
                                 note="absent from the county's Lands Available list at a COMPLETE/EMPTY read; why is not published")
    return StatusObservation("available_otc", "LIST_PRESENCE", raw=None,
                             note="on the county's Lands Available list at the last read (F.S. 197.502(7))")


def fl_auction_status(row: dict, *, today: date) -> StatusObservation:
    """A Florida deed-auction row. The feed publishes a scheduled date and
    presence; no result."""
    ps = _pipeline_status(row.get("status"))
    if ps in GONE_PIPELINE_STATUSES:
        return StatusObservation("closed", "LIST_PRESENCE", note="left the county's auction feed; the result is not published there")
    sale = _date_of(row.get("sale_date"))
    if sale is None:
        return StatusObservation("active", "LIST_PRESENCE", note="on the county's auction feed; no sale date published")
    if sale >= today:
        return StatusObservation("upcoming", "SCHEDULED_DATE", note=f"scheduled for {sale.isoformat()} per the county's auction feed")
    return StatusObservation("unknown", "SCHEDULED_DATE",
                             note=f"sale date {sale.isoformat()} has passed; the feed publishes no result (sold / no sale / redeemed are not distinguishable)")


def tx_lgbs_status(row: dict) -> StatusObservation:
    """A Texas LGBS row: the vendor's raw sale status is the only state it
    publishes (properties.tx_sale_status, verbatim)."""
    raw = str(row.get("tx_sale_status") or "").strip()
    if not raw:
        ps = _pipeline_status(row.get("status"))
        if ps in GONE_PIPELINE_STATUSES:
            return StatusObservation("closed", "LIST_PRESENCE", note="left the vendor feed; no status published")
        return StatusObservation("unknown", "NOT_PUBLISHED", note="the vendor row carries no sale status")
    status = LGBS_STATUS_MAP.get(raw.lower())
    if status is None:
        return StatusObservation("unknown", "SOURCE_STATUS", raw=raw, note="vendor status wording outside the mapped vocabulary; kept verbatim")
    if status == "upcoming":
        sale = _date_of(row.get("sale_date"))
        if sale is not None and sale < date.today():
            # Vendor still says scheduled but the date passed: the feed has
            # not been re-read since; do not claim a result.
            return StatusObservation("unknown", "SOURCE_STATUS", raw=raw,
                                     note="vendor status says scheduled but the sale date has passed; no result published")
    return StatusObservation(status, "SOURCE_STATUS", raw=raw, note="the vendor's own sale status (LGBS)")


def alabama_status(normalized: str, raw: str | None) -> StatusObservation:
    """harvesters/otc/adapters/alabama.py's normalized status + the list's
    own wording."""
    status = ALABAMA_STATUS_MAP.get(normalized, "unknown")
    if raw:
        return StatusObservation(status, "SOURCE_STATUS", raw=raw, note="the State's list wording, through the configured vocabulary")
    if status == "state_held":
        return StatusObservation(status, "LIST_PRESENCE", note="on the State's list of land available for purchase by application")
    return StatusObservation("unknown", "NOT_PUBLISHED", note="the list publishes no status for this row")


def status_for_row(row: dict, *, today: date, sold_column_present: bool = False) -> StatusObservation | None:
    """Dispatch on the row's state / source / harvester. None = this row
    kind has no mapping (certificates; unknown vendors) - nothing is written."""
    state = str(row.get("state") or "FL")
    source = str(row.get("source") or "")
    hs = str(row.get("harvester_source") or "")
    if state == "FL" and source == "laft":
        return fl_laft_status(row, sold_column_present=sold_column_present)
    if state == "FL" and source == "auction":
        return fl_auction_status(row, today=today)
    if state == "TX" and hs == "tx_lgbs":
        return tx_lgbs_status(row)
    if state == "AL" and source == "laft":
        prov = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
        return alabama_status(str(prov.get("normalized_status") or "UNKNOWN"),
                              row.get("source_status_text") or prov.get("source_status_text"))
    return None


def _date_of(value) -> date | None:
    if value is None:
        return None
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        m, d, y = text.split("/")
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


# Customer-facing labels (factual; no score, no badge). Mirrored in
# public/app.js INVENTORY_STATUS_LABELS - a test keeps the keys in step.
LABELS = {
    "upcoming": "Upcoming sale",
    "active": "Listed",
    "sold": "Sold (per the source)",
    "redeemed": "Redeemed (per the source)",
    "withdrawn": "Withdrawn (per the source)",
    "cancelled": "Cancelled (per the source)",
    "struck_off": "Struck off to the taxing unit (per the source)",
    "state_held": "State-held; available by application",
    "resale_inventory": "Held for a future resale",
    "available_otc": "Available over the counter",
    "closed": "Left the list / feed",
    "unknown": "Not published",
}
