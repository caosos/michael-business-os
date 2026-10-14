"""S7: 'Ending within' N hours/days filter on /market. Offline fixture data only."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest

from operator_ui import market_browse as mbr, market_prefs as mp, market_search as ms
from tests.test_market_f47 import cache, req, ui  # noqa: F401

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)      # 10:00 AM Central


def lot(i, closes_at=None, closes=None):
    return {"id": f"gsa:{i}", "title": f"QZEND lot {i}", "closes_at": closes_at, "closes": closes}


def test_ending_ok_windows_and_unknowns():
    in3h = lot(1, (NOW + timedelta(hours=3)).isoformat())
    in30h = lot(2, (NOW + timedelta(hours=30)).isoformat())
    past = lot(3, (NOW - timedelta(minutes=1)).isoformat())
    today = lot(4, closes="2026-10-14")                                  # date only = 11:59 PM Central = 13 h 59 m away
    none = lot(5)
    assert [mbr.ending_ok(c, "6h", NOW) for c in (in3h, in30h, past, today, none)] == [True, False, False, False, False]
    assert [mbr.ending_ok(c, "1d", NOW) for c in (in3h, in30h, past, today, none)] == [True, False, False, True, False]
    assert [mbr.ending_ok(c, "2d", NOW) for c in (in3h, in30h, past, today, none)] == [True, True, False, True, False]
    assert all(mbr.ending_ok(c, "", NOW) for c in (in3h, past, none))       # not set: nothing is filtered


def test_parse_accepts_only_known_windows():
    assert ms.parse_query({"ending_within": ["12h"]})["ending_within"] == "12h"
    assert ms.parse_query({"ending_within": ["99h"]})["ending_within"] == ""


@pytest.fixture(autouse=True)
def prefs(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


def page(ui, **qs):
    return req(ui, "GET", "/market?" + urlencode(qs, doseq=True))[2]


def total(h):
    return int(re.search(r"id='result-count' class='mk-count'>([\d,]+) results? found", h).group(1).replace(",", ""))


def test_page_filter_shrinks_results_keeps_the_choice_in_links_and_remembers_it(ui):
    base = dict(source="gsa", base="Conway AR", radius="", cat="all", broad="1")
    every = total(page(ui, **base))
    h = page(ui, **base, ending_within="7d")
    assert "id='sec-ending'" in h and "<option value='7d' selected>7 days</option>" in h
    assert total(h) <= every
    assert all("ending_within=7d" in m for m in re.findall(r"href='(/market\?[^']*page=\d+[^']*)'", h))
    assert mp.load()["last"].get("ending_within") == ["7d"]
    assert "<option value='7d' selected>" in page(ui)                     # a plain reload restores it
