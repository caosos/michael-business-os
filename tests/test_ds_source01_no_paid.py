"""DS-SOURCE-01: no path can send a paid-provider request (owner direction, 2026-10-13).

Every outbound connection, urlopen and http.client request is intercepted. Only the loopback test server may be reached; anything
else, and any Bright Data URL, is recorded and refused. The tests then drive every entry point (page load, Search, Enter, saved-search
Run, all sources, Facebook selected, reload, direct backend and client calls) WITH Bright Data credentials configured, and assert that
zero paid requests were attempted, that the historical cache is read but never written, and that it is labelled as a cache.
Deterministic fixtures only; nothing here reaches a network."""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from operator_ui import market_facebook as fb, market_search as ms, market_sources as msrc, market_source_panel as msp
from tests.test_market_f47 import cache, get, post, ui  # noqa: F401

AS_OF = "2026-10-12T22:15:00+00:00"          # the historical cache's retrieval time (test data)
NOW = datetime(2026, 10, 13, 23, 0, tzinfo=timezone.utc)
WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "deploy-dealsniffer-elitedesk.yml"


@pytest.fixture()
def attempts(monkeypatch):
    """Record and refuse every non-loopback connection and every paid-provider URL, at three layers."""
    seen: list[str] = []
    real_connect = socket.create_connection

    def connect(addr, *a, **k):
        if addr[0] not in ("127.0.0.1", "localhost", "::1"):
            seen.append(f"socket:{addr[0]}")
            raise AssertionError(f"network used: {addr}")
        return real_connect(addr, *a, **k)

    def urlopen(req, *a, **k):
        seen.append(f"urlopen:{getattr(req, 'full_url', req)}")
        raise AssertionError("urlopen used")

    real_request = http.client.HTTPConnection.request

    def request(self, method, url, *a, **k):
        if self.host not in ("127.0.0.1", "localhost", "::1"):
            seen.append(f"http:{self.host}{url}")
            raise AssertionError("http.client used")
        return real_request(self, method, url, *a, **k)

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(fb, "urlopen", urlopen)
    monkeypatch.setattr(http.client.HTTPConnection, "request", request)
    return seen


@pytest.fixture()
def fbcache(tmp_path, monkeypatch):
    """A historical Facebook cache, with Bright Data credentials configured in BOTH the environment and a key file."""
    rows = [{"url": f"https://www.facebook.com/marketplace/item/9{n}/", "title": f"QZHIST utility trailer {n}", "price": 400 + n,
             "location": {"name": "Conway, AR 72032", "latitude": 35.0887, "longitude": -92.4421},
             "images": [{"url": f"https://scontent.example/{n}.jpg"}]} for n in range(3)]
    q = {"keyword": "trailer", "city": "72032", "radius": 30}
    doc = {"as_of": AS_OF, "query": q, "records": rows, "shards": {"k": {"as_of": AS_OF, "query": q, "records": rows}}}
    p = tmp_path / "facebook-marketplace.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("MBOS_FACEBOOK_CACHE", str(p))
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "configured-test-key")
    monkeypatch.setenv("BRIGHTDATA_TOKEN", "configured-test-token")
    key = tmp_path / "BRIGHTDATA_API_KEY"
    key.write_text("file-test-key\n", encoding="utf-8")
    monkeypatch.setattr(fb, "API_KEY_FILE", key)
    monkeypatch.setattr(fb, "TOKEN_FILE", key)
    return p, p.read_bytes(), p.stat().st_mtime_ns


class Spy:
    """An injected provider client. It must never be asked for anything."""
    calls: list = []

    def __getattr__(self, name):
        def call(*a, **k):
            Spy.calls.append(name)
            raise AssertionError(f"provider client used: {name}")
        return call


def unchanged(fbcache):
    p, before, mtime = fbcache
    assert p.read_bytes() == before and p.stat().st_mtime_ns == mtime
    assert not fb._pending_path(p).exists()


