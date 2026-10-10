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

pickup_state, pg, ph, ip = load("pickup_state"), load("pickup_git"), load("pickup_health"), load("inbox_pickup")


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
    import pause as _pz
    monkeypatch.setattr(_pz, "FLAG", tmp_path / "NO_PAUSE_FLAG")        # tests never see the real owner pause flag
    monkeypatch.setattr(ip, "run_work", lambda *a: (_ for _ in ()).throw(AssertionError("test reached the REAL claude executor")))

    def send(mid, body):  # a DISTINCT sender clone publishes to the liaison branch
        sender = tmp_path / ("sender-" + mid)
        subprocess.run(["git", "clone", "-q", "-b", "liaison/aria-to-agent-01", str(origin), str(sender)], check=True, capture_output=True)
        (sender / "docs/messages/inbox" / f"{mid}.md").write_text(body)
        g(sender, "add", "-A"); g(sender, "commit", "-qm", "send " + mid); g(sender, "push", "-q", "origin", "liaison/aria-to-agent-01")

    def remote_files(branch, folder):
        return subprocess.run(["git", "ls-tree", "--name-only", "-r", branch, folder], cwd=origin, capture_output=True, text=True).stdout.split()

    def set_exec(fn):
        monkeypatch.setattr(ip, "run_work", fn)

    return type("W", (), {"set_exec": staticmethod(set_exec), "send": staticmethod(send), "origin": origin, "files": staticmethod(remote_files), "dir": tmp_path / "pickup"})


def run_cycle(world, dry=True):
    store = pickup_state.Store(world.dir)
    ip.cycle(store, dry, ph.Beat(store, world.dir, 60, "t0"))
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
        a = wt / f"docs/messages/acks/{m}.md"
        a.write_text(a.read_text().replace("**Stage:** ACKED", "**Stage:** COMPLETED"))
        return {"ok": True, "process_ok": True}

    store = pickup_state.Store(world.dir)
    ip.pg.fetch()
    assert ip.deliver(mid, store, False, executor=good) == "COMPLETED"
    run_cycle(world)
    assert store.get("EVIL-20261010-0906-x") == {}


def test_message_acked_by_someone_else_is_recorded_not_executed(world):
    mid = "ARYA-20261010-0907-handled"
    world.send(mid, "Type: TASK_REQUEST\nhandled by hand\n")
    sender = world.dir.parent / "hand"                # a human/agent pushes the ack on the coordinator branch first
    subprocess.run(["git", "clone", "-q", "-b", "research/agent-01-coordinator", str(world.origin), str(sender)], check=True, capture_output=True)
    (sender / "docs/messages/acks" / f"{mid}.md").write_text("# manual ack")
    g(sender, "add", "-A"); g(sender, "commit", "-qm", "manual ack"); g(sender, "push", "-q", "origin", "research/agent-01-coordinator")
    calls = []
    world.set_exec(lambda *a: calls.append(a) or {"ok": True, "process_ok": True})
    store = run_cycle(world, dry=False)
    r = store.get(mid)
    assert r["state"] == "COMPLETED" and r["completed_at"] and not r.get("delivered_at") and calls == []
    run_cycle(world, dry=False)
    assert calls == []


def _hb(world):
    return json.loads((world.dir / "heartbeat.json").read_text())


def test_executor_that_leaves_the_ack_blocked_is_blocked_not_completed(world):          # A-52(d): the 0433 bug
    mid = "ARYA-20261010-0908-blockedack"
    world.send(mid, "Type: TASK_REQUEST\nneeds the interactive coordinator\n")

    def blocked(m, wt, dry):
        (wt / "docs/receipts/pickup").mkdir(parents=True, exist_ok=True)
        (wt / f"docs/receipts/pickup/{m}.md").write_text("could not do it")
        a = wt / f"docs/messages/acks/{m}.md"
        a.write_text(a.read_text().replace("**Stage:** ACKED", "**Stage:** BLOCKED: queue row needs an interactive edit").split("(received")[0] + "\n")
        return {"ok": True, "process_ok": True}

    world.set_exec(blocked)
    store = run_cycle(world, dry=False)
    r = store.get(mid)
    assert r["state"] == "BLOCKED" and "interactive edit" in r["blocked"] and r["needs"]
    assert _hb(world)["counts"].get("COMPLETED", []).count(mid) == 0 and _hb(world)["blockers"][0]["id"] == mid
    run_cycle(world, dry=False)
    assert pickup_state.Store(world.dir).get(mid)["attempts"] == 1          # a blocked-by-executor message is not replayed


