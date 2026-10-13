"""Bid-watch foundation: manual, listing-imported and authenticated-email provenance."""
from __future__ import annotations

import re

import pytest

from operator_ui import market_prefs as mp
from operator_ui import accounts
from tests.test_market_f47 import cache, get, post, ui  # noqa: F401


@pytest.fixture(autouse=True)
def prefs(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


def test_manual_bid_watch_has_required_fields_and_no_account_access(ui):
    status, _, _ = post(ui, "/market/bid", act="add", title="County tractor", source="GovDeals",
                        url="https://www.govdeals.com/asset/123", status="watching", current_bid="900", max_bid="1400",
                        closes_at="2026-10-15T19:00:00-05:00", next_action="Inspect hydraulic leak")
    assert status in (302, 303)
    [record] = mp.load()["bids"].values()
    assert record["origin"] == "MANUAL" and record["provenance"]["kind"] == "owner_entry"
    assert record["provenance"]["source_account_access"] == "NONE"
    assert record["status"] == "watching" and record["bid"] == 900 and record["max_bid"] == 1400
    from tests.test_operator_ui import req

    h = req(ui, "GET", "/market/bids")[2]
    for text in ("County tractor", "GovDeals · MANUAL", "current bid $900", "your max: $1,400", "Inspect hydraulic leak", "original listing"):
        assert text in h
    assert "entered by you; no source-account access" in h


def test_hibid_link_only_add_is_canonical_stable_and_activates_nav_count(ui):
    link = "https://wooleyauctioneers.hibid.com/lot/324232426/countyline-32-ton-towable-log-splitter?ref=lot-list"
    status, _, _ = post(ui, "/market/bid", act="add", url=link,
                        closes_at="2026-10-13T18:10:00-05:00")
    assert status in (302, 303)
    bids = mp.load()["bids"]
    assert list(bids) == ["hibid:wooleyauctioneers.hibid.com:324232426"]
    record = next(iter(bids.values()))
    assert record["title"] == "CountyLine 32 Ton Towable Log Splitter"
    assert record["source"] == "Wooley Auctioneers / HiBid"
    assert record["url"] == "https://wooleyauctioneers.hibid.com/lot/324232426/countyline-32-ton-towable-log-splitter"
    from tests.test_operator_ui import req

    h = req(ui, "GET", "/market/bids")[2]
    assert "id='my-bids-nav'" in h and "My bids (1)" in h
    assert "data-end='2026-10-13T23:10:00Z'" in h
    assert "src='/static/market_bids.js'" in h


def test_link_only_unknown_close_is_truthful_and_does_not_fetch(ui):
    link = "https://wooleyauctioneers.hibid.com/lot/324232426/countyline-32-ton-towable-log-splitter?tracking=x"
    status, location, _ = post(ui, "/market/bid", act="add", url=link)
    assert status in (302, 303) and "Add the closing time" in location
    record = next(iter(mp.load()["bids"].values()))
    assert record["closes_at"] == "" and record["bid"] is None
    assert "closes UNKNOWN" in get(ui, new=1)


def test_non_hibid_link_still_requires_manual_title_and_source(ui):
    from operator_ui import market_bids as mb

    with pytest.raises(ValueError, match="title is required"):
        mb.act("add", {"url": "https://example.com/auction/1"}, "2026-10-13T05:00:00+00:00")


def test_imported_card_is_snapshot_not_source_account_connection(ui):
    h = get(ui, go=1, keywords="trailer")
    form = re.search(r"<form method='post' action='/market/bid' class='mk-pref' data-bidform>(.*?)</form>", h, re.S).group(1)
    fields = dict(re.findall(r"name='([^']+)' value='([^']*)'", form))
    status, _, _ = post(ui, "/market/bid", act="bid", **{k: v for k, v in fields.items() if k not in ("csrf", "nonce", "act")})
    assert status in (302, 303)
    [record] = mp.load()["bids"].values()
    assert record["origin"] == "IMPORTED" and record["status"] == "bid placed"
    assert record["provenance"]["kind"] == "listing_snapshot" and record["provenance"]["source_account_access"] == "NONE"
    assert "IMPORTED · listing feed snapshot; no source-account access" in get(ui, new=1)


def test_watch_update_changes_status_current_max_close_and_next_action(ui):
    post(ui, "/market/bid", act="add", title="Loader", source="Public Surplus", url="https://publicsurplus.com/sms/auction/view?auc=1")
    lot = next(iter(mp.load()["bids"]))
    status, _, _ = post(ui, "/market/bid", act="update", lot=lot, status="outbid", current_bid="1250", max_bid="1600",
                        closes_at="2026-10-16T12:30:00-05:00", next_action="Verify buyer premium")
    assert status in (302, 303)
    r = mp.load()["bids"][lot]
    assert (r["status"], r["bid"], r["max_bid"], r["next_action"]) == ("outbid", 1250, 1600, "Verify buyer premium")
    h = get(ui, new=1)
    assert "status <b>outbid</b>" in h and "current bid $1,250" in h and "your max: $1,600" in h


def test_manual_watch_rejects_bad_link_status_and_amount(ui):
    from operator_ui import market_bids as mb

    for extra in ({"url": "javascript:alert(1)"}, {"status": "maybe"}, {"current_bid": "lots"}):
        f = {"act": "add", "title": "X", "source": "Y", "url": "https://example.com/1", **extra}
        with pytest.raises(ValueError):
            mb.act("add", f, "2026-10-13T05:00:00+00:00")
        assert not mp.load()["bids"]


def test_my_bids_has_a_direct_expanded_page_and_returns_there(ui):
    post(ui, "/market/bid", act="add", title="Equipment trailer", source="HiBid",
         url="https://hibid.com/lot/1", current_bid="450", max_bid="700",
         closes_at="2026-10-15T19:00:00-05:00", next_action="Inspect frame")
    from tests.test_operator_ui import req

    h = req(ui, "GET", "/market/bids")[2]
    assert "<h1 class='pagehead'>My Bids</h1>" in h
    assert "id='my-bids' open" in h
    assert "<span class='badge bid-origin'>MANUAL</span>" in h
    assert "EMAIL CONNECTED — NOT ACTIVE" in h
    assert "requires a proven mailbox connection" in h
    assert "Update status, amounts, closing or next action" in h
    assert "name='return_to' value='/market/bids'" in h
    lot = next(iter(mp.load()["bids"]))
    status, location, _ = post(ui, "/market/bid", act="update", lot=lot, status="winning",
                              current_bid="500", max_bid="700", closes_at="2026-10-15T19:00:00-05:00",
                              next_action="Check at 6:45", return_to="/market/bids")
    assert status == 303 and location.startswith("/market/bids?msg=")


def test_bid_records_are_isolated_by_verified_request_account(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "owner.json"))
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(tmp_path / "accounts"))
    first = accounts.google_account("google-user-one", "one@example.com")
    second = accounts.google_account("google-user-two", "two@example.com")
    form = {"title": "Loader", "source": "GovDeals", "url": "https://govdeals.com/asset/1"}
    with accounts.use(first):
        mb = __import__("operator_ui.market_bids", fromlist=["act"])
        mb.act("add", form, "2026-10-13T06:00:00+00:00")
        first_path = mp.path()
        assert len(mp.load()["bids"]) == 1
    with accounts.use(second):
        second_path = mp.path()
        assert mp.load()["bids"] == {}
        assert second_path != first_path
    assert not (tmp_path / "owner.json").exists()
