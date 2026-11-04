"""The three ledgers' record contracts (2026-10-13).

`harvesters/ledgers/__init__.py` says which ledger a row belongs to and
`domains.py` names each ledger's scripts and files. This module is the
part those two did not have: what a record of each ledger IS, which
fields it may carry, what each field means, how a missing value reads, and
which combinations are classification bugs.

    AuctionRecord      a scheduled tax sale of a property (source='auction')
    AvailableRecord    property a government unit offers after / outside a
                       sale, by purchase or application (source='laft')
    CertificateRecord  the lien / certificate INSTRUMENT (source='certificate')
                       - never the land, never a sale of the land

Every record is read from the same `properties` row the pipeline already
writes (no second table, no second property identity); `property_key()`
is the shared property reference that lets one parcel be found in several
ledgers while each ledger keeps its own row, status and history.

`problems(row)` names what is wrong with a row for its own ledger; the
syncs refuse such rows before any write (sync_state_inventory.py,
sync-texas-to-supabase.py) and the status writer refuses a status outside
the row's ledger vocabulary (inventory_status_writer.py). `customer_view()`
is the ledger's backend contract for a customer surface: ledger-specific
fields, each either a published value or an explicit missing-value
wording - never a value borrowed from another field (an opening bid is
never a winning bid; a list page is never a purchase link; an application
quote is never a price; a certificate's assignment is never a property
sale).

Pure: no network, no database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

from . import (AVAILABLE_INVENTORY_TYPES, LEDGER_STATUSES, Ledger, ledger_for_ledger_type, ledger_for_row,
               ledgers_for_source_id, lgbs_status_ledger)

__all__ = ["NOT_PUBLISHED", "NO_PURCHASE_LINK", "OUTCOME_NOT_PUBLISHED", "LedgerViolation", "AuctionRecord",
           "AvailableRecord", "CertificateRecord", "record_for_row", "problems", "customer_view", "property_key",
           "status_allowed", "RESULT_STATUSES_BY_LEDGER"]

# Missing-value wordings. public/app.js uses the same strings (a test pins it).
NOT_PUBLISHED = "Not published"
NO_PURCHASE_LINK = "No online purchase link on file"
OUTCOME_NOT_PUBLISHED = "Not published by the source"

# Statuses that assert a RESULT, per ledger (harvesters/governance/inventory_status.py
# decides them, only from a source-published status). A certificate's results are
# results of the INSTRUMENT; none of them is a sale of the property.
RESULT_STATUSES_BY_LEDGER = {
    Ledger.AUCTIONS: frozenset({"sold", "redeemed", "withdrawn", "cancelled", "struck_off"}),
    Ledger.AVAILABLE: frozenset({"sold", "redeemed", "withdrawn", "cancelled"}),
    Ledger.LIENS_CERTIFICATES: frozenset({"certificate_redeemed", "certificate_assigned", "certificate_expired"}),
}

# Amount kinds that mean "no figure": the source quotes on application or
# publishes none. A row of these kinds never carries an amount.
NO_FIGURE_KINDS = frozenset({"QUOTED_ON_APPLICATION", "NOT_PUBLISHED"})

# What each Available amount kind is called (never "price" unless the source said so).
AMOUNT_KIND_LABELS = {
    "FIXED_PRICE": "Purchase price",
    "OPENING_BID": "Opening bid",
    "MINIMUM_BID": "Minimum bid",
    "BASE_PRICE": "Base purchase price",
    "ESTIMATED_AMOUNT": "Estimated amount",
    "PUBLISHED_AMOUNT_KIND_UNSPECIFIED": "Published amount (kind not stated)",
    "QUOTED_ON_APPLICATION": "Quoted on application",
    "NOT_PUBLISHED": NOT_PUBLISHED,
}

# Sources whose `parcel` column is NOT the property's parcel: Texas tax-suit
# vendors store the CAUSE number there and the CAD account in case_no
# (public/app.js parcelOf(); one cause covers several parcels).
CAUSE_IN_PARCEL_SOURCES = frozenset({"tx_lgbs", "tx_realauction", "tx_pbfcm", "tx_mvba", "tx_govease"})

# Fields that belong to one ledger only. A row of another ledger carrying one
# is a classification bug (it was built by the wrong path or merged across
# ledgers). Purchase / application paths are NOT Available-only: an auction's
# bid form and a certificate's assignment process are paths too.
AVAILABLE_ONLY_FIELDS = ("inventory_type",)
CERTIFICATE_ONLY_FIELDS = ("issued_date",)
RESULT_FIELDS = ("result_amount", "result_date", "result_party")


class LedgerViolation(ValueError):
    """A row presented as one ledger that belongs to (or carries fields of) another."""


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _num(v: Any) -> float | None:
    if _blank(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _prov(row: dict, key: str) -> dict:
    v = row.get(key)
    return v if isinstance(v, dict) else {}


def _source_id(row: dict) -> str:
    return str(row.get("source_id") or row.get("harvester_source") or "")


def status_allowed(ledger: Ledger, status: str | None) -> bool:
    """A normalized inventory status may be written to a row of `ledger` only
    if it is in that ledger's vocabulary (LEDGER_STATUSES)."""
    return status is None or status in LEDGER_STATUSES[ledger]