def test_heartbeat_shows_the_task_during_delivery_and_clears_it_only_after(world):        # A-52(a)(b)
    mid = "ARYA-20261010-0909-live"
    world.send(mid, "Type: TASK_REQUEST\nlong job\n")
    seen = {}

    def slow(m, wt, dry):
        hb = _hb(world)
        seen["during_file"] = hb["currently_running"], hb["session"]["status"]
        pub = subprocess.run(["git", "show", "status/agent-01-pickup:PICKUP_HEALTH.json"], cwd=world.origin, capture_output=True, text=True).stdout
        seen["during_remote"] = json.loads(pub)["currently_running"]
        (wt / "docs/receipts/pickup").mkdir(parents=True, exist_ok=True)
        (wt / f"docs/receipts/pickup/{m}.md").write_text("done")
        a = wt / f"docs/messages/acks/{m}.md"
        a.write_text(a.read_text().replace("ACKED (received", "COMPLETED (received"))
        return {"ok": True, "process_ok": True}

    world.set_exec(slow)
    run_cycle(world, dry=False)
    assert seen["during_file"][0]["id"] == mid and seen["during_file"][0]["started_at"] and seen["during_file"][1] == "busy"
    assert seen["during_remote"]["id"] == mid
    after = _hb(world)
    assert after["currently_running"] is None and after["session"]["status"] == "idle" and after["counts"]["COMPLETED"] == [mid]


def test_stale_or_null_reading_is_unknown_with_age_never_idle():                          # A-52(c)
    from datetime import datetime, timedelta, timezone
    t = datetime(2026, 10, 10, 5, 0, tzinfo=timezone.utc)
    fresh = {"session": {"status": "idle", "observed_at": "2026-10-10T04:59:30Z", "ttl_sec": 300}}
    stale = {"session": {"status": "idle", "observed_at": "2026-10-10T04:30:16Z", "ttl_sec": 300}}
    assert ph.session_status(fresh, t) == {"status": "idle", "age_s": 30}
    s = ph.session_status(stale, t)
    assert s["status"] == "UNKNOWN" and s["age_s"] > 1700 and s["reason"] == "stale reading"
    assert ph.session_status({"session": {"status": None, "observed_at": "2026-10-10T04:59:59Z"}}, t)["status"] == "UNKNOWN"
    assert ph.session_status({}, t)["status"] == "UNKNOWN"
    assert ph.TTL_IDLE >= 2 * ph.IDLE_PUBLISH_S and ph.TTL_BUSY >= 2 * ph.BUSY_PUBLISH_S


def test_docs_guard_ignores_code_pushed_by_others_after_the_run_started(world, tmp_path):
    mid = "ARYA-20261010-0910-moved"
    world.send(mid, "Type: TASK_REQUEST\nwork\n")

    def good_while_origin_moves(m, wt, dry):
        other = tmp_path / "other"                      # someone pushes CODE to the coordinator branch while the executor runs
        subprocess.run(["git", "clone", "-q", "-b", "research/agent-01-coordinator", str(world.origin), str(other)], check=True, capture_output=True)
        (other / "tools").mkdir(exist_ok=True)
        (other / "tools/new_code.py").write_text("x = 1")
        g(other, "add", "-A"); g(other, "commit", "-qm", "code"); g(other, "push", "-q", "origin", "research/agent-01-coordinator")
        ip.pg.fetch()
        (wt / "docs/receipts/pickup").mkdir(parents=True, exist_ok=True)
        (wt / f"docs/receipts/pickup/{m}.md").write_text("done")
        a = wt / f"docs/messages/acks/{m}.md"
        a.write_text(a.read_text().replace("**Stage:** ACKED", "**Stage:** COMPLETED"))
        return {"ok": True, "process_ok": True}

    store = pickup_state.Store(world.dir)
    ip.pg.fetch()
    r = ip.deliver(mid, store, False, executor=good_while_origin_moves)
    assert r == "COMPLETED", store.get(mid).get("blocked")
    assert "tools/new_code.py" in world.files("research/agent-01-coordinator", "tools")        # their code survived the rebase and our docs landed


# ---- owner pause (ARYA-0528): no model work may start while var/PAUSED_BY_OWNER exists ----
def test_pause_blocks_work_executor_but_ping_still_answers(world, monkeypatch, tmp_path):
    import pause as pz
    monkeypatch.setattr(pz, "FLAG", tmp_path / "PAUSED_BY_OWNER")
    pz.FLAG.write_text("owner pause test")
    called = []
    world.set_exec(lambda *a: called.append(a) or {"ok": True, "process_ok": True})
    work, ping = "ARYA-20261010-0911-work", "ARYA-20261010-0912-ping"
    world.send(work, "Type: TASK_REQUEST\ndo model work\n")
    world.send(ping, "Type: PING\nNonce: p\n")
    store = run_cycle(world, dry=False)
    assert called == [] and store.get(work)["state"] == "BLOCKED" and "PAUSED_BY_OWNER" in store.get(work)["blocked"]
    assert store.get(work).get("attempts", 0) == 0 and store.get(ping)["state"] == "COMPLETED"        # acknowledged, not executed; ping unaffected
    pz.FLAG.unlink()                                                                                   # resume: the hourly retry runs it
    st = pickup_state.Store(world.dir)
    st.block(work, "x", retry_after=0, attempts=0)
    run_cycle(world, dry=False)
    assert len(called) == 1


