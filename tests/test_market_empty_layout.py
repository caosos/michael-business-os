"""With no source data at all (a fresh public site), /market still shows the full browse layout and an honest empty state."""
from urllib.parse import urlencode

import pytest

from tests.test_market_f47 import req, ui  # noqa: F401
from tests.test_market_f47 import cache  # noqa: F401


@pytest.fixture(autouse=True)
def empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.setenv("MBOS_GSA_CACHE", str(tmp_path / "no-gsa.json"))
    monkeypatch.setenv("MBOS_FACEBOOK_CACHE", str(tmp_path / "no-fb.json"))
    for k in ("WOOLEY", "WILSON", "BLACKMON"):
        monkeypatch.setenv(f"MBOS_{k}_CACHE", str(tmp_path / f"no-{k.lower()}.json"))


def test_empty_site_keeps_search_bar_filters_and_sources(ui, tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_GSA_CACHE", str(tmp_path / "still-no-gsa.json"))      # after the shared fixture set a GSA cache
    h = req(ui, "GET", "/market?" + urlencode({"base": "72032", "radius": "50", "cat": "all"}))[2]
    for marker in ("id='mkfilters'", "id='sec-source'", "id='sec-ending'", "name='keywords'", "id='no-sources'", "No listings yet"):
        assert marker in h, marker
    assert "0 results found" in h or "id='result-count'" not in h
