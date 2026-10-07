"""E-06: PDP policy data in lane D's mbos.policy / policy_current (publish receipted; read fail-closed)."""
from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

from mbos_governance import ActionGateway, PolicyStore, PolicyUnavailable, decide
from mbos_governance.gateway import GatewayRefused
from mbos_governance.policy_pg import DOC_KEY, PgPolicyStore, publish

from .conftest import CATEGORY_CAPABILITY

REPO = Path(__file__).resolve().parents[1]


def _publish(env, actor="michael"):
    return publish(env.dsn("policy_admin"), env.policy_path, env.policy_path.with_name("content_rules.v1.json"), actor)


def _db_gateway(env) -> ActionGateway:
    return ActionGateway(env.store, PgPolicyStore(env.dsn("gateway")), env.panic, clock=env.clock,
                         journal_path=env.tmp / "j.jsonl")


def test_packaged_schema_matches_repo_schema():
    assert (REPO / "src/mbos_governance/schemas/policy.schema.json").read_bytes() == \
        (REPO / "policy/policy.schema.json").read_bytes()


def test_publish_is_receipted_and_db_policy_equals_file(env):
    out = _publish(env)
    assert len(out["published"]) == 2 + 11 + 12 and out["unchanged"] == []
    bumps = [r for r in env.store.receipts() if r["type"] == "CONFIG_VERSION_BUMPED" and r.get("entity_type") == "policy"]
    assert len(bumps) == 25 and all(r["actor"] == {"type": "human", "id": "michael"} for r in bumps)
    db, file = PgPolicyStore(env.dsn("gateway")).current(), PolicyStore(env.policy_path).current()
    assert db.version == file.version == out["policy_version"] and db.data == file.data


def test_same_decisions_as_the_file(env):
    _publish(env)
    db, file = PgPolicyStore(env.dsn("gateway")).current(), PolicyStore(env.policy_path).current()
    cases = [env.ar(c) for c in CATEGORY_CAPABILITY]
    cases += [{**env.ar("email"), "capability": "comms.fax.send"}, {**env.ar("money"), "proposed_by": "agent-06-communications"},
              {**env.ar("email"), "tier": 2}]
    for ar in cases:
        a, b = decide(ar, db), decide(ar, file)
        assert (a.decision, a.tier, a.reasons, a.policy_version) == (b.decision, b.tier, b.reasons, b.policy_version)


def test_republish_is_idempotent_and_change_bumps_only_what_changed(env):
    _publish(env)
    assert _publish(env)["published"] == []
    env.policy_edit(lambda d: d["quiet_hours"].__setitem__("start", "21:00"))
    out = _publish(env)
    assert out["published"] == [DOC_KEY]                      # the matrix rows did not change
    assert env.sql("SELECT version FROM mbos.policy_current WHERE policy_key=%s", (DOC_KEY,))[0][0] == 2
    assert PgPolicyStore(env.dsn("gateway")).current().data["quiet_hours"]["start"] == "21:00"


def test_no_published_policy_denies_everything(env):
    gw = _db_gateway(env)
    with pytest.raises(PolicyUnavailable, match="default deny"):
        gw.policies.current()
    ar = env.ar("email")
    with pytest.raises(GatewayRefused, match="CONTENT_RULES_UNREADABLE"):  # rules travel with the policy
        gw.propose(ar, ar["proposed_by"])


def test_full_flow_on_db_policy(env):
    _publish(env)
    gw = _db_gateway(env)
    ar = env.ar("purchase")
    assert gw.propose(ar, ar["proposed_by"]).outcome == "pending_approval"
    assert gw.record_approval(env.approval(ar)).status == "approved"
    res = gw.execute(ar["action_request_id"])
    assert res.outcome == "executed" and res.effector_response["dry_run"] is True
    secret = env.ar("email", payload={"to_ref": "relay:EXAMPLE-0001", "body": "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"})
    with pytest.raises(GatewayRefused, match="SECRET_IN_PAYLOAD"):            # content rules read from the DB too
        gw.propose(secret, secret["proposed_by"])


