"""Spine-side fixes from the 2026-10-07 lane review: blocking-key dedup, step-up, MODIFY by full payload."""

from dataclasses import asdict

import pytest
import sqlalchemy as sa

from mbos import spine
from mbos.interfaces import RawListing
from mbos.reference.fixture_adapter import FixtureNormalizer, FixtureSourceAdapter
from mbos.runtime import Components
from tests.helpers.common import FIXTURE, STEP_UP, scalar
from tests.helpers.seed import seed_flow


class NeverDuplicate:
    def is_duplicate(self, existing_item, candidate, context=None):
        assert context is None or {'source', 'match_hints'} <= set(context)
        return False


def _raw(listing):
    return next(r for r in FixtureSourceAdapter(FIXTURE).fetch() if r.source_listing_id == listing)


def test_equal_blocking_key_does_not_merge_without_deduper_consent(ledger_db):
    comps = Components(deduper=NeverDuplicate()).with_defaults()
    a, b = _raw("FIX-TRAILER-1"), _raw("FIX-TRAILER-1-DUP")
    n = FixtureNormalizer()
    with ledger_db.begin() as c:
        r1 = spine.ingest(c, asdict(a), asdict(n.normalize(a)), "fx", "0", comps)
        r2 = spine.ingest(c, asdict(b), asdict(n.normalize(b)), "fx", "0", comps)
        r3 = spine.ingest(c, asdict(a), asdict(n.normalize(a)), "fx", "0", comps)  # same identity again
    assert r1["created"] and r2["created"] and r1["item_id"] != r2["item_id"]
    assert r3 == {"item_id": r1["item_id"], "created": False, "merged": False, "dropped": False}
    assert scalar(ledger_db, "SELECT count(*) FROM mbos.items") == 2


