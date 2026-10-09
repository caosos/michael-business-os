# Coordinator watchdogs: how Agent 01 is checked, woken and verified

Owner command (2026-10-09): activate watchdogs for the three coordinators without relaying messages between terminals. Everything here is non-LLM, read-mostly, DRY-RUN. Evidence and receipts: `var/watchdog/receipts.jsonl` (hash-chained; each row cites its sources).

## Michael Business OS (this project)
| Piece | What it is | State |
|---|---|---|
| `tools/coordinator_watch.py` (tmux `mbos-watchdog`, every 120 s, no model) | fetches origin, lists `origin/liaison/aria-to-agent-01:docs/messages/inbox` vs `docs/messages/acks/` on the coordinator branch; decides NEED; reads Claude's own session registry (`~/.claude/sessions/*.json`: `status` busy/idle, `tmux` pane) and wakes the session ONLY when idle, quota allows a turn, and limits allow (>= 10 min apart, <= 3 wakes per message). The wake line carries message ids, never bodies | running |
| Verification ladder | DELIVERED (typed into the pane) -> INGESTED (session went busy after the wake) -> ACKNOWLEDGED (ack file on the coordinator branch). Delivery is never reported as acknowledgement; no ingestion in 90 s or no ack in 15 min = STALE; 3 tries = OWNER_ACTION | tested (unit) + live test below |
| Approved work / workers | restarts `mbos-dispatcher` only when specialist READY rows exist and it is down (a deliberate stop on an empty queue is left alone); flags workers older than their 3500 s timeout (never kills) | running |
| Status feed for the panel | `http://127.0.0.1:8479/health.json` (read-only, local); `tools/coordinator_state.py` prints the same fields CAOSCare's `coordinator_state.py` does; `tools/heartbeat_probe.py` returns `{"verdict": "WAKE"|"IDLE"}` | running |
| Read-only probes of the other two projects | public GitHub issues Desktop-Agent #3 and CAOSCare #117: last inbound, last ACK | running |

## The three paths: what actually works (evidence)
1. **Desktop-Agent (issue #3):** WORKS for intake. The control plane ACKs owner items on its own issue within about a minute (7 distinct items ACKed on #3, receipts `path_evidence`). Its coordinator is the control plane itself (no separate Claude session to wake).
2. **CAOSCare (issue #117):** event-driven idle wake VERIFIED by its own coordinator twice: da-46a126825e delivered 02:49:45Z / ACK 02:50:01Z; da-0cf0297adf delivered 02:58:01Z / ACK 02:58:06Z / DONE 02:58:20Z. The PERIODIC heartbeat is still UNVERIFIED: the central bridge has not yet scheduled `heartbeat_probe.py`.
3. **Michael Business OS (liaison inbox):** the central poller does NOT yet read the liaison branch. Until it does, `tools/coordinator_watch.py` is the working path. Result of the live end-to-end test: see the receipts and the ack of `2026-10-08-aria-owner-agent-watchdog`.

## What is NOT possible from this side (and why)
- **Showing status inside the :8477 panel.** Its write API requires a token this project neither has nor should obtain, and the panel belongs to the Desktop-Agent coordinator (project isolation). The feed above is the contract; the panel owner renders it. If it prefers, it can run `tools/coordinator_state.py`.
- **Retiring/limiting the old host watchdog.** `mbos-foreman.service` (`/usr/local/bin/mbos-foreman-watch`, root-owned) types a wake into any idle `mbos-agent-0N` pane every 45 s. FACT from its log: it has made **0 wakes** since it started (its idle regex does not match Claude's prompt) and it writes a "missing tmux session" line per retired session every 45 s. Proposed host change (needs approval, NOT applied): `sudo systemctl disable --now mbos-foreman.service` (it duplicates this watchdog and cannot work as written); the local daemon replaces it.
- **Host persistence after reboot:** `loginctl enable-linger michaelos` plus a systemd user unit starting `mbos-watchdog`, `mbos-dispatcher`, `mbos-dev-worker`, `mbos-dev-ui` (queue row O-1). Not applied.

## Switch for the central bridge
When the Desktop-Agent bridge adds the liaison inbox and schedules `heartbeat_probe.py`, set `var/watchdog/mode.json` to `{"wake": false}` so only one component wakes the session; this daemon then keeps checking, verifying and reporting.
