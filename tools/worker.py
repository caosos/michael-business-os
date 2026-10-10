"""Bounded-worker launcher (ADR-0014). One fresh `claude -p` run per task, started from repo truth, telemetry recorded, then it exits.

    .venv/bin/python -I tools/worker.py TASK_ID --lane 03 [--kind implement] [--risk medium] [--cross-lane] [--long-horizon]
                                         [--model sonnet] [--worktree PATH] [--dry] [--no-escalate]

* Reads the task row from READY_QUEUE on origin/research/agent-01-coordinator (no chat context is inherited).
* Routes the model with `mbos.router` (config/model_router.v1.json); `--model` overrides, and the override is recorded.
* Refuses to start if that lane still has a live tmux session (two writers on one branch) or the worktree is dirty.
* Uses only supported Claude Code non-interactive mode: `claude -p --output-format stream-json --verbose`. The result event and the `rate_limit_event` is appended to the
  hash-chained telemetry (mbos.telemetry), including 5-hour/weekly utilization when Claude Code reports it. No private endpoints, no scraping.
* The worker may commit and push ONLY its lane branch (`git push origin HEAD`). Network tools, sudo and force-push are denied.
* DRY-RUN rules are part of every prompt. Nothing here contacts anyone, spends money or deploys.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mbos import router, telemetry  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pause  # noqa: E402

LANES = {
    "01": ("Agent 01 Coordinator", "agent-01-coordinator", "research/agent-01-coordinator", "agent-01-coordinator"),
    "02": ("Agent 02 Discovery", "agent-02-opportunity", "research/agent-02-opportunity", "agent-02-opportunity"),
    "03": ("Agent 03 Economics", "agent-03-economics", "research/agent-03-economics", "agent-03-economics"),
    "04": ("Agent 04 State", "agent-04-state", "research/agent-04-state", "agent-04-state"),
    "05": ("Agent 05 Governance", "agent-05-governance", "research/agent-05-governance", "agent-05-governance"),
    "06": ("Agent 06 Communications", "agent-06-communications", "research/agent-06-communications", "agent-06-communications"),
    "07": ("Agent 07 QA", "agent-07-marketing", "research/agent-07-marketing", "agent-07-marketing"),
}
WORKTREES = Path(os.environ.get("MBOS_WORKTREES", str(Path.home() / "business-os-worktrees")))
ALLOWED = ["Read", "Edit", "Write", "Grep", "Glob", "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git add:*)",
           "Bash(git commit:*)", "Bash(git fetch:*)", "Bash(git show:*)", "Bash(git push origin HEAD)", "Bash(ls:*)", "Bash(cat:*)",
           "Bash(.venv/bin/python:*)", "Bash(*/.venv/bin/python:*)", "Bash(python:*)", "Bash(python3:*)", "Bash(pytest:*)", "Bash(.venv/bin/pytest:*)",
           "Bash(*/.venv/bin/*)", "Bash(.venv/bin/*)", "Bash(cd:*)", "Bash(echo:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(sed:*)", "Bash(sort:*)",
           "Bash(find:*)", "Bash(test:*)", "Bash(cut:*)", "Bash(tr:*)", "Bash(diff:*)", "Bash(git grep:*)", "Bash(git -C * grep:*)",
           "Bash(git -C * show:*)", "Bash(git -C * log:*)", "Bash(git -C * status:*)", "Bash(git -C * diff:*)", "Bash(git checkout -- :*)", "Bash(wc:*)", "Bash(grep:*)", "Bash(tools/*)", "Bash(bash tools/*)", "Bash(.tools/uv pip install:*)",
           "Bash(*uv pip install*)", "Bash(*pip install*)", "Bash(git archive:*)", "Bash(tar:*)", "Bash(mktemp:*)", "Bash(mkdir:*)", "Bash(cp:*)", "Bash(git rev-parse:*)", "Bash(git ls-tree:*)"]
DENIED = ["Bash(curl:*)", "Bash(wget:*)", "Bash(ssh:*)", "Bash(scp:*)", "Bash(sudo:*)", "Bash(gh:*)", "Bash(git push --force:*)",
          "Bash(git push -f:*)", "Bash(git reset --hard:*)", "Bash(rm -rf:*)", "Bash(git branch -D:*)", "Bash(git worktree remove:*)"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sh(args: list[str], cwd: Path, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, **kw)


def find_task(queue_text: str, task_id: str) -> Optional[dict]:
    for line in queue_text.splitlines():
        c = [x.strip() for x in line.split("|")]
        if len(c) >= 8 and c[1] == task_id:
            return {"id": c[1], "pri": re.sub(r"\*", "", c[2]), "title": c[3], "deps": c[4], "status": re.sub(r"[*`]", "", c[5]),
                    "agent": re.sub(r"\*", "", c[6]), "acceptance": c[7]}
    return None


def build_prompt(lane: str, task: dict, branch: str) -> str:   # `branch` is the branch the worker must push (HEAD)
    name = LANES[lane][0]
    return f"""You are a fresh bounded worker for {name} (lane {lane}) in Michael Business OS. You have no prior chat context; repo truth is your memory.

