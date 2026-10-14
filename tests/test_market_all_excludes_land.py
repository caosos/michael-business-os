"""Owner rule: property listings show only when Land/Real Estate is ticked. 'All categories' alone means everything except property."""
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import pytest

from operator_ui import market_search as ms
from tests.test_market_f47 import cache, req, ui  # noqa: F401
from tests.test_market_p0_distance import fb

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def prefs(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


@pytest.fixture()
def pool(ui, cache, monkeypatch):
    loaded = ms.load_gsa(str(cache), NOW, ms._origin("Conway AR"))
    cards = [fb("1", "QZL 40 acre hunting land parcel", "Conway, AR", 3.0), fb("2", "QZL utility trailer 6x12", "Conway, AR", 3.0),
             fb("3", "QZL mobile home trailer frame", "Conway, AR", 3.0)]
    monkeypatch.setattr(ms, "load_source", lambda *a, **k: {**loaded, "cards": cards, "in_file": 3, "in_scope": 3})


def titles(ui, **qs):
    h = req(ui, "GET", "/market?" + urlencode({"go": 1, "base": "Conway AR", "radius": "25", "keywords": "qzl", **qs}, doseq=True))[2]
    return set(re.findall(r"QZL [a-z0-9 ]+", h)), h


def test_all_alone_hides_property_and_all_plus_land_shows_it(ui, pool):
    got, h = titles(ui, cat=["all"])
    assert "QZL utility trailer 6x12" in got and "QZL 40 acre hunting land parcel" not in got
    assert "QZL mobile home trailer frame" in got                      # a trailer that mentions a home is still a trailer
    assert "name='cat' value='all' checked" in h and "name='cat' value='land_real_estate' checked" not in h
    got, h = titles(ui, cat=["all", "land_real_estate"])
    assert "QZL 40 acre hunting land parcel" in got and "name='cat' value='land_real_estate' checked" in h


def test_parse_rule():
    q = ms.parse_query({"cat": ["all"]})
    assert not q["cat_all"] and q["cat_all_but_land"] and "land_real_estate" not in q["cats"] and "tools" in q["cats"]
    q = ms.parse_query({"cat": ["all", "land_real_estate"]})
    assert q["cat_all"] and "land_real_estate" in q["cats"]
