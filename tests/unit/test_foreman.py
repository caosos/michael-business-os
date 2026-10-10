import importlib.util
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location("foreman", Path(__file__).resolve().parents[2] / "tools" / "foreman.py")
foreman = importlib.util.module_from_spec(spec)
spec.loader.exec_module(foreman)

QUEUE = """Last synced: heads x
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| B-21 | P1 | tags | none | READY | 02 | ok |
| B-12 | P1 | live | creds | BLOCKED | 02 | ok |
| C-19 | **P0** | floor | none | **CLAIMED** | 03 | ok |
| C-20 | P1 | digest | C-19 | BLOCKED | 03 | ok |
| E-18 | P2 | seams | none | READY | 05 | ok |
| E-17 | P1 | autonomy | A-26 | BLOCKED on A-26 | 05 | ok |
| G-09 | P1 | reverify | none | **READY** | 07 | ok |
"""


def sh(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)


def make_repo(tmp_path, statuses):
    origin = tmp_path / "origin"
    origin.mkdir()
    sh(origin, "init", "-q", "-b", "main")
    for branch, files in {"research/agent-01-coordinator": {"docs/status/READY_QUEUE.md": QUEUE}, **statuses}.items():
        sh(origin, "checkout", "-q", "-B", branch, "main") if False else sh(origin, "checkout", "-q", "--orphan", branch.replace("/", "_"))
        for p, t in files.items():
            f = origin / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(t)
        sh(origin, "add", "-A")
        sh(origin, "commit", "-qm", "x")
        sh(origin, "branch", "-M", branch)
        sh(origin, "rm", "-rfq", ".")
    clone = tmp_path / "clone"
    sh(tmp_path, "clone", "-q", str(origin), str(clone))
    return clone


def lane(state, claimed="", done=""):
    return {"docs/status/AGENT_STATUS.md": f"State: {state}\nClaimed: {claimed}\n{done}\n"}