TASK {task['id']} (priority {task['pri']}): {task['title']}
ACCEPTANCE: {task['acceptance']}
DEPENDENCIES: {task['deps']}

Do exactly this task, then stop:
1. Run `git fetch -q origin`. The coordination files live on the coordinator branch, NOT on your lane branch: read them with `git show origin/research/agent-01-coordinator:<path>` for START_HERE.md, docs/operations/AI_PROJECT_OPERATING_BLUEPRINT.md (skim: sections 4, 6, 13 and the project overrides at the end), docs/product/DEAL_SNIFFER_START_HERE.md, docs/COORDINATION.md and docs/runbooks/AGENT_RUNTIME.md. Then read, from your own worktree: docs/handoff/LANE_{lane}.md (if present) and docs/status/AGENT_STATUS.md, plus only the files and ADRs the task needs. The queue row above is authoritative; the full queue is `git show origin/research/agent-01-coordinator:docs/status/READY_QUEUE.md`. To use code from the coordinator branch (for example the `mbos` package), `git archive origin/research/agent-01-coordinator <paths>` into a temp dir and install it with `uv pip install` / `pip install` from that local directory (remove any build/ dir first).
2. Work on branch `{branch}` only (you are already in its worktree). Never edit another lane's branch or worktree. Never merge to main.
3. Implement and test. Keep the diff small. Run the lane's health command from its handoff and report the exact pass/fail numbers.
4. Write a receipt under docs/receipts/ for consequential work. No action without a receipt; no receipt without provenance.
5. Update docs/status/AGENT_STATUS.md (`Done: {task['id']} @ <commit>`, `State: CLOSED`).
6. Commit with identity `git -c user.name="{name}" -c user.email="michaelos+{LANES[lane][1]}@users.noreply.github.com"`. End the message with `Co-Authored-By: Claude <noreply@anthropic.com>`. Then `git push origin HEAD` (never force).
7. Print a final JSON line: {{"task":"{task['id']}","status":"DONE|BLOCKED|FAILED","commit":"<sha or null>","tests":"<n passed/n failed>","notes":"<one line>"}} and exit.

