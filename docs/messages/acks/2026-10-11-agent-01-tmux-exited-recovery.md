# ACK — Agent 01 tmux session exited (NEED_HOST_RECOVERY)
- **Disposition:** ACK, reconciled (no duplicate launched). Checked 2026-10-11T17:20Z.
- FACT: `tmux has-session mbos-agent-01` present (created 11:32:33 CDT, attached); watchdog, dev-worker, dev-ui, pickup sessions present, one each.
- FACT: all five user units enabled and active; Linger=yes (receipts 593116b, 04bbd50).
- FACT: :8479/health.json HTTP 200; :8766 HTTP 303.
- FACT: owner's [exited] at 11:34 CDT predates the session now present; the cause of that exit is UNKNOWN (not proven).
- Persistence command state reconciled from receipts, not assumed. Full host reboot still untested.
