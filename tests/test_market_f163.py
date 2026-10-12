"""F-163: /market layout rework in a real browser. Phone: the first result card is within the first 900 px. Desktop: Filters card first (left), My bids below it and collapsed,
result grid near the top, one-line top bar with exactly one submit, one visible primary button per card, readable active pill. Offline: fixture caches only."""
from __future__ import annotations

import json
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from operator_ui import market_bids as mbids, market_sources as msrc
from tests.test_market_f47 import cache, get, ui  # noqa: F401
from tests.test_market_f149 import caches  # noqa: F401

MAIL = Path(__file__).parent / "fixtures" / "alerts"
QS = "/market?go=1&loc_mode=state&state=AR&broad=1"


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.setenv(msrc.ENV_FLAG, "1")                      # the FIXTURE banner and alert fixtures are part of the page under test
    monkeypatch.setenv(msrc.ENV_DIR, str(MAIL))
    real = socket.create_connection
    monkeypatch.setattr(socket, "create_connection", lambda a, *x, **k: real(a, *x, **k) if a[0] in ("127.0.0.1", "localhost") else (_ for _ in ()).throw(AssertionError(a)))
    for i in range(12):                                         # a long My bids list, like the owner's
        mbids.act("bid", {"lot": f"b{i}", "title": f"Tracked lot {i}", "source": "GSA Auctions", "closes": "2026-12-01", "bid": "100"}, datetime.now(timezone.utc).isoformat())


def _browser(p):
    try:
        return p.chromium.launch(channel="chrome", headless=True)
    except Exception:
        pytest.skip("no chrome")


def top(pg, sel):
    return pg.evaluate("s=>{const e=document.querySelector(s);return e?e.getBoundingClientRect().top+scrollY:null}", sel)


def test_page_order_and_card_markup(ui, caches):
    h = get(ui, go=1, loc_mode="state", state="AR", broad=1)
    assert h.index("id='mkfilters'") < h.index("id='my-bids'") and "<details class='card small' id='my-bids'>" in h and "<details open" not in h.split("id='my-bids'")[0][-40:]
    assert h.count("class='mk-go' type='submit'") == 1 and ">Search</button>" in h and "mk-apply'>Apply</button></form>" not in h
    assert h.index("id='topbar'") < h.index("id='quick-views'") < h.index("id='result-grid'")
    assert "id='suggestions-strip'" in h and "id='sources-summary'" in h and "id='source-status'" in h.split("id='sources-panel'")[1]
    assert "id='fixture-banner'" in h.split("id='topbar'")[1].split("id='result-grid'")[0]
    card = h.split("class='mk-g mk-card'")[1].split("<div class='mk-g mk-card'")[0]
    assert card.count("class='mk-view'") + card.count("class='mk-vw'") >= 1 and "<details class='mk-more'>" in card and card.index("mk-view") < card.index("mk-more")
    assert "Save" in card.split("mk-more")[1] and "I bid on this" in card.split("mk-more")[1]


def test_phone_first_card_within_900(ui, caches):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = _browser(p)
        pg = b.new_page(viewport={"width": 390, "height": 900})
        pg.goto(f"http://127.0.0.1:{ui.port}{QS}")
        y = top(pg, ".mk-card")
        print("PHONE_FIRST_CARD_TOP", y)
        assert y is not None and y < 900, y
        b.close()


def test_desktop_layout(ui, caches):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = _browser(p)
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(f"http://127.0.0.1:{ui.port}{QS}")
        assert top(pg, "#mkfilters") < top(pg, "#my-bids") and pg.evaluate("document.querySelector('#my-bids').open") is False
        assert pg.evaluate("document.querySelector('#mkfilters').getBoundingClientRect().left") < pg.evaluate("document.querySelector('#result-grid').getBoundingClientRect().left")
        print("DESKTOP_GRID_TOP", top(pg, "#result-grid"), "FILTERS", top(pg, "#mkfilters"))
        assert top(pg, "#result-grid") < 450, top(pg, "#result-grid")
        pg.evaluate("document.querySelector('#my-bids').open=true")
        assert top(pg, "#mkfilters") < top(pg, "#my-bids li")
        pg.evaluate("document.querySelector('#my-bids').open=false")
        bar = pg.evaluate("""()=>{const bar=document.querySelector('#mkform'),r=[...bar.children].filter(e=>e.getBoundingClientRect().height).map(e=>Math.round(e.getBoundingClientRect().top));
          return {tops:r,subs:[...document.querySelectorAll('#topbar button[type=submit],#topbar input[type=submit]')].length}}""")
        assert max(bar["tops"]) - min(bar["tops"]) < 20 and bar["subs"] == 1, bar
        top_row = pg.evaluate("[...document.querySelectorAll('#topbar>*')].filter(e=>!e.matches('.mk-quick')&&e.getBoundingClientRect().height).map(e=>Math.round(e.getBoundingClientRect().top))")
        assert max(top_row) - min(top_row) < 20, top_row                     # search form and the Filters toggle share one line
        cards = pg.query_selector_all(".mk-card")
        assert cards
        for c in [c for c in cards if c.is_visible()]:
            vis = c.evaluate("e=>[...e.querySelectorAll('.mk-view,button')].filter(x=>x.checkVisibility()).length")
            assert vis == 1, (vis, c.query_selector('.mk-vw').inner_html()[:300])
        pg.click("#quick-views .mk-q.cur") if pg.query_selector("#quick-views .mk-q.cur") else None
        pill = pg.evaluate("""()=>{const a=document.querySelector('.mk-q.cur .mk-n');if(!a)return null;return [getComputedStyle(a).color,getComputedStyle(a.parentElement).backgroundColor]}""")
        assert pill == ["rgb(255, 255, 255)", "rgb(29, 78, 216)"], pill
        b.close()


def test_no_duplicate_state_in_card_location(ui, caches):
    import re
    h = get(ui, go=1, loc_mode="state", state="AR", broad=1)
    assert "class='mk-g mk-card'" in h and not re.search(r", ([A-Z]{2}), \1\b", h)
    from operator_ui.market_browse import _where
    assert _where({"city": "Fayetteville, AR", "state": "AR", "zip": "72701"}) == "Fayetteville, AR 72701"
    assert _where({"city": "Conway", "state": "AR", "zip": None}) == "Conway, AR" and _where({"city": None}) == "town UNKNOWN"


@pytest.mark.parametrize("w,h", [(390, 900), (360, 800), (1440, 900)])
def test_no_horizontal_overflow(ui, caches, w, h):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = _browser(p)
        pg = b.new_page(viewport={"width": w, "height": h})
        pg.goto(f"http://127.0.0.1:{ui.port}/market?go=1&loc_mode=state&state=AR&broad=1")
        assert pg.evaluate("document.scrollingElement.scrollWidth") == w
        for sel in (".mk-go", "#topbar .mk-fm" if w < 700 else "#filters-btn"):
            r = pg.evaluate("s=>{const r=document.querySelector(s).getBoundingClientRect();return [r.left,r.right]}", sel)
            assert r[0] >= 0 and r[1] <= w, (sel, r)
        assert top(pg, ".mk-card") < h
        b.close()
