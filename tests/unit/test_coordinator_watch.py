import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("cw", Path(__file__).resolve().parents[2] / "tools" / "coordinator_watch.py")
cw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cw)

IDLE = {"name": "agent-01", "status": "idle", "updatedAt": 1000, "tmux": "s:@0.%0"}


def test_unacked_is_set_difference_in_order():
    assert cw.unacked(["a", "b", "c"], {"b"}) == ["a", "c"]


def test_no_llm_wake_when_nothing_is_needed():
    assert cw.wake_decision(needed=[], session=IDLE, quota_ok=True, per_msg={}, t=1e6) == (False, "nothing needed")


def test_wakes_only_an_idle_live_session_with_quota():
    ok, _ = cw.wake_decision(needed=["m1"], session=IDLE, quota_ok=True, per_msg={}, t=1e6)
    assert ok
    assert not cw.wake_decision(needed=["m1"], session={**IDLE, "status": "busy"}, quota_ok=True, per_msg={}, t=1e6)[0]
    assert "awaiting connection" in cw.wake_decision(needed=["m1"], session=None, quota_ok=True, per_msg={}, t=1e6)[1]
    assert "quota" in cw.wake_decision(needed=["m1"], session=IDLE, quota_ok=False, per_msg={}, t=1e6)[1]


def test_wake_limits_gap_and_max_attempts():
    t = 1e6
    recent = {"m1": {"wakes": 1, "last_wake": t - 60}}
    assert not cw.wake_decision(needed=["m1"], session=IDLE, quota_ok=True, per_msg=recent, t=t)[0]
    later = {"m1": {"wakes": 1, "last_wake": t - 700}}
    assert cw.wake_decision(needed=["m1"], session=IDLE, quota_ok=True, per_msg=later, t=t)[0]
    spent = {"m1": {"wakes": cw.MAX_WAKES, "last_wake": t - 99999}}
    assert not cw.wake_decision(needed=["m1"], session=IDLE, quota_ok=True, per_msg=spent, t=t)[0]


def test_delivery_is_never_an_acknowledgement():
    rec = {"at": 1000.0}
    assert cw.verify_wake(rec, IDLE, False, 1010.0) == "DELIVERED"                       # typed, session still idle
    assert cw.verify_wake(rec, {**IDLE, "status": "busy"}, False, 1020.0) == "INGESTED"  # session picked it up
    assert cw.verify_wake(rec, {**IDLE, "updatedAt": 1005_000}, False, 1020.0) == "INGESTED"
    assert cw.verify_wake(rec, IDLE, False, 1000 + cw.INGEST_WAIT_S + 5) == "STALE"      # never ingested
    assert cw.verify_wake(rec, {**IDLE, "status": "busy"}, False, 1000 + cw.ACK_DEADLINE_S + 5) == "STALE"   # ingested but no ack
    assert cw.verify_wake(rec, IDLE, True, 1010.0) == "ACKNOWLEDGED"


def test_health_vocabulary():
    t = 1e6
    base = dict(session=IDLE, unacked_ids=[], per_msg={}, last_check=t - 30, t=t)
    assert cw.classify(**base) == "HEALTHY"
    assert cw.classify(**{**base, "unacked_ids": ["m"]}) == "DEGRADED"
    assert cw.classify(**{**base, "session": None}) == "STOPPED"
    assert cw.classify(**{**base, "last_check": t - 5000}) == "STALE"
    assert cw.classify(**{**base, "last_check": None}) == "STALE"
    assert cw.classify(**{**base, "unacked_ids": ["m"], "per_msg": {"m": {"wakes": cw.MAX_WAKES}}}) == "OWNER_ACTION"
    assert cw.classify(**{**base, "quota_ok": False}) == "DEGRADED"


