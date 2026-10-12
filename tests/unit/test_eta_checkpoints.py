"""A-71: ETA-driven checkpoints and the once-only event outbox (tools/eta_checkpoints.py), deterministic."""
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location("eta", Path(__file__).resolve().parents[2] / "tools" / "eta_checkpoints.py")
eta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eta)
CHI = ZoneInfo("America/Chicago")
T0 = datetime(2026, 10, 11, 23, 0, tzinfo=CHI)


def cp(**kw):
    rec = {"project": "DealSniffer", "task": "F-151", "responsible": "lane 06 worker", "stage": "WORKING", "evidence": "worker pid 1 started",
           "eta": "about 40 minutes (implementation + tests + browser check)", "next_check_at": "2026-10-11 23:30 CDT",
           "acceptance": "focused tests + browser", "blocker": "NONE"}
    rec.update(kw)
    return rec


def test_required_fields_and_vague_eta_and_project():
    assert eta.validate(cp()) == []
    errs = eta.validate(cp(eta="soon", blocker="", project="CAOSCare"))
    assert any("eta must come from" in e for e in errs) and "missing blocker" in errs and any("project must be" in e for e in errs)
    for k in eta.REQUIRED:
        assert f"missing {k}" in eta.validate({**cp(), k: ""})


def test_next_check_must_be_exact_chicago_time():
    assert eta.parse_chicago("2026-10-11 23:30 CDT") == datetime(2026, 10, 11, 23, 30, tzinfo=CHI)
    assert eta.parse_chicago("2026-12-11 23:30 CST").tzname() == "CST"
    assert eta.parse_chicago("2026-10-11 23:30 CST") is None             # CST during daylight time is wrong, not shifted
    assert eta.parse_chicago("2026-10-12T04:30:00+00:00") is None        # UTC is not Chicago
    assert eta.parse_chicago("2026-10-11T23:30:00") is None              # naive
    assert eta.parse_chicago("2026-10-11T23:30:00-05:00") is not None
    assert any("America/Chicago" in e for e in eta.validate(cp(next_check_at="tonight")))


def test_due_and_not_due_and_exactly_one_outcome():
    r = cp()
    assert eta.decide(r, now=T0, done_ref=None, worker_alive=True, observed_at="x") is None                    # not due -> nothing
    late = T0 + timedelta(minutes=31)
    outs = [eta.decide(r, now=late, done_ref=None, worker_alive=a, observed_at="x") for a in (True, False, None)]
    assert [o["stage"] for o in outs] == ["WORKING", "NEED", "NEED"]
    assert all(o["stage"] in eta.OUTCOMES for o in outs)
    w = outs[0]
    assert eta.parse_chicago(w["next_check_at"]) > late and w["blocker"] == "NONE" and "missed" in w["exception"]


def test_early_done_and_done_wins():
    r = cp()
    o = eta.decide(r, now=T0, done_ref="commit abc123", worker_alive=None, observed_at="x")
    assert o["stage"] == "DONE" and o["early"] is True
    o2 = eta.decide(r, now=T0 + timedelta(hours=2), done_ref="commit abc123", worker_alive=False, observed_at="x")
    assert o2["stage"] == "DONE" and o2["early"] is False


def test_stale_wording_only_without_host_evidence():
    late = T0 + timedelta(hours=1)
    no_evidence = eta.decide(cp(), now=late, done_ref=None, worker_alive=None, observed_at="x")
    assert eta.STALE in no_evidence["evidence"] and no_evidence["blocker"] == eta.STALE
    gone = eta.decide(cp(), now=late, done_ref=None, worker_alive=False, observed_at="2026-10-12T05:00Z")
    assert eta.STALE not in gone["evidence"] and "no worker process" in gone["evidence"]


def test_worker_alive_ignores_shells_and_self_matching_checks():
    ps = ["  101 /home/x/.venv/bin/python -I tools/worker.py F-151 --lane 06",
          "  102 /bin/bash -c ps -eo pid,args | grep 'tools/worker.py F-151'",
          "  103 /home/x/.venv/bin/python -I tools/worker.py F-1510 --lane 06"]
    assert eta.worker_alive("F-151", ps) is True
    assert eta.worker_alive("F-151", ps[1:2]) is False
    assert eta.worker_alive("F-15", ps) is False


