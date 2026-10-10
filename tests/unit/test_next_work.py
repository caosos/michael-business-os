import importlib.util
import sys
from pathlib import Path

T = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(T))
spec = importlib.util.spec_from_file_location("next_work", T / "next_work.py")
nw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nw)

Q = ("| ID | Pri | Task | Deps | Status | Agent | Acceptance |\n"
     "| A-1 | P1 | mine ready | none | READY | 01 engineering | x |\n"
     "| A-2 | P1 | mine blocked by dep | A-9 | READY | 01 | x |\n"
     "| A-3 | P1 | other lane | none | READY | 06 | x |\n"
     "| A-4 | P1 | mine done | none | DONE | 01 | x |\n"
     "| A-5 | P2 | side | none | READY | worker:side-worktree | x |\n"
     "| A-9 | P2 | unfinished | none | BLOCKED | 01 | x |\n")


def test_reports_new_instruction_and_ready_unblocked_own_rows_once():
    lines, seen = nw.new_items(["M1"], Q, {})
    assert lines[0] == "NEW INSTRUCTION M1"
    assert [l.split()[2] for l in lines[1:]] == ["A-1", "A-5"]            # not A-2 (dependency open), A-3 (other lane), A-4 (done), A-9 (blocked)
    again, seen = nw.new_items(["M1"], Q, seen)
    assert again == []
    more, seen = nw.new_items(["M1", "M2"], Q, seen)
    assert more == ["NEW INSTRUCTION M2"]


def test_a_row_that_leaves_ready_and_returns_is_reported_again():
    _, seen = nw.new_items([], Q, {})
    _, seen = nw.new_items([], Q.replace("| A-1 | P1 | mine ready | none | READY", "| A-1 | P1 | mine ready | none | DONE"), seen)
    lines, _ = nw.new_items([], Q, seen)
    assert any("A-1" in l for l in lines)


def test_dependency_done_unblocks_the_row():
    lines, _ = nw.new_items([], Q.replace("| BLOCKED | 01 | x |", "| DONE | 01 | x |"), {})
    assert any("A-2" in l for l in lines)
