"""screening-v1 rules - line-for-line mirror of public/screening.js.

See that file's header for what the screen is and is not. Every reason cites
a field the row carries and the evidence behind it; missing data is reported
as missing, never as a defect.
"""
from __future__ import annotations

import math
import re

SCREENING_VERSION = "screening-v1"

SCREENING_DEFAULTS = {
    "tinyAcres": 0.01,
    "smallAcres": 0.05,
    "lowValue": 1000,
    "bidHighRatio": 1.0,
    "bidLowRatio": 0.10,
}

CLASSIFICATIONS = (
    "PRIORITY_REVIEW", "REVIEW", "LIMITED_OPPORTUNITY", "HIGH_RISK_REVIEW", "INSUFFICIENT_DATA",
)
DEFAULT_DISCOVERY = ("PRIORITY_REVIEW", "REVIEW")
SCREENED_SOURCES = ("auction", "laft")

REASON_LABELS = {
    "POSSIBLE_RIGHT_OF_WAY": "Possible right-of-way",
    "DRAINAGE_INDICATOR": "Drainage / waste-land indicator",
    "UTILITY_INDICATOR": "Utility indicator",
    "COMMON_AREA_INDICATOR": "Common-area indicator",
    "SUBMERGED_LAND_INDICATOR": "Submerged-land indicator",
    "SUBSURFACE_RIGHTS_ONLY": "Subsurface rights only",
    "POSSIBLE_EASEMENT": "Possible easement",
    "STRIP_DESCRIPTION": "Described as a strip of land",
    "NOT_A_BUILDING_SITE": "Described as not a building site",
    "BUYER_ELIGIBILITY_RESTRICTED": "Buyer eligibility restricted",
    "TINY_PARCEL": "Tiny parcel",
    "SMALL_ACREAGE": "Small acreage",
    "LOW_JUST_VALUE": "Low county value",
    "OPENING_BID_HIGH_RELATIVE_TO_VALUE": "Bid at or above county value",
    "OPENING_BID_LOW_RELATIVE_TO_VALUE": "Bid low relative to county value",
    "PARCEL_MISSING": "Parcel number missing",
    "ACREAGE_MISSING": "Acreage missing",
    "VALUE_DATA_MISSING": "County value missing",
    "PROPERTY_CLASS_UNKNOWN": "Property class unknown",
    "INSUFFICIENT_DATA": "Insufficient data",
}

FL_DOR_FLAGS = {
    "09": ("COMMON_AREA_INDICATOR", "Residential common elements / areas"),
    "91": ("UTILITY_INDICATOR", "Utility, pipelines, canals, communication"),
    "93": ("SUBSURFACE_RIGHTS_ONLY", "Subsurface rights"),
    "94": ("POSSIBLE_RIGHT_OF_WAY", "Right-of-way, streets, roads, irrigation channel, ditch"),
    "95": ("SUBMERGED_LAND_INDICATOR", "Rivers and lakes, submerged lands"),
    "96": ("DRAINAGE_INDICATOR", "Sewage disposal, solid waste, borrow pits, drainage reservoirs, waste land, marsh, swamps"),
}
FL_DOR_VACANT = {"00", "10", "40", "70", "80", "99"}

RESTRICTED_PROGRAMS = {
    "mi_detroit_landbank_lots": {
        "Side Lot For Sale": "Detroit Land Bank side lot: sold only to the owner-occupant of the adjacent home",
    },
}
PROGRAM_CLASS = {
    "mi_detroit_landbank_lots": {
        "Neighborhood Lot For Sale": "vacant", "Side Lot For Sale": "vacant",
        "Oversized Lot For Sale": "vacant", "Marketed Lot For Sale": "vacant",
        "Marketed Structure For Sale": "improved",
    },
}

