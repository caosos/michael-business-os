# Pickup receipt: ARYA-20261010-0735-a54-rollback-paths

Routine coordination only (dry-run; no code edited, no live restart, no 8766 operation, no spend/contact).

## Verified by reading `tools/reload_ui.sh` at HEAD (e3b6a42, hardening commit 09de842)
1. **Rollback success test too weak - CONFIRMED.** Line 72: `[ "$(curl ... %{http_code} "$BASE:$PORT/")" != "000" ]` accepts HTTP 500 (any non-000) as "rollback done". Needs the healthy semantic response.
2. **Post-stop `rm` unguarded - CONFIRMED.** Line 78 `rm -rf "$LIVE/operator_ui" "$LIVE/comms_spec"` runs after `tmux kill-session` with no `|| rollback`; under `set -euo pipefail` a failure exits with the UI down and no rollback attempt. (Lines 79-81 and 85-89 do call `rollback`.)
3. **Artifact identity wording:** the script proves on-disk tree hash (`tree_hash`), the `ARTIFACT` marker, tmux session presence and semantic route markers. None is a SHA returned by the running process. No existing process-binding mechanism was found in the script or packet by grep; the limitation is retained and must be stated that way in the packet. No telemetry feature proposed.

## Actions
- Both fixes and tests are code, so not done here. Added READY_QUEUE row **A-55** (P0, owner 01 engineering, depends on DONE A-54, same packet, no new lane) with exact acceptance.
- Until A-55 is DONE the recovery packet must not be described as verified for rollback. No live approval exists; F-59 worker untouched.

## Tests
None run (docs-only task). Prior evidence stands: 9 reload tests and 334 unit tests per the A-54 row; not re-run.

## Remaining blockers
A-55 code and tests (Agent 01 engineering); live reload still needs explicit owner approval.
