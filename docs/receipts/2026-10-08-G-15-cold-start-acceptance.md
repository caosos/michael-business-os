# Receipt G-15: cold-start acceptance

- **Action:** fresh `git worktree` of `origin/research/agent-01-coordinator` @ `d79bd27` (temp dir, detached), followed START_HERE + RUNBOOK + AGENT_RUNTIME + LANE_06 handoff: venv, `devdb up`, `migrate`, `worker --once` on `fixtures/sources/illustrative.json`, `queue`, `card`, `show`, `decide NO`, `audit`, Operator UI (`/` and `/item/<id>` 200), `devdb down`. DRY-RUN; no external contact.
- **Provenance:** commands and outputs recorded in `docs/qa/COLD_START.md`; UI code from `git archive origin/research/agent-06-communications operator_ui comms_spec`.
- **Result:** all 15 steps pass once N1..N4 are applied; two gaps filed: F-70 (`mbos queue` lacks item_id), F-71 (RUNBOOK lacks Operator UI start instructions; UI not on coordinator head). Both are in `FINDINGS` / `FINDING_STATUS` as OPEN.
- **Health (pins mbos 944f8e4):** `spine --rc` 105 passed, 3 skipped, 0 failed (READY); `card` 457 passed, 0 failed; `run` completed.
- **Cleanup:** temp worktree/DB are under /tmp and disposable.