def test_outbox_dedupe_ordering_owner_alert_quarantine_and_no_loop(tmp_path):
    ob = eta.Outbox(tmp_path)
    a = ob.add({**cp(), "stage": "ACK"}, at="t1")
    assert ob.add({**cp(), "stage": "ACK"}, at="t2") is None                          # same event -> once
    b = ob.add({**cp(), "stage": "NEED", "blocker": "x"}, at="t3")
    assert (a["seq"], b["seq"]) == (1, 2) and a["owner_alert"] is False and b["owner_alert"] is True
    assert ob.add({**cp(), "project": "CAOSCare"}, at="t4") is None and (tmp_path / "quarantine.jsonl").exists()
    assert ob.add({**cp(), "stage": "DONE", "source": "relay"}, at="t5") is None        # relay output never re-enters
    assert [r["seq"] for r in ob.pending()] == [1, 2]


def test_relay_in_order_retry_without_duplicates(tmp_path):
    ob = eta.Outbox(tmp_path)
    for s in ("ACK", "WORKING", "DONE"):
        ob.add({**cp(), "stage": s, "evidence": f"e-{s}"}, at="t")
    calls = []

    def flaky(body):
        calls.append(body.splitlines()[0])
        return None if len(calls) == 2 else f"c{len(calls)}"
    r1 = ob.relay(flaky)
    assert r1 == {"sent": 1, "failed_at": ob.pending()[0]["event_id"], "pending": 2}
    r2 = ob.relay(lambda body: (calls.append(body.splitlines()[0]) or "ok"))
    assert r2["sent"] == 2 and r2["pending"] == 0
    assert calls == ["DEAL SNIFFER: F-151 — ACK", "DEAL SNIFFER: F-151 — WORKING", "DEAL SNIFFER: F-151 — WORKING", "DEAL SNIFFER: F-151 — DONE"]
    assert ob.relay(lambda b: "x")["sent"] == 0                                          # nothing posted twice


def test_record_validates_and_early_done_closes(tmp_path):
    c, ob = eta.Checkpoints(tmp_path), eta.Outbox(tmp_path)
    try:
        c.record(cp(eta="tbd"), ob, at="t")
        raise AssertionError("vague ETA accepted")
    except ValueError as e:
        assert "eta must come from" in str(e)
    c.record(cp(), ob, at="t")
    done = c.record({"project": "DealSniffer", "task": "F-151", "stage": "DONE", "evidence": "tests 20/0", "commit": "abc"}, ob, at="t", now=T0)
    assert done["early"] is True and c.load()["F-151"]["closed"] == "DONE"


def test_tick_publishes_one_outcome_then_stays_quiet_and_never_launches(tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr(eta.subprocess, "run", lambda *a, **k: launched.append(a))
    c, ob = eta.Checkpoints(tmp_path), eta.Outbox(tmp_path)
    c.record(cp(), ob, at="t")
    late = T0 + timedelta(minutes=45)
    r = eta.tick(tmp_path, late, [], "obs", post=None)
    assert [o["stage"] for o in r["outcomes"]] == ["NEED"] and "gh auth login" in r["relay"]["need"]
    assert eta.tick(tmp_path, late + timedelta(minutes=5), [], "obs", post=None)["outcomes"] == []   # closed -> no repeat
    alive = ["  9 /v/bin/python tools/worker.py F-152 --lane 02"]
    c.record(cp(task="F-152"), ob, at="t")
    r2 = eta.tick(tmp_path, late, alive, "obs", post=lambda b: "ok")
    assert [o["stage"] for o in r2["outcomes"]] == ["WORKING"] and r2["relay"]["pending"] == 0
    assert launched == []
    events = [json.loads(x) for x in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))


def test_agent01_owned_checkpoints_use_the_agent01_session_not_a_worker(tmp_path):
    ps = ["  594278 claude --permission-mode acceptEdits MICHAEL BUSINESS OS — ROUND TWO AGENT 01 — COORDINATOR",
          "  481241 claude --model sonnet You are the persistent CAOSCare coordinator."]
    assert eta.agent01_alive(ps) is True and eta.agent01_alive(ps[1:]) is False          # another project's coordinator does not count
    c, ob = eta.Checkpoints(tmp_path), eta.Outbox(tmp_path)
    c.record(cp(task="A-71", responsible="Agent 01"), ob, at="t")
    r = eta.tick(tmp_path, T0 + timedelta(minutes=45), ps, "obs", post=None)
    assert [o["stage"] for o in r["outcomes"]] == ["WORKING"] and "responsible process observed alive" in r["outcomes"][0]["evidence"]