def test_every_marketplace_entry_point_sends_zero_paid_requests(ui, fbcache, attempts):
    pages = {
        "initial load": get(ui),
        "Search button (go=1)": get(ui, go=1, keywords="qzhist", source="all", cat="all", radius="50"),
        "Enter in the keyword box (no go)": get(ui, keywords="trailer", source="all", cat="all", radius="50"),
        "search all sources": get(ui, go=1, source="all", cat="all"),
        "Facebook selected": get(ui, go=1, source="facebook", cat="all", radius="50"),
        "Facebook selected, reload": get(ui, go=1, source="facebook", cat="all", radius="50"),
        "plain reload": get(ui),
    }
    status, _, _ = post(ui, "/market/save", keywords="qzhist", base="Conway AR", radius="50", max_price="5000", title="History check")
    assert status == 303
    cid = ui.campaigns.all()[0]["doc"]["campaign_id"]
    pages["saved search Run"] = get(ui, run=cid)
    assert attempts == [] and Spy.calls == []
    unchanged(fbcache)
    for name, h in pages.items():
        assert "facebook-refresh-pending" not in h, name
    fb_page = pages["Facebook selected"]
    assert "QZHIST utility trailer" in fb_page                                    # cached listings still usable
    assert "historical cache · retrieval off" in fb_page                         # the source picker label
    assert fb_page.count("Facebook Marketplace · cached 2026-10-12") == 3          # each card says it is a cache, with its retrieval date
    assert re.search(r"name='source' value='facebook'(?![^>]*disabled)", fb_page)    # still selectable


def test_direct_backend_refresh_and_injected_client_are_denied(fbcache, attempts):
    Spy.calls = []
    d = fb.load(NOW, keyword="trailer", city="72032", radius=30, refresh=True, client=Spy())
    assert d["historical"] and d["in_scope"] == 3 and "does not use paid listing providers" in d["message"]
    for q in ({"_facebook_refresh": True, "source": "facebook", "keywords": "trailer"}, {"_facebook_refresh": True, "source": "all"}):
        for source in ("facebook", "all"):
            msrc.load_source(source, None, NOW, ms._origin("Conway AR"), query=q)
    assert fb.probe(NOW)["historical"] is True
    assert attempts == [] and Spy.calls == []
    unchanged(fbcache)


def test_direct_paid_client_and_transport_refuse_before_any_request(attempts):
    sent = []
    with pytest.raises(fb.PaidProviderDenied):
        fb.BrightDataClient("configured-test-key", request=lambda *a: sent.append(a) or (200, {}, b"[]"))
    raw = object.__new__(fb.BrightDataClient)                                     # an instance that skipped __init__
    raw._token, raw._request, raw._sleep, raw.max_polls, raw.poll_seconds = "k", (lambda *a: sent.append(a) or (200, {}, b"[]")), (lambda s: None), 1, 0
    for call in (lambda: raw.search("trailer", "72032", 30), lambda: raw.search_many(fb.DENSITY_TERMS, "72032", 30),
                 lambda: raw.resume("snap_123"), lambda: raw._call("GET", fb.API + "/progress/x")):
        with pytest.raises(fb.PaidProviderDenied):
            call()
    with pytest.raises(fb.PaidProviderDenied):
        fb._urllib("POST", fb.API + "/scrape", {}, b"{}", 5)
    assert sent == [] and attempts == []
    assert fb.PAID_PROVIDER_REQUESTS == "DENIED"


def test_configured_credentials_do_not_authorize_anything(fbcache, attempts, monkeypatch):
    assert fb.token() == "configured-test-key"
    for flag in ("MBOS_BRIGHTDATA_ENABLE", "MBOS_ALLOW_PAID_PROVIDERS", "MBOS_BRIGHTDATA_FACEBOOK_DATASET"):
        monkeypatch.setenv(flag, "1")
    d = fb.load(NOW, refresh=True)
    assert d["credential_configured"] is True and d["historical"] is True
    with pytest.raises(fb.PaidProviderDenied):
        fb.BrightDataClient(fb.token())
    assert attempts == []
    unchanged(fbcache)