def property_key(row: dict) -> tuple[str, str, str] | None:
    """The shared property reference (state, county, normalized parcel) that
    joins one parcel's records across ledgers - the same exact-match rule as
    public/app.js relatedRecordsFor(): punctuation and case stripped, never an
    address or owner match. Texas tax-suit rows carry the cause number in
    `parcel`, so their parcel is the CAD account in case_no. None = the row
    publishes no parcel and cannot be matched."""
    sid = _source_id(row)
    raw = row.get("case_no") if sid in CAUSE_IN_PARCEL_SOURCES else row.get("parcel")
    norm = re.sub(r"[^0-9A-Za-z]", "", str(raw or "")).upper()
    if not norm:
        return None
    return (str(row.get("state") or "").upper(), str(row.get("county") or "").strip().casefold(), norm)


def _classification_problems(row: dict, ledger: Ledger) -> list[str]:
    out = []
    src = row.get("source")
    if src not in (None, "") and src != ledger.source:
        out.append(f"source {src!r} is not the {ledger.value} ledger ({ledger.source!r})")
    lt = row.get("ledger_type")
    if not _blank(lt):
        try:
            if ledger_for_ledger_type(str(lt)) is not ledger:
                out.append(f"ledger_type {lt!r} contradicts source {ledger.source!r}")
        except ValueError:
            out.append(f"unknown ledger_type {lt!r}")
    sid = _source_id(row)
    if sid:
        fed = ledgers_for_source_id(sid)
        if fed and ledger not in fed:
            out.append(f"source id {sid} does not feed {ledger.value} (it feeds {', '.join(sorted(l.value for l in fed))})")
    if sid == "tx_lgbs" and not _blank(row.get("tx_sale_status")):
        by_status = lgbs_status_ledger(row.get("tx_sale_status"))
        if by_status is not None and by_status is not ledger:
            out.append(f"the vendor's own sale status puts this LGBS row in {by_status.value}, not {ledger.value}")
    status = row.get("inventory_status")
    if not _blank(status) and not status_allowed(ledger, str(status)):
        out.append(f"inventory_status {status!r} is not a {ledger.value} status")
    return out


def _freshness(row: dict) -> dict:
    return {"last_read": row.get("last_seen_at") or None, "first_seen": row.get("first_seen_at") or None,
            "delisted_at": row.get("delisted_at") or None, "list_as_of": row.get("list_as_of") or None}


def _provenance(row: dict) -> dict:
    fp = _prov(row, "field_provenance")
    return {"source_id": _source_id(row) or None, "source_authority": row.get("source_authority") or None,
            "status_basis": row.get("inventory_status_basis") or None,
            "fields_with_origin": sorted(fp)}


