import json
import threading
import time

import pytest

from mbos_qa.impl_spine import INVOCATIONS, LANE_D, LANE_E, Refused

from .conftest import FLIP, FU_EMAIL, FU_UNGRANTED, acted_item, followup, live_followups, snapshot, wait_for


def _decision_refused():
    from mbos.spine import DecisionRefused

    return DecisionRefused


# ---------------------------------------------------------------- the happy path (what 01 claims)
def test_a_followup_runs_the_same_gate_and_executes_exactly_once(qa):
    i, first = acted_item(qa)
    out = followup(qa, i)
    assert out["policy_denied"] is False and out["action_request_id"]
    fid = out["action_request_id"]
    assert qa.item(i)["state"] == "AWAITING_APPROVAL" and qa.areq(fid)["status"] == "pending_approval"
    qa.decide(fid, "YES")
    assert wait_for(lambda: qa.areq(fid)["status"] == "executed", 30)
    assert qa.wait_state(i, "ACTED") == "ACTED"
    ex = [r for r in qa.receipts(item_id=i) if r["type"] == "ACTION_EXECUTED"]
    assert sorted(r["action_request_id"] for r in ex) == sorted([first["action_request_id"], fid]), "two requests, two executions"
    keys = [r["idempotency_key"] for r in qa.effector_rows()]
    assert INVOCATIONS.get(first["idempotency_key"]) == 1 and INVOCATIONS.get(qa.areq(fid)["idempotency_key"]) == 1
    assert len(qa.effector_rows(areq_id=fid)) == 1 and len(qa.effector_rows(areq_id=first["action_request_id"])) == 1 and keys
    assert qa.verify_chain()["ok"]


# ---------------------------------------------------------------- 1. a follow-up on a non-ACTED item
def _item_in(qa, kind: str) -> str:
    if kind == "awaiting":
        i = qa.discover(FLIP)
        qa.pending(i)
        return i
    if kind == "held":
        i = qa.discover(FLIP)
        a = qa.pending(i)
        qa.decide(a["action_request_id"], "HOLD", step_up=False, hold={"hold_until": "2099-01-01T00:00:00Z", "wake_on": ["michael_ping"],
                                                                      "renotify_after": "PT1H", "escalate_after": "P30D"})
        qa.wait_state(i, "HELD")
        return i
    if kind == "archived_by_no":
        i = qa.discover(FLIP)
        a = qa.pending(i)
        qa.decide(a["action_request_id"], "NO", reason="QA")
        qa.wait_state(i, "ARCHIVED")
        return i
    if kind == "archived_pass":
        return qa.discover("FIX-MOWER-1")
    if kind == "researching_maybe":
        return qa.discover("FIX-LEAD-DRYWALL-1")
    if kind == "failed_by_freeze":
        i = qa.discover(FLIP)
        a = qa.pending(i)
        qa.freeze("global_freeze", True)
        try:
            qa.decide(a["action_request_id"], "YES")
            qa.wait_state(i, {"ACTED", "FAILED"})
        finally:
            qa.freeze("global_freeze", False)
        return i
    raise KeyError(kind)


@pytest.mark.parametrize("kind", ["awaiting", "held", "archived_by_no", "archived_pass", "researching_maybe", "failed_by_freeze"])
def test_a_followup_on_a_non_acted_item_is_refused_and_writes_nothing(qa, kind):
    i = _item_in(qa, kind)
    if kind == "researching_maybe":
        time.sleep(3.0)  # its own workflow is still writing receipts; compare only what a follow-up could change
    before = snapshot(qa, i)
    with pytest.raises(_decision_refused()):
        followup(qa, i)
    after = snapshot(qa, i)
    assert (after["state"], after["areqs"]) == (before["state"], before["areqs"]), "a refused follow-up changed the item or created a request"
    if kind != "researching_maybe":
        assert after == before, "a refused follow-up left a partial write"