# Designation-only wording; see public/screening.js for the rationale.
# (code, pattern, lead): lead = must open the description (first 40
# characters) or stand in parentheses.
LEGAL_TEXT_FLAGS = [
    ("COMMON_AREA_INDICATOR", re.compile(r"COMMON (?:AREAS?|GROUNDS?|ELEMENTS?)\b"), False),
    ("NOT_A_BUILDING_SITE", re.compile(r"\bNOT A BUILDING SITE\b|\bNON[- ]?BUILDABLE\b|\bUNBUILDABLE\b"), False),
    ("DRAINAGE_INDICATOR", re.compile(
        r"\b(?:RETENTION|DETENTION) (?:POND|AREA|BASIN)\b"
        r"|\bDRAINAGE (?:EASEMENT|R/W|RIGHT[ -]OF[ -]WAY|SERVITUDE|AREA|TRACT|POND|RESERVE)\b"
        r"|\bDRAINAGE\s*$"), False),
    ("POSSIBLE_EASEMENT", re.compile(
        r"\b(?:DRAINAGE|UTILITY|ACCESS|INGRESS(?:/| AND )EGRESS) EASEMENT\b|\bEASEMENT (?:ONLY|AREA|PARCEL|TRACT)\b"), False),
    ("UTILITY_INDICATOR", re.compile(r"\b(?:LIFT|PUMP) STATION\b|\bWELL SITE\b|\bUTILITY (?:STRIP|PARCEL|TRACT|SITE)\b"), False),
    ("POSSIBLE_RIGHT_OF_WAY", re.compile(
        r"\bABAN(?:DONED|D)?\.? (?:RR |RAILROAD )?(?:R/W|RIGHT[ -]OF[ -]WAY)"
        r"|(?:R/W|RIGHT[ -]OF[ -]WAY) (?:ABANDONED|VACATED)\b|\bUNDEDICATED\b"), False),
    ("STRIP_DESCRIPTION", re.compile(r"\bSTRIP\b"), True),
]
NEGATORS = re.compile(r"(?:\b(?:LESS|EX|EXC|EXCEPT|EXCEPTING|SUBJ|SUBJECT|TOGETHER|WITH|PLUS|INT|INTEREST|ALSO|AND|RESERVING)\b|&)")
SEVERITY_ORDER = {"limited": 0, "risk": 1, "review": 2, "info": 3}


def _num(v):
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _text(v):
    return "" if v is None else str(v).strip()


def _round(v, d):
    # JS Math.round semantics (half away from zero for positives, toward +inf).
    f = 10 ** d
    return math.floor(v * f + 0.5) / f


def _fmt_int(v):
    return f"{int(math.floor(v + 0.5)):,}"


def _fmt_num(v):
    """JS default Number -> string for the values this module prints."""
    if float(v).is_integer():
        return str(int(v))
    return repr(float(v))


def has_parcel_id(p):
    v = _text(p.get("parcel"))
    return bool(v) and not re.match(r"^(unknown|n/?a|none|null)$", v, re.I)


def acreage_of(p):
    a = _num(p.get("acreage"))
    if a is not None and a > 0:
        return a, "acreage"
    sq = _num(p.get("lot_sqft"))
    if sq is not None and sq > 0:
        return sq / 43560, "lot_sqft"
    return None, None


def value_of(p):
    m = _num(p.get("market"))
    if m is not None and m > 0:
        return m, "market"
    a = _num(p.get("assessed"))
    if a is not None and a > 0:
        return a, "assessed"
    return None, None


def amount_of(p):
    kind = p.get("purchase_amount_kind")
    if kind in ("NOT_PUBLISHED", "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"):
        return None, None
    for col in ("purchase_amount", "min_bid", "bid"):
        v = _num(p.get(col))
        if v is not None and v > 0:
            return v, col
    return None, None


def _dor_code(p):
    if _text(p.get("state") or "FL") != "FL":
        return ""
    c = _text(p.get("dor_use_code"))
    return c.zfill(2) if re.match(r"^\d{1,2}$", c) else ""


def _fl_dor_improved(c):
    n = int(c)
    return c not in FL_DOR_VACANT and (1 <= n <= 49 or 71 <= n <= 89)


