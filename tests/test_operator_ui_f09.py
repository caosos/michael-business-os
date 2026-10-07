"""F-09: outcome entry (spine.record_outcome), HOLD backlog, read-only source health. Real spine (mbos @ c23bee8)."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import pytest

from operator_ui import server, ux
from operator_ui.sources import load_health
from tests.conftest import PIN
from tests.test_operator_ui import approvals, item_state, open_request, post, q, ready, req, wait_state


def acted(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    post(ui, areq, "YES", pin=PIN)
    wait_state(rt.engine, item_id, "ACTED")
    return item_id, areq


# ---------------------------------------------------------------- outcome entry
def test_outcome_entry_records_via_spine_with_learn_pairs(rt, discover, ui):
    item_id, areq = acted(rt, discover, ui)
    _, _, body = req(ui, "GET", f"/areq/{areq['action_request_id']}")
    assert "Record outcome" in body and "flip_sold" in body and "service_won" not in body
    _, loc, _ = req(ui, "POST", f"/areq/{areq['action_request_id']}/outcome",
                    {"csrf": ui.csrf, "kind": "flip_sold", "revenue": "$2,050", "total_cost": "1100", "hours": "7.5",
                     "days_to_cash": "12", "notes": "sold to a <b>neighbor</b>"})
    assert "msg=Outcome flip_sold recorded" in loc, loc
    ((o,),) = q(rt.engine, "SELECT body FROM mbos.outcomes WHERE body->>'item_id' = :i", i=item_id)
    assert o["realized"] == {"revenue": 2050, "total_cost": 1100, "hours": 7.5, "days_to_cash": 12, "net_profit": 950}
    fields = {p["field"]: p for p in o["predicted_vs_actual"]}
    item = q(rt.engine, "SELECT body FROM mbos.items WHERE item_id = :i", i=item_id)[0][0]
    assert fields["resale.target_sell_price"]["predicted"] == item["economics"]["resale"]["target_sell_price"]
    assert fields["resale.target_sell_price"]["actual"] == 2050 and fields["rehab.labor_hours"]["actual"] == 7.5
    assert item_state(rt.engine, item_id) == "OUTCOME_RECORDED"
    ((r,),) = q(rt.engine, "SELECT body FROM mbos.receipts WHERE item_id = :i AND type = 'OUTCOME_RECORDED'", i=item_id)
    assert r["actor"] == {"type": "human", "id": "michael"} and r["outcome_id"] == o["outcome_id"]
    _, _, card = req(ui, "GET", f"/areq/{areq['action_request_id']}")
    assert "flip_sold" in card and "resale.target_sell_price" in card and "&lt;b&gt;neighbor" in card
    _, _, page = req(ui, "GET", "/outcomes")
    assert "flip_sold" in page and "950" in page


@pytest.mark.parametrize("form,err", [
    ({"kind": "service_won"}, "not valid for a flip"),
    ({"kind": "flip_sold", "revenue": "lots"}, "revenue must be a number"),
    ({"kind": "flip_sold", "total_cost": "-5"}, "between 0"),
])
def test_outcome_validation(rt, discover, ui, form, err):
    _, areq = acted(rt, discover, ui)
    _, loc, _ = req(ui, "POST", f"/areq/{areq['action_request_id']}/outcome", {"csrf": ui.csrf, **form})
    assert "err=" in loc and err in loc, loc
    assert q(rt.engine, "SELECT count(*) FROM mbos.outcomes WHERE body->>'item_id' = :i", i=areq["item_id"])[0][0] == 0


def test_outcome_refused_before_settled_and_without_csrf(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    _, _, body = req(ui, "GET", f"/areq/{areq['action_request_id']}")
    assert "Outcome entry opens once the item has settled" in body
    _, loc, _ = req(ui, "POST", f"/areq/{areq['action_request_id']}/outcome", {"csrf": ui.csrf, "kind": "flip_sold"})
    assert "err=the item is AWAITING_APPROVAL" in loc
    _, loc, _ = req(ui, "POST", f"/areq/{areq['action_request_id']}/outcome", {"kind": "flip_sold"})
    assert "err=invalid form token" in loc
    assert req(ui, "POST", f"/areq/{areq['action_request_id']}/outcome",
               {"csrf": ui.csrf, "kind": "flip_sold"}, host="evil.example")[0] == 403


def test_service_outcome_kinds_and_win_prob_pair():
    item = {"type": "service", "economics": {"job": {"win_prob": 0.6, "labor_hours": 4}}}
    kind, kw = ux.parse_outcome(item, {"kind": "service_won", "hours": "5"})
    pairs = {p["field"]: p for p in kw["predicted_vs_actual"]}
    assert pairs["job.win_prob"] == {"field": "job.win_prob", "predicted": 0.6, "actual": 1}
    assert pairs["job.labor_hours"]["actual"] == 5
    with pytest.raises(ux.InputError):
        ux.parse_outcome(item, {"kind": "flip_sold"})


# ---------------------------------------------------------------- HOLD backlog
def test_hold_backlog_lists_held_requests_read_only(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    post(ui, areq, "HOLD", hold_preset="3d", reason="waiting on <photos>")
    wait_state(rt.engine, item_id, "HELD")
    s, _, body = req(ui, "GET", "/holds")
    assert s == 200 and areq["action_request_id"] in body and "&lt;photos&gt;" in body
    hold = approvals(rt.engine, areq["action_request_id"])[0]["hold"]
    assert hold["hold_until"] in body and "<form" not in body


def test_hold_backlog_flags_overdue():
    now = datetime(2026, 10, 7, 17, 0, tzinfo=timezone.utc)
    row = {"action_request": {"action_request_id": "areq_X", "capability": "comms.email.send"},
           "item": {"type": "flip", "normalized": {"title": "t"}},
           "hold": {"hold_until": "2026-10-07T12:00:00Z", "wake_on": ["time"]}, "held_at": "x", "reason": None}
    html = server.render_holds([row], now)
    assert "OVERDUE" in html and "1 hold(s) past their wake time" in html
    assert "OVERDUE" not in server.render_holds([dict(row, hold={"hold_until": "2026-10-09T12:00:00Z"})], now)


# ---------------------------------------------------------------- source health (lane B data, read-only)
HEALTH = {
    "ebay": {"source": "ebay", "status": "HEALTHY", "consecutive_failures": 0, "consecutive_blocks": 0, "total_runs": 12,
             "total_failures": 1, "last_run_at": "2026-10-07T16:00:00Z", "last_success_at": "2026-10-07T16:00:00Z",
             "last_error": None, "last_items_seen": 40, "frozen_at": None, "freeze_reason": None},
    "craigslist": {"source": "craigslist", "status": "FROZEN", "consecutive_failures": 2, "consecutive_blocks": 2,
                   "total_runs": 9, "total_failures": 3, "last_run_at": "2026-10-07T15:00:00Z",
                   "last_success_at": "2026-10-06T15:00:00Z",
                   "last_error": {"kind": "blocked", "status": 403, "message": "<script>alert(1)</script>", "at": "x"},
                   "last_items_seen": 0, "frozen_at": "2026-10-07T15:00:00Z",
                   "freeze_reason": "blocked (status 403) x2 — stop; no evasion; human must clear"},
    "govdeals": {"source": "govdeals", "status": "WEIRD"},
}


def test_source_health_panel(rt, ui, tmp_path):
    f = tmp_path / "health.json"
    f.write_text(json.dumps(HEALTH))
    ui.health_file = str(f)
    s, _, body = req(ui, "GET", "/sources")
    assert s == 200 and "3 sources, 1 frozen" in body
    assert body.index("UNKNOWN(WEIRD)") < body.index("craigslist") < body.index("ebay")  # worst first; unknown is worst
    assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body
    assert "human must clear" in body and "<form" not in body.split("<main>")[1]  # read-only
    old = time.time() - 3 * 86400
    os.utime(f, (old, old))
    assert "STALE" in req(ui, "GET", "/sources")[2]


def test_source_health_missing_or_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("MBOS_SOURCE_HEALTH_FILE", raising=False)
    assert load_health(None)["error"] == "MBOS_SOURCE_HEALTH_FILE not set"
    assert load_health(str(tmp_path / "nope.json"))["error"] == "health file not found"
    (tmp_path / "bad.json").write_text("[1,2]")
    assert "unexpected format" in load_health(str(tmp_path / "bad.json"))["error"]
    (tmp_path / "junk.json").write_text("{not json")
    assert load_health(str(tmp_path / "junk.json"))["error"].startswith("unreadable")


def test_new_pages_keep_the_human_channel_guards(rt, ui):
    for path in ("/holds", "/sources", "/outcomes"):
        assert req(ui, "GET", path, host="evil.example")[0] == 403
        assert req(ui, "GET", path)[0] == 200