@pytest.mark.xfail(not LANE_E, strict=True, reason="reference spine has no PDP / proposer_for; the lane E gateway provides this")
def test_a_followup_on_an_unknown_item_is_refused(qa):
    with pytest.raises(Exception) as e:
        followup(qa, "itm_01ZZZZZZZZZZZZZZZZZZZZZZZZ")
    assert not isinstance(e.value, (KeyError, AttributeError, TypeError)), f"unhandled {type(e.value).__name__}: {e.value}"


# ---------------------------------------------------------------- 2. the PDP denies / nobody may propose
@pytest.mark.xfail(not LANE_E, strict=True, reason="reference spine has no PDP / proposer_for; the lane E gateway provides this")
def test_a_followup_the_pdp_denies_leaves_the_item_acted_and_creates_no_workflow(qa):
    i, first = acted_item(qa)
    before = snapshot(qa, i)
    out = followup(qa, i, FU_UNGRANTED)
    assert out.get("policy_denied") is True
    assert qa.item(i)["state"] == "ACTED", "a denied follow-up must not move the item"
    assert not live_followups(qa, i, first["action_request_id"])
    if out.get("action_request_id"):
        from dbos import DBOS

        assert DBOS.retrieve_workflow(f"followup:{out['action_request_id']}", existing_workflow=False) is None
    # and the item can still take a legitimate follow-up afterwards
    ok = followup(qa, i)
    assert ok["policy_denied"] is False
    assert before["state"] == "ACTED"


@pytest.mark.skipif(not LANE_E, reason="the denial comes from lane E's policy")
@pytest.mark.xfail(strict=True, reason="F-43: a policy-denied follow-up returns id None and leaves no request and no receipt")
def test_a_denied_followup_attempt_is_visible_in_the_ledger(qa):
    """R17 (no invisible autonomous actions) applies to Michael's own tools too: if a follow-up is refused by policy, there
    must be a receipt saying so, otherwise the card/ledger cannot explain why nothing happened."""
    i, _ = acted_item(qa)
    out = followup(qa, i, FU_UNGRANTED)
    assert out["policy_denied"] is True
    rs = qa.receipts(action_request_id=out["action_request_id"])
    assert any(r["type"] == "POLICY_DECIDED" for r in rs), f"the policy refusal left no POLICY_DECIDED receipt: {[r['type'] for r in rs]}"


# ---------------------------------------------------------------- 3. PANIC engaged
# Restated after probing: a PROPOSAL under a freeze is inert by design (a first-action proposal under L3 is also accepted into
# AWAITING_APPROVAL); the fail-closed guarantee is that nothing EXECUTES. So: whatever is proposed under a freeze must not run
# on YES, and must not run after the freeze lifts unless Michael decides again.
@pytest.mark.parametrize("level,target,key", [("L3", None, "global_freeze"), ("L2", "comms.email.send", "capability_freeze:comms.email.send"),
                                                ("L1", "agent-01-coordinator", "agent_freeze:agent-01-coordinator")])
def test_a_followup_proposed_under_panic_never_executes(qa, level, target, key):
    i, first = acted_item(qa)
    qa.freeze(key, True)
    fid = None
    try:
        try:
            out = followup(qa, i)
            fid = out.get("action_request_id")
        except _decision_refused():
            return  # refusing outright is also fail-closed
        if out.get("policy_denied") or not fid:
            return
        try:
            qa.decide(fid, "YES")
        except Refused:
            pass
        wait_for(lambda: qa.areq(fid)["status"] in ("executed", "failed", "cancelled_by_freeze"), 8)
        assert qa.areq(fid)["status"] != "executed", f"a follow-up executed under {level}"
        assert not qa.effector_rows(areq_id=fid), f"an effector ran under {level}"
    finally:
        qa.freeze(key, False)
    if fid:
        time.sleep(3)
        assert not qa.effector_rows(areq_id=fid), "the approval given during the freeze fired after it lifted"


