"""F-165: detail page fixes: no empty gallery block without a photo, the card's distance on the detail page, similar listings inside the owner's scope."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from operator_ui import market_detail as md
from operator_ui import market_search as ms
from tests.test_market_f47 import cache, get, ui  # noqa: F401
from tests.test_market_f160 import NOW, isolate, item  # noqa: F401
from tests.test_market_f149 import caches  # noqa: F401


def _c(i, cat, title, dist=None, state="AR", closes="2026-10-20"):
    return {"id": i, "title": title, "category": cat, "distance": dist, "bid": None, "city": "X, AR", "state": state, "closes": closes, "source": "GSA Auctions"}


def test_similar_within_radius_sorted_capped_no_land_no_self():
    me = _c("a", "trailers", "Me", 10)
    pool = [me, _c("far", "trailers", "Texas trailer", 400, "TX"), _c("unk", "trailers", "Nowhere trailer", None), _c("land", "trailers", "Ten acres of land", 3)]
    pool += [_c(f"n{i}", "trailers", f"Near {i}", i + 2) for i in range(12)] + [_c("tie", "trailers", "Tie late", 1, closes="2026-12-01"), _c("tie2", "trailers", "Tie early", 1, closes="2026-10-15")]
    q = ms.parse_query({"base": ["Conway AR"], "radius": ["100"], "loc_mode": ["distance"]})
    h = md._similar(me, pool, NOW, q)
    assert h.count("<li>") == 8 and "Texas" not in h and "Nowhere" not in h and "acres of land" not in h and ">Me<" not in h
    assert h.index("Tie early") < h.index("Tie late") < h.index("Near 0")
    assert "distance UNKNOWN" not in h


def test_detail_distance_equals_card_distance(ui, cache):
    get(ui, go=1, base="Conway AR", radius="500", view="list", keywords="trailer")      # remembers the owner's search
    q = md.search_query()
    cards = ms.load_source("all", NOW, ms._origin(q["base"]), str(cache))["cards"]
    c = next(x for x in cards if x.get("distance") is not None and not x.get("event"))
    s, h = item(ui, md.href(c))
    assert s == 200
    assert f"{round(c['distance'], 1):g} mi" in h and "distance unknown" not in h.split("Similar listings")[0] and "distance unknown (location not found)" not in h


def test_no_photo_layout_has_no_empty_gallery_block(ui, cache):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            pytest.skip("no chrome")
        d = json.loads(cache.read_text())
        for r in (d.get("Results") or d.get("records") or d):
            r["imageURL"] = ""
        cache.write_text(json.dumps(d))
        url = f"http://127.0.0.1:{ui.port}/market/item/gsa-auctions/3-1-QSC-I-27-006-005"
        for w, limit in ((1440, 600), (390, 400)):
            pg = b.new_page(viewport={"width": w, "height": 900})
            pg.goto(url)
            assert pg.query_selector("#dt-nophoto") is not None
            assert pg.query_selector(".dt-photos") is None
            top = pg.evaluate("document.querySelector('#dt-status').getBoundingClientRect().top + window.scrollY")
            assert top < limit, (w, top, pg.evaluate("[...document.querySelectorAll('header,nav,h1,main > p,#dt-nophoto')].map(e=>e.tagName+Math.round(e.getBoundingClientRect().top)+'+'+Math.round(e.getBoundingClientRect().height))"))
            pg.close()
        b.close()
