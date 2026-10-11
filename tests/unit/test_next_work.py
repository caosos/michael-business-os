import importlib.util
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


nw, es = load("next_work"), load("engineering_session")

Q = ("| ID | Pri | Task | Deps | Status | Agent | Acceptance |\n"
     "| A-1 | P1 | mine ready | none | READY | 01 engineering | x |\n"
     "| A-2 | P1 | needs a1 | A-1 | READY | 01 | x |\n"
     "| A-3 | P1 | other lane | none | READY | 06 | x |\n"
     "| A-4 | P1 | mine done | none | DONE | 01 | x |\n"
     "| A-5 | P2 | side | none | READY | worker:side-worktree | x |\n")
WAIT = "ACKED (received by automatic pickup; AWAITING the interactive engineering session, which pickup does not replace; NOT completed)"


import re


def ids(lines):
    return [m.group(1) for l in lines for m in [re.search(r"\b(A-\d+)\b", l)] if m]


def step(inbox, q, seen, eng, now):
    return nw.new_items(inbox, q, seen, eng, now, retry_s=600)


def test_first_notification_unhandled_then_a_bounded_retry_then_quiet_until_the_next_interval():
    lines, seen = step({"ARYA-20261010-2001-m1": WAIT}, Q, {}, {}, 1000)
    assert "NEW INSTRUCTION ARYA-20261010-2001-m1" in lines and ids(lines) == ["A-1", "A-5"] and len(lines) == 3
    assert step({"ARYA-20261010-2001-m1": WAIT}, Q, seen, {}, 1300)[0] == []                       # inside the interval: nothing
    again, seen = step({"ARYA-20261010-2001-m1": WAIT}, Q, seen, {}, 1700)                          # notification was missed: bounded retry
    assert len(again) == 3 and all(l.startswith("REMINDER #2") for l in again)
    assert step({"ARYA-20261010-2001-m1": WAIT}, Q, seen, {}, 1800)[0] == []
    third, _ = step({"ARYA-20261010-2001-m1": WAIT}, Q, seen, {}, 2400)
    assert third[0].startswith("REMINDER #3")


def test_an_active_claim_suppresses_announcements_and_done_stops_retries_for_good():
    _, seen = step({"ARYA-20261010-2001-m1": WAIT}, Q, {}, {}, 1000)
    claim = {"ARYA-20261010-2001-m1": {"state": "STARTED"}, "A-1": {"state": "STARTED"}}
    lines, seen = step({"ARYA-20261010-2001-m1": WAIT}, Q, seen, claim, 9999)
    assert ids(lines) == ["A-5"]                              # claimed items are silent, the unclaimed A-5 is still reminded
    done = {"ARYA-20261010-2001-m1": {"state": "DONE"}, "A-1": {"state": "DONE"}, "A-5": {"state": "DONE"}}
    assert step({"ARYA-20261010-2001-m1": WAIT}, Q, seen, done, 99999)[0] == []


def test_completed_pickup_acks_and_other_lanes_are_never_announced_and_ineligible_items_are_forgotten():
    lines, seen = step({"ARYA-20261010-2004-old": "COMPLETED (done)", "ARYA-20261010-2003-noack": None}, Q, {}, {}, 0)
    assert "NEW INSTRUCTION ARYA-20261010-2003-noack" in lines and not any("ARYA-20261010-2004-old" in l for l in lines)
    _, seen = step({"ARYA-20261010-2003-noack": None}, Q.replace("| A-1 | P1 | mine ready | none | READY", "| A-1 | P1 | mine ready | none | DONE"), seen, {}, 10)
    assert "A-1" not in seen
    back, _ = step({"ARYA-20261010-2003-noack": None}, Q, seen, {}, 20)                              # READY again after leaving READY: announced as new
    assert any(l.startswith("NEW READY ROW A-1") for l in back)


