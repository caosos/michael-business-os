"""F-159: GSA-Auctions-style search page across all sources: sticky top bar, quick views, facet counts that equal the rows you get, sort orders,
numbered pagination, remembered sidebar collapse, Land/Real Estate default-off, prefs isolation. Offline: fixture caches only, no network."""
from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import pytest

from operator_ui import market_browse as mbr, market_prefs as mp, market_search as ms, market_sources as msrc
from tests.test_market_f47 import cache, post, req, ui  # noqa: F401
from tests.test_market_f149 import caches  # noqa: F401

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)      # 10:00 CDT


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.delenv(msrc.ENV_FLAG, raising=False)
    monkeypatch.delenv(msrc.ENV_DIR, raising=False)
    real = socket.create_connection

    def no_net(addr, *a, **k):
        if addr[0] not in ("127.0.0.1", "localhost"):
            raise AssertionError(f"network used: {addr}")
        return real(addr, *a, **k)
    monkeypatch.setattr(socket, "create_connection", no_net)
    return tmp_path / "prefs.json"


def get(ui, **qs):
    return req(ui, "GET", "/market?" + urlencode(qs, doseq=True))[2]


def total(h: str) -> int:
    return int(re.search(r"id='result-count' class='mk-count'>([\d,]+) results? found", h).group(1).replace(",", ""))


def counts(h: str, cls: str, attr: str) -> dict:
    return {m.group(1): int(m.group(2)) for m in re.finditer(rf"<label class='{cls}[^']*' {attr}='([^']+)' data-count='(\d+)'", h)}


BASE = dict(go=1, loc_mode="state", state="AR", broad=1)


# ---- counts equal the rows you get ----
def test_category_counts_equal_filtered_rows(ui):
    h = get(ui, **BASE)
    cats = {m.group(2): int(m.group(1)) for m in re.finditer(r"<label class='mk-cat[^']*' data-count='(\d+)'><input type='checkbox' form='mkform' name='cat' value='([^']+)'", h)}
    assert set(cats) == {"all", *ms.CONTROL_CATS}
    for k, n in cats.items():
        assert total(get(ui, **{**BASE, "cat": k})) == n, k
    assert any(n == 0 for n in cats.values()) and re.search(r"<label class='mk-cat' data-count='0'>", h)      # zero-count stays selectable


def test_source_counts_equal_filtered_rows_and_show_connection(ui, caches):
    h = get(ui, **BASE)
    src = counts(h, "mk-src-row", "data-src")
    assert {"gsa", "wooley", "wilson", "blackmon"} <= set(src)
    for k in ("gsa", "wooley", "wilson", "blackmon"):
        assert total(get(ui, **{**BASE, "source": k})) == src[k], k
    assert total(h) == int(re.search(r"<b>All sources</b> <span class='mk-n'>\((\d+)\)", h).group(1))
    side = h.split("id='sec-source'")[1].split("</details>")[0]
    assert "type='checkbox'" in side and "value='all' checked" in side
    assert all(f"value='{k}' checked" in side for k in ("gsa", "wooley", "wilson", "blackmon"))
    assert "connected" in side and "not connected" in side            # unavailable sources stay visible and selectable, honestly
    combo = get(ui, **{**BASE, "source": ["gsa", "wooley"]})
    assert total(combo) == src["gsa"] + src["wooley"]
    assert "value='gsa' checked" in combo and "value='wooley' checked" in combo and "value='wilson' checked" not in combo


def test_all_sources_checkbox_updates_every_source_immediately():
    js = (Path(__file__).parent.parent / "operator_ui/static/market_radius.js").read_text()
    assert 'getElementById("sec-source")' in js
    assert 'input[name=source][value=all]' in js
    assert "rest[i].checked = all.checked" in js
    assert "requestSubmit" not in js                         # choose several, then apply once; no reload between ticks


def test_state_counts_equal_filtered_rows(ui):
    h = get(ui, **BASE)
    st = {m.group(2): int(m.group(1)) for m in re.finditer(r"data-count='(\d+)'><input form='mkform' type='checkbox' name='state' value='([A-Z]{2})'", h)}
    assert st["AR"] > 0
    for code in [c for c, n in st.items() if n][:4] + ["WY"]:
        assert total(get(ui, **{**BASE, "state": code})) == st[code], code