def test_yes_on_irreversible_request_requires_step_up(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    with ledger_db.begin() as c:
        h = c.execute(sa.text("SELECT payload_hash FROM mbos.action_requests")).scalar_one()
        with pytest.raises(spine.DecisionRefused, match="step-up"):
            spine.decide(c, ids["action_request_id"], "YES", h, ids["components"])
    with ledger_db.begin() as c:
        out = spine.decide(c, ids["action_request_id"], "YES", h, ids["components"], auth_context=STEP_UP)
    assert out["approval"]["auth_context"]["step_up"] is True


def test_modify_accepts_full_edited_payload(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    with ledger_db.begin() as c:
        areq = c.execute(sa.text("SELECT body FROM mbos.action_requests")).scalar_one()
        edited = {**areq["payload"], "summary": "Offer $700 (DRY-RUN draft)"}
        out = spine.decide(c, ids["action_request_id"], "MODIFY", areq["payload_hash"], ids["components"], new_payload=edited)
    assert out["approval"]["modifications"]["diff"] == {"summary": "Offer $700 (DRY-RUN draft)"}
    with ledger_db.begin() as c, pytest.raises(spine.DecisionRefused, match="remove"):
        new = c.execute(sa.text("SELECT body FROM mbos.action_requests WHERE action_request_id = :a"),
                        {"a": out["new_action_request_id"]}).scalar_one()
        spine.decide(c, new["action_request_id"], "MODIFY", new["payload_hash"], ids["components"], new_payload={"summary": "x"})


def test_notify_event_wakes_matching_hold_and_never_executes(rt, run_discovery):
    from datetime import timedelta

    from mbos import workflows
    from mbos.clock import iso, utcnow
    from tests.helpers.common import pending_request, receipts_for, wait_state

    item_id = run_discovery("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    workflows.notify_event(item_id, "new_info", "seller added photos")  # awaiting → re-notified only
    workflows.record_decision(areq["action_request_id"], "HOLD", areq["payload_hash"],
                              hold={"hold_until": iso(utcnow() + timedelta(hours=6)), "wake_on": ["price_change"],
                                    "renotify_after": "PT6H"})
    wait_state(rt.engine, item_id, "HELD")
    workflows.notify_event(item_id, "auction_ending", "not in wake_on")  # ignored while held
    workflows.notify_event(item_id, "price_change", "ask dropped 950 -> 800")
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    intents = [r["intent"] for r in receipts_for(rt.engine, areq=areq["action_request_id"], type="APPROVAL_REQUESTED")]
    assert any("new_info" in i for i in intents) and any("price_change" in i for i in intents)
    assert not any("auction_ending" in i for i in intents)
    assert not receipts_for(rt.engine, areq=areq["action_request_id"], type="ACTION_EXECUTING")
    with pytest.raises(ValueError):
        workflows.notify_event(item_id, "buy_now")
    workflows.record_decision(areq["action_request_id"], "NO", areq["payload_hash"], reason="cleanup")
    wait_state(rt.engine, item_id, "ARCHIVED")


def test_planner_draft_is_frozen_into_the_payload(ledger_db):
    """07 F-19: what Michael approves is the draft that goes out, hash-frozen (A-13 extension merge)."""
    from mbos.hashing import sha256_of

    class DraftPlanner:
        def plan(self, item):
            draft = {"content": "Hi — is the trailer still available? (DRY-RUN)", "template_version": "t1"}
            return [{"capability": "comms.email.send", "summary": "first contact", "reversibility": "irreversible",
                     "estimated_cost": {"amount": 0, "currency": "USD"}, "draft": {**draft, "content_hash": sha256_of(draft)}}]

    comps = Components(planner=DraftPlanner()).with_defaults()
    raw = _raw("FIX-TRAILER-1")
    n = FixtureNormalizer()
    with ledger_db.begin() as c:
        item_id = spine.ingest(c, asdict(raw), asdict(n.normalize(raw)), "fx", "0", comps)["item_id"]
    from mbos.reference.placeholder_scorer import PlaceholderScorer
    with ledger_db.begin() as c:
        spine.record_score(c, item_id, asdict(PlaceholderScorer().score(spine.read_item(c, item_id))))
    with ledger_db.begin() as c:
        areq_id = spine.route_recommendation(c, item_id, comps)["action_request_id"]
        areq = c.execute(sa.text("SELECT body FROM mbos.action_requests WHERE action_request_id = :a"), {"a": areq_id}).scalar_one()
    assert areq["payload"]["draft"]["content"].startswith("Hi")
    assert areq["payload_hash"] == sha256_of(areq["payload"])
    with ledger_db.connect() as c:  # F-21: the draft has its own provenance, cited by the request
        bodies = [c.execute(sa.text("SELECT body FROM mbos.provenance WHERE provenance_id = :p"), {"p": p}).scalar_one()
                  for p in areq["provenance_ids"]]
    assert any(b.get("tool_name") == "template:unknown" and b["tool_version"] == "t1" for b in bodies)


def test_no_without_reason_is_decision_refused(ledger_db):
    ids = seed_flow(ledger_db, act=False)
    with ledger_db.begin() as c:
        h = c.execute(sa.text("SELECT payload_hash FROM mbos.action_requests")).scalar_one()
        with pytest.raises(spine.DecisionRefused, match="contract"):
            spine.decide(c, ids["action_request_id"], "NO", h, ids["components"])


def test_outcome_attribution_and_channel(ledger_db):
    ids = seed_flow(ledger_db, outcome=False)
    with ledger_db.begin() as c:
        out = spine.record_outcome(c, ids["item_id"], "flip_acquired", channel="web",
                                   attribution={"first_touch_source": "craigslist", "channel": "organic"})
        tool = c.execute(sa.text("SELECT body->>'tool_name' FROM mbos.provenance WHERE provenance_id = :p"),
                         {"p": out["provenance_ids"][0]}).scalar_one()
    assert out["attribution"]["first_touch_source"] == "craigslist" and tool == "mbos.web.outcome"


def test_policy_denied_proposal_never_awaits_approval(ledger_db):
    """07 F-23 / R21: a PDP-denied proposal leaves the item RECOMMENDED with nothing to approve, and Michael is told."""
    from mbos import card as cardmod
    from mbos.interfaces import PolicyDecision

    class DenyAll:
        def decide(self, areq):
            return PolicyDecision(decision="deny", tier=0, category="email", reason="DENY_TEST", policy_version="t")

    ids = seed_flow(ledger_db, act=False)  # prime comps for a clean second item
    comps = Components(pdp=DenyAll()).with_defaults()
    raw = _raw("FIX-LEAD-SMARTHOME-1")
    n = FixtureNormalizer()
    from mbos.reference.placeholder_scorer import PlaceholderScorer
    with ledger_db.begin() as c:
        item_id = spine.ingest(c, asdict(raw), asdict(n.normalize(raw)), "fx", "0", comps)["item_id"]
    with ledger_db.begin() as c:
        spine.record_score(c, item_id, asdict(PlaceholderScorer().score(spine.read_item(c, item_id))))
    with ledger_db.begin() as c:
        out = spine.route_recommendation(c, item_id, comps)
    assert out["policy_denied"] is True
    with ledger_db.begin() as c:
        item, receipts, areqs = cardmod.load_inputs(c, item_id)
        st = c.execute(sa.text("SELECT status FROM mbos.action_requests WHERE action_request_id = :a"), {"a": out["action_request_id"]}).scalar_one()
        queued = c.execute(sa.text("SELECT count(*) FROM mbos.outbox WHERE topic = 'operator.notify' AND payload->>'kind' = 'policy_denied'")).scalar_one()
        pend = spine.pending_decisions(c)
    assert item["state"] == "RECOMMENDED" and st == "rejected" and queued == 1
    assert all(p["item"]["item_id"] != item_id for p in pend), "nothing for Michael to approve"
    card = cardmod.build_card(item, receipts, areqs)
    assert card["recommendation"]["action"] == "HOLD" and "policy blocked" in card["recommendation"]["why"]


def test_yes_without_step_up_is_refused_when_the_pdp_requires_it(ledger_db):
    """07 F-40: the PDP says step_up=required (even for a reversible request); decide() must refuse the YES up front."""
    from mbos.interfaces import PolicyDecision

    class StepUpPDP:
        def decide(self, areq):
            return PolicyDecision(decision="require_approval", tier=0, category="publishing",
                                  reason="GATED:publishing:tier0; step_up=required", policy_version="t")

    ids = seed_flow(ledger_db, act=False)
    with ledger_db.begin() as c:
        h = c.execute(sa.text("SELECT payload_hash FROM mbos.action_requests")).scalar_one()
        areq = c.execute(sa.text("SELECT body FROM mbos.action_requests")).scalar_one()
    reversible = {**areq, "reversibility": "reversible", "category": "publishing"}
    assert spine.requires_step_up(reversible, Components(pdp=StepUpPDP()).with_defaults()) is True
    assert spine.requires_step_up(reversible, Components().with_defaults()) is False  # the stand-in PDP does not demand it


def test_a_poisonous_listing_does_not_abort_the_batch(ledger_db):
    comps = Components().with_defaults()
    good, bad = _raw("FIX-TRAILER-1"), _raw("FIX-LEAD-SMARTHOME-1")
    n = FixtureNormalizer()
    bad_norm = asdict(n.normalize(bad))
    bad_norm["normalized"]["title"] = "Saw\x00 with a NUL"
    bad_norm["normalized"]["description"] = "line\x07bell \x1b[2J"
    with ledger_db.begin() as c:
        r_bad = spine.ingest_safe(c, asdict(bad), bad_norm, "fx", "0", comps)
        r_good = spine.ingest_safe(c, asdict(good), asdict(n.normalize(good)), "fx", "0", comps)
        item = spine.read_item(c, r_bad["item_id"])
    assert r_bad["created"] and r_good["created"], (r_bad, r_good)           # NUL scrubbed, batch continues
    assert "\x00" not in item["normalized"]["title"] and "needs_review" in item["normalized"]["flags"]
    with ledger_db.begin() as c:                                                # an unrecoverable listing is dropped, not fatal
        r = spine.ingest_safe(c, {"payload": {}, "source": None}, {"dedup_key": "k", "type": "flip", "category": "trailer"}, "fx", "0", comps)
    assert r["dropped"] is True and "error" in r


class _Gov:  # stands in for lane E's Governance handle; proposer_for is patched below
    pass


@pytest.mark.parametrize("answer,expect_proposer", [("agent-06-communications", "agent-06-communications"),
                                                    ("agent-01-coordinator", "agent-01-coordinator"), (None, None)])
def test_proposer_comes_from_lane_e_and_none_means_no_request(ledger_db, monkeypatch, answer, expect_proposer):
    """07 F-41 / 05 E-15: proposed_by = lane E's proposer_for(); None => nobody may propose => no request, card says why."""
    import mbos_governance.spine_adapter as sa

    from mbos import card as cardmod
    from mbos.reference.placeholder_scorer import PlaceholderScorer

    seen = {}

    def fake(gov, capability, lane, spine_identity="agent-01-coordinator"):
        seen.update(capability=capability, lane=lane)
        return answer

    monkeypatch.setattr(sa, "proposer_for", fake)

    class Tagging:
        def plan(self, item):
            return [{"capability": "comms.email.send", "summary": "first contact", "reversibility": "irreversible",
                     "estimated_cost": {"amount": 0, "currency": "USD"}, "lane": "agent-06-communications"}]

    comps = Components(planner=Tagging(), governance=_Gov()).with_defaults()
    raw = _raw("FIX-TRAILER-1")
    with ledger_db.begin() as c:
        item_id = spine.ingest(c, asdict(raw), asdict(FixtureNormalizer().normalize(raw)), "fx", "0", comps)["item_id"]
    with ledger_db.begin() as c:
        spine.record_score(c, item_id, asdict(PlaceholderScorer().score(spine.read_item(c, item_id))))
    with ledger_db.begin() as c:
        out = spine.route_recommendation(c, item_id, comps)
    assert seen == {"capability": "comms.email.send", "lane": "agent-06-communications"}
    with ledger_db.connect() as c:
        item, rc, ar = cardmod.load_inputs(c, item_id)
    if expect_proposer is None:
        assert out["policy_denied"] is True and out["action_request_id"] is None and ar == []
        card = cardmod.build_card(item, rc, ar)
        assert card["recommendation"]["action"] == "HOLD" and "policy blocked" in card["recommendation"]["why"]
    else:
        assert ar[0]["proposed_by"] == expect_proposer and "lane" not in ar[0]["payload"]
