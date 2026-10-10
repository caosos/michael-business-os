"""F-39: deal card as a decision, control strip, Morning Money Hunt, and the resale workflow intake -> sold with a receipt.
All data is DEMO/SIMULATED fixture data."""
from operator_ui import resale_view as rv
from tests.conftest import PIN
from tests.test_operator_ui import req


def test_demo_splitter_is_a_watch_with_forecast_and_owner_basis():
    c = rv.decide(rv.DEMO_DEALS["demo-splitter"])
    assert c["action"] == "WATCH" and c["computable"] and c["max_bid"] <= 500 and c["forecast"]["label"].startswith("FORECAST")
    assert c["resale"]["owner_target"] == 1500 and c["asking_comps"] == 1 and c["sold_comps"] == 0
    h = rv.render_deal_card(c)
    assert "DEMO" in h and "human-attested" in h and "asking never counts as sold" in h and "owner-gated" in h


def test_missing_inputs_are_unknown_and_watch_never_buy():
    c = rv.decide({"item_id": "x", "title": "<b>x</b>"})
    assert c["action"] == "WATCH" and not c["computable"] and c["unknowns"] and c["net"] is None
    h = rv.render_deal_card(c)
    assert "UNKNOWN" in h and "<b>x</b>" not in h


def test_hunt_shape():
    cards = [rv.decide(rv.DEMO_DEALS["demo-splitter"])]
    h = rv.render_hunt(cards, [])
    for s in ("Bottom line", "What changed", "What was rejected", "Today's best move", "Source", "Time to cash", "Action today"):
        assert s in h


def advance(ui, iid, **kw):
    return req(ui, "POST", f"/resale/{iid}/advance", {"csrf": ui.csrf, "pin": PIN, **kw})


def test_item_moves_intake_to_sold_with_receipt_and_simulated_is_never_earned(ui):
    st, _, b = req(ui, "GET", "/resale?demo=1")
    assert st == 200 and "Capital tied up" in b and "demo-splitter" in b
    assert req(ui, "POST", "/resale/add", {"csrf": ui.csrf, "pin": "bad", "title": "t"})[0] == 200 and not ui.resale.items  # PIN gate
    assert req(ui, "POST", "/resale/add", {"csrf": ui.csrf, "pin": PIN, "title": "TEST mower", "paid": "100", "deal": "demo-splitter"})[0] == 303
    iid = next(iter(ui.resale.items))
    assert advance(ui, iid, step="sold", price="300", receipt="x")[0] == 200 and ui.resale.items[iid]["stage"] == "intake"  # no skipping
    for kw in ({"step": "photos", "photos": "a.jpg"}, {"step": "listing", "listing": "TEST ad", "demand": "two calls", "ask": "350"},
               {"step": "listed"}, {"step": "sold", "price": "300", "fees": "10", "receipt": "cash, buyer Sam, 10/9"}):
        assert advance(ui, iid, **kw)[0] == 303
    it = ui.resale.items[iid]
    assert it["stage"] == "sold" and it["sale"]["net"] == 190 and it["receipt_id"] in {r["id"] for r in ui.resale.receipts}
    assert len(ui.resale.receipts) == 5
    b = req(ui, "GET", "/resale?demo=1")[2]
    assert "SIMULATED, not earned" in b and ui.resale.realized() == {"earned": 0.0, "simulated": 190.0, "n_earned": 0, "n_simulated": 1}
    assert "EARNED (" not in b
    req(ui, "POST", "/resale/add", {"csrf": ui.csrf, "pin": PIN, "title": "real one", "paid": "50", "real": "1"})
    rid = [k for k, v in ui.resale.items.items() if not v["simulated"]][0]
    for kw in ({"step": "photos", "photos": "b.jpg"}, {"step": "listing", "listing": "ad", "ask": "120"}, {"step": "listed"}, {"step": "sold", "price": "120", "receipt": "cash"}):
        advance(ui, rid, **kw)
    assert ui.resale.realized()["earned"] == 70.0 and "EARNED (" in req(ui, "GET", "/resale?demo=1")[2]
    assert "Morning Money Hunt" in req(ui, "GET", "/?demo=1")[2]
