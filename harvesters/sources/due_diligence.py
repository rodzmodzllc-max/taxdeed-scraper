"""Due diligence: one evidence state per checklist item, from the records.

The checklist a customer works through for a saved property. Each item's
state is decided only by what the property's records can show - never by a
field merely being populated:

- ``VERIFIED``: the record carries the value AND evidence for it (the source
  list that published it was read, a recorded provenance entry, an official
  coordinate method, a verified acquisition record, a source-published
  result).
- ``NOT_VERIFIED``: a value or process may exist, but the evidence rules do not
  support calling it verified. Examples: a value with no recorded origin,
  coordinates from a vendor listing or an address geocode, a source still
  awaiting review, a list not read recently.
- ``NOT_PUBLISHED``: the source publishes no such value for this record.
- ``NOT_APPLICABLE``: the item does not apply to this ledger. A certificate
  has no sale result; an auction has no lands-available purchase path.
- ``SOURCE_UNAVAILABLE``: the source could not be read at its last attempt.

The input is a dict of FACTS (categories, not values) that
``public/app.js`` ``diligenceFacts(p)`` derives from a row. The rule itself is
``checklist(facts)`` here and ``diligenceChecklistFromFacts(facts)`` in app.js;
``tests/python/fixtures/due_diligence_cases.json`` pins both.

The customer's own review notes per item are stored separately
(``research_items.diligence``). They never change an item's evidence state:
a customer cannot mark an item verified.
"""
from __future__ import annotations

STATES = ("VERIFIED", "NOT_VERIFIED", "NOT_PUBLISHED", "NOT_APPLICABLE", "SOURCE_UNAVAILABLE")
STATE_LABELS = {
    "VERIFIED": "Verified",
    "NOT_VERIFIED": "Not verified",
    "NOT_PUBLISHED": "Not published",
    "NOT_APPLICABLE": "Not applicable",
    "SOURCE_UNAVAILABLE": "Source unavailable",
}
GROUPS = ("identity", "acquisition", "property", "auction", "certificate", "source")
GROUP_LABELS = {
    "identity": "Property identity", "acquisition": "Acquisition", "property": "Property",
    "auction": "Auction", "certificate": "Lien / certificate", "source": "Source",
}
# (key, group, label) in display order.
ITEMS = (
    ("parcel", "identity", "Parcel / account identifier"),
    ("county", "identity", "County"),
    ("legal", "identity", "Legal description"),
    ("acq_source", "acquisition", "Official source"),
    ("acq_path", "acquisition", "Acquisition path"),
    ("acq_url", "acquisition", "Purchase / application document"),
    ("acq_amount", "acquisition", "Current amount"),
    ("acq_amount_date", "acquisition", "Amount date"),
    ("coords", "property", "Coordinates"),
    ("acreage", "property", "Acreage"),
    ("land_use", "property", "Land use"),
    ("imagery", "property", "Imagery"),
    ("values", "property", "Assessed / taxable value"),
    ("sale_date", "auction", "Sale date"),
    ("bid", "auction", "Opening / minimum bid"),
    ("auction_source", "auction", "Auction source"),
    ("result", "auction", "Sale result"),
    ("cert_number", "certificate", "Certificate number"),
    ("cert_face", "certificate", "Face / certificate amount"),
    ("cert_interest", "certificate", "Interest rate"),
    ("cert_redemption", "certificate", "Redemption / expiration"),
    ("source_record", "source", "Source record"),
    ("last_read", "source", "Last read"),
    ("provenance", "source", "Provenance"),
    ("source_health", "source", "Source health"),
)
GOOD_HEALTH = ("CURRENT", "RECENT")


def _sourced(v: str | None) -> str:
    """'sourced' -> VERIFIED, 'unsourced' -> NOT_VERIFIED (populated, origin not recorded), else NOT_PUBLISHED."""
    return {"sourced": "VERIFIED", "unsourced": "NOT_VERIFIED"}.get(v or "none", "NOT_PUBLISHED")