@dataclass(frozen=True)
class _Record:
    row: dict = field(repr=False)

    ledger: ClassVar[Ledger]

    def __post_init__(self):
        got = ledger_for_row(self.row)
        if got is not None and got is not self.ledger:
            raise LedgerViolation(f"a {got.value} row is not a {self.ledger.value} record")

    @property
    def identity(self) -> tuple:
        return (self.row.get("state"), self.ledger.source, self.row.get("county"), self.row.get("case_no"))

    @property
    def property_key(self):
        return property_key(self.row)

    @property
    def status(self) -> str | None:
        s = self.row.get("inventory_status")
        return None if _blank(s) else str(s)

    @property
    def result_published(self) -> bool:
        return self.status in RESULT_STATUSES_BY_LEDGER[self.ledger]

    def problems(self) -> list[str]:
        out = _classification_problems(self.row, self.ledger)
        if self.ledger is not Ledger.AVAILABLE:
            out += [f"{self.ledger.value} row carries the Available field {f}" for f in AVAILABLE_ONLY_FIELDS
                    if not _blank(self.row.get(f))]
        if self.ledger is not Ledger.LIENS_CERTIFICATES:
            out += [f"{self.ledger.value} row carries the certificate field {f}" for f in CERTIFICATE_ONLY_FIELDS
                    if not _blank(self.row.get(f))]
        if self.ledger is Ledger.LIENS_CERTIFICATES:
            out += [f"certificate row carries the property-sale field {f} (a certificate result is never a property sale)"
                    for f in RESULT_FIELDS if not _blank(self.row.get(f))]
        elif self.status is not None and not self.result_published:
            # A result field beside a non-result status: the result was not
            # published by the source (or a status writer has not run yet:
            # no status, no judgment).
            out += [f"{f} beside status {self.status!r} (not a source-published result)" for f in RESULT_FIELDS
                    if not _blank(self.row.get(f))]
        return out

    def _base_view(self) -> dict:
        return {"ledger": self.ledger.value, "ledger_name": self.ledger.customer_name, "id": self.row.get("id"),
                "state": self.row.get("state"), "county": self.row.get("county"),
                "property_key": list(self.property_key) if self.property_key else None,
                "status": self.status, "raw_status": self.row.get("inventory_status_raw") or None,
                "freshness": _freshness(self.row), "provenance": _provenance(self.row)}


@dataclass(frozen=True)
class AuctionRecord(_Record):
    ledger: ClassVar[Ledger] = Ledger.AUCTIONS

    @property
    def opening_bid(self) -> float | None:
        """The published opening / minimum bid (bid > 0 or a published
        purchase_amount; 0 is the legacy 'not posted yet' sentinel). It is the
        price a sale STARTS at - never a result."""
        if self.row.get("purchase_amount_kind") == "NOT_PUBLISHED":
            return None
        for k in ("min_bid", "purchase_amount", "bid"):
            v = _num(self.row.get(k))
            if v is not None and v > 0:
                return v
        return None

    @property
    def winning_bid(self) -> float | None:
        """Only a result the source published as a sale amount - never the
        opening bid, never inferred from absence."""
        if self.status != "sold":
            return None
        v = _num(self.row.get("result_amount"))
        return v if v is not None and v > 0 else None


    def customer_view(self) -> dict:
        v = self._base_view()
        r = self.row
        url = r.get("url_auction") or None
        v.update({
            "auction_id": r.get("case_no"), "parcel": r.get("parcel") or None,
            "certificate_no": r.get("certificate_no") or None,
            "sale_date": r.get("sale_date") or NOT_PUBLISHED,
            "opening_bid": self.opening_bid if self.opening_bid is not None else NOT_PUBLISHED,
            "auction_url": url if url else NOT_PUBLISHED,
            "auction_url_kind": (r.get("url_auction_kind") or None) if url else None,
            "raw_source_status": r.get("tx_sale_status") or r.get("inventory_status_raw") or None,
            "result": self.status if self.result_published else OUTCOME_NOT_PUBLISHED,
            "winning_bid": self.winning_bid if self.winning_bid is not None else NOT_PUBLISHED,
            "result_date": (r.get("result_date") or NOT_PUBLISHED) if self.result_published else NOT_PUBLISHED,
            "history": "auction_events + auction_event_observations",
        })
        return v


