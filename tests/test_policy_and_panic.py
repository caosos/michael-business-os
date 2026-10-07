"""PDP (policy as data) and PANIC state: unit tests incl. fail-closed reads."""
from __future__ import annotations

import json

import pytest

from mbos_governance.panic import FROZEN, RUNNING, PanicStore
from mbos_governance.policy import DENY, REQUIRE_APPROVAL, PolicyStore, PolicyUnavailable, decide

from .conftest import CATEGORY_CAPABILITY


# ---------------------------------------------------------------- policy loading
def test_shipped_policy_loads(env):
    pol = PolicyStore(env.policy_path).current()
    assert pol.data["system_mode"] == "mvp"
    assert pol.data["delegation_enabled"] is False
    assert set(pol.data["categories"]) == set(CATEGORY_CAPABILITY)  # all 11 gated categories present
    assert all(c["tier"] == 0 for c in pol.data["categories"].values())


@pytest.mark.parametrize("mutation", [
    lambda d: d.__setitem__("system_mode", "live"),
    lambda d: d.__setitem__("delegation_enabled", True),
    lambda d: d["categories"]["sms"].__setitem__("tier", 1),
    lambda d: d["categories"]["sms"].__setitem__("decision", "allow"),
    lambda d: d["approval"].__setitem__("allowed_scopes", ["standing_rule"]),
    lambda d: d["budgets"]["live"]["buckets"]["money"].__setitem__("per_action_hard_cap", 1),
    lambda d: d["budgets"]["live"].__setitem__("global_daily_hard_cap", 10),
    lambda d: d["capabilities"]["comms.sms.send"].__setitem__("effector", "twilio"),
    lambda d: d["agent_grants"]["agent-06-communications"].append("money.teleport.send"),  # cross-check
    lambda d: d["capabilities"]["comms.sms.send"].__setitem__("category", "nonsense"),     # cross-check
    lambda d: d["quiet_hours"].__setitem__("timezone", "Mars/Olympus"),                     # cross-check
])
def test_policy_cannot_loosen_wave_one_invariants(env, mutation):
    env.policy_edit(mutation)
    with pytest.raises(PolicyUnavailable):
        PolicyStore(env.policy_path).current()


@pytest.mark.parametrize("content", [None, "", "{not json", "[]", json.dumps({"policy_schema": "x"})])
def test_unreadable_policy_raises(env, content):
    if content is None:
        env.policy_path.unlink()
    else:
        env.policy_path.write_text(content)
    with pytest.raises(PolicyUnavailable):
        PolicyStore(env.policy_path).current()


def test_policy_store_never_serves_stale_policy_after_breakage(env):
    ps = PolicyStore(env.policy_path)
    ps.current()
    env.policy_path.write_text("{broken")
    with pytest.raises(PolicyUnavailable):
        ps.current()


# ---------------------------------------------------------------- decide()
def test_decide_requires_approval_tier0_for_every_category(env):
    pol = PolicyStore(env.policy_path).current()
    for cat in CATEGORY_CAPABILITY:
        d = decide(env.ar(cat), pol)
        assert (d.decision, d.tier) == (REQUIRE_APPROVAL, 0), (cat, d)
        assert d.policy_decision_ref.startswith("pdp_")


def test_decide_forces_tier_zero(env):
    pol = PolicyStore(env.policy_path).current()
    d = decide(env.ar("email", tier=2), pol)
    assert d.tier == 0 and any(r.startswith("TIER_FORCED") for r in d.reasons)


@pytest.mark.parametrize("over,reason", [
    ({"capability": "comms.fax.send"}, "UNKNOWN_CAPABILITY"),
    ({"category": "sms"}, "CATEGORY_MISMATCH"),
    ({"proposed_by": "agent-02-opportunity"}, "CAPABILITY_NOT_HELD"),
    ({"estimated_cost": {"amount": 1, "currency": "EUR"}}, "CURRENCY_NOT_ALLOWED"),
])
def test_decide_denies(env, over, reason):
    pol = PolicyStore(env.policy_path).current()
    ar = env.ar("email")
    ar.update(over)
    d = decide(ar, pol)
    assert d.decision == DENY and d.reasons[-1].startswith(reason)


def test_comms_agent_cannot_hold_money_capability(env):
    """§17 #21: comms agent attempts money.* -> impossible (capability not held)."""
    pol = PolicyStore(env.policy_path).current()
    d = decide(env.ar("money", proposed_by="agent-06-communications"), pol)
    assert d.decision == DENY and "CAPABILITY_NOT_HELD" in d.reasons[-1]


def test_money_requires_cost_estimate(env):
    pol = PolicyStore(env.policy_path).current()
    ar = env.ar("money")
    del ar["estimated_cost"]
    assert decide(ar, pol).reasons[-1].startswith("COST_ESTIMATE_REQUIRED")


# ---------------------------------------------------------------- PANIC state
def test_missing_panic_file_is_frozen(tmp_path):
    st = PanicStore(tmp_path / "nope.json").read()
    assert st.globally_frozen and not st.readable
    assert st.blocks("a", "b", "c")


@pytest.mark.parametrize("content", ["", "{", "[]", '{"schema":"mbos.governance.panic/1"}', "\x00\x01"])
def test_garbage_panic_file_is_frozen(tmp_path, content):
    p = tmp_path / "panic.json"
    p.write_text(content)
    st = PanicStore(p).read()
    assert st.globally_frozen and st.blocks(None, None, None)


def test_hand_edited_panic_file_fails_checksum(env):
    raw = json.loads(env.panic.path.read_text())
    raw["global"]["state"] = RUNNING
    raw["agents"] = {}
    raw["revision"] = 99  # any edit without re-sealing
    env.panic.path.write_text(json.dumps(raw))
    st = env.panic.read()
    assert not st.readable and "checksum" in st.error


def test_init_defaults_to_frozen(tmp_path):
    ps = PanicStore(tmp_path / "p.json")
    ps.init("michael", "bootstrap")
    assert ps.read().global_state == FROZEN


def test_mutation_never_repairs_unreadable_into_running(env):
    env.panic.path.write_text("{garbage")
    env.panic.mutate("L1", "agent-07-marketing", True, "michael", "x")
    st = env.panic.read()
    assert st.readable and st.global_state == FROZEN  # rebuilt FROZEN, not RUNNING


def test_levels(env):
    env.panic.mutate("L1", "agent-07-marketing", True, "michael", "misbehaving")
    env.panic.mutate("L2", "money.*", True, "michael", "freeze money")
    env.panic.mutate("L2", "category:sms", True, "michael", "freeze sms")
    st = env.panic.read()
    assert st.blocks("agent-07-marketing", "publish.listing.create", "publishing") == ["PANIC_L1_AGENT:agent-07-marketing"]
    assert st.blocks("agent-01-coordinator", "money.payment.send", "money") == ["PANIC_L2_CAPABILITY:money.*"]
    assert st.blocks("agent-06-communications", "comms.sms.send", "sms") == ["PANIC_L2_CATEGORY:sms"]
    assert st.blocks("agent-06-communications", "comms.email.send", "email") == []
    env.panic.mutate("L3", None, True, "michael", "stop")
    assert "PANIC_L3_FROZEN" in env.panic.read().blocks("agent-06-communications", "comms.email.send", "email")
