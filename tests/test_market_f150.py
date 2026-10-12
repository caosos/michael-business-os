"""F-150: Census gazetteer coverage (ZIP, City ST) and same-source dedupe never merging distinct auctions. Offline."""
from __future__ import annotations

import pytest
from mbos_discovery.adapters.wilson_site import WilsonSiteAdapter
from mbos_discovery.adapters.wooley_site import WooleySiteAdapter

from operator_ui import gazetteer, market_search as ms, market_sources as msrc
from tests.test_market_f149 import AS_OF, FIX, NOW, caches, isolate, write  # noqa: F401
from tests.test_market_f47 import cache  # noqa: F401


@pytest.mark.parametrize("q", ["72013", "71667", "72160", "72106", "Bee Branch, AR", "Star City AR", "stuttgart, ar", "Mayflower, AR", "Perry, AR", "Malvern AR", "St. Francis, AR", "Saint Francis AR"])
def test_towns_and_zips_resolve(q):
    assert gazetteer.locate(q) is not None


def test_zip_first_override_still_works(tmp_path, monkeypatch):
    f = tmp_path / "g.csv"
    f.write_text("zip,city,state,lat,lng\n99999,Nowhere,AR,1.0,2.0\n")
    monkeypatch.setenv("MBOS_GAZETTEER_FILE", str(f))
    assert gazetteer.locate("99999") == (1.0, 2.0) and gazetteer.locate("Nowhere, AR") == (1.0, 2.0) and gazetteer.locate("72013") is None


def test_wilson_all_events_located_and_counts_match(caches, cache):
    o = ms._origin("Conway AR")
    w = ms.load_source("wilson", NOW, o)
    assert len(w["cards"]) == 17
    for c in w["cards"]:
        assert c["distance"] is not None, c["title"]
    allh = ms.load_source("auctions", NOW, o)
    assert sum(1 for c in allh["cards"] if c["source"] == "Wilson Auctioneers") == 17
    wlr = [c for c in allh["cards"] if "west little rock" in c["title"].lower()]
    assert sorted(c["url"][-4:] for c in wlr) == ["1069", "1089"]


def test_dedupe_same_source_never_merged_cross_source_rules():
    a = {"title": "Residential Estate Auction West Little Rock", "url": "u1", "city": "Little Rock, AR", "closes": "2026-10-20", "source": "Wilson"}
    b = {**a, "url": "u2"}
    assert len(msrc.dedupe([a, b])) == 2
    assert len(msrc.dedupe([a, {**a, "source": "GSA", "url": "u3"}])) == 1
    assert len(msrc.dedupe([a, {**a, "source": "GSA", "url": "u3", "closes": "2026-10-21"}])) == 2
    assert len(msrc.dedupe([a, {**b, "source": "GSA", "title": "Totally different", "url": "u1"}])) == 1
