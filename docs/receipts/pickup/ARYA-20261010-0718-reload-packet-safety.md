# Pickup receipt: ARYA-20261010-0718-reload-packet-safety

Executor: automatic inbox pickup, docs-only, dry-run. Nothing run against live :8766; no script executed; no code changed.

## What I did
- Read the instruction and `tools/reload_ui.sh` (27 lines) on this branch; read the recovery packet `docs/runbooks/port8766-reload-rollback-verification-packet.md`.
- **Confirmed the finding (FACT, by reading):**
  - L6 `set -u` only: no `-e`, no `pipefail`.
  - L14 `git archive ... | tar -x` : a failing `git archive` is masked by the pipe; only `tar`'s status is checked; no check that `$NEW/operator_ui` / `comms_spec` exist or are non-empty.
  - L15 `cp -a $L/agent-06 "$B" && echo` : a failed backup is not fatal; execution continues to L18 `tmux kill-session` and L19 `rm -rf $L/agent-06/{operator_ui,comms_spec}`, i.e. the live UI is stopped and removed with no valid rollback copy. Backup is also never verified.
  - L22-23: success = HTTP 200 on `/market` only; it does not prove the intended artifact (SHA) is what is being served.
  - L24: rollback `cp -a "$B"` is unchecked and `rm -rf $L/agent-06` precedes it.
- This is a code change (`tools/`) plus new tests, which a docs-only pickup must not do.

## Output
- Added READY_QUEUE row **A-54** (P0, owner: Agent 01 engineering) with the exact required hardening, the artifact-identity marker and semantic route checks, the test seam, and the failure-injection test matrix (backup fails, export fails/empty, staged success, 200-but-wrong-artifact). Depends on F-58.
- Tests run: none (0). No safety evidence exists yet; the packet must not be used until A-54 produces it.

## Remaining blockers
- A-54 implementation and test evidence (Agent 01 engineering).
- Owner approval for any live reload is still pending; nothing here requests or implies it.
