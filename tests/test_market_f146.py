"""F-146: the real Wooley auction-EVENT source on /market, offline. Cache built from lane 02's archived Wooley pages (tests/fixtures/wooley,
copied from 5c1aaa5); no test makes a network request or names a hibid.com URL to fetch."""
from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from mbos_discovery.adapters.wooley_site import WooleySiteAdapter

from operator_ui import market_search as ms, market_sources as msrc
from tests.test_market_f47 import cache, get, ui  # noqa: F401
from tools import refresh_wooley_cache as rw

PAGES = Path(__file__).parent / "fixtures" / "wooley"
AS_OF = datetime(2026, 10, 11, 23, 0, tzinfo=timezone.utc)
NOW = AS_OF + timedelta(hours=1)
BRUCK = "t-j-bruck-estate-heavy-equipment-machinery-auction-perryville-arkansas"


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


def write_cache(path: Path, as_of=AS_OF, **over) -> Path:
    ad = WooleySiteAdapter(PAGES, clock=lambda: as_of)
    res = ad.fetch()
    doc = {"as_of": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"), "requests": 0, "error": None, "records": [r.payload for r in res.records], **over}
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture()
def wcache(tmp_path, monkeypatch):
    p = write_cache(tmp_path / "wooley.json")
    monkeypatch.setenv(msrc.ENV_WOOLEY, str(p))
    return p


def cards(origin="Conway AR"):
    d = ms.load_source("wooley", NOW, ms._origin(origin))
    return d, {c["id"]: c for c in d["cards"]}


def test_card_shape_parity_and_event_fields(cache, wcache):
    d, by = cards()
    want = set(ms.load_gsa(str(cache), NOW)["cards"][0])
    assert d["status"] == "connected" and d["fixture"] is False and len(by) == 2
    b = by[f"wooley:{BRUCK}"]
    assert want <= set(b), want - set(b)
    assert b["kind"] == "auction event" and b["event"] and b["auctioneer"] == "Wooley Auctioneers" and b["source"] == "Wooley Auctioneers"
    assert b["title"].startswith("T.J. Bruck") and b["city"] == "Perryville, AR" and b["closes"] == "2026-10-13" and b["buyer_premium_pct"] == 10.0
    assert b["url"] == f"https://wooleyauctioneers.com/{BRUCK}/" and b["hibid_url"].startswith("https://wooleyauctioneers.hibid.com/catalog/")
    assert {"Vehicle", "Truck", "Equipment"} <= set(b["tags"]) and b["distance"] is not None and 20 < b["distance"] < 80
    assert b["lot_number"] is None and b["current_bid"] is None and b["bid_count"] is None and b["bid"] is None and b["price"] is None


def test_page_shows_unknown_lot_fields_links_and_connected_label(ui, wcache):
    h = get(ui, go=1, source="wooley", broad=1, view="list")
    assert "Wooley Auctioneers: connected (cached file)" in h and "FIXTURE" not in h and "auction events (not lots)" in h
    assert "T.J. Bruck" in h and "AUCTION EVENT" in h and "Buyer premium</span> 10%" in h
    assert "Lot number</span> UNKNOWN" in h and "Current bid</span> UNKNOWN" in h and "Bid count</span> UNKNOWN" in h
    assert f"https://wooleyauctioneers.com/{BRUCK}/" in h and "View and bid on HiBid" in h and "mi from your base" in h
    g = get(ui, go=1, source="wooley", broad=1)
    assert "data-kind='auction-event'" in g and "View and bid on HiBid" in g
    assert "Craigslist: NOT CONNECTED" in h and "eBay: NOT CONNECTED" in h and "Facebook Marketplace: NOT CONNECTED" in h


def test_selector_option_and_all_sources_merge(ui, wcache, cache):
    h = get(ui, go=1, source="all", broad=1)
    assert "Wooley Auctioneers</option>" in h and "T.J. Bruck" in h and "GSA Auctions: connected" in h and "Wooley Auctioneers: connected" in h
    d = msrc.load_source("all", str(cache), NOW, None)
    assert {c["source"] for c in d["cards"]} == {"GSA Auctions", "Wooley Auctioneers"} and d["status"] == "connected" and d["fixture"] is False


def test_all_sources_with_fixture_alerts_only_on_flag(wcache, cache):
    mail = Path(__file__).parent / "fixtures" / "alerts"
    d = msrc.load_source("all", str(cache), NOW, None, str(mail))
    assert {c["source"] for c in d["cards"]} == {"GSA Auctions", "Wooley Auctioneers", "GovDeals", "Public Surplus"}
    assert not any(c.get("fixture") for c in msrc.load_source("all", str(cache), NOW, None)["cards"])


def test_filters_distance_category_keyword_and_price_rule(wcache):
    run = lambda **k: ms.partition(cards()[0]["cards"], ms.parse_query({"base": ["Conway AR"], "broad": ["1"], **{a: [b] for a, b in k.items()}}))  # noqa: E731
    ids = lambda r: sorted(c["title"][:12] for c in r[0] + r[1])  # noqa: E731
    assert len(run()[0]) == 2
    assert len(run(radius="1")[0]) == 0 and run(radius="1")[2]["radius"] >= 1                 # Perryville is tens of miles away
    assert [c["title"] for c in run(keywords="bruck")[0]] == [c["title"] for c in run(keywords="perryville")[0]] and len(run(keywords="bruck")[0]) == 1
    assert len(run(keywords="zzzz")[0]) == 0
    assert any("Bruck" in c["title"] for c in ms.partition(cards()[0]["cards"], ms.parse_query({"base": ["Conway AR"], "cat": ["equipment"]}))[0])
    for k in ({"min_price": "0"}, {"max_price": "100000"}, {"min_price": "10", "max_price": "500"}):       # documented rule: any price filter EXCLUDES events
        r = run(**k)
        assert not r[0] and not r[1] and r[2]["price"] == 2, k
    assert ids(run()) and run(sort="closing")[0][0]["closes"] <= run(sort="closing")[0][-1]["closes"]


def test_state_mode_and_search_now_page_price_hint(ui, wcache):
    assert "T.J. Bruck" in get(ui, go=1, source="wooley", broad=1, loc_mode="state", state="AR")
    h = get(ui, go=1, source="wooley", broad=1, max_price="500")
    assert "T.J. Bruck" not in h and "hidden" in h.lower() and "price" in h.lower() and "excludes events" in h


def test_stale_cache_is_labelled(tmp_path, monkeypatch):
    p = write_cache(tmp_path / "w.json", as_of=AS_OF - timedelta(hours=30))
    monkeypatch.setenv(msrc.ENV_WOOLEY, str(p))
    d = ms.load_source("wooley", NOW)
    assert d["stale"] and d["status"] == "connected" and all(c["stale"] for c in d["cards"])
    from operator_ui import market_source_view as msv
    assert "STALE" in msv.coverage(d)


@pytest.mark.parametrize("content", [None, "not json", "{}", json.dumps({"as_of": "nonsense", "records": []})])
def test_missing_or_unreadable_cache_is_honest_offline(ui, tmp_path, monkeypatch, content):
    p = tmp_path / "w.json"
    if content is not None:
        p.write_text(content)
    monkeypatch.setenv(msrc.ENV_WOOLEY, str(p))
    d = ms.load_source("wooley", NOW)
    assert d["status"] == "offline" and d["cards"] == []
    h = get(ui, go=1, source="wooley", broad=1)
    assert "Wooley Auctioneers: offline" in h and "T.J. Bruck" not in h and "FIXTURE" not in h


def test_failed_refresh_cache_is_offline(tmp_path, monkeypatch):
    p = write_cache(tmp_path / "w.json", error={"kind": "network", "message": "unreachable"}, records=[])
    monkeypatch.setenv(msrc.ENV_WOOLEY, str(p))
    d = ms.load_source("wooley", NOW)
    assert d["status"] == "offline" and "unreachable" in d["message"]


def test_refresh_refuses_without_live_and_makes_no_request(tmp_path, capsys):
    out = tmp_path / "w.json"
    assert rw.main(["--out", str(out)]) == 2 and not out.exists()
    assert "refused" in capsys.readouterr().err


def test_refresh_live_writes_atomically_with_a_stub_adapter(tmp_path):
    out = tmp_path / "var" / "cache" / "w.json"
    ad = WooleySiteAdapter(PAGES, clock=lambda: AS_OF)
    assert rw.refresh(out, ad) == 0
    doc = json.loads(out.read_text())
    assert doc["as_of"] == "2026-10-11T23:00:00Z" and doc["requests"] == 0 and doc["error"] is None and len(doc["records"]) == 2
    assert not list(out.parent.glob(".wooley-*"))
    bad = WooleySiteAdapter(tmp_path / "nowhere", clock=lambda: AS_OF)
    assert rw.refresh(out, bad) == 1 and json.loads(out.read_text()) == doc            # a failed refresh keeps the good cache


def test_no_hibid_request_anywhere():
    import re
    for f in ("tools/refresh_wooley_cache.py", "operator_ui/market_sources.py", "operator_ui/market_source_view.py"):
        src = (Path(__file__).parent.parent / f).read_text()
        assert not re.search(r"(urlopen|requests\.|http\.client|UrllibTransport)\([^)]*hibid", src)
    html = get_card_html()
    assert "<img" not in html and "<script" not in html and "iframe" not in html


def get_card_html() -> str:
    from operator_ui import market_source_view as msv
    from operator_ui.live_demo import link_html
    return msv.event_card({**{"title": "x", "description": "", "closes_at": None, "city": None, "distance": None, "stale": False, "source": "s", "fetched_at": "t", "kind": "k",
                              "url": "https://wooleyauctioneers.com/a/", "hibid_url": "https://wooleyauctioneers.hibid.com/catalog/1"}}, None, None, link_html)
