"""What each acquisition link on an AVAILABLE record actually is.

One rule for the customer's "Documents & links" list, mirrored by
``classifyAcquisitionLink()`` in ``public/app.js`` and pinned by
``tests/python/fixtures/acquisition_documents_cases.json``.

Classes:

- ``PURCHASE_LINK``: a web page where this property is bought or applied for
  online. Never a downloadable file. A PDF is never a purchase link, whatever
  kind it was stored under.
- ``FORM``: an application, bid, offer or request form, usually downloaded,
  completed and submitted offline.
- ``INSTRUCTIONS``: the office's own description of its process.
- ``DOCUMENT``: any other source document, such as a list PDF, a statement
  or a policy.
- ``SOURCE_PAGE``: the official listing page the record was read from.

A link that is not ``https://`` is not shown. A value that is not a URL is
not a link.
"""
from __future__ import annotations

import re

CLASSES = ("PURCHASE_LINK", "FORM", "INSTRUCTIONS", "DOCUMENT", "SOURCE_PAGE")
LABELS = {
    "PURCHASE_LINK": "Purchase / apply online",
    "FORM": "Form",
    "INSTRUCTIONS": "Instructions",
    "DOCUMENT": "Document",
    "SOURCE_PAGE": "Official listing page",
}
# The same document test as scripts/laft_purchase_paths.is_document_url and
# app.js isDocumentUrl(): a file to download, not a page or a checkout.
_DOCUMENT = re.compile(r"\.(?:pdf|docx?|xlsx?|rtf)(?:$|[?#/])|/DocumentCenter/View/", re.I)
FORM_KINDS = ("bid_form", "offer_form", "application_form")
INSTRUCTION_KINDS = ("purchase_instructions",)
FORM_PATH_TYPES = ("application_download",)
INSTRUCTION_PATH_TYPES = ("county_instructions",)
ONLINE_PATH_TYPES = ("direct_property_url", "application_page")
ROLES = ("purchase_url", "application_url", "path_url", "evidence_url", "list_url", "document_url")


def is_document(url) -> bool:
    return bool(url) and bool(_DOCUMENT.search(str(url)))


def classify(url, role: str, kind: str | None = None) -> str | None:
    """The class of one link, or None when it must not be shown.

    ``role`` says where the link came from (``ROLES``). ``kind`` is the
    stored ``purchase_url_kind`` for ``purchase_url``, or the path type for
    ``path_url``.
    """
    u = str(url or "").strip()
    if not u.lower().startswith("https://"):
        return None
    doc = is_document(u)
    if role == "list_url":
        return "DOCUMENT" if doc else "SOURCE_PAGE"
    if role == "document_url":
        return "DOCUMENT"
    if role == "application_url":
        return "FORM"
    if role == "evidence_url":
        return "DOCUMENT" if doc else "INSTRUCTIONS"
    if role == "purchase_url":
        if kind in FORM_KINDS:
            return "FORM"
        if kind in INSTRUCTION_KINDS:
            return "INSTRUCTIONS"
        if kind == "online_purchase":
            return "FORM" if doc else "PURCHASE_LINK"
        return "DOCUMENT" if doc else "INSTRUCTIONS"
    if role == "path_url":
        if kind in FORM_PATH_TYPES:
            return "FORM"
        if kind in INSTRUCTION_PATH_TYPES:
            return "INSTRUCTIONS"
        if kind in ONLINE_PATH_TYPES:
            return "FORM" if doc else "PURCHASE_LINK"
        return "DOCUMENT" if doc else "INSTRUCTIONS"
    return None


def documents(links: list[dict]) -> list[dict]:
    """Classify a record's links, one entry per distinct URL, first role wins.

    ``links`` is ``[{"url", "role", "kind"?}]`` in priority order.
    """
    out, seen = [], set()
    for link in links:
        cls = classify(link.get("url"), link.get("role", ""), link.get("kind"))
        u = str(link.get("url") or "").strip()
        if not cls or u in seen:
            continue
        seen.add(u)
        out.append({"url": u, "role": link.get("role"), "class": cls})
    return out