def test_listing_type_counts_and_events_are_never_lots(ui, caches):
    h = get(ui, **BASE)
    lt = {m.group(2): int(m.group(1)) for m in re.finditer(r"data-count='(\d+)'><input type='radio' form='mkform' name='ltype' value='(\w+)'", h)}
    for k, n in lt.items():
        assert total(get(ui, **{**BASE, "ltype": k})) == n, k
    ev = get(ui, **{**BASE, "ltype": "event"})
    cards = re.findall(r"<div class='mk-g mk-card'[^>]*>", ev)
    assert cards and all("data-kind='auction-event'" in c for c in cards)
    assert "current bid / bidders UNKNOWN (event, not a lot)" in ev


# ---- quick views ----
def test_quick_view_counts_match_their_pages(ui, caches):
    h = get(ui, **BASE)
    qv = {m.group(1): int(m.group(2)) for m in re.finditer(r"data-quick='(\w+)' href='[^']*'>[^<]+<span class='mk-n'>\((\d+)\)", h)}
    assert set(qv) == {"all", "saved", "new", "today", "soon"} and qv["all"] == total(h) and qv["saved"] == 0
    for k in ("saved", "new", "today", "soon"):
        assert total(get(ui, **{**BASE, "quick": k})) == qv[k], k


def test_quick_view_rules():
    c = lambda **k: {"closes": None, "closes_at": None, "posted": None, **k}  # noqa: E731
    assert mbr.quick_ok(c(posted="2026-10-12"), "new", NOW) and not mbr.quick_ok(c(posted="2026-10-11"), "new", NOW)
    assert mbr.quick_ok(c(closes_at="2026-10-12T22:00:00-05:00"), "today", NOW)
    assert not mbr.quick_ok(c(closes_at="2026-10-13T09:00:00-05:00"), "today", NOW) and mbr.quick_ok(c(closes_at="2026-10-13T09:00:00-05:00"), "soon", NOW)
    assert not mbr.quick_ok(c(closes_at="2026-10-12T08:00:00-05:00"), "today", NOW)             # already closed
    assert not mbr.quick_ok(c(), "soon", NOW) and mbr.quick_ok(c(), "", NOW)                   # unknown close never counts as closing


def test_countdown_badge():
    at = lambda m: {"closes_at": (NOW + timedelta(minutes=m)).isoformat(), "closes": None}  # noqa: E731
    assert mbr.countdown(at(12), NOW) == ("12 min left", True) and mbr.countdown(at(125), NOW) == ("2 h 5 min left", True)
    assert mbr.countdown({"closes_at": (NOW + timedelta(seconds=30)).isoformat()}, NOW) == ("Closing", True)
    assert mbr.countdown(at(60 * 30), NOW) == ("", False) and mbr.countdown({"closes": "2026-10-12"}, NOW) == ("Closes today (time UNKNOWN)", True)


# ---- sort orders ----
ROWS = [{"id": "a", "title": "Alpha", "closes": "2026-10-20", "bid": 50.0, "distance": 30.0, "posted": "2026-10-01"},
        {"id": "b", "title": "Bravo", "closes": "2026-10-13", "bid": None, "distance": None, "posted": None},
        {"id": "c", "title": "Charlie", "closes": "2026-10-15", "bid": 10.0, "distance": 5.0, "posted": "2026-10-11"}]


@pytest.mark.parametrize("sort,want", [("closing", "bca"), ("new", "cab"), ("bid", "cab"), ("price_desc", "acb"), ("distance", "cab")])
def test_sort_orders(sort, want):
    key = {"closing": lambda c: (c["closes"] or "9999", c["title"]), "bid": lambda c: (c["bid"] is None, c["bid"] or 0, c["title"]),
           "distance": lambda c: (c["distance"] is None, c["distance"] or 0, c["title"])}.get(sort)
    assert "".join(c["id"] for c in ms.order(ROWS, sort, key)) == want


def test_sort_dropdown_labels_and_default(ui):
    h = get(ui, **BASE)
    sel = re.search(r"<label>Sort <select name='sort'>(.*?)</select>", h).group(1)
    assert re.findall(r">([^<]+)</option>", sel) == ["Ending soonest", "Newest", "Price: low to high", "Price: high to low", "Distance", "Suggested"]
    assert "<option value='closing' selected>" in sel and ms.parse_query({})["sort"] == "closing"
    assert ms.DEFAULT_RADIUS == 30.0


