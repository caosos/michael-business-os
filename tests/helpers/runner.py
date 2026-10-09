"""Out-of-process scenarios for crash/restart tests (A5, A6). Each mode ends in os._exit, i.e. a hard
process death with no cleanup — the next process must recover from durable state alone.

    python -m tests.helpers.runner <mode> <args...>     (env: MBOS_DATABASE_URL, MBOS_SYSTEM_DATABASE_URL)
"""

from __future__ import annotations

import json
import pathlib
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
                    system_database_url=os.environ["MBOS_SYSTEM_DATABASE_URL"], approval_poll_seconds=0.3,
                    owner_database_url=os.environ.get("MBOS_OWNER_DATABASE_URL") or None)


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


def _budgets(node) -> list:
    """Every numeric value under a key containing 'budget', wherever it sits in lane E's LiteLLM spec."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if "budget" in str(k).lower() and isinstance(v, (int, float)):
                out.append(v)
            else:
                out += _budgets(v)
    elif isinstance(node, list):
        for v in node:
            out += _budgets(v)
    return out


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

        from dbos import DBOS as _D

        from mbos.adapters.governance import role_dsns

        comps, gov = lane_e_components(role_dsns(s.database_url, os.environ.get("MBOS_OWNER_DATABASE_URL")), os.environ["MBOS_POLICY_PATH"], dbos=_D,
                                       egress_file=os.environ.get("MBOS_EGRESS_FILE"), litellm_file=os.environ.get("MBOS_LITELLM_FILE"))
    if os.environ.get("MBOS_SCORER") == "engine":  # lane C's real engine (release gate AT-1)
        from mbos.adapters.economics import EconomicsEngineScorer

        comps.scorer = EconomicsEngineScorer()
    init_runtime(s, comps)
    from mbos import workflows

    engine = runtime().engine
    def owner_begin():  # D-26: Michael's actions use the OWNER login; the workflow login holds no approver
        url = os.environ.get("MBOS_OWNER_DATABASE_URL")
        if not url:
            return engine.begin()
        from mbos.db.engine import engine_for
        return engine_for(url).begin()

    with owner_begin() as c:  # a fresh lane D DB is FROZEN; Michael (approver/owner) releases it, receipted
        spine_d.set_kill_switch(c, "global_freeze", False, reason="test bootstrap: Michael releases the initial FROZEN state")
    sched = runtime().reconcile_schedule
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
    followup = None
    if trailer in awaiting and final.get("trailer_after") == "ACTED":  # A-15: a follow-up on the item that already acted
        fu = workflows.propose_followup(trailer, {"capability": "comms.email.send", "reversibility": "irreversible",
                                                  "summary": "Follow up: still available? (DRY-RUN draft)",
                                                  "estimated_cost": {"amount": 0, "currency": "USD"}})
        wait_state(engine, trailer, "AWAITING_APPROVAL", timeout=60)
        f2 = pending_request(engine, trailer)
        workflows.record_decision(f2["action_request_id"], "YES", f2["payload_hash"], auth_context=STEP_UP)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 60:
            with engine.connect() as c:
                n = c.execute(sa.text("SELECT count(*) FROM mbos.receipts WHERE item_id = :i AND type = 'ACTION_EXECUTED'"), {"i": trailer}).scalar_one()
            if n >= 2:
                break
            time.sleep(0.3)
        wait_state(engine, trailer, "ACTED", timeout=30)
        followup = {"policy_denied": fu["policy_denied"], "executed_receipts": n, "second_request": f2["action_request_id"] != a["action_request_id"]}
        # 07 F-45: concurrent follow-ups on one ACTED item -> exactly ONE live request (lane D row lock)
        import threading

        outs, refused = [], []

        def _go():
            try:
                outs.append(workflows.propose_followup(trailer, {"capability": "comms.email.send", "reversibility": "irreversible",
                                                                 "summary": "concurrent follow-up (DRY-RUN draft)",
                                                                 "estimated_cost": {"amount": 0, "currency": "USD"}}))
            except Exception as e:  # noqa: BLE001
                refused.append(type(e).__name__)

        ths = [threading.Thread(target=_go) for _ in range(6)]
        [t_.start() for t_ in ths]
        [t_.join() for t_ in ths]
        with engine.connect() as c:
            live = c.execute(sa.text("SELECT count(*) FROM mbos.action_requests WHERE item_id = :i AND status = 'pending_approval'"),
                             {"i": trailer}).scalar_one()
        followup["concurrent"] = {"accepted": len(outs), "refused": refused, "live_pending": live}
        if live:  # leave the item settled: Michael says NO to the concurrent one
            f3 = pending_request(engine, trailer)
            workflows.record_decision(f3["action_request_id"], "NO", f3["payload_hash"], reason="e2e cleanup")
    if smart in awaiting:
        b = pending_request(engine, smart)
        workflows.record_decision(b["action_request_id"], "NO", b["payload_hash"], reason="lane D e2e: not this week")
        final["smart_after"] = wait_state(engine, smart, "ARCHIVED", timeout=60)
    panic = None
    if gateway_mode == "lane_e":  # A-18: PANIC through lane E (hooks), then Michael releases as approver
        with engine.begin() as c:
            eng = spine_d.set_kill_switch(c, "global_freeze", True, reason="A-18 drill: engage L3")
        egress = json.loads(pathlib.Path(os.environ["MBOS_EGRESS_FILE"]).read_text())
        lite = json.loads(pathlib.Path(os.environ["MBOS_LITELLM_FILE"]).read_text())
        with engine.connect() as c:
            frozen_now = c.execute(sa.text("SELECT mbos.panic_blocks('agent-x', 'comms.email.send', 'email')")).scalar_one()
        with owner_begin() as c:
            rel = spine_d.set_kill_switch(c, "global_freeze", False, reason="A-18 drill: all clear")
        with engine.connect() as c:
            clear_now = c.execute(sa.text("SELECT mbos.panic_blocks('agent-x', 'comms.email.send', 'email')")).scalar_one()
        panic = {"engage_error": eng.get("error"), "frozen_blocks": bool(frozen_now), "released_blocks": bool(clear_now),
                 "egress_file": egress, "litellm_budgets": _budgets(lite),
                 "release_error": rel.get("error")}
    import pathlib as _p  # noqa: F401
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
        who = c.execute(sa.text("SELECT session_user, (SELECT rolsuper FROM pg_roles WHERE rolname = session_user)")).one()
        wroles = list(c.execute(sa.text("SELECT pg_has_role(session_user,'approver','MEMBER'), pg_has_role(session_user,'owner_channel','MEMBER')")).one())
    oroles = None
    if os.environ.get("MBOS_OWNER_DATABASE_URL"):
        from mbos.db.engine import engine_for
        with engine_for(os.environ["MBOS_OWNER_DATABASE_URL"]).connect() as oc:
            oroles = list(oc.execute(sa.text("SELECT pg_has_role(session_user,'approver','MEMBER'), pg_has_role(session_user,'owner_channel','MEMBER')")).one())
    id_addressable = sum(1 for r in exported if r["type"] in ("SCORE_RECORDED", "RECOMMENDATION_RECORDED")
                         and r.get("entity_type") in ("scorecard", "recommendation") and r.get("entity_id", "")[:4] in ("scr_", "rec_"))
    scored = sum(1 for r in exported if r["type"] in ("SCORE_RECORDED", "RECOMMENDATION_RECORDED"))
    say("RESULT", json.dumps({"db_login": [who[0], bool(who[1])], "roles": {"worker": [bool(x) for x in wroles], "owner": oroles}, "followup": followup, "id_addressable": [id_addressable, scored], "panic": panic, "reconcile_schedule": sched, "cards": card_stats, "card_errors": card_errors[:5], "at1": at1, "receipt_types": by_type, "gateway_mode": gateway_mode, "final": final, "chain": chain, "reference_chain": [ref_ok, ref_msg],
                              "effector_calls": calls, "live_effector_calls": live, "receipts": len(exported),
                              "contract_errors": errors[:5], "executed": sum(r["type"] == "ACTION_EXECUTED" for r in exported)}))
    os._exit(0)


def training_set(fixture: str) -> None:
    """A-41: the ILLUSTRATIVE training set through the REAL assembly (`production.build_components`: lane C engine fed by the funded ledger,
    lane E gateway) on lane D. Reports each deal's state/verdict/gate text, the attestation path and every card's validity and labels."""
    import dataclasses

    import sqlalchemy as sa
    from dbos import DBOS as _D

    from mbos import card as cardmod, spine_d, workflows
    from mbos.db.engine import engine_for
    from mbos.production import build_components
    from tests.helpers.common import item_state

    s = dataclasses.replace(_settings(), state_backend="lane_d", gateway_mode="lane_e")
    owner = engine_for(os.environ["MBOS_OWNER_DATABASE_URL"])
    with owner.begin() as c:  # Michael's side, before the worker assembly exists (the worker holds no approver login)
        spine_d.set_kill_switch(c, "global_freeze", False, reason="test bootstrap: Michael releases the initial FROZEN state")
        spine_d.fund_bankroll(c, 500, reason="A-41 dry-run bankroll", idempotency_key="a41-bankroll")
    comps, report = build_components(s, dbos=_D)
    init_runtime(s, comps)
    engine = runtime().engine
    runtime().components.adapters["fx"] = FixtureSourceAdapter(fixture, name="fx")
    with SetWorkflowID("discover:fx"):
        results = DBOS.start_workflow(workflows.discover, "fx").get_result()
    ids = {r["item_id"] for r in results if r["created"]}
    names = {}
    with engine.connect() as c:
        for i in ids:
            names[c.execute(sa.text("SELECT doc->'sources'->0->>'source_listing_id' FROM mbos.v_item_documents WHERE item_id = :i"), {"i": i}).scalar_one()] = i
    settled = {"AWAITING_APPROVAL", "RESEARCHING", "ARCHIVED"}

    def snap(item_id: str) -> dict:
        with engine.connect() as c:
            item, receipts, areqs = cardmod.load_inputs(c, item_id)
            enr = cardmod.enrichment_from_item(c, item)
        card = cardmod.build_card(item, receipts, areqs, enr)
        sc = item["scores"]["scorecard"]
        return {"state": item["state"], "verdict": item["recommendation"]["verdict"], "rationale": item["recommendation"]["rationale"],
                "cheapest": sc.get("cheapest_decisive_evidence"), "gates": sc.get("gates"), "pass_on_priors": sc.get("pass_on_priors"),
                "card_errors": cardmod.validate_card(card), "card": card}

    first = {}
    for lid, i in names.items():
        wait_state(engine, i, settled, timeout=60)
        first[lid] = snap(i)
    lead = names["TRAIN-LEAD-DRYWALL-1"]
    with owner.begin() as c:  # D-29: attestation is the owner login's act
        for key in ("scope_verified", "customer_screened"):
            spine_d.record_attestation(c, lead, key, f"Michael confirmed {key} (A-41 test)", "michael")
    workflows.recheck([lead])
    time.sleep(1.0)
    wait_state(engine, lead, {"AWAITING_APPROVAL", "ARCHIVED"}, timeout=60)
    after = snap(lead)
    cap = engine.connect().execute(sa.text("SELECT mbos.capital_position_document('dry_run')")).scalar()
    say("RESULT", json.dumps({"report": report, "first": first, "lead_after": after, "capital": cap}, default=str))
    os._exit(0)


def ui_act(action: str, *args: str) -> None:
    """A-49: one Operator UI action in its OWN process (no DBOS runtime), exactly as `operator_ui.backend` does it: the owner login writes in
    one transaction, then `mbos.workflows` wakes the gate through a DBOSClient. Michael's side only."""
    import sqlalchemy as sa

    from mbos import spine_d, workflows
    from mbos.config import configure, settings
    from mbos.db.engine import engine_for

    configure(settings())  # env: MBOS_DATABASE_URL / MBOS_SYSTEM_DATABASE_URL / MBOS_OWNER_DATABASE_URL
    owner = engine_for(os.environ["MBOS_OWNER_DATABASE_URL"])
    if action in ("HOLD", "YES"):
        (item_id,) = args
        with owner.connect() as c:
            a = c.execute(sa.text("SELECT action_request_id, payload_hash FROM mbos.action_requests WHERE item_id = :i "
                                  "AND status IN ('pending_approval', 'held') ORDER BY created_at DESC LIMIT 1"), {"i": item_id}).one()
        kw = {"hold": {"hold_until": "2099-01-01T00:00:00Z", "wake_on": ["michael_ping"], "renotify_after": "PT6H"}} if action == "HOLD" \
            else {"auth_context": STEP_UP}
        with owner.begin() as c:  # backend.decide: spine.decide in ONE transaction, then the wake-up
            out = spine_d.decide(c, a.action_request_id, action, a.payload_hash, None, channel="web", **kw)
        workflows.notify_decision(out["item_id"], out["approval"]["approval_id"])
    elif action == "ping":  # backend.ping ("Wake now")
        workflows.ping(args[0])
    elif action == "attest":
        with owner.begin() as c:
            spine_d.record_attestation(c, args[0], args[1], f"Michael confirmed {args[1]} (A-49)", "michael")
    elif action == "quote":
        with owner.begin() as c:
            spine_d.record_human_input(c, args[0], "quote", "amount_usd", float(args[1]), "quoted by phone (A-49)", "michael")
    say("UI_OK", action)
    sys.stdout.flush()
    os._exit(0)


