"""PDP (policy as data) and PANIC state: unit tests incl. fail-closed reads."""
from __future__ import annotations

import json

import pytest

from mbos_governance.panic import FROZEN, RUNNING
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


# ---------------------------------------------------------------- PANIC state (lane D panic_state via PgPanicStore)
def test_fresh_database_bootstraps_frozen(cluster, tmp_path):
    import psycopg
    from mbos_governance import PgPanicStore
    from .conftest import TEMPLATE_DB
    name = "t05_bootstrap_frozen"
    with psycopg.connect(f"{cluster['base']} dbname=postgres user=postgres", autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name}")
        c.execute(f"CREATE DATABASE {name} TEMPLATE {TEMPLATE_DB}")
    st = PgPanicStore(f"{cluster['base']} dbname={name} user=mbos_gateway").read()
    assert st.readable and st.global_state == FROZEN  # lane D 0007 bootstrap: releasing is Michael's act


def test_unreachable_database_is_frozen():
    from mbos_governance import PgPanicStore
    st = PgPanicStore("host=/nonexistent-socket-dir port=1 dbname=x user=y", connect_timeout=1).read()
    assert st.globally_frozen and not st.readable and st.blocks("a", "b", "c")


def test_empty_panic_state_is_frozen(env):
    env.sql("DELETE FROM mbos.panic_state", replica=True)
    st = env.panic.read()
    assert st.globally_frozen and not st.readable and st.blocks(None, None, None)


def test_hand_edited_panic_state_fails_checksum(env):
    env.freeze_sql("L1", "agent-07-marketing")
    env.sql("UPDATE mbos.panic_state SET body = jsonb_set(body, '{agents}', '{}') "
            "WHERE revision = (SELECT max(revision) FROM mbos.panic_state)", replica=True)
    st = env.panic.read()
    assert not st.readable and "checksum" in st.error


def test_engage_on_unreadable_state_rebuilds_frozen(env):
    env.sql("UPDATE mbos.panic_state SET body = jsonb_set(body, '{schema}', '\"x\"') "
            "WHERE revision = (SELECT max(revision) FROM mbos.panic_state)", replica=True)
    env.gw.engage_panic("L1", "agent-07-marketing", "michael", "x")
    st = env.panic.read()
    assert st.readable and st.global_state == FROZEN  # rebuilt FROZEN, never repaired into RUNNING


def test_levels(env):
    env.gw.engage_panic("L1", "agent-07-marketing", "michael", "misbehaving")
    env.gw.engage_panic("L2", "money.*", "michael", "freeze money")
    env.gw.engage_panic("L2", "category:sms", "michael", "freeze sms")
    st = env.panic.read()
    assert st.blocks("agent-07-marketing", "publish.listing.create", "publishing") == ["PANIC_L1_AGENT:agent-07-marketing"]
    assert st.blocks("agent-01-coordinator", "money.payment.send", "money") == ["PANIC_L2_CAPABILITY:money.*"]
    assert st.blocks("agent-06-communications", "comms.sms.send", "sms") == ["PANIC_L2_CATEGORY:sms"]
    assert st.blocks("agent-06-communications", "comms.email.send", "email") == []
    env.gw.engage_panic("L3", None, "michael", "stop")
    assert "PANIC_L3_FROZEN" in env.panic.read().blocks("agent-06-communications", "comms.email.send", "email")


def test_python_and_sql_blocks_agree(env):
    """PanicState.blocks (05) and mbos.panic_blocks (lane D) give the same reasons."""
    env.gw.engage_panic("L1", "agent-07-marketing", "michael", "a")
    env.gw.engage_panic("L2", "discovery.source.*", "michael", "b")
    env.gw.engage_panic("L2", "category:sms", "michael", "c")
    st = env.panic.read()
    for args in [("agent-07-marketing", "publish.listing.create", "publishing"),
                 ("agent-02-opportunity", "discovery.source.ebay.read", "discovery"),
                 ("agent-06-communications", "comms.sms.send", "sms"),
                 ("agent-06-communications", "comms.email.send", "email")]:
        sql = env.sql("SELECT mbos.panic_blocks(%s, %s, %s)", args)[0][0]
        assert sorted(sql) == sorted(st.blocks(*args)), args
