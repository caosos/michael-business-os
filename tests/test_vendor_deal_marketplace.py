"""Approved local-deal ads use the same Marketplace grid and filter chain."""

from datetime import datetime, timezone

from operator_ui import local_deal_sources as lds
from operator_ui import market_browse as browse
from operator_ui import market_detail
from operator_ui import market_search as search
from operator_ui import market_view


NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)


def local_card(n: int, category: str = "food_grocery") -> dict:
    payload = {
        "method": "vendor_submission",
        "source_id": f"customer-{n}",
        "source_name": f"Conway Customer {n}",
        "source_class": "local business",
        "geography": "Conway, AR",
        "source_offer_id": f"offer-{n}",
        "source_url": f"https://customer{n}.com/deals/{n}",
        "image_url": f"https://cdn.customer{n}.com/deals/{n}.jpg",
        "vendor_submission_id": f"mail-{n}",
        "authority_attested": True,
        "title": f"Fresh ground beef deal {n}" if category == "food_grocery" else f"Lunch special {n}",
        "category": category,
        "description": "Customer-authorized daily special",
        "deal_price": str(1.99 + n),
        "regular_price": str(4.99 + n),
        "unit": "per pound" if category == "food_grocery" else "per meal",
        "location": "Conway, AR 72032",
        "availability": f"First {100 + n} available",
        "terms": "While supplies last",
        "observed_at": "2026-10-13T17:30:00Z",
        "expires_at": "2026-10-14T23:00:00Z",
    }
    row = lds.normalize(payload, "2026-10-13T18:00:00Z", f"import-{n}")
    return lds.card(row, search._origin("72032"))


def auction_card() -> dict:
    return {
        "id": "gsa:trailer-1", "title": "Utility trailer", "description": "Federal surplus",
        "text": "utility trailer federal surplus", "url": "https://www.gsaauctions.gov/auctions/preview/1",
        "image": "https://images.gsa.gov/trailer.jpg", "bid": 50.0, "price": None, "price_type": "auction_current",
        "bidders": 2, "closes": "2026-10-15", "closes_at": "2026-10-15T18:00:00Z",
        "city": "Conway, AR", "state": "AR", "zip": "72032", "posted": "2026-10-13", "distance": 1.0,
        "category": "trailer", "condition": "used", "labels": search.auction_labels({"highBidAmount": 50.0}),
        "source": "GSA Auctions", "source_key": "gsa", "fetched_at": NOW.isoformat(), "kind": "auction", "stale": False,
    }


def query(**overrides) -> dict:
    raw = {"loc_mode": ["state"], "state": ["AR"], "cat": ["all"], "broad": ["1"], "source": ["all"]}
    raw.update({k: [v] if not isinstance(v, list) else v for k, v in overrides.items()})
    return search.parse_query(raw)


def test_mixed_auction_and_local_deals_share_filter_sort_and_pagination_path():
    rows = [auction_card()] + [local_card(i, "restaurants" if i == 13 else "food_grocery") for i in range(1, 59)]
    checked, unchecked, hidden = search.partition(rows, query(sort="bid"))
    assert unchecked == [] and not any(hidden.values())
    assert len(checked) == 59 and {c["source_key"] for c in checked} == {"gsa", "local_deals"}
    assert [search.display_price(c) for c in checked] == sorted(search.display_price(c) for c in checked)

    first, page, pages = browse.paginate(checked, 1)
    second, page2, _ = browse.paginate(checked, 2)
    assert (len(first), page, pages) == (50, 1, 2)
    assert (len(second), page2) == (9, 2)
    assert not {c["id"] for c in first} & {c["id"] for c in second}
    assert "Showing 1-50 of 59" in browse.pager(query(), 1, pages, len(checked))
    tok = lambda: "<input name='csrf' value='x'>"
    page_one_grid = "<div id='result-grid'>" + "".join(browse.card(c, tok, NOW, market_view.pref_buttons) for c in first) + "</div>"
    page_two_grid = "<div id='result-grid'>" + "".join(browse.card(c, tok, NOW, market_view.pref_buttons) for c in second) + "</div>"
    assert page_one_grid.count("class='mk-g mk-card'") == 50
    assert page_two_grid.count("class='mk-g mk-card'") == 9


def test_named_vendor_source_selects_its_approved_offer_and_keeps_local_group():
    payload = {
        "method": "vendor_submission", "source_id": "half_off_wholesale",
        "source_name": "Half Off Wholesale — Little Rock", "source_class": "liquidation / wholesale",
        "geography": "North Little Rock, AR", "source_offer_id": "pallet-1",
        "source_url": "https://halfoffvip.com/offers/pallet-1", "image_url": "https://halfoffvip.com/images/pallet-1.jpg",
        "vendor_submission_id": "mail-pallet-1", "authority_attested": True,
        "title": "Tool liquidation pallet", "category": "pallets_wholesale",
        "description": "Current reviewed pallet offer", "deal_price": "699", "regular_price": "999",
        "unit": "per pallet", "location": "North Little Rock, AR 72117", "availability": "One available",
        "terms": "While available", "observed_at": "2026-10-13T17:30:00Z", "expires_at": "2026-10-14T23:00:00Z",
    }
    card = lds.card(lds.normalize(payload, "2026-10-13T18:00:00Z", "half-off-pallet-1"), search._origin("72032"))
    assert browse.source_ok(card, "half_off_wholesale")
    assert browse.source_ok(card, "local_deals")
    assert set(browse.facets(lambda qq, relax: browse.post([card], qq, NOW, relax), query(), NOW)["source"]) >= {"half_off_wholesale", "local_deals"}


def test_local_deal_category_source_and_keyword_filters_are_exact():
    food = local_card(1)
    meal = local_card(2, "restaurants")
    auction = auction_card()
    rows = [food, meal, auction]

    food_rows = search.partition(rows, query(cat="food_grocery"))[0]
    assert [c["id"] for c in food_rows] == [food["id"]]
    local_rows = browse.post(search.partition(rows, query())[0], query(source="local_deals"), NOW)
    assert {c["id"] for c in local_rows} == {food["id"], meal["id"]}
    mixed_sources = browse.post(search.partition(rows, query())[0], query(source=["gsa", "local_deals"]), NOW)
    assert {c["id"] for c in mixed_sources} == {c["id"] for c in rows}
    keyword_rows = search.partition(rows, query(keywords="lunch special"))[0]
    assert [c["id"] for c in keyword_rows] == [meal["id"]]


def test_local_deal_grid_card_keeps_customer_offer_facts_and_shared_actions():
    card = local_card(1)
    html = browse.card(card, lambda: "<input name='csrf' value='x'>", NOW, market_view.pref_buttons)

    for expected in (
        card["image"], "Conway Customer 1", "$2.99 per pound", "Conway, AR 72032", "Expires Wed Oct 14",
        "Available:</b> First 101 available", "Authorized local deals", "View", "Original offer",
        "Save", "Hide", "More like this", "Less like this",
    ):
        assert expected in html
    assert card["url"] in html
    assert "current bid" not in html and "I bid on this" not in html
    detail = market_detail.local_deal_page(card, NOW)
    assert card["image"] in detail and card["url"] in detail
    assert "Open original offer" in detail and "Deal price</th><td>$2.99 per pound" in detail
