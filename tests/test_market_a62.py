"""A-62: no-bid card says opening/minimum bid unknown + original link, no number; a sourced minimum shows with provenance + asof."""
from __future__ import annotations

import re

from operator_ui import market_search as ms
from operator_ui import market_view as mv

URL = "https://www.gsaauctions.gov/auctions/lot/ABC-1"


def card(p, bid=None):
    return {"id": "L1", "title": "Scrap trailer", "description": "d", "url": URL, "image": None, "bid": bid, "closes": "2026-10-20", "city": "Conway, AR",
            "distance": 5.0, "condition": None, "stale": False, "source": "GSA Auctions", "fetched_at": "2026-10-10T00:19:23Z", "kind": "auction",
            "labels": ms.auction_labels(p, "2026-10-10T00:19:23Z"), "tags": {}, "unchecked": []}


def text(h):
    return re.sub(r"<[^>]+>", " ", h)


def test_no_bid_fixture_unknown_label_link_and_no_number():
    c = card({"highBidAmount": None, "aucIncrement": 8, "reserve": True})
    for h in (mv.render_card(c), mv.gallery_card(c, lambda: "")):
        assert "Opening/minimum bid unknown — check original listing" in h and URL in h
        assert c["labels"]["opening_min"] is None
    h = mv.render_card(c)
    seg = re.search(r"id='opening-min'>(.*?)</p>", h).group(1)
    assert not re.search(r"\$\s*\d|\b\d+(\.\d+)?\b", text(seg)), seg
    assert "reserve amount undisclosed" in h and "ESTIMATED" not in text(h).split("Next bid:")[1].split("·")[0]


def test_sourced_minimum_renders_with_provenance_and_asof():
    c = card({"highBidAmount": None, "aucIncrement": 8, "reserve": True, "minBidAmount": 25})
    h = mv.render_card(c)
    assert "Opening/minimum bid $25.00 (source field minBidAmount, as of cached 2026-10-10T00:19:23Z" in h
    assert "unknown — check" not in h


def test_never_substituted_from_zero_increment_or_retail():
    for p in ({"openingBidAmount": 0, "aucIncrement": 8}, {"retailPrice": 900, "aucIncrement": 8, "reserve": True}, {"minBidAmount": "x"}):
        L = ms.auction_labels(p)
        assert L["opening_min"] is None and "unknown" in L["opening_text"]
    assert ms.auction_labels({"highBidAmount": 40.0})["opening_text"] == ""


def test_valuation_note_keeps_unknowns_explicit():
    h = mv.render_card(card({}))
    for w in ("gross scrap/component estimate", "net yard pickup offer", "towing", "disposal", "recoverable weight", "UNKNOWN"):
        assert w in h
