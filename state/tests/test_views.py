"""D-03: reporting views (pipeline by lane, HOLD backlog, approval latency, P&L, budget, A7 audit)."""

from conftest import AGENT, GATEWAY, MICHAEL, key, make_areq, make_item, payload_hash, to_pending


def _decide(s, areq, decision, **extra):
    a = {"action_request_id": areq, "decision": decision, "decider": "michael", "channel": "web",
         "payload_hash_seen": payload_hash(s, areq), "scope": "once",
         "auth_context": {"method": "web", "step_up": True}, **extra}
    return s.record_approval(a, MICHAEL, f"Michael: {decision}", key())


def test_reporting_views(db):
    s = db.store()
    flip, pid = make_item(s, "AWAITING_APPROVAL")
    svc_id = s.create_item({"type": "service", "category": "drywall_repair", "dedup_key": key(), "sources": [],
                            "normalized": {}}, AGENT, "service lead", [pid], key())
    held = make_areq(s, flip, pid)
    to_pending(s, held, pid)
    _decide(s, held, "HOLD", hold={"hold_until": "2026-10-09T00:00:00Z", "wake_on": ["time"]})
    yes = make_areq(s, flip, pid)
    to_pending(s, yes, pid)
    _decide(s, yes, "YES")
    s.record_outcome({"item_id": flip, "kind": "flip_sold", "provenance_ids": [pid],
                      "realized": {"revenue": 900, "total_cost": 520.5, "net_profit": 379.5, "hours": 6}},
                     GATEWAY, "sold", key())
    s.budget_reserve(yes, 50, "USD", 500, GATEWAY, "reserve", [pid], key())

    q = lambda sql, *p: s.conn.execute(sql, p).fetchall()
    lanes = {(lane, state): n for lane, state, n, _ in q("SELECT * FROM mbos.v_pipeline_by_lane")}
    assert lanes == {("flip", "AWAITING_APPROVAL"): 1, ("service", "DISCOVERED"): 1}

    backlog = q("SELECT action_request_id, hold_until FROM mbos.v_hold_backlog")
    assert [r[0] for r in backlog] == [held] and backlog[0][1] is not None

    lat = q("SELECT action_request_id, decision, latency >= interval '0' FROM mbos.v_approval_latency ORDER BY decided_at")
    assert [(r[0], r[1], r[2]) for r in lat] == [(held, "HOLD", True), (yes, "YES", True)]

    pnl = q("SELECT lane, revenue, total_cost, net_profit, outcomes FROM mbos.v_pnl_by_item WHERE item_id = %s", flip)
    assert pnl == [("flip", 900, 520.5, 379.5, 1)]

    res = q("SELECT reserved, committed, released, outstanding FROM mbos.v_budget_reservations")
    assert res == [(50, 0, 0, 50)]
    assert q("SELECT count(*) FROM mbos.v_a7_live_effects") == [(0,)]

    # read-only role sees every view; the chain under them verifies (ADR-0010)
    r = db.connect("reader")
    for v in ("v_pipeline_by_lane", "v_hold_backlog", "v_approval_latency", "v_pnl_by_item",
              "v_budget_reservations", "v_a7_live_effects", "policy_current", "v_receipt_documents"):
        r.execute(f"SELECT * FROM mbos.{v} LIMIT 1")
    assert s.verify_chain().ok
