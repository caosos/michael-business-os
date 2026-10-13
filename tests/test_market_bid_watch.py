"""Bid-watch foundation: manual, listing-imported and authenticated-email provenance."""
from __future__ import annotations

import re

import pytest

from operator_ui import market_prefs as mp
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
    h = get(ui, new=1)
    for text in ("County tractor", "GovDeals · MANUAL", "current bid $900", "your max: $1,400", "Inspect hydraulic leak", "original listing"):
        assert text in h
    assert "entered by you; no source-account access" in h


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
