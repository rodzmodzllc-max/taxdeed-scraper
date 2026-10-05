"""Legal / support / source-disclosure readiness, read from the repository only.

Lists exactly which owner-supplied values are still blank in config.js (the
legal pages show "[not configured]" for each), and checks the structure the
pages depend on. It never invents a value and never reads or writes anything
outside the repository.

    python scripts/legal_readiness_check.py            # report, exit 0
    python scripts/legal_readiness_check.py --strict   # exit 1 while anything is missing

Billing is out of scope for launch: billing.enabled must stay false and the
billing values (price, Stripe) are reported as "not required while billing
is off", never as blockers.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEGAL_PAGES = ("terms.html", "privacy.html", "acceptable-use.html", "source-disclaimer.html")
# config key -> what the owner must supply (the same wording legal.js shows)
OWNER_VALUES = {
    "legal.operatorName": "the operator's legal business name",
    "legal.governingLaw": "the governing law / jurisdiction",
    "legal.effectiveDate": "the effective date of the documents",
    "supportEmail": "a support / contact e-mail address (also used as legal.contactEmail when that is blank)",
}
REUSE_SENTENCE = "Publication by a government office does not, by itself, establish permission for commercial reuse"


def _config_text() -> str:
    return (REPO / "config.js").read_text(encoding="utf-8")


def config_value(text: str, dotted: str) -> str:
    """The string literal assigned to a key in config.js ('' when blank or absent)."""
    key = dotted.split(".")[-1]
    scope = text
    if "." in dotted:
        block = re.search(rf"\b{re.escape(dotted.split('.')[0])}\s*:\s*\{{(.*?)\}}", text, re.S)
        scope = block.group(1) if block else ""
    m = re.search(rf"\b{re.escape(key)}\s*:\s*\"([^\"]*)\"", scope)
    return m.group(1).strip() if m else ""


def billing_enabled(text: str) -> bool:
    block = re.search(r"\bbilling\s*:\s*\{(.*?)\}", text, re.S)
    return bool(block and re.search(r"\benabled\s*:\s*true\b", block.group(1)))


def report() -> dict:
    text = _config_text()
    missing = {k: label for k, label in OWNER_VALUES.items() if not config_value(text, k)}
    contact = config_value(text, "legal.contactEmail") or config_value(text, "supportEmail")
    if contact:
        missing.pop("supportEmail", None)
    problems = []
    for page in LEGAL_PAGES:
        for where in (REPO / "public" / page, REPO / page):
            if not where.exists():
                problems.append(f"{where.relative_to(REPO)} is missing")
                continue
            html = where.read_text(encoding="utf-8")
            if 'src="legal.js"' not in html:
                problems.append(f"{where.relative_to(REPO)} does not load legal.js")
            if 'id="legalUnconfigured"' not in html:
                problems.append(f"{where.relative_to(REPO)} has no not-configured notice")
    disclaimer = (REPO / "public" / "source-disclaimer.html").read_text(encoding="utf-8")
    if REUSE_SENTENCE not in disclaimer:
        problems.append("source-disclaimer.html does not state that government publication is not permission for reuse")
    return {"missing": missing, "problems": problems, "billing_enabled": billing_enabled(text)}


def main(argv: list[str]) -> int:
    r = report()
    print("Legal / support readiness (repository only)")
    if r["missing"]:
        print("Owner-supplied values still blank in config.js:")
        for k, label in r["missing"].items():
            print(f"  - {k}: {label}")
    else:
        print("All owner-supplied legal / support values are set.")
    print("Billing: " + ("ENABLED - out of scope for this launch, turn it off" if r["billing_enabled"]
                         else "off (price and Stripe values are not required while billing is off)"))
    for p in r["problems"]:
        print("PROBLEM: " + p)
    if r["problems"] or r["billing_enabled"]:
        return 1
    return 1 if ("--strict" in argv and r["missing"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
