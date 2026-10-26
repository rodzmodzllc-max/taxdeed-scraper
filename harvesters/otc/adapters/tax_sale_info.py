"""Tax-Sale.info (Michigan public land auctions) - catalogs of the county
foreclosure auctions and the counties' surplus (unsold) property offers.

New-sources sprint, 2026-10-26 (owner decision: every property, every
source; terms risk accepted; INTERIM permission; UNREVIEWED). Structure read
live 2026-10-26, no login, no CAPTCHA:

* ``/auctions`` - "2026 UPCOMING AUCTIONS" block, then "PAST AUCTIONS FROM
  THIS SEASON". Each auction entry carries its date ("October 30, 2026") and
  a "Ready to Browse:" list of per-county catalog links
  ``/listings/catalog/<id>`` whose text is the county ("Saginaw",
  "Lapeer DNR", "Bay Re-Offer"; "Saint Clair" = St. Clair County).
* ``/surplus`` - "SURPLUS PROPERTIES ... properties that have gone through
  the auction process already and failed to sell ... sold on a first come
  first serve basis"; links ``/listings/catalog/<id>`` titled
  "<County> Surplus <year>".
* ``/catalog/getCsv/id/<id>`` - the catalog's own "Catalog Spreadsheet"
  (text/csv): Lot Number, Minimum Bid, Current Taxes, Parcel Id, County,
  Address, Local Unit, Section, Township, Range, SEV, Legal Description, CIS,
  Comment 2, Latitude, Longitude, Alt Latitude, Alt Longitude. Longitude is
  written with a hemisphere letter ("W84.06").

Ledgers: an UPCOMING auction catalog is an AUCTIONS record (sale date = the
auction entry's own date; amount = the published Minimum Bid, an opening
bid). A surplus catalog is AVAILABLE (offered after failing to sell). Past
auction catalogs are never read (a past listing says nothing about who
bought what). Comment / CIS free text is never mapped.

The adapter does not fetch: callers inject ``fetch_text``.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable
from urllib.parse import urljoin

from ..model import AmountKind, InventoryType, OtcRecord, SourceAuthority

SITE = "https://www.tax-sale.info"
AUCTIONS_URL = SITE + "/auctions"
SURPLUS_URL = SITE + "/surplus"
CSV_URL = SITE + "/catalog/getCsv/id/{id}"
CATALOG_URL = SITE + "/listings/catalog/{id}"
HEADER = ("Lot Number", "Minimum Bid", "Parcel Id", "County", "Address", "Legal Description", "Latitude", "Longitude")

# Catalog link text -> the county's own name (mi-counties.svg).
NAME_FIX = {"Saint Clair": "St. Clair", "Saint Joseph": "St. Joseph"}
# Michigan counties Tax-Sale.info listed in its 2026 season (/auctions read 2026-10-26).
SEASON_COUNTIES = (
    "Alcona", "Alger", "Allegan", "Alpena", "Antrim", "Arenac", "Baraga", "Barry", "Bay", "Benzie", "Berrien", "Branch",
    "Calhoun", "Cass", "Charlevoix", "Cheboygan", "Chippewa", "Clare", "Clinton", "Crawford", "Delta", "Dickinson",
    "Emmet", "Genesee", "Gladwin", "Gogebic", "Grand Traverse", "Gratiot", "Hillsdale", "Houghton", "Huron", "Ionia",
    "Iosco", "Iron", "Isabella", "Jackson", "Kalamazoo", "Kalkaska", "Kent", "Keweenaw", "Lake", "Lapeer", "Leelanau",
    "Livingston", "Luce", "Mackinac", "Manistee", "Marquette", "Mason", "Mecosta", "Menominee", "Missaukee", "Monroe",
    "Montcalm", "Montmorency", "Muskegon", "Oakland", "Oceana", "Ogemaw", "Ontonagon", "Osceola", "Oscoda", "Otsego",
    "Ottawa", "Presque Isle", "Roscommon", "Saginaw", "Sanilac", "Schoolcraft", "Shiawassee", "St. Clair", "St. Joseph",
    "Tuscola", "Van Buren", "Wexford")

# Counties whose surplus catalog Tax-Sale.info listed on /surplus (read 2026-10-26).
# A surplus catalog for another county is counted by the harvester, never read
# under a county it does not name; add the county here to collect it.
SURPLUS_COUNTIES = ("Arenac", "Bay", "Jackson", "Monroe", "Montcalm", "Oceana", "Otsego", "Presque Isle")

_DATE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})")


@dataclass(frozen=True)
class TaxSaleInfoConfig:
    source_id: str
    state: str
    county: str
    kind: str                         # "auction" (upcoming catalogs) | "surplus"
    list_url: str
    source_authority: SourceAuthority = SourceAuthority.VENDOR_AUCTION
    inventory_type: InventoryType | None = None
    amount_kind: AmountKind = AmountKind.OPENING_BID
    columns_verified: bool = False
    notes: str = ""

    @property
    def record_source(self) -> str:
        return "auction" if self.kind == "auction" else "laft"


@dataclass
class Catalog:
    catalog_id: str
    county: str
    label: str
    sale_date: date | None = None


@dataclass
class TsiResult:
    outcome: str                      # COMPLETE | EMPTY | FAILED
    records: list[OtcRecord] = field(default_factory=list)
    error_category: str | None = None
    error_detail: str | None = None
    catalogs: int = 0
    rows_read: int = 0
    rejected: int = 0


def county_of(label: str) -> str:
    """'Lapeer DNR' / 'Bay Re-Offer' / 'Saint Clair' / 'Otsego Surplus 2026' -> the county's own name."""
    name = re.sub(r"\s+(DNR|Re-Offer|Surplus\s+\d{4})$", "", label.strip(), flags=re.I).strip()
    name = re.sub(r"\s+(DNR|Re-Offer)$", "", name, flags=re.I).strip()
    return NAME_FIX.get(name, name)