def occupancy_of(p):
    prog = PROGRAM_CLASS.get(p.get("source_id") or "")
    raw = _text(p.get("inventory_status_raw"))
    if prog and prog.get(raw):
        return prog[raw]
    if any((_num(p.get(c)) or 0) > 0 for c in ("num_buildings", "living_area", "improvement_value", "year_built")):
        return "improved"
    dor = _dor_code(p)
    if dor:
        return "vacant" if dor in FL_DOR_VACANT else ("improved" if _fl_dor_improved(dor) else "")
    lu = (_text(p.get("land_use")) + " " + _text(p.get("prop_type"))).lower()
    if re.search(r"\bvacant\b|\blot\b|\bland\b", lu):
        return "vacant"
    if re.search(r"\bbuilding\b|\bimproved\b|\bstructure\b|\bhouse\b|\bcondo\b|single family|residence", lu):
        return "improved"
    return ""


def has_property_class(p):
    if _dor_code(p):
        return True
    if _text(p.get("land_use")) or _text(p.get("prop_type")):
        return True
    prog = PROGRAM_CLASS.get(p.get("source_id") or "")
    return bool(prog and prog.get(_text(p.get("inventory_status_raw"))))


def _legal_text_reasons(p):
    legal = _text(p.get("legal_desc")).upper()
    if not legal:
        return []
    out = []
    for code, rx, lead in LEGAL_TEXT_FLAGS:
        for m in rx.finditer(legal):
            if lead and m.start() >= 40 and not (
                    legal[m.start() - 1] == "(" and legal[m.end():m.end() + 1] == ")"):
                continue
            before = legal[max(0, m.start() - 40):m.start()]
            clause = re.split(r"[.;,]", before)[-1]
            if not NEGATORS.search(clause):
                out.append((code, m.group(0)))
                break
    return out


