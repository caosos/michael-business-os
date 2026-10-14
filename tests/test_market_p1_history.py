"""P1-01: auction history in My Bids. Append-only observations on the existing bid record (market_prefs `bids`), shown in time order with
price and bid-count changes, closing extensions, gaps, the verified final price and the change after the owner's last bid.

REGRESSION EXAMPLE — TEST FIXTURE ONLY (not live source data): Wooley Auctioneers lot 34, CountyLine 32-Ton Towable Log Splitter,
Perryville AR. The owner reported three observations ($800/33 bids winning, close 6:10 PM CT; $975/37 bids outbid, close extended to
6:11 PM; final $975/37 bids closed). The four bids between observations 1 and 2 are not known and must never be invented. The calendar
date of the close was not given; the 2026-10-11 used here is a test date only. Offline: no network."""
from __future__ import annotations

import re
import socket

import pytest

from operator_ui import accounts, bid_history as bh, bid_state_watch as bsw, market_bids as mb, market_prefs as mp
from tests.test_market_f47 import cache, get, post, ui  # noqa: F401

LOT_URL = "https://wooleyauctioneers.hibid.com/lot/34/countyline-32-ton-towable-log-splitter"
T0 = "2026-10-11T22:50:00+00:00"       # entry times of this test, not claimed auction times


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.setenv("MBOS_BID_STATE_FILE", str(tmp_path / "bid_state.json"))
    real = socket.create_connection

    def no_net(addr, *a, **k):
        if addr[0] not in ("127.0.0.1", "localhost"):
            raise AssertionError(f"network used: {addr}")
        return real(addr, *a, **k)
    monkeypatch.setattr(socket, "create_connection", no_net)


def page(ui) -> str:
    from tests.test_operator_ui import req
    return req(ui, "GET", "/market/bids")[2]


def wooley(act=lambda a, f: mb.act(a, f, T0)) -> str:
    act("add", {"url": LOT_URL, "location": "Perryville, AR"})
    lot = next(iter(mp.load()["bids"]))
    act("observe", {"lot": lot, "high_bid": "800", "bid_count": "33", "owner_max": "800", "status": "winning",
                    "closes_at": "2026-10-11T18:10", "note": "HiBid lot page"})
    act("observe", {"lot": lot, "high_bid": "975", "bid_count": "37", "status": "outbid", "closes_at": "2026-10-11T18:11", "note": "HiBid lot page"})
    act("observe", {"lot": lot, "high_bid": "975", "bid_count": "37", "status": "closed", "final": "1", "note": "HiBid lot page, bidding closed"})
    return lot


def test_wooley_lot_34_keeps_all_three_observations_and_the_175_increase():
    lot = wooley()
    r = mp.load()["bids"][lot]
    obs = r["observations"]
    assert [(o["high_bid"], o["bid_count"], o["status"], o["final"]) for o in obs] == [
        (800, 33, "winning", False), (975, 37, "outbid", False), (975, 37, "closed", True)]
    assert len({o["obs_id"] for o in obs}) == 3
    s = bh.summary(r, bh.timeline(r))
    assert s["after_mine"] == 175 and s["last_mine"]["high_bid"] == 800 and s["end_price"] == 975
    assert s["first_close"].startswith("2026-10-11T18:10:00-05:00") and s["last_close"].startswith("2026-10-11T18:11:00-05:00")
    assert r["final_price"] == 975 and r["status"] == "closed" and r["bid"] == 975 and r["bidders"] == 37 and r["max_bid"] == 800
    assert r["title"] == "CountyLine 32 Ton Towable Log Splitter" and r["location"] == "Perryville, AR"


def test_history_view_shows_changes_gaps_extension_and_never_invents_the_four_bids(ui):
    wooley()
    h = page(ui)
    hist = h[h.index("class='bid-history'"):]
    for text in ("History (3 observations)", "Perryville, AR", "Your max bid</dt><dd>$800", "Oct 11, 6:10 PM CT", "Oct 11, 6:11 PM CT",
                 "closing extended 1m: Oct 11, 6:10 PM CT → Oct 11, 6:11 PM CT", "high bid <b>$975</b> (+$175)", "37 bids (+4 bids)",
                 "FINAL PRICE (verified)", "$975 (verified, entered by you)", "data-after-mine='175.0'", "+$175 (from $800 while you led to $975 final)",
                 "high bid +$175; +4 bids.", "Individual bids, their times and bidders in this gap were not recorded", "HiBid lot page"):
        assert text in hist, text
    assert hist.count("data-gap='1'") == 2
    assert hist.count("data-class='MANUAL'") == 3 and "CONNECTED" not in re.sub(r"connected source evidence", "", hist).replace("EMAIL CONNECTED", "")
    for amount in ("$825", "$850", "$900", "$925", "$950"):        # no intermediate bid is made up
        assert amount not in hist
    assert hist.index("(+$175)") < hist.index("FINAL PRICE")       # chronological


def test_outbid_keeps_the_watch_active_and_counted():
    lot = wooley(lambda a, f: mb.act(a, f, T0) if f.get("final") is None else None)
    r = mp.load()["bids"][lot]
    assert r["status"] == "outbid" and len(r["observations"]) == 2
    assert mb.nav_summary(__import__("datetime").datetime(2026, 10, 11, 23, 0, tzinfo=__import__("datetime").timezone.utc))["active"] == 1


