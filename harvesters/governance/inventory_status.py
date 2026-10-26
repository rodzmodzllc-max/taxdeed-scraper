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

AVAILABLE rows outside Florida (adapter-backed sources - land banks, county
repositories, forfeited-land lists, the Louisiana adjudicated list; 2026-10-11):
  available_otc     ONLY when the source's own status wording for the row is one
                    of that source's published "offered" wordings
                    (AVAILABLE_OFFERED_WORDINGS, pinned to the adapter configs)
  active            on the source's inventory list with no mapped availability
                    wording - list presence is all the source publishes
                    (a dated list says so in its basis)
  sold              only the source's own sold flag (arcgis sold_flag)
  closed            absent from the list at a COMPLETE / EMPTY read
Nothing else: a program name ("Own It Now") is kept verbatim as raw, never
read as a status, and absence is never a result.

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
                      "state_held", "resale_inventory", "available_otc", "closed", "unknown",
                      # LIENS & CERTIFICATES - the certificate product, never the land:
                      "certificate_listed",      # on the county-held / state-held list, purchasable (FL: LienHub county-held)
                      "certificate_redeemed",    # the source says the owner redeemed the certificate
                      "certificate_assigned",    # the source says the certificate was sold / assigned to a buyer
                      "certificate_expired")     # the source says it expired (FL: seven years, F.S. 197.482)
BASES = ("SOURCE_STATUS", "LIST_PRESENCE", "SCHEDULED_DATE", "NOT_PUBLISHED")

# Statuses that assert a RESULT. Only a SOURCE_STATUS basis may produce one.
# A certificate result (redeemed / assigned / expired) is a CERTIFICATE
# event, never a property sale - the vocabulary keeps the two apart by name.
RESULT_STATUSES = frozenset({"sold", "redeemed", "withdrawn", "cancelled", "struck_off",
                             "certificate_redeemed", "certificate_assigned", "certificate_expired"})

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
    return feed_auction_status(row, today=today, feed="the county's auction feed")


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


def fl_certificate_status(row: dict) -> StatusObservation:
    """A Florida county-held certificate row (LienHub). The list publishes
    presence only: a certificate that left it was redeemed OR bought by
    assignment OR expired - LienHub's county-held page does not say which,
    so absence is `closed`, never a certificate result. The certificate's
    own expiration date is a published fact but a passed date is not an
    observed expiry (a redeemed or assigned certificate leaves the list
    before then), so it is not asserted either."""
    ps = _pipeline_status(row.get("status"))
    if ps in GONE_PIPELINE_STATUSES:
        return StatusObservation("closed", "LIST_PRESENCE",
                                 note="absent from the county-held certificate list at a COMPLETE read; redeemed, assigned or expired is not published there")
    return StatusObservation("certificate_listed", "LIST_PRESENCE",
                             note="on the county-held certificate list at the last read; purchasable by assignment from the Tax Collector")


# The AVAILABLE sources' own "offered" wordings, as their adapter configs
# select or publish them (harvesters/otc/adapters/expansion.py: the DLBA
# layer's status filter, MO's status_include, MN's Status requirement, the
# ePropertyPlus `offered` rule). A row whose inventory_status_raw is one of
# these is `available_otc` on the source's own authority; tests pin this
# table to those configs so the two cannot drift. A source absent here
# publishes no per-row availability wording: list presence is all it says.
AVAILABLE_OFFERED_WORDINGS: dict[str, tuple[str, ...]] = {
    "mi_detroit_landbank_lots": ("Neighborhood Lot For Sale", "Side Lot For Sale", "Oversized Lot For Sale",
                                 "Marketed Lot For Sale", "Marketed Structure For Sale"),
    "mo_stl_lra_inventory": ("Available",),
    "mn_ramsey_tax_forfeit": ("Available for purchase",),
    "tn_shelby_landbank": ("FOR SALE",),
}


def source_id_of(row: dict) -> str:
    """The row's source id: `source_id` (migration 022, propagated from the
    registry) else the harvester's own `harvester_source`."""
    return str(row.get("source_id") or row.get("harvester_source") or "")


