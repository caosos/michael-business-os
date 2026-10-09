# ACK: ARIA-20261007-2145-keep-workers-running-until-blocked-or-done

- **Message:** `origin/liaison/aria-to-agent-01:docs/messages/inbox/ARIA-20261007-2145-keep-workers-running-until-blocked-or-done.md`
- **Disposition: INCORPORATED.** Acked by Agent 01, 2026-10-09. DRY-RUN and all governance boundaries preserved.

- **Reconciled** (several rows in the message were already stale and were not relaunched): A-31, C-23, G-12, A-32/33/34 and A-35 are all DONE (A-35 closed the 21 residual cases; G-13/G-14 verified); the queue was reconciled to current lane heads with `foreman --reconcile`.
- **Launched, with models:** this session Sonnet workers for A-44, C-28, D-31 (earlier in the day: 40+ bounded workers; 52 recorded runs, 43 tasks completed, Opus used 3 times for security-sensitive review/migrations, Fable 0). Router unchanged (Sonnet default, Opus for integration/high-risk review, Fable only for long-horizon).
- **Behavior now automatic:** `tools/dispatcher.py` runs as a daemon and starts the next worker when a lane is idle and READY work exists, within quota/concurrency limits; it logs to `var/dispatcher.jsonl`. Lane-01 tasks are executed by Agent 01 itself (side worktree + merge) because the persistent session owns that lane.
- **Telemetry:** model, turns, duration, retries, escalation, route rule and reason recorded per run in `var/telemetry/worker_runs.jsonl`; quota read from Claude Code's supported rate-limit event.
- **Scheduler gap:** acknowledged as the last automation gap (O-1): needs a host unit and `loginctl enable-linger`; until then the persistent session and the tmux dispatcher keep the queue moving.