# ---------------------------------------------------------------- 4. double submit
def test_a_sequential_double_submit_creates_one_request_and_one_gate(qa):
    i, first = acted_item(qa)
    a = followup(qa, i)
    with pytest.raises(_decision_refused()):
        followup(qa, i)
    assert [r["action_request_id"] for r in live_followups(qa, i, first["action_request_id"])] == [a["action_request_id"]]


@pytest.mark.xfail(LANE_D, strict=True, reason="F-45: 8 concurrent propose_followup calls on one ACTED item create 2 live requests (3/3 runs, lane D+E)")
def test_a_concurrent_double_submit_creates_exactly_one_request_and_one_execution(qa):
    i, first = acted_item(qa)
    results, errors = [], []
    barrier = threading.Barrier(8)

    def go():
        barrier.wait()
        try:
            results.append(followup(qa, i))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    created = [r for r in results if r.get("action_request_id") and not r.get("policy_denied")]
    unhandled = [e for e in errors if not isinstance(e, _decision_refused())]
    assert len(created) == 1, f"{len(created)} follow-ups created by 8 concurrent submits"
    assert not unhandled, f"unhandled errors from a double submit: {[type(e).__name__ + ': ' + str(e)[:80] for e in unhandled]}"
    fid = created[0]["action_request_id"]
    assert [r["action_request_id"] for r in live_followups(qa, i, first["action_request_id"])] == [fid]
    qa.decide(fid, "YES")
    assert wait_for(lambda: qa.areq(fid)["status"] == "executed", 30)
    assert len(qa.effector_rows(areq_id=fid)) == 1 and INVOCATIONS.get(qa.areq(fid)["idempotency_key"]) == 1


# ---------------------------------------------------------------- 5. a crash between request creation and the gate starting
def _enqueue_breaks(monkeypatch):
    from dbos import DBOS

    import mbos.runtime as rt

    def boom(*a, **k):
        raise RuntimeError("QA: process died between creating the request and starting its gate")

    monkeypatch.setattr(DBOS, "enqueue_workflow_with_options", boom)
    monkeypatch.setattr(rt, "client", boom)


@pytest.mark.xfail(strict=True, reason="F-42: a follow-up whose gate never started is accepted on YES and never executes")
def test_a_crash_between_request_creation_and_gate_start_is_recoverable(qa, monkeypatch):
    """The request is committed (item AWAITING_APPROVAL, request pending) but its approval-gate workflow was never started.
    Whatever recovers it - a retry of the same call, a startup scan, a reconcile - Michael's YES must still lead to ONE
    execution. If nothing recovers it, his approval is accepted and silently does nothing."""
    i, first = acted_item(qa)
    with monkeypatch.context() as m:
        _enqueue_breaks(m)
        with pytest.raises(RuntimeError):
            followup(qa, i)
    pend = live_followups(qa, i, first["action_request_id"])
    assert len(pend) == 1 and qa.item(i)["state"] == "AWAITING_APPROVAL", "the request must be committed atomically with the item move"
    fid = pend[0]["action_request_id"]
    from dbos import DBOS

    assert DBOS.get_workflow_status(f"followup:{fid}") is None, "no gate was started (the crash window)"
    # recovery attempt 1: the caller retries the same call
    try:
        followup(qa, i)
    except Exception:  # noqa: BLE001 - a refusal is an acceptable answer to a retry, recovery may live elsewhere
        pass
    qa.decide(fid, "YES")
    done = wait_for(lambda: qa.areq(fid)["status"] == "executed", 25)
    assert done, (f"Michael's YES was accepted but nothing executed: request={qa.areq(fid)['status']}, item={qa.item(i)['state']}; "
                  "the orphaned follow-up has no recovery path")
    assert len(qa.effector_rows(areq_id=fid)) == 1