def test_coverage_line_names_the_cache_and_its_age(fbcache):
    from operator_ui import market_source_view as msv
    d = msrc.load_source("all", None, NOW, ms._origin("Conway AR"))
    html = msv.coverage(d)
    assert "Facebook Marketplace: HISTORICAL CACHE (not connected)" in html and "retrieved 2026-10-12 22:15 UTC (24.8 h ago)" in html
    assert "fresh retrieval is off: no paid provider" in html


def test_historical_cache_keeps_source_time_and_age_and_is_never_live(fbcache):
    d = fb.load(NOW)
    assert d["as_of"] == AS_OF and d["age_h"] == pytest.approx(24.8, abs=0.1) and d["stale"] is True
    assert {c["source"] for c in d["cards"]} == {"Facebook Marketplace"} and all(c["url"].startswith("https://www.facebook.com/") for c in d["cards"])
    assert all(c["fetched_at"] == AS_OF for c in d["cards"]) and all(c["image"] for c in d["cards"])
    info = next(i for i in msrc.REGISTRY if i.key == "facebook")
    row = {"info": info, "probe": msrc.probe(info, NOW), "state": msrc.source_state(info, msrc.probe(info, NOW))}
    assert row["state"] == "NOT CONNECTED" and msp.display_kind(row) == "historical"
    assert "HISTORICAL CACHE retrieved 2026-10-12 22:15 UTC" in msp._fresh(row["probe"])
    unchanged(fbcache)


def test_no_cache_says_so_without_offering_a_paid_search(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_FACEBOOK_CACHE", str(tmp_path / "missing.json"))
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "configured-test-key")
    d = fb.load(NOW, refresh=True)
    assert d["status"] == "offline" and "does not use paid listing providers" in d["message"]
    assert "press Search" not in msp._fresh(fb.probe(NOW))


def test_deploy_workflow_has_no_paid_provider_or_owner_prefs_overwrite_path():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "refresh=True" not in text and "api.brightdata.com" not in text
    for url in re.findall(r"http://127\.0\.0\.1:8766/market\?[^'\" ]+", text):
        if "go=1" in url:
            assert re.search(r"source=(?!facebook|all)\w+", url) and "source=facebook" not in url and "source=all" not in url, url
    assert "PRE_TEST_PREFS" not in text                                           # never copy an old snapshot over live bids/filters
    assert "paid_provider_requests=DENIED" in text


def test_card_without_a_usable_photo_says_why():
    """S2: GSA image links need a GSA login (HTTP 401), so the card says so instead of showing nothing; other sources say UNKNOWN."""
    from operator_ui import market_browse as mbr, market_view as mv
    base = {"id": "3-1-X-1", "title": "Trailer", "url": "https://www.gsaauctions.gov/auctions/preview/1", "bid": None, "bidders": None,
            "closes": "2026-10-20", "city": "Conway, AR", "state": "AR", "zip": "72032", "distance": 2.0, "source": "GSA Auctions",
            "source_key": "gsa", "kind": "auction", "fetched_at": AS_OF, "stale": False, "labels": {}, "category": "trailers"}
    tok = lambda: ""  # noqa: E731
    gsa = mbr.card({**base, "image": "https://www.ppms.gov/gw/auction/ppms/api/v1/auction/image/1.jpg"}, tok, NOW, mv.pref_buttons)
    assert "Photo is behind GSA&#x27;s login" in gsa and "<img" not in gsa
    none = mbr.card({**base, "image": None, "source": "Wooley Auctioneers", "source_key": "wooley"}, tok, NOW, mv.pref_buttons)
    assert "Photo: UNKNOWN (the source gave none)" in none
