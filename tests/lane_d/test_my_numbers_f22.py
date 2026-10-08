"""F-22 (R14): the "My numbers" page, through the real HTTP server on a backend that connects as lane D's REAL Operator UI login
(`mbos_operator_ui`, non-superuser). A mission and $500 of funding are receipted; clearing a value returns it to UNKNOWN; an agent
role is refused by the database. Ledger assertions are deltas (the module-scoped database is shared with other tests)."""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from tests.conftest import PIN
from tests.lane_d.test_least_privilege_p0612 import refused
from tests.lane_d.test_ui_on_lane_d import req

pytestmark = pytest.mark.usefixtures("rtd")


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


_n = iter(range(10**6))


def post(ui, path, **f):
    f = {"csrf": ui.csrf, "pin": PIN, "nonce": f"nonce{next(_n):08d}", **f}
    return req(ui, "POST", path, f)


def position(rtd):
    with rtd.engine.connect() as c:
        r = c.execute(sa.text("SELECT protected_principal, earned_working_capital, realized_profit FROM mbos.v_capital_position "
                              "WHERE mode = 'dry_run'")).first()
    return tuple(float(x) for x in r) if r else (0.0, 0.0, 0.0)


def receipts(rtd, kind):
    with rtd.engine.connect() as c:
        return c.execute(sa.text("SELECT actor, count(*) OVER () FROM mbos.receipts WHERE type = 'CONFIG_VERSION_BUMPED' "
                                 "AND entity_type = :k"), {"k": kind}).all()


def current(ui):
    return ui.store.my_numbers()["mission"]


def test_set_mission_and_fund_500_show_on_the_pages(rtd, ui_least):
    before = position(rtd)
    s, loc, _ = post(ui_least, "/numbers/mission", weekly_target_usd="1,500", hours_available="20", cash_situation="$500 free, rest tied up",
                     actor="agent-evil")  # an actor field is ignored
    assert s == 303 and "msg=Saved" in loc, loc
    m = current(ui_least)
    assert (m["weekly_target_usd"], m["hours_available"], m["notes"]) == (1500, 20, "$500 free, rest tied up")
    s, loc, _ = post(ui_least, "/numbers/capital", kind="fund", amount="500")
    assert s == 303 and "Fund of $500.00 recorded" in loc, loc
    after = position(rtd)
    assert after[0] - before[0] == 500 and after[1:] == before[1:]
    s, _, body = req(ui_least, "GET", "/numbers")
    assert s == 200 and "$1,500" in body and "$500 free, rest tied up" in body and "Protected principal" in body
    s, _, mp = req(ui_least, "GET", "/mission")
    assert s == 200 and "$1,500" in mp and "emaining gap" in mp
    rows = receipts(rtd, "mission") + receipts(rtd, "capital_fund")
    assert rows and all(r[0] == {"type": "human", "id": "michael"} for r in rows)


def test_clearing_a_value_returns_it_to_unknown(rtd, ui_least):
    post(ui_least, "/numbers/mission", weekly_target_usd="900", hours_available="10", cash_situation="tight")
    s, loc, _ = post(ui_least, "/numbers/mission", weekly_target_usd="", hours_available="10", cash_situation="")
    assert s == 303 and "msg=Saved" in loc
    m = current(ui_least)
    assert m["weekly_target_usd"] is None and m["hours_available"] == 10 and "notes" not in m
    _, _, body = req(ui_least, "GET", "/numbers")
    assert body.count("UNKNOWN") >= 2
    _, _, mp = req(ui_least, "GET", "/mission")
    assert "UNKNOWN" in mp


def test_every_change_has_a_receipt_and_the_chain_verifies(rtd, ui_least):
    n0 = len(receipts(rtd, "mission"))
    post(ui_least, "/numbers/mission", weekly_target_usd="700")
    post(ui_least, "/numbers/capital", kind="fund", amount="25")
    assert len(receipts(rtd, "mission")) == n0 + 1
    assert ui_least.store.verify_chain()["ok"] is True
    with rtd.engine.connect() as c:
        assert c.execute(sa.text("SELECT ok FROM mbos.capital_verify() LIMIT 1")).scalar() is not False


def test_double_submit_is_idempotent(rtd, ui_least):
    f = {"nonce": "dupnonce0001", "kind": "fund", "amount": "7"}
    before = position(rtd)
    post(ui_least, "/numbers/capital", **f)
    post(ui_least, "/numbers/capital", **f)
    assert position(rtd)[0] - before[0] == 7


def test_withdraw_beyond_earned_is_refused_with_the_reason(rtd, ui_least):
    before = position(rtd)
    s, _, body = post(ui_least, "/numbers/capital", kind="withdraw", amount="99999")
    assert s == 200 and "Not saved" in body and "exceeds" in body
    assert position(rtd) == before


@pytest.mark.parametrize("f", [{"weekly_target_usd": "abc"}, {"weekly_target_usd": "-5"}, {"hours_available": "200"},
                               {"weekly_target_usd": "1e3"}, {"cash_situation": "x" * 501}])
def test_bad_mission_input_is_refused_and_nothing_written(rtd, ui_least, f):
    n0 = len(receipts(rtd, "mission"))
    s, _, body = post(ui_least, "/numbers/mission", **f)
    assert s == 200 and "Not saved" in body and len(receipts(rtd, "mission")) == n0


@pytest.mark.parametrize("f", [{"amount": "0"}, {"amount": "-1"}, {"amount": "nan"}, {"amount": ""}, {"amount": "1.234"}, {"kind": "deploy"}])
def test_bad_capital_input_is_refused(rtd, ui_least, f):
    before = position(rtd)
    s, _, body = post(ui_least, "/numbers/capital", **{"kind": "fund", "amount": "5", **f})
    assert s == 200 and "Not saved" in body and position(rtd) == before


def test_pin_csrf_and_host_guard(rtd, ui_least):
    before = position(rtd)
    s, _, body = req(ui_least, "POST", "/numbers/capital", {"csrf": ui_least.csrf, "nonce": "nonce99999999", "kind": "fund", "amount": "5"})
    assert s == 200 and "PIN is required" in body
    s, _, body = req(ui_least, "POST", "/numbers/capital", {"csrf": "bad", "pin": PIN, "nonce": "nonce99999999", "kind": "fund", "amount": "5"})
    assert s == 200 and "invalid form token" in body
    assert req(ui_least, "GET", "/numbers", host="evil.example")[0] == 403
    assert position(rtd) == before


@pytest.mark.parametrize("login", ["mbos_state_mcp", "mbos_reader", "mbos_gateway"])
def test_an_agent_role_is_refused_by_the_database(rtd, login):
    eng = sa.create_engine(make_url(rtd.url).set(username=login, password=None))
    try:
        for sql in ("SELECT mbos.capital_fund(5::numeric, '{\"type\":\"agent\",\"id\":\"a\"}'::jsonb, 'x', ARRAY['p'], 'f22:agent')",
                    "SELECT mbos.capital_withdraw(5::numeric, '{\"type\":\"agent\",\"id\":\"a\"}'::jsonb, 'x', ARRAY['p'], 'f22:agent2')",
                    "SELECT mbos.set_mission('{}'::jsonb, '{\"type\":\"agent\",\"id\":\"a\"}'::jsonb, 'x', ARRAY['p'], 'f22:agent3')"):
            assert "permission denied" in refused(eng, sql)
    finally:
        eng.dispose()
