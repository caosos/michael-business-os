"""F-57: wide-screen density on /market. The page wraps in a wide main, the gallery packs ~230px cards, the 'Operator UI' title is dropped, an empty row says so across the grid."""

from __future__ import annotations

import re

import pytest

from tests.test_market_f47 import cache, get, ui  # noqa: F401


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


def test_market_uses_width_and_compact_chrome(ui):
    h = get(ui, go=1, keywords="trailer")
    assert "main{max-width:1900px}" in h and "header b{display:none}" in h
    assert re.search(r"\.mk-gal\{display:grid;grid-template-columns:repeat\(auto-fill,minmax\(min\(230px,100%\),1fr\)\)", h)
    assert ".mk-gal>p{grid-column:1/-1" in h
    assert "mk-g' data-lot" in h and "behind GSA" in h and "<img" not in h.split("mk-g' data-lot", 1)[1].split("</div>", 1)[0]  # photo tiles stay honest


def test_mobile_nav_scrolls_instead_of_stacking(ui):
    assert re.search(r"@media\(max-width:700px\)\{header nav\{flex-wrap:nowrap;overflow-x:auto", get(ui, go=1))
