"""E-03: A8/A9 hardening, dry. L3 cancels unstarted DBOS workflows, egress deny-all file,
per-agent LiteLLM budget generator. Every test runs with outbound sockets disabled."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from mbos_governance import PolicyStore
from mbos_governance.hooks import (DbosCancelHook, EgressPolicyHook, LiteLLMBudgetHook, render_egress,
                                   render_litellm_keys, verify_sealed)
from mbos_governance.panic import PanicState

REPO = Path(__file__).resolve().parents[1]


class NetworkUsed(AssertionError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Nothing in E-03 may reach the network: any outbound connect fails the test."""
    def boom(*a, **k):
        raise NetworkUsed(f"network call attempted: {a[1:] if len(a) > 1 else a}")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket.socket, "connect_ex", boom)
    monkeypatch.setattr(socket, "create_connection", boom)


class FakeWF:
    def __init__(self, wid, status):
        self.workflow_id, self.status = wid, status


class FakeDBOS:
    def __init__(self, wfs):
        self.wfs = {w.workflow_id: w for w in wfs}
        self.cancel_calls = []

    def list_workflows(self, *, status):
        return [w for w in self.wfs.values() if w.status in status]

    def cancel_workflows(self, workflow_ids):
        self.cancel_calls.append(list(workflow_ids))
        for i in workflow_ids:
            self.wfs[i].status = "CANCELLED"


def hooked(env, dbos=None):
    ps = PolicyStore(env.policy_path)
    hooks = [EgressPolicyHook(env.tmp / "egress.json", ps), LiteLLMBudgetHook(env.tmp / "litellm.json", ps)]
    if dbos is not None:
        hooks.insert(0, DbosCancelHook(dbos))
    env.gw.panic_hooks = hooks
    return env


def kill_switch_receipts(env):
    return [r for r in env.store.receipts() if r["type"] == "KILL_SWITCH_CHANGED"]


# ---------------------------------------------------------------- DBOS cancel hook
def test_l3_cancels_unstarted_and_reports_in_flight(env):
    dbos = FakeDBOS([FakeWF("w1", "ENQUEUED"), FakeWF("w2", "DELAYED"), FakeWF("w3", "PENDING"), FakeWF("w4", "SUCCESS")])
    out = hooked(env, dbos).gw.engage_panic("L3", None, "michael", "stop")
    res = out["hooks"]["dbos_cancel"]
    assert res == {"ok": True, "cancelled": ["w1", "w2"], "in_flight_at_freeze": ["w3"]}
    assert dbos.wfs["w3"].status == "PENDING"  # started work is not killed; the gateway's late PANIC read stops it
    assert kill_switch_receipts(env)[-1]["details"]["hooks"]["dbos_cancel"]["cancelled"] == ["w1", "w2"]


@pytest.mark.parametrize("level,target", [("L1", "agent-07-marketing"), ("L2", "money.*")])
def test_l1_l2_do_not_cancel_workflows(env, level, target):
    dbos = FakeDBOS([FakeWF("w1", "ENQUEUED")])
    hooked(env, dbos).gw.engage_panic(level, target, "michael", "narrow freeze")
    assert dbos.cancel_calls == []


def test_failing_hook_never_blocks_the_freeze(env):
    class Broken:
        name = "broken"

        def on_change(self, *a):
            raise RuntimeError("engine down")
    env.gw.panic_hooks = [Broken()]
    out = env.gw.engage_panic("L3", None, "michael", "stop")
    assert env.panic.read().globally_frozen
    assert out["hooks"]["broken"] == {"ok": False, "error": "RuntimeError: engine down"}
    assert kill_switch_receipts(env)[-1]["details"]["hooks"]["broken"]["ok"] is False


@pytest.mark.skipif(subprocess.run([sys.executable, "-c", "import dbos"], capture_output=True).returncode != 0,
                    reason="dbos not installed (pip install 'dbos>=3.2,<4')")