def checklist(f: dict) -> list[dict]:
    """[{key, group, label, state}] for every item, in display order."""
    led = f.get("ledger") or "laft"
    unavailable = f.get("source_health") == "SOURCE_UNAVAILABLE"
    read = "VERIFIED" if f.get("read_recently") else "NOT_VERIFIED"
    st: dict[str, str] = {}
    # Identity: a value the source list published counts as verified once that
    # list has actually been read; a value of unrecorded origin does not.
    st["parcel"] = "NOT_PUBLISHED" if not f.get("parcel") else ("VERIFIED" if f.get("read_ever") else "NOT_VERIFIED")
    st["county"] = "VERIFIED" if f.get("county") and f.get("read_ever") else "NOT_VERIFIED"
    st["legal"] = _sourced(f.get("legal"))
    # Acquisition (Available only).
    if led != "laft":
        for k in ("acq_source", "acq_path", "acq_url", "acq_amount", "acq_amount_date"):
            st[k] = "NOT_APPLICABLE"
    else:
        pub = f.get("source_publication")
        st["acq_source"] = "SOURCE_UNAVAILABLE" if unavailable else ("VERIFIED" if pub == "approved" else "NOT_VERIFIED")
        path = f.get("acq_path")
        st["acq_path"] = "VERIFIED" if path == "verified" else ("SOURCE_UNAVAILABLE" if path == "unavailable" else "NOT_VERIFIED")
        st["acq_url"] = ("VERIFIED" if f.get("acq_url") else "NOT_PUBLISHED") if path == "verified" else "NOT_VERIFIED"
        amt = f.get("amount") or "none"
        st["acq_amount"] = {"current": "VERIFIED", "not_current": "NOT_VERIFIED"}.get(amt, "NOT_PUBLISHED")
        ad = f.get("amount_date") or "none"
        st["acq_amount_date"] = {"current": "VERIFIED", "expired": "NOT_VERIFIED"}.get(ad, "NOT_PUBLISHED")
    # Property (not for a certificate: a lien instrument is not a parcel record).
    if led == "certificate":
        for k in ("coords", "acreage", "land_use", "imagery", "values"):
            st[k] = "NOT_APPLICABLE"
    else:
        st["coords"] = {"authoritative": "VERIFIED", "other": "NOT_VERIFIED"}.get(f.get("coords") or "none", "NOT_PUBLISHED")
        st["acreage"] = _sourced(f.get("acreage"))
        st["land_use"] = _sourced(f.get("land_use"))
        st["imagery"] = {"stored": "VERIFIED", "checked_none": "NOT_PUBLISHED"}.get(f.get("imagery") or "not_checked", "NOT_VERIFIED")
        st["values"] = _sourced(f.get("values"))
    # Auction.
    if led != "auction":
        for k in ("sale_date", "bid", "auction_source", "result"):
            st[k] = "NOT_APPLICABLE"
    else:
        st["sale_date"] = ("VERIFIED" if f.get("read_ever") else "NOT_VERIFIED") if f.get("sale_date") else "NOT_PUBLISHED"
        st["bid"] = "VERIFIED" if f.get("bid") else "NOT_PUBLISHED"
        st["auction_source"] = "VERIFIED" if f.get("auction_link") else "NOT_VERIFIED"
        st["result"] = {"verified": "VERIFIED", "future": "NOT_APPLICABLE", "not_verified": "NOT_VERIFIED"}.get(
            f.get("sale_outcome") or "none", "NOT_PUBLISHED")
    # Lien / certificate.
    if led != "certificate":
        for k in ("cert_number", "cert_face", "cert_interest", "cert_redemption"):
            st[k] = "NOT_APPLICABLE"
    else:
        st["cert_number"] = "VERIFIED" if f.get("cert_number") else "NOT_PUBLISHED"
        st["cert_face"] = "VERIFIED" if f.get("cert_face") else "NOT_PUBLISHED"
        st["cert_interest"] = "VERIFIED" if f.get("cert_interest") else "NOT_PUBLISHED"
        st["cert_redemption"] = "VERIFIED" if f.get("cert_redemption") else "NOT_PUBLISHED"
    # Source.
    st["source_record"] = "VERIFIED" if f.get("source_record") else "NOT_VERIFIED"
    st["last_read"] = "SOURCE_UNAVAILABLE" if unavailable else read
    st["provenance"] = "VERIFIED" if f.get("provenance") else "NOT_VERIFIED"
    h = f.get("source_health") or "NOT_RECORDED"
    st["source_health"] = "SOURCE_UNAVAILABLE" if h == "SOURCE_UNAVAILABLE" else ("VERIFIED" if h in GOOD_HEALTH else "NOT_VERIFIED")
    return [{"key": k, "group": g, "label": lbl, "state": st[k]} for k, g, lbl in ITEMS]


def summary(items: list[dict]) -> dict:
    out = {s: 0 for s in STATES}
    for it in items:
        out[it["state"]] += 1
    return out
