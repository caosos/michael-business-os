"""G1–G4 (owner 07) against the REAL spine, with the real lane-07 ActionPlanner (`mbos_qa.marketing_planner`) wired into
01's runtime Components. Two draft kinds, because they hit different governance rules:
  * email   — service lead → `comms.email.send` quote (held by the propose-only grant, R7)
  * publish — flip → `publish.listing.create` resale listing (manual-assist lane; no grant exists in Agent 05's policy)
On the lane E stack the publish kind is denied by the PDP (F-22) and the spine then leaves the item stuck in
AWAITING_APPROVAL (F-23). Those cases are STRICT xfails tied to the findings: they turn into failures the moment
the gaps close, so the marker has to be removed rather than drift. G3 has no code path in wave one."""
import time

import pytest

from mbos_qa.core import sha256_ref
from mbos_qa.impl_spine import LANE_E
from mbos_qa.marketing_planner import MarketingPlanner

from .conftest import FLIP_YES, SERVICE_YES, effector_calls_for, invocations

F22 = pytest.mark.xfail(LANE_E, strict=True, reason="F-22: Agent 05's policy grants `publish.listing.create` to nobody; "
                                                    "the PDP denies the spine's proposer (CAPABILITY_NOT_HELD)")
KINDS = [pytest.param("email", id="email"), pytest.param("publish", id="publish", marks=F22)]


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
    out = qa.decide(areq["action_request_id"], "YES", step_up=(kind == "email"))
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


@pytest.mark.xfail(LANE_E, strict=True, reason="F-23: when the PDP DENIES a proposal, the spine still moves the item to "
                                               "AWAITING_APPROVAL with a rejected request: Michael is told to decide "
                                               "on nothing and the item is stuck")
def test_a_pdp_denied_proposal_never_leaves_the_item_awaiting_michael(qa, planner07):
    item_id = qa.discover(FLIP_YES)
    time.sleep(3.0)
    reqs = qa.areqs(item_id=item_id)
    if not reqs or reqs[-1]["status"] != "rejected":
        pytest.skip("this configuration did not deny the proposal")
    assert qa.item(item_id)["state"] != "AWAITING_APPROVAL", "AWAITING_APPROVAL with no request to approve"
    assert not qa.areqs(item_id=item_id, status=("pending_approval", "held"))


@pytest.mark.skip(reason="G3: wave one has no review-request path in the spine or in lane 06/07 code.")
def test_g3_review_requests_follow_google_policy():
    pass