def upcoming_catalogs(html: str) -> list[Catalog]:
    """Catalogs of the UPCOMING block only (between '2026 UPCOMING AUCTIONS' and
    'PAST AUCTIONS'). Raises ValueError when the block is missing (format change)."""
    from bs4 import BeautifulSoup  # noqa: PLC0415
    i, j = html.find("UPCOMING AUCTIONS"), html.find("PAST AUCTIONS")
    if i < 0 or j < 0 or j < i:
        raise ValueError("no UPCOMING / PAST AUCTIONS block")
    soup = BeautifulSoup(html[i:j], "html.parser")
    out: list[Catalog] = []
    for entry in soup.select("div.entry"):
        meta = entry.select_one(".entry-meta")
        m = _DATE.search(meta.get_text(" ", strip=True)) if meta else None
        when = datetime.strptime(" ".join(m.groups()), "%B %d %Y").date() if m else None
        for a in entry.select('a[href^="/listings/catalog/"]'):
            cid = a["href"].rstrip("/").rsplit("/", 1)[-1]
            if cid.isdigit():
                out.append(Catalog(cid, county_of(a.get_text(strip=True)), a.get_text(strip=True), when))
    return out


def surplus_catalogs(html: str) -> list[Catalog]:
    """Surplus catalog links ('<County> Surplus <year>'). Raises ValueError when
    the page carries no SURPLUS PROPERTIES heading (format change)."""
    from bs4 import BeautifulSoup  # noqa: PLC0415
    if "SURPLUS PROPERTIES" not in html:
        raise ValueError("no SURPLUS PROPERTIES heading")
    out, seen = [], set()
    for a in BeautifulSoup(html, "html.parser").select('a[href^="/listings/catalog/"]'):
        text = a.get_text(strip=True)
        cid = a["href"].rstrip("/").rsplit("/", 1)[-1]
        if cid.isdigit() and re.search(r"\bSurplus\s+\d{4}$", text) and cid not in seen:
            seen.add(cid)
            out.append(Catalog(cid, county_of(text), text))
    return out


def _num(v: str | None) -> float | None:
    s = re.sub(r"[^0-9.\-]", "", v or "")
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def _coord(v: str | None) -> float | None:
    """'44.1070' / 'W84.0635' / 'N44.1' -> signed degrees (W / S negative)."""
    s = (v or "").strip().upper()
    if not s:
        return None
    sign = -1.0 if s[0] in "WS" else 1.0
    n = _num(s.lstrip("NSEW"))
    return None if n is None else sign * abs(n)


