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
    lines, seen = step({"M1": WAIT}, Q, {}, {}, 1000)
    assert "NEW INSTRUCTION M1" in lines and ids(lines) == ["A-1", "A-5"] and len(lines) == 3
    assert step({"M1": WAIT}, Q, seen, {}, 1300)[0] == []                       # inside the interval: nothing
    again, seen = step({"M1": WAIT}, Q, seen, {}, 1700)                          # notification was missed: bounded retry
    assert len(again) == 3 and all(l.startswith("REMINDER #2") for l in again)
    assert step({"M1": WAIT}, Q, seen, {}, 1800)[0] == []
    third, _ = step({"M1": WAIT}, Q, seen, {}, 2400)
    assert third[0].startswith("REMINDER #3")


def test_an_active_claim_suppresses_announcements_and_done_stops_retries_for_good():
    _, seen = step({"M1": WAIT}, Q, {}, {}, 1000)
    claim = {"M1": {"state": "STARTED"}, "A-1": {"state": "STARTED"}}
    lines, seen = step({"M1": WAIT}, Q, seen, claim, 9999)
    assert ids(lines) == ["A-5"]                              # claimed items are silent, the unclaimed A-5 is still reminded
    done = {"M1": {"state": "DONE"}, "A-1": {"state": "DONE"}, "A-5": {"state": "DONE"}}
    assert step({"M1": WAIT}, Q, seen, done, 99999)[0] == []


def test_completed_pickup_acks_and_other_lanes_are_never_announced_and_ineligible_items_are_forgotten():
    lines, seen = step({"OLD": "COMPLETED (done)", "NOACK": None}, Q, {}, {}, 0)
    assert "NEW INSTRUCTION NOACK" in lines and not any("OLD" in l for l in lines)
    _, seen = step({"NOACK": None}, Q.replace("| A-1 | P1 | mine ready | none | READY", "| A-1 | P1 | mine ready | none | DONE"), seen, {}, 10)
    assert "A-1" not in seen
    back, _ = step({"NOACK": None}, Q, seen, {}, 20)                              # READY again after leaving READY: announced as new
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
    lines, _ = step({"OLD": WAIT}, Q, {"OLD": {"first": 0, "last": 0, "count": 0, "closed": True}}, {}, 99999)
    assert not any("OLD" in l for l in lines)