Hard rules: never wait on a process with `pgrep -f <text>` or `pkill -f <text>` where <text> also appears in your own shell command (it matches itself and hangs forever; a stuck wait loop blocked lane 06 for 6 minutes): use a pid, a status file, or `timeout`. Everything is DRY-RUN. Do not send messages, contact sellers or customers, spend money, publish, deploy, change credentials, or touch CAOSCare. Do not change frozen contracts (docs/research/contracts v1.0.0) without an accepted ADR. If blocked by a genuine owner decision, a missing credential, or a dependency, say so in the final JSON and in AGENT_STATUS (`Blocked:`), then stop. Keep context small: avoid reading large files you do not need.
"""


PERMISSION_MODES = ("acceptEdits", "auto", "dontAsk")   # never bypassPermissions: the deny-list and the classifier must stay in force


def command(route: router.Route, prompt: str, *, permission_mode: str = "auto") -> list[str]:
    if permission_mode not in PERMISSION_MODES:
        raise ValueError(f"permission mode {permission_mode!r} not allowed for workers; use one of {PERMISSION_MODES}")
    return ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", route.model, "--max-turns", str(route.max_turns),
            "--permission-mode", permission_mode, "--allowedTools", *ALLOWED, "--disallowedTools", *DENIED]


def lane_session_alive(lane: str) -> bool:
    r = subprocess.run(["tmux", "has-session", "-t", f"mbos-agent-{lane}"], capture_output=True)
    return r.returncode == 0


def should_escalate(row: dict) -> bool:
    """Escalate only when a STRONGER MODEL could help. Not when the run was blocked by permissions (a launcher/allowlist problem),
    when the worker itself reported BLOCKED (an owner/dependency problem), or when it finished."""
    if row.get("task_completed"):
        return False
    if (row.get("permission_denials") or 0) > 0:
        return False
    rep = row.get("worker_report") or {}
    if rep.get("status") == "BLOCKED":
        return False
    return True


def run_one(task_id: str, lane: str, profile: router.TaskProfile, *, worktree: Path, dry: bool, model: Optional[str],
            escalate: bool = True, allow_dirty: bool = False, permission_mode: str = "auto", ignore_quota: bool = False, branch_override: Optional[str] = None, max_turns: Optional[int] = None, runner: Optional[Callable[..., Any]] = None, tpath: Optional[Path] = None,
            skip_session_check: bool = False, queue_text: Optional[str] = None, timeout_s: int = 3600,
            prompt_override: Optional[str] = None) -> dict[str, Any]:
    name, _, branch, _ = LANES[lane]
    branch = branch_override or branch
    if not dry and pause.reason():
        return {"ok": False, "error": "PAUSED_BY_OWNER: " + pause.reason()[:160]}
    if queue_text is None:
        sh(["git", "fetch", "-q", "origin"], ROOT)
        queue_text = sh(["git", "show", "origin/research/agent-01-coordinator:docs/status/READY_QUEUE.md"], ROOT).stdout
    task = find_task(queue_text, task_id)
    if task is None:
        return {"ok": False, "error": f"task {task_id} not found in READY_QUEUE"}
    if not re.match(r"READY|CLAIMED", task["status"]):
        return {"ok": False, "error": f"task {task_id} is {task['status']!r}, not READY"}
    if not skip_session_check and lane_session_alive(lane):
        return {"ok": False, "error": f"lane {lane} still has a live tmux session (mbos-agent-{lane}); close it out first (docs/handoff/CLOSEOUT_CHECKLIST.md)"}
    if not dry and not ignore_quota:
        g = telemetry.quota_guard(router.load_policy(), path=tpath)
        if not g["allow"]:
            return {"ok": False, "error": "quota guard: " + g["reason"], "quota_guard": g}
    if not dry:
        st = sh(["git", "status", "--porcelain"], worktree).stdout.strip()
        if st and not allow_dirty:
            return {"ok": False, "error": f"worktree {worktree} is not clean", "status": st.splitlines()[:5]}
    route = router.route(profile)
    if max_turns:
        cap = router.load_policy()["defaults"]["max_turns_cap"]
        route = router.Route(model=route.model, tier=route.tier, rule_id=route.rule_id, reason=route.reason + f" (max_turns {min(max_turns, cap)} by request)",
                             max_turns=min(max_turns, cap), escalate_to=route.escalate_to, notes=route.notes)
    override = None
    if model:
        override, route = route.model, router.Route(model=model, tier="override", rule_id="OVERRIDE", reason=f"explicit --model (router chose {route.model})",
                                                    max_turns=route.max_turns)
    prompt = prompt_override or build_prompt(lane, task, branch)
    if allow_dirty:
        prompt += ("\nNOTE: the worktree has UNCOMMITTED changes from a previous attempt at this same task. Review them with `git status` and "
                   "`git diff`, keep what is correct, finish the task, and commit them. Do not discard work you have not read.\n")
    cmd = command(route, prompt, permission_mode=permission_mode)
    if dry:
        return {"ok": True, "dry": True, "route": route.as_dict(), "cmd": cmd[:2] + ["<prompt>"] + cmd[3:], "prompt": prompt, "task": task}
    run = runner or (lambda c, cwd, env, to: subprocess.run(c, cwd=cwd, env=env, capture_output=True, text=True, timeout=to))
    env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_COMMITTER_NAME": name,
           "GIT_AUTHOR_EMAIL": f"michaelos+{LANES[lane][1]}@users.noreply.github.com", "GIT_COMMITTER_EMAIL": f"michaelos+{LANES[lane][1]}@users.noreply.github.com"}
    attempts, retry, escalated_from, rows = [route], 0, None, []
    while True:
        cur = attempts[-1]
        if pause.reason() and retry > 0:   # owner pause also stops an escalation / retry that would start another model run
            break
        head_before = sh(["git", "rev-parse", "--short", "HEAD"], worktree).stdout.strip() or None
        t0, started = time.time(), now()
        try:
            cp = run(command(cur, prompt, permission_mode=permission_mode), worktree, env, timeout_s)
            rc, out = cp.returncode, cp.stdout
        except subprocess.TimeoutExpired:
            rc, out = 124, ""
        parsed, rl = telemetry.parse_stream(out)
        telemetry.quota_from_rate_limit(rl, path=tpath)  # supported source of 5-hour and weekly utilization; else nothing
        head_after = sh(["git", "rev-parse", "--short", "HEAD"], worktree).stdout.strip() or None
        row = telemetry.append(telemetry.run_row(task_id=task_id, lane=lane, route=cur.as_dict(), started_at=started, ended_at=now(),
                                                 exit_code=rc, result=parsed, retry=retry, escalated_from=escalated_from,
                                                 head_before=head_before, head_after=head_after,
                                                 note=("override of " + override) if override else None), tpath)
        rows.append(row)
        if row["task_completed"] or not escalate or retry >= 1 or not should_escalate(row):
            break
        nxt = router.escalate(cur, profile)
        if nxt is None:
            break
        escalated_from, retry = cur.model, retry + 1
        attempts.append(nxt)
    return {"ok": rows[-1]["task_completed"], "process_ok": rows[-1]["success"], "worker_report": rows[-1].get("worker_report"),
            "permission_denials": rows[-1].get("permission_denials"), "result_text": rows[-1].get("result_text"), "route": route.as_dict(), "runs": rows, "final_model": attempts[-1].model}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task_id")
    ap.add_argument("--lane", required=True, choices=sorted(LANES))
    ap.add_argument("--kind", default="implement", choices=router.TASK_KINDS)
    ap.add_argument("--risk", default="medium", choices=("low", "medium", "high"))
    ap.add_argument("--cross-lane", action="store_true")
    ap.add_argument("--long-horizon", action="store_true")
    ap.add_argument("--model")
    ap.add_argument("--max-turns", type=int, help="override the router's turn budget (capped by the policy max_turns_cap)")
    ap.add_argument("--worktree")
    ap.add_argument("--branch", help="branch name to tell the worker it is on (use with --worktree for a side worktree of the coordinator)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-escalate", action="store_true")
    ap.add_argument("--permission-mode", default="auto", choices=PERMISSION_MODES)
    ap.add_argument("--ignore-quota", action="store_true", help="launch even if the supported quota reading is above the guard (recorded in the output)")
    ap.add_argument("--allow-dirty", action="store_true", help="continue a previous attempt's uncommitted work (the prompt says so)")
    ap.add_argument("--timeout", type=int, default=3600)
    a = ap.parse_args(argv)
    wt = Path(a.worktree) if a.worktree else WORKTREES / LANES[a.lane][3]
    prof = router.TaskProfile(task_id=a.task_id, lane=a.lane, kind=a.kind, risk=a.risk, cross_lane=a.cross_lane, long_horizon=a.long_horizon)
    out = run_one(a.task_id, a.lane, prof, worktree=wt, dry=a.dry, model=a.model, escalate=not a.no_escalate, allow_dirty=a.allow_dirty, permission_mode=a.permission_mode, ignore_quota=a.ignore_quota, branch_override=a.branch, max_turns=a.max_turns, timeout_s=a.timeout,
                  skip_session_check=bool(a.worktree))
    print(json.dumps({k: v for k, v in out.items() if k != "prompt"}, indent=2, default=str))
    if a.dry and out.get("prompt"):
        print("\n--- PROMPT ---\n" + out["prompt"])
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
