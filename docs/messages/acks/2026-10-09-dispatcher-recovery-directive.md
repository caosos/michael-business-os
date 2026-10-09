# ACK: dispatcher recovery directive (origin/liaison/aria-to-agent-01 f5f5473)

Agent 01, 2026-10-09 ~20:30Z. No host service, Claude setting, tmux wake flag or persistent config was changed. No duplicate dispatcher. Coordinator session and all worktrees preserved.

## Observed (FACT, current runtime, not the screenshot)
- `mbos-watchdog` alive; `tools/dispatcher.py` was not running; no worker processes. `var/dispatcher.jsonl` ends: `idle ... nothing ready for an idle lane` x3, then `stop: no READY work for any idle lane (3 rounds)`. This repeated at 19:55, 20:06, 20:16 (watchdog receipts `dispatcher_restarted`, ready_rows 1).
- The one READY row was **F-39** (lane 06). The dispatcher log shows 3 launches of F-39 (18:09, 18:15, 18:17), all ending without a commit that completes it; `plan_launches` skips a task at `MAX_ATTEMPTS` (3), so the plan was empty and the dispatcher stopped by design.
- Why the 3 attempts failed: the lane-06 worker needed `mbos_economics.auction` (C-32/C-33); lane 06's venv holds an older package; the install into that venv was **denied by the permission classifier** each time; the worker stopped without a workaround and wrote `Blocked: F-39` (020fe2a).
- The quota is not the cause (session 58%, week 86% at the last reading; the reading later went stale, which also stops launches).

## Cause
Intentional stop at the attempt cap, after a permission-denied environment install. Not a crash, not a stale feed, not a failed restart. The watchdog restart loop was a side effect: it counts F-39 as READY work while the dispatcher refuses it.

## Fix / receipt
- Not a within-permissions dispatcher failure, so no restart would help. Relaunching F-39 would only be denied again.
- ONE operator step (yours; writes into lane 06's venv only): `cd ~/business-os-worktrees/agent-01-coordinator && .venv/bin/python -I tools/sync_lanes.py --venv ~/business-os-worktrees/agent-06-communications/.venv` (new `--venv` option, `tools/sync_lanes.py`). Then flip F-39 to READY (or tell me) and delete nothing.
- F-39 row now says BLOCKED (environment). The watchdog's ready count follows the queue, so the restart loop ends.
- Verified that the dispatcher does launch READY workers when launchable: B-23/B-24 (lane 02), C-33 (lane 03), D-33 (lane 04), F-39 attempts (lane 06) in `var/dispatcher.jsonl`; worker telemetry rows in `var/telemetry/worker_runs.jsonl`. I did not poll in a loop.

## Reconciled
A-49 DONE @ b2b3399 (merged, gate green 510); C-33 DONE @ d209573; D-33 DONE @ fd922e5; B-23/B-24 DONE; new A-50, A-51 (lane 01 side worktree). Also fixed a gate failure D-32 caused in lane 01's `record_human_input`.