def available_record_status(row: dict, *, source_id: str) -> StatusObservation:
    """An AVAILABLE row from an adapter-backed source outside Florida (see
    the module docstring). `source_id` picks the offered-wording table; the
    row's otc_provenance is NOT required (a later sync can drop its
    `adapter` key - 6,334 Louisiana rows had on 2026-10-11)."""
    prov = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
    raw = str(row.get("inventory_status_raw") or "").strip() or None
    gone = _pipeline_status(row.get("status")) in GONE_PIPELINE_STATUSES
    if gone:
        return StatusObservation("closed", "LIST_PRESENCE", raw=raw,
                                 note="absent from the source's inventory list at a COMPLETE/EMPTY read; why is not published")
    if prov.get("published_outcome") == "sold" and raw:
        return StatusObservation("sold", "SOURCE_STATUS", raw=raw, note="the source's own sold flag on its inventory list")
    offered = {w.casefold() for w in AVAILABLE_OFFERED_WORDINGS.get(source_id, ())}
    if raw and raw.casefold() in offered:
        return StatusObservation("available_otc", "SOURCE_STATUS", raw=raw,
                                 note=f"the source's own availability status for this row ({source_id})")
    dated = _date_of(row.get("list_as_of"))
    where = f"the source's inventory list dated {dated.isoformat()}" if dated else "the source's current inventory list"
    if raw:
        return StatusObservation("active", "LIST_PRESENCE", raw=raw,
                                 note=f"on {where} at the last read; the wording is kept verbatim and is not a mapped availability status")
    return StatusObservation("active", "LIST_PRESENCE",
                             note=f"on {where} at the last read; the source publishes no per-row availability status")


def feed_auction_status(row: dict, *, today: date, feed: str) -> StatusObservation:
    """A deed-auction row read from a sale-calendar feed that publishes a
    scheduled date and presence, no result (Florida and Texas RealAuction)."""
    ps = _pipeline_status(row.get("status"))
    if ps in GONE_PIPELINE_STATUSES:
        return StatusObservation("closed", "LIST_PRESENCE", note=f"left {feed}; the result is not published there")
    sale = _date_of(row.get("sale_date"))
    if sale is None:
        return StatusObservation("active", "LIST_PRESENCE", note=f"on {feed}; no sale date published")
    if sale >= today:
        return StatusObservation("upcoming", "SCHEDULED_DATE", note=f"scheduled for {sale.isoformat()} per {feed}")
    return StatusObservation("unknown", "SCHEDULED_DATE",
                             note=f"sale date {sale.isoformat()} has passed; the feed publishes no result (sold / no sale / redeemed are not distinguishable)")


ADAPTER_KINDS = frozenset({"arcgis", "tabular"})


def adapter_record_status(row: dict, *, today: date) -> StatusObservation | None:
    """An AUCTIONS or LIENS & CERTIFICATES row written by the shared OTC
    adapters (harvesters/otc/adapters/arcgis.py / tabular.py - the
    five-state sources; otc_provenance.adapter says which). Data-driven: a
    new state configured through those adapters gets these semantics with
    no code here.

      auction, on the list:  sale date ahead -> upcoming; passed -> unknown
                             (no result published); none -> active.
      auction, off the list: the source's own sold flag
                             (inventory_status_raw, e.g. Eaton MI 'Sold: Yes')
                             or a published Sale Price in a past-sales table
                             (result_amount) -> sold, SOURCE_STATUS; anything
                             else -> closed (never sold from absence).
      certificate:           listed while on the list; closed once off it
                             (redeemed / assigned are not published)."""
    prov = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
    if prov.get("adapter") not in ADAPTER_KINDS:
        return None
    source = str(row.get("source") or "")
    gone = _pipeline_status(row.get("status")) in GONE_PIPELINE_STATUSES
    if source == "certificate":
        if gone:
            return StatusObservation("closed", "LIST_PRESENCE",
                                     note="absent from the county's certificate list at a COMPLETE read; redeemed or assigned is not published there")
        return StatusObservation("certificate_listed", "LIST_PRESENCE",
                                 note="on the county's list of certificates purchasable from the Treasurer at the last read")
    if source != "auction":
        return None
    if gone:
        raw = str(row.get("inventory_status_raw") or "").strip()
        if raw:
            return StatusObservation("sold", "SOURCE_STATUS", raw=raw, note="the source's own sold flag on its sale list")
        if row.get("result_amount") not in (None, ""):
            return StatusObservation("sold", "SOURCE_STATUS", raw="Previous Sales: Sale Price",
                                     note="listed in the county's own past-sales table with a published sale price")
        return StatusObservation("closed", "LIST_PRESENCE", note="no longer on the county's sale list; the result is not published there")
    if prov.get("list_superseded"):
        return StatusObservation("unknown", "SCHEDULED_DATE", note=str(prov["list_superseded"])[:300])
    sale = _date_of(row.get("sale_date"))
    if sale is None:
        return StatusObservation("active", "LIST_PRESENCE", note="on the county's current sale list; no sale date published on the list")
    if sale >= today:
        return StatusObservation("upcoming", "SCHEDULED_DATE", note=f"scheduled for {sale.isoformat()} per the county's sale list")
    return StatusObservation("unknown", "SCHEDULED_DATE",
                             note=f"sale date {sale.isoformat()} has passed; the list publishes no result")


