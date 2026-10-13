"""P0-06: a listing whose distance cannot be measured is never shown inside a distance radius.

Found in the P0 browser acceptance (2026-10-13): with Conway AR and a 10-mile radius, Facebook listings from
'Hot Springs National Park, AR' (about 50 miles away, a town name the offline gazetteer does not know) were shown as
results marked 'distance UNKNOWN'. They now leave the grid, the page says how many were left out, and choosing Any
radius (or By State mode) still shows them. Offline: fixture caches only, no network."""
from __future__ import annotations

import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlencode

import pytest

from operator_ui import market_search as ms, market_sources as msrc
from tests.test_market_f47 import cache, req, ui  # noqa: F401

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


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


def get(ui, **qs):
    return req(ui, "GET", "/market?" + urlencode(qs, doseq=True))[2]


def total(h: str) -> int:
    return int(re.search(r"id='result-count' class='mk-count'>([\d,]+) results? found", h).group(1).replace(",", ""))


def fb(ident: str, title: str, city: str, distance):
    return {"id": f"facebook:{ident}", "title": title, "description": "", "text": title.lower(), "url": f"https://www.facebook.com/marketplace/item/{ident}/",
            "image": None, "bid": 300.0, "price": 300.0, "price_type": "fixed", "bidders": None, "closes": None, "city": city, "state": "AR",
            "zip": None, "distance": distance, "category": "other", "condition": None, "labels": {}, "source": "Facebook Marketplace",
            "source_key": "facebook", "fetched_at": NOW.isoformat(), "kind": "fixed", "stale": False, "fixture": False, "posted": None}


@pytest.fixture()
def two_towns(ui, cache, monkeypatch):
    loaded = ms.load_gsa(str(cache), NOW, ms._origin("Conway AR"))
    near = fb("101", "PZQNEAR utility trailer", "Conway, AR", 2.0)
    unknown = fb("202", "PZQFAR utility trailer", "Hot Springs National Park, AR", None)
    data = {**loaded, "cards": [near, unknown], "in_file": 2, "in_scope": 2}
    monkeypatch.setattr(ms, "load_source", lambda *args, **kwargs: data)
    return near, unknown


def test_unknown_distance_listing_is_not_shown_inside_a_radius(ui, two_towns):
    h = get(ui, go=1, base="Conway AR", radius="10", loc_mode="distance", source="all", cat="all", keywords="pzq")
    assert "PZQNEAR" in h
    assert "PZQFAR" not in h                      # was rendered as a result marked 'distance UNKNOWN'
    assert total(h) == 1
    assert "id='location-unknown'" in h and "1 listing with an unknown location left out: the 10-mile radius cannot be checked" in h


def test_unknown_distance_listing_returns_without_a_radius(ui, two_towns):
    h = get(ui, go=1, base="Conway AR", radius="", loc_mode="distance", source="all", cat="all", keywords="pzq")
    assert "PZQNEAR" in h and "PZQFAR" in h
    assert "id='location-unknown'" not in h


def test_by_state_mode_without_radius_keeps_the_unknown_distance_listing(ui, two_towns):
    h = get(ui, go=1, base="Conway AR", radius="10", loc_mode="state", state="AR", source="all", cat="all", keywords="pzq")
    assert "PZQNEAR" in h and "PZQFAR" in h
    assert "id='location-unknown'" not in h


def test_radius_applies_matches_the_partition_rule():
    assert ms.radius_applies({"radius": 10.0, "loc_mode": "distance"})
    assert not ms.radius_applies({"radius": None, "loc_mode": "distance"})
    assert not ms.radius_applies({"radius": 10.0, "loc_mode": "state"})
    assert ms.radius_applies({"radius": 10.0, "loc_mode": "state", "also_radius": True})
