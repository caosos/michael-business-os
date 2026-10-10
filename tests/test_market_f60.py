"""F-60: the primary 'Search Now' lives in the filter card and submits the real current values (click and Enter); the disconnected
'Find Deals Now' box is gone and New Search / Save / My Campaigns / Saved Deals are secondary."""
from __future__ import annotations

import re

import pytest

from tests.test_market_f47 import cache, get, ui  # noqa: F401


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


def _card(h: str) -> str:
    return re.search(r"<div class='card' id='mkfilters'>.*?</p></div>", h, re.S).group(0)


def test_search_now_is_in_filter_card_and_owned_by_the_search_form(ui):
    h = get(ui)
    card = _card(h)
    assert card.count("Search Now") == 1 and "type='submit' form='mkform'>Search Now" in card
    for name in ("min_price", "max_price", "radius", "base"):
        assert re.search(rf"<input[^>]*form='mkform'[^>]*name='{name}'", card)
    assert h.count("Search Now") == 1 and h.count("mk-go' type='submit'") == 1
    assert "Find Deals Now" not in h and "<form method='get' action='/market' class='mk-form mk-bar' id='mkform'" in h


def test_secondary_actions_kept_and_demoted(ui):
    nav = re.search(r"<nav aria-label='Marketplace'>.*?</nav>", get(ui), re.S).group(0)
    for t in ("New Search", "My Campaigns / Saved Searches", "Saved Deals", "Auctions Closing Soon"):
        assert t in nav
    assert "mk-go" not in nav and "id='save-search'" in get(ui) and "Save this search" in get(ui)


def _pw():
    pw = pytest.importorskip("playwright.sync_api")
    return pw


def test_real_browser_click_and_enter_submit_current_values(ui):
    pw = _pw()
    base = f"http://127.0.0.1:{ui.port}"
    ids = lambda pg: pg.evaluate("()=>[...document.querySelectorAll('.mk-g')].filter(c=>!c.closest('#unchecked-section')).map(c=>c.dataset.lot)")  # noqa: E731
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            pytest.skip("no chrome")
        for vp in ({"width": 1280, "height": 800}, {"width": 390, "height": 800}):
            pg = b.new_page(viewport=vp)
            pg.goto(base + "/market?go=1&broad=1&radius=150")
            wide = ids(pg)
            assert pg.evaluate("()=>{const r=document.querySelector('button.mk-go').getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight}"), vp
            pg.fill("#max_price", "25")
            pg.click("button.mk-go")
            pg.wait_for_load_state()
            assert "max_price=25" in pg.url and "radius=150" in pg.url and pg.input_value("#max_price") == "25"
            click_ids = ids(pg)
            assert len(wide) == 6 and len(click_ids) == 4 and set(click_ids) < set(wide)
            pg.fill("#max_price", "")
            pg.fill("#max_price", "20000")
            pg.focus("#max_price")
            with pg.expect_navigation():
                pg.keyboard.press("Enter")
            enter_ids = ids(pg)
            assert "max_price=20000" in pg.url and len(enter_ids) > len(click_ids)
            pg.goto(base + "/market?go=1&broad=1&radius=150&max_price=20000")
            assert ids(pg) == enter_ids
            pg.fill("input[name=radius]", "37.5")
            with pg.expect_navigation():
                pg.keyboard.press("Enter")
            assert "radius=37.5" in pg.url and pg.input_value("input[name=radius]") == "37.5"
            pg.close()
        b.close()