def test_l3_cancels_real_dbos_queue(env, tmp_path):
    """Real DBOS 3.2 on a local SQLite system DB, in a subprocess (DBOS is process-global),
    with outbound sockets disabled inside the subprocess too."""
    script = textwrap.dedent(f"""
        import json, socket, threading, time, shutil, sys
        def boom(*a, **k): raise RuntimeError("network call attempted")
        socket.socket.connect = boom; socket.create_connection = boom
        sys.path.insert(0, {str(REPO / "src")!r})
        from pathlib import Path
        from dbos import DBOS
        from mbos_governance import ActionGateway, PgGovernanceStore, PgPanicStore, PolicyStore
        from mbos_governance.hooks import DbosCancelHook
        tmp = Path({str(tmp_path)!r}) / "sub"
        tmp.mkdir()
        (tmp / "policy").mkdir()
        for f in ("policy.v1.json", "policy.schema.json", "content_rules.v1.json"):
            shutil.copy({str(REPO / "policy")!r} + "/" + f, tmp / "policy" / f)
        DBOS(config={{"name": "mbos-e03", "system_database_url": "sqlite:///" + str(tmp / "dbos.sqlite")}})
        gate = threading.Event()
        @DBOS.workflow()
        def act(i):
            gate.wait(20); return i
        DBOS.launch()
        DBOS.register_queue("act_q", concurrency=1)
        q = DBOS.retrieve_queue("act_q")
        handles = [q.enqueue(act, i) for i in range(4)]
        deadline = time.time() + 15
        while time.time() < deadline and not DBOS.list_workflows(status=["PENDING"]):
            time.sleep(0.1)
        dsns = json.loads({json.dumps(env.dsns)!r})
        gw = ActionGateway(PgGovernanceStore(dsns), PolicyStore(tmp / "policy/policy.v1.json"),
                           PgPanicStore(dsns["gateway"]), panic_hooks=[DbosCancelHook(DBOS)],
                           journal_path=tmp / "j.jsonl")
        out = gw.engage_panic("L3", None, "michael", "real dbos test")
        gate.set(); time.sleep(2)
        final = sorted(w.status for w in DBOS.list_workflows())
        DBOS.destroy()
        print(json.dumps({{"hook": out["hooks"]["dbos_cancel"], "final": final}}))
    """)
    p = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stderr[-2000:]
    res = json.loads(p.stdout.strip().splitlines()[-1])
    assert res["hook"]["ok"] and len(res["hook"]["cancelled"]) == 3 and len(res["hook"]["in_flight_at_freeze"]) == 1
    assert res["final"] == ["CANCELLED", "CANCELLED", "CANCELLED", "SUCCESS"]


# ---------------------------------------------------------------- egress policy file
def test_egress_default_is_deny_with_empty_allow(env):
    doc = render_egress(PolicyStore(env.policy_path).current().data, env.panic.read())
    assert doc["default"] == "deny" and doc["allow"] == {} and not doc["deny_all"] and verify_sealed(doc)


def test_l3_writes_deny_all_egress_file(env):
    hooked(env).gw.engage_panic("L3", None, "michael", "stop")
    doc = json.loads((env.tmp / "egress.json").read_text())
    assert verify_sealed(doc) and doc["deny_all"] and doc["allow"] == {} and "PANIC_L3_FROZEN" in doc["reasons"]


def test_egress_allow_list_cannot_be_opened_in_wave_one(env):
    from mbos_governance.policy import PolicyUnavailable
    env.policy_edit(lambda d: d["egress"]["allow"].__setitem__("agent-02-opportunity", ["api.ebay.com"]))
    with pytest.raises(PolicyUnavailable):
        PolicyStore(env.policy_path).current()


def test_egress_l1_drops_agent_and_unreadable_state_is_deny_all():
    data = {"version": "t", "egress": {"default": "deny", "allow": {"a": ["x.example"], "b": ["y.example"]}}}
    st = PanicState("RUNNING", frozen_agents={"a": {}})
    assert render_egress(data, st)["allow"] == {"b": ["y.example"]}  # generator logic beyond wave-one data
    unread = PanicState("FROZEN", readable=False, error="missing")
    assert render_egress(data, unread)["deny_all"] and render_egress(data, unread)["allow"] == {}
    assert render_egress(None, st)["deny_all"]


