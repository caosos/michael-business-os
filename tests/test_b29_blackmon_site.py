"""B-29: Blackmon Auctions EVENTS from the archived real RSS feed + one real event page (docs/receipts/b29-blackmon-archive, scrubbed;
sha256 in ORIGINAL_SHA256.txt). Offline only: no test makes a network request, and no proxibid.com URL is ever fetched."""
import re
import shutil
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mbos_discovery import auctions as A
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters import blackmon_site as B
from mbos_discovery.http import CallbackTransport, HttpResponse, TransportError
from mbos_discovery.policy import Disposition, policy_for

ARCHIVE = Path(__file__).resolve().parents[1] / "docs" / "receipts" / "b29-blackmon-archive"
BANK = "bank-repo-auction-logging-equip-trucks-trailers"
NOW = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
P = SearchProfile("blackmon", "flip")
FEED = (ARCHIVE / "auctions.rss").read_text()
PAGE = (ARCHIVE / "event-bank-repo.html").read_text()


@pytest.fixture
def pages(tmp_path):
    shutil.copy(ARCHIVE / "auctions.rss", tmp_path / "auctions.rss")
    shutil.copy(ARCHIVE / "event-bank-repo.html", tmp_path / f"event-{BANK}.html")
    return tmp_path


def _ad(pages, **kw):
    return B.BlackmonSiteAdapter(pages, clock=lambda: NOW, **kw)


def _bank(pages):
    ad = _ad(pages)
    res = ad.fetch(P)
    return ad, res, ad.lot(res.records[0].payload, NOW)


def test_feed_has_29_items_with_publish_dates_that_are_not_event_dates():
    items = B.parse_feed(FEED)
    assert len(items) == 29 and items[0]["slug"] == BANK and items[0]["published_at"].startswith("Fri, 09 Oct 2026")
    assert all(i["url"].startswith("https://www.blackmonauctions.com/auctions/") for i in items)
    assert {i["title"] for i in items if "Stardust" in i["title"]} == {"“Stardust Ranch” Equipment & Structures Auction"}


def test_event_page_dates_location_premium_and_proxibid_text(pages):
    ad, res, e = _bank(pages)
    assert len(res.records) == 1 and ad.summary["requests"] == 0 and ad.summary["feed_items"] == 29
    assert ad.summary["skipped"] == {"past": 0, "no_page": 28, "no_date": 0}
    assert e.get("begins_at") == "2026-10-13T09:00:00-05:00" and e.get("closes_at") == "2026-10-13T23:30:00-05:00"
    assert e.fields["begins_at"].basis == "INFERENCE" and e.fields["closes_at"].basis == "INFERENCE"
    assert e.get("buyer_premium_pct") == 14.0 and e.fields["buyer_premium_pct"].basis == "FACT"
    assert e.get("sale_type") == "Public Online Auction" and e.get("auctioneer") == "Blackmon Auctions"
    assert e.get("published_at").startswith("Fri, 09 Oct 2026")
    assert e.get("proxibid_url") == "https://www.proxibid.com/Blackmon-Auctions/BANK-REPO-AUCTION-LOGGING-EQUIP-TRUCKS-TRAILERS/event-catalog/301594"
    assert e.get("rules_url").endswith("/auctions/" + BANK)
    assert e.fields["closes_at"].source == e.get("rules_url") and e.fields["closes_at"].observed_at == "2026-10-12T04:00:00Z"


def test_multiple_locations_is_unknown_with_reason(pages):
    _, _, e = _bank(pages)
    assert e.get("location") == A.UNKNOWN and e.get("address") == A.UNKNOWN and e.distance_miles is None
    assert "Multiple Locations" in e.get("location_unknown_reason")


def test_lot_level_and_unstated_fields_are_unknown(pages):
    _, _, e = _bank(pages)
    for name in (*B.LOT_LEVEL_UNKNOWN, "sales_tax_pct", "preview", "pickup"):
        assert e.fields[name].value == A.UNKNOWN and e.fields[name].basis == "UNKNOWN"


def test_parse_local_and_missing_dates():
    assert B.parse_local("2026-10-13", "9:00 AM") == "2026-10-13T09:00:00-05:00"
    assert B.parse_local("2026-12-01", "11:30 PM") == "2026-12-01T23:30:00-06:00"
    assert B.parse_local("", "9:00 AM") is None and B.parse_local("2026-10-13", "TBD") is None
    p = {"slug": "x", "title": "T", "url": "https://www.blackmonauctions.com/auctions/x", "start_date": "2026-10-13"}
    lot = B.BlackmonSiteAdapter().lot(p, NOW)
    assert lot.get("begins_at") == A.UNKNOWN and "no parseable date" in lot.get("date_unknown_reason")


