"""Craigslist alert place text (seller-typed, unverified) -> gazetteer town; anything that does not resolve stays UNKNOWN (never local)."""
from operator_ui import market_sources as m


def test_town_spellings_resolve():
    for text, want in (("Warren Arkansas", "Warren"), ("N little rock ar", "North Little Rock"), ("Jax", "Jacksonville"),
                       ("West little Rock", "Little Rock"), ("cabot", "Cabot"), ("Conway", "Conway"), ("bigelow ar", "Bigelow")):
        hit = m._town(text, "AR")
        assert hit and hit[0] == want, text


def test_unknown_and_junk_stay_unknown():
    for text in ("UNKNOWN", "", "CALL 501-557-6154 FOR AVAILABILITY", "Northwest"):
        assert m._town(text, "AR") is None, text


def test_remembered_facebook_only_view_falls_back_to_all(monkeypatch):
    from operator_ui import market_prefs, market_facebook
    monkeypatch.setattr(market_prefs, "load", lambda: {"last": {"source": ["facebook"], "radius": ["30"]}})
    monkeypatch.setattr(market_facebook, "SHOW_HISTORICAL", False)
    assert market_prefs.recall({"source", "radius"}) == {"source": ["all"], "radius": ["30"]}
    monkeypatch.setattr(market_facebook, "SHOW_HISTORICAL", True)
    assert market_prefs.recall({"source", "radius"})["source"] == ["facebook"]


def test_fixed_price_card_without_a_price_renders():
    from datetime import datetime, timezone
    from operator_ui import market_browse as mb
    c = {"id": "craigslist_email:x", "title": "Yard sale", "price": None, "bid": None, "price_type": "fixed", "url": "https://www.craigslist.org/view/d/x/abcdefghij12",
         "source": "Craigslist", "distance": None, "city": None, "state": "AR", "labels": {}, "image": None, "kind": "auction", "fetched_at": "2026-10-14T22:00:00+00:00"}
    html = mb.card(c, lambda: "", datetime(2026, 10, 14, 23, tzinfo=timezone.utc), lambda *_: "")
    assert "Price not stated" in html
