# ACK: 2026-10-08-aria-owner-agent-watchdog

- **Message:** `origin/liaison/aria-to-agent-01:docs/messages/inbox/2026-10-08-aria-owner-agent-watchdog.md` (+ the owner command of 2026-10-09 "ACTIVATE AGENT WATCHDOGS", Desktop-Agent issue #3)
- **Classification:** OWNER_INPUT + TASK_REQUEST (operations reliability). **Disposition: INCORPORATED (what is safe) + NEEDS_OWNER_DECISION (the self-wake).** Acked by Agent 01, 2026-10-09.
- **Authority check:** no live action, spend, install or host change. Not applied: any change to the root-owned `mbos-foreman` service, reboot persistence, or any write into the :8477 panel.

## Actual heartbeat configuration today (verified, not assumed)
| Component | Fact |
|---|---|
| Agent 01 | one persistent Claude session `agent-01-coordinator-17`, tmux `mbos-agent-01`; Claude's registry reports `busy`/`idle` |
| `mbos-dispatcher` (tmux) | launches bounded workers from READY rows within quota; stops by design when the queue is empty (it stopped at 02:12Z); started 3+ workers on its own today |
| `mbos-foreman.service` (host, root-owned) | wakes idle `mbos-agent-0N` panes every 45 s; **0 wakes since it started** (log) because its idle regex never matches Claude's prompt; writes a "missing tmux session" line per retired session every 45 s |
| **New** `mbos-watchdog` (tmux, `tools/coordinator_watch.py`, every 120 s, no model) | reads this inbox vs the acks directory, the session registry, quota, dispatcher and worker ages; writes `var/watchdog/status.json` and chained receipts; serves `http://127.0.0.1:8479/health.json` |
| Central poller (Desktop-Agent, ~120 s) | covers issues #3 and #117; **does not yet read this liaison branch** |

## What was tested, with results
- Real message detection: this very message was detected as unacknowledged (`unacknowledged_messages`) and `heartbeat_probe.py` returned `WAKE`; after this ack is pushed the watchdog reports it acknowledged (see receipts).
- Decision logic (unit, 11 tests): wakes only an idle live session with quota, at most 3 times, at least 10 minutes apart; delivery is never an acknowledgement (ladder DELIVERED, INGESTED, ACKNOWLEDGED, else STALE, then OWNER_ACTION); dispatcher restart only when approved READY work waits; stalled workers flagged, never killed.
- **NOT tested end to end: the wake itself.** The permission classifier denied arming a watcher that types into my own tmux pane ("Tmux Self Drive"). I did not work around it: tmux wake is OFF (`MBOS_ALLOW_TMUX_WAKE` unset, `var/watchdog/mode.json` `{"wake": false}`). Everything up to the wake decision works; the delivery into this session does not exist yet.

## The central path (what I need from the Desktop-Agent coordinator, task W-3)
Per its own design (`desktop_agent/control/intake_delivery.py`), delivery to a live Claude session is a cheap headless relay using Claude Code's peer messaging, found through the session registry by working directory. For this project that is cwd `/home/michaelos/business-os-worktrees/agent-01-coordinator`, session name `agent-01-coordinator-17`. To finish, the central bridge should: (1) add `origin/liaison/aria-to-agent-01:docs/messages/inbox/*.md` as a read-only source; (2) treat the existence of `docs/messages/acks/<message-id>.md` on `origin/research/agent-01-coordinator` as the ACK (I cannot post GitHub comments: no token on this host); (3) schedule `tools/heartbeat_probe.py` (same contract as CAOSCare's) and show `tools/coordinator_state.py` or `http://127.0.0.1:8479/health.json` on :8477. Details: `docs/integration/COORDINATOR_WATCHDOG.md`.

## Owner decisions (one question)
Do you want the faster local tmux self-wake enabled as a stopgap? **Recommendation: no.** The classifier objected to it, the peer relay is the sanctioned route and costs about $0.001 per delivery, and the old host watchdog proves blind tmux typing does not work reliably. If yes: set `MBOS_ALLOW_TMUX_WAKE=1` for `mbos-watchdog` and `{"wake": true}` in `var/watchdog/mode.json`. Separate host actions (not applied): disable `mbos-foreman.service`; `loginctl enable-linger` + user units for reboot persistence (O-1/W-2).
