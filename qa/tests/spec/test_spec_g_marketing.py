"""G1–G4 (owner 07) against the REAL spine, with the real lane-07 ActionPlanner (`mbos_qa.marketing_planner`) wired into
01's runtime Components. Two draft kinds, because they hit different governance rules:
  * email   — service lead → `comms.email.send` quote (held by the propose-only grant, R7)
  * publish — flip → `publish.listing.create` resale listing (manual-assist lane; no grant exists in Agent 05's policy)
F-22 (no publish grant) and F-23 (a PDP denial left the item stuck awaiting Michael) are CLOSED (05 E-13, 01 R21),
verified on the real stack; their strict xfail markers have been removed. Publishing needs Michael's step-up on lane
E (policy `GATED:publishing:tier0; step_up=required`). G3 has no code path in wave one."""
import time

import pytest

from mbos_qa.core import sha256_ref
from mbos_qa.impl_spine import LANE_E, Refused
from mbos_qa.marketing_planner import MarketingPlanner

from .conftest import FLIP_YES, SERVICE_YES, effector_calls_for, invocations

KINDS = ["email", "publish"]


@pytest.fixture
def planner07(qa):
    from mbos.runtime import components

    comps = components()
    saved = comps.planner
    comps.planner = MarketingPlanner()
    yield comps.planner
    comps.planner = saved


def _request(qa, kind):
    item_id = qa.discover(FLIP_YES if kind == "publish" else SERVICE_YES)
    areq = qa.pending(item_id)
    assert areq["capability"] == ("publish.listing.create" if kind == "publish" else "comms.email.send"), areq["capability"]
    return item_id, areq


@pytest.mark.parametrize("kind", KINDS)
def test_g1_draft_is_a_tier0_dry_run_request_awaiting_michael(qa, planner07, kind):
    item_id, areq = _request(qa, kind)
    assert areq["tier"] == 0 and areq["status"] == "pending_approval" and areq["payload"]["dry_run"] is True
    time.sleep(1.0)
    assert invocations(qa, areq) == 0 and effector_calls_for(qa, areq["action_request_id"]) == 0
    assert not [r for r in qa.receipts(action_request_id=areq["action_request_id"])
                if r["type"] in ("ACTION_EXECUTING", "ACTION_EXECUTED")], "executed before approval"


@pytest.mark.parametrize("kind", KINDS)
def test_g1_no_means_nothing_is_sent_or_published(qa, planner07, kind):
    item_id, areq = _request(qa, kind)
    qa.decide(areq["action_request_id"], "NO", reason="QA: not this one")
    qa.wait_state(item_id, "ARCHIVED")
    assert invocations(qa, areq) == 0 and effector_calls_for(qa, areq["action_request_id"]) == 0


@pytest.mark.parametrize("kind", KINDS)
def test_g1_yes_executes_exactly_once_in_dry_run(qa, planner07, kind):
    item_id, areq = _request(qa, kind)
    out = qa.decide(areq["action_request_id"], "YES", step_up=True)
    assert qa.wait_state(item_id, {"ACTED", "FAILED"}) == "ACTED"
    (ex,) = [r for r in qa.receipts(action_request_id=areq["action_request_id"]) if r["type"] == "ACTION_EXECUTED"]
    assert ex["effect"] == ("publish" if kind == "publish" else "send") and ex["effector_response"]["dry_run"] is True
    assert ex["approval_id"] == out["approval"]["approval_id"] and ex["payload_hash"] == areq["payload_hash"]
    assert invocations(qa, areq) == 1 and effector_calls_for(qa, areq["action_request_id"]) == 1


def test_g1_every_execution_in_the_ledger_traces_to_a_yes_on_the_same_payload(qa, planner07):
    item_id, areq = _request(qa, "email")
    qa.decide(areq["action_request_id"], "YES")
    qa.wait_state(item_id, {"ACTED", "FAILED"})
    executed = [r for r in qa.receipts() if r["type"] == "ACTION_EXECUTED"]
    assert executed
    for r in executed:
        appr = next(a for a in qa.approvals(r["action_request_id"]) if a["approval_id"] == r["approval_id"])
        assert appr["decision"] == "YES" and appr["decider"] == "michael"
        assert appr["payload_hash_seen"] == r["payload_hash"] == qa.areq(r["action_request_id"])["payload_hash"]


@pytest.mark.parametrize("kind", KINDS)
def test_g4_approved_payload_freezes_the_draft_exactly(qa, planner07, kind):
    """F-19 (fixed in A-13): what Michael approves is the draft itself, hash-covered."""
    item_id, areq = _request(qa, kind)
    expected = MarketingPlanner().plan(qa.item(item_id))[0]["draft"]
    draft = areq["payload"].get("draft")
    assert draft == expected, "the approved payload does not carry the planner's draft verbatim"
    assert draft["content_hash"] == sha256_ref(draft["content"])
    assert draft["prompt_hash"] and draft["model_id"] and draft["template_version"]
    assert areq["payload_hash"] == sha256_ref(areq["payload"]), "the draft is not covered by the approved hash"


