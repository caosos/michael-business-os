"""P-06-18 (R14): the outcome-entry and operator-note paths, run through the real HTTP server on a backend whose engine
is lane D's REAL Operator UI login (`mbos_operator_ui`, non-superuser), plus the forbidden writes still refused."""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from tests.conftest import PIN
from tests.lane_d.test_least_privilege_p0612 import refused
from tests.lane_d.test_notes_f14 import NOTE
from tests.lane_d.test_ui_on_lane_d import post, q, ready, req, wait

STMT = "Least-privilege role probe: the coupler latch pin wears out first on this model."

pytestmark = pytest.mark.usefixtures("rtd")


@pytest.fixture(scope="module")
def ui_role(rtd):
    eng = sa.create_engine(make_url(rtd.url).set(username="mbos_operator_ui", password=None))
    yield eng
    eng.dispose()


@pytest.fixture()
def ui_least(rtd, ui_role):
    """The real HTTP server whose backend connects as the least-privilege role (same Components as the worker)."""
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


def _capital(rtd):
    with rtd.engine.connect() as c:
        r = c.execute(sa.text("SELECT earned_working_capital, realized_profit FROM mbos.v_capital_position WHERE mode = 'dry_run'")).first()
    return (float(r[0]), float(r[1])) if r else (0.0, 0.0)


def test_human_outcome_via_the_ui_path_succeeds_as_the_ui_role_and_moves_capital(rtd, discover_d, ui_d, ui_least, ui_role):
    """P-06-20 (lane D 0018, 819b5c7): the real UI role records Michael's closing outcome through POST /areq/<id>/outcome, and
    it moves capital (D-18). The capital is funded by the same role (owner channel) so no superuser shortcut is involved."""
    item_id, areq = ready(ui_d, discover_d)
    post(ui_d, areq, "YES", pin=PIN)
    wait(lambda: ui_d.store.item(item_id)["state"] == "ACTED")
    with ui_role.begin() as c:
        pid = c.execute(sa.text("SELECT provenance_id FROM mbos.provenance LIMIT 1")).scalar_one()
        c.execute(sa.text("SELECT mbos.capital_fund(100::numeric, CAST(:a AS jsonb), 'P-06-20 bankroll', ARRAY[:p], :k)"),
                  {"a": '{"type": "human", "id": "michael"}', "p": pid, "k": "p0620:" + item_id})
    before = _capital(rtd)
    s, loc, _ = req(ui_least, "POST", f"/areq/{areq['action_request_id']}/outcome",
                    {"csrf": ui_least.csrf, "kind": "flip_sold", "revenue": "250", "total_cost": "200"})
    assert s == 303 and "msg=Outcome flip_sold recorded" in loc, loc
    (o,) = ui_d.store.outcomes(item_id)
    assert o["kind"] == "flip_sold" and ui_d.store.item(item_id)["state"] == "OUTCOME_RECORDED"
    after = _capital(rtd)
    assert round(after[0] - before[0], 2) == 50.0 and round(after[1] - before[1], 2) == 50.0, (before, after)


def test_an_agent_actor_under_the_ui_role_is_refused_and_nothing_is_written(rtd, discover_d, ui_d, ui_role):
    item_id, areq = ready(ui_d, discover_d, "FIX-TRAILER-1")
    before = _capital(rtd)
    with pytest.raises(sa.exc.DBAPIError) as e:
        with ui_role.begin() as c:
            c.execute(sa.text("SELECT mbos.record_outcome(CAST(:o AS jsonb), CAST(:a AS jsonb), 'agent via UI', :k)"),
                      {"o": json.dumps({"item_id": item_id, "kind": "flip_sold", "realized": {"net_profit": 9999}}),
                       "a": '{"type": "agent", "id": "agent-x"}', "k": "p0620:agent:" + item_id})
    assert "may record only a human outcome" in str(e.value.orig)
    assert ui_d.store.outcomes(item_id) == [] and _capital(rtd) == before


def test_operator_note_by_a_human_actor_succeeds_as_the_ui_role(rtd, discover_d, ui_d, ui_least):
    item_id, _ = ready(ui_d, discover_d)
    s, loc, _ = req(ui_least, "POST", f"/item/{item_id}/note", {"csrf": ui_least.csrf, "pin": PIN, **NOTE, "statement": STMT})
    assert s == 303 and "Note saved (mn_" in loc, loc
    (n,) = [x for x in ui_d.store.operator_notes() if x["statement"] == STMT]
    assert n["entered_by"] == "michael"
    # retract as the same role (a new row): proves that path too and keeps the shared F-14 fixtures clean
    s, loc, _ = req(ui_least, "POST", f"/notes/{n['note_id']}/retract", {"csrf": ui_least.csrf, "pin": PIN, "reason": "P-06-18 probe"})
    assert s == 303 and "msg=" in loc, loc
    assert not [x for x in ui_d.store.operator_notes() if x["statement"] == STMT]


def test_forbidden_writes_are_still_refused_after_the_human_paths_ran(ui_role):
    for sql in ("INSERT INTO mbos.capital_ledger DEFAULT VALUES", "UPDATE mbos.receipts SET intent = 'edited'",
                "UPDATE mbos.items SET doc = '{}'::jsonb", "INSERT INTO mbos.budget_ledger DEFAULT VALUES"):
        assert "permission denied" in refused(ui_role, sql)


def test_the_role_cannot_edit_or_delete_operator_notes(ui_role):
    for sql in ("DELETE FROM mbos.operator_notes", "UPDATE mbos.operator_notes SET statement = 'x'"):
        assert "permission denied" in refused(ui_role, sql)
