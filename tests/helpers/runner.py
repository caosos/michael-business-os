"""Out-of-process scenarios for crash/restart tests (A5, A6). Each mode ends in os._exit, i.e. a hard
process death with no cleanup — the next process must recover from durable state alone.

    python -m tests.helpers.runner <mode> <args...>     (env: MBOS_DATABASE_URL, MBOS_SYSTEM_DATABASE_URL)
"""

from __future__ import annotations

import json
import os
import sys
import time

from dbos import DBOS, SetWorkflowID

from mbos.config import Settings
from mbos.reference.fixture_adapter import FixtureSourceAdapter
from mbos.runtime import Components, init_runtime, runtime
from tests.helpers.common import STEP_UP, pending_request, wait_state


def say(*parts) -> None:
    print(*parts, flush=True)


def _settings() -> Settings:
    return Settings(database_url=os.environ["MBOS_DATABASE_URL"],
                    system_database_url=os.environ["MBOS_SYSTEM_DATABASE_URL"], approval_poll_seconds=0.3)


def _discover_one(fixture: str) -> str:
    from mbos import workflows

    runtime().components.adapters["fx"] = FixtureSourceAdapter(fixture, name="fx")
    with SetWorkflowID("discover:fx"):
        results = DBOS.start_workflow(workflows.discover, "fx").get_result()
    item_id = next(r["item_id"] for r in results if r["created"])
    say("ITEM", item_id)
    wait_state(runtime().engine, item_id, "AWAITING_APPROVAL")
    return item_id


def crash_mid_act(fixture: str, point: str) -> None:
    """Approve YES and die inside the gateway step — before or after the effector committed."""
    import mbos.reference.governance as g

    original = g.DryRunEffector.execute

    def crashing(self, engine, areq):
        if point == "before_effector":
            say("CRASH before effector")
            os._exit(137)
        resp = original(self, engine, areq)  # effector call committed …
        say("CRASH after effector")
        os._exit(137)  # … but the process dies before DBOS checkpoints the step
        return resp

    g.DryRunEffector.execute = crashing
    init_runtime(_settings(), Components())
    from mbos import workflows

    item_id = _discover_one(fixture)
    areq = pending_request(runtime().engine, item_id)
    workflows.record_decision(areq["action_request_id"], "YES", areq["payload_hash"], auth_context=STEP_UP)
    time.sleep(60)
    say("ERROR: did not crash")
    os._exit(3)


def hold_then_die(fixture: str) -> None:
    init_runtime(_settings(), Components())
    from mbos import workflows

    item_id = _discover_one(fixture)
    areq = pending_request(runtime().engine, item_id)
    workflows.record_decision(areq["action_request_id"], "HOLD", areq["payload_hash"],
                              hold={"hold_until": "2099-01-01T00:00:00Z", "wake_on": ["michael_ping"],
                                    "renotify_after": "PT1H", "escalate_after": "P30D"})
    wait_state(runtime().engine, item_id, "HELD")
    say("HELD")
    os._exit(0)


def resume(item_id: str, action: str) -> None:
    """Restart: launching DBOS recovers every PENDING workflow from the system database."""
    init_runtime(_settings(), Components())
    from mbos import workflows
    from tests.helpers.common import item_state

    engine = runtime().engine
    if action == "result":
        say("RESULT", json.dumps(DBOS.retrieve_workflow(f"item:{item_id}").get_result()))
    elif action == "ping":
        time.sleep(1.5)  # give the recovered workflow time to prove it does NOT act on its own
        say("STATE_AFTER_RESTART", item_state(engine, item_id))
        workflows.ping(item_id)
        wait_state(engine, item_id, "AWAITING_APPROVAL")
        say("STATE_AFTER_PING", item_state(engine, item_id))
    os._exit(0)