def status_for_row(row: dict, *, today: date, sold_column_present: bool = False) -> StatusObservation | None:
    """Dispatch on the row's state / source / harvester. None = this row
    kind has no mapping (certificates; unknown vendors) - nothing is written."""
    state = str(row.get("state") or "FL")
    source = str(row.get("source") or "")
    sid = source_id_of(row)
    if state == "FL" and source == "laft":
        return fl_laft_status(row, sold_column_present=sold_column_present)
    if state == "FL" and source == "auction":
        return fl_auction_status(row, today=today)
    if state == "FL" and source == "certificate":
        return fl_certificate_status(row)
    if sid == "tx_lgbs":
        return tx_lgbs_status(row)
    if sid == "tx_realauction" and source == "auction":
        return feed_auction_status(row, today=today, feed="the county's RealAuction sale calendar")
    if state == "AL" and source == "laft":
        prov = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
        return alabama_status(str(prov.get("normalized_status") or "UNKNOWN"),
                              row.get("source_status_text") or prov.get("source_status_text"))
    if state != "FL" and source == "laft" and sid:
        # Every adapter-backed AVAILABLE source (LA, MI, MN, MO, OK, PA, SC,
        # TN ...). Before 2026-10-11 these fell through to
        # adapter_record_status, which maps auction / certificate rows only,
        # so ~54,000 rows never received a status.
        return available_record_status(row, source_id=sid)
    if state not in ("FL", "TX", "AL", "LA"):
        return adapter_record_status(row, today=today)
    return None


# Statuses that assert the row is on its source's list / feed NOW. Only these
# depend on the row having actually been read recently (apply_staleness).
CURRENT_PRESENCE_STATUSES = frozenset({"upcoming", "active", "available_otc", "certificate_listed",
                                       "state_held", "resale_inventory"})


def apply_staleness(obs: StatusObservation | None, row: dict, *, now) -> StatusObservation | None:
    """A presence status for a row no successful read has observed within its
    ledger's window (harvesters/ledgers/health.py row_observation: NEVER_READ
    or STALE) becomes `unknown`, so the row is no longer presented as listed,
    available or upcoming. Reader-side only: nothing is closed, a result is
    never inferred (closed / sold / redeemed pass through unchanged), and the
    next successful read restores the presence status. A row dict that does
    not carry the `last_seen_at` key (the column was not read) is left alone:
    it cannot be judged."""
    if obs is None or obs.status not in CURRENT_PRESENCE_STATUSES or "last_seen_at" not in row:
        return obs
    from ..ledgers import health as LH  # noqa: PLC0415 - avoids an import cycle at module load
    state = LH.row_observation(row, now)
    if state not in LH.NOT_CURRENT:
        return obs
    seen = LH.observed_at(row)
    why = ("never observed by a successful source read" if state == "NEVER_READ"
           else f"not observed by a successful source read since {seen.date().isoformat()}")
    return StatusObservation("unknown", "LIST_PRESENCE", raw=obs.raw,
                             note=f"{state}: {why}; the last presence status ({obs.status}) is not current; not closed")


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
    "certificate_listed": "Certificate listed (county-held)",
    "certificate_redeemed": "Certificate redeemed (per the source)",
    "certificate_assigned": "Certificate sold / assigned (per the source)",
    "certificate_expired": "Certificate expired (per the source)",
}
