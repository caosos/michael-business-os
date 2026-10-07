"""E-14: spine_adapter helpers that make Agent 01's A-18 a wiring change."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "vendor/agent01_mbos"))
from mbos_governance import spine_adapter as sa  # noqa: E402
from mbos_governance.gateway import GatewayRefused  # noqa: E402

from .test_e03_hooks import FakeDBOS, FakeWF  # noqa: E402
from .test_e05_reconcile import crash_after_effector, crash_before_effector  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def gov(env):
    dbos = FakeDBOS([FakeWF("w1", "ENQUEUED"), FakeWF("w2", "PENDING")])
    g = sa.build(env.dsns, str(env.policy_path), dbos=dbos, egress_file=str(env.tmp / "egress.json"),
                 litellm_file=str(env.tmp / "litellm.json"), clock=env.clock, journal_path=env.tmp / "j.jsonl")
    g.dbos = dbos
    return g


def test_build_wires_the_three_hooks(env, gov):
    assert [h.name for h in gov.action_gateway.panic_hooks] == ["dbos_cancel", "egress_policy", "litellm_budgets"]
    bare = sa.build(env.dsns, str(env.policy_path), egress_file=None, litellm_file=None)
    assert bare.action_gateway.panic_hooks == []
    only = sa.build(env.dsns, str(env.policy_path), panic_hooks=[])
    assert only.action_gateway.panic_hooks == []


def test_engage_l3_runs_every_hook_and_is_json(env, gov):
    out = sa.engage_panic(gov, "L3", None, "michael", "incident")
    json.dumps(out)
    assert set(out["hooks"]) == {"dbos_cancel", "egress_policy", "litellm_budgets"} and all(h["ok"] for h in out["hooks"].values())
    assert out["hooks"]["dbos_cancel"]["cancelled"] == ["w1"] and out["hooks"]["dbos_cancel"]["in_flight_at_freeze"] == ["w2"]
    assert json.loads((env.tmp / "egress.json").read_text())["deny_all"] is True
    assert all(k["max_budget"] == 0 for k in json.loads((env.tmp / "litellm.json").read_text())["keys"])
    assert sa.panic_state(gov)["global"] == "FROZEN"
    assert any(r["type"] == "KILL_SWITCH_CHANGED" and r.get("details", {}).get("hooks") for r in env.store.receipts())


def test_engage_l1_l2_do_not_cancel_workflows(env, gov):
    out = sa.engage_panic(gov, "L2", "money.*", "agent-01-coordinator", "spend anomaly")
    assert gov.dbos.cancel_calls == [] and out["hooks"]["litellm_budgets"]["ok"]
    out = sa.engage_panic(gov, "L1", "agent-07-marketing", "michael", "misbehaving")
    assert gov.dbos.cancel_calls == [] and "agent-07-marketing" in sa.panic_state(gov)["frozen_agents"]


def test_release_runs_as_approver_and_loosens_after_commit(env, gov):
    sa.engage_panic(gov, "L3", None, "michael", "incident")
    out = sa.release_panic(gov, "L3", None, "michael", "all clear")
    json.dumps(out)
    assert sa.panic_state(gov)["global"] == "RUNNING"
    assert json.loads((env.tmp / "egress.json").read_text())["deny_all"] is False
    assert all(k["max_budget"] == 2 for k in json.loads((env.tmp / "litellm.json").read_text())["keys"])
    assert env.sql("SELECT actor->>'id' FROM mbos.receipts WHERE type='KILL_SWITCH_CHANGED' AND intent LIKE 'PANIC L3 release%%' "
                   "ORDER BY seq DESC LIMIT 1")[0][0] == "michael"


def test_release_refusals_leave_everything_frozen(env, gov):
    sa.engage_panic(gov, "L3", None, "michael", "incident")
    with pytest.raises(GatewayRefused):                              # not a policy approver
        sa.release_panic(gov, "L3", None, "agent-01-coordinator", "self-release")
    with pytest.raises(GatewayRefused):                              # blank reason
        sa.release_panic(gov, "L3", None, "michael", "  ")
    no_approver = dict(env.dsns, approver=env.dsns["gateway"])       # a login WITHOUT the approver role
    g2 = sa.build(no_approver, str(env.policy_path), egress_file=None, litellm_file=None)
    with pytest.raises(Exception, match="approver"):
        sa.release_panic(g2, "L3", None, "michael", "try")
    assert sa.panic_state(gov)["global"] == "FROZEN"
    assert json.loads((env.tmp / "egress.json").read_text())["deny_all"] is True


def test_engage_with_database_down_returns_error_not_exception(env, gov, tmp_path):
    bad = {r: d.replace("dbname=", "dbname=gone_") for r, d in env.dsns.items()}
    g = sa.build(bad, str(env.policy_path), egress_file=None, litellm_file=None, journal_path=tmp_path / "j.jsonl")
    out = sa.engage_panic(g, "L3", None, "michael", "db is down")
    assert out["error"] and sa.panic_state(g)["readable"] is False and sa.panic_state(g)["global"] == "FROZEN"


def test_reconcile_function_still_available(env, gov, monkeypatch):
    ar = crash_after_effector(env, monkeypatch, "email")
    out = sa.reconcile(gov.action_gateway, older_than_seconds=0)
    assert out[0]["action_request_id"] == ar["action_request_id"] and out[0]["outcome"] == "executed"


def test_schedule_reconcile_registers_a_real_dbos_scheduled_workflow(env, monkeypatch, tmp_path):
    """Real DBOS 3.2 (local SQLite system DB) in a subprocess: the scheduled workflow settles a crashed claim."""
    ar = crash_before_effector(env, monkeypatch, "email")
    script = textwrap.dedent(f"""
        import json, shutil, sys, time
        sys.path.insert(0, {str(REPO / "src")!r}); sys.path.insert(0, {str(REPO / "tests/vendor/agent01_mbos")!r})
        from pathlib import Path
        from dbos import DBOS
        from mbos_governance import spine_adapter as sa
        tmp = Path({str(tmp_path)!r}) / "dbos"; tmp.mkdir()
        for f in ("policy.v1.json", "policy.schema.json", "content_rules.v1.json"):
            shutil.copy({str(env.policy_path.parent)!r} + "/" + f, tmp / f)
        DBOS(config={{"name": "mbos-e14", "system_database_url": "sqlite:///" + str(tmp / "dbos.sqlite")}})
        gov = sa.build(json.loads({json.dumps(env.dsns)!r}), str(tmp / "policy.v1.json"), dbos=DBOS,
                       egress_file=str(tmp / "e.json"), litellm_file=str(tmp / "l.json"),
                       journal_path=tmp / "j.jsonl")
        sched = sa.schedule_reconcile(gov, DBOS, crontab="* * * * * *", name="mbos_reconcile_claims", older_than_seconds=0)
        DBOS.launch()
        first = sched.activate(); second = sched.activate()
        deadline = time.time() + 30
        done = None
        import psycopg
        while time.time() < deadline:
            with psycopg.connect({env.dsn("reader")!r}) as c:
                done = c.execute("SELECT status FROM mbos.action_requests WHERE action_request_id=%s", ({ar["action_request_id"]!r},)).fetchone()[0]
            if done != "executing":
                break
            time.sleep(0.5)
        wfs = [w.name for w in DBOS.list_workflows()]
        DBOS.destroy()
        print(json.dumps({{"status": done, "workflows": sorted(set(wfs)), "activate": [first, second]}}))
    """)
    p = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120, cwd=tmp_path)
    assert p.returncode == 0, p.stderr[-2500:]
    res = json.loads(p.stdout.strip().splitlines()[-1])
    assert res["activate"] == ["created", "unchanged"]                                       # idempotent activation
    assert res["status"] == "failed" and "mbos_reconcile_claims" in res["workflows"]      # crash before send -> failed, no resend
    assert env.sql("SELECT state FROM mbos.effector_calls WHERE action_request_id=%s", (ar["action_request_id"],))[0][0] == "failed"


def test_l3_cancel_never_touches_the_reconcile_workflow(env):
    class NamedWF(FakeWF):
        def __init__(self, wid, status, name):
            super().__init__(wid, status)
            self.name = name
    dbos = FakeDBOS([NamedWF("r1", "ENQUEUED", "mbos_reconcile_claims"), NamedWF("w1", "ENQUEUED", "item_lifecycle"),
                     NamedWF("w2", "DELAYED", "item_lifecycle")])
    g = sa.build(env.dsns, str(env.policy_path), dbos=dbos, egress_file=None, litellm_file=None, clock=env.clock,
                 journal_path=env.tmp / "j.jsonl")

    g.action_gateway.panic_hooks[0].protect.add("mbos_reconcile_claims")   # what schedule_reconcile does
    out = sa.engage_panic(g, "L3", None, "michael", "incident")
    assert out["hooks"]["dbos_cancel"]["cancelled"] == ["w1", "w2"] and dbos.wfs["r1"].status == "ENQUEUED"