def test_completion_makes_the_next_item_actionable_once_and_reentry_recovers_pending_work(tmp_path, monkeypatch):
    monkeypatch.setattr(es, "STATE", tmp_path / "eng.json")
    monkeypatch.setattr(es, "RECEIPTS", tmp_path / "rc")
    monkeypatch.setattr(nw, "STATE", tmp_path / "seen.json")
    _, seen = step({}, Q, {}, {}, 0)
    nw.write_state(seen)
    assert step({}, Q, nw.read_state(), {}, 100)[0] == []                         # A-1/A-5 were announced and are quiet until the interval
    es.begin("A-1", {"pid": 1})
    out = es.finish("A-1", Q.replace("| A-1 | P1 | mine ready | none | READY", "| A-1 | P1 | mine ready | none | DONE"), "done")
    assert out["next"]["id"] == "A-2"
    after, seen2 = step({}, Q.replace("| A-1 | P1 | mine ready | none | READY", "| A-1 | P1 | mine ready | none | DONE"), nw.read_state(), es.load(), 101)
    assert ids([l for l in after if l.startswith("NEW")]) == ["A-2"]       # announced at once on completion, not after the interval
    nw.write_state(seen2)
    assert step({}, Q.replace("| A-1 | P1 | mine ready | none | READY", "| A-1 | P1 | mine ready | none | DONE"), nw.read_state(), es.load(), 102)[0] == []   # and only once
    # re-entry: a fresh process (empty in-memory state) reads the persisted state and re-announces the still-unclaimed item after the interval
    again, _ = step({}, Q.replace("| A-1 | P1 | mine ready | none | READY", "| A-1 | P1 | mine ready | none | DONE"), nw.read_state(), es.load(), 101 + 700)
    assert any(l.startswith("REMINDER") and "A-2" in l for l in again)


def test_the_earlier_one_shot_state_format_is_discarded_and_a_baseline_closes_history(tmp_path, monkeypatch):
    monkeypatch.setattr(nw, "STATE", tmp_path / "seen.json")
    nw.STATE.write_text('{"inbox": ["x"], "rows": ["A-1"]}')
    assert nw.read_state() == {}
    lines, _ = step({"ARYA-20261010-2004-old": WAIT}, Q, {"ARYA-20261010-2004-old": {"first": 0, "last": 0, "count": 0, "closed": True}}, {}, 99999)
    assert not any("ARYA-20261010-2004-old" in l for l in lines)


def test_history_ids_before_the_pickup_cutoff_or_oddly_named_are_never_announced():
    inbox = {"2026-10-09-aria-owner-x": None, "ARIA-20261009-2100-old": None, "ARYA-20261010-2301-new": None}
    lines, seen = step(inbox, Q, {}, {}, 0)
    assert [l for l in lines if "INSTRUCTION" in l] == ["NEW INSTRUCTION ARYA-20261010-2301-new"]
    assert "ARIA-20261009-2100-old" not in seen


# ---------------------------------------------------------------- A-68: five-minute handoff (fake clock, synthetic)
def test_sla_boundary_299_silent_300_reminds_and_the_first_announcement_is_immediate():
    first, seen = step({}, Q, {}, {}, 1000)
    assert any(l.startswith("NEW") for l in first)                         # eligible at t0: announced in the same cycle
    assert nw.RETRY_S == 300 and nw.SLA_S == 300 and nw.POLL_MAX_S < nw.SLA_S
    assert nw.new_items({}, Q, seen, {}, 1000 + 299, retry_s=nw.RETRY_S)[0] == []                      # 299 s: still quiet
    at300, seen2 = nw.new_items({}, Q, seen, {}, 1000 + 300, retry_s=nw.RETRY_S)
    assert at300 and all("SLA 300s exceeded" in l for l in at300)                                      # 300 s: bounded retry, flagged
    assert nw.new_items({}, Q, seen2, {}, 1000 + 301, retry_s=nw.RETRY_S)[0] == []                     # once per interval, not every cycle


