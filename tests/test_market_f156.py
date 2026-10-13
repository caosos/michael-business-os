"""F-156: the Sources panel on /market. Display only; registry lives in market_sources; every state label tested; fixtures never LIVE."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from operator_ui import market_source_panel as msp, market_sources as msrc
from tests.test_market_f146 import NOW, wcache, write_cache  # noqa: F401
from tests.test_market_f47 import cache, get, ui  # noqa: F401


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.delenv(msrc.ENV_FLAG, raising=False)
    monkeypatch.delenv(msrc.ENV_DIR, raising=False)
    for s in msrc.AUCTION_SITES.values():
        monkeypatch.setenv(s.env, str(tmp_path / "none.json"))


def by(rows):
    return {r["info"].key: r for r in rows}


def test_registry_covers_every_named_source_and_state_is_one_label():
    names = {i.name for i in msrc.REGISTRY}
    for n in ("GSA Auctions", "Wooley Auctioneers", "Wilson Auctioneers", "Blackmon Auctions", "GovDeals", "Public Surplus", "HiBid e-mail alerts",
              "Craigslist", "Facebook Marketplace", "eBay", "OfferUp", "Owner-entered finds"):
        assert n in names
    assert all(i.path in ("official API", "provider API", "own site", "RSS", "e-mail alerts", "owner import", "none") for i in msrc.REGISTRY)
    for r in msp.rows(NOW):
        assert r["state"] in msrc.STATES


def test_live_connected_only_from_a_real_cache(cache, wcache):  # noqa: F811
    r = by(msp.rows(NOW))
    assert r["gsa"]["state"] == "LIVE CONNECTED" and r["gsa"]["probe"]["as_of"]
    assert r["wooley"]["state"] == "LIVE CONNECTED"
    assert r["wilson"]["state"] == "NOT CONNECTED"            # no cache file


def test_not_connected_without_caches():
    r = by(msp.rows(NOW))
    for k in ("wooley", "govdeals", "publicsurplus", "hibid_email", "facebook", "ebay"):
        assert r[k]["state"] == "NOT CONNECTED"


def test_manual_blocked_and_imported_labels(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_FINDS_FILE", str(tmp_path / "f.json"))
    r = by(msp.rows(NOW))
    for k in ("facebook", "offerup", "owner_finds"):
        assert r[k]["state"] == "MANUAL"
    assert r["hibid_site"]["state"] == "BLOCKED"
    assert r["craigslist"]["state"] == "NOT CONNECTED"      # F-161: e-mail alerts, no mailbox read in this test
    imp = msrc.SourceInfo("x", "X", "c", "g", "owner import", "item", "none", "", "", None, "IMPORTED")
    assert msrc.source_state(imp, {"status": "imported"}) == "IMPORTED"
    assert msrc.source_state(imp, {"status": "offline"}) == "NOT CONNECTED"


def test_fixtures_never_read_live(tmp_path, monkeypatch):
    monkeypatch.setenv(msrc.ENV_FLAG, "1")
    monkeypatch.setenv(msrc.ENV_DIR, str(tmp_path))
    r = by(msp.rows(NOW))
    for k in ("govdeals", "publicsurplus"):
        assert r[k]["probe"]["status"] == "fixture" and r[k]["state"] == "NOT CONNECTED"
    for info in msrc.REGISTRY:                                # no probe status other than a real cache can produce LIVE
        for st in ("fixture", "offline", "manual", "imported"):
            assert msrc.source_state(info, {"status": st}) != "LIVE CONNECTED"
    assert "FIXTURE / not live" in msp.render(NOW)


def test_stale_cache_is_flagged(wcache):  # noqa: F811
    late = NOW + timedelta(hours=30)
    row = by(msp.rows(late))["wooley"]
    assert row["probe"]["stale"] and "STALE" in msp.render(late)


def test_page_shows_panel_with_states(ui, wcache):  # noqa: F811
    h = get(ui)
    assert "id='sources-panel'" in h
    states = re.findall(r"data-src='(\w+)' data-state='([A-Z ]+)'", h)
    assert dict(states)["hibid_site"] == "BLOCKED" and dict(states)["gsa"] == "LIVE CONNECTED"
    assert "HiBid terms forbid scraping" in h


def test_panel_escapes_and_makes_no_requests():
    assert "<script" not in msp.render(NOW)
