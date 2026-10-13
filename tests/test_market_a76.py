"""A-76: explicit, account-owned personalization with hard-filter safety."""

from __future__ import annotations

from datetime import datetime, timezone

from operator_ui import accounts, market_browse as mb, market_prefs as mp, market_search as ms, market_view as mv


NOW = datetime(2026, 10, 13, 17, 0, tzinfo=timezone.utc)


def card(i: str, title: str, *, source="Facebook Marketplace", distance=10.0, category="trailers") -> dict:
    return {"id": i, "title": title, "description": "", "text": title.lower(), "url": "https://example.test/" + i,
            "image": None, "bid": 100.0, "price": 100.0, "price_type": "asking", "bidders": None,
            "closes": "2026-10-20", "city": "Conway, AR", "state": "AR", "zip": "72032", "distance": distance,
            "category": category, "condition": "used", "source": source, "fetched_at": NOW.isoformat(), "kind": "fixed", "stale": False}


def prefs(**changes) -> dict:
    base = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in mp.EMPTY.items()}
    return {**base, **changes}


def test_ranking_cannot_reintroduce_rows_removed_by_city_radius_category_or_source():
    rows = [card("ok", "Utility trailer"),
            card("far", "Utility trailer far away", distance=80),
            card("source", "Utility trailer from GSA", source="GSA Auctions"),
            card("category", "Mechanic tool set", category="tools")]
    q = ms.parse_query({"go": ["1"], "base": ["72032"], "radius": ["30"], "cat": ["trailers"], "source": ["facebook"]})
    checked, unchecked, _ = ms.partition(rows, q)
    filtered = mb.post(checked + unchecked, q, NOW)
    ranked, _ = mp.rank(filtered, prefs(more={"trailer": 5}), lambda c: (c["title"],))

    assert [c["id"] for c in ranked] == ["ok"]
    assert ranked[0]["distance"] <= q["radius"]
    assert ms.cat_ok(ranked[0], q["cats"]) and mb.source_ok(ranked[0], q["source"])


def test_explicit_feedback_ranks_by_item_words_category_and_source_with_explanations():
    d = prefs(saved=["saved"], more={"utility": 1}, less={"office": 1},
              more_categories={"trailers": 2}, less_categories={},
              more_sources={"facebook_marketplace": 1}, less_sources={})
    rows = [card("plain", "Plain listing", source="Craigslist", category="other"),
            card("liked", "Utility trailer"), card("saved", "Saved mower", category="equipment"),
            card("down", "Office chair", source="Craigslist", category="other")]

    ranked, _ = mp.rank(rows, d, lambda c: (c["title"],))

    assert ranked[0]["id"] == "liked"
    assert ranked[-1]["id"] == "down"
    assert all(c["why"].startswith("Why you're seeing this:") for c in ranked)
    assert "categories you liked" in ranked[0]["why"] and "source you liked" in ranked[0]["why"]
    assert "you saved it" in next(c["why"] for c in ranked if c["id"] == "saved")


def test_discovery_mix_is_bounded_and_deterministic():
    rows = [card("liked", "Favorite trailer")] + [card(f"n{i}", f"Neutral chair {i}", source="Craigslist", category="other") for i in range(8)]
    d = prefs(more={"favorite": 2})

    first, _ = mp.rank(rows, d, lambda c: (c["title"],))
    second, _ = mp.rank(rows, d, lambda c: (c["title"],))

    assert [c["id"] for c in first] == [c["id"] for c in second]
    discovery = [c for c in first if c["discovery"]]
    assert len(discovery) == mp.DISCOVERY_MAX == 2
    assert all("discovery pick" in c["why"] for c in discovery)


def test_disable_preserves_input_order_and_reset_clears_learning_but_not_hides(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    mp.act("more", "one", "Utility trailer", "trailers", "Facebook Marketplace")
    mp.act("hide", "hidden", "Hidden trailer")
    mp.act("disable", "")
    rows = [card("b", "B trailer"), card("a", "A trailer")]
    assert mp.rank(rows, mp.load(), lambda c: (c["title"],))[0] == rows

    mp.act("reset", "")
    d = mp.load()
    assert not d["enabled"] and d["hidden"] == {"hidden": "Hidden trailer"}
    assert d["saved"] == [] and d["more"] == {} and d["more_categories"] == {} and d["more_sources"] == {}


def test_learning_signals_are_strictly_account_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "owner.json"))
    one, two = accounts.google_account("a76-one"), accounts.google_account("a76-two")

    with accounts.use(one):
        mp.act("more", "one", "Utility trailer", "trailers", "Facebook Marketplace")
        assert mp.load()["more_categories"] == {"trailers": 1}
    with accounts.use(two):
        assert mp.load()["more_categories"] == {} and mp.load()["more_sources"] == {}
        mp.act("less", "two", "Office equipment", "equipment", "GSA Auctions")
    with accounts.use(one):
        d = mp.load()
        assert d["less_categories"] == {} and d["more_sources"] == {"facebook_marketplace": 1}


def test_card_controls_submit_category_and_source_and_show_reason_outside_more_menu():
    c = {**card("one", "Utility trailer"), "why": "Why you're seeing this: you asked for more trailers."}
    controls = mv.pref_buttons(c, lambda: "", include_why=False)
    html = mb.card(c, lambda: "", NOW, mv.pref_buttons)

    assert "data-learning name='category' value='trailers'" in controls
    assert "data-learning name='source' value='Facebook Marketplace'" in controls
    assert html.count("data-why") == 1
    assert html.index("data-why") < html.index("mk-card-src")