def lane_d_e2e(fixture: str, gateway_mode: str = "reference") -> None:
    """A-01 phase 2 / A-03: the full DBOS lifecycle on lane D's canonical store (state_backend="lane_d"),
    with the spine's stand-in gateway or lane E's real ActionGateway (gateway_mode="lane_e")."""
    import dataclasses

    import sqlalchemy as sa

    from mbos import spine_d
    from mbos.adapters.state04 import Pg04Ledger
    from mbos.contracts import schemas
    from mbos.hashing import reference
    from tests.helpers.common import item_state

    s = dataclasses.replace(_settings(), state_backend="lane_d", gateway_mode=gateway_mode)
    comps, gov = Components(), None
    if gateway_mode == "lane_e":
        from mbos.adapters.governance import lane_e_components

        comps, gov = lane_e_components(s.database_url, os.environ["MBOS_POLICY_PATH"])
    if os.environ.get("MBOS_SCORER") == "engine":  # lane C's real engine (release gate AT-1)
        from mbos.adapters.economics import EconomicsEngineScorer

        comps.scorer = EconomicsEngineScorer()
    init_runtime(s, comps)
    from mbos import workflows

    engine = runtime().engine
    with engine.begin() as c:  # a fresh lane D DB is FROZEN; Michael (approver/owner) releases it, receipted
        spine_d.set_kill_switch(c, "global_freeze", False, reason="test bootstrap: Michael releases the initial FROZEN state")
    runtime().components.adapters["fx"] = FixtureSourceAdapter(fixture, name="fx")
    with SetWorkflowID("discover:fx"):
        results = DBOS.start_workflow(workflows.discover, "fx").get_result()
    ids = {r["item_id"] for r in results if r["created"]}
    with engine.connect() as c:
        by_cat = {c.execute(sa.text("SELECT category FROM mbos.items WHERE item_id = :i"), {"i": i}).scalar_one(): i for i in ids}
    final = {}
    for cat, i in by_cat.items():
        final[cat] = wait_state(engine, i, {"AWAITING_APPROVAL", "RESEARCHING", "ARCHIVED"}, timeout=60)
    trailer, smart = by_cat["trailer"], by_cat["smart_home_install"]
    awaiting = [i for i in (trailer, smart) if final[[k for k, v in by_cat.items() if v == i][0]] == "AWAITING_APPROVAL"]
    if trailer in awaiting:
        a = pending_request(engine, trailer)
        workflows.record_decision(a["action_request_id"], "YES", a["payload_hash"], auth_context=STEP_UP)
        final["trailer_after"] = wait_state(engine, trailer, {"ACTED", "FAILED"}, timeout=60)
    if smart in awaiting:
        b = pending_request(engine, smart)
        workflows.record_decision(b["action_request_id"], "NO", b["payload_hash"], reason="lane D e2e: not this week")
        final["smart_after"] = wait_state(engine, smart, "ARCHIVED", timeout=60)
    L = Pg04Ledger()
    with engine.connect() as c:
        chain = L.verify_chain(c)
        exported = L.export_receipts(c)
        calls = c.execute(sa.text("SELECT count(*) FROM mbos.effector_calls")).scalar_one()
        live = c.execute(sa.text("SELECT count(*) FROM mbos.effector_calls WHERE dry_run IS NOT TRUE")).scalar_one()
        docs = [r[0] for r in c.execute(sa.text("SELECT doc FROM mbos.v_item_documents"))]
        areqs = [r[0] for r in c.execute(sa.text("SELECT doc FROM mbos.v_action_request_documents"))]
    ref_ok, ref_msg = reference().verify_chain(exported)
    at1 = None
    if os.environ.get("MBOS_SCORER") == "engine":  # 03's AT-1 replay audit over this lane-D export (strict)
        from mbos_economics.replay_audit import audit, load_scored_items

        raw = engine.raw_connection()
        try:
            items_, receipts_ = load_scored_items(raw.driver_connection)
        finally:
            raw.close()
        rep = audit(items_, receipts=receipts_, strict=True)
        at1 = {k: rep.get(k) for k in ("ok", "drift_count", "weak_receipt_count")} | {"items": len(items_)}
    errors = [e for d in docs for e in schemas.errors("item", d)] + [e for d in areqs for e in schemas.errors("action-request", d)] \
        + [e for r in exported for e in schemas.errors("receipt", r)]
    from mbos import card as cardmod

    card_errors, card_stats = [], {}
    with engine.begin() as c:  # a lane attaches enrichment through the ledger (ADR-0011 interim convention)
        pv = L.record_provenance(c, actor_type="agent", agent_name="agent-02-opportunity", basis="FACT",
                                 tool_name="listing-activity", tool_version="0.1.0")
        spine_d.record_enrichment(c, trailer, "listing_activity", {"stale_risk": {"value": "medium", "basis": "INFERENCE"},
                                  "recent_activity": ["Seller edited the listing 8 days ago"]}, pv, agent="agent-02-opportunity")
    with engine.connect() as c:
        it_, _, _ = cardmod.load_inputs(c, trailer)
        enriched = cardmod.enrichment_from_item(c, it_)
        card_stats["enrichment_roundtrip"] = enriched.get("listing_activity", {}).get("stale_risk", {}).get("value")
    with engine.connect() as c:
        for cat, i in by_cat.items():
            it, rc, ar = cardmod.load_inputs(c, i)
            cd = cardmod.build_card(it, rc, ar, cardmod.enrichment_from_item(c, it))
            card_errors += [f"{cat}: {e}" for e in cardmod.validate_card(cd)]
            card_stats[cat] = [cd["status"]["current"], cd["recommendation"]["action"], len(cd["unknowns"]), len(cd["activity_trail"])]
    with engine.connect() as c:
        by_type = dict(c.execute(sa.text("SELECT type, count(*) FROM mbos.receipts GROUP BY type")).all())
    say("RESULT", json.dumps({"cards": card_stats, "card_errors": card_errors[:5], "at1": at1, "receipt_types": by_type, "gateway_mode": gateway_mode, "final": final, "chain": chain, "reference_chain": [ref_ok, ref_msg],
                              "effector_calls": calls, "live_effector_calls": live, "receipts": len(exported),
                              "contract_errors": errors[:5], "executed": sum(r["type"] == "ACTION_EXECUTED" for r in exported)}))
    os._exit(0)


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    try:
        {"crash_mid_act": crash_mid_act, "hold_then_die": hold_then_die, "resume": resume,
     "lane_d_e2e": lane_d_e2e}[mode](*args)
    except BaseException:  # DBOS threads are non-daemon: without a hard exit a failure would hang to the timeout
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
