"""F-152: auto-detected bids (B-27 bid_events over an EmlDirReader, isolated-staging fixture flag only) in the My bids window."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from operator_ui import market_autobids as mba
from operator_ui import market_bids as mb
from operator_ui import market_prefs as mp
from tests.test_market_f47 import cache, get, post, ui  # noqa: F401

MAIL = Path(__file__).parent / "fixtures" / "bid_mail"


@pytest.fixture(autouse=True)
def prefs(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.delenv(mba.ENV_FLAG, raising=False)
    monkeypatch.delenv(mba.ENV_DIR, raising=False)
    return tmp_path / "prefs.json"


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setenv(mba.ENV_FLAG, "1")
    monkeypatch.setenv(mba.ENV_DIR, str(MAIL))


def window(h):
    i = h.index("id='my-bids'")
    return h[i:h.index("</div>", i)]


def test_no_flag_shows_not_connected_note_and_no_items(ui):
    h = get(ui, go=1, keywords="trailer")
    assert "Automatic bid detection is not connected (no mailbox)" in h and "auto-detected from your e-mail" not in h
    import os
    os.environ[mba.ENV_DIR] = str(MAIL)                       # the directory alone, without the flag, is still not connected
    assert mba.mail_dir() is None and "not connected" in get(ui, go=1)


def test_every_event_rendered_with_wording_amount_provenance(ui, on):
    w = window(get(ui, go=1))
    assert "not connected" not in w
    assert w.count("auto-detected from your e-mail") == 5                     # 9 records, 5 distinct listings (latest event headlines, earlier ones listed)
    for word in ("you were OUTBID", "you WON", "you did not win", "auction closed", "you are winning", "bid placed"):
        assert word in w, word
    assert "e-mail Message-ID &lt;syn-gd-3@govdeals.com&gt;" in w
    assert "$1,310.50" in w and "(owner-local, this page only)" in w
    assert "ended (read " in w   # F-153: won/lost/closed rows use the adapter's timestamp; the outbid listing keeps its countdown
    assert "amount not stated" in w
    assert "IMPORTED" in w and "current bid UNKNOWN · your max UNKNOWN" in w
    assert "no source-account access" in w and "next action:" in w and "provenance: e-mail Message-ID" in w


def test_dkim_failed_mail_is_absent(ui, on):
    h = get(ui, go=1)
    assert "9999" not in window(h) and "syn-gd-spoof" not in h.lower()


def test_amounts_only_on_this_page(ui, on):
    h = get(ui, go=1)
    assert "$1,310.50" in window(h) and "$1,310.50" not in h.replace(window(h), "")
    assert not mp.path().exists() or "1310" not in mp.path().read_text()


def test_matching_result_card_is_excluded(ui, on, monkeypatch):
    h = get(ui, go=1, keywords="trailer")
    n = h.count("data-lot=")
    match = re.search(r"data-lot='[^']+'.*?href='(https://www\.gsaauctions\.gov/auctions/preview/\d+)'", h, re.S)
    if not match:
        pytest.skip("dated GSA fixture has no still-open trailer card")
    url = match.group(1)
    rec = {"source": "gsa_auctions", "listing_id": "X-1", "title": "Matched lot", "url": url, "event": "winning", "observed_at": "2026-10-11T20:00:00Z",
           "provenance": {"kind": "email", "message_id": "<m@x>"}, "visibility": "owner_local", "origin": "auto_detected"}
    monkeypatch.setattr(mba, "read_bid_events", lambda r, clock=None: ([rec], []))
    h2 = get(ui, go=1, keywords="trailer")
    assert h2.count("data-lot=") == n - 1 and "1 in My bids" in h2 and "Matched lot" in window(h2)


def test_stop_tracking_persists_and_hides_auto_item(ui, on):
    w = window(get(ui, go=1))
    lot = re.search(r"data-bid='(auto:hibid:[^']+)'", w).group(1)
    r = post(ui, "/market/bid", act="unbid", lot=lot)
    assert r[0] in (302, 303)
    assert lot in json.loads(mp.path().read_text())["auto_stopped"]
    assert lot not in window(get(ui, go=1)) and len(list(MAIL.glob("*.eml"))) == 10      # mail untouched
    mp.act("reset", "")
    assert lot in mp.load()["auto_stopped"]                                              # survives a suggestions reset


def test_auto_urls_normalised():
    assert mba.norm_url("https://WWW.example.com/a/b/") == mba.norm_url("http://example.com/a/b")
    keep, n = mb.exclude([{"id": "i", "url": "https://gsaauctions.gov/x/"}], {"bids": {}}, frozenset({mba.norm_url("https://www.gsaauctions.gov/x")}))
    assert keep == [] and n == 1


def test_f153_ended_rows_and_display_names(ui, on):
    w = window(get(ui, go=1))
    lis = re.findall(r"<li data-bid=.*?</li>", w, re.S)
    ended = [x for x in lis if any(k in x for k in ("you WON", "you did not win", "auction closed"))]
    assert len(ended) == 4
    for x in ended:
        assert "ended (read " in x and "closes in" not in x and "closed (was" not in x
    for name in ("GovDeals", "Public Surplus", "GSA Auctions", "HiBid"):
        assert f"{name} · auto-detected" in w
    for raw in ("govdeals ·", "gsa_auctions ·", "hibid ·", "publicsurplus ·"):
        assert raw not in w
