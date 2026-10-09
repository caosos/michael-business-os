# OWNER PRIORITY — DEAL SNIFFER: DIAGNOSE STOPPED DISPATCHER, DO NOT REBUILD

Date: 2026-10-09 CDT. Evidence: owner captured live Mission Control :8477 page at approximately 15:16 CDT (from read-only feed :8479 / host process list), reporting:
- `michael_business_os` coordinator manual-only under `michaelos`, not reachable by current Desktop-Agent peer relay; automatic self-wake remains disabled.
- `WORKERS IDLE`, active processes 0; `dispatcher not running`; stalled 0; **ready rows 1**; **quota allows a turn: true**. This is one timestamped observation, NOT proof of current runtime when you read this.
- Owner wonders if he needs to discard/restart his whole Claude Code session. **Do not recommend that as a first fix**; preserve existing state and worktrees.

## Your bounded operator objective
1. At your next authorized sync, compare *current* live :8479 health, tmux sessions, dispatcher/watchdog receipts, worker state/queue, quota and actual process list to the screenshot. Explain why `mbos-dispatcher` was stopped while authorized READY work existed with quota available. Is it an intentional stop, crashed service, stale queue, source feed mismatch, or a watchdog restart failure? Do not assert root cause until observed.
2. If it is an ordinary within-current-permissions dispatcher failure, use the **existing documented non-privileged recovery/start path** under the same account, observing queue guards and no duplicate worker launches. Do not change host services, users, persistent config, Claude settings, or tmux self-wake flags. Don't bypass previous classifier refusals; if recover needs a new protected approval, record exact ONE operator step and stop that action while advancing other work.
3. Reconcile lane 01 (A-49) and workers queued (C-33/D-33/F-39 etc.) against actual branch receipts; keep ACK/WORKING/DONE accurate. Report whether the dispatcher launches a READY task and obtains a WORKER_STARTED receipt, or explicitly that it remains blocked. Verify after 5 minutes if able, without model polling loops.
4. Record short cause/fix/test/status and any missing owner decision in canonical queue/state/receipt plus matching GitHub ACK; do not claim you made runtime changes from a GitHub-only message.
5. Keep the coordinator session and worktrees; if near context-limit, checkpoint to GitHub then offer a clean resume, not deletion. This is a runtime-recovery task, not authorization for self-wake.

No bids, spend, external contact, unreviewed deployments or host-level changes.
No action without a receipt; no receipt without provenance.