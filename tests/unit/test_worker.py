import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from mbos import router, telemetry

spec = importlib.util.spec_from_file_location("worker", Path(__file__).resolve().parents[2] / "tools" / "worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

QUEUE = """| ID | Pri | Task | Deps | Status | Agent | Acceptance |
|---|---|---|---|---|---|---|
| T-1 | P1 | do a thing | none | READY | 03 | thing exists |
| T-2 | P1 | blocked thing | T-1 | BLOCKED | 03 | x |
"""
DONE_LINE = '{"task":"T-1","status":"DONE","commit":"abc","tests":"3 passed/0 failed","notes":"x"}'
OK = json.dumps({"type": "result", "is_error": False, "result": "did it\n" + DONE_LINE, "duration_ms": 10, "duration_api_ms": 5, "num_turns": 2, "session_id": "s", "total_cost_usd": 0.1,
                 "modelUsage": {"claude-x": {}}})
BAD = json.dumps({"type": "result", "is_error": True, "duration_ms": 10, "num_turns": 1, "session_id": "s2", "subtype": "error_max_turns"})


@pytest.fixture(autouse=True)
def _isolated_telemetry(tmp_path_factory, monkeypatch):
    """The quota guard reads the REAL telemetry file; tests must never depend on Michael's live quota (found when the real window hit 97%)."""
    monkeypatch.setenv("MBOS_TELEMETRY_DIR", str(tmp_path_factory.mktemp("telemetry")))


@pytest.fixture()
def wt(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(tmp_path), "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    return tmp_path


def cp(rc, out):
    return subprocess.CompletedProcess([], rc, out, "")


def prof(**kw):
    return router.TaskProfile(task_id="T-1", lane="03", **kw)


def test_dry_run_builds_prompt_from_repo_truth_and_never_runs(wt):
    r = worker.run_one("T-1", "03", prof(), worktree=wt, dry=True, model=None, queue_text=QUEUE, skip_session_check=True)
    assert r["ok"] and r["dry"] and r["route"]["model"] == "sonnet"
    p = r["prompt"]
    assert "thing exists" in p and "DRY-RUN" in p and "START_HERE.md" in p and "docs/handoff/LANE_03.md" in p
    assert "--dangerously-skip-permissions" not in r["cmd"] and "--allowedTools" in r["cmd"] and "--disallowedTools" in r["cmd"]


def test_refuses_unknown_blocked_and_live_session_and_dirty_tree(wt, monkeypatch):
    assert "not found" in worker.run_one("T-9", "03", prof(), worktree=wt, dry=True, model=None, queue_text=QUEUE, skip_session_check=True)["error"]
    assert "not READY" in worker.run_one("T-2", "03", prof(), worktree=wt, dry=True, model=None, queue_text=QUEUE, skip_session_check=True)["error"]
    monkeypatch.setattr(worker, "lane_session_alive", lambda lane: True)
    assert "live tmux session" in worker.run_one("T-1", "03", prof(), worktree=wt, dry=True, model=None, queue_text=QUEUE)["error"]
    monkeypatch.setattr(worker, "lane_session_alive", lambda lane: False)
    (wt / "dirty.txt").write_text("x")
    assert "not clean" in worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE)["error"]


def test_successful_run_records_telemetry_with_identity_env(wt, tmp_path):
    seen = {}

    def runner(cmd, cwd, env, to):
        seen.update(env=env, cmd=cmd, cwd=cwd)
        subprocess.run(["git", "-c", "user.name=w", "-c", "user.email=w@w", "-C", str(cwd), "commit", "-q", "--allow-empty", "-m", "work"], check=True)
        return cp(0, OK)

    tp = tmp_path / "t.jsonl"
    r = worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE, runner=runner, tpath=tp, skip_session_check=True)
    assert r["ok"] and r["final_model"] == "sonnet"
    assert seen["env"]["GIT_AUTHOR_NAME"] == "Agent 03 Economics" and seen["cwd"] == wt
    rows = telemetry.read(tp)
    assert len(rows) == 1 and rows[0]["task_id"] == "T-1" and rows[0]["route_rule"] == "R-SONNET" and rows[0]["num_turns"] == 2
    assert telemetry.verify(rows) == []


def test_failure_escalates_once_then_stops(wt, tmp_path):
    models = []

    def runner(cmd, cwd, env, to):
        models.append(cmd[cmd.index("--model") + 1])
        return cp(1, BAD)

    tp = tmp_path / "t.jsonl"
    r = worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE, runner=runner, tpath=tp, skip_session_check=True)
    assert not r["ok"] and models == ["sonnet", "opus"]          # one escalation, never Fable for non-long-horizon work
    rows = telemetry.read(tp)
    assert rows[1]["escalated_from"] == "sonnet" and rows[1]["retry"] == 1


def test_no_escalate_and_override_are_recorded(wt, tmp_path):
    tp = tmp_path / "t.jsonl"
    r = worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model="opus", queue_text=QUEUE, escalate=False,
                       runner=lambda *a: cp(1, BAD), tpath=tp, skip_session_check=True)
    row = telemetry.read(tp)[0]
    assert not r["ok"] and len(telemetry.read(tp)) == 1
    assert row["route_rule"] == "OVERRIDE" and "router chose sonnet" in row["route_reason"] and row["note"].startswith("override of")


