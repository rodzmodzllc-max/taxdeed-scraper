"""A source's own per-property page (acquisition-path sprint, 2026-10-25).

The owner's rule: the best acquisition path is a link that opens THIS
property on the source's official site - the page carrying the source's
own "Apply" / "Purchase" action - with no extra steps. Such a link is
taken only when:

  * the source publishes the link pattern itself (its own page markup or its
    own portal code builds `<page>?parcelId=<id>` / `/property/<id>`), and
  * the identifier in it is a value the source publishes on the row (a field
    of the feed, never a slug derived from an address), and
  * the pattern was followed live, anonymously, for at least three sampled
    offered properties, each page showing that property and the source's
    own purchase / apply action (`verification` records how).

Nothing here guesses: an identifier that does not match `id_pattern` gets no
link, and a source whose own list says a parcel is not on its page (the
`listed` set) gets no link. A row without a link is still a row - this
module never withholds anything; the source's listing page stays its
acquisition path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

from ..model import PurchaseUrlKind

__all__ = ["PropertyPage"]

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class PropertyPage:
    template: str                 # https URL with exactly one "{id}" placeholder
    kind: PurchaseUrlKind         # a property-action kind (online_purchase / offer_form / bid_form)
    id_pattern: str               # the identifier must match in full before it is placed in the URL
    verified_on: str              # YYYY-MM-DD: the date the pattern was followed live
    verification: str             # how it was verified (value-free)
    pattern_source: str           # where the SOURCE publishes the pattern
    action_label: str = ""        # the source's own button text on the page

    def __post_init__(self) -> None:
        if not self.template.startswith("https://") or self.template.count("{id}") != 1:
            raise ValueError("template must be https with exactly one {id} placeholder")
        if self.kind not in (PurchaseUrlKind.ONLINE_PURCHASE, PurchaseUrlKind.OFFER_FORM, PurchaseUrlKind.BID_FORM):
            raise ValueError("a per-property page is a property-action kind")
        if not _DATE.match(self.verified_on) or not self.verification or not self.pattern_source:
            raise ValueError("a per-property page needs verified_on, verification and pattern_source")

    def url_for(self, identifier: str | None) -> str | None:
        """The property's own page, or None when the identifier is not the
        source's published identifier shape."""
        ident = (identifier or "").strip()
        if not ident or not re.fullmatch(self.id_pattern, ident):
            return None
        return self.template.replace("{id}", quote(ident, safe=""))

    def basis(self) -> str:
        """The purchase_url_basis text the purchase-path engine reads (its
        'verified YYYY-MM-DD' gives the path's observed date)."""
        action = f" ('{self.action_label}')" if self.action_label else ""
        return (f"the source's own per-property page{action}, pattern published by the source ({self.pattern_source}); "
                f"verified {self.verified_on}: {self.verification}")
