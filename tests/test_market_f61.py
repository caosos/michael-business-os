"""F-61: current bid, next minimum bid and reserve Yes/No/Unknown only from fields in the GSA cache (highBidAmount, aucIncrement, reserve)."""
from __future__ import annotations

from operator_ui.market_search import auction_labels as lab
from tests.test_market_f47 import cache, get, ui  # noqa: F401


def test_reserve_yes_without_amount_says_undisclosed_and_no_floor():
    r = lab({"highBidAmount": 45.0, "aucIncrement": 20.0, "reserve": True})
    assert r["reserve"] == "Yes" and "reserve amount undisclosed" in r["reserve_text"]
    assert r["next_min_bid"] == 65.0 and "$65.00" in r["next_min_text"] and "$65" not in r["reserve_text"]


def test_reserve_no_and_unknown():
    assert lab({"reserve": False})["reserve_text"] == "No"
    for v in (None, "", "maybe", 1, [], {}):
        r = lab({"reserve": v})
        assert r["reserve"] == "Unknown" and "UNKNOWN" in r["reserve_text"] and "field reserve" in r["reserve_text"]
    assert lab({})["reserve"] == "Unknown"


def test_reserve_never_derived_from_retail_or_bid():
    r = lab({"highBidAmount": 85.0, "aucIncrement": 5.0, "reserve": None, "retailPrice": 900, "estimatedValue": 900})
    assert r["reserve"] == "Unknown" and "900" not in r["reserve_text"] and "90" not in r["reserve_text"]


def test_next_min_bid_needs_bid_and_increment():
    no_bid = lab({"highBidAmount": None, "aucIncrement": 10.0})
    assert no_bid["next_min_bid"] is None and "no bid yet" in no_bid["next_min_text"] and "increment $10.00" in no_bid["next_min_text"]
    no_inc = lab({"highBidAmount": 25.0})
    assert no_inc["next_min_bid"] is None and "aucIncrement" in no_inc["next_min_text"]
    assert lab({"highBidAmount": True, "aucIncrement": True})["next_min_bid"] is None


def test_rendered_list_card_shows_labels_and_names_source(ui):
    h = get(ui, go=1, keywords="trailer", view="list")
    assert "id='auction-labels'" in h and "Next minimum bid:" in h and "Reserve:" in h and "GSA Auctions cache" in h


def test_render_card_unknown_reserve_wording(ui):
    h = get(ui, go=1, keywords="trailer", view="list")
    assert "reserve amount undisclosed" in h or "Reserve: No" in h or "Reserve: UNKNOWN" in h