def test_history_survives_close_update_and_remarking():
    lot = wooley()
    mb.act("update", {"lot": lot, "status": "lost", "current_bid": "975", "max_bid": "800", "closes_at": "2026-10-11T18:11:00-05:00"}, T0)
    r = mp.load()["bids"][lot]
    assert len(r["observations"]) == 4 and r["observations"][-1]["status"] == "lost" and r["observations"][-1]["kind"] == "watch_update"
    mb.act("bid", {"lot": lot, "title": r["title"], "source": r["source"], "url": r["url"]}, T0)
    assert len(mp.load()["bids"][lot]["observations"]) == 4


def test_update_form_appends_instead_of_overwriting():
    mb.act("add", {"url": LOT_URL, "current_bid": "500", "closes_at": "2026-10-11T18:10:00-05:00"}, T0)
    lot = next(iter(mp.load()["bids"]))
    mb.act("update", {"lot": lot, "status": "outbid", "current_bid": "650", "closes_at": "2026-10-11T18:12:00-05:00"}, "2026-10-11T23:05:00+00:00")
    obs = mp.load()["bids"][lot]["observations"]
    assert [o["high_bid"] for o in obs] == [500, 650] and [o["closes_at"][11:16] for o in obs] == ["18:10", "18:12"]
    assert obs[0]["observed_basis"] == "entry time"


def test_backdated_entry_is_inserted_in_order_and_does_not_replace_current_values():
    lot = wooley()
    mb.act("observe", {"lot": lot, "high_bid": "600", "bid_count": "20", "observed_at": "2026-10-11T12:00", "note": "screenshot"}, T0)
    r = mp.load()["bids"][lot]
    assert r["bid"] == 975 and r["bidders"] == 37 and len(r["observations"]) == 4
    tl = bh.timeline(r)
    assert tl[0]["high_bid"] == 600 and tl[0]["observed_basis"] == "stated"


def test_existing_record_without_history_is_preserved_as_its_baseline():
    d = mp.load()
    d["bids"]["gsa:1"] = {"title": "Old truck", "source": "GSA Auctions", "url": "https://gsaauctions.gov/x", "closes": "", "closes_at": "2026-10-20T15:00:00-05:00",
                          "bid": 1200.0, "bidders": 5, "fetched_at": "2026-10-10T12:00:00+00:00", "marked_at": "2026-10-10T12:05:00+00:00", "max_bid": 2000,
                          "status": "bid placed", "origin": "IMPORTED", "provenance": {"kind": "listing_snapshot", "observed_at": "2026-10-10T12:00:00+00:00"}}
    mp._store(d)
    mb.act("observe", {"lot": "gsa:1", "high_bid": "1300", "bid_count": "6"}, T0)
    obs = mp.load()["bids"]["gsa:1"]["observations"]
    assert [(o["high_bid"], o["evidence_class"]) for o in obs] == [(1200.0, "SNAPSHOT"), (1300, "MANUAL")]
    assert obs[0]["observed_at"] == "2026-10-10T12:00:00+00:00" and obs[0]["observed_basis"] == "stated"


def test_connected_receipts_are_shown_apart_from_manual_entries(ui):
    lot = wooley()
    bsw.BidWatchStore().apply(bsw.BidObservation(listing_id=lot, source="HiBid", title="Log splitter", url=LOT_URL, state="OUTBID",
                                                 observed_at="2026-10-11T23:10:30+00:00", evidence_kind="AUTHENTICATED_EMAIL",
                                                 evidence_id="msg-1@test", current_bid="975", adapter="test_fixture"))
    hist = page(ui)
    assert "History (4 observations)" in hist and hist.count("data-class='CONNECTED'") == 1 and hist.count("data-class='MANUAL'") == 3
    assert "connected source evidence" in hist


def test_observation_validation():
    lot = wooley()
    for bad in ({}, {"high_bid": "lots"}, {"bid_count": "3.5"}, {"final": "1"}, {"closes_at": "tomorrow", "high_bid": "1"}, {"status": "maybe", "high_bid": "1"}):
        with pytest.raises(ValueError):
            mb.act("observe", {"lot": lot, **bad}, T0)
    with pytest.raises(ValueError):
        mb.act("observe", {"lot": "nope", "high_bid": "1"}, T0)
    assert len(mp.load()["bids"][lot]["observations"]) == 3


def test_post_route_adds_an_observation_and_returns_to_my_bids(ui):
    lot = wooley()
    status, location, _ = post(ui, "/market/bid", act="observe", lot=lot, high_bid="980", return_to="/market/bids")
    assert status == 303 and location.startswith("/market/bids?msg=Observation added")
    assert len(mp.load()["bids"][lot]["observations"]) == 4


def test_history_is_isolated_per_account(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(tmp_path / "accounts"))
    one = accounts.google_account("google-user-one", "one@example.com")
    two = accounts.google_account("google-user-two", "two@example.com")
    with accounts.use(one):
        lot = wooley()
        assert len(mp.load()["bids"][lot]["observations"]) == 3
        assert bsw.store_path() != mp.path() and bsw.store_path().name == "bid_state.json"
    with accounts.use(two):
        assert mp.load()["bids"] == {}
        with pytest.raises(ValueError):
            mb.act("observe", {"lot": lot, "high_bid": "1"}, T0)
    assert not (tmp_path / "prefs.json").exists()
