"""E-08: sandbox spec (data) + invariant checker. Doc + checker only."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mbos_governance import PolicyStore
from mbos_governance.sandbox import check, host_readiness, load

REPO = Path(__file__).resolve().parents[1]
SPEC = load(REPO / "policy" / "sandbox.v1.json")


def comp(spec, cid):
    return next(c for c in spec["components"] if c["id"] == cid)


def test_shipped_spec_passes(env):
    assert check(SPEC, PolicyStore(env.policy_path).current().data) == []
    assert {c["kind"] for c in SPEC["components"]} == {"gateway", "orchestrator", "operator_ui", "source_adapter",
                                                       "llm_agent", "model_generated_code"}


@pytest.mark.parametrize("cid,mutate,inv", [
    ("discovery-adapters", lambda c: c.__setitem__("runtime", "host"), "I1"),
    ("model-generated-code", lambda c: c.__setitem__("network", "egress_proxy"), "I2"),
    ("model-generated-code", lambda c: c["secrets"].append("llm:litellm_virtual_key"), "I2"),
    ("llm-agents", lambda c: c.__setitem__("runtime", "e2b"), "I2"),
    ("llm-agents", lambda c: c["secrets"].append("effector:twilio"), "I3"),
    ("spine-dbos", lambda c: c["db_roles"].append("gateway"), "I3"),
    ("discovery-adapters", lambda c: c["db_roles"].append("approver"), "I4"),
    ("llm-agents", lambda c: c["secrets"].append("ui:session_key"), "I4"),
    ("discovery-adapters", lambda c: c.__setitem__("untrusted_input", False), "I4"),
    ("action-gateway", lambda c: c["db_roles"].append("policy_admin"), "I5"),
    ("action-gateway", lambda c: c["db_roles"].append("approver"), "I5"),
    ("operator-ui", lambda c: c.__setitem__("privileged", True), "I6"),
    ("operator-ui", lambda c: c.__setitem__("mounts_container_socket", True), "I6"),
    ("spine-dbos", lambda c: c.__setitem__("host_network", True), "I6"),
    ("spine-dbos", lambda c: c.__setitem__("rootfs_readonly", False), "I6"),
    ("llm-agents", lambda c: c["limits"].pop("pids"), "I6"),
    ("llm-agents", lambda c: c.__setitem__("uid", "mbos-discovery"), "I7"),
    ("llm-agents", lambda c: c.__setitem__("network", "host"), "I7"),
])
def test_each_invariant_is_enforced(env, cid, mutate, inv):
    spec = copy.deepcopy(SPEC)
    mutate(comp(spec, cid))
    problems = check(spec, PolicyStore(env.policy_path).current().data)
    assert any(f"({inv})" in p and p.startswith(cid) for p in problems), problems


def test_unknown_owner_and_duplicate_id(env):
    spec = copy.deepcopy(SPEC)
    spec["components"].append(copy.deepcopy(spec["components"][0]))
    comp(spec, "llm-agents")["owner"] = "agent-99"
    problems = check(spec, PolicyStore(env.policy_path).current().data)
    assert any("duplicate id" in p for p in problems) and any("agent-99" in p for p in problems)


@pytest.mark.parametrize("bad", [None, {}, {"sandbox_schema": "x", "components": []}, {"sandbox_schema": "mbos.governance.sandbox/1"}])
def test_malformed_spec(bad):
    assert check(bad) == ["spec: wrong schema or no components"]


def test_missing_fields_reported():
    spec = {"sandbox_schema": "mbos.governance.sandbox/1", "components": [{"id": "x"}]}
    assert check(spec)[0].startswith("x: missing")


def test_host_readiness_is_report_only():
    r = host_readiness()
    assert set(r["tools"]) == {"runsc", "podman", "docker", "e2b"} and isinstance(r["gvisor_ready"], bool)


def test_cli(env, capsys):
    from mbos_governance.cli import main
    assert main(["--policy", str(env.policy_path), "sandbox", "check", "--spec", str(REPO / "policy/sandbox.v1.json"),
                 "--host"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and "gvisor_ready" in out["host"]
