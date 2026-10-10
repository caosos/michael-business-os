"""F-47: Michael's Marketplace. GSA results from lane 02's recorded slice via GsaLiveAdapter (cache, no network); saved searches are
Wanted campaigns and survive a reload; demo data never appears; stale, no-photo, escaping, ungrounded comp = WATCH."""

from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from operator_ui import market_search as ms
from operator_ui.server import App, make_handler
from tests.conftest import PIN
from tests.test_operator_ui import req
from tests.test_wanted_f23 import GOV_POLICY, StubStore

FIX = Path(__file__).parent / "fixtures/gsa_live/active-auctions.json"
ASOF = datetime(2026, 10, 10, 0, 19, tzinfo=timezone.utc)
NOW = ASOF + timedelta(minutes=30)


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    p = tmp_path / "gsa.json"
    shutil.copy(FIX, p)
    p.with_suffix(".asof").write_text(ASOF.isoformat())
    monkeypatch.setenv("MBOS_GSA_CACHE", str(p))
    return p


@pytest.fixture()
def ui(tmp_path, cache):
    app = App(StubStore(), operator_pin=PIN, campaigns_file=str(tmp_path / "campaigns.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()


_n = iter(range(10**6))
SEARCH = {"keywords": "trailer", "base": "Conway AR", "radius": "150", "max_price": "500"}


def post(ui, path, **f):
    return req(ui, "POST", path, {"csrf": ui.csrf, "pin": PIN, "nonce": f"nonce{next(_n):08d}", **f})


def get(ui, **qs):
    from urllib.parse import urlencode
    return req(ui, "GET", "/market?" + urlencode(qs))[2]


def test_gsa_result_has_real_link_photo_bid_and_as_of(ui):
    h = get(ui, go=1, keywords="trailer")
    assert "Marianna" in h and "https://www.gsaauctions.gov/auctions/preview/378501" in h
    assert "<img src='https://" in h and "$25.00" in h and "2026-10-12" in h
    assert "GSA Auctions: connected" in h and "2026-10-10T00:19:00+00:00" in h
    assert "buyer premium UNKNOWN" in h and "transport UNKNOWN" in h and "repair UNKNOWN" in h and "RESEARCH NEEDED" in h
    assert "Michael's Marketplace" in h and "Find Deals Now" in h and "+ New Search" in h and "Auctions Closing Soon" in h
    assert "mi from your base" in h                              # Marianna AR is a located place, so distance is grounded


def test_unlocated_place_has_no_invented_distance(ui):
    cards = ms.load_gsa(None, NOW)["cards"]
    known = ms.place_coords.__globals__["AR_PLACES"]
    assert cards and any(c["distance"] is not None for c in cards)
    for c in cards:
        located = c["city"] and c["city"].split(",")[0].lower() in known
        assert (c["distance"] is not None) == bool(located)


def test_save_search_then_reload_survives_and_runs(ui):
    status, loc, _ = post(ui, "/market/save", **SEARCH, exclude="broken", required="utility", title="Trailer hunt")
    assert status == 303 and loc.startswith("/market?msg=Campaign created")
    [rec] = ui.campaigns.all()
    c = rec["doc"]["criteria"]
    assert c["category"] == "marketplace" and c["keywords"] == ["trailer"] and c["max_price_usd"] == 500.0 and c["radius_miles"] == 150.0
    assert c["must_have"] == ["utility"] and "exclude:broken" in c["nice_to_have"] and c["origin"] == "Conway AR"
    assert rec["history"][0]["by"] == "michael"
    h = get(ui)                                                   # a fresh GET = the reload
    assert "Trailer hunt" in h and "ON" in h
    cid = rec["doc"]["campaign_id"]
    run = get(ui, run=cid)
    assert "Marianna" in run and "iPad" not in run
    edit = get(ui, edit=cid)
    assert "value='trailer'" in edit and "value='broken'" in edit


def test_disable_enable_and_edit_use_the_wanted_history(ui):
    post(ui, "/market/save", **SEARCH, title="T")
    cid = ui.campaigns.all()[0]["doc"]["campaign_id"]
    assert post(ui, f"/market/{cid}/pause")[0] == 303
    assert ui.campaigns.get(cid)["doc"]["status"] == "PAUSED" and "Enable" in get(ui)
    post(ui, f"/market/{cid}/resume")
    assert post(ui, f"/market/{cid}/edit", **{**SEARCH, "max_price": "40"}, title="T2")[0] == 303
    rec = ui.campaigns.get(cid)
    assert rec["doc"]["criteria"]["max_price_usd"] == 40.0 and [x["what"].split()[0] for x in rec["history"]] == ["created", "pause", "resume", "edited"]


def test_save_needs_pin_and_a_price(ui):
    s, _, body = req(ui, "POST", "/market/save", {"csrf": ui.csrf, "pin": "wrong", "nonce": "nonce99999999", **SEARCH})
    assert s == 200 and "Not saved" in body and not ui.campaigns.all()
    s, _, body = post(ui, "/market/save", keywords="x")
    assert "Not saved" in body and "Max price" in body and not ui.campaigns.all()


def test_demo_isolation_no_train_or_example_invalid_in_live_results(ui):
    h = get(ui, go=1)
    assert "TRAIN-" not in h and "example.invalid" not in h and "DEMO / TRAINING" not in h
    assert "href='/?demo=1'" in h                                 # demo lives behind a separate sidebar area only


def test_unsupported_source_is_not_connected_never_mock(ui):
    h = get(ui, go=1, source="ebay")
    assert "ebay: not connected" in h and "Marianna" not in h
    assert "fixed-price results" in get(ui, go=1, kind="fixed") and "Marianna" not in get(ui, go=1, kind="fixed")


def test_offline_when_no_cache(ui, monkeypatch, tmp_path):
    monkeypatch.setenv("MBOS_GSA_CACHE", str(tmp_path / "missing.json"))
    h = get(ui, go=1)
    assert "GSA Auctions: offline" in h and "Marianna" not in h


def test_stale_lot_is_flagged(cache):
    d = ms.load_gsa(str(cache), ASOF + timedelta(hours=9))
    assert d["stale"] and d["age_h"] == 9.0 and all(c["stale"] for c in d["cards"])
    assert not ms.load_gsa(str(cache), NOW)["stale"]


def test_no_photo_card_says_so_and_has_no_img():
    from operator_ui import market_view as mv
    c = {**_card(), "image": None}
    h = mv.render_card(c)
    assert "No photo from the seller" in h and "<img" not in h


def _card(**kw):
    return {"id": "1-1", "title": "Thing", "description": "d", "text": "thing d", "url": "https://www.gsaauctions.gov/auctions/preview/1", "image": "https://x.gsa.gov/a.jpg",
            "bid": None, "bidders": None, "closes": "2026-10-12", "city": "Conway, AR", "distance": None, "category": "other", "condition": None,
            "source": "GSA Auctions", "fetched_at": "2026-10-10T00:19:00+00:00", "kind": "auction", "stale": False, "tags": {"required": [], "preferred": []}, **kw}


def test_html_is_escaped_and_bad_links_are_not_links():
    from operator_ui import market_view as mv
    h = mv.render_card(_card(title="<script>alert(1)</script>", description="<img src=x onerror=1>", url="javascript:alert(1)", image="javascript:x",
                             city="<b>x</b>"))
    assert "<script>" not in h and "<img src=x" not in h and "&lt;script&gt;" in h and "href=\"javascript" not in h and "href='javascript" not in h
    assert "No verified live link" in h and "<b>x</b>" not in h


def test_ungrounded_comp_is_watch_never_buy():
    assert ms.decision(_card())[0] == "WATCH" and "RESEARCH NEEDED" in ms.decision(_card())[1]
    for comp in (None, {}, {"kind": "asking", "n": 5}, {"kind": "sold", "n": 0}):
        assert ms.decision(_card(), comp)[0] == "WATCH"
    assert ms.decision(_card(), {"kind": "sold", "n": 3})[0] == "WATCH"


def test_terms_are_tagged_seller_stated_or_inferred_and_exclude_drops(cache):
    cards = ms.load_gsa(str(cache), NOW)["cards"]
    tr = next(c for c in cards if "Trailer" in c["title"])
    got, _ = ms.search(cards, ms.parse_query({"required": ["utility"], "preferred": ["trailer"]}))
    assert [t for t in got if t["id"] == tr["id"]][0]["tags"]["required"] == [("utility", "seller-stated")]
    assert ms.tag_terms({**tr, "text": "x", "category": "trailer"}, ms.parse_query({"preferred": ["trailer"]}))["preferred"] == [("trailer", "inferred")]
    assert not [c for c in ms.search(cards, ms.parse_query({"exclude": ["utility"]}))[0] if c["id"] == tr["id"]]


def test_price_radius_sort_filters(cache):
    cards = ms.load_gsa(str(cache), NOW)["cards"]
    assert all(c["bid"] is None or c["bid"] <= 20 for c in ms.search(cards, ms.parse_query({"max_price": "20"}))[0])
    bids = [c["bid"] for c in ms.search(cards, ms.parse_query({"sort": "bid"}))[0] if c["bid"] is not None]
    assert bids == sorted(bids)
    close = [c["closes"] for c in ms.search(cards, ms.parse_query({"closing_by": "2026-10-12"}))[0]]
    assert close and max(close) <= "2026-10-12"
    assert not [c for c in ms.search(cards, ms.parse_query({"radius": "1"}))[0] if c["distance"] is not None]
    assert ms.parse_query({"max_price": ["abc"], "radius": ["-5"]})["max_price"] is None
