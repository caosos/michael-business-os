"""G1–G4 (owner 07) against the REAL spine, with the real lane-07 ActionPlanner (`mbos_qa.marketing_planner`) wired
into 01's runtime Components. G1 must pass. G2/G4 encode spine gaps as STRICT xfails tied to findings (F-20/F-19):
they fail the run the moment the gap closes, so the marker has to be removed rather than drift. G3 has no code path
in wave one and is skipped with a reason."""
import time

import pytest

from mbos_qa.core import sha256_ref
from mbos_qa.marketing_planner import MarketingPlanner

from .conftest import FLIP_YES, SERVICE_YES, effector_calls_for, invocations


@pytest.fixture
def planner07(qa):
    from mbos.runtime import components

    comps = components()
    saved = comps.planner
    comps.planner = MarketingPlanner()
    yield comps.planner
    comps.planner = saved


def _publishing_request(qa):
    item_id = qa.discover(FLIP_YES)
    areq = qa.pending(item_id)
    assert areq["capability"] == "publish.listing.create", areq["capability"]
    return item_id, areq


def test_g1_publishing_draft_is_a_tier0_dry_run_request_awaiting_michael(qa, planner07):
    item_id, areq = _publishing_request(qa)
    assert areq["category"] == "publishing" and areq["tier"] == 0 and areq["status"] == "pending_approval"
    assert areq["payload"]["dry_run"] is True
    time.sleep(1.0)
    assert invocations(qa, areq) == 0 and effector_calls_for(qa, areq["action_request_id"]) == 0
    assert not [r for r in qa.receipts(action_request_id=areq["action_request_id"])
                if r["type"] in ("ACTION_EXECUTING", "ACTION_EXECUTED")], "published before approval"


def test_g1_no_means_nothing_is_published(qa, planner07):
    item_id, areq = _publishing_request(qa)
    qa.decide(areq["action_request_id"], "NO", reason="QA: not listing this one")
    qa.wait_state(item_id, "ARCHIVED")
    assert invocations(qa, areq) == 0 and effector_calls_for(qa, areq["action_request_id"]) == 0


def test_g1_yes_publishes_exactly_once_in_dry_run(qa, planner07):
    item_id, areq = _publishing_request(qa)
    out = qa.decide(areq["action_request_id"], "YES", step_up=False)  # partially_reversible: no step-up required
    assert qa.wait_state(item_id, {"ACTED", "FAILED"}) == "ACTED"
    (ex,) = [r for r in qa.receipts(action_request_id=areq["action_request_id"]) if r["type"] == "ACTION_EXECUTED"]
    assert ex["effect"] == "publish" and ex["effector_response"]["dry_run"] is True
    assert ex["approval_id"] == out["approval"]["approval_id"] and ex["payload_hash"] == areq["payload_hash"]
    assert invocations(qa, areq) == 1 and effector_calls_for(qa, areq["action_request_id"]) == 1


def test_g1_every_execution_in_the_ledger_traces_to_a_yes_on_the_same_payload(qa, planner07):
    _publishing_request(qa)  # ensure the shared ledger holds publishing + comms executions from this session
    executed = [r for r in qa.receipts() if r["type"] == "ACTION_EXECUTED"]
    assert executed
    for r in executed:
        appr = next(a for a in qa.approvals(r["action_request_id"]) if a["approval_id"] == r["approval_id"])
        assert appr["decision"] == "YES" and appr["decider"] == "michael"
        assert appr["payload_hash_seen"] == r["payload_hash"] == qa.areq(r["action_request_id"])["payload_hash"]


@pytest.mark.xfail(strict=True, reason="F-19: the spine freezes {summary, target, ids} only; the planner's draft "
                                       "content and its G4 provenance never reach the approved payload")
def test_g4_approved_payload_carries_the_draft_and_its_provenance(qa, planner07):
    item_id, areq = _publishing_request(qa)
    draft = MarketingPlanner().plan(qa.item(item_id))[0]["draft"]
    payload = areq["payload"]
    assert payload.get("content_hash") == draft["content_hash"] == sha256_ref(draft["content"])
    assert payload.get("prompt_hash") and payload.get("model_id") and payload.get("template_version")
    prov = [qa.find_provenance(p) for p in areq["provenance_ids"]]
    assert any(p.get("prompt_hash") == draft["prompt_hash"] for p in prov)


@pytest.mark.xfail(strict=True, reason="F-20: no spine API records lead attribution (record_outcome takes no "
                                       "`attribution`; outcome.schema.json supports it)")
def test_g2_service_lead_carries_attribution(qa, planner07):
    from mbos import spine

    item_id = qa.discover(SERVICE_YES)
    qa.pending(item_id)
    with qa.engine.begin() as c:
        spine.record_outcome(c, item_id, "lead_attributed",
                             attribution={"first_touch_source": "google_business_profile", "channel": "organic_local"})
    outs = [d for k, d in qa.documents() if k == "outcome" and d["item_id"] == item_id]
    assert outs and outs[-1]["attribution"]["first_touch_source"] == "google_business_profile"


@pytest.mark.skip(reason="G3: wave one has no review-request path in the spine or in lane 06/07 code. The mock "
                         "suite's policy checks apply once one exists.")
def test_g3_review_requests_follow_google_policy():
    pass
