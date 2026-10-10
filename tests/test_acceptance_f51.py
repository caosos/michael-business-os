"""F-51: min+max price, editable origin/radius that really constrain, unchecked section, default trailers/equipment focus, broad mode explicit,
working-capital label, demo only at /demo, GSA plain language, a visible Search button. Reuses the F-47 fixtures (GSA cache, no network)."""

from __future__ import annotations

import re
from datetime import timedelta

from operator_ui import market_search as ms
from tests.test_market_f47 import ASOF, NOW, cache, get, post, ui  # noqa: F401  (fixtures)
from tests.test_operator_ui import req


def cards(cache):
    return ms.load_gsa(str(cache), NOW)["cards"]


def names(rs):
    return sorted(c["title"] for c in rs)


def q(**kw):
    return ms.parse_query({k: [str(v)] for k, v in {"broad": "1", **kw}.items()})


def test_min_and_max_price_select_the_right_set(cache):
    cs = cards(cache)
    assert names(ms.partition(cs, q(min_price=20, max_price=30))[0]) == ["Trailer, Utility", "iPad Mini Lot"]
    assert names(ms.partition(cs, q(min_price=40))[0]) == ["Traulsen Double Refrigerator"]
    assert ms.partition(cs, q(min_price=100000))[0] == []                      # zero is zero, not padded
    res, unchecked, hidden = ms.partition(cs, q(min_price=20, max_price=30))
    assert hidden["price"] >= 3 and all(c["bid"] is None for c in unchecked if "price unknown" in " ".join(c["unchecked"]))


def test_radius_constrains_known_distance_and_unknown_goes_to_optional(cache):
    cs = cards(cache)
    res, unchecked, hidden = ms.partition(cs, q(radius=100))
    assert names(res) == ["Trailer, Utility"] and hidden["radius"] >= 5        # 97.9 mi is in, 117.6 mi is out
    assert all("distance unknown" in " ".join(c["unchecked"]) for c in unchecked) and any("Blackhawk" in c["title"] for c in unchecked)
    assert not any(c["distance"] is None for c in res)                         # an unlocated lot is never counted as local
    assert ms.partition(cs, q(radius=50))[0] == []
    assert len(ms.partition(cs, q(radius=150))[0]) == 6


def test_default_view_is_trailer_equipment_near_conway_and_broad_is_explicit(ui):
    h = get(ui)                                                                # no filters at all
    assert "Mode: repairable trailers/equipment focus: trailer, equipment" in h and "Radius: 150 mi" in h and "Origin: Conway AR (ZIP 72032)" in h
    assert "Trailer, Utility" in h and "iPad Mini" not in h and "Whirlpool" not in h
    hb = get(ui, go=1, broad=1, base="Conway AR", radius="")
    assert "Mode: BROAD inventory" in hb and "iPad Mini" in hb and "Broad (all categories)" in hb


def test_http_min_max_radius_change_results_and_chips(ui):
    h = get(ui, go=1, broad=1, base="Conway AR", radius="100", min_price="20", max_price="30")
    assert "Min price: $20" in h and "Max price: $30" in h and "Radius: 100 mi" in h
    assert "Trailer, Utility" in h and "iPad Mini" not in h and "id='unchecked-section'" in h and "Blackhawk" in h
    sec = h.split("id='unchecked-section'")[1]
    assert "Blackhawk" in sec and "Trailer, Utility" not in sec
    assert "1 result" in h.split("unchecked-section")[0]                       # the unchecked lots are not in the count
    z = get(ui, go=1, broad=1, radius="10", min_price="20")
    assert "id='zero-results'" in z and "0 results" in z


def test_unresolved_origin_applies_no_radius_and_invents_nothing(ui):
    h = get(ui, go=1, broad=1, base="Zzyzx 99999", radius="50")
    assert "accepted but not located" in h and "0 results" in h and "id='unchecked-section'" in h
    assert re.search(r"<h2>0 results", h)


def test_filters_persist_across_navigation(ui):
    get(ui, go=1, broad=1, radius="100", min_price="20", max_price="30", base="Conway AR")
    req(ui, "GET", "/wanted")
    h = req(ui, "GET", "/market")[2]
    assert "Min price: $20" in h and "Radius: 100 mi" in h and "Mode: BROAD" in h
    assert "Fill in the search" in get(ui, new=1)
    assert "Min price: $" not in req(ui, "GET", "/market")[2]                      # `new` cleared them


def test_labels_gsa_explainer_working_capital_and_button(ui):
    h = get(ui, view="list")        # F-52: the default view is the gallery; the detailed labels live on the list card
    assert "Current bid" in h and "Asking price: none (auction)" in h and "never the final cost" in h and "all-in cost UNKNOWN" in h
    assert "government surplus auctions" in h and "requires a GSA login" in h and "do not log in or bypass" in h
    assert "SETTING" in h and "Verified cash:" in h and "not cash" in h
    assert "type='range'" in h and "aria-label='Minimum price slider'" in h and "not a budget" in h
    assert "background:var(--acc);color:var(--bg)" in h and "<button class='mk-go' type='submit'>Search</button>" in h and "disabled" not in h.split("mk-go")[1][:80]


def test_demo_only_behind_explicit_route(ui):
    for path in ("/market", "/wanted", "/gsa"):
        assert "demo=1" not in req(ui, "GET", path)[2], path
    s, _, h = req(ui, "GET", "/demo")
    assert s == 200 and "separate area" in h and "/queue?demo=1" in h
    assert 'href="/demo"' not in req(ui, "GET", "/market")[2]


def test_slider_without_scripts_wins_only_when_moved(ui):
    assert q(max_r=500, prev_max=20000, max_price=30)["max_price"] == 500       # moved slider beats the old box
    assert q(max_r=20000, prev_max=20000, max_price=30)["max_price"] == 30      # untouched slider: the typed number
    assert q(min_r=1, prev_min=1)["min_price"] is None
    h = get(ui, go=1, broad=1, radius="", max_r="25", prev_max="20000")
    assert "Max price: $25" in h and "name='max_r'" in h and "name='prev_max' value='25'" in h and "<script" not in h
