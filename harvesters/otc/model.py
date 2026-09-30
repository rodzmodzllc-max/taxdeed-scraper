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

__all__ = ["AmountKind", "DB_SUPPORTED_AMOUNT_KINDS", "DB_SUPPORTED_INVENTORY_TYPES", "InventoryType",
           "OtcRecord", "PurchaseUrlKind", "SourceAuthority", "UrlRef"]


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


# Exactly what migration 017's purchase_amount_kind constraint allows.
DB_SUPPORTED_AMOUNT_KINDS = frozenset({
    AmountKind.MINIMUM_PURCHASE_AMOUNT.value, AmountKind.OPENING_BID.value,
    AmountKind.ORIGINAL_OPENING_BID.value, AmountKind.FIXED_PURCHASE_PRICE.value,
    AmountKind.ESTIMATED_PURCHASE_PRICE.value, AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED.value,
    AmountKind.NOT_PUBLISHED.value,
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

    def validate(self) -> list[str]:
        problems: list[str] = []
        # A state is acceptable only if harvesters/governance/states.py
        # registers it (FL and TX in production; tests register a temporary
        # one). No env override, no pass-through of an unknown code.
        problems.extend(states.state_problems(self.state))
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
        row = {
            "state": self.state,
            "source": "laft",
            "county": self.county,
            "case_no": self.case_no,
            "parcel": self.parcel,
            "address": self.address or (f"Parcel {self.parcel}" if self.parcel else f"Case {self.case_no}"),
            "legal_desc": self.legal_desc,
            "bid": self.amount if self.amount is not None else 0,
            "purchase_amount": self.amount,
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
        for name in ("owner_name", "assessed", "market", "tax_year", "latitude", "longitude"):
            value = getattr(self, name)
            if value is not None:
                row[name] = value
        return row

    def to_harvest_row(self) -> dict:
        """The row shape the FL harvesters write to out/harvest_*.json and
        scripts/laft_lifecycle.py reads (identity = county + case_no;
        bid/bid_kind; url_auction = the list page; purchase_url/kind as
        published; provenance carried). An absent value is absent."""
        row = {
            "state": self.state, "source": "laft", "county": self.county, "case_no": self.case_no,
            "parcel": self.parcel, "owner_name": self.owner_name, "address": self.address, "legal_desc": self.legal_desc,
            "assessed": self.assessed, "market": self.market, "tax_year": self.tax_year,
            "latitude": self.latitude, "longitude": self.longitude,
            "bid": "" if self.amount is None else self.amount, "bid_kind": self.amount_kind.value,
            "url_auction": self.list_url, "purchase_url": self.purchase_url,
            "purchase_url_kind": self.purchase_url_kind.value if self.purchase_url_kind else None,
            "inventory_type": self.inventory_type.value if self.inventory_type else None,
            "source_id": self.source_id, "source_authority": self.source_authority.value,
            "list_as_of": self.list_as_of.isoformat() if self.list_as_of else None,
            "source_status_text": self.source_status_text, "otc_provenance": dict(self.provenance),
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
