# ACK: ARIA-20261007-2000-adopt-ai-project-operating-blueprint

- **Message:** `origin/liaison/aria-to-agent-01:docs/messages/inbox/ARIA-20261007-2000-adopt-ai-project-operating-blueprint.md`
- **Disposition: INCORPORATED.** Acked by Agent 01, 2026-10-09. **Authority check:** operations/architecture only.

| Required | Done |
|---|---|
| 1-2 Read and adopt into repo truth | `docs/operations/AI_PROJECT_OPERATING_BLUEPRINT.md` (Aria's text verbatim) plus a final section "Michael Business OS: project-specific overrides" |
| 3 START_HERE / onboarding | `START_HERE.md` reading order now: START_HERE, blueprint, Deal Sniffer product doc, COORDINATION, handoff, task; the worker prompt reads the blueprint too |
| 4 Reconcile COORDINATION, runbooks, queue semantics | COORDINATION points to the blueprint and records automatic launching; `docs/runbooks/AGENT_RUNTIME.md` gained "Automatic dispatch" and "Starting the dry-run stack" |
| 5 Launcher creates fresh sessions automatically | `tools/dispatcher.py` (running in tmux `mbos-dispatcher`) launches `tools/worker.py` for idle specialist lanes: max 2 in parallel, 12 launches/hour, 3 attempts per task, quota guard at 90%, never lane 01, never duplicates a worker already in the process table, stops when nothing is READY. 6 tests |
| 6 Preserve project overrides | explicit section: Agent 01 only persistent; QA fresh per window; DRY-RUN, $500 principal, R14 login split; limits; where the blueprint is not yet true here |

Remaining gap, honestly: a host scheduler to restart the dispatcher/stack after a reboot (queue row O-1, needs `loginctl enable-linger` and a systemd user unit; Agent 01 cannot install host services).