@pytest.mark.parametrize("tamper,match", [
    ("jsonb_set(limits, '{document,categories,sms,tier}', '1')", "schema"),          # loosen in place: pinned schema refuses
    ("jsonb_set(limits, '{document,quiet_hours,start}', '\"23:00\"')", "hash"),       # silent edit: version hash mismatch
])
def test_tampered_document_row_fails_closed(env, tamper, match):
    _publish(env)
    env.sql(f"UPDATE mbos.policy SET limits = {tamper} WHERE policy_key = %s", (DOC_KEY,), replica=True)
    with pytest.raises(PolicyUnavailable, match=match):
        PgPolicyStore(env.dsn("gateway")).current()


def test_per_key_row_drift_fails_closed(env):
    _publish(env)
    with psycopg.connect(env.dsn("policy_admin"), autocommit=True) as c:   # a stray matrix edit outside publish()
        prov = c.execute("SELECT mbos.record_provenance(%s)", (json.dumps(
            {"actor_type": "human", "human_actor": "michael", "basis": "FACT", "tool_name": "psql", "tool_version": "16"}),)).fetchone()[0]
        c.execute("SELECT mbos.publish_policy(%s, %s, 'hand edit', 'k-drift')", (json.dumps({
            "policy_key": "category:email", "version": 2, "category": "email", "tier": 0, "decision": "deny",
            "limits": {}, "created_by": "michael", "reason": "hand edit", "provenance_ids": [prov]}),
            json.dumps({"type": "human", "id": "michael"})))
    with pytest.raises(PolicyUnavailable, match="disagree"):
        PgPolicyStore(env.dsn("gateway")).current()


def test_loosened_file_is_refused_at_publish(env):
    env.policy_edit(lambda d: d.__setitem__("delegation_enabled", True))
    with pytest.raises(PolicyUnavailable):
        _publish(env)
    assert env.sql("SELECT count(*) FROM mbos.policy WHERE policy_key LIKE 'governance:%%'")[0][0] == 0


def test_only_policy_admin_may_publish(env):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        publish(env.dsn("agent_write"), env.policy_path, env.policy_path.with_name("content_rules.v1.json"), "agent-07-marketing")


def test_lane_d_refuses_money_allow_row(env):
    with psycopg.connect(env.dsn("policy_admin"), autocommit=True) as c, pytest.raises(psycopg.errors.CheckViolation):
        prov = c.execute("SELECT mbos.record_provenance(%s)", (json.dumps(
            {"actor_type": "system", "basis": "FACT", "tool_name": "t", "tool_version": "1"}),)).fetchone()[0]
        c.execute("SELECT mbos.publish_policy(%s, %s, 'x', 'k-allow')", (json.dumps({
            "policy_key": "category:money", "version": 1, "category": "money", "tier": 0, "decision": "allow",
            "limits": {}, "created_by": "x", "reason": "x", "provenance_ids": [prov]}), json.dumps({"type": "system", "id": "x"})))


def test_cli_publish_and_check(env, monkeypatch, capsys):
    from mbos_governance.cli import main
    for role, dsn in env.dsns.items():
        monkeypatch.setenv(f"MBOS_GOV_DSN_{role.upper()}", dsn)
    monkeypatch.setenv("MBOS_POLICY_SOURCE", "db")
    assert main(["--policy", str(env.policy_path), "policy", "check"]) == 1          # nothing published yet
    assert main(["--policy", str(env.policy_path), "policy", "publish", "--actor", "michael"]) == 0
    assert main(["--policy", str(env.policy_path), "policy", "check"]) == 0
    assert "2026.10.07" in capsys.readouterr().out


def test_spine_adapter_build_defaults_to_db_policy(env):
    import sys
    sys.path.insert(0, str(REPO / "tests/vendor/agent01_mbos"))
    from mbos_governance.spine_adapter import build
    gov = build(env.dsns)                                  # production default: no policy file
    assert isinstance(gov.action_gateway.policies, PgPolicyStore)
    assert gov.pdp.decide(env.ar("email")).decision == "deny"            # nothing published: default deny
    _publish(env)
    d = gov.pdp.decide(env.ar("email"))
    assert (d.decision, d.tier) == ("require_approval", 0)
