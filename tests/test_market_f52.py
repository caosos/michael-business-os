"""F-52: the F-51 AMENDMENT items F-51 left undone. (A) invalid filters are said out loud and unknowns never pass a strict limit;
(B) a gallery with the owner's rows; (C) explicit-feedback preference learning that never overrides a hard filter."""

from __future__ import annotations

import re

import pytest

from operator_ui import market_prefs as mp
from operator_ui import market_search as ms
from tests.test_market_f47 import NOW, cache, get, post, ui  # noqa: F401


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


def lots():
    return ms.load_gsa(None, NOW)["cards"]


# ---- (A) strict filters and visible validation
@pytest.mark.parametrize("bad", [{"max_price": "abc"}, {"min_price": "-5"}, {"radius": "far"}, {"max_price": "1e999"}, {"min_price": "900", "max_price": "100"}])
def test_invalid_numeric_filter_is_said_and_runs_nothing(ui, bad):
    h = get(ui, go=1, keywords="trailer", **bad)
    assert "id='filter-errors'" in h and "No search was run" in h
    assert "data-lot=" not in h and "id='zero-results'" not in h


def test_valid_filters_show_no_validation_message(ui):
    assert "filter-errors" not in get(ui, go=1, keywords="trailer", max_price="500", radius="150")


def test_unknown_price_or_distance_never_in_checked_results(ui):
    q = ms.parse_query({"keywords": [""], "broad": ["1"], "radius": ["150"], "max_price": ["100000"]})
    res, unchecked, _ = ms.partition(lots(), q)
    assert all(c["distance"] is not None and c["bid"] is not None and c["distance"] <= 150 and c["bid"] <= 100000 for c in res)
    assert all(c["unchecked"] for c in unchecked)
    assert any(c["distance"] is None or c["bid"] is None for c in unchecked)


def test_unchecked_section_is_a_closed_optional_disclosure(ui):
    h = get(ui, go=1, keywords="", broad="1", radius="150", max_price="100000")
    m = re.search(r"<details class='mk-sec' id='unchecked-section'>", h)
    assert m and "Optional" in h and "not counted as local or in range" in h


# ---- (B) gallery
def test_gallery_is_default_with_price_on_card_rows_and_placeholders(ui):
    h = get(ui, go=1)
    assert "class='mk-g'" in h and "data-row='trailers'" in h and "data-row='equipment'" in h
    assert "current bid" in h and "posted age: not given" in h and "Cached copy of the GSA list, not a fresh fetch" in h
    assert "Craigslist</a>" not in h and "<img" not in h.split("mk-main")[1]          # GSA photos need a login: tile, never a fake picture


def test_empty_category_row_says_no_matching_known_inventory(ui):
    h = get(ui, go=1, row1="trailers", row2="electronics", row3="", row4="", broad="1", keywords="trailer")
    assert "data-row='electronics'" in h and "No matching known inventory" in h


def test_owner_chooses_and_orders_rows_and_checked_category_replaces_focus(ui):
    h = get(ui, go=1, row1="equipment", row2="trailers", row3="", row4="")
    assert h.index("data-row='equipment'") < h.index("data-row='trailers'")
    only = get(ui, go=1, cat="trailers", radius="")
    assert "data-row='trailers'" in only and "data-row='equipment'" not in only


def test_sidebar_holds_filters_and_list_view_is_available(ui):
    h = get(ui, go=1)
    side = h.split("<aside")[1].split("</aside>")[0]
    for name in ("base", "radius", "min_price", "max_price", "cat"):
        assert f"form='mkform' name='{name}'" in side or f"form='mkform' type='number' id='{name}'" in side
    assert "form='mkform'" in side and "id='mkform'" in h
    assert "class='card mk-res'" in get(ui, go=1, view="list")


# ---- (C) preference learning, last
def test_feedback_is_persisted_reorders_and_says_why_but_never_widens_a_filter(ui):
    cards = lots()
    first = ms.partition(cards, ms.parse_query({"broad": ["1"], "radius": ["150"]}))[0]
    assert len(first) >= 2
    pick = first[-1]
    st, loc, _ = post(ui, "/market/pref", act="save", lot=pick["id"], title=pick["title"])
    assert st == 303 and mp.load()["saved"] == [pick["id"]]
    h = get(ui, go=1, broad="1", radius="150", view="list")
    assert "you saved it" in h
    assert h.index("data-why") < h.index("Original listing:", h.index("Original listing:") + 1)   # the saved lot is the first card
    # a saved lot that fails a strict limit stays out
    assert pick["title"] not in get(ui, go=1, broad="1", radius="150", max_price="0.01", sort="suggested") or pick["bid"] is None
    assert mp.act("more", "x", "Utility trailer heavy duty") and "trailer" in mp.load()["more"]


def test_dismiss_hides_until_reset_and_disable_turns_ranking_off(ui):
    first = ms.partition(lots(), ms.parse_query({"keywords": ["trailer"]}))[0][0]
    post(ui, "/market/pref", act="dismiss", lot=first["id"], title=first["title"])
    assert f"data-lot='{first['id']}'" not in get(ui, go=1, keywords="trailer")
    post(ui, "/market/pref", act="disable")
    assert f"data-lot='{first['id']}'" in get(ui, go=1, keywords="trailer") and "Suggestions: OFF" in get(ui, go=1)
    post(ui, "/market/pref", act="enable")
    post(ui, "/market/pref", act="reset")
    d = mp.load()
    assert d["dismissed"] == [] and d["saved"] == [] and d["more"] == {} and d["enabled"]


def test_pref_post_needs_csrf_and_rejects_unknown_actions(ui):
    from tests.test_operator_ui import req
    assert req(ui, "POST", "/market/pref", {"csrf": "wrong", "act": "reset"})[0] == 200      # re-rendered with the error, nothing stored
    assert mp.load()["saved"] == []
    st, _, body = post(ui, "/market/pref", act="launch")
    assert st == 200 and "unknown preference action" in body


def test_rank_only_reorders_and_hides_dismissed():
    a = {"id": "1", "title": "Utility trailer", "closes": "2026-10-20"}
    b = {"id": "2", "title": "Office chair", "closes": "2026-10-11"}
    d = {"enabled": True, "saved": [], "dismissed": [], "more": {"trailer": 2}, "less": {"chair": 1}}
    out, gone = mp.rank([b, a], d, lambda c: (c["closes"], c["title"]))
    assert [c["id"] for c in out] == ["1", "2"] and gone == 0 and "liked" in out[0]["why"] and "disliked" in out[1]["why"]
    d["dismissed"] = ["1"]
    out, gone = mp.rank([b, a], d, lambda c: (c["closes"], c["title"]))
    assert [c["id"] for c in out] == ["2"] and gone == 1
