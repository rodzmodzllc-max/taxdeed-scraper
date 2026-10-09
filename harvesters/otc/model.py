"""The OTC record contract: what an adapter must produce for one property
on a post-sale / struck-off / future-resale list, and how that maps onto
the `properties` row shape migration 017 defines.

Every field is either read from the source or NULL. There is no default
amount, no default date, no default URL, no inferred outcome.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum

from ..governance import states
from ..governance.county_source_registry import (DB_SUPPORTED_INVENTORY_TYPES, InventoryType,
                                                 PurchaseUrlKind, SourceAuthority)

from decimal import ROUND_HALF_UP, Decimal


def to_cents(value: float | None) -> float | None:
    """A currency amount rounded to whole cents (half away from zero), or
    None. Spreadsheet cells and PDF text reach the adapters as floats that
    can carry representation noise (0.30000000000000004) or a stray third
    decimal; public.properties stores `bid` / `min_bid` / `assessed` /
    `market` as numeric(12,2) but `purchase_amount` / `result_amount` /
    `taxable_value` / `land_value` / `improvement_value` as unbounded
    numeric, so the same figure landed rounded in one column and raw in
    another (Horry SC, 2026-10-09: 23 rows, |bid - purchase_amount| <=
    0.005). Rounding once here, from the float's shortest repr (what JSON
    sends), matches Postgres' numeric(12,2) rounding. Only currency fields
    go through this - never acreage, coordinates, rates or identifiers."""
    if value is None:
        return None
    return float(Decimal(repr(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# Currency columns an OtcRecord carries besides its amount / result_amount.
CURRENCY_VALUE_FIELDS = ("assessed", "market", "taxable_value", "land_value", "improvement_value")


__all__ = ["AmountKind", "DB_SUPPORTED_AMOUNT_KINDS", "DB_SUPPORTED_INVENTORY_TYPES", "InventoryType",
           "OtcRecord", "PurchaseUrlKind", "SourceAuthority", "UrlRef", "to_cents"]


class AmountKind(str, Enum):
    # --- carried by public.properties today (migration 017's check constraint)
    MINIMUM_PURCHASE_AMOUNT = "MINIMUM_PURCHASE_AMOUNT"
    OPENING_BID = "OPENING_BID"
    ORIGINAL_OPENING_BID = "ORIGINAL_OPENING_BID"
    FIXED_PURCHASE_PRICE = "FIXED_PURCHASE_PRICE"
    ESTIMATED_PURCHASE_PRICE = "ESTIMATED_PURCHASE_PRICE"
    PUBLISHED_AMOUNT_KIND_UNSPECIFIED = "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"
    NOT_PUBLISHED = "NOT_PUBLISHED"
    # --- model vocabulary only: NOT in the 017 constraint, NOT storable until
    #     a future migration widens it. The source publishes no figure at
    #     all: the price is quoted to the applicant after an application
    #     (the state-land-office pattern the 50-state audit found). Like
    #     NOT_PUBLISHED it carries no amount - it says WHY there is none.
    QUOTED_ON_APPLICATION = "QUOTED_ON_APPLICATION"


# Exactly what the purchase_amount_kind constraint allows: migration 017's
# values plus QUOTED_ON_APPLICATION (migration 020, applied 2026-09-30).
DB_SUPPORTED_AMOUNT_KINDS = frozenset({
    AmountKind.MINIMUM_PURCHASE_AMOUNT.value, AmountKind.OPENING_BID.value,
    AmountKind.ORIGINAL_OPENING_BID.value, AmountKind.FIXED_PURCHASE_PRICE.value,
    AmountKind.ESTIMATED_PURCHASE_PRICE.value, AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED.value,
    AmountKind.NOT_PUBLISHED.value, AmountKind.QUOTED_ON_APPLICATION.value,
})

# Amount kinds that mean "no figure was published" - the amount must be None.
AMOUNTLESS_KINDS = frozenset({AmountKind.NOT_PUBLISHED, AmountKind.QUOTED_ON_APPLICATION})


@dataclass(frozen=True)
class UrlRef:
    """A URL and what it is. `kind` is one of the three OTC URL roles:
    'list' (the page the row was read from), 'document' (the file), or a
    PurchaseUrlKind value (where the buyer acts)."""
    url: str
    kind: str

    def __post_init__(self) -> None:
        if not self.url.startswith("https://"):
            raise ValueError(f"URL must be https: {self.url!r}")
        allowed = {"list", "document"} | {k.value for k in PurchaseUrlKind}
        if self.kind not in allowed:
            raise ValueError(f"unknown URL kind {self.kind!r}")


@dataclass
class OtcRecord:
    state: str
    county: str
    case_no: str                                    # the source's own identifier (account, case, file no.)
    source_id: str
    source_authority: SourceAuthority
    inventory_type: InventoryType | None            # None = the source did not say / not yet classified
    retrieved_at: datetime
    parcel: str | None = None
    address: str | None = None
    legal_desc: str | None = None
    # The name the source publishes for the property (FL: owner of record
    # on the list; AL: the name in which the property was assessed when it
    # sold to the State). What it means is stated in provenance["owner_name"].
    owner_name: str | None = None
    # Tax-roll figures and coordinates when the SOURCE publishes them on the
    # row (EBR's adjudicated dataset carries assessed / market value and a
    # geolocation). Never computed; provenance names the column.
    assessed: float | None = None
    market: float | None = None
    tax_year: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    amount: float | None = None
    amount_kind: AmountKind = AmountKind.NOT_PUBLISHED
    list_url: str | None = None
    document_url: str | None = None
    purchase_url: str | None = None
    purchase_url_kind: PurchaseUrlKind | None = None
    list_as_of: date | None = None                  # the list's own date (filename/title), never retrieval
    source_published_at: datetime | None = None     # the source's own timestamp, never retrieval
    source_status_text: str | None = None           # the source's own status wording, verbatim
    document_sha256: str | None = None
    provenance: dict = field(default_factory=dict)  # per-field origin, filled by the adapter
    # Which ledger's record this is: "laft" (AVAILABLE inventory) or
    # "certificate" (LIENS & CERTIFICATES - the lien product, never the land).
    # "auction" (six-state sprint): an AUCTIONS ledger record - a parcel
    # offered at a published tax / foreclosure sale; `amount` is then the
    # published minimum / opening bid and `sale_date` the published date.
    record_source: str = "laft"
    certificate_no: str | None = None               # the certificate / CP number, as published
    interest_rate: float | None = None              # the certificate's rate, as published (percent)
    sale_date: date | None = None                   # AUCTIONS only: the sale date as the source publishes it
    acreage: float | None = None                    # as the source publishes it on the row, never computed
    land_use: str | None = None                     # the source's own property type / class wording
    taxable_value: float | None = None              # as published on the row (e.g. Michigan's taxable value)
    # The source lists the row in a table of PAST sales (e.g. Green WI's "Previous Sales"):
    # the listing is over (status closed). Says nothing about who bought it or for how much.
    listing_closed: bool = False
    land_value: float | None = None                 # as published on the row (e.g. York SC's land market value)
    improvement_value: float | None = None          # as published on the row (building / improvement value)
    # A PUBLISHED result (six-state sprint): only when the source's own row
    # carries it (e.g. a county's "Previous Sales" table with a sale price).
    # Never inferred from absence. A row with a result is closed.
    result_amount: float | None = None
    result_date: date | None = None
    # The source's own sold / not-sold flag, when it publishes one (Eaton
    # County's 'Has Been Sold'): "sold" closes the auction row; the source's
    # wording is kept in inventory_status_raw. Never inferred.
    published_outcome: str | None = None
    # Five-state sprint: a CERTIFICATE's own sale / purchase date, as the
    # source publishes it (properties.issued_date).
    issued_date: date | None = None

    def validate(self) -> list[str]:
        problems: list[str] = []
        # A state is acceptable only if harvesters/governance/states.py
        # registers it (FL and TX in production; tests register a temporary
        # one). No env override, no pass-through of an unknown code.
        problems.extend(states.state_problems(self.state))
        if self.record_source not in ("laft", "certificate", "auction"):
            problems.append("record_source must be 'laft' (AVAILABLE), 'certificate' (LIENS & CERTIFICATES) or 'auction' (AUCTIONS)")
        if self.record_source in ("certificate", "auction") and self.inventory_type is not None:
            problems.append(f"a {self.record_source} record carries no inventory type (that vocabulary describes AVAILABLE land)")
        if self.published_outcome not in (None, "sold"):
            problems.append("published_outcome is 'sold' or None")
        if self.published_outcome and self.record_source != "auction":
            problems.append("a published outcome belongs to an auction record")
        if self.result_amount is not None and self.result_amount < 0:
            problems.append("result_amount cannot be negative")
        if (self.result_amount is not None or self.result_date is not None) and self.record_source != "auction":
            problems.append("a published sale result belongs to an auction record")
        if self.listing_closed and self.record_source != "auction":
            problems.append("a past-sale listing belongs to an auction record")
        if self.sale_date is not None and self.record_source != "auction":
            problems.append("sale_date belongs to an auction record")
        if self.issued_date is not None and self.record_source != "certificate":
            problems.append("issued_date belongs to a certificate record")
        if self.record_source == "auction" and self.amount is not None and self.amount_kind not in (AmountKind.OPENING_BID, AmountKind.MINIMUM_PURCHASE_AMOUNT, AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED):
            problems.append("an auction amount is the published opening / minimum bid (or of unspecified kind)")
        for name in ("acreage", "taxable_value", "land_value", "improvement_value"):
            value = getattr(self, name)
            if value is not None and value < 0:
                problems.append(f"{name} cannot be negative")
        if self.interest_rate is not None and self.interest_rate < 0:
            problems.append("interest_rate cannot be negative")
        if not self.county or not self.case_no or not self.source_id:
            problems.append("county, case_no and source_id are required")
        if not isinstance(self.source_authority, SourceAuthority):
            problems.append("source_authority must be a SourceAuthority")
        if self.inventory_type is not None and not isinstance(self.inventory_type, InventoryType):
            problems.append("inventory_type must be an InventoryType or None")
        if not isinstance(self.amount_kind, AmountKind):
            problems.append("amount_kind must be an AmountKind")
        if self.amount is None and self.amount_kind not in AMOUNTLESS_KINDS:
            problems.append("an absent amount must be NOT_PUBLISHED or QUOTED_ON_APPLICATION")
        if self.amount is not None and self.amount_kind in AMOUNTLESS_KINDS:
            problems.append(f"a present amount cannot be {self.amount_kind.value}")
        if self.amount is not None and self.amount < 0:
            problems.append("amount cannot be negative")
        for name in ("assessed", "market"):
            value = getattr(self, name)
            if value is not None and value < 0:
                problems.append(f"{name} cannot be negative")
        if (self.latitude is None) != (self.longitude is None):
            problems.append("latitude and longitude go together")
        if self.latitude is not None and not (-90 <= self.latitude <= 90 and -180 <= self.longitude <= 180):
            problems.append("coordinates out of range")
        if (self.purchase_url is None) != (self.purchase_url_kind is None):
            problems.append("purchase_url and purchase_url_kind go together")
        if self.purchase_url and self.purchase_url == self.list_url:
            problems.append("the list page is not a purchase URL")
        for name in ("list_url", "document_url", "purchase_url"):
            value = getattr(self, name)
            if value and not value.startswith("https://"):
                problems.append(f"{name} must be https")
        if self.list_as_of is not None and self.list_as_of == self.retrieved_at.date() and not self.provenance.get("list_as_of"):
            problems.append("list_as_of equals the retrieval date with no provenance - never stamp retrieval time as publication")
        return problems

    def to_properties_row(self) -> dict:
        """The migration-017 row shape. `bid` is the legacy NOT NULL mirror
        (0 only when nothing was published - the sentinel the FL syncs have
        always written); purchase_amount / purchase_amount_kind carry the
        honest value. url_auction/url_auction_kind = the list page as a
        'county' link (migration 013's vocabulary), never the purchase URL."""
        problems = self.validate()
        # Fail closed on vocabulary public.properties cannot store yet: the
        # 017 check constraints would reject the row, and the alternative -
        # relabelling to an FL/TX value - is exactly the mislabelling the
        # framework exists to prevent.
        if self.inventory_type is not None and self.inventory_type.value not in DB_SUPPORTED_INVENTORY_TYPES:
            problems.append(f"inventory_type {self.inventory_type.value} is not storable in public.properties until a migration widens the check constraint")
        if self.amount_kind.value not in DB_SUPPORTED_AMOUNT_KINDS:
            problems.append(f"amount_kind {self.amount_kind.value} is not storable in public.properties until a migration widens the check constraint")
        if problems:
            raise ValueError("; ".join(problems))
        amount = to_cents(self.amount)        # one rounded figure for bid / purchase_amount / min_bid
        row = {
            "state": self.state,
            "source": self.record_source,
            "county": self.county,
            "case_no": self.case_no,
            "parcel": self.parcel,
            "address": self.address or (f"Parcel {self.parcel}" if self.parcel else f"Case {self.case_no}"),
            "legal_desc": self.legal_desc,
            "bid": amount if amount is not None else 0,
            "purchase_amount": amount,
            "purchase_amount_kind": self.amount_kind.value,
            "inventory_type": self.inventory_type.value if self.inventory_type else None,
            "source_authority": self.source_authority.value,
            "source_id": self.source_id,
            "list_url": self.list_url,
            "document_url": self.document_url,
            "purchase_url": self.purchase_url,
            "purchase_url_kind": self.purchase_url_kind.value if self.purchase_url_kind else None,
            "url_auction": self.list_url,
            "url_auction_kind": "county" if self.list_url else None,
            "list_as_of": self.list_as_of.isoformat() if self.list_as_of else None,
            "source_published_at": self.source_published_at.isoformat() if self.source_published_at else None,
            "tx_sale_status": self.source_status_text if self.state == "TX" else None,
            "source_document_sha256": self.document_sha256,
            "status": "active",
            "otc_provenance": {
                "source_id": self.source_id,
                "retrieved_at": self.retrieved_at.isoformat(),
                "list_url": self.list_url,
                "document_url": self.document_url,
                **self.provenance,
            },
        }
        # Only when the source published one: an absent key never writes
        # NULL over a value another step carried.
        for name in ("owner_name", "assessed", "market", "tax_year", "latitude", "longitude", "certificate_no", "interest_rate",
                     "acreage", "land_use", "taxable_value", "land_value", "improvement_value"):
            value = getattr(self, name)
            if value is not None:
                row[name] = to_cents(value) if name in CURRENCY_VALUE_FIELDS else value
        if self.issued_date is not None:
            row["issued_date"] = self.issued_date.isoformat()
        if self.published_outcome == "sold" or self.listing_closed:
            row["status"] = "closed"
        if self.result_amount is not None or self.result_date is not None:
            row["status"] = "closed"
            if self.result_amount is not None:
                row["result_amount"] = to_cents(self.result_amount)
            if self.result_date is not None:
                row["result_date"] = self.result_date.isoformat()
        if self.record_source == "auction":
            # AUCTIONS: the published minimum / opening bid is the auction's
            # bid (FL auction rows' own columns); no AVAILABLE purchase fields.
            row["ledger_type"] = "auctions"
            row.pop("inventory_type", None)
            if self.amount is not None and self.amount_kind in (AmountKind.OPENING_BID, AmountKind.MINIMUM_PURCHASE_AMOUNT):
                # The source calls it an opening / minimum bid: the auction's own column.
                row["min_bid"] = amount
                row.pop("purchase_amount", None)
                row.pop("purchase_amount_kind", None)
            elif self.amount is None:
                row.pop("purchase_amount", None)
                row.pop("purchase_amount_kind", None)
            else:
                # An amount of UNSPECIFIED kind (e.g. a list's bare "Total") is never
                # called a minimum bid - it keeps purchase_amount + purchase_amount_kind
                # so the frontend labels it as the source published it. min_bid is sent
                # as NULL explicitly so an upsert clears any earlier value.
                row["min_bid"] = None
            if self.sale_date is not None:
                row["sale_date"] = self.sale_date.isoformat()
            if self.source_status_text:
                row["inventory_status_raw"] = self.source_status_text
        elif self.record_source == "laft" and self.source_status_text:
            # AVAILABLE: the source's own program / status wording (a land
            # bank's "Side Lot For Sale", "Own It Now"), verbatim - never mapped
            # to a lifecycle status here.
            row["inventory_status_raw"] = self.source_status_text
        return row

    def to_harvest_row(self) -> dict:
        """The row shape the FL harvesters write to out/harvest_*.json and
        scripts/laft_lifecycle.py reads (identity = county + case_no;
        bid/bid_kind; url_auction = the list page; purchase_url/kind as
        published; provenance carried). An absent value is absent."""
        row = {
            "state": self.state, "source": self.record_source, "county": self.county, "case_no": self.case_no,
            "certificate_no": self.certificate_no, "interest_rate": self.interest_rate,
            "parcel": self.parcel, "owner_name": self.owner_name, "address": self.address, "legal_desc": self.legal_desc,
            "assessed": to_cents(self.assessed), "market": to_cents(self.market), "tax_year": self.tax_year,
            "latitude": self.latitude, "longitude": self.longitude,
            "bid": "" if self.amount is None else to_cents(self.amount), "bid_kind": self.amount_kind.value,
            "url_auction": self.list_url, "purchase_url": self.purchase_url,
            "purchase_url_kind": self.purchase_url_kind.value if self.purchase_url_kind else None,
            "inventory_type": self.inventory_type.value if self.inventory_type else None,
            "source_id": self.source_id, "source_authority": self.source_authority.value,
            "list_as_of": self.list_as_of.isoformat() if self.list_as_of else None,
            "source_status_text": self.source_status_text, "otc_provenance": dict(self.provenance),
            "sale_date": self.sale_date.isoformat() if self.sale_date else None,
            "acreage": self.acreage, "land_use": self.land_use, "taxable_value": to_cents(self.taxable_value),
            "land_value": to_cents(self.land_value), "improvement_value": to_cents(self.improvement_value),
        }
        return {k: v for k, v in row.items() if v is not None}

    def as_dict(self) -> dict:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, Enum):
                d[k] = v.value
            elif isinstance(v, (datetime, date)):
                d[k] = v.isoformat()
        return d