# ---- pagination ----
def test_paginate_12_per_page_and_clamps():
    rows = [{"id": str(i)} for i in range(50)]
    p1, n, pages = mbr.paginate(rows, 1)
    assert (len(p1), n, pages) == (12, 1, 5) and p1[0]["id"] == "0"
    p3, n, _ = mbr.paginate(rows, 3)
    assert [r["id"] for r in p3] == [str(i) for i in range(24, 36)] and n == 3
    assert mbr.paginate(rows, 99)[1] == 5 and mbr.paginate([], 5)[1:] == (1, 1)
    assert ms.parse_query({"page": ["2"]})["page"] == 2 and ms.parse_query({"page": ["x"]})["page"] == 1


def test_pager_links_carry_the_page_in_the_url():
    q = ms.parse_query({"go": ["1"], "loc_mode": ["state"], "state": ["AR"]})
    h = mbr.pager(q, 2, 5, 110)
    assert "aria-current='page'>2</b>" in h and "page=3" in h and "rel='prev'" in h and "rel='next'" in h and "Showing 13-24 of 110" in h
    assert mbr.pager(q, 1, 1, 10) == ""


def test_page_param_selects_the_slice(ui, monkeypatch):
    monkeypatch.setattr(ms, "PAGE_SIZE", 2)
    monkeypatch.setattr(mbr.paginate, "__defaults__", (2,))
    ids = lambda h: re.findall(r"<div class='mk-g mk-card' data-lot='([^']+)'", h.split("id='result-grid'")[1].split("id='pager'")[0])  # noqa: E731
    p1, p2 = get(ui, **BASE), get(ui, **BASE, page=2)
    assert len(ids(p1)) == 2 and len(ids(p2)) >= 1 and not set(ids(p1)) & set(ids(p2))
    assert "id='pager'" in p1 and "page=2" in p1


# ---- collapse persistence / Land default / prefs isolation ----
def test_collapse_is_remembered_and_survives_reset(ui, isolate):
    h = get(ui, **BASE)
    assert "<aside class='mk-side' id='filters-side'>" in h and "aria-expanded='true'" in h
    s = post(ui, "/market/ui", act="collapse", back="/market?go=1&loc_mode=state&state=AR")
    assert s[0] in (200, 303) and json.loads(isolate.read_text())["ui"]["filters_collapsed"] is True
    h = get(ui, **BASE)
    assert "<aside class='mk-side folded' id='filters-side'>" in h and "value='expand'" in h
    post(ui, "/market/pref", act="reset")
    assert mbr.collapsed()
    post(ui, "/market/ui", act="expand", back="https://evil.example/")
    assert not mbr.collapsed()


def test_collapse_needs_csrf(ui):
    st = req(ui, "POST", "/market/ui", {"act": "collapse"})[0]
    assert st in (200, 400, 403) and not mbr.collapsed()


def test_land_default_off_and_arkansas_preselected(ui):
    h = get(ui)
    box = re.search(r"<div id='mkcats'>.*?</div>", h, re.S).group(0)
    assert "value='land_real_estate' checked" not in box and "value='tools' checked" in box
    assert "name='state' value='AR' checked" in h and "name='base' size='12' value='72032'" in h
    assert "Filters (0)" in h


def test_prefs_isolated_to_the_test_file(isolate):
    assert mp.path() == isolate
    mbr.set_collapsed(True)
    d = json.loads(isolate.read_text())
    assert d["ui"] == {"filters_collapsed": True} and d["saved"] == [] and d["bids"] == {}
    isolate.write_text(json.dumps({"ui": {"home": {"state": "TX", "zip": "75001", "label": "Addison"}}}))
    assert mbr.home() == {"state": "TX", "zip": "75001", "label": "Addison"}
    assert mbr.with_home({})["state"] == ["TX"] and mbr.with_home({"base": ["x"]}) == {"base": ["x"]}


def test_phone_drawer_markup_and_card_shape(ui):
    h = get(ui, **BASE)
    assert "id='mkdrawer'" in h and "for='mkdrawer' id='filters-btn-m'" in h and "@media(max-width:600px){.mk-grid{grid-template-columns:minmax(0,1fr)}}" in h
    card = re.search(r"<div class='mk-g mk-card'.*?<div class='mk-vw'>.*?</div>", h, re.S).group(0)
    assert "mk-src'>GSA Auctions<" in card and "Closes " in card and ("current bid" in card or "bidders UNKNOWN" in card)
    assert "class='mk-view' href='/market/item/" in card              # F-160: View opens our detail page; the original link is on it


