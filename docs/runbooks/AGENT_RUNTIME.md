# Agent runtime: persistent control plane + bounded workers (ADR-0014)

## Who is persistent
Only **Agent 01** (`mbos-tmux 1`). Everyone else is a bounded worker started per task.

## Run a bounded worker
```bash
cd ~/business-os-worktrees/agent-01-coordinator
.venv/bin/python -I tools/worker.py TASK_ID --lane 03 --dry            # show route, command and prompt; runs nothing
.venv/bin/python -I tools/worker.py TASK_ID --lane 03 [--kind implement|integration|architecture|...] [--risk low|medium|high] [--cross-lane] [--long-horizon] [--model sonnet|opus|fable]
```
It refuses if: the task is not READY/CLAIMED in `origin/research/agent-01-coordinator:docs/status/READY_QUEUE.md`; the lane still has a live tmux session; the lane worktree is dirty. One escalation on failure (see router). Output: JSON summary; telemetry row(s) appended to `var/telemetry/worker_runs.jsonl`.

The worker may commit and `git push origin HEAD` on its lane branch only. It is denied curl/wget/ssh/sudo/gh, force-push, `reset --hard`, `rm -rf`. Everything is DRY-RUN.

## Pick the model
`config/model_router.v1.json` (data) via `mbos.router.route(TaskProfile(...))`. Defaults: Sonnet; Opus for planning/integration/high-risk review/failed attempt; Fable only for `--long-horizon` architecture/migration/synthesis/deep research. A `--model` override is allowed and is recorded as OVERRIDE.

## Close a lane out (before any session is closed)
`docs/handoff/CLOSEOUT_CHECKLIST.md`. Agent 01 verifies (pushed head == worktree head, clean status, `docs/handoff/LANE_NN.md`, `State: CLOSED`) and only then `tmux kill-session -t mbos-agent-NN`.

## Telemetry and quota
- Runs: `mbos.telemetry` (chained JSONL; `verify` detects edits). Cost is Claude Code's estimate, not a bill.
- Quota: 5-hour and weekly utilization are captured from Claude Code's documented `rate_limit_event` on every worker run. Fable weekly % and the contributor splits are **not** available programmatically: enter a manual snapshot with `telemetry.quota_snapshot(...)`; the dashboard shows them as UNKNOWN until then.
- Idle detection: `tools/foreman.py --wake-text`.

## Efficiency rules
Fresh worker by default. Keep context under about 150k tokens. `/compact` to continue a justified context; `/clear` to change task. At most 2 heavyweight workers in parallel. Durable knowledge goes to the repo, not chat.