def test_wake_text_carries_ids_not_bodies(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(cw, "WD", tmp_path)
    monkeypatch.setattr(cw, "send_wake", lambda s, t: sent.append(t) or True)
    monkeypatch.setattr(cw, "WD", tmp_path)
    monkeypatch.setattr(cw, "my_session", lambda: IDLE)
    monkeypatch.setattr(cw, "quota_ok", lambda: True)
    monkeypatch.setattr(cw, "git", lambda *a: type("R", (), {"returncode": 0, "stdout": "abc1234\n"})())
    monkeypatch.setattr(cw, "list_ids", lambda ref, path: ["MSG-1"] if "inbox" in path else [])
    monkeypatch.setattr(cw, "panel_health", lambda: {"reachable": False})
    started = []
    monkeypatch.setattr(cw, "ready_rows", lambda: 2)
    monkeypatch.setattr(cw, "dispatcher_alive", lambda: False)
    monkeypatch.setattr(cw, "start_dispatcher", lambda: started.append(1) or True)
    out = cw.cycle("origin/liaison/test", True, probe=False)
    assert len(sent) == 1 and "MSG-1" in sent[0] and "\n" not in sent[0] and len(sent[0]) < 400
    assert out["projects"]["michael_business_os"]["last_wake_state"] == "DELIVERED"
    # same cycle again immediately: rate-limited, no second wake, no duplicate
    cw.cycle("origin/liaison/test", True, probe=False)
    assert len(sent) == 1 and len(started) == 1                          # dispatcher restarted once (approved work waiting), not in a loop
    # receipts are chained
    rows = [__import__("json").loads(x) for x in (tmp_path / "receipts.jsonl").read_text().splitlines()]
    assert rows[0]["kind"] == "wake_delivered" and rows[0]["provenance"]["sources"]


def test_dispatcher_is_restarted_only_when_approved_work_waits_and_quota_allows():
    assert cw.dispatcher_action(ready=0, alive=False, quota_ok=True, last_start=0, t=1e6) == "NONE"        # deliberate stop: queue empty
    assert cw.dispatcher_action(ready=3, alive=True, quota_ok=True, last_start=0, t=1e6) == "NONE"
    assert cw.dispatcher_action(ready=3, alive=False, quota_ok=True, last_start=0, t=1e6) == "START"
    assert cw.dispatcher_action(ready=3, alive=False, quota_ok=False, last_start=0, t=1e6) == "WAIT"
    assert cw.dispatcher_action(ready=3, alive=False, quota_ok=True, last_start=1e6 - 60, t=1e6) == "WAIT"  # no restart loops


def test_stalled_workers_are_found_by_age_not_killed():
    ps = ["  120 /x/python -I tools/worker.py C-30 --lane 03", " 9000 /x/python -I tools/worker.py D-31 --lane 04 --kind implement",
          " 9000 /x/python -I tools/dispatcher.py", " 9999 bash something"]
    assert cw.stalled_workers(ps) == [{"age_s": 9000, "task": "D-31"}]


def test_probe_and_state_contract_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(cw, "WD", tmp_path)
    monkeypatch.setattr(cw, "git", lambda *a: type("R", (), {"returncode": 0, "stdout": ""})())
    monkeypatch.setattr(cw, "list_ids", lambda ref, path: ["MSG-9"] if "inbox" in path else [])
    monkeypatch.setattr(cw, "stalled_workers", lambda ps: [])
    v = cw.probe_verdict(["origin/liaison/x"])
    assert v["verdict"] == "WAKE" and any("MSG-9" in r for r in v["reasons"])
    monkeypatch.setattr(cw, "list_ids", lambda ref, path: [])
    assert cw.probe_verdict(["origin/liaison/x"]) == {"verdict": "IDLE", "reasons": []}
    spec = importlib.util.spec_from_file_location("cs", Path(cw.__file__).resolve().parent / "coordinator_state.py")
    cs = importlib.util.module_from_spec(spec); spec.loader.exec_module(cs)
    s = cs.state()
    assert {"project", "last_received", "last_ack", "open_items", "heartbeat", "event_wake", "periodic_wake", "accepts_messages"} <= set(s)
    assert s["event_wake"]["status"] == "UNVERIFIED" and "no wake has been acknowledged" in s["event_wake"]["evidence"]


def test_tmux_wake_is_off_by_default(monkeypatch):
    calls = []
    monkeypatch.delenv("MBOS_ALLOW_TMUX_WAKE", raising=False)
    monkeypatch.setattr(cw.subprocess, "run", lambda *a, **k: calls.append(a) or type("R", (), {"returncode": 0})())
    assert cw.send_wake({"tmux": "s:@0.%0"}, "x") is False and calls == []            # nothing is typed into any pane


def test_dispatcher_restart_does_not_depend_on_the_wake_switch(tmp_path, monkeypatch):
    started, sent = [], []
    (tmp_path / "mode.json").write_text('{"wake": false}')                       # tmux wake OFF
    monkeypatch.setattr(cw, "WD", tmp_path)
    monkeypatch.setattr(cw, "send_wake", lambda s, t: sent.append(t) or True)
    monkeypatch.setattr(cw, "my_session", lambda: IDLE)
    monkeypatch.setattr(cw, "quota_ok", lambda: True)
    monkeypatch.setattr(cw, "git", lambda *a: type("R", (), {"returncode": 0, "stdout": "abc\n"})())
    monkeypatch.setattr(cw, "list_ids", lambda ref, path: ["MSG-1"] if "inbox" in path else [])
    monkeypatch.setattr(cw, "panel_health", lambda: {"reachable": False})
    monkeypatch.setattr(cw, "ready_rows", lambda: 3)
    monkeypatch.setattr(cw, "dispatcher_alive", lambda: False)
    monkeypatch.setattr(cw, "start_dispatcher", lambda: started.append(1) or True)
    cw.cycle("origin/liaison/x", True, probe=False)
    assert started == [1] and sent == []                                          # workers resume; nothing typed into any session


def test_only_approved_lane01_ready_rows_count_as_work():
    rows = [{"id": "A-49", "status": "READY", "agent": "worker:side-worktree (sonnet)"}, {"id": "A-50", "status": "READY (A-48 DONE)", "agent": "01"},
            {"id": "W-4", "status": "NEEDS OWNER", "agent": "owner"}, {"id": "F-37", "status": "READY", "agent": "worker:lane-06 (sonnet)"},
            {"id": "A-51", "status": "BLOCKED on A-49", "agent": "01"}, {"id": "A-52", "status": "DONE", "agent": "01"}]
    assert cw.lane01_ready_ids(rows) == ["row:A-49", "row:A-50"]       # not owner decisions, not other lanes, not blocked, not done


def test_wake_text_is_a_fixed_safe_template():
    t = cw.wake_text(["row:A-49", "MSG-1"], "origin/liaison/aria-to-agent-01")
    assert "\n" not in t and "No purchases, sales, seller contact, spending or deployment" in t and "row:A-49" in t
    import pytest
    with pytest.raises(ValueError):
        cw.wake_text(["$(rm -rf x)"], "r")                                   # characters outside the allow-list are refused
    with pytest.raises(ValueError):
        cw.wake_text(["id\ninjected"], "r")


def test_hourly_cap():
    now = 1e6
    assert cw.hourly_cap_ok([{"at": now - 10}] * (cw.MAX_WAKES_PER_HOUR - 1), now)
    assert not cw.hourly_cap_ok([{"at": now - 10}] * cw.MAX_WAKES_PER_HOUR, now)
    assert cw.hourly_cap_ok([{"at": now - 4000}] * 50, now)                   # old wakes do not count


def test_send_wake_refuses_any_other_session_or_text(monkeypatch):
    calls = []
    monkeypatch.setenv("MBOS_ALLOW_TMUX_WAKE", "1")
    monkeypatch.setattr(cw.subprocess, "run", lambda a, **k: calls.append(a) or type("R", (), {"returncode": 0, "stdout": "other-session\n"})())
    assert cw.send_wake({"tmux": "other-session:@0.%3"}, "ok text") is False          # registry says another session
    assert cw.send_wake({"tmux": "mbos-agent-01:@0.%0"}, "ok text") is False           # tmux says the pane belongs to another session
    assert not any("send-keys" in a for a in calls)
    monkeypatch.setattr(cw.subprocess, "run", lambda a, **k: calls.append(a) or type("R", (), {"returncode": 0, "stdout": "mbos-agent-01\n"})())
    assert cw.send_wake({"tmux": "mbos-agent-01:@0.%0"}, "bad\ntext") is False
    assert cw.send_wake({"tmux": "mbos-agent-01:@0.%0"}, "x && $(z) `y`") is False
    assert cw.send_wake({"tmux": "mbos-agent-01:@0.%0"}, "fine text") is True
    assert any("send-keys" in a for a in calls)