def test_address_with_city_state_zip_is_located():
    p = {"slug": "x", "title": "T", "url": "https://www.blackmonauctions.com/auctions/x", "location_text": "Blackmon Yard, 1 Main St, Lonoke, AR 72086"}
    lot = B.BlackmonSiteAdapter().lot(p, NOW)
    assert lot.get("location") == {"city": "Lonoke", "state": "AR", "zip": "72086"}


def test_past_events_are_dropped_and_today_is_kept(pages):
    late = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)         # Oct 14 Chicago: the Oct 13 event is past
    ad = B.BlackmonSiteAdapter(pages, clock=lambda: late)
    assert ad.fetch(P).records == [] and ad.summary["skipped"]["past"] == 1
    evening = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)       # still Oct 13 in Chicago
    assert len(B.BlackmonSiteAdapter(pages, clock=lambda: evening).fetch(P).records) == 1


def test_repeat_parse_is_byte_identical(pages):
    a, b = _ad(pages).fetch(P).records, _ad(pages).fetch(P).records
    assert [r.raw_bytes for r in a] == [r.raw_bytes for r in b]


def test_normalize_item_shape(pages):
    ad, res, _ = _bank(pages)
    n = ad.normalize(res.records[0].payload, NOW)
    assert n.url.endswith("/auctions/" + BANK) and n.opportunity_kind == "auction_lot" and n.source_listing_id == BANK
    assert n.normalized["ends_at"] == "2026-10-14T04:30:00Z"
    assert n.normalized["price"] == {"currency": "USD"} and n.normalized["images"] == [] and "location" not in n.normalized
    assert "needs_review" in n.normalized["flags"] and n.normalized["counterparty"]["name"] == "Blackmon Auctions"


def test_policy_and_house_registered_proxibid_forbidden():
    assert policy_for("blackmon_auctions").disposition is Disposition.ALLOWED
    assert policy_for("proxibid").disposition is Disposition.FORBIDDEN
    assert "blackmon_auctions" in A.HOUSES


# ---- live path: OFF by default, proxibid refused, feed + feed-item pages only, 10 s apart, hourly, honest errors -------------
def test_live_flag_off_by_default_and_no_request_made(pages):
    ct = CallbackTransport(lambda *a: pytest.fail("network used with live off"))
    ad = B.BlackmonSiteAdapter(pages, transport=ct, clock=lambda: NOW)
    assert ad.live is False and ad.fetch(P).ok and ct.calls == []
    res = B.BlackmonSiteAdapter(None, transport=ct).fetch(P)
    assert res.error and res.error.kind == "config" and ct.calls == []


@pytest.mark.parametrize("url", ["https://blackmon.proxibid.com/x", "https://proxibid.com/y", "https://www.proxibid.com/Blackmon-Auctions/E/event-catalog/1"])
def test_adapter_refuses_any_proxibid_fetch(url):
    ct = CallbackTransport(lambda *a: HttpResponse(200, b""))
    ad = B.BlackmonSiteAdapter(live=True, transport=ct, sleep=lambda s: None)
    with pytest.raises(B.ProxibidRefused):
        ad._get(url)
    for other in ("https://example.com/", "https://www.blackmonauctions.com/admin", "http://www.blackmonauctions.com/auctions/x"):
        body, err = ad._get(other)
        assert body is None and err.kind == "config"
    assert ct.calls == []


def _live(handler=None, **kw):
    t = {"now": 1000.0}
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        t["now"] += s

    def default(method, url, headers, body):
        if "format=rss" in url:
            return HttpResponse(200, FEED.encode())
        return HttpResponse(200, PAGE.encode()) if url.endswith("/" + BANK) else HttpResponse(200, re.sub(r"2026-10-13", "2026-09-01", PAGE).encode())

    def h(method, url, headers, body):
        t["now"] += 0.5
        return (handler or default)(method, url, headers, body)
    ct = CallbackTransport(h)
    return B.BlackmonSiteAdapter(None, live=True, transport=ct, clock=lambda: NOW, sleep=sleep, monotonic=lambda: t["now"], **kw), ct, sleeps, t


def test_live_fetches_feed_then_only_feed_item_pages_ten_seconds_apart_never_proxibid():
    ad, ct, sleeps, _ = _live()
    res = ad.fetch(P)
    urls = [u for _, u in ct.calls]
    assert res.ok and res.requests_made == 30 and urls[0] == B.FEED_URL and set(urls[1:]) == {i["url"] for i in B.parse_feed(FEED)}
    assert [r.payload["slug"] for r in res.records] == [BANK] and ad.summary["skipped"]["past"] == 28
    assert all("proxibid" not in u for u in urls) and len(sleeps) == 29 and all(abs(s - 9.5) < 1e-9 for s in sleeps)
    assert ad.crawl_delay == 10.0 and _live(crawl_delay=1.0)[0].crawl_delay == 10.0


def test_anonymous_user_agent():
    seen = []
    ad, _, _, _ = _live(lambda m, u, hd, b: (seen.append(hd["User-Agent"]), HttpResponse(200, FEED.encode() if "rss" in u else PAGE.encode()))[1])
    ad.fetch(P)
    assert set(seen) == {B.USER_AGENT} and "@" not in B.USER_AGENT


