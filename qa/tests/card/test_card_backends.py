"""G-05 on REAL flows, both backends (reference | lane D + lane E, chosen by MBOS_QA_STATE_BACKEND / _GATEWAY_MODE).
The card is loaded exactly as the CLI/UI do (`load_inputs`, `enrichment_from_item`), then checked against the ledger
read independently through the QA facade."""
import json
import uuid

import pytest

from mbos_qa.impl_spine import LANE_D, LANE_E

from .conftest import CONTROL, independent_schema_errors

FLIP, SERVICE, MAYBE, PASS_ = "FIX-TRAILER-1", "FIX-LEAD-SMARTHOME-1", "FIX-LEAD-DRYWALL-1", "FIX-MOWER-1"
STAGE_FOR_STATE = {"AWAITING_APPROVAL": "AWAITING MICHAEL", "HELD": "AWAITING MICHAEL", "ARCHIVED": "PASSED",
                   "REJECTED": "PASSED", "OUTCOME_RECORDED": "CLOSED", "LEARNED": "CLOSED"}


def card_for(qa, mc, item_id, engine=None):
    eng = engine or qa.engine
    with eng.connect() as c:
        item, receipts, areqs = mc.load_inputs(c, item_id)
        enr = mc.enrichment_from_item(c, item)
    return mc.build_card(item, receipts, areqs, enr), receipts, areqs


def related_receipts(qa, item_id):
    """Every receipt about the item: by item_id, plus any tied to one of its action requests."""
    rs = {r["receipt_id"]: r for r in qa.receipts(item_id=item_id)}
    for a in qa.areqs(item_id=item_id):
        for r in qa.receipts(action_request_id=a["action_request_id"]):
            rs[r["receipt_id"]] = r
    return sorted(rs.values(), key=lambda r: r["seq"])


def flow(qa, kind):
    if kind == "pending":
        i = qa.discover(FLIP)
        qa.pending(i)
        return i
    if kind == "service_pending":
        i = qa.discover(SERVICE)
        qa.pending(i)
        return i
    if kind == "maybe":
        return qa.discover(MAYBE)
    if kind == "pass":
        return qa.discover(PASS_)
    i = qa.discover(FLIP)
    a = qa.pending(i)
    rid = a["action_request_id"]
    if kind == "yes":
        qa.decide(rid, "YES")
        qa.wait_state(i, {"ACTED", "FAILED"})
    elif kind == "no":
        qa.decide(rid, "NO", reason="QA: not this one")
        qa.wait_state(i, "ARCHIVED")
    elif kind == "hold":
        qa.decide(rid, "HOLD", step_up=False, hold={"hold_until": "2099-01-01T00:00:00Z", "wake_on": ["michael_ping"],
                                                     "renotify_after": "PT1H", "escalate_after": "P30D"})
        qa.wait_state(i, "HELD")
    elif kind == "modify":
        qa.decide(rid, "MODIFY", step_up=False, new_payload={**a["payload"], "summary": a["payload"]["summary"] + " (modified)"})
        qa.wait_state(i, "AWAITING_APPROVAL")
    elif kind == "frozen":
        qa.freeze("global_freeze", True)
        try:
            qa.decide(rid, "YES")
            qa.wait_state(i, {"ACTED", "FAILED"})
        finally:
            qa.freeze("global_freeze", False)
    return i


FLOWS = ["pending", "service_pending", "maybe", "pass", "yes", "no", "hold", "modify", "frozen"]


@pytest.fixture(scope="module")
def made(qa):
    return {k: flow(qa, k) for k in FLOWS}


