import importlib.util
import json
import sys
from pathlib import Path

import pytest

T = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(T))
spec = importlib.util.spec_from_file_location("engineering_session", T / "engineering_session.py")
es = importlib.util.module_from_spec(spec)
spec.loader.exec_module(es)

Q = ("| ID | Pri | Task | Deps | Status | Agent | Acceptance |\n"
     "| A-1 | P1 | first | none | READY | 01 engineering | x |\n"
     "| A-2 | P0 | needs a1 | A-1 | READY | 01 engineering | x |\n"
     "| A-3 | P2 | other lane | none | READY | 06 | x |\n"
     "| A-4 | P1 | done already | none | DONE | 01 | x |\n"
     "| A-5 | P1 | blocked on owner | none | BLOCKED | 01 | x |\n"
     "| A-6 | P1 | later | A-5 | READY | 01 | x |\n")
IDENT = {"pid": 4242, "entrypoint": "cli", "kind": "interactive"}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(es, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(es, "RECEIPTS", tmp_path / "receipts")


def test_begin_is_idempotent_duplicate_delivery_executes_once():
    assert es.begin("MSG-1", IDENT) == "RUN"
    receipt = es.receipt_path("MSG-1").read_text()
    assert "pid 4242" in receipt and "not the pickup watcher" in receipt
    es.finish("MSG-1", Q, "proof ok")
    assert es.begin("MSG-1", IDENT) == "DUPLICATE_IGNORED"           # redelivered after completion: nothing runs
    assert es.receipt_path("MSG-1").read_text().count("## START") == 1


def test_restart_or_reentry_while_unfinished_resumes_the_same_record_once():
    assert es.begin("MSG-2", IDENT) == "RUN"
    started = es.load()["MSG-2"]["started_at"]
    assert es.begin("MSG-2", IDENT) == "RESUME" and es.begin("MSG-2", IDENT) == "RESUME"
    rec = es.load()["MSG-2"]
    assert rec["started_at"] == started and rec["resumes"] == 2 and es.receipt_path("MSG-2").read_text().count("## START") == 1


def test_completion_advances_to_the_next_eligible_task_once_honouring_deps_and_done_history():
    es.begin("MSG-3", IDENT)
    out = es.finish("MSG-3", Q, "done")
    assert out["next"]["id"] == "A-1"                                  # A-2 is P0 but depends on open A-1; A-3 other lane; A-4 done; A-6 behind blocked A-5
    again = es.finish("MSG-3", Q.replace("| A-1 | P1 | first | none | READY", "| A-1 | P1 | first | none | DONE"), "done again")
    assert again["already_done"] is True and again["next"]["id"] == "A-1"          # no second advance, no re-evaluation
    assert es.next_eligible(Q.replace("| A-1 | P1 | first | none | READY", "| A-1 | P1 | first | none | DONE"))["id"] == "A-2"
    assert es.next_eligible("| ID |\n") is None
    assert "A-4" != es.next_eligible(Q)["id"]


def test_finish_without_begin_is_refused_and_state_survives_a_process_restart():
    with pytest.raises(SystemExit):
        es.finish("NEVER", Q)
    es.begin("MSG-4", IDENT)
    assert json.loads(es.STATE.read_text())["MSG-4"]["state"] == "STARTED"       # durable on disk, a new process sees it
    assert es.begin("MSG-4", IDENT) == "RESUME"


def test_session_identity_is_honest_when_not_under_a_registered_session(tmp_path, monkeypatch):
    monkeypatch.setattr(es, "SESSIONS", tmp_path / "none")
    assert es.session_identity()["entrypoint"] == "unknown"


def test_a_live_holder_keeps_its_claim_a_dead_holder_is_recovered(monkeypatch):
    es.begin("MSG-9", {"pid": 111, "entrypoint": "cli"})
    monkeypatch.setattr(es, "pid_alive", lambda p: p == 111)
    assert es.begin("MSG-9", {"pid": 222, "entrypoint": "cli"}) == "ACTIVE_CLAIM"       # another live session holds it: no duplicate run
    assert es.load()["MSG-9"]["session"]["pid"] == 111
    monkeypatch.setattr(es, "pid_alive", lambda p: False)
    assert es.begin("MSG-9", {"pid": 222, "entrypoint": "cli"}) == "RESUME"             # holder gone: the new session recovers the same record
    assert es.load()["MSG-9"]["session"]["pid"] == 222 and es.receipt_path("MSG-9").read_text().count("## START") == 1
