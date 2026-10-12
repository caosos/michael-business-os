"""F-149: the generalized auction-house events source (Wooley + Wilson + Blackmon) on /market, offline, from lane 02's archived pages (0a71a9d). No network."""
from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from mbos_discovery.adapters.blackmon_site import BlackmonSiteAdapter
from mbos_discovery.adapters.wilson_site import WilsonSiteAdapter
from mbos_discovery.adapters.wooley_site import WooleySiteAdapter

from operator_ui import market_search as ms, market_source_view as msv, market_sources as msrc
from tests.test_market_f47 import cache, get, ui  # noqa: F401
from tools import refresh_auction_events as rae, refresh_wooley_cache as rw

FIX = Path(__file__).parent / "fixtures"
AS_OF = datetime(2026, 10, 11, 23, 0, tzinfo=timezone.utc)
NOW = AS_OF + timedelta(hours=1)
BM_AS_OF = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)   # lane 02 B-29 test clock: the archived event date is still upcoming


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


def write(path: Path, ad) -> Path:
    path.write_text(json.dumps({"as_of": "2026-10-11T23:00:00Z", "requests": 0, "error": None, "records": [r.payload for r in ad.fetch().records]}))
    return path


@pytest.fixture()
def caches(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_WOOLEY_CACHE", str(write(tmp_path / "w.json", WooleySiteAdapter(FIX / "wooley", clock=lambda: AS_OF))))
    monkeypatch.setenv("MBOS_WILSON_CACHE", str(write(tmp_path / "i.json", WilsonSiteAdapter(FIX / "wilson", clock=lambda: AS_OF))))
    monkeypatch.setenv("MBOS_BLACKMON_CACHE", str(write(tmp_path / "b.json", BlackmonSiteAdapter(FIX / "blackmon", clock=lambda: BM_AS_OF))))


def test_registry_and_local_time():
    assert set(msrc.AUCTION_SITES) == {"wooley", "wilson", "blackmon"}
    assert msrc.local_when("2026-10-13T18:00:00-05:00") == "Tue Oct 13, 6:00 PM CDT"
    assert msrc.local_when("2026-10-13T23:00:00Z") == "Tue Oct 13, 6:00 PM CDT"
    assert msrc.local_when("2026-12-01T12:00:00Z") == "Tue Dec 1, 6:00 AM CST"
    assert msrc.local_when("2026-10-13") == "Tue Oct 13 (date only)" and msrc.local_when("junk") is None and msrc.local_when(None) is None


def test_wilson_cards_same_shape_unknown_lot_fields_human_link(caches, cache):
    d = ms.load_source("wilson", NOW, ms._origin("Conway AR"))
    gsa = set(ms.load_gsa(str(cache), NOW)["cards"][0])
    assert d["status"] == "connected" and d["fixture"] is False and len(d["cards"]) == 17
    for c in d["cards"]:
        assert gsa <= set(c) and c["event"] and c["source"] == "Wilson Auctioneers" and c["id"].startswith("wilson:")
        assert c["lot_number"] is None and c["current_bid"] is None and c["bid_count"] is None and c["bid"] is None and c["price"] is None
        assert c["platform"] == "BidWrangler" and c["url"].startswith("https://wilsonauctioneers.com/")
    online = next(c for c in d["cards"] if c["closes_at"])
    assert online["closes_local"].endswith("CDT") and online["left"]
    live = next(c for c in d["cards"] if not c["closes_at"])
    assert live["begins_local"].endswith("CDT") and "no end time" in msv.when_label(live)


def test_page_lists_each_house_all_houses_and_all_sources(ui, caches, cache):
    h = get(ui, go=1, source="auctions", broad=1, view="list")
    assert "All auction houses</option>" in h and "Wilson Auctioneers</option>" in h and "Wooley Auctioneers</option>" in h
    assert "Wilson Auctioneers: connected (cached file)" in h and "Wooley Auctioneers: connected (cached file)" in h and "T.J. Bruck" in h and "AUCTION EVENT" in h
    assert "Tue Oct 13, 6:00 PM CDT" in h and "Lot number</span> UNKNOWN" in h and "FIXTURE" not in h
    a = get(ui, go=1, source="all", broad=1)
    assert "Wilson Auctioneers: connected" in a and "GSA Auctions: connected" in a
    g = get(ui, go=1, source="auctions", broad=1)
    assert "data-row='auction events'" in g and "View and bid on" in g
    w = get(ui, go=1, source="wilson", broad=1, view="list")
    assert "T.J. Bruck" not in w and "Wilson Auctioneers" in w


def test_no_cache_for_one_house_is_honest_offline(ui, tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_WOOLEY_CACHE", str(write(tmp_path / "w.json", WooleySiteAdapter(FIX / "wooley", clock=lambda: AS_OF))))
    monkeypatch.setenv("MBOS_WILSON_CACHE", str(tmp_path / "missing.json"))
    h = get(ui, go=1, source="auctions", broad=1)
    assert "Wilson Auctioneers: offline" in h and "Wooley Auctioneers: connected" in h


def test_refresh_refuses_without_live_and_alias(tmp_path, capsys):
    out = tmp_path / "x.json"
    assert rae.main([]) == 2 and rae.main(["--only", "wilson", "--out", str(out)]) == 2 and rw.main(["--out", str(out)]) == 2 and not out.exists()
    assert rae.main(["--live", "--out", str(out)]) == 2
    assert "refused" in capsys.readouterr().err


def test_refresh_stub_writes_one_cache_per_house_and_respects_wilson_hourly_cap(tmp_path):
    w, i = tmp_path / "w.json", tmp_path / "i.json"
    assert rae.refresh(msrc.AUCTION_SITES["wooley"], w, WooleySiteAdapter(FIX / "wooley", clock=lambda: AS_OF)) == 0
    assert rae.refresh(msrc.AUCTION_SITES["wilson"], i, WilsonSiteAdapter(FIX / "wilson", clock=lambda: AS_OF)) == 0
    assert len(json.loads(w.read_text())["records"]) == 2 and len(json.loads(i.read_text())["records"]) == 17
    # a live Wilson run inside the hour is skipped before any adapter (and so any request) is built
    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("adapter built")
    site = msrc.AuctionSite("wilson", "Wilson Auctioneers", "X", "i.json", Boom, "bidwrangler_url", "BidWrangler", 3600.0)
    assert rae.refresh(site, i, None, now=AS_OF + timedelta(minutes=10)) == 0


def test_no_platform_request_anywhere():
    import re
    for f in ("tools/refresh_auction_events.py", "operator_ui/market_sources.py", "operator_ui/market_source_view.py"):
        src = (Path(__file__).parent.parent / f).read_text()
        assert not re.search(r"(urlopen|requests\.|http\.client|UrllibTransport)\([^)]*(hibid|bidwrangler|proxibid)", src)


def test_blackmon_cards_proxibid_link_for_human_only(caches, cache):
    d = ms.load_source("blackmon", NOW, ms._origin("Conway AR"))
    assert d["status"] == "connected" and d["fixture"] is False and d["cards"]
    for c in d["cards"]:
        assert c["event"] and c["source"] == "Blackmon Auctions" and c["id"].startswith("blackmon:")
        assert c["lot_number"] is None and c["current_bid"] is None and c["bid_count"] is None and c["price"] is None
        assert c["platform"] == "Proxibid" and c["url"].startswith("https://www.blackmonauctions.com/")
        assert "proxibid.com" in (c["platform_url"] or "")
    h = msv._platform(d["cards"][0])
    assert "View and bid on Proxibid" in h and "nofollow" in h


def test_page_includes_blackmon_in_all_houses_and_all_sources(ui, caches, cache):
    h = get(ui, go=1, source="auctions", broad=1, view="list")
    assert "Blackmon Auctions</option>" in h and "Blackmon Auctions: connected (cached file)" in h and "View and bid on Proxibid" in h
    a = get(ui, go=1, source="all", broad=1)
    assert "Blackmon Auctions: connected" in a
    assert "Census 2023 ZIP and place gazetteer" in a and "limited coverage" not in a


def test_blackmon_refresh_refuses_without_live_and_is_hourly_capped(tmp_path):
    out = tmp_path / "b.json"
    assert rae.main(["--only", "blackmon", "--out", str(out)]) == 2 and not out.exists()
    site = msrc.AUCTION_SITES["blackmon"]
    assert site.min_interval_s == 3600.0 and site.env == "MBOS_BLACKMON_CACHE" and site.platform_field == "proxibid_url"
    assert rae.refresh(site, out, BlackmonSiteAdapter(FIX / "blackmon", clock=lambda: BM_AS_OF)) == 0
    doc = json.loads(out.read_text())
    assert doc["requests"] == 0 and doc["records"]

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("adapter built")
    capped = msrc.AuctionSite("blackmon", "Blackmon Auctions", "X", "b.json", Boom, "proxibid_url", "Proxibid", 3600.0)
    assert rae.refresh(capped, out, None, now=BM_AS_OF + timedelta(minutes=10)) == 0
