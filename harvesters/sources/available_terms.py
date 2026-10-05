"""Source-aware AVAILABLE financial terms (2026-10-05).

One row per (state, source_id[, county][, status_raw]) in
data/available_financial_terms.csv says what the source's own figure IS and
what the source establishes about acquiring the property: the price basis,
what the listed figure already includes, what is added on top (as named
items - never a formula), the official total and how it is obtained, and
any application cost or deposit (always separate, never added to a price).

Nothing here is invented: every row quotes the source (or the statute /
document it rests on) and names the evidence. A source with no row gets the
kind-based wording only - no additions, no calculation.

public/available-terms.json is generated from the CSV by
scripts/build_available_terms.py and read by app.js (termsFor()).
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "data" / "available_financial_terms.csv"
REGISTRY = ROOT / "data" / "county_source_registry.csv"

COLUMNS = ("state", "source_id", "county", "status_raw", "basis", "figure_label", "figure_note", "program_price",
           "program_price_note", "additions", "included_in_figure", "official_total", "application_costs",
           "application_costs_in_price", "deposit", "deposit_in_price", "quote", "evidence", "observed_on")

# What the source's figure / process is. Customer labels live in app.js
# (AVAILABLE_BASIS_LABELS, pinned equal by a test).
BASES = {
    "OFFICIAL_PRICE": "the source publishes the current purchase price",
    "PROGRAM_PRICE": "a price set by the owner's published program, dated",
    "OFFICIAL_TOTAL_DUE": "the source publishes the current amount due",
    "OPENING_BID_PLUS_ADDITIONS": "the listed figure is a starting amount; named items are added by statute / the source",
    "BASE_PRICE_PLUS_ADDITIONS": "the listed figure is a base price; named items are added by the source",
    "ESTIMATE": "the source's own estimate",
    "MINIMUM_BID": "a minimum bid - the buyer bids at or above it",
    "BID_SUBMISSION": "a submitted / sealed bid the government decides",
    "OFFER_NEGOTIATED": "the buyer makes an offer; the price is negotiated",
    "PROPOSAL": "the buyer submits a proposal on the owner's application",
    "QUOTED_ON_REQUEST": "the amount is quoted by the office on request",
    "NOT_PUBLISHED": "no amount is published",
}
# Items a source may establish as ADDED on top of its figure. Anything the
# figure already contains belongs in included_in_figure, never here.
ADDITION_KEYS = ("interest", "omitted_taxes", "doc_stamps", "recording_fees")
IN_PRICE = ("", "yes", "no", "unknown")


def load(path: Path = CSV) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return [{c: (r.get(c) or "").strip() for c in COLUMNS} for r in csv.DictReader(f)]


def problems(rows: list[dict] | None = None) -> list[str]:
    rows = load() if rows is None else rows
    out = []
    reg_ids = set()
    if REGISTRY.exists():
        with open(REGISTRY, newline="", encoding="utf-8") as f:
            reg_ids = {r["source_id"] for r in csv.DictReader(f)}
    seen = set()
    for i, r in enumerate(rows, 2):
        key = (r["state"], r["source_id"], r["county"], r["status_raw"])
        where = f"row {i} {key}"
        if key in seen:
            out.append(f"{where}: duplicate key")
        seen.add(key)
        if r["basis"] not in BASES:
            out.append(f"{where}: unknown basis {r['basis']!r}")
        if reg_ids and r["source_id"] not in reg_ids:
            out.append(f"{where}: source_id not in the registry")
        adds = [a for a in r["additions"].split("|") if a]
        for a in adds:
            if a not in ADDITION_KEYS:
                out.append(f"{where}: unknown addition {a!r}")
        if adds and r["basis"] not in ("OPENING_BID_PLUS_ADDITIONS", "BASE_PRICE_PLUS_ADDITIONS"):
            out.append(f"{where}: additions are only meaningful on a starting / base figure")
        if adds and not r["included_in_figure"]:
            out.append(f"{where}: additions need included_in_figure (what is NOT added again)")
        if r["program_price"] and r["basis"] != "PROGRAM_PRICE":
            out.append(f"{where}: program_price only on PROGRAM_PRICE")
        if r["program_price"] and not re.fullmatch(r"\d+(\.\d{1,2})?", r["program_price"]):
            out.append(f"{where}: program_price must be a number")
        if r["basis"] == "PROGRAM_PRICE" and not r["program_price_note"]:
            out.append(f"{where}: PROGRAM_PRICE needs the dated policy note")
        for c in ("application_costs_in_price", "deposit_in_price"):
            if r[c] not in IN_PRICE:
                out.append(f"{where}: {c} must be one of {IN_PRICE}")
        if r["application_costs"] and not r["application_costs_in_price"]:
            out.append(f"{where}: an application cost must say whether it is in the price (yes / no / unknown)")
        if r["deposit"] and not r["deposit_in_price"]:
            out.append(f"{where}: a deposit must say whether it is in the price (yes / no / unknown)")
        # "Official" claims need the source's own wording.
        if r["basis"] in ("OFFICIAL_PRICE", "OFFICIAL_TOTAL_DUE") and not r["quote"]:
            out.append(f"{where}: an official price / total needs the source's quote")
        if not r["quote"] or not r["evidence"] or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["observed_on"]):
            out.append(f"{where}: quote, evidence and observed_on are required")
    return out


def render(rows: list[dict] | None = None) -> str:
    rows = load() if rows is None else rows
    doc = {
        "_comment": "Generated by scripts/build_available_terms.py from data/available_financial_terms.csv - do not edit.",
        "bases": BASES,
        "addition_keys": list(ADDITION_KEYS),
        "terms": [{k: v for k, v in r.items() if v} for r in rows],
    }
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
