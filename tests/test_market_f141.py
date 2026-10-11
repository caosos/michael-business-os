"""F-141: owner-entered finds on /market. SYNTHETIC finds only; scratch files in tmp; no network (asserted)."""
from __future__ import annotations

import json
import re
import socket
import urllib.request
from datetime import datetime, timezone

import pytest

from operator_ui import market_finds as mf
from operator_ui import market_prefs as mp
from operator_ui import market_routes, market_search as ms
from tests.test_market_f47 import cache, get, post, ui  # noqa: F401

LINK = "https://www.facebook.com/marketplace/item/1234567890/?ref=share&utm=x"
GOOD = dict(act="add", link=LINK, title="SYNTHETIC utility trailer 5x8", price="450", location="Conway, AR", condition="used", source="facebook", notes="SYNTHETIC note")
BROAD = dict(go=1, broad=1, radius=150, base="Conway AR")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.setenv("MBOS_DECISION_CASES_DIR", str(tmp_path / "cases"))


def add(ui, **over):
    return post(ui, "/market/find", **{**GOOD, **over})


def fid(**over):
    return next(iter(mf.load())) if not over else mf.find_id(over.get("source", "facebook"), over.get("link", ""), over.get("title", ""), over.get("location", ""))


def section(h):
    return h.split("id='your-finds'")[1].split("id='add-find'")[0]


def test_add_validate_and_store_shape(ui, tmp_path):
    st, loc, _ = add(ui)
    assert st == 303 and "owner-entered" in loc
    (i, r), = mf.load().items()
    assert re.fullmatch(r"own:facebook:[0-9a-f]{12}", i) and r["link"] == LINK and r["price"] == 450.0
    assert r["created_by"] == mf.WHO and r["created_at"] and r["updated_at"] and r["deleted"] is False
    assert mf.path().parent == tmp_path and mf.path().name == "market_finds.json"
    bad = [dict(title=""), dict(link="ftp://x.example/a"), dict(link="https://a.example/a b"), dict(price="abc"), dict(price="-5"), dict(source="ebay"), dict(location=""), dict(condition="mint")]
    for b in bad:
        st, _, body = add(ui, **{"title": "SYNTHETIC other thing", **b})
        assert st == 200 and "Not saved" in body, b
    assert len(mf.load()) == 1


def test_shown_in_own_section_labelled_not_in_gsa_counts(ui):
    h0 = get(ui, **BROAD)
    n0 = re.search(r"<h2>(\d+) result", h0).group(1)
    add(ui)
    h = get(ui, **BROAD)
    assert re.search(r"<h2>(\d+) result", h).group(1) == n0                          # GSA count unchanged
    s = section(h)
    assert "Your finds" in s and "SYNTHETIC utility trailer" in s and "Facebook Marketplace" in s
    assert "OWNER-ENTERED" in s and "not fetched" in s and "unverified" in s and "not a live listing" in s
    assert "SYNTHETIC utility trailer" not in h.split("id='your-finds'")[0]            # never mixed into GSA results
    assert "price as entered" in s and "mi" in s and "created_by" not in s


def test_persists_across_restart_and_reload(ui):
    add(ui)
    raw = mf.path().read_text()
    assert json.loads(raw)["finds"]
    assert get(ui, **BROAD).count("data-find='1'") == 1 == get(ui, **BROAD).count("data-find='1'")
    assert not list(mf.path().parent.glob("tmp*"))                                      # atomic write leaves no temp file


def test_duplicates_refused_link_tracking_ignored_and_title_city_key(ui):
    add(ui)
    st, _, body = add(ui, link=LINK.split("?")[0] + "/", title="SYNTHETIC different title")
    assert st == 200 and "Already in your finds" in body and len(mf.load()) == 1
    add(ui, link="", title="SYNTHETIC Mower", location="Little Rock, AR", source="craigslist")
    st, _, body = add(ui, link="", title=" synthetic  mower ", location="little rock, ar", source="craigslist")
    assert st == 200 and "Already in your finds" in body and len(mf.load()) == 2


def test_edit_and_audit(ui):
    add(ui)
    i = fid()
    st, loc, _ = post(ui, "/market/find", **{**GOOD, "act": "edit", "find": i, "price": "400", "notes": "SYNTHETIC revised"})
    assert st == 303
    r = mf.load()[i]
    assert r["price"] == 400.0 and r["notes"] == "SYNTHETIC revised" and r["updated_by"] == mf.WHO and r["created_at"]
    st, _, body = post(ui, "/market/find", **{**GOOD, "act": "edit", "find": i, "price": "x"})
    assert st == 200 and mf.load()[i]["price"] == 400.0


def test_delete_soft_and_undo(ui):
    add(ui)
    i = fid()
    post(ui, "/market/find", act="delete", find=i)
    assert mf.load()[i]["deleted"] is True and mf.load()[i]["deleted_by"] == mf.WHO and mf.load()[i]["deleted_at"]
    h = get(ui, **BROAD)
    assert "data-find='1'" not in h and f"data-deleted='{i}'" in h
    st, _, body = add(ui)
    assert "undo it from" in body
    post(ui, "/market/find", act="undo", find=i)
    assert mf.load()[i]["deleted"] is False and "data-find='1'" in get(ui, **BROAD)