@dataclass(frozen=True)
class AvailableRecord(_Record):
    ledger: ClassVar[Ledger] = Ledger.AVAILABLE

    @property
    def amount_kind(self) -> str | None:
        k = self.row.get("purchase_amount_kind")
        return None if _blank(k) else str(k)

    @property
    def amount(self) -> float | None:
        """The published asking / application amount, of the source's own kind.
        No figure when the source quotes on application or publishes none."""
        if self.amount_kind in NO_FIGURE_KINDS:
            return None
        v = _num(self.row.get("purchase_amount"))
        if v is not None and v > 0:
            return v
        if self.amount_kind is None:   # pre-017 rows: the legacy bid > 0 rule
            b = _num(self.row.get("bid"))
            return b if b is not None and b > 0 else None
        return None

    @property
    def purchase_link(self) -> str | None:
        """Only the row's own verified purchase / application link - never the
        inventory list, never the source document, never a constructed URL."""
        u = self.row.get("purchase_url")
        if _blank(u) or not str(u).startswith("https://"):
            return None
        if str(u).strip() in {str(self.row.get("list_url") or "").strip(), str(self.row.get("document_url") or "").strip()}:
            return None
        return str(u).strip()

    def problems(self) -> list[str]:
        out = super().problems()
        it = self.row.get("inventory_type")
        if not _blank(it) and it not in AVAILABLE_INVENTORY_TYPES:
            out.append(f"inventory_type {it!r} is not an Available inventory type")
        amt = _num(self.row.get("purchase_amount"))
        if amt is not None and amt > 0 and self.amount_kind is None:
            out.append("purchase_amount without purchase_amount_kind (an amount's kind is never assumed)")
        if amt is not None and amt > 0 and self.amount_kind in NO_FIGURE_KINDS:
            out.append(f"purchase_amount present with kind {self.amount_kind} (that kind publishes no figure)")
        return out

    def customer_view(self) -> dict:
        v = self._base_view()
        r = self.row
        prov = _prov(r, "otc_provenance")
        kind = self.amount_kind
        amount = self.amount
        v.update({
            "inventory_id": r.get("case_no"), "parcel": r.get("parcel") or None,
            "inventory_type": r.get("inventory_type") or None,
            "availability": self.status or NOT_PUBLISHED,
            "amount": amount if amount is not None else NOT_PUBLISHED,
            "amount_kind": kind or (None if amount is None else "LEGACY_BID"),
            "amount_label": AMOUNT_KIND_LABELS.get(kind, "Published amount") if amount is not None else
                            AMOUNT_KIND_LABELS.get(kind, NOT_PUBLISHED),
            "purchase_link": self.purchase_link or NO_PURCHASE_LINK,
            "inventory_list_url": r.get("list_url") or NOT_PUBLISHED,
            "source_document_url": r.get("document_url") or None,
            "application_instructions": prov.get("purchase_instructions") or NOT_PUBLISHED,
            "list_as_of": r.get("list_as_of") or NOT_PUBLISHED,
            "available_date": r.get("available_date") or NOT_PUBLISHED,
            "closed": r.get("status") in ("closed", "dropped", "sold", "notfound") or self.status == "closed",
            "history": "inventory_status_observations",
        })
        return v


@dataclass(frozen=True)
class CertificateRecord(_Record):
    ledger: ClassVar[Ledger] = Ledger.LIENS_CERTIFICATES

    @property
    def face_amount(self) -> float | None:
        v = _num(self.row.get("bid"))
        return v if v is not None and v > 0 else None


    def customer_view(self) -> dict:
        v = self._base_view()
        r = self.row
        v.update({
            "certificate_no": r.get("certificate_no") or r.get("case_no"),
            "parcel": r.get("parcel") or None,
            "tax_year": r.get("tax_year") or NOT_PUBLISHED,
            "face_amount": self.face_amount if self.face_amount is not None else NOT_PUBLISHED,
            "minimum_bid": _num(r.get("min_bid")) or NOT_PUBLISHED,
            "interest_rate": _num(r.get("interest_rate")) if _num(r.get("interest_rate")) is not None else NOT_PUBLISHED,
            "penalty": NOT_PUBLISHED,
            "certificate_sale_date": r.get("issued_date") or NOT_PUBLISHED,
            "expiration_date": r.get("expiration_date") or NOT_PUBLISHED,
            "redemption": self.status if self.result_published else OUTCOME_NOT_PUBLISHED,
            # The holder is never the property's assessed owner (owner_name).
            "holder": NOT_PUBLISHED,
            "instrument": "lien certificate - not ownership of the property",
            "history": "inventory_status_observations",
        })
        return v


_CLASSES = {Ledger.AUCTIONS: AuctionRecord, Ledger.AVAILABLE: AvailableRecord,
            Ledger.LIENS_CERTIFICATES: CertificateRecord}


def record_for_row(row: dict) -> _Record:
    ledger = ledger_for_row(row)
    if ledger is None:
        raise LedgerViolation("row cannot be classified into a ledger (no source / ledger_type)")
    return _CLASSES[ledger](row)


def problems(row: dict) -> list[str]:
    """Every ledger-contract problem of a row, or ['unclassifiable ...']."""
    try:
        return record_for_row(row).problems()
    except LedgerViolation as exc:
        return [str(exc)]


def customer_view(row: dict) -> dict:
    return record_for_row(row).customer_view()