def hold_paths(fixture: str) -> None:
    """A-49 (F-126, F-129): the real assembly on lane D with split logins; every Michael action runs in a separate UI process (`ui_act`).
    TV: HOLD, then YES straight from the HOLD list (no wake). Drywall lead: a quote (both worker watchers fire on it), two attestations,
    then HOLD -> Wake now -> YES. Reports states, receipts, the rechecks started and every ERROR log record / ERROR workflow."""
    import dataclasses
    import logging
    import subprocess

    import sqlalchemy as sa
    from dbos import DBOS as _D

    from mbos import cli, spine_d, workflows
    from mbos.adapters.state04 import Pg04Ledger
    from mbos.db.engine import engine_for
    from mbos.inbox import HumanInputWatcher, ResearchWatcher
    from mbos.production import build_components
    from tests.helpers.common import ROOT, receipts_for

    errors: list[str] = []

    class _Errors(logging.Handler):
        def emit(self, record):
            errors.append(f"{record.name}: {record.getMessage()[:300]}")

    logging.getLogger().addHandler(_Errors(level=logging.ERROR))
    logging.getLogger("dbos").addHandler(_Errors(level=logging.ERROR))

    def ui(*a: str) -> None:
        cp = subprocess.run([sys.executable, "-m", "tests.helpers.runner", "ui_act", *a], cwd=ROOT, env=os.environ.copy(),
                            capture_output=True, text=True, timeout=60)
        if cp.returncode != 0 or "UI_OK" not in cp.stdout:
            raise RuntimeError(f"ui_act {a} failed:\n{cp.stdout[-2000:]}\n{cp.stderr[-4000:]}")

    s = dataclasses.replace(_settings(), state_backend="lane_d", gateway_mode="lane_e")
    os.environ.update(MBOS_STATE_BACKEND="lane_d", MBOS_GATEWAY_MODE="lane_e")  # inherited by the UI processes
    owner = engine_for(os.environ["MBOS_OWNER_DATABASE_URL"])
    with owner.begin() as c:
        spine_d.set_kill_switch(c, "global_freeze", False, reason="test bootstrap: Michael releases the initial FROZEN state")
        spine_d.fund_bankroll(c, 500, reason="A-49 dry-run bankroll", idempotency_key="a49-bankroll")
    comps, _ = build_components(s, dbos=_D)
    init_runtime(s, comps)
    engine = runtime().engine
    runtime().components.adapters["fx"] = FixtureSourceAdapter(fixture, name="fx")
    with SetWorkflowID("discover:fx"):
        results = DBOS.start_workflow(workflows.discover, "fx").get_result()
    names = {}
    with engine.connect() as c:
        for r in results:
            if r["created"]:
                names[c.execute(sa.text("SELECT doc->'sources'->0->>'source_listing_id' FROM mbos.v_item_documents WHERE item_id = :i"),
                                {"i": r["item_id"]}).scalar_one()] = r["item_id"]
    tv, lead = names["TRAIN-TV-1"], names["TRAIN-LEAD-DRYWALL-1"]
    out: dict = {"first": {"tv": wait_state(engine, tv, {"AWAITING_APPROVAL", "RESEARCHING", "ARCHIVED"}, timeout=60),
                           "lead": wait_state(engine, lead, {"AWAITING_APPROVAL", "RESEARCHING", "ARCHIVED"}, timeout=60)}}

    # (a) HOLD, then YES directly from the HOLD list
    ui("HOLD", tv)
    out["tv_held"] = wait_state(engine, tv, "HELD")
    ui("YES", tv)
    out["tv_final"] = wait_state(engine, tv, {"ACTED", "FAILED"}, timeout=60)
    out["tv_executed"] = len(receipts_for(engine, item_id=tv, type="ACTION_EXECUTED"))

    # F-129: the worker loop's watchers, as `mbos worker` runs them (each tick queues through `workflows.recheck`)
    rw = ResearchWatcher(cli._parked_research_lengths, workflows.recheck)
    hw = HumanInputWatcher(cli._parked_human_input_counts, workflows.recheck)
    rw.tick(), hw.tick()  # baseline
    queued: list[list[str]] = []
    ui("quote", lead, "700")
    queued.append(rw.tick() + hw.tick())  # ONE input that both watchers see in the same loop round
    time.sleep(1.0)
    ui("attest", lead, "scope_verified")
    queued.append(rw.tick() + hw.tick())
    ui("attest", lead, "customer_screened")
    queued.append(rw.tick() + hw.tick())
    out["lead_after_inputs"] = wait_state(engine, lead, {"AWAITING_APPROVAL", "ARCHIVED"}, timeout=90)
    out["queued"] = queued

    # (b) HOLD -> Wake now (from the UI process) -> YES
    ui("HOLD", lead)
    out["lead_held"] = wait_state(engine, lead, "HELD")
    ui("ping", lead)
    out["lead_woken"] = wait_state(engine, lead, "AWAITING_APPROVAL")
    ui("YES", lead)
    out["lead_final"] = wait_state(engine, lead, {"ACTED", "FAILED"}, timeout=60)
    out["lead_executed"] = len(receipts_for(engine, item_id=lead, type="ACTION_EXECUTED"))

    # F-129: two writers of the same provenance record at once (two rechecks racing): the second waits, then finds it stored, no error
    import threading

    from mbos.clock import now_iso
    from mbos.ids import new_id

    doc = {"provenance_id": new_id("prov"), "created_at": now_iso(), "actor_type": "system", "agent_name": "a49-race", "basis": "FACT",
           "tool_name": "a49.race", "tool_version": "0.1.0"}
    race: dict = {}

    def second():
        try:
            with engine.begin() as cb:
                race["second"] = spine_d.record_lane_provenance(cb, doc)
        except Exception as e:  # noqa: BLE001
            race["second"] = f"{type(e).__name__}: {e}"[:300]

    with engine.connect() as ca:
        first = ca.begin()
        spine_d.L.record_provenance(ca, **doc)
        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.5)  # the second insert is now blocked on the first's uncommitted row
        first.commit()
        t.join(10)
    out["provenance_race"] = race.get("second") == doc["provenance_id"] or race.get("second")

    time.sleep(1.0)
    rechecks = DBOS.list_workflows(workflow_id_prefix=f"recheck:{lead}:", load_input=False, load_output=False)
    out["rechecks"] = sorted({w.workflow_id.split("-")[0] for w in rechecks})
    out["error_workflows"] = [(w.workflow_id, w.status, str(w.error)[:300]) for w in
                              DBOS.list_workflows(status="ERROR", load_input=False, load_output=False)]
    with engine.connect() as c:
        out["chain"] = Pg04Ledger().verify_chain(c)
    out["error_logs"] = errors
    say("RESULT", json.dumps(out, default=str))
    os._exit(0)


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    try:
        {"crash_mid_act": crash_mid_act, "hold_then_die": hold_then_die, "resume": resume,
     "lane_d_e2e": lane_d_e2e, "training_set": training_set, "hold_paths": hold_paths, "ui_act": ui_act}[mode](*args)
    except BaseException:  # DBOS threads are non-daemon: without a hard exit a failure would hang to the timeout
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