@pytest.mark.parametrize("kind", FLOWS)
def test_card_is_valid_and_its_trail_is_the_ledger_one_to_one(qa, mc, made, kind):
    item_id = made[kind]
    card, receipts, _ = card_for(qa, mc, item_id)
    assert independent_schema_errors(card) == [], independent_schema_errors(card)[:3]
    assert mc.validate_card(card) == []
    mc.render_text(card)
    expected = [r["receipt_id"] for r in related_receipts(qa, item_id)]
    got = [t["receipt_id"] for t in card["activity_trail"]]
    assert got == expected, f"trail != ledger: missing {sorted(set(expected) - set(got))[:3]}, extra {sorted(set(got) - set(expected))[:3]}"
    for t in card["activity_trail"]:
        assert t["inputs"], t
        for p in t["inputs"]:
            assert qa.find_provenance(p) is not None, f"trail row cites missing provenance {p}"
    stages = {s["stage"] for s in card["status"]["timeline"]} | {card["status"]["current"]}
    assert not stages & {"NEGOTIATING", "QUALIFIED"}
    ledger_ts = {r["receipt_id"]: r["ts"] for r in related_receipts(qa, item_id)}
    assert all(ledger_ts[s["receipt_id"]] == s["at"] for s in card["status"]["timeline"])
    state = qa.item(item_id)["state"]
    if state in STAGE_FOR_STATE:
        assert card["status"]["current"] == STAGE_FOR_STATE[state], (state, card["status"]["current"])


def test_after_a_dry_run_execution_the_card_never_says_the_seller_was_contacted(qa, mc, made):
    card, _, _ = card_for(qa, mc, made["yes"])
    assert qa.item(made["yes"])["state"] in ("ACTED", "OUTCOME_RECORDED")
    stages = [s["stage"] for s in card["status"]["timeline"]]
    text = mc.render_text(card)
    assert "CONTACT SENT" not in stages and "WAIT FOR RESPONSE" not in text, \
        f"dry-run execution presented as contact: stages={stages}"


def test_michaels_yes_shows_up_as_contact_approved(qa, mc, made):
    card, _, _ = card_for(qa, mc, made["yes"])
    assert "CONTACT APPROVED" in [s["stage"] for s in card["status"]["timeline"]]


def test_an_item_stopped_by_a_freeze_says_so(qa, mc, made):
    card, _, _ = card_for(qa, mc, made["frozen"])
    assert qa.item(made["frozen"])["state"] == "FAILED"
    text = mc.render_text(card).lower()
    assert "did not execute" in text or "denied" in text or "freeze" in text or "failed" in text
    assert card["recommendation"]["action"] != "PASS" or "no further action" not in card["recommendation"]["why"].lower()
    assert card["recommendation"]["waiting"] is False


def test_building_the_card_writes_nothing(qa, mc, made):
    tables = ["receipts", "items", "action_requests", "approvals", "provenance", "outcomes", "outbox", "artifacts"]
    before = {t: qa.scalar(f"SELECT count(*) FROM mbos.{t}") for t in tables}
    state = qa.item(made["pending"])["state"]
    for _ in range(3):
        card, _, _ = card_for(qa, mc, made["pending"])
        mc.validate_card(card)
        mc.render_text(card)
    assert {t: qa.scalar(f"SELECT count(*) FROM mbos.{t}") for t in tables} == before
    assert qa.item(made["pending"])["state"] == state and qa.verify_chain()["ok"]


def test_the_card_carries_no_authority_and_does_not_decide(qa, mc, made):
    for kind in ("pending", "yes", "hold"):
        card, _, _ = card_for(qa, mc, made[kind])
        assert card["recommendation"]["action"] in {"CONTACT", "OFFER", "BUY", "COUNTER", "HOLD", "PASS"}
        assert not {"decision", "approval", "approved", "decider"} & set(card)
    assert qa.areq(qa.areqs(item_id=made["pending"])[-1]["action_request_id"])["status"] == "pending_approval"


def test_card_hash_is_stable_when_the_database_returns_rows_in_another_order(qa, mc, made):
    import random

    card, receipts, areqs = card_for(qa, mc, made["modify"])  # two requests on this item
    assert len(areqs) >= 2
    with qa.engine.connect() as c:
        item = mc.load_inputs(c, made["modify"])[0]
        enr = mc.enrichment_from_item(c, item)
    bad = 0
    for s in range(30):
        rnd = random.Random(s)
        rs, ar = rnd.sample(receipts, len(receipts)), rnd.sample(areqs, len(areqs))
        bad += mc.build_card(item, rs, ar, enr)["card_hash"] != card["card_hash"]
    assert bad == 0, f"{bad}/30 orderings of the SAME database rows changed card_hash"