def test_idle_with_ready_work_exits_2_and_names_task(tmp_path, capsys):
    clone = make_repo(tmp_path, {
        "research/agent-02-opportunity": lane("WAITING"),
        "research/agent-03-economics": lane("WORKING", "C-19"),
        "research/agent-05-governance": lane("WAITING", done="Done: E-17 @ abc"),
        "research/agent-07-marketing": lane("IDLE", "(none)"),
    })
    rc = foreman.main(["--repo", str(clone), "--no-fetch", "--wake-text"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "WAKE 02" in out and "B-21" in out
    assert "WAKE 07" in out and "G-09" in out
    assert "WAKE 03" not in out            # busy
    assert "B-12" not in out               # blocked work is not "ready"


def test_done_tasks_and_blocked_only_lanes_do_not_trigger(tmp_path, capsys):
    clone = make_repo(tmp_path, {
        "research/agent-02-opportunity": lane("WAITING", done="Done: B-21 @ a"),
        "research/agent-03-economics": lane("WORKING", "C-19"),
        "research/agent-05-governance": lane("WAITING", done="Done: E-18 @ b"),
        "research/agent-07-marketing": lane("WORKING", "G-09"),
    })
    assert foreman.main(["--repo", str(clone), "--no-fetch"]) == 0


def test_parse_queue_ignores_non_task_rows():
    rows = foreman.parse_queue(QUEUE)
    assert [r["id"] for r in rows if r["status"].startswith("READY")] == ["B-21", "E-18", "G-09"]


def test_launch_prints_worker_commands_for_idle_lanes_only(tmp_path, capsys):
    clone = make_repo(tmp_path, {
        "research/agent-02-opportunity": lane("WAITING"),
        "research/agent-03-economics": lane("WORKING", "C-19"),
        "research/agent-05-governance": lane("WAITING", done="Done: E-17 @ a · E-18 @ b"),
        "research/agent-07-marketing": lane("CLOSED"),
    })
    rc = foreman.main(["--repo", str(clone), "--no-fetch", "--launch"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "LAUNCH" in out and "worker.py B-21 --lane 02" in out and "worker.py G-09 --lane 07" in out
    assert "--lane 03" not in out and "--lane 05" not in out


def test_exec_refuses_when_queue_is_stale(tmp_path, capsys):
    clone = make_repo(tmp_path, {"research/agent-02-opportunity": lane("WAITING")})
    # QUEUE says "Last synced: heads x" while real heads differ -> stale warning -> refuse
    rc = foreman.main(["--repo", str(clone), "--no-fetch", "--launch", "--exec", "1"])
    assert rc == 3 and "REFUSING" in capsys.readouterr().out


def test_reconcile_marks_only_what_the_owning_lane_reports_done():
    q = """- **Last synced:** old
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| B-21 | P1 | tags | none | READY | 02 | ok |
| B-22 | P1 | other | none | READY | 02 | ok |
| C-19 | P0 | floor | none | **CLAIMED** | 03 | ok |
| E-18 | P2 | seams | none | DONE | 05 | ok |
| X-03 | P1 | builds | none | READY | ALL (02, 03) | ok |
"""
    new, ch = foreman.reconcile(q, {"02": {"B-21"}, "03": {"C-19"}, "05": set()}, {"02": "abc1234"})
    assert sorted(ch) == ["B-21: READY -> DONE", "C-19: CLAIMED -> DONE"]
    assert "| B-22 | P1 | other | none | READY |" in new and "abc1234" in new
    assert "| X-03 | P1 | builds | none | READY |" in new      # needs every named lane to report it


def test_done_line_with_many_ids_is_fully_parsed():
    st = foreman.parse_status("State: CLOSED\nDone: F-01 @ 190bb9b (+ x) · F-02 @ fc31896 · F-18 @ d56f8d2 · X-03 (checked)\n")
    assert st["done"] == {"F-01", "F-02", "F-18", "X-03"}


def _load_foreman():
    import importlib.util, sys
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("foreman_t", Path(__file__).resolve().parents[2] / "tools" / "foreman.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["foreman_t"] = m
    spec.loader.exec_module(m)
    return m


QUEUE_F = """
| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| F-10 | **P0** | first task | none | **READY** | worker:lane-06 (sonnet) | ok |
| F-11 | P1 | depends on F-10 | F-10 | READY | worker:lane-06 (sonnet) | ok |
| F-12 | **P0** **ADDED BY 01: merged pri and title, one column short** | F-10, F-9 | **READY** | worker:lane-06 (sonnet) | ok |
| F-13 | P0 | title with a pipe | x | none | **READY** | worker:lane-06 (sonnet) | ok |
| F-9 | P1 | done earlier | none | **DONE** | worker:lane-06 (sonnet) | ok |
"""


def test_short_or_pipe_rows_are_still_ready_and_dependencies_are_honoured():
    f = _load_foreman()
    rows = {r["id"]: r for r in f.parse_queue(QUEUE_F)}
    assert rows["F-12"]["status"] == "READY" and rows["F-12"]["pri"] == "P0" and rows["F-12"]["agent"].startswith("worker:lane-06")   # one column short
    assert rows["F-13"]["status"] == "READY"                                                                                         # a pipe inside the title
    ready = [r["id"] for r in f.ready_for(f.parse_queue(QUEUE_F), "06", set())]
    assert "F-11" not in ready                       # F-10 is not DONE yet: dispatching F-11 first would be out of order (it was, live)
    assert set(ready) == {"F-10", "F-13"}   # F-12 (a one-column-short row) is parsed as READY but depends on F-10 (not DONE yet), so it must wait
    q2 = QUEUE_F.replace("| F-10 | **P0** | first task | none | **READY**", "| F-10 | **P0** | first task | none | **DONE**")
    assert {"F-11", "F-12"} <= {r["id"] for r in f.ready_for(f.parse_queue(q2), "06", set())}  # once F-10 is DONE the dependents become ready
