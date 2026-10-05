"""Temporary, value-free: why Citrus statements fail the sum check.
Prints, per statement-like docket document: each money line's LABEL (through
the document-type vocabulary; unknown words -> ~) and the amount SHAPE, plus
the parse status and the direction / order of magnitude of any mismatch."""
import re, sys, io, math, requests
sys.path.insert(0, "scripts")
import harvest_clerk_statements as h
from capture_pioneer_statements import vocab_only, DOC_VOCAB
DOC_VOCAB.update("FEE FEES CLERK CLERK'S SHERIFF ADVERTISING COLLECTOR COLLECTOR'S RECORDING DOCUMENTARY STAMP STAMPS LANDS AVAILABLE INTEREST OMITTED TOTAL DUE PURCHASER OPENING BID BALANCE AMOUNT REDEMPTION CERTIFICATE CERTIFICATES SURPLUS COST COSTS TAX TAXES DEED VALID THROUGH RECEIVED IF BY PAID LESS PLUS SUBTOTAL NET STATE COUNTY ADDITIONAL ONLINE CONVENIENCE PROCESSING TITLE SEARCH ELECTRONIC".split())
s = requests.Session(); s.headers["User-Agent"] = h.UA
base = "https://search.citrusclerk.org/TaxSmartWeb/"
g = s.get(base + "Home/GridSearchData", params={"SearchType": "Lands Available", "_search": "false", "rows": "100", "page": "1", "sidx": "", "sord": "asc"}, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30).json()
for r in g["rows"]:
    det = base + f"Home/Details?id={r['id']}"
    docs = [(hh, t) for hh, t in h._docket(s.get(det, timeout=30).text) if re.search(h.CITRUS.docket_pattern, t, re.I)]
    for href, label in docs:
        text = h._ocr_pdf(s.get(requests.compat.urljoin(det, href), timeout=60).content, 4)
        p = h.parse_statement(text, h.CITRUS)
        comps = {k: h._num(h._after(text, rx, h.MONEY)) for k, rx in h.CITRUS.labels.items()}
        tot = None
        for rx in h.CITRUS.total_labels:
            tot = h._num(h._after(text, rx, h.MONEY))
            if tot is not None: break
        diff = ""
        if tot is not None and all(v is not None for v in comps.values()):
            d = round(tot - sum(comps.values()), 2)
            diff = f"total-minus-sum sign={'+' if d > 0 else '-' if d < 0 else '0'} magnitude~1e{int(math.log10(abs(d))) if d else 0}"
        print(f"== doc {vocab_only(label)} status={p.status} missing={p.missing} {diff}")
        for line in text.splitlines():
            m = re.search(r"\$?\s*-?[\d,]+\.\d{2}", line)
            if m:
                lab = line[:m.start()]
                print(f"   {vocab_only(lab):60s} | {re.sub(r'[0-9]', '9', m.group(0).strip())}")