def test_suppression_pause_quota_claim_done_and_unmet_dependency_never_announce(tmp_path, monkeypatch):
    monkeypatch.setattr(nw, "STATE", tmp_path / "seen.json")
    monkeypatch.setattr(nw, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(nw, "current", lambda: ({}, Q))
    monkeypatch.setattr(nw, "engineering_state", lambda: {})
    assert nw.cycle(now=10, blocked="owner pause: x") == [] and nw.read_state() == {}                  # paused: no announcement and no timer started
    assert nw.cycle(now=20, blocked="quota guard: over") == [] and nw.read_state() == {}
    monkeypatch.setattr(nw, "blocked_reason", lambda: None)
    lines = nw.cycle(now=30)
    assert ids(lines) == ["A-1", "A-5"]                                                                 # A-2 has an unmet dependency; A-3 other lane; A-4 DONE
    claimed = {"A-1": {"state": "STARTED"}, "A-5": {"state": "DONE"}}
    monkeypatch.setattr(nw, "engineering_state", lambda: claimed)
    assert nw.cycle(now=30 + 301) == []                                                                 # claimed / DONE: silent even after the interval


def test_restart_recovery_and_the_latency_log_prove_the_handoff_time(tmp_path, monkeypatch):
    monkeypatch.setattr(nw, "STATE", tmp_path / "seen.json")
    monkeypatch.setattr(nw, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(nw, "current", lambda: ({}, Q))
    monkeypatch.setattr(nw, "engineering_state", lambda: {})
    monkeypatch.setattr(nw, "blocked_reason", lambda: None)
    nw.cycle(now=100)                                                                                  # announced at once (latency 0)
    assert nw.cycle(now=160) == []                                                                      # a restarted process re-reads the persisted state: no duplicate
    again = nw.cycle(now=100 + 300)
    assert again and all(l.startswith("REMINDER") for l in again)                                      # still unclaimed after a restart: re-announced at 300 s
    import json
    rows = [json.loads(x) for x in nw.LOG.read_text().splitlines()]
    assert [r["kind"] for r in rows[:2]] == ["NEW", "NEW"] and rows[0]["since_first_seen_s"] == 0 and all(r["within_sla"] for r in rows[:2])
    assert rows[-1]["kind"] == "REMINDER" and rows[-1]["since_first_seen_s"] == 300.0


def test_a_watch_interval_above_the_cap_is_clamped_below_the_sla():
    assert max(60, min(10_000, nw.POLL_MAX_S)) == nw.POLL_MAX_S < nw.SLA_S


# ---- A-69: continuity (single watcher, arm/exit log, gap measure)
import json as _json
import os


def test_a69_stale_lock_taken_over(tmp_path):
    lock = tmp_path / "w.pid"
    assert nw.acquire_watch(lock, pid=111) is None and lock.read_text() == "111"
    # pid 111 is not a live next_work process, so a later arm (restart / re-entry) takes the lock over
    assert nw.acquire_watch(lock, pid=222) is None and lock.read_text() == "222"


def test_a69_live_watcher_suppresses_duplicate(tmp_path, monkeypatch):
    lock = tmp_path / "w.pid"
    lock.write_text("4242")
    monkeypatch.setattr(nw, "_alive", lambda pid: pid == 4242)
    assert nw.acquire_watch(lock, pid=7) == 4242 and lock.read_text() == "4242"  # duplicate refused, holder untouched


def test_a69_garbage_lock_is_taken_over(tmp_path):
    lock = tmp_path / "w.pid"
    lock.write_text("not-a-pid")
    assert nw.acquire_watch(lock, pid=8) is None and lock.read_text() == "8"


def test_a69_release_only_own_lock(tmp_path):
    lock = tmp_path / "w.pid"
    lock.write_text("5")
    nw.release_watch(lock, pid=6)
    assert lock.exists()                                                         # not ours: left alone
    nw.release_watch(lock, pid=5)
    assert not lock.exists()                                                     # session-closed safe: nothing lingers


def test_a69_alive_rejects_non_watcher():
    import subprocess
    p = subprocess.Popen(["sleep", "5"])                                         # a live pid that is not next_work (e.g. a recycled pid)
    try:
        assert not nw._alive(p.pid)
    finally:
        p.kill()
    assert not nw._alive(2 ** 22 + 12345)                                        # no such pid


def test_a69_arm_log_and_gap(tmp_path):
    log = tmp_path / "arm.jsonl"
    for kind, t in (("ARM", 1000.0), ("EXIT", 2800.0), ("ARM", 2900.0), ("EXIT", 4700.0), ("ARM", 5200.0)):
        nw.arm_log(kind, now=t, path=log)
    rows = [_json.loads(x) for x in log.read_text().splitlines()]
    assert rows[0]["kind"] == "ARM" and "host_time" in rows[0] and rows[0]["at"] == 1000.0
    assert nw.max_gap(rows[:3]) == 100.0 < nw.MAX_GAP_S                          # re-armed 100 s after expiry
    assert nw.max_gap(rows) == 500.0 > nw.MAX_GAP_S                              # 500 s dark would fail the live proof
    assert nw.max_gap([]) == 0.0


def test_a69_watch_exits_on_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(nw, "WATCH_LOCK", tmp_path / "l.pid")
    monkeypatch.setattr(nw, "ARM_LOG", tmp_path / "a.jsonl")
    (tmp_path / "l.pid").write_text("4242")
    monkeypatch.setattr(nw, "_alive", lambda pid: True)
    assert nw.main(["--watch", "120"]) == 0                                      # returns instead of looping
    assert "DUPLICATE_SUPPRESSED" in (tmp_path / "a.jsonl").read_text()