def test_pause_stops_dispatcher_and_worker_launcher(monkeypatch, tmp_path):
    import pause as pz
    monkeypatch.setattr(pz, "FLAG", tmp_path / "PAUSED_BY_OWNER")
    pz.FLAG.write_text("owner pause test")
    disp, wk = load("dispatcher"), load("worker")
    monkeypatch.setattr(disp, "LOG", tmp_path / "d.jsonl")
    assert disp.main(["--once"]) == 0 and "paused" in (tmp_path / "d.jsonl").read_text()
    out = wk.run_one("F-99", "06", wk.router.TaskProfile(task_id="F-99", lane="06", kind="implement", risk="low", cross_lane=False, long_horizon=False),
                     worktree=tmp_path, dry=False, model=None, queue_text="| F-99 | P0 | t | none | READY | 06 | x |")
    assert out["ok"] is False and "PAUSED_BY_OWNER" in out["error"]


def test_a_pause_citing_a_cancelled_instruction_is_ignored_and_never_reexecuted(world, monkeypatch, tmp_path):
    import pause as pz
    flag, ledger = tmp_path / "PAUSED_BY_OWNER", tmp_path / "SUPERSEDED.json"
    ledger.write_text(json.dumps({"_note": "x", "ARYA-20261010-0528-owner-pause-compute": {"superseded_by": "ARYA-20261010-0530-owner-resume"}}))
    monkeypatch.setattr(pz, "FLAG", flag); monkeypatch.setattr(pz, "SUPERSEDED", ledger)
    flag.write_text("PAUSED_BY_OWNER (owner via ARYA-20261010-0528-owner-pause-compute)")
    assert pz.reason() is None                                                # stale flag: ignored
    flag.write_text("PAUSED_BY_OWNER (owner via ARYA-20261010-0600-new-pause)")
    assert "0600" in pz.reason()                                              # a genuinely new pause still works
    assert not ip.eligible("ARYA-20261010-0528-owner-pause-compute") and ip.eligible("ARYA-20261010-0600-new-pause")


def test_same_line_docs_conflict_with_the_coordinator_resolves_for_upstream_and_publishes(world, tmp_path):
    mid = "ARYA-20261010-0913-conflict"
    world.send(mid, "Type: TASK_REQUEST\nedit the same queue row\n")

    def edits_same_row(m, wt, dry):
        other = tmp_path / "coord"                       # the coordinator edits the SAME line of a docs file and pushes first
        subprocess.run(["git", "clone", "-q", "-b", "research/agent-01-coordinator", str(world.origin), str(other)], check=True, capture_output=True)
        (other / "docs/QUEUE.md").write_text("| F-1 | status DONE by coordinator |\n")
        g(other, "add", "-A"); g(other, "commit", "-qm", "coord edit"); g(other, "push", "-q", "origin", "research/agent-01-coordinator")
        ip.pg.fetch()
        (wt / "docs/QUEUE.md").write_text("| F-1 | status DONE by executor |\n")                 # conflicting edit of the same line
        (wt / "docs/receipts/pickup").mkdir(parents=True, exist_ok=True)
        (wt / f"docs/receipts/pickup/{m}.md").write_text("r")
        a = wt / f"docs/messages/acks/{m}.md"
        a.write_text(a.read_text().replace("**Stage:** ACKED", "**Stage:** COMPLETED"))
        return {"ok": True, "process_ok": True}

    seed = tmp_path / "seedq"
    subprocess.run(["git", "clone", "-q", "-b", "research/agent-01-coordinator", str(world.origin), str(seed)], check=True, capture_output=True)
    (seed / "docs/QUEUE.md").write_text("| F-1 | status READY |\n")
    g(seed, "add", "-A"); g(seed, "commit", "-qm", "queue"); g(seed, "push", "-q", "origin", "research/agent-01-coordinator")
    store = pickup_state.Store(world.dir)
    ip.pg.fetch()
    assert ip.deliver(mid, store, False, executor=edits_same_row) == "COMPLETED"
    q = subprocess.run(["git", "show", "research/agent-01-coordinator:docs/QUEUE.md"], cwd=world.origin, capture_output=True, text=True).stdout
    assert "DONE by coordinator" in q and "DONE by executor" not in q                              # upstream wins the contested line
    assert f"docs/receipts/pickup/{mid}.md" in world.files("research/agent-01-coordinator", "docs/receipts")      # executor's own files still land