def parse_catalog(text: str, cfg: TaxSaleInfoConfig, cat: Catalog, *, retrieved_at: datetime) -> tuple[list[OtcRecord], int]:
    """One catalog CSV -> records (and the rejected-row count). A file
    without the catalog header raises ValueError (format change)."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or any(h not in reader.fieldnames for h in HEADER):
        raise ValueError("catalog CSV without the expected header")
    out, rejected = [], 0
    for row in reader:
        pid = re.sub(r"\s+", " ", (row.get("Parcel Id") or "")).strip()
        if not pid or not re.search(r"\d", pid):
            rejected += 1
            continue
        amount = _num(row.get("Minimum Bid"))
        lat, lng = _coord(row.get("Latitude")), _coord(row.get("Longitude"))
        coords = {"latitude": lat, "longitude": lng} if (lat is not None and lng is not None and 41 < lat < 49
                                                         and -91 < lng < -82) else {}
        prov = {"adapter": "tax_sale_info", "catalog": CATALOG_URL.format(id=cat.catalog_id),
                "catalog_label": cat.label, "lot_number": (row.get("Lot Number") or "").strip(),
                "amount": "column 'Minimum Bid' as published" if amount is not None else "no amount on the row",
                "list_as_of": "not stated by the catalog - never the read time"}
        if coords:
            prov["coordinates"] = "the catalog's own Latitude / Longitude for the lot"
        if cat.sale_date:
            prov["sale_date"] = "the auction entry's own date on /auctions"
        sev = _num(row.get("SEV"))
        out.append(OtcRecord(
            state=cfg.state, county=cfg.county, case_no=pid, source_id=cfg.source_id,
            source_authority=cfg.source_authority, inventory_type=cfg.inventory_type, retrieved_at=retrieved_at,
            parcel=pid, address=re.sub(r"\s+", " ", row.get("Address") or "").strip() or None,
            legal_desc=re.sub(r"\s+", " ", row.get("Legal Description") or "").strip() or None,
            assessed=sev if sev and sev > 0 else None,
            amount=amount, amount_kind=cfg.amount_kind if amount is not None else AmountKind.NOT_PUBLISHED,
            list_url=CATALOG_URL.format(id=cat.catalog_id), document_url=CSV_URL.format(id=cat.catalog_id),
            provenance=prov, record_source=cfg.record_source,
            sale_date=cat.sale_date if cfg.record_source == "auction" else None,
            **coords,
        ))
    return out, rejected


_PAGE_CACHE: dict[tuple[int, str], str] = {}


def _page(fetch_text: Callable[[str], str], url: str) -> str:
    key = (id(fetch_text), url)
    if key not in _PAGE_CACHE:
        _PAGE_CACHE[key] = fetch_text(url)
    return _PAGE_CACHE[key]


def fetch_county(cfg: TaxSaleInfoConfig, fetch_text: Callable[[str], str], *, retrieved_at: datetime) -> TsiResult:
    """Read this county's catalogs (upcoming auctions or surplus). The index
    page is read once per run and shared by every county (cached per fetcher).
    COMPLETE = rows read; EMPTY = the index lists no catalog for the county
    (or only empty catalogs); FAILED = transport / format failure - nothing
    read is trusted."""
    try:
        html = _page(fetch_text, AUCTIONS_URL if cfg.kind == "auction" else SURPLUS_URL)
        cats = upcoming_catalogs(html) if cfg.kind == "auction" else surplus_catalogs(html)
    except ValueError as exc:
        return TsiResult("FAILED", error_category="PARSE_FORMAT_CHANGE", error_detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - transport
        return TsiResult("FAILED", error_category="TRANSPORT_CONNECTION", error_detail=type(exc).__name__)
    mine = [c for c in cats if c.county == cfg.county]
    recs, rejected, read = [], 0, 0
    seen: set[str] = set()
    for cat in mine:
        try:
            got, rej = parse_catalog(fetch_text(CSV_URL.format(id=cat.catalog_id)), cfg, cat, retrieved_at=retrieved_at)
        except ValueError as exc:
            return TsiResult("FAILED", error_category="PARSE_FORMAT_CHANGE", error_detail=f"catalog {cat.catalog_id}: {exc}")
        except Exception as exc:  # noqa: BLE001
            return TsiResult("FAILED", error_category="TRANSPORT_CONNECTION", error_detail=type(exc).__name__)
        read += len(got) + rej
        rejected += rej
        for r in got:
            if r.case_no not in seen:      # a lot repeated in a re-offer catalog keeps its first listing
                seen.add(r.case_no)
                recs.append(r)
    res = TsiResult("COMPLETE" if recs else "EMPTY", recs, catalogs=len(mine), rows_read=read, rejected=rejected)
    return res
