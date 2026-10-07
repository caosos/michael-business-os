"""G1–G4 (owner 07) against the REAL spine, with the real lane-07 ActionPlanner (`mbos_qa.marketing_planner`) wired
into 01's runtime Components. G1, G2 and G4 (draft frozen into the approved payload) must pass. The G4 provenance
clause is a STRICT xfail tied to F-21: it fails the run the moment the gap closes, so the marker has to be removed
rather than drift. G3 has no code path in wave one and is skipped with a reason."""
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


def test_g4_approved_payload_freezes_the_draft_exactly(qa, planner07):
    """F-19 (fixed in A-13): what Michael approves is the draft itself, hash-covered."""
    item_id, areq = _publishing_request(qa)
    expected = MarketingPlanner().plan(qa.item(item_id))[0]["draft"]
    draft = areq["payload"].get("draft")
    assert draft == expected, "the approved payload does not carry the planner's draft verbatim"
    assert draft["content_hash"] == sha256_ref(draft["content"])
    assert draft["prompt_hash"] and draft["model_id"] and draft["template_version"]
    assert areq["payload_hash"] == sha256_ref(areq["payload"]), "the draft is not covered by the approved hash"


@pytest.mark.xfail(strict=True, reason="F-21: the draft's template/prompt hash/model are frozen in the payload "
                                       "but no provenance record for the request resolves to them (only "
                                       "route_recommendation tool provenance)")
def test_g4_draft_provenance_resolves_to_template_and_model(qa, planner07):
    """G4 wording: content hash, prompt version and model are recorded IN PROVENANCE for the outgoing draft."""
    item_id, areq = _publishing_request(qa)
    draft = areq["payload"]["draft"]
    prov = [qa.find_provenance(p) for p in areq["provenance_ids"]]
    assert any(p.get("prompt_hash") == draft["prompt_hash"] and p.get("model_id") for p in prov), \
        [{k: p.get(k) for k in ("tool_name", "prompt_hash", "model_id")} for p in prov]


def test_g2_service_lead_carries_attribution(qa, planner07):
    """F-20 (fixed): attribution is recorded on the lead through the spine's public API."""
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