def test_at_most_one_live_run_per_hour():
    ad, ct, _, t = _live(min_run_interval=60.0)                       # cannot be configured below an hour
    assert ad.fetch(P).ok
    n = len(ct.calls)
    again = ad.fetch(P)
    assert again.error and again.error.kind == "config" and again.records == [] and len(ct.calls) == n
    t["now"] += 3600
    assert ad.fetch(P).ok and len(ct.calls) == 2 * n


def test_http_errors_timeouts_and_block_are_honest():
    res = _live(lambda *a: HttpResponse(503, b"down"))[0].fetch(P)
    assert res.error and res.error.kind == "http" and res.error.status == 503 and res.records == []

    def boom(*a):
        raise TransportError("timed out")
    res = _live(boom)[0].fetch(P)
    assert res.error and res.error.kind == "network" and "offline" in res.error.message

    ad, ct, _, _ = _live(lambda m, u, hd, b: HttpResponse(200, FEED.encode()) if "rss" in u else HttpResponse(429, b"slow down"))
    res = ad.fetch(P)
    assert res.error.kind == "rate_limited" and res.error.is_block and len(ct.calls) == 2      # stops at the first block


def test_event_page_failure_skips_that_event_only():
    def h(m, u, hd, b):
        return HttpResponse(200, FEED.encode()) if "rss" in u else HttpResponse(404, b"gone") if u.endswith("mckoin-farms-auction") else HttpResponse(200, PAGE.encode())
    ad, _, _, _ = _live(h)
    res = ad.fetch(P)
    assert res.ok and ad.summary["skipped"]["no_page"] == 1 and len(res.records) == 28


def test_no_proxibid_request_anywhere_in_code():
    src = Path(B.__file__).read_text()
    assert "proxibid" not in B.FEED_URL and B.SITE_HOST == "www.blackmonauctions.com"
    for needle in ("urlopen(", "requests.", "httpx", "http.client", "socket"):
        assert needle not in src


def test_offline_guarantee(monkeypatch, pages):
    def deny(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", deny)
    assert _ad(pages).fetch(P).ok


# ---- B-33: locations (Squarespace address lines) and multi-day dates -------------------------------------------------------------
def _page(name):
    return (ARCHIVE / f"event-{name}.html").read_text()


def _lot(page, slug="x"):
    ad = B.BlackmonSiteAdapter(None, clock=lambda: NOW)
    return ad.lot({"slug": slug, "title": "T", "url": f"https://www.blackmonauctions.com/auctions/{slug}", **B.parse_event_page(page)}, NOW)


def test_b33_lonoke_ar_address_parsed():
    e = _lot(_page("arkansas-contractors-auction-oct-2026"))
    assert e.get("location") == {"city": "Lonoke", "state": "AR", "zip": "72086"}
    assert e.get("address") == "425 Blackmon Road, Lonoke, AR, 72086" and e.get("location_unknown_reason") == A.UNKNOWN


def test_b33_west_plains_missouri_full_state_name():
    e = _lot(_page("crown-manufacturing-liquidation-auction"))
    assert e.get("location") == {"city": "West Plains", "state": "MO", "zip": "65775"}
    assert e.get("address") == "6468 U.S. 63, West Plains, Missouri, 65775" and e.distance_miles is None


@pytest.mark.parametrize("name", ["union-pacific-railroad-surplus-equipment-auction-oct-2026", "bank-repo"])
def test_b33_multiple_locations_stays_unknown_with_reason(name):
    e = _lot(_page(name))
    assert e.get("location") == A.UNKNOWN and e.get("address") == A.UNKNOWN
    assert "Multiple Locations" in e.get("location_unknown_reason")


def test_b33_multi_day_is_inference_in_chicago_time():
    e = _lot(_page("arkansas-contractors-auction-oct-2026"))
    assert e.get("begins_at") == "2026-10-27T08:00:00-05:00" and e.get("closes_at") == "2026-10-29T09:00:00-05:00"
    assert e.fields["begins_at"].basis == e.fields["closes_at"].basis == "INFERENCE"


def test_b33_multi_day_without_times_is_whole_days():
    page = re.sub(r'<span class="eventitem-meta-time">.*?</span>', "", _page("arkansas-contractors-auction-oct-2026"), flags=re.S)
    e = _lot(page)
    assert e.get("begins_at") == "2026-10-27T00:00:00-05:00" and e.get("closes_at") == "2026-10-29T23:59:00-05:00"
    assert e.fields["begins_at"].basis == e.fields["closes_at"].basis == "INFERENCE"


def test_b33_no_proxibid_request(pages):
    ad = _ad(pages)
    ad.fetch(P)
    assert not any(B.is_proxibid(str(x)) for x in ad.http.log)