def test_price_filters_and_unknown_price(ui):
    add(ui)
    add(ui, link="", title="SYNTHETIC no price trailer", price="", location="Conway, AR")
    h = get(ui, **BROAD, max_price=300)
    s = section(h)
    assert "SYNTHETIC utility trailer" not in s.split("finds-unchecked")[0]            # 450 > 300 is excluded
    assert "finds-unchecked" in s and "SYNTHETIC no price trailer" in s and "Price UNKNOWN" in s     # unknown price: unchecked, not counted
    assert "SYNTHETIC no price trailer" not in s.split("finds-unchecked")[0]
    assert "SYNTHETIC utility trailer" in section(get(ui, **BROAD, max_price=500))


def test_radius_boundary_and_unknown_location(ui):
    r = {"id": "own:other:aaaaaaaaaaaa", "title": "SYNTHETIC trailer", "source": "other", "price": 10.0, "location": "Little Rock, AR", "condition": "", "notes": ""}
    origin = ms._origin("Conway AR")
    d = mf.card(r, origin)["distance"]
    assert d and d > 20
    q = lambda rad: ms.parse_query({"go": ["1"], "broad": ["1"], "radius": [repr(rad)], "base": ["Conway AR"]})  # noqa: E731
    assert len(ms.partition([mf.card(r, origin)], q(d))[0]) == 1                        # exactly on the boundary is in
    assert len(ms.partition([mf.card(r, origin)], q(d - 0.001))[0]) == 0
    unk = mf.card({**r, "id": "own:other:bbbbbbbbbbbb", "location": "Nowhereville, ZZ"}, origin)
    assert unk["distance"] is None
    res, unch, _ = ms.partition([unk], q(5000))
    assert res == [] and unch[0]["unchecked"]
    add(ui, link="", title="SYNTHETIC trailer lost", location="Nowhereville, ZZ", source="other")
    s = section(get(ui, **BROAD))
    assert "finds-unchecked" in s and "distance UNKNOWN" in s and "data-find" in s.split("finds-unchecked")[1]
    assert "data-find" not in s.split("finds-unchecked")[0]                             # not counted as local


def test_state_mode_and_condition_and_category(ui):
    add(ui)
    add(ui, link="", title="SYNTHETIC tractor", location="Memphis, TN", condition="new", source="craigslist")
    s = section(get(ui, **BROAD, loc_mode="state", state="AR"))
    assert "SYNTHETIC utility trailer" in s and "SYNTHETIC tractor" not in s
    s = section(get(ui, **BROAD, condition="new"))
    assert "SYNTHETIC tractor" in s and "SYNTHETIC utility trailer" not in s.split("finds-unchecked")[0]
    s = section(get(ui, go=1, radius=500, base="Conway AR", cat="trailers"))
    assert "SYNTHETIC utility trailer" in s and "SYNTHETIC tractor" not in s


def test_hide_undo_save_through_prefs_ids(ui):
    add(ui)
    i = fid()
    post(ui, "/market/pref", act="save", lot=i, title="x")
    assert "SAVED" in section(get(ui, **BROAD)) and i in mp.load()["saved"]
    post(ui, "/market/pref", act="hide", lot=i, title="SYNTHETIC utility trailer")
    h = get(ui, **BROAD)
    assert f"data-lot='{i}'" not in section(h) and "1 hidden by you" in section(h) and f"data-hidden='{i}'" in h
    post(ui, "/market/pref", act="restore", lot=i)
    assert f"data-lot='{i}'" in section(get(ui, **BROAD))
    post(ui, "/market/pref", act="dismiss", lot=i, title="SYNTHETIC utility trailer")
    assert f"data-lot='{i}'" not in section(get(ui, **BROAD))


def test_precedent_block_available(ui, tmp_path):
    from mbos import decision_cases as dc
    add(ui)
    case = {"listing_id": "SYN-0001", "source": "facebook", "title": "synthetic utility trailer", "decided_at": "2026-01-02T00:00:00+00:00", "decision": "pass",
            "reason_summary": "SYNTHETIC reason", "evidence": [{"kind": "condition", "text": "SYNTHETIC note", "provenance": "unverified"}], "owner_estimates": [], "alternatives_considered": [], "uncertainty": [], "missing_evidence": [], "owner_skills": "", "category_tags": []}
    f = tmp_path / "case.json"
    f.write_text(json.dumps(case))
    dc.import_cases(f)
    assert "data-testid='precedent'" in section(get(ui, **BROAD)) and "SYNTHETIC reason" in section(get(ui, **BROAD))


def test_hostile_text_escaped(ui):
    add(ui, link="", title="<script>alert(1)</script>", notes="<img src=x onerror=1>", location="Conway, AR", source="other")
    h = get(ui, **BROAD)
    assert "<script>alert(1)</script>" not in h and "&lt;script&gt;" in h and "<img src=x" not in h


def test_no_network_and_no_private_content(ui, monkeypatch):
    import operator_ui.market_finds as a, operator_ui.finds_view as b
    for m in (a, b):
        src = open(m.__file__).read()
        assert not re.search(r"^\s*(import|from)\s+(urllib\.request|requests|socket|http\.client|httpx|aiohttp|playwright)", src, re.M)
    def boom(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert market_routes.post(ui, ["market", "find"], {**GOOD, "csrf": ui.csrf})[1] is None
    html = market_routes.page_body(ui, {k: [str(v)] for k, v in BROAD.items()}, datetime.now(timezone.utc))
    assert "SYNTHETIC utility trailer" in html and "var/private" not in html
