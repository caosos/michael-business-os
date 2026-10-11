# NEED_HOST_RECOVERY — Agent 01 tmux session exited

Owner screenshot at 2026-10-11 11:34 CDT from michaelos shell in ~/business-os-worktrees/agent-01-coordinator:
- watchdog health JSON displayed dispatcher_running true, approved_ready_rows_for_specialist_lanes 0;
- DealSniffer :8766 returned HTTP 200;
- tmux capture showed Claude at a Bash approval prompt;
- Michael entered `1` at the outer Bash prompt (command not found), then `tmux send-keys -t mbos-agent-01 '2' Enter`;
- `tmux attach -t mbos-agent-01` returned `[exited]`.
This proves the named tmux session was not attachable at that moment; it does not prove why Claude exited or whether other services remain up.

On recovery: inspect `tmux has-session -t mbos-agent-01` and current Claude process/session registry before launching; create exactly one existing named coordinator session with `/home/michaelos/bin/mbos-agent 1` only if absent. Check watchdog :8479 health, resolved session/pid, loaded branch SHA, inbox pickup, dispatcher and :8766. Require ACK/WORKING for owner operations takeover (`2026-10-11-owner-operations-takeover.md`) and F-142 Search Now correction (`2026-10-11-owner-search-button-bottom-correction.md`), or a structured NEED. Reconcile persistence command state; do not assume it completed. Do not duplicate coordinator or workers.