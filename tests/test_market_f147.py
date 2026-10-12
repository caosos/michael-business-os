"""F-147: 'I bid on this' / My bids window. Owner-reported only; excluded from results; visible under any filter; UNKNOWN where the source has none."""
from __future__ import annotations

import json
import re

import pytest

from operator_ui import market_prefs as mp
from tests.test_market_f47 import cache, get, post, ui  # noqa: F401


@pytest.fixture(autouse=True)
def prefs(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    return tmp_path / "prefs.json"


def first_lot(ui):
    h = get(ui, go=1, keywords="trailer")
    m = re.search(r"data-lot='([^']+)'", h)
    return h, m.group(1)


def mark(ui, lot, **extra):
    r = post(ui, "/market/bid", act="bid", lot=lot, title=extra.pop("title", "Test trailer"), **extra)
    return r


def test_every_card_has_the_control_and_it_is_not_save(ui):
    h, lot = first_lot(ui)
    assert "I bid on this" in h and "data-bidform" in h
    post(ui, "/market/pref", act="save", lot=lot, title="t")
    assert lot not in mp.load()["bids"] and lot in mp.load()["saved"]       # Save never marks a bid


def test_mark_excludes_from_results_with_count_and_unmark_returns(ui):
    h, lot = first_lot(ui)
    n = h.count("data-lot=")
    mark(ui, lot, source="GSA Auctions", closes="2026-10-12", bid="25", bidders="3", url="https://www.gsaauctions.gov/auctions/preview/1", max_bid="90")
    h2 = get(ui, go=1, keywords="trailer")
    assert h2.count("data-lot=") == n - 1 and f"data-lot='{lot}'" not in h2
    assert "1 in My bids" in h2 and f"data-bid='{lot}'" in h2
    post(ui, "/market/bid", act="unbid", lot=lot)
    h3 = get(ui, go=1, keywords="trailer")
    assert f"data-lot='{lot}'" in h3 and "in My bids (left" not in h3 and "My bids (0)" in h3


def test_window_persists_across_restart_and_under_any_filter(ui):
    lot = "gone:1"                                       # not in the current source: the marking-time snapshot is what shows
    mark(ui, lot, source="GSA Auctions", closes="2026-10-12", bid="25", bidders="3")
    assert json.loads(open(mp.path()).read())["bids"][lot]["bidders"] == 3.0       # file on disk = what a restart reloads
    for qs in ({"go": 1, "keywords": "zzzznomatch"}, {"go": 1, "keywords": "trailer", "radius": "1"}, {"go": 1, "source": "alerts"}, {"new": 1}):
        h = get(ui, **qs)
        assert f"data-bid='{lot}'" in h and "My bids (1)" in h and "bids 3" in h and "current bid $25" in h


def test_unknown_fields_and_max_bid_local_and_hostile_escaped(ui):
    mark(ui, "wooley:x1", title="<script>x</script>", source="Wooley Auctioneers", closes_at="2026-10-14T15:00:00Z", max_bid="150")
    h = get(ui, new=1)
    assert "current bid UNKNOWN" in h and "bids UNKNOWN" in h and "<script>x</script>" not in h and "your max: $150" in h and ("closes in" in h or "closed" in h)
    assert "no link" in h
    assert post(ui, "/market/bid", act="bid", lot="a", max_bid="abc")[0] in (200, 303) and "a" not in mp.load()["bids"]


def test_closing_soon_first_and_reset_keeps_bids(ui):
    mark(ui, "b", title="later", closes="2026-12-30")
    mark(ui, "a", title="sooner", closes="2026-11-01")
    mark(ui, "c", title="unknown")
    h = get(ui, new=1)
    assert h.index("sooner") < h.index("later") < h.index("unknown")
    post(ui, "/market/pref", act="reset")
    assert set(mp.load()["bids"]) == {"a", "b", "c"}


def test_csrf_required(ui):
    from tests.test_operator_ui import req
    st = req(ui, "POST", "/market/bid", {"act": "bid", "lot": "z", "title": "t"})[0]
    assert "z" not in mp.load()["bids"] and st in (200, 400, 403)


LONG = "wooley:t-j-bruck-estate-heavy-equipment-machinery-auction-perryville-arkansas"


def test_long_wooley_id_is_not_truncated_and_date_only_close_is_end_of_day_chicago(ui):
    from datetime import datetime, timezone

    from operator_ui import market_bids as mb
    assert len(LONG) > 60
    mark(ui, LONG, source="Wooley Auctioneers", closes="2026-10-14")
    assert LONG in mp.load()["bids"]                                          # full id stored, not cut
    d = mp.load()
    cards = [{"id": LONG, "title": "t"}, {"id": "other", "title": "o"}]
    assert [c["id"] for c in mb.exclude(cards, d)[0]] == ["other"]            # absent from results (both sections use exclude)
    h = get(ui, new=1)
    assert f"data-bid='{LONG}'" in h
    post(ui, "/market/bid", act="unbid", lot=LONG)
    assert LONG not in mp.load()["bids"] and len(mb.exclude(cards, mp.load())[0]) == 2   # back in results
    end = mb._end({"closes": "2026-10-14"})
    assert end.astimezone(timezone.utc) == datetime(2026, 10, 15, 4, 59, 59, tzinfo=timezone.utc)   # 23:59:59 CDT
