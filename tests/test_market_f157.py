"""F-157: category controls control the feed. Multi-select + All; Land/Real Estate off by default; pure land hidden, mixed lots kept; choices
persist through the existing market prefs path; tests never touch the owner's real prefs file."""
from __future__ import annotations

import json
import re

import pytest

from operator_ui import market_prefs as mp, market_search as ms
from tests.test_market_f47 import cache, req, ui  # noqa: F401
from urllib.parse import urlencode


def get(ui, **qs):
    if "go" in qs:
        qs.setdefault("base", "Conway AR")
    return req(ui, "GET", "/market?" + urlencode(qs, doseq=True))[2]



@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


def lot(title, category=""):
    return {"id": title, "title": title, "category": category, "text": title.lower()}


LAND = lot("40 acres of vacant land, Perry County")
HOUSE = lot("3 bedroom house and residence lot")
MIXED = lot("Farm land parcel with tractor and shop tools")
TRAILER = lot("2015 utility trailer")
TOOL = lot("Snap-on wrench set")
ODD = lot("Antique clock")
ALL = [LAND, HOUSE, MIXED, TRAILER, TOOL, ODD]


def shown(cats):
    q = ms.parse_query({"cat": cats} if cats else {})
    return {c["title"] for c in ALL if q["cat_all"] or ms.cat_ok(c, q["cats"])}


def test_defaults_exclude_land_only():
    q = ms.parse_query({})
    assert q["cat_default"] and "land_real_estate" not in q["cats"] and set(q["cats"]) == set(ms.DEFAULT_CATS)
    assert shown(None) == {MIXED["title"], TRAILER["title"], TOOL["title"], ODD["title"]}      # pure land and house hidden, mixed kept, unknown kept under Other


def test_pure_land_hidden_mixed_retained_when_land_off():
    s = shown(["tools"])
    assert MIXED["title"] in s and TOOL["title"] in s and LAND["title"] not in s and HOUSE["title"] not in s
    assert TRAILER["title"] not in s and ODD["title"] not in s


def test_all_shows_every_category_and_land_alone_shows_only_land():
    assert shown(["all"]) == {c["title"] for c in ALL}
    assert shown(["land_real_estate"]) == {LAND["title"], HOUSE["title"], MIXED["title"]}
    assert shown(["other"]) == {ODD["title"]}


def test_multi_select_is_a_union():
    assert shown(["trailers", "other"]) == {TRAILER["title"], ODD["title"]}


def test_land_rover_is_not_land():
    assert not ms.in_cat(lot("Land Rover Defender"), "land_real_estate")


def test_controls_render_big_and_labelled(ui):
    h = get(ui, go=1)
    box = re.search(r"<div id='mkcats'>.*?</div>", h, re.S).group(0)
    for lab in ("All categories", "Tools", "Equipment", "Trailers", "Vehicles", "Lawn &amp; Garden", "Machinery", "Pallets/Wholesale", "Land/Real Estate", "Other/Unknown"):
        assert lab in box
    assert not re.search(r"value='land_real_estate' checked", box) and "value='tools' checked" in box
    assert "min-height:44px" in h
    assert "value='all' checked" in re.search(r"<div id='mkcats'>.*?</div>", get(ui, go=1, cat="all"), re.S).group(0)


def test_feed_follows_the_ticks_and_persists_per_owner_prefs(ui, tmp_path):
    get(ui, go=1, cat=["trailers"])
    saved = json.loads((tmp_path / "prefs.json").read_text())["last"]
    assert saved["cat"] == ["trailers"]
    h = get(ui)                                       # a later visit with no filters restores the choice from the same prefs path
    assert "value='trailers' checked" in h and "value='tools' checked" not in h
    assert mp.recall(("cat",)) == {"cat": ["trailers"]}


def test_isolation_owner_prefs_untouched(ui, tmp_path, monkeypatch):
    assert mp.path() == tmp_path / "prefs.json"
    assert "var/market_prefs.json" not in str(mp.path())
    owner = tmp_path / "owner.json"
    owner.write_text(json.dumps({"enabled": True, "last": {"cat": ["land_real_estate"]}}))
    before = owner.read_bytes()
    get(ui, go=1, cat=["tools"])
    assert owner.read_bytes() == before


# F-158: commercial real-estate titles must not be kept by the system category guess
COMM = [lot(t, "commercial_equipment") for t in (
    "CENTRAL AVENUE NO RESERVE COMMERCIAL REAL ESTATE AUCTION", "MALVERN AVENUE COMMERCIAL REAL ESTATE AUCTION",
    "MCGEHEE MULTI-PARCEL COMMERCIAL BUILDING AUCTION")]
CAMPERS = lot("ONLINE ONLY NO RESERVE FALL CONSIGNMENT CAMPERS, VEHICLES, TRAILERS, TRACTOR & IMPLEMENTS", "commercial_equipment")


@pytest.mark.parametrize("cats", [None, ["equipment"], ["equipment", "tools", "other"]])
def test_f158_commercial_real_estate_hidden(cats):
    q = ms.parse_query({"cat": cats} if cats else {})
    assert not any(ms.cat_ok(c, q["cats"]) for c in COMM)


def test_f158_shown_with_land_or_all():
    q = ms.parse_query({"cat": ["land_real_estate"]})
    assert all(ms.cat_ok(c, q["cats"]) for c in COMM)
    assert ms.parse_query({"cat": ["all"]})["cat_all"]


def test_f158_building_auction_is_land_and_mixed_kept():
    assert ms.in_cat(lot("Downtown building auction"), "land_real_estate")
    q = ms.parse_query({})
    assert ms.cat_ok(CAMPERS, q["cats"])
