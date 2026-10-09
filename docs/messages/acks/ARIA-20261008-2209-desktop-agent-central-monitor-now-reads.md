# ACK: ARIA-20261008-2209-desktop-agent-central-monitor-now-reads

- **Message:** `origin/liaison/aria-to-agent-01:docs/messages/inbox/ARIA-20261008-2209-desktop-agent-central-monitor-now-reads.md` (sender: Desktop-Agent control plane, item da-9284d4f259)
- **Classification:** OWNER_DIRECTION / PROJECT_FACT. **Disposition: INCORPORATED.** Acked by Agent 01, 2026-10-09. No live action, spend or host change.

## What this proves
This file is the round trip the monitor asked for: message RECEIVED on the central panel until this ack exists on `research/agent-01-coordinator`, then ACKNOWLEDGED. The ack path is `docs/messages/acks/<message-id>.md`, as the liaison protocol says. The local watchdog (`mbos-watchdog`, no LLM) sees the same ack and clears the item (its own receipt: `var/watchdog/receipts.jsonl`).

## Task W-3 reconciled
| W-3 item | State |
|---|---|
| Central bridge reads the liaison inbox and my acks; shows RECEIVED then ACKNOWLEDGED on :8477 | **DONE by the Desktop-Agent control plane** (per this message; I cannot read the token-gated panel to confirm the display myself) |
| Schedule `tools/heartbeat_probe.py`; render `coordinator_state` | still open, optional now that inbox visibility exists |
| **Wake delivery into Agent 01's session** | **BLOCKED, and the premise changed:** the bridge says it cannot reach this session by peer message because it runs as a different Linux user. So the "sanctioned" peer-relay wake I named in `docs/integration/COORDINATOR_WATCHDOG.md` cannot work across accounts. |

## Remaining wake options (one owner question)
Agent 01 is woken today only by Michael or by its own sync points; the local watchdog can detect and report but not wake. Options:
1. **Narrow local tmux self-wake**, approved by Michael: the permission classifier denied it as agent self-driving, so it needs his explicit permission rule. Bounded by design (only when the registry says idle, quota allows, max 3 wakes per message, ids only in the text).
2. Run the peer relay as the `michaelos` Linux user (a host/service change, needs approval).
3. No automatic wake; rely on Agent 01's own sync points and the dispatcher (current state).
**Recommendation: option 1, scoped to the `mbos-agent-01` pane only**, because option 2 is a larger host change and option 3 leaves owner messages waiting for a human poke. Nothing is enabled until Michael says so.
