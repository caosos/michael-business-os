"""E-16 (06 P-06-16): binding-key check is top-level for generic names, any-depth only for unambiguous amount names."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "vendor/agent01_mbos"))
from mbos_governance import PolicyStore, decide  # noqa: E402
from mbos_governance import spine_adapter as sa  # noqa: E402

from .conftest import REPO  # noqa: E402
from .test_e12_recommendation_actions import ar_for  # noqa: E402

SHIPPED = REPO / "policy" / "policy.v1.json"
COMMS = [("comms.email.send", "email"), ("comms.sms.send", "sms"), ("comms.message.send", "message")]


def verdict(env, cap, cat, payload, agent="agent-06-communications"):
    return decide(ar_for(env, cap, cat, agent, payload={"to_ref": "r", **payload}), PolicyStore(env.policy_path).current())


@pytest.mark.parametrize("cap,cat", COMMS)
@pytest.mark.parametrize("payload", [
    {"meta": {"binding": False}},                       # 06's accident: a nested `binding: false`
    {"draft": {"flags": [{"binding": False}]}},
    {"meta": {"offer": "see attached flyer"}},           # a nested generic name is just text
    {"notes": {"counter": "n/a", "binding": True}},      # nested generic names are allowed at any value
    {"body": "I may make an offer later", "offer_note": "none"},   # VALUES are never scanned; similar names are fine
])
def test_nested_generic_names_are_allowed(env, cap, cat, payload):
    assert verdict(env, cap, cat, payload).decision == "require_approval"


@pytest.mark.parametrize("cap,cat", COMMS)
@pytest.mark.parametrize("key", ["offer", "counter", "binding", "OFFER", "Counter_Offer", "offer_amount", "offer_usd", "bid_amount"])
def test_top_level_reserved_names_are_denied(env, cap, cat, key):
    d = verdict(env, cap, cat, {key: 850})
    assert d.decision == "deny" and "BINDING_UNDER_COMMS" in d.reasons[-1]


def test_top_level_binding_false_is_still_reserved(env):
    d = verdict(env, "comms.email.send", "email", {"binding": False})
    assert d.decision == "deny" and "BINDING_UNDER_COMMS:binding" in d.reasons[-1]


@pytest.mark.parametrize("payload", [{"meta": {"offer_amount": 1}}, {"a": [{"b": {"counter_offer": 2}}]},
                                     {"deep": {"er": {"Bid_Amount": 3}}}, {"x": {"offer_usd": 4}}])
def test_unambiguous_amount_names_are_denied_at_any_depth(env, payload):
    for cap, cat in COMMS:
        d = verdict(env, cap, cat, payload)
        assert d.decision == "deny" and "BINDING_UNDER_COMMS" in d.reasons[-1]


def test_publish_uses_the_same_rule(env):
    pub = lambda p: verdict(env, "publish.listing.create", "publishing", p, agent="agent-07-marketing")  # noqa: E731
    assert pub({"title": "Trailer", "meta": {"binding": False}}).decision == "require_approval"
    d = pub({"title": "Trailer", "offer": 900})
    assert d.decision == "deny" and "BINDING_UNDER_PUBLISH:offer" in d.reasons[-1]
    assert pub({"title": "x", "listing": {"offer_usd": 5}}).decision == "deny"


def test_binding_offers_still_flow_through_offer_capabilities(env):
    for p in ({"offer": 850}, {"meta": {"binding": False}, "counter_offer": 700}):
        assert verdict(env, "offer.email.send", "offer", p).decision == "require_approval"


def test_lanes_can_pin_their_planners(env):
    gov = sa.build(env.dsns, str(SHIPPED), egress_file=None, litellm_file=None)
    assert sa.binding_key_violations(gov, "comms.email.send", {"meta": {"binding": False}}) == []
    assert sa.binding_key_violations(gov, "comms.email.send", {"offer": 1, "meta": {"bid_amount": 2}}) == ["bid_amount", "offer"]
    assert sa.binding_key_violations(gov, "publish.listing.create", {"counter": 1}) == ["counter"]
    assert sa.binding_key_violations(gov, "offer.email.send", {"offer": 1}) == []           # binding capability: not applicable
    bad = sa.build(env.dsns, str(env.tmp / "missing.json"), egress_file=None, litellm_file=None)
    assert sa.binding_key_violations(bad, "comms.email.send", {}) == ["POLICY_UNREADABLE"]


def test_the_lists_are_published_in_the_shipped_policy():
    ra = PolicyStore(SHIPPED).current().data["recommendation_actions"]
    assert set(ra["binding_payload_keys_any_depth"]) <= set(ra["binding_payload_keys"])
    assert {"offer", "counter", "binding", "offer_amount", "counter_offer"} <= set(ra["binding_payload_keys"])
    assert "TOP LEVEL" in ra["binding_keys_note"] and "ANY depth" in ra["binding_keys_note"]