@pytest.mark.parametrize("kind", KINDS)
def test_g4_draft_provenance_resolves_to_template_and_model(qa, planner07, kind):
    """G4 wording: content hash, prompt version and model are recorded IN PROVENANCE for the outgoing draft (F-21, fixed)."""
    item_id, areq = _request(qa, kind)
    draft = areq["payload"]["draft"]
    prov = [qa.find_provenance(p) for p in areq["provenance_ids"]]
    assert any(p.get("prompt_hash") == draft["prompt_hash"] and p.get("model_id") for p in prov), \
        [{k: p.get(k) for k in ("tool_name", "prompt_hash", "model_id")} for p in prov]


def test_g2_service_lead_carries_attribution(qa, planner07):
    """F-20 (fixed): attribution is recorded on the lead through the spine's public API."""
    from mbos.runtime import spine_module

    item_id = qa.discover(SERVICE_YES)
    qa.pending(item_id)
    with qa.engine.begin() as c:
        spine_module().record_outcome(c, item_id, "lead_attributed",
                                      attribution={"first_touch_source": "google_business_profile", "channel": "organic_local"})
    outs = [d for k, d in qa.documents() if k == "outcome" and d["item_id"] == item_id]
    assert outs and outs[-1]["attribution"]["first_touch_source"] == "google_business_profile"


class _UngrantedPlanner:
    """Proposes a capability the spine's proposer does not hold (comms.voice.call): the PDP must deny it."""
    def plan(self, item):
        return [{"capability": "comms.voice.call", "summary": "QA: phone the seller (ungranted for the proposer; must be denied)",
                 "reversibility": "irreversible", "estimated_cost": {"amount": 0, "currency": "USD"}}]


@pytest.mark.skipif(not LANE_E, reason="a PDP denial needs lane E's policy")
def test_a_pdp_denied_proposal_never_leaves_the_item_awaiting_michael(qa):
    """F-23 regression (fixed by 01's R21): nothing to approve → no AWAITING_APPROVAL, no pending request."""
    from mbos.runtime import components

    comps = components()
    saved, comps.planner = comps.planner, _UngrantedPlanner()
    try:
        item_id = qa.discover(FLIP_YES)
        time.sleep(3.0)
    finally:
        comps.planner = saved
    live = ("pending_approval", "held", "approved", "executing", "executed")
    assert not qa.areqs(item_id=item_id, status=live), f"an ungranted capability produced a live request: {qa.areqs(item_id=item_id)}"
    # F-41 model: if nobody may propose it, NO request is created; older heads created a `rejected` one. Either is a denial.
    assert all(r["status"] == "rejected" for r in qa.areqs(item_id=item_id))
    assert qa.item(item_id)["state"] != "AWAITING_APPROVAL", "AWAITING_APPROVAL with no request to approve"


@pytest.mark.skipif(not LANE_E, reason="step-up policy comes from lane E")
def test_a_yes_the_policy_will_refuse_is_refused_when_it_is_given(qa, planner07):
    """The PDP stamps `step_up=required` on a publishing request. A YES without step-up must be refused AT DECISION TIME
    with a clear message. Today the spine accepts it, the gateway then refuses (STEP_UP_REQUIRED) and the item ends FAILED:
    Michael's approval is silently lost (F-40)."""
    item_id, areq = _request(qa, "publish")
    with pytest.raises(Refused):
        qa.decide(areq["action_request_id"], "YES", step_up=False)
    assert qa.item(item_id)["state"] == "AWAITING_APPROVAL"
    assert qa.areq(areq["action_request_id"])["status"] == "pending_approval"


@pytest.mark.skipif(not LANE_E, reason="grants and proposer identities come from lane E's policy")
def test_f41_no_agent_holds_the_unneeded_money_grants_and_drafting_lanes_propose_as_themselves(qa, planner07):
    """F-41 (05's w1.8 policy + 01's lane-tagged proposals), verified from the policy data AND the live request."""
    import json
    import pathlib

    from mbos_qa.impl_spine import policy_path

    policy = json.loads(pathlib.Path(policy_path()).read_text())
    holders = {cap: [a for a, g in policy["agent_grants"].items() if cap in g]
               for cap in ("money.payment.send", "price.change", "commit.external")}
    assert holders == {"money.payment.send": [], "price.change": [], "commit.external": []}, holders
    item_id, areq = _request(qa, "publish")  # a flip → publish.listing.create drafted by lane 07
    assert areq["proposed_by"] == "agent-07-marketing", f"publishing was proposed by {areq['proposed_by']!r}, not its drafting lane"
    item2, areq2 = _request(qa, "email")  # lane 07 holds no comms grant → falls back to the spine identity
    assert areq2["proposed_by"] == "agent-01-coordinator", areq2["proposed_by"]


@pytest.mark.skip(reason="G3: wave one has no review-request path in the spine or in lane 06/07 code.")
def test_g3_review_requests_follow_google_policy():
    pass