def test_timeout_is_a_failed_run_not_a_crash(wt, tmp_path):
    def runner(cmd, cwd, env, to):
        raise subprocess.TimeoutExpired(cmd, to)

    r = worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE, escalate=False, runner=runner,
                       tpath=tmp_path / "t.jsonl", skip_session_check=True)
    assert not r["ok"] and r["runs"][0]["exit_code"] == 124


def test_clean_exit_without_a_commit_is_not_a_completed_task(wt, tmp_path):
    """Found by the first real worker run: exit 0 + is_error false but no commit and no DONE report = the task was NOT done."""
    tp = tmp_path / "t.jsonl"
    r = worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE, escalate=False,
                       runner=lambda *a: cp(0, OK), tpath=tp, skip_session_check=True)   # claims DONE but HEAD did not move
    row = telemetry.read(tp)[0]
    assert row["success"] is True and row["task_completed"] is False and r["ok"] is False and r["process_ok"] is True
    assert telemetry.summarize(telemetry.read(tp))["tasks_completed"] == 0


def test_blocked_report_is_recorded_and_not_completed(wt, tmp_path):
    tp = tmp_path / "t.jsonl"
    out = json.dumps({"type": "result", "is_error": False, "result": '{"task":"T-1","status":"BLOCKED","commit":null,"tests":"","notes":"needs owner"}'})
    r = worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE, escalate=False,
                       runner=lambda *a: cp(0, out), tpath=tp, skip_session_check=True)
    assert not r["ok"] and r["worker_report"]["status"] == "BLOCKED"


def test_no_escalation_for_permission_denials_or_blocked_reports(wt, tmp_path):
    denied = json.dumps({"type": "result", "is_error": False, "result": "can't run python", "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "pytest"}}]})
    models = []

    def runner(cmd, cwd, env, to):
        models.append(cmd[cmd.index("--model") + 1])
        return cp(0, denied)

    worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE, runner=runner, tpath=tmp_path / "a.jsonl", skip_session_check=True)
    assert models == ["sonnet"]                                        # a stronger model cannot fix an allowlist
    assert telemetry.read(tmp_path / "a.jsonl")[0]["denial_samples"] == ["Bash: pytest"]


def test_allow_dirty_continues_previous_work_and_says_so(wt, tmp_path):
    (wt / "half_done.txt").write_text("wip")
    seen = {}

    def runner(cmd, cwd, env, to):
        seen["prompt"] = cmd[2]
        return cp(0, OK)

    assert "not clean" in worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE, skip_session_check=True)["error"]
    worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE, runner=runner, tpath=tmp_path / "b.jsonl",
                   skip_session_check=True, allow_dirty=True)
    assert "UNCOMMITTED changes from a previous attempt" in seen["prompt"]


def test_allowlist_never_contains_network_or_destructive_tools():
    joined = " ".join(worker.ALLOWED)
    for bad in ("curl", "wget", "ssh", "sudo", "push --force", "reset --hard", "rm "):
        assert bad not in joined, bad
    assert "Bash(git push origin HEAD)" in worker.ALLOWED


def test_bypass_permissions_is_never_available_to_workers():
    r = router.route(prof())
    for ok in ("acceptEdits", "auto", "dontAsk"):
        assert worker.command(r, "p", permission_mode=ok)[worker.command(r, "p", permission_mode=ok).index("--permission-mode") + 1] == ok
    for bad in ("bypassPermissions", "default", "plan", ""):
        with pytest.raises(ValueError):
            worker.command(r, "p", permission_mode=bad)
    assert "--dangerously-skip-permissions" not in worker.command(r, "p")
    cmd = worker.command(r, "p")
    assert cmd[cmd.index("--permission-mode") + 1] == "auto"             # default: the classifier, with the deny-list still in force


def test_quota_guard_refuses_launch_and_override_is_explicit(wt, tmp_path, monkeypatch):
    from datetime import datetime, timezone
    tp = tmp_path / "q.jsonl"
    telemetry.append({"kind": "quota_snapshot", "source": "claude_code_rate_limit_event", "session_pct": 97.0, "week_all_pct": 10.0,
                      "session_resets_at": "soon", "week_resets_at": "later", "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}, tp)
    r = worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE, runner=lambda *a: cp(0, OK), tpath=tp, skip_session_check=True)
    assert not r["ok"] and "quota guard" in r["error"] and len(telemetry.read(tp)) == 1       # nothing launched
    r2 = worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE, runner=lambda *a: cp(0, OK), tpath=tp,
                        skip_session_check=True, ignore_quota=True)
    assert "quota guard" not in str(r2.get("error"))


def test_max_turns_override_is_capped_by_policy(wt, tmp_path):
    seen = []
    worker.run_one("T-1", "03", prof(), worktree=wt, dry=False, model=None, queue_text=QUEUE, escalate=False, max_turns=999,
                   runner=lambda c, cwd, env, to: (seen.append(c[c.index("--max-turns") + 1]), cp(1, BAD))[1], tpath=tmp_path / "m.jsonl", skip_session_check=True)
    assert seen == [str(router.load_policy()["defaults"]["max_turns_cap"])]
