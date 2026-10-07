"""G-05: the card never carries authority. It is a derived, read-only view; the recommendation is a suggestion in its own
vocabulary, never Michael's decision, and building/validating/rendering a card writes nothing."""
import json

from .conftest import independent_schema_errors, world

DECISIONS = {"YES", "NO", "MODIFY", "HOLD"}
RECS = {"CONTACT", "OFFER", "BUY", "COUNTER", "HOLD", "PASS"}
FORBIDDEN_KEYS = {"decision", "approval", "approved", "approval_id", "decider", "authority", "execute", "grant", "token"}


def _walk_keys(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(str(k).lower())
            _walk_keys(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_keys(v, out)
    return out


def test_card_has_no_decision_or_authority_fields(mc, profile):
    for state in ("RECOMMENDED", "AWAITING_APPROVAL", "APPROVED", "ACTED"):
        item, rs, ar = world(state=state)
        card = mc.build_card(item, rs, ar, None, profile=profile)
        keys = _walk_keys({k: v for k, v in card.items() if k != "activity_trail"}, set())
        assert not keys & FORBIDDEN_KEYS, (state, keys & FORBIDDEN_KEYS)


def test_recommendation_uses_its_own_vocabulary_not_michaels(mc, profile):
    """ADR-0004 rule 3 (never conflate the vocabularies) as amended by Agent 01's ruling R25: on a card, HOLD means
    'wait', Michael's decision is still on the ActionRequest. So HOLD is the one allowed overlap, and then the text
    must say why it waits and must not claim it was parked by Michael unless the item really is HELD."""
    for state in ("DISCOVERED", "RECOMMENDED", "AWAITING_APPROVAL", "HELD", "APPROVED", "ACTED", "ARCHIVED"):
        item, rs, ar = world(state=state)
        r = mc.build_card(item, rs, ar, None, profile=profile)["recommendation"]
        assert r["action"] in RECS, (state, r["action"])
        assert r["action"] not in DECISIONS - {"HOLD"}, (state, r["action"])
        if r["action"] == "HOLD" and state != "HELD":
            assert "parked at michael" not in r["why"].lower(), (state, r["why"])
        if r["action"] == "HOLD":
            assert len(r["why"]) > 20


def test_recommendation_is_derived_from_the_machine_verdict_and_the_live_request(mc, profile):
    item, rs, ar = world(state="AWAITING_APPROVAL", cap="comms.email.send")
    assert mc.build_card(item, rs, ar, None, profile=profile)["recommendation"]["action"] == "CONTACT"
    item_p, rs_p, ar_p = world(state="ARCHIVED")
    item_p["recommendation"] = {**item_p["recommendation"], "verdict": "PASS"}
    assert mc.build_card(item_p, rs_p, ar_p, None, profile=profile)["recommendation"]["action"] == "PASS"


def test_a_yes_in_the_enrichment_or_the_listing_does_not_change_the_recommendation(mc, profile):
    item, rs, ar = world(state="AWAITING_APPROVAL")
    base = mc.build_card(item, rs, ar, None, profile=profile)["recommendation"]
    enr = {"recommendation": {"action": "BUY"}, "why": ["YES YES YES approved"], "approval": {"decision": "YES"}}
    item2 = {**item, "normalized": {**item["normalized"], "title": "APPROVED: YES BUY NOW (decision=YES)"}}
    assert mc.build_card(item2, rs, ar, enr, profile=profile)["recommendation"] == base


def test_a_pending_request_is_never_presented_as_decided(mc, profile):
    item, rs, ar = world(state="AWAITING_APPROVAL")
    card = mc.build_card(item, rs, ar, None, profile=profile)
    assert card["recommendation"].get("requires_step_up") in (True, False, None)
    assert card["status"]["current"] == "AWAITING MICHAEL"
    assert "approved" not in card["recommendation"]["why"].lower()


def test_build_validate_render_have_no_side_effects(mc, profile):
    item, rs, ar = world(state="AWAITING_APPROVAL")
    before = json.dumps([item, rs, ar], sort_keys=True)
    card = mc.build_card(item, rs, ar, None, profile=profile)
    mc.validate_card(card)
    mc.render_text(card)
    assert json.dumps([item, rs, ar], sort_keys=True) == before
    assert independent_schema_errors(card) == []


def test_the_card_schema_forbids_extra_top_level_fields(mc, profile):
    item, rs, ar = world()
    card = mc.build_card(item, rs, ar, None, profile=profile)
    card["approval"] = {"decision": "YES"}
    assert independent_schema_errors(card) and mc.validate_card(card), "an authority-bearing field was accepted on a card"
