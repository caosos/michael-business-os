"""P-06-18 (R14): the outcome-entry and operator-note paths, run through the real HTTP server on a backend whose engine
is lane D's REAL Operator UI login (`mbos_operator_ui`, non-superuser), plus the forbidden writes still refused."""

from __future__ import annotations

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


def test_outcome_entry_as_the_ui_role_is_refused_by_lane_d_FINDING(rtd, discover_d, ui_d, ui_role):
    """FINDING (lane D, migration 0004): `mbos.record_outcome` is granted to `agent_write` only, so the real UI role cannot
    record a human outcome. Pinned as observed; flip it when lane D grants the human outcome path to `approver`
    (proposed P-06-19). The same call succeeds as the shared app role (test_ui_on_lane_d)."""
    item_id, areq = ready(ui_d, discover_d)
    post(ui_d, areq, "YES", pin=PIN)
    wait(lambda: ui_d.store.item(item_id)["state"] == "ACTED")
    from mbos.runtime import components

    from operator_ui.backend import SpineBackend

    with pytest.raises(sa.exc.DBAPIError) as e:
        SpineBackend(ui_role, components(), lane="lane_d").record_outcome(item_id, "flip_sold", realized={"net_profit": 1})
    assert "permission denied for function record_outcome" in str(e.value.orig)
    assert ui_d.store.outcomes(item_id) == [] and ui_d.store.item(item_id)["state"] == "ACTED"


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
