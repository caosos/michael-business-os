"""Automatic pickup: states, duplicate suppression, restart recovery, blockers, docs-only guard. Real git remotes in tmp dirs, no network, no model."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

T = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(T))


def load(name):
    spec = importlib.util.spec_from_file_location(name, T / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


import pytest  # noqa: E402

pickup_state, pg, ip = load("pickup_state"), load("pickup_git"), load("inbox_pickup")


def g(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def world(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
    (seed / "docs/messages/acks").mkdir(parents=True)
    (seed / "docs/messages/acks/old.md").write_text("x")
    (seed / "README.md").write_text("r")
    g(seed, "add", "-A"); g(seed, "commit", "-qm", "seed"); g(seed, "branch", "-M", "research/agent-01-coordinator")
    g(seed, "push", "-q", "origin", "research/agent-01-coordinator")
    g(seed, "checkout", "-q", "-b", "liaison/aria-to-agent-01")
    (seed / "docs/messages").mkdir(exist_ok=True)
    (seed / "docs/messages/inbox").mkdir(parents=True)
    (seed / "docs/messages/inbox/ARIA-20250101-0000-old-history.md").write_text("old")
    g(seed, "add", "-A"); g(seed, "commit", "-qm", "inbox"); g(seed, "push", "-q", "origin", "liaison/aria-to-agent-01")
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    monkeypatch.setattr(pg, "ROOT", work)
    monkeypatch.setattr(pg, "SIDE", tmp_path / "side")
    monkeypatch.setattr(ip, "DIR", tmp_path / "pickup")
    monkeypatch.setattr(ip.shutil, "which", lambda n: "/usr/bin/claude")

    def send(mid, body):  # a DISTINCT sender clone publishes to the liaison branch
        sender = tmp_path / ("sender-" + mid)
        subprocess.run(["git", "clone", "-q", "-b", "liaison/aria-to-agent-01", str(origin), str(sender)], check=True, capture_output=True)
        (sender / "docs/messages/inbox" / f"{mid}.md").write_text(body)
        g(sender, "add", "-A"); g(sender, "commit", "-qm", "send " + mid); g(sender, "push", "-q", "origin", "liaison/aria-to-agent-01")

    def remote_files(branch, folder):
        return subprocess.run(["git", "ls-tree", "--name-only", "-r", branch, folder], cwd=origin, capture_output=True, text=True).stdout.split()

    return type("W", (), {"send": staticmethod(send), "origin": origin, "files": staticmethod(remote_files), "dir": tmp_path / "pickup"})


def run_cycle(world, dry=True):
    store = pickup_state.Store(world.dir)
    ip.cycle(store, dry, {}, 60, "t0")
    return store


def test_eligibility_and_pending_rules():
    assert ip.eligible("ARYA-20261010-0900-x") and ip.eligible("ARIA-20261011-0100-x")
    assert not ip.eligible("ARIA-20250101-0000-old") and not ip.eligible("EVIL-20261010-0900-x") and not ip.eligible("2026-10-09-aria-owner-x")
    assert ip.is_ping("Type: PING\nNonce: abc-1\n") == "abc-1" and ip.is_ping("Type: TASK_REQUEST") is None
    inbox = ["ARYA-20261010-0900-a", "ARYA-20261010-0901-b", "ARYA-20261010-0902-c", "ARYA-20261010-0903-d"]
    data = {inbox[0]: {"state": "COMPLETED"}, inbox[1]: {"state": "BLOCKED", "retry_after": 9e9}, inbox[2]: {"state": "BLOCKED", "attempts": 3}}
    assert ip.pending(inbox, set(), data, 1.0) == [inbox[3]]


def test_ping_end_to_end_fetch_deliver_ack_execute_receipt_heartbeat(world):
    mid = "ARYA-20261010-0900-selftest"
    world.send(mid, "# t\nType: PING\nNonce: n-42\n")
    store = run_cycle(world)
    r = store.get(mid)
    assert r["state"] == "COMPLETED" and all(r.get(k) for k in ("fetched_at", "delivered_at", "acked_at", "running_at", "completed_at"))
    assert f"docs/messages/acks/{mid}.md" in world.files("research/agent-01-coordinator", "docs/messages/acks")
    assert f"docs/receipts/pickup/{mid}.md" in world.files("research/agent-01-coordinator", "docs/receipts")
    ack = subprocess.run(["git", "show", f"research/agent-01-coordinator:docs/messages/acks/{mid}.md"], cwd=world.origin, capture_output=True, text=True).stdout
    assert "COMPLETED" in ack and "no human relay" in ack
    assert "PICKUP_HEALTH.json" in world.files("status/agent-01-pickup", ".")
    hb = json.loads((world.dir / "heartbeat.json").read_text())
    assert hb["counts"]["COMPLETED"] == [mid] and hb["session"]["name"] == "mbos-pickup" and hb["blockers"] == []
    rows = [json.loads(x) for x in (world.dir / "receipts.jsonl").read_text().splitlines()]
    assert {x["operation"] for x in rows} >= {"fetched", "executor started", "ack pushed", "execute", "completed"}
    prev = "sha256:" + "0" * 64
    for x in rows:                                    # chain verifies, nothing secret
        assert x["prev_hash"] == prev and x["actor"] == "agent-01-pickup"
        body = {k: v for k, v in x.items() if k != "row_hash"}
        assert pickup_state.sha256_of(body) == x["row_hash"]
        prev = x["row_hash"]


def test_duplicate_suppression_and_restart(world):
    mid = "ARYA-20261010-0901-dup"
    world.send(mid, "Type: PING\nNonce: d\n")
    run_cycle(world)
    head = subprocess.run(["git", "rev-parse", "research/agent-01-coordinator"], cwd=world.origin, capture_output=True, text=True).stdout
    n = len((world.dir / "receipts.jsonl").read_text().splitlines())
    run_cycle(world); run_cycle(world)                # "restart": brand-new Store and cycle each time
    assert subprocess.run(["git", "rev-parse", "research/agent-01-coordinator"], cwd=world.origin, capture_output=True, text=True).stdout == head
    assert [json.loads(x)["operation"] for x in (world.dir / "receipts.jsonl").read_text().splitlines()[n:]].count("executor started") == 0


def test_recovery_of_a_dead_running_executor_retries_once_and_completes(world):
    mid = "ARYA-20261010-0902-crash"
    world.send(mid, "Type: PING\nNonce: c\n")
    store = pickup_state.Store(world.dir)
    store.move(mid, "FETCHED", operation="fetched", attempts=0)
    store.move(mid, "RUNNING", operation="execute", pid=999999, attempts=1)      # a watcher that died mid-run
    ip.recover(store, set(), lambda pid: False)
    assert store.get(mid)["state"] == "BLOCKED" and "died" in store.get(mid)["blocked"]
    store.block(mid, "x", retry_after=0, attempts=1)
    run_cycle(world)
    assert pickup_state.Store(world.dir).get(mid)["state"] == "COMPLETED"


def test_missing_delivery_interface_is_a_specific_visible_blocker_not_success(world, monkeypatch):
    mid = "ARYA-20261010-0903-work"
    world.send(mid, "Type: TASK_REQUEST\nplease reconcile\n")
    monkeypatch.setattr(ip.shutil, "which", lambda n: None)
    store = run_cycle(world)
    assert store.get(mid)["state"] == "BLOCKED" and "claude" in store.get(mid)["blocked"]
    hb = json.loads((world.dir / "heartbeat.json").read_text())
    assert hb["blockers"][0]["id"] == mid and hb["delivery_interface"]["claude_cli"] is False
    assert f"docs/messages/acks/{mid}.md" not in world.files("research/agent-01-coordinator", "docs/messages/acks")


def test_work_executor_may_only_change_docs(world):
    mid = "ARYA-20261010-0904-bad"
    world.send(mid, "Type: TASK_REQUEST\ndo it\n")

    def evil(m, wt, dry):
        (wt / "tools").mkdir(exist_ok=True)
        (wt / "tools/evil.py").write_text("print(1)")
        (wt / "docs").mkdir(exist_ok=True)
        (wt / f"docs/receipts/pickup").mkdir(parents=True, exist_ok=True)
        (wt / f"docs/receipts/pickup/{m}.md").write_text("r")
        return {"ok": True, "process_ok": True}

    store = pickup_state.Store(world.dir)
    ip.pg.fetch()
    assert ip.deliver(mid, store, False, executor=evil) == "BLOCKED"
    assert "non-docs" in store.get(mid)["blocked"]
    assert not any(f.startswith("tools/evil") for f in world.files("research/agent-01-coordinator", "tools"))


def test_work_executor_success_completes_and_unauthorized_sender_is_ignored(world):
    mid = "ARYA-20261010-0905-good"
    world.send(mid, "Type: TASK_REQUEST\nreconcile queue\n")
    world.send("EVIL-20261010-0906-x", "Type: PING\nNonce: z\n")

    def good(m, wt, dry):
        (wt / "docs/receipts/pickup").mkdir(parents=True, exist_ok=True)
        (wt / f"docs/receipts/pickup/{m}.md").write_text("did the work")
        return {"ok": True, "process_ok": True}

    store = pickup_state.Store(world.dir)
    ip.pg.fetch()
    assert ip.deliver(mid, store, False, executor=good) == "COMPLETED"
    run_cycle(world)
    assert store.get("EVIL-20261010-0906-x") == {}
