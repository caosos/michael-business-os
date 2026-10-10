"""F-137: estimated (never 'minimum') next bid with as-of stamp; non-finite amounts rejected; labels on the gallery card."""
from __future__ import annotations

import pytest

from operator_ui.market_search import _amt, auction_labels as lab
from operator_ui.market_view import gallery_labels
from tests.test_market_f47 import cache, get, ui  # noqa: F401


def test_estimate_has_asof_and_unverified_and_is_not_called_minimum():
    r = lab({"highBidAmount": 45.0, "aucIncrement": 20.0, "reserve": False}, "2026-10-10T00:19:23Z")
    t = r["next_min_text"]
    assert t.startswith("ESTIMATED $65.00") and "as of cached 2026-10-10T00:19:23Z" in t and "live minimum unverified" in t
    assert "minimum" not in t.replace("live minimum unverified", "").replace("opening minimum", "")


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), -1, True, "5", None])
def test_amt_rejects_non_finite_and_invalid(bad):
    assert _amt(bad) is None


def test_non_finite_bid_increment_and_sum_rejected():
    for p in ({"highBidAmount": float("inf"), "aucIncrement": 5}, {"highBidAmount": 5, "aucIncrement": float("nan")}):
        assert lab(p)["est_next_bid"] is None
    big = lab({"highBidAmount": 1e308, "aucIncrement": 1e308})          # finite parts, infinite sum
    assert big["est_next_bid"] is None and "inf" not in big["next_min_text"].lower()


def test_unknown_opening_minimum_retained_without_bid():
    r = lab({"aucIncrement": 10.0, "reserve": True})
    assert r["est_next_bid"] is None and "opening minimum is not in the GSA cache" in r["next_min_text"] and "increment $10.00" in r["next_min_text"]


def test_gallery_card_shows_reserve_and_bid_vs_estimate():
    c = {"labels": lab({"highBidAmount": 45.0, "aucIncrement": 20.0, "reserve": True})}
    assert gallery_labels(c) == "Bid $45 → est. next ~$65 (cached, unverified) · Reserve: Yes (amount undisclosed)"
    assert "est. next UNKNOWN" in gallery_labels({"labels": lab({"reserve": None})}) and "Reserve: UNKNOWN" in gallery_labels({})


def test_rendered_gallery_has_labels(ui):
    h = get(ui, go=1, keywords="trailer", view="gallery")
    assert "gal-lbl" in h and "est. next" in h and "Reserve:" in h