def test_tampered_egress_file_fails_verification(env):
    hooked(env).gw.engage_panic("L3", None, "michael", "stop")
    doc = json.loads((env.tmp / "egress.json").read_text())
    doc["allow"] = {"agent-02-opportunity": ["evil.example"]}
    assert not verify_sealed(doc)


# ---------------------------------------------------------------- LiteLLM budgets
def test_litellm_generator_per_agent_budgets(env):
    env.policy_edit(lambda d: d["llm_spend"]["per_agent_daily_usd"].__setitem__("agent-03-economics", 5))
    doc = render_litellm_keys(PolicyStore(env.policy_path).current().data, env.panic.read())
    by = {k["metadata"]["agent_id"]: k for k in doc["keys"]}
    assert set(by) == {f"agent-0{i}-{n}" for i, n in [(1, "coordinator"), (2, "opportunity"), (3, "economics"),
                                                       (4, "state"), (5, "governance"), (6, "communications"),
                                                       (7, "marketing")]}
    assert by["agent-03-economics"]["max_budget"] == 5 and by["agent-02-opportunity"]["max_budget"] == 2
    assert all(k["budget_duration"] == "1d" and k["key_alias"] == "mbos-" + a for a, k in by.items())
    assert verify_sealed(doc) and not doc["frozen"]


def test_l3_zeroes_all_budgets_and_release_restores(env):
    hooked(env).gw.engage_panic("L3", None, "michael", "stop")
    doc = json.loads((env.tmp / "litellm.json").read_text())
    assert doc["frozen"] and all(k["max_budget"] == 0 for k in doc["keys"])
    env.gw.release_panic("L3", None, "michael", "all clear")
    doc = json.loads((env.tmp / "litellm.json").read_text())
    assert not doc["frozen"] and all(k["max_budget"] == 2 for k in doc["keys"])
    egress = json.loads((env.tmp / "egress.json").read_text())
    assert not egress["deny_all"] and egress["default"] == "deny"
    last = kill_switch_receipts(env)[-1]
    assert last["intent"].startswith("PANIC side effects applied:") and last["details"]["hooks"]["litellm_budgets"]["ok"]


def test_l1_zeroes_only_that_agent(env):
    hooked(env).gw.engage_panic("L1", "agent-07-marketing", "michael", "misbehaving")
    doc = json.loads((env.tmp / "litellm.json").read_text())
    zero = [k["metadata"]["agent_id"] for k in doc["keys"] if k["max_budget"] == 0]
    assert zero == ["agent-07-marketing"]


def test_release_side_effects_not_applied_if_release_refused(env):
    """Loosening side effects run only after the release committed; a DB-refused release applies none."""
    hooked(env).gw.engage_panic("L3", None, "michael", "stop")
    env.store.dsns["approver"] = env.dsn("gateway")   # a login WITHOUT the approver role
    env.store.close()
    with pytest.raises(Exception, match="approver"):
        env.gw.release_panic("L3", None, "michael", "try")
    assert env.panic.read().globally_frozen
    assert json.loads((env.tmp / "litellm.json").read_text())["frozen"]
    assert json.loads((env.tmp / "egress.json").read_text())["deny_all"]


def test_unreadable_panic_renders_zero_budgets(env):
    env.sql("DELETE FROM mbos.panic_state", replica=True)
    doc = render_litellm_keys(PolicyStore(env.policy_path).current().data, env.panic.read())
    assert doc["frozen"] and all(k["max_budget"] == 0 for k in doc["keys"])


def test_cli_render_commands(env, capsys):
    from mbos_governance.cli import main
    base = ["--dsn", env.dsn("gateway"), "--policy", str(env.policy_path)]
    assert main(base + ["render", "litellm"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "mbos.litellm.keys/1"
    out = env.tmp / "eg.json"
    assert main(base + ["render", "egress", "--out", str(out)]) == 0
    assert verify_sealed(json.loads(out.read_text()))
