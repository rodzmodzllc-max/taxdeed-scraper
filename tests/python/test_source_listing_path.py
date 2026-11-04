"""Owner's rule (2026-10-25): a property is never hidden for lacking a verified
purchase procedure. The official page it was found on is its acquisition path
(path_type source_listing). A row the source no longer lists is still not
current (freshness gate), and a homepage / search page / http link is never a
path."""
from __future__ import annotations

import pytest

from harvesters.governance import publication_state as PS
from test_publication_state_gate import ctx, row


def laft(**over):
    base = dict(id="a1", source="laft", ledger_type="buy", source_id="fl_laft_calhoun", county="Gulf", url_auction=None,
                url_auction_kind=None, sale_date=None, list_url="https://www.calhounclerk.example.com/lands-available-list.pdf")
    base.update(over)
    return row(**base)


def test_available_row_with_only_its_source_list_is_published_with_that_link():
    d = PS.decide(laft(), ctx())
    assert d.state == "CUSTOMER_PUBLISHED"
    assert d.path.path_type == "source_listing" and d.path.destination_url.endswith("lands-available-list.pdf")
    assert d.path.scope == "source" and "no verified purchase procedure" in d.path.notes


@pytest.mark.parametrize("url", ["http://www.calhounclerk.example.com/list.pdf", "https://www.calhounclerk.example.com/",
                                 "https://www.google.com/search?q=lands+available"])
def test_untrusted_source_links_are_never_a_path(url):
    d = PS.decide(laft(list_url=url), ctx())
    assert d.state == "ADMIN_ONLY_NO_PATH" and d.path.path_type != "source_listing"


def test_a_stale_row_is_still_not_current_even_with_its_source_link():
    d = PS.decide(laft(last_seen_at=None), ctx())
    assert d.state == "ADMIN_ONLY_STALE"


def test_auction_with_a_non_sale_link_falls_back_to_its_source_listing():
    d = PS.decide(row(url_auction="https://www.desotoclerk.example.com/tax-deeds", url_auction_kind="info"), ctx())
    assert d.state == "CUSTOMER_PUBLISHED" and d.path.path_type == "source_listing" and d.path.scope == "record"


def test_the_source_listing_order_prefers_the_records_own_links():
    d = PS.decide(laft(purchase_url="https://www.calhounclerk.example.com/apply/123", document_url="https://www.calhounclerk.example.com/doc.pdf"), ctx())
    assert d.path.destination_url.endswith("/apply/123") and d.path.scope == "record"
    assert PS.SOURCE_LISTING_FIELDS == ("purchase_url", "url_auction", "document_url", "list_url")