def test_search_is_the_only_control_that_requests_a_live_provider_refresh(ui):
    h = get(ui, **BASE)
    top = h.split("id='topbar'", 1)[1].split("</div>", 1)[0]
    assert "type='hidden' name='go'" not in top
    assert "type='submit' name='go' value='1'>Search" in top
    assert "class='mk-apply mk-apply-top'" in h
    assert "?go=1&amp;" not in mbr.href(ms.parse_query({"loc_mode": ["state"], "state": ["AR"]}), page=2)


def test_card_source_and_hide_are_visible_not_buried_on_the_photo_or_in_more():
    c = {"id": "facebook:visible", "title": "Utility trailer", "description": "", "text": "utility trailer", "url": "https://www.facebook.com/marketplace/item/1/",
         "image": "https://example.com/trailer.jpg", "bid": 450.0, "price": 450.0, "price_type": "fixed", "bidders": None, "closes": None, "city": "Conway, AR", "state": "AR",
         "distance": 4.2, "category": "trailer", "condition": "used", "labels": {}, "source": "Facebook Marketplace", "fetched_at": NOW.isoformat(),
         "kind": "fixed", "stale": False, "fixture": False, "posted": "2026-10-12"}
    h = mbr.card(c, lambda: "", NOW, __import__("operator_ui.market_view", fromlist=["x"]).pref_buttons)
    photo = re.search(r"<div class='mk-ph'>.*?</div>", h, re.S).group(0)
    assert "Facebook Marketplace" not in photo
    assert h.index("mk-card-src") > h.index("</div>")
    assert h.index("class='mk-x'") < h.index("class='mk-more'")
    assert h.count("value='hide'") == 1


def test_rental_ads_are_hidden_unless_the_owner_searches_for_rentals():
    base = {"description": "", "url": "https://www.facebook.com/marketplace/item/1/", "image": None, "bid": 80.0, "price": 80.0,
            "price_type": "fixed", "bidders": None, "closes": None, "city": "Conway, AR", "state": "AR", "distance": 4.2,
            "category": "trailer", "condition": "used", "labels": {}, "source": "Facebook Marketplace", "fetched_at": NOW.isoformat(),
            "kind": "fixed", "stale": False, "fixture": False, "posted": "2026-10-12"}
    sale = {**base, "id": "sale", "title": "Utility trailer", "text": "utility trailer"}
    rental = {**base, "id": "rental", "title": "16ft Utility Trailer Rental", "text": "16ft utility trailer rental"}
    q = ms.parse_query({"broad": ["1"]})
    rows, _, hidden = ms.partition([sale, rental], q)
    assert [c["id"] for c in rows] == ["sale"] and hidden["rentals"] == 1
    q = ms.parse_query({"broad": ["1"], "keywords": ["rental"]})
    rows, _, _ = ms.partition([sale, rental], q)
    assert [c["id"] for c in rows] == ["rental"]


def test_fixed_price_card_is_not_labelled_as_an_auction_bid():
    c = {"id": "facebook:1", "title": "Utility trailer", "description": "", "text": "utility trailer", "url": "https://www.facebook.com/marketplace/item/1/",
         "image": None, "bid": 450.0, "price": 450.0, "price_type": "fixed", "bidders": None, "closes": None, "city": "Conway, AR", "state": "AR",
         "distance": 4.2, "category": "trailer", "condition": "used", "labels": {}, "source": "Facebook Marketplace", "fetched_at": NOW.isoformat(),
         "kind": "fixed", "stale": False, "fixture": False, "posted": "2026-10-12"}
    h = mbr.card(c, lambda: "", NOW, lambda card, tok: "")
    assert "$450" in h and "fixed price" in h
    assert "current bid" not in h and "bidders UNKNOWN" not in h


def test_owner_marketplace_is_listings_first_without_operator_clutter(ui, caches):
    h = get(ui, **BASE)
    assert "DRY-RUN · nothing leaves this machine" not in h and "<header><b>Operator UI</b>" not in h
    assert "id='result-grid'" in h and "id='unchecked-section'" not in h
    assert all(x not in h for x in ("id='working-capital'", "id='gsa-explainer'", "id='sources-panel'", "id='your-finds'", "id='suggestions-strip'"))
    assert "id='my-marketplace'" in h and "id='admin-menu'" in h and "Saved listings" in h
    assert "No photo" not in h and "No photo from the seller" not in h
    assert ".mk-card-src{display:flex;justify-content:flex-end" in h
    card = h.split("class='mk-g mk-card'", 1)[1].split("class='mk-g mk-card'", 1)[0]
    assert "class='mk-save'" in card and card.index("class='mk-save'") < card.index("class='mk-more'")