# ---------------------------------------------------------------- 6. YES without step-up
def test_a_yes_without_step_up_on_an_irreversible_followup_is_refused(qa):
    i, first = acted_item(qa)
    fid = followup(qa, i)["action_request_id"]
    with pytest.raises(Refused):
        qa.decide(fid, "YES", step_up=False)
    assert qa.areq(fid)["status"] == "pending_approval" and not qa.effector_rows(areq_id=fid)


def test_the_caller_cannot_downgrade_reversibility_to_skip_step_up(qa):
    """`reversibility` is supplied by the caller. Declaring a message 'reversible' must not let a YES skip step-up when the
    policy says the capability needs it."""
    i, first = acted_item(qa)
    pa = {**FU_EMAIL, "reversibility": "reversible"}
    fid = followup(qa, i, pa)["action_request_id"]
    try:
        qa.decide(fid, "YES", step_up=False)
    except Refused:
        return
    assert wait_for(lambda: qa.areq(fid)["status"] in ("executed", "failed", "cancelled_by_freeze"), 25)
    assert qa.areq(fid)["status"] != "executed" or not LANE_E, \
        "an email declared 'reversible' was executed on a YES without step-up (the policy requires it for email)"


# ---------------------------------------------------------------- 7. stale approval after a freeze
def test_an_approval_given_during_a_freeze_cannot_fire_after_it_lifts(qa):
    i, first = acted_item(qa)
    fid = followup(qa, i)["action_request_id"]
    qa.freeze("global_freeze", True)
    try:
        qa.decide(fid, "YES")
        assert wait_for(lambda: qa.areq(fid)["status"] in ("cancelled_by_freeze", "failed", "executed"), 25)
        status = qa.areq(fid)["status"]
    finally:
        qa.freeze("global_freeze", False)
    assert status in ("cancelled_by_freeze", "failed"), status
    time.sleep(2.0)
    assert qa.areq(fid)["status"] == status and not qa.effector_rows(areq_id=fid), "the denied approval fired after the freeze lifted"
    if LANE_D:
        from mbos.runtime import components, runtime

        appr = qa.approvals(fid)[-1]
        res = components().gateway.execute(runtime().engine, fid, appr["approval_id"])
        assert not getattr(res, "ok", False) and not qa.effector_rows(areq_id=fid), "replaying the stale approval executed the follow-up"


def test_a_freeze_engaged_after_the_yes_cancels_instead_of_executing(qa):
    i, first = acted_item(qa)
    fid = followup(qa, i)["action_request_id"]

    qa.freeze("global_freeze", True)
    try:
        time.sleep(0.5)
        qa.decide(fid, "YES")
        wait_for(lambda: qa.areq(fid)["status"] != "approved", 25)
    finally:
        qa.freeze("global_freeze", False)
    assert qa.areq(fid)["status"] != "executed" and not qa.effector_rows(areq_id=fid)


# ---------------------------------------------------------------- 8. malformed / hostile input to the API
MALFORMED = [("empty", {}), ("none", None), ("no-summary", {"capability": "comms.email.send", "reversibility": "irreversible"}),
             ("no-capability", {"summary": "x", "reversibility": "irreversible"}), ("no-reversibility", {"capability": "comms.email.send", "summary": "x"}),
             ("capability-int", {"capability": 5, "summary": "x", "reversibility": "irreversible"}),
             ("capability-unknown", {"capability": "teleport.item", "summary": "x", "reversibility": "irreversible"}),
             ("reversibility-bogus", {"capability": "comms.email.send", "summary": "x", "reversibility": "maybe"}),
             ("summary-nul", {**FU_EMAIL, "summary": "x\u0000y"}), ("cost-negative", {**FU_EMAIL, "estimated_cost": {"amount": -50, "currency": "USD"}}),
             ("cost-string", {**FU_EMAIL, "estimated_cost": "free"}), ("list", [1, 2])]