def screen_property(p, opts=None):
    o = dict(SCREENING_DEFAULTS, **(opts or {}))
    base = {"version": SCREENING_VERSION, "geometry": "GEOMETRY_NOT_AVAILABLE", "access": "ACCESS_UNKNOWN"}
    if not p or p.get("source") not in SCREENED_SOURCES:
        return dict(base, classification="NOT_SCREENED", promoted=True, reasons=[], metrics={})
    reasons = []

    def add(code, severity, evidence):
        if not any(r["code"] == code and r["severity"] == severity for r in reasons):
            reasons.append({"code": code, "severity": severity, "evidence": evidence})

    acres, acre_basis = acreage_of(p)
    value, value_basis = value_of(p)
    amount, amount_basis = amount_of(p)
    occupancy = occupancy_of(p)
    dor = _dor_code(p)

    if dor and dor in FL_DOR_FLAGS:
        add(FL_DOR_FLAGS[dor][0], "limited", f"FL DOR use code {dor} ({FL_DOR_FLAGS[dor][1]})")
    restricted = RESTRICTED_PROGRAMS.get(p.get("source_id") or "", {}).get(_text(p.get("inventory_status_raw")))
    if restricted:
        add("BUYER_ELIGIBILITY_RESTRICTED", "limited", restricted)

    if acres is not None and occupancy != "improved":
        acres_txt = f"{_fmt_num(_round(acres, 4))} ac" + (" (from lot sq ft)" if acre_basis == "lot_sqft" else "")
        if acres < o["tinyAcres"]:
            vacant = occupancy == "vacant"
            add("TINY_PARCEL", "limited" if vacant else "review",
                f"{acres_txt}, under {_fmt_num(o['tinyAcres'])} ac"
                + ("; vacant land per source" if vacant else "; vacancy not established"))
        elif acres < o["smallAcres"]:
            add("SMALL_ACREAGE", "review", f"{acres_txt}, under {_fmt_num(o['smallAcres'])} ac (provisional threshold)")

    for code, term in _legal_text_reasons(p):
        add(code, "risk", f'Legal description contains "{term}"')

    if value is not None and value < o["lowValue"]:
        add("LOW_JUST_VALUE", "review",
            f"County value ${_fmt_int(value)} under ${_fmt_int(o['lowValue'])} (provisional threshold)")
    metrics = {
        "acres": None if acres is None else _round(acres, 4), "acresBasis": acre_basis,
        "value": value, "valueBasis": value_basis, "amount": amount, "amountBasis": amount_basis,
        "bidToValue": None, "valueToBid": None, "valueSpread": None, "pricePerAcre": None, "valuePerAcre": None,
    }
    if value is not None and amount is not None:
        metrics["bidToValue"] = _round(amount / value, 4)
        metrics["valueToBid"] = _round(value / amount, 2)
        metrics["valueSpread"] = _round(value - amount, 2)
        if amount / value >= o["bidHighRatio"]:
            add("OPENING_BID_HIGH_RELATIVE_TO_VALUE", "review",
                f"Published amount is {_fmt_num(_round(amount / value, 2))}x the county value")
        elif amount / value < o["bidLowRatio"]:
            add("OPENING_BID_LOW_RELATIVE_TO_VALUE", "info",
                f"Published amount is {_fmt_num(_round(amount / value * 100, 1))}% of the county value")
    if acres is not None and acres > 0:
        if amount is not None:
            metrics["pricePerAcre"] = _round(amount / acres, 2)
        if value is not None:
            metrics["valuePerAcre"] = _round(value / acres, 2)

    parcel, cls = has_parcel_id(p), has_property_class(p)
    if not parcel:
        add("PARCEL_MISSING", "review", "No parcel number in the source row")
    if acres is None:
        add("ACREAGE_MISSING", "review", "No acreage or lot size on file")
    if value is None:
        add("VALUE_DATA_MISSING", "review", "No county / tax-roll value on file")
    if not cls:
        add("PROPERTY_CLASS_UNKNOWN", "review", "No use code, land use or property type on file")

    sev = {r["severity"] for r in reasons}
    if "limited" in sev:
        classification = "LIMITED_OPPORTUNITY"
    elif "risk" in sev:
        classification = "HIGH_RISK_REVIEW"
    elif not parcel or (value is None and acres is None and not cls):
        classification = "INSUFFICIENT_DATA"
        add("INSUFFICIENT_DATA", "review",
            "No parcel number to research the property by" if not parcel else "No value, size or property class on file")
    elif "review" in sev:
        classification = "REVIEW"
    else:
        classification = "PRIORITY_REVIEW"
    return dict(base, classification=classification, promoted=classification in DEFAULT_DISCOVERY,
                reasons=reasons, metrics=metrics)


def key_reasons(result):
    rs = [r for r in result.get("reasons", []) if r["severity"] != "info"]
    return sorted(rs, key=lambda r: SEVERITY_ORDER[r["severity"]])


BUY_BOX_DEFAULTS = {
    "minAcres": None, "maxAcres": None, "minValue": None, "maxAmount": None, "maxBidToValue": None,
    "requireParcel": False, "requireAcreage": False, "requireValue": False, "requireClass": False,
}


def passes_buy_box(p, result, box=None):
    b = dict(BUY_BOX_DEFAULTS, **(box or {}))
    m = result.get("metrics") or {}

    def has(k):
        return m.get(k) is not None

    if b["minAcres"] is not None and not (has("acres") and m["acres"] >= b["minAcres"]):
        return False
    if b["maxAcres"] is not None and not (has("acres") and m["acres"] <= b["maxAcres"]):
        return False
    if b["minValue"] is not None and not (has("value") and m["value"] >= b["minValue"]):
        return False
    if b["maxAmount"] is not None and not (has("amount") and m["amount"] <= b["maxAmount"]):
        return False
    if b["maxBidToValue"] is not None and not (has("bidToValue") and m["bidToValue"] <= b["maxBidToValue"]):
        return False
    if b["requireParcel"] and not has_parcel_id(p):
        return False
    if b["requireAcreage"] and not has("acres"):
        return False
    if b["requireValue"] and not has("value"):
        return False
    if b["requireClass"] and not has_property_class(p):
        return False
    return True
