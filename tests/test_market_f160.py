"""F-160: the listing detail page /market/item/<source>/<id>, offline, from fixture caches only. Every card links to it; GSA fields render; unknowns are labelled;
an auction event gets an event page; similar listings exclude the item and keep Land default-off; nothing is fetched while rendering."""
from __future__ import annotations

import re
import socket
from datetime import datetime, timezone
from urllib.parse import unquote

import pytest

from operator_ui import market_detail as md
from tests.test_market_f47 import cache, get, ui  # noqa: F401
from tests.test_market_f149 import caches  # noqa: F401
from tests.test_operator_ui import req

NOW = datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc)
HREF = re.compile(r"href='(/market/item/[^']+)'")


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    real = socket.create_connection
    monkeypatch.setattr(socket, "create_connection", lambda a, *x, **k: real(a, *x, **k) if a[0] in ("127.0.0.1", "localhost") else (_ for _ in ()).throw(AssertionError(f"network used: {a}")))


def item(ui, path):
    s, _, h = req(ui, "GET", path)
    return s, h


def test_every_card_links_to_a_detail_page(ui, caches):
    for view in ("gallery", "list"):
        h = get(ui, go=1, loc_mode="state", state="AR", broad=1, source="all", view=view)
        links = sorted(set(HREF.findall(h)))
        assert links, view
        for u in links[:12]:
            s, body = item(ui, u)
            assert s == 200 and "<h1>" in body and "Back to Marketplace" in body, u
    h = get(ui, go=1, loc_mode="state", state="AR", broad=1)
    assert h.count("class='mk-view' href='/market/item/") == h.count("class='mk-g mk-card'")


def test_gsa_fields_from_the_fixture_lot(ui):
    s, h = item(ui, "/market/item/gsa-auctions/3-1-QSC-I-27-006-005")
    assert s == 200
    for want in ("Trailer, Utility", "Active", "$25.00", "1</td>", "ESTIMATED $98.00", "$73.00", "Bid on the original site", "https://www.gsaauctions.gov/auctions/preview/378501",
                 "salvage condition", "Inspection and Removal", "Pay by", "10/15", "Remove by", "10/29", "5825 Lee Co Rd 501", "Marianna",
                 "https://www.openstreetmap.org/search?query=", "Illinois Federal Surplus Property", "REDACTED", "id='dt-cd'", "data-end=", "Photo is behind GSA", "dt-status", "sg-reason", "/market/resale", "/market/bid"):
        assert want in h, want
    assert "<iframe" not in h and "<script src='/static/market_detail.js'>" in h and "<script>" not in h and "mailto:" not in h
    assert "days" in h and "hrs" in h                                         # server-rendered countdown fallback
    s, js = item(ui, "/static/market_detail.js")
    assert s == 200 and "dt-cd" in js


def test_unknown_fields_are_labelled(ui):
    md_raw = md.raw_gsa("3-1-QSC-I-27-017-016")
    s, h = item(ui, "/market/item/gsa-auctions/3-1-QSC-I-27-017-016")
    assert s == 200 and md_raw is not None
    assert "UNKNOWN" in h
    s, h404 = item(ui, "/market/item/gsa-auctions/nope")
    assert s == 404 and "No cached listing" in h404


def test_event_page(ui, caches):
    h = get(ui, go=1, source="wooley", broad=1, view="list")
    u = unquote(HREF.findall(h)[0])
    s, body = item(ui, u)
    assert s == 200 and "Auction event" in body and "Lots not available:" in body and "see the auctioneer" in body and "Auctioneer" in body
    assert "Bid on the original site" not in body and "Current bid" not in body


def _c(i, cat, title, dist=None):
    return {"id": i, "title": title, "category": cat, "distance": dist, "bid": None, "city": "X, AR", "source": "GSA Auctions"}


def test_similar_excludes_item_orders_nearest_and_keeps_land_off():
    me = _c("a", "trailers", "Utility trailer", 10)
    pool = [me, _c("b", "trailers", "Far trailer", 90), _c("c", "trailers", "Near trailer", 5), _c("d", "trailers", "Unknown place trailer"),
            _c("e", "trailers", "Five acres of land for sale", 1), _c("f", "tools", "Hammer", 2)]
    h = md._similar(me, pool, NOW)
    assert h.index("Near trailer") < h.index("Far trailer") < h.index("Unknown place trailer")
    assert "Hammer" not in h and "acres of land" not in h and "Utility trailer" not in h
    assert md._similar(_c("z", None, "No category"), pool, NOW).count("<li>") == 0 and "UNKNOWN" in md._similar(_c("z", None, "No category"), pool, NOW)


def test_clean_html_drops_scripts_links_and_attributes():
    h = md.clean_html("<h4 onclick='x'>T</h4><p style='a'>Hi <a href='mailto:a@b.c'>a@b.c</a><script>alert(1)</script><img src=x></p>")
    assert "<script" not in h and "href" not in h and "onclick" not in h and "style" not in h and "<img" not in h and "a@b.c" in h


def test_phone_390_no_horizontal_overflow(ui):
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            pytest.skip("no chrome")
        pg = b.new_page(viewport={"width": 390, "height": 900})
        pg.goto(f"http://127.0.0.1:{ui.port}/market/item/gsa-auctions/3-1-QSC-I-27-006-005")
        assert pg.evaluate("document.scrollingElement.scrollWidth") <= 390
        pg.wait_for_timeout(1300)
        assert "days" in pg.inner_text("#dt-cd") or pg.inner_text("#dt-cd") == "Closed"
        b.close()
