"""F-33 (R14): "I bought it" over real HTTP, on a backend that connects as lane D's REAL Operator UI login (`mbos_operator_ui`).
Bought -> deployed rises (available falls) -> sold -> principal returns and the profit is earned; a second close and an over-available
purchase are refused with a clear message. Ledger assertions are deltas (the module-scoped database is shared)."""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from tests.conftest import PIN
from tests.lane_d.test_ui_on_lane_d import post, ready, req, wait

pytestmark = pytest.mark.usefixtures("rtd")
_n = iter(range(10**6))


@pytest.fixture(scope="module")
def ui_role(rtd):
    eng = sa.create_engine(make_url(rtd.url).set(username="mbos_operator_ui", password=None))
    yield eng
    eng.dispose()


@pytest.fixture()
def ui_least(rtd, ui_role):
    from mbos.runtime import components

    from operator_ui.backend import SpineBackend
    from operator_ui.server import App, make_handler

    app = App(SpineBackend(ui_role, components(), lane="lane_d"), operator_pin=PIN)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()


def pos(rtd):
    with rtd.engine.connect() as c:
        r = c.execute(sa.text("SELECT capital_deployed, earned_working_capital, realized_profit, available_to_deploy FROM mbos.v_capital_position "
                              "WHERE mode = 'dry_run'")).first()
    return tuple(float(x) for x in r) if r else (0.0, 0.0, 0.0, 0.0)


def bought(ui, item_id, **f):
    return req(ui, "POST", f"/item/{item_id}/bought", {"csrf": ui.csrf, "pin": PIN, "nonce": f"nonce{next(_n):08d}", **f})


def acted_flip(ui_d, discover_d):
    item_id, areq = ready(ui_d, discover_d)
    post(ui_d, areq, "YES", pin=PIN)
    wait(lambda: ui_d.store.item(item_id)["state"] == "ACTED")
    return item_id, areq


def test_bought_then_sold_returns_principal_and_earns_profit_over_http(rtd, discover_d, ui_d, ui_least, ui_role):
    item_id, areq = acted_flip(ui_d, discover_d)
    with ui_role.begin() as c:
        pid = c.execute(sa.text("SELECT provenance_id FROM mbos.provenance LIMIT 1")).scalar_one()
        c.execute(sa.text("SELECT mbos.capital_fund(1000::numeric, CAST(:a AS jsonb), 'F-33 bankroll', ARRAY[:p], :k)"),
                  {"a": '{"type": "human", "id": "michael"}', "p": pid, "k": "f33:" + item_id})
    assert "I bought it" in req(ui_least, "GET", f"/item/{item_id}")[2]
    b = pos(rtd)
    # bad input and a wrong PIN write nothing
    assert bought(ui_least, item_id, amount="-5", note="x")[0] == 200 and bought(ui_least, item_id, amount="120", note="from Sam, Sat", pin="0000")[0] == 200
    assert pos(rtd) == b
    s, loc, _ = bought(ui_least, item_id, amount="120", note="Bought from Sam on Saturday", author="mallory")
    assert s == 303 and "you bought it for $120.00" in loc and "Capital deployed on this item is now $120.00" in loc, loc
    a = pos(rtd)
    assert round(a[0] - b[0], 2) == 120 and round(b[3] - a[3], 2) == 120                      # deployed rises, available falls
    with rtd.engine.connect() as c:
        r = c.execute(sa.text("SELECT actor->>'type', actor->>'id', details->>'dry_run' FROM mbos.receipts WHERE item_id = :i AND type = 'BUDGET_COMMITTED' AND actor->>'type' = 'human'"),
                      {"i": item_id}).all()
    assert r == [("human", "michael", "true")]                                                # the mallory field was ignored
    mission = req(ui_least, "GET", "/mission")[2]
    assert "Open flips" in mission and "$120.00" in mission
    assert "Recorded as bought: <b>$120.00</b>" in req(ui_least, "GET", f"/item/{item_id}")[2]
    # sold: principal returns, profit becomes earned working capital, and the open-flips block empties
    oc = {"csrf": ui_least.csrf, "kind": "flip_sold", "revenue": "200", "total_cost": "120"}
    s, loc, _ = req(ui_least, "POST", f"/areq/{areq['action_request_id']}/outcome", oc)
    assert s == 303 and "msg=Outcome flip_sold recorded" in loc, loc
    z = pos(rtd)
    assert round(z[0] - b[0], 2) == 0 and round(z[1] - b[1], 2) == 80 and round(z[2] - b[2], 2) == 80
    assert f"/item/{item_id}'" not in req(ui_least, "GET", "/mission")[2]
    # a second close is refused with a clear message and moves nothing
    s, loc, _ = req(ui_least, "POST", f"/areq/{areq['action_request_id']}/outcome", {**oc, "kind": "flip_sold", "revenue": "999"})
    assert s == 303 and "err=" in loc and "already closed" in loc and "nothing moved" in loc, loc
    assert pos(rtd) == z and len(ui_d.store.outcomes(item_id)) == 1
    page = req(ui_least, "GET", f"/item/{item_id}")[2]
    assert "A second close is refused" in page
    assert bought(ui_least, item_id, amount="10", note="again please")[0] == 200 and pos(rtd) == z   # no buy form once closed


def test_over_available_unknown_and_non_flip_are_refused_with_a_reason(rtd, discover_d, ui_d, ui_least):
    item_id, _ = acted_flip(ui_d, discover_d)
    b = pos(rtd)
    s, _, body = bought(ui_least, item_id, amount=f"{b[3] + 1:.2f}", note="way too much")
    assert s == 200 and "Not recorded" in body and ("exceeds available" in body or "not funded" in body)
    assert pos(rtd) == b
    s, _, body = bought(ui_least, "item_nope", amount="5", note="whatever it was")
    assert s == 404 or "unknown opportunity" in body or "No such" in body


def test_the_workflow_login_cannot_record_an_acquisition(rtd, discover_d, ui_d):
    item_id, _ = acted_flip(ui_d, discover_d)
    from mbos.runtime import components
    from operator_ui.backend import NumbersRefused, SpineBackend

    be = SpineBackend(sa.create_engine(make_url(rtd.url).set(username="mbos_dbos", password=None)), components(), lane="lane_d")
    with pytest.raises(NumbersRefused):
        be.record_acquisition(item_id, 5, "forged", "michael", "f33:forged:" + item_id)
