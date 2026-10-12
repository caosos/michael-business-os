"""F-161: e-mail alert listings (GovDeals, Public Surplus, Craigslist) on /market from the local alert-mail cache written by tools/refresh_alert_mail.py.
Offline: the cache is built from the scrubbed .eml fixtures; no mailbox is contacted."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from operator_ui import market_search as ms, market_sources as msrc, market_source_panel as msp
from tests.test_market_f47 import cache, get, req, ui  # noqa: F401

MAIL = Path(__file__).parent / "fixtures" / "alerts"
NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
AS_OF = "2026-10-13T17:00:00+00:00"


def write_cache(path: Path, files=None, **over) -> Path:
    msgs = [p.read_text(encoding="utf-8") for p in sorted(MAIL.glob("*.eml")) if files is None or p.name in files]
    path.write_text(json.dumps({"as_of": AS_OF, "mailbox_read": True, "fixture": False, "messages": msgs, **over}), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.delenv(msrc.ENV_FLAG, raising=False)
    monkeypatch.delenv(msrc.ENV_DIR, raising=False)
    monkeypatch.setenv(msrc.ENV_ALERTS, str(tmp_path / "alert-mail.json"))


def test_no_cache_is_not_connected_for_all_three():
    for s in msrc.ALERT_SOURCES:
        d = ms.load_source(s, NOW)
        assert d["status"] == "not_connected" and d["cards"] == []
    assert "craigslist" in msrc.ALERT_SOURCES


def test_real_read_with_items_is_connected_and_cards_match_gsa_shape(cache, tmp_path):
    write_cache(tmp_path / "alert-mail.json")
    want = set(ms.load_gsa(str(cache), NOW)["cards"][0])
    for s in msrc.ALERT_SOURCES:
        d = ms.load_source(s, NOW, ms._origin("Conway AR"))
        assert d["status"] == "connected" and d["fixture"] is False and d["cards"], s
        for c in d["cards"]:
            assert want <= set(c), want - set(c)
            assert c["fixture"] is False and c["url"].startswith("https://")


def test_craigslist_card_fields_and_unknown_distance_is_never_local(tmp_path):
    write_cache(tmp_path / "alert-mail.json")
    cl = {c["id"].split(":")[-1]: c for c in ms.load_source("craigslist", NOW, ms._origin("Conway AR"))["cards"]}
    t = cl["7712345001"]
    assert t["source"] == "Craigslist" and t["price"] == 650.0 and t["bid"] is None and t["price_type"] == "fixed"
    assert t["url"] == "https://littlerock.craigslist.org/tla/d/conway-utility-trailer-5x10/7712345001.html"
    assert t["state"] == "AR" and t["distance"] is not None and t["distance"] < 5
    assert "Asking price $650.00" in t["labels"]["opening_text"]
    nop = cl["7712345002"]
    assert nop["price"] is None and "not stated" in nop["labels"]["opening_text"]
    ms_cards = [c for c in ms.load_source("craigslist", NOW, ms._origin("Conway AR"))["cards"] if c["distance"] is None]
    assert ms_cards                                                 # a town the gazetteer cannot place keeps distance None


def test_dedupe_across_repeated_alerts(tmp_path):
    write_cache(tmp_path / "alert-mail.json")
    ids = [c["id"] for c in ms.load_source("craigslist", NOW)["cards"]]
    assert len(ids) == len(set(ids)) == 5                           # postings repeated across alerts appear once; the spoof adds none
    allc = ms.load_source("all", NOW, None)
    assert len({c["url"] for c in allc["cards"]}) == len(allc["cards"])


def test_spoofed_mail_never_shown(tmp_path):
    write_cache(tmp_path / "alert-mail.json", files={"03-spoof.eml"})
    d = ms.load_source("craigslist", NOW)
    assert d["cards"] == [] and d["status"] == "waiting"


def test_waiting_state_is_honest(tmp_path):
    write_cache(tmp_path / "alert-mail.json", files={"01-govdeals.eml"})
    cl = ms.load_source("craigslist", NOW)
    assert cl["status"] == "waiting" and "waiting for alerts" in cl["message"]
    gd = ms.load_source("govdeals", NOW)
    assert gd["status"] == "connected"
    info = {i.key: i for i in msrc.REGISTRY}
    assert msrc.source_state(info["craigslist"], msrc.probe(info["craigslist"], NOW)) == "CONNECTED, WAITING FOR ALERTS"
    assert msrc.source_state(info["govdeals"], msrc.probe(info["govdeals"], NOW)) == "LIVE CONNECTED"
    assert msrc.source_state(info["publicsurplus"], msrc.probe(info["publicsurplus"], NOW)) == "CONNECTED, WAITING FOR ALERTS"


def test_flagged_fixture_cache_or_unflagged_read_is_never_connected(tmp_path):
    for over in ({"fixture": True}, {"mailbox_read": False}):
        write_cache(tmp_path / "alert-mail.json", **over)
        d = ms.load_source("govdeals", NOW)
        assert d["status"] == "fixture" and d["fixture"] is True and all(c["fixture"] for c in d["cards"])
        info = {i.key: i for i in msrc.REGISTRY}["govdeals"]
        assert msrc.source_state(info, msrc.probe(info, NOW)) == "NOT CONNECTED"


def test_malformed_cache_is_not_connected(tmp_path):
    (tmp_path / "alert-mail.json").write_text("{not json")
    assert ms.load_source("govdeals", NOW)["status"] == "not_connected"
    (tmp_path / "alert-mail.json").write_text(json.dumps({"as_of": AS_OF, "messages": [1]}))
    assert ms.load_source("govdeals", NOW)["status"] == "not_connected"


def test_page_shows_alert_listing_with_original_link_and_honest_panel(ui, tmp_path):
    write_cache(tmp_path / "alert-mail.json", files={"01-littlerock-fayar.eml", "01-govdeals.eml"})
    h = get(ui, go=1, source="craigslist", broad=1, base="Conway AR", radius="150", view="list")
    assert "https://littlerock.craigslist.org/tla/d/conway-utility-trailer-5x10/7712345001.html" in h
    assert "id='fixture-banner'" not in h
    assert "Craigslist: connected (mailbox read, cached)" in h
    allp = get(ui, go=1, source="all", broad=1, base="Conway AR", radius="150")
    assert "data-src='craigslist'" in allp and "connected" in allp
    panel = msp.render(NOW)
    assert "data-src='craigslist' data-state='LIVE CONNECTED'" in panel
    assert "data-src='publicsurplus' data-state='CONNECTED, WAITING FOR ALERTS'" in panel


def test_page_waiting_and_not_connected_and_fixture_banner(ui, tmp_path, monkeypatch):
    h = get(ui, go=1, source="craigslist", broad=1)
    assert "not connected" in h.lower() and "7712345001" not in h
    write_cache(tmp_path / "alert-mail.json", files={"01-govdeals.eml"})
    assert "connected, waiting for alerts" in get(ui, go=1, source="craigslist", broad=1)
    monkeypatch.setenv(msrc.ENV_FLAG, "1")
    monkeypatch.setenv(msrc.ENV_DIR, str(MAIL))
    fx = get(ui, go=1, source="craigslist", broad=1, base="Conway AR", radius="150")
    assert "id='fixture-banner'" in fx and "FIXTURE / not live" in fx


def test_filters_and_counts_include_new_source(ui, tmp_path):
    write_cache(tmp_path / "alert-mail.json")
    h = get(ui, go=1, source="all", broad=1, base="Conway AR", radius="150", keywords="trailer")
    assert "7712345001" in h or "conway-utility-trailer" in h
    only = get(ui, go=1, source="craigslist", broad=1, base="Conway AR", radius="150", max_price="700")
    assert "conway-utility-trailer" in only and "springdale-dump-trailer" not in only


def _tool():
    spec = importlib.util.spec_from_file_location("refresh_alert_mail", Path(__file__).parent.parent / "tools" / "refresh_alert_mail.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["refresh_alert_mail"] = m
    spec.loader.exec_module(m)
    return m


class Reader:
    def __init__(self, msgs=None, exc=None):
        self.m, self.exc = msgs or [], exc

    def messages(self, since):
        if self.exc:
            raise self.exc
        return iter(self.m)


def test_refresh_tool_keeps_only_alert_senders_and_marks_a_real_read(tmp_path):
    t = _tool()
    c = tmp_path / "c.json"
    msgs = [p.read_bytes() for p in sorted(MAIL.glob("*.eml"))]
    out = t.refresh(Reader(msgs), NOW, c, "DealSniffer/Alerts")
    doc = json.loads(c.read_text())
    assert out["result"] == "refreshed" and doc["mailbox_read"] is True and doc["fixture"] is False
    assert 0 < len(doc["messages"]) < len(msgs)                      # the newsletter / spoofs are dropped
    assert msrc.read_alert_cache(str(c)) is not None


def test_refresh_tool_failure_keeps_old_cache_and_no_config_touches_nothing(tmp_path, monkeypatch, capsys):
    t = _tool()
    c = tmp_path / "c.json"
    c.write_text('{"keep": 1}')
    out = t.refresh(Reader(exc=PermissionError("live mailbox access not enabled")), NOW, c)
    assert out["result"] == "failed" and c.read_text() == '{"keep": 1}'
    for k in ("MBOS_ALERT_IMAP_HOST", "MBOS_ALERT_IMAP_USER", "MBOS_ALERT_IMAP_PASSWORD_ENV"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(t, "off", lambda: False)
    assert t.main([]) == 0 and "not_configured" in capsys.readouterr().out
