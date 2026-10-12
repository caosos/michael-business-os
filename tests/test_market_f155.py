"""F-155: DealSniffer Suggestions panel on /market. Engine numbers only, $500 cap, repair rule, owner resale override, events out,
unknown-heavy lots under 'needs research', every estimate labelled. Display only."""
from __future__ import annotations

from operator_ui import market_suggest as ms

ASOF = "2026-10-12T12:00:00Z"


def lot(i, title="Utility trailer 6x12", bid=50, d=20, **k):
    return {"id": i, "title": title, "category": "", "bid": bid, "distance": d, "city": "Conway, AR", "state": "AR", "url": "https://x.example/" + i,
            "source": "GSA Auctions", "kind": "auction", **k}


def run(cards, targets=None):
    return ms.suggest(cards, {"resale_targets": targets or {}}, ASOF)


def test_numbers_come_from_the_engine_and_rank_by_its_velocity(monkeypatch):
    monkeypatch.setenv("MBOS_SUGGEST_REPAIR_MAX", "1000")
    s = run([lot("a", bid=40), lot("b", "Utility trailer 7x14", bid=40)], {"a": 1500, "b": 2500})
    assert [r["card"]["id"] for r in s["ranked"]] == ["b", "a"]
    for r in s["ranked"]:
        again = ms.score_lot(r["card"], r["owner_target"], ASOF)["numbers"]
        assert r["numbers"] == again                                      # nothing added or adjusted by this module
    v = [r["numbers"]["velocity"] for r in s["ranked"]]
    assert v == sorted(v, reverse=True)


def test_500_cap_on_bid_and_max_bid(monkeypatch):
    monkeypatch.setenv("MBOS_SUGGEST_REPAIR_MAX", "1000")
    s = run([lot("a", bid=600)], {"a": 9000})
    assert not s["ranked"] and any("over your per-purchase cap" in w for w in s["outside"][0]["why_not"])
    s = run([lot("b", bid=40)], {"b": 9000})
    assert s["ranked"] and s["ranked"][0]["max_bid"] <= 500


def test_repair_rule_and_override(monkeypatch):
    s = run([lot("a", bid=40)], {"a": 1500})
    assert not s["ranked"] and any("repair" in w for w in s["outside"][0]["why_not"])
    monkeypatch.setenv("MBOS_SUGGEST_REPAIR_MAX", "1000")                 # owner override
    assert run([lot("a", bid=40)], {"a": 1500})["ranked"]


def test_owner_resale_wins(monkeypatch):
    monkeypatch.setenv("MBOS_SUGGEST_REPAIR_MAX", "1000")
    r = run([lot("a", bid=40)], {"a": 1500})["ranked"][0]
    assert r["owner_target"] == 1500 and r["numbers"]["resale_likely"] == 1500
    h = ms.render_ranked(r)
    assert "$1,500 your resale price (owner-set, not a sold comp)" in h and "OWNER-SET" in h


def test_events_excluded_and_unknown_heavy_go_to_research():
    s = run([lot("e", "Wooley auction", bid=None, kind="auction event"), lot("e2", "Wilson sale", bid=None, event=True), lot("f", bid=40, fixture=True), lot("u", "Mystery crate", bid=None, d=None), lot("n", bid=40)])
    assert s["events"] == 2 and not s["ranked"]
    ids = {r["card"]["id"] for r in s["research"]}
    assert ids == {"u", "n"}                                              # no owner resale target and no comps: never ranked on a guess
    assert "UNKNOWN" in ms.render(s) and "not ranked as deals" in ms.render(s)


def test_everything_labelled_and_escaped(monkeypatch):
    monkeypatch.setenv("MBOS_SUGGEST_REPAIR_MAX", "1000")
    h = ms.render(run([lot("a", "Trailer <script>x</script>", bid=40)], {"a": 1500}))
    assert "<script>" not in h and "ESTIMATE" in h and "ENGINE" in h and "straight-line" in h
    assert "Display only" in h and "/market/bid" not in h      # only the local resale-price form; no bid, contact or spend control


def test_pallet_rows_labelled_not_ranked():
    s = run([lot("p", "Pallet of tools 40 pcs", bid=120)])
    assert not s["ranked"] and len(s["pallets"]) == 1
    h = ms.render(s)
    for w in ("Pallet price", "Testing / sort burden", "Expected recovery", "Sell-through speed", "Storage / handling", "Downside"):
        assert w in h
    assert h.count("not estimated") >= 5 and "40 stated in the title" in h


def test_resale_form_save_and_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "p.json"))
    from operator_ui import market_prefs as mp
    assert "saved on this computer only" in ms.act_resale({"lot": "a", "resale": "$1,500"})
    assert mp.load()["resale_targets"] == {"a": 1500.0}
    assert "cleared" in ms.act_resale({"lot": "a", "resale": ""})
    assert mp.load()["resale_targets"] == {}
    for bad in ("abc", "0", "-5", "nan"):
        try:
            ms.act_resale({"lot": "a", "resale": bad})
        except ValueError:
            continue
        raise AssertionError(bad)


def test_panel_has_resale_form_on_research_and_ranked(monkeypatch):
    monkeypatch.setenv("MBOS_SUGGEST_REPAIR_MAX", "1000")
    tok = lambda: "<input type='hidden' name='csrf' value='T'>"  # noqa: E731
    h = ms.render(run([lot("a", bid=40), lot("b", bid=40)], {"a": 1500}), tok)
    assert h.count("action='/market/resale'") == 2 and "name='csrf'" in h
    assert "your resale price (owner-set, not a sold comp)" in h