def test_publish_is_refused_when_the_executor_would_reopen_a_done_queue_row(world, tmp_path):
    """A-57: an executor result that moves a DONE row back to READY or drops a row is never pushed (the 9435d68 failure mode)."""
    mid = "ARYA-20261010-2001-queue-regress"
    world.send(mid, "Type: TASK_REQUEST\nedit the queue\n")
    hdr = "| ID | Pri | Task | Deps | Status | Agent | Acceptance |\n"
    seed = tmp_path / "seedg"
    subprocess.run(["git", "clone", "-q", "-b", "research/agent-01-coordinator", str(world.origin), str(seed)], check=True, capture_output=True)
    (seed / "docs/status").mkdir(parents=True, exist_ok=True)
    (seed / "docs/status/READY_QUEUE.md").write_text(hdr + "| F-60 | P0 | t | none | DONE | 06 | p |\n| F-61 | P0 | t | F-60 | READY | 06 | p |\n")
    g(seed, "add", "-A"); g(seed, "commit", "-qm", "queue"); g(seed, "push", "-q", "origin", "research/agent-01-coordinator")
    before = subprocess.run(["git", "rev-parse", "research/agent-01-coordinator"], cwd=world.origin, capture_output=True, text=True).stdout

    def reverts(m, wt, dry):
        (wt / "docs/status/READY_QUEUE.md").write_text(hdr + "| F-60 | P0 | t | none | READY | 06 | p |\n")      # F-60 reopened, F-61 dropped
        (wt / "docs/receipts/pickup").mkdir(parents=True, exist_ok=True)
        (wt / f"docs/receipts/pickup/{m}.md").write_text("r")
        return {"ok": True, "process_ok": True}

    store = pickup_state.Store(world.dir)
    ip.pg.fetch()
    assert ip.deliver(mid, store, False, executor=reverts) != "COMPLETED"
    after = subprocess.run(["git", "show", "research/agent-01-coordinator:docs/status/READY_QUEUE.md"], cwd=world.origin, capture_output=True, text=True).stdout
    assert "F-60 | P0 | t | none | DONE" in after and "F-61" in after            # origin queue untouched


def _seed_queue(world, tmp_path, text, name):
    seed = tmp_path / name
    subprocess.run(["git", "clone", "-q", "-b", "research/agent-01-coordinator", str(world.origin), str(seed)], check=True, capture_output=True)
    (seed / "docs/status").mkdir(parents=True, exist_ok=True)
    (seed / "docs/status/READY_QUEUE.md").write_text(text)
    g(seed, "add", "-A"); g(seed, "commit", "-qm", "queue"); g(seed, "push", "-q", "origin", "research/agent-01-coordinator")


QHDR = "| ID | Pri | Task | Deps | Status | Agent | Acceptance |\n"


def _publish_with(world, tmp_path, mid, mutate):
    world.send(mid, "Type: TASK_REQUEST\nx\n")

    def ex(m, wt, dry):
        mutate(wt)
        (wt / "docs/receipts/pickup").mkdir(parents=True, exist_ok=True)
        (wt / f"docs/receipts/pickup/{m}.md").write_text("r")
        return {"ok": True, "process_ok": True}

    ip.pg.fetch()
    out = ip.deliver(mid, pickup_state.Store(world.dir), False, executor=ex)
    return out, subprocess.run(["git", "show", "research/agent-01-coordinator:docs/status/READY_QUEUE.md"], cwd=world.origin, capture_output=True, text=True).stdout


def test_a59_emptied_or_deleted_established_queue_is_not_published(world, tmp_path):
    _seed_queue(world, tmp_path, QHDR + "| F-60 | P0 | t | none | DONE | 06 | p |\n", "s1")
    out, after = _publish_with(world, tmp_path, "ARYA-20261010-2201-empty", lambda wt: (wt / "docs/status/READY_QUEUE.md").write_text(""))
    assert out != "COMPLETED" and "F-60" in after
    out, after = _publish_with(world, tmp_path, "ARYA-20261010-2202-deleted", lambda wt: (wt / "docs/status/READY_QUEUE.md").unlink())
    assert out != "COMPLETED" and "F-60" in after


def test_a59_unreadable_origin_queue_refuses_and_absent_baseline_allows(world, tmp_path, monkeypatch):
    wt, why = ip.pg.prepare_side()
    assert wt, why
    assert ip.pg.queue_problems(wt) == []                      # no queue upstream yet: initial baseline is allowed
    real = ip.pg.git

    def broken(*a, **k):
        if a[:1] == ("ls-tree",):
            return subprocess.CompletedProcess(a, 128, "", "fatal: simulated read failure")
        return real(*a, **k)

    monkeypatch.setattr(ip.pg, "git", broken)
    assert any("cannot read" in p for p in ip.pg.queue_problems(wt))