REFONLY = {"capability-int", "capability-unknown", "cost-negative"}
_REF = pytest.mark.xfail(not LANE_E, strict=True, reason="reference spine has no PDP; lane E validates these")
F44 = {"empty", "none", "no-summary", "no-capability", "no-reversibility", "list"}
_X = pytest.mark.xfail(strict=True, raises=AssertionError, reason="F-44: a malformed payload escapes as a raw KeyError/AttributeError, not DecisionRefused")
@pytest.mark.parametrize("name,pa", [pytest.param(n, p, id=n, marks=[_X] if n in F44 else ([_REF] if n in REFONLY else [])) for n, p in MALFORMED])
def test_a_malformed_followup_is_refused_cleanly_and_atomically(qa, name, pa):
    i, first = acted_item(qa)
    before = snapshot(qa, i)
    try:
        out = followup(qa, i, pa) if pa is not None else __import__("mbos.workflows", fromlist=["x"]).propose_followup(i, None)
    except Exception as e:  # noqa: BLE001
        assert isinstance(e, (_decision_refused(), ValueError)), f"unhandled {type(e).__name__}: {str(e)[:120]}"
    else:
        assert out.get("policy_denied") or not live_followups(qa, i, first["action_request_id"]), f"accepted a malformed follow-up: {out}"
    after = snapshot(qa, i)
    assert after["state"] == "ACTED", f"the item moved: {before} -> {after}"
    assert not live_followups(qa, i, first["action_request_id"]), "a live request exists"
    extra = [a for a in qa.areqs(item_id=i) if a["action_request_id"] != first["action_request_id"]]
    assert all(a["status"] == "rejected" for a in extra), [a["status"] for a in extra]  # a denial is recorded, not live


@pytest.mark.xfail(not LANE_E, strict=True, reason="reference spine has no PDP / proposer_for; the lane E gateway provides this")
def test_the_caller_cannot_forge_identity_or_authority_fields(qa):
    i, first = acted_item(qa)
    pa = {**FU_EMAIL, "lane": "agent-99-evil", "proposed_by": "agent-05-governance", "tier": 3, "status": "approved",
          "payload_hash": "sha256:" + "0" * 64, "approval_id": "appr_01ZZZZZZZZZZZZZZZZZZZZZZZZ", "action_request_id": "areq_01ZZZZZZZZZZZZZZZZZZZZZZZZ",
          "idempotency_key": "forged", "on_behalf_of": "attacker", "untrusted_inputs_present": False}
    try:
        out = followup(qa, i, pa)
    except Exception as e:  # noqa: BLE001
        assert isinstance(e, (_decision_refused(), ValueError)), type(e).__name__
        return
    if out.get("policy_denied"):
        return
    a = qa.areq(out["action_request_id"])
    assert a["proposed_by"] in ("agent-01-coordinator",) and a["tier"] == 0 and a["status"] == "pending_approval", a
    assert a["action_request_id"] != "areq_01ZZZZZZZZZZZZZZZZZZZZZZZZZ" and a["idempotency_key"] != "forged"
    assert a["on_behalf_of"] == "michael" and a.get("untrusted_inputs_present") is not False
    assert not qa.approvals(a["action_request_id"]), "a forged approval_id produced an approval"


# ---------------------------------------------------------------- 9. integrity after all of the above
def test_the_chain_and_the_dry_run_invariant_survive_every_follow_up_abuse(qa):
    assert qa.verify_chain()["ok"]
    assert all(r["dry_run"] is True for r in qa.effector_rows())
    live = [r for r in qa.receipts() if r["type"] in ("ACTION_EXECUTED", "ACTION_FAILED") and (r.get("effector_response") or {}).get("dry_run") is not True]
    assert not live
    for r in qa.receipts():
        assert r["provenance_ids"] and all(qa.find_provenance(p) for p in r["provenance_ids"])
    json.dumps(0)
    assert FLIP