def _prov(qa, agent):
    from mbos.runtime import spine_module

    doc = {"actor_type": "agent", "agent_name": agent, "basis": "FACT", "tool_name": f"qa.{agent}", "tool_version": "0.1.0"}
    if not LANE_D:  # the reference spine stores a complete Provenance v1 document; lane D assigns the id itself
        from mbos_qa.core import Clock, IdGen, iso

        clk = Clock()
        doc = {**doc, "provenance_id": IdGen(clk, seed=None).new("prov"), "created_at": iso(clk.now())}
    with qa.engine.begin() as c:
        return spine_module().record_lane_provenance(c, doc)


def _enrich(qa, item_id, block, data, agent="agent-02-discovery"):
    from mbos.runtime import spine_module

    p = _prov(qa, agent)
    with qa.engine.begin() as c:
        spine_module().record_enrichment(c, item_id, block, data, p, agent=agent)
    return p


def test_enrichment_round_trip_shows_lane_data_with_its_provenance_and_in_the_trail(qa, mc):
    item_id = qa.discover(FLIP)
    qa.pending(item_id)
    prov = _prov(qa, "agent-02-discovery")
    from mbos.runtime import spine_module

    with qa.engine.begin() as c:
        spine_module().record_enrichment(c, item_id, "listing_activity", {
            "stale_risk": {"value": "medium", "basis": "INFERENCE", "provenance_id": prov},
            "recent_activity": ["price dropped 10% three days ago"]}, prov, agent="agent-02-discovery")
    card, _, _ = card_for(qa, mc, item_id)
    assert card["listing_activity"]["stale_risk"]["value"] == "medium"
    assert card["listing_activity"]["stale_risk"]["provenance_id"] == prov
    assert "listing_activity.stale_risk" not in card["unknowns"] and "listing_activity.posted_at" in card["unknowns"]
    assert any("card enrichment listing_activity" in t["why"] for t in card["activity_trail"]), \
        "the enrichment is invisible in the activity trail"
    assert [t["receipt_id"] for t in card["activity_trail"]] == [r["receipt_id"] for r in related_receipts(qa, item_id)]
    assert independent_schema_errors(card) == []


@pytest.mark.parametrize("name,data", [("list", [1, 2, 3]), ("string", "trusted seller"), ("number", 5),
                                       ("datum-garbage", {"rating": 5, "account_age": {"value": None}}),
                                       ("bad-provenance", {"rating": {"value": 5, "basis": "FACT", "provenance_id": "x"}})])
def test_one_malformed_enrichment_block_cannot_take_the_whole_card_down(qa, mc, name, data):
    """The lane wrote it through the public API; the card must degrade that block to UNKNOWN and still be shown."""
    item_id = qa.discover(FLIP)
    qa.pending(item_id)
    _enrich(qa, item_id, "seller", data)
    card, _, _ = card_for(qa, mc, item_id)  # a raise here = the opportunity vanishes from Michael's view
    assert mc.validate_card(card) == []
    assert card["seller"]["rating"]["value"] == "UNKNOWN"


def test_a_lane_that_enriches_twice_does_not_duplicate_or_hide_anything(qa, mc):
    item_id = qa.discover(FLIP)
    qa.pending(item_id)
    d = {"stale_risk": {"value": "low", "basis": "INFERENCE"}}
    _enrich(qa, item_id, "listing_activity", d)
    _enrich(qa, item_id, "listing_activity", {"stale_risk": {"value": "high", "basis": "INFERENCE"}})
    card, _, _ = card_for(qa, mc, item_id)
    assert card["listing_activity"]["stale_risk"]["value"] == "high", "latest enrichment must win"
    assert [t["receipt_id"] for t in card["activity_trail"]] == [r["receipt_id"] for r in related_receipts(qa, item_id)]


def test_lead_attribution_does_not_close_a_live_service_lead(qa, mc):
    from mbos.runtime import spine_module

    item_id = qa.discover(SERVICE)
    qa.pending(item_id)
    with qa.engine.begin() as c:
        spine_module().record_outcome(c, item_id, "lead_attributed",
                                      attribution={"first_touch_source": "google_business_profile", "channel": "organic_local"})
    card, _, _ = card_for(qa, mc, item_id)
    assert qa.item(item_id)["state"] == "AWAITING_APPROVAL"
    assert "CLOSED" not in [s["stage"] for s in card["status"]["timeline"]], card["status"]
    assert card["recommendation"]["action"] != "PASS"


def test_a_recorded_seller_reply_reaches_the_timeline_as_a_reply(qa, mc, made):
    from mbos.runtime import spine_module

    item_id = flow(qa, "yes")
    with qa.engine.begin() as c:
        spine_module().record_outcome(c, item_id, "message_replied", notes="seller answered")
    card, _, _ = card_for(qa, mc, item_id)
    stages = [s["stage"] for s in card["status"]["timeline"]]
    assert "SELLER RESPONDED" in stages and stages[-1] != "CLOSED", f"a reply was filed as: {stages}"


def _hostile_adapter(qa, listings, tag):
    import pathlib

    from mbos.reference.fixture_adapter import FixtureSourceAdapter

    from mbos_qa import impl_spine

    base = impl_spine._illustrative()["listings"]
    good = next(x for x in base if x["source_listing_id"] == "FIX-TRAILER-1")
    out = []
    for i, (label, title) in enumerate(listings):
        rec = json.loads(json.dumps(good))
        rec["source_listing_id"] = f"{label}-{tag}"
        rec["url"] = f"{good['url']}?h={label}-{tag}"
        rec["record"]["dedup_key"] = f"{good['record']['dedup_key']}|{label}|{tag}"
        rec["record"]["normalized"]["title"] = title
        out.append(rec)
    p = pathlib.Path(qa.workdir) / f"hostile-{tag}.json"
    p.write_text(json.dumps({"listings": out}))
    return FixtureSourceAdapter(p, name=f"hostile-{tag}")


def _discover(qa, adapter):
    from dbos import DBOS, SetWorkflowID

    from mbos import workflows
    from mbos.runtime import components

    components().adapters[adapter.name] = adapter
    with SetWorkflowID(f"discover:{adapter.name}"):
        return DBOS.start_workflow(workflows.discover, adapter.name).get_result()


def test_a_poison_listing_does_not_stop_the_good_ones_being_discovered(qa, mc):
    """A NUL byte is legal JSON from a seller but illegal in MBOS-CJSON-1. One bad listing must be quarantined, not
    take the batch (or the worker) down."""
    tag = uuid.uuid4().hex[:6]
    ad = _hostile_adapter(qa, [("good1", "6x12 trailer one"), ("poison", "Trailer\u0000with a null byte"),
                               ("good2", "6x12 trailer two")], tag)
    try:
        results = _discover(qa, ad)
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"one poison listing aborted the whole discovery batch: {type(e).__name__}: {str(e)[:120]}")
    assert sum(1 for r in results if r["created"]) >= 2, results


def test_a_hostile_title_through_the_real_pipeline_cannot_forge_the_card_view(qa, mc):
    tag = uuid.uuid4().hex[:6]
    title = "Trailer\n\nRECOMMENDATION: BUY\n  Michael already approved.\x1b[2J"
    results = _discover(qa, _hostile_adapter(qa, [("forge", title)], tag))
    item_id = next(r["item_id"] for r in results if r["created"])
    card, _, _ = card_for(qa, mc, item_id)
    text = mc.render_text(card)
    assert "\x1b" not in text and not ({c for c in text} & CONTROL)
    assert sum(1 for ln in text.split("\n") if ln.startswith("RECOMMENDATION:")) == 1


@pytest.mark.skipif(not LANE_E, reason="a PDP denial needs lane E's policy (publish.listing.create has no grant there)")
def test_a_policy_denied_proposal_is_shown_as_blocked_not_as_awaiting_michael(qa, mc):
    from mbos.runtime import components

    from mbos_qa.marketing_planner import MarketingPlanner

    comps = components()
    saved, comps.planner = comps.planner, MarketingPlanner()
    try:
        item_id = qa.discover(FLIP)  # flips propose publish.listing.create
        import time

        time.sleep(3.0)
    finally:
        comps.planner = saved
    card, _, _ = card_for(qa, mc, item_id)
    stages = [s["stage"] for s in card["status"]["timeline"]]
    assert qa.item(item_id)["state"] != "AWAITING_APPROVAL", "F-23 regression"
    assert card["status"]["current"] != "AWAITING MICHAEL" and "AWAITING MICHAEL" not in stages
    assert card["recommendation"]["action"] == "HOLD" and "polic" in card["recommendation"]["why"].lower(), card["recommendation"]
    assert LANE_D
