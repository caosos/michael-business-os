# Agent Status

Agent: 06
Role: Communications + Operator UI / Approval UX (build lane F)
Branch: research/agent-06-communications
Worktree: /home/michaelos/business-os-worktrees/agent-06-communications
State: WORKING
Claimed: F-02
Done: F-01 @ 190bb9b
Started: 2026-10-06 (Round One) · 2026-10-07 (Round Two)
Last updated: 2026-10-07

## Current objective
**F-02** (READY_QUEUE @ `99e9ec0`): ADR-0010 conformance for lane 06. Next in queue: **F-03** (comms dry-run spec as data).

## Done
- **F-01 @ `190bb9b`** (ruling R10): the Operator UI runs on the spine.
  - Every YES/NO/MODIFY/HOLD is `mbos.spine.decide(channel="web")` in one transaction, plus a DBOS wake.
  - HOLD timers live in the item workflow. "Wake now" sends `michael_ping`.
  - The UI's own gateway, `tick()`, SQLite ledger, mock effector and seed data are removed. A test guards against them coming back.
  - Kept: cards, CSRF, loopback-only, Host check, PIN step-up, HOLD presets.
  - **11 tests pass against the real spine** (DBOS + pgserver Postgres 16; `mbos` pinned at `bed7609`, installed, not merged).
  - Receipt: `docs/receipts/2026-10-07-f01-operator-ui-on-spine.md`. Spec: `docs/research/agent-06-operator-ui.md`.
- Wave one (`3e51ba4`): first UI with a SQLite stand-in, 29 tests. Superseded by F-01.
- Round One: comms research, ADR-001/002, receipts 01–04.

## Findings (F-01)
- FACT: `notify_decision`, named in R10, does not exist in the spine at `bed7609`. The UI uses the same wake as `mbos decide` (`DBOSClient.send(item:<id>, …, topic="decision")`).
- FACT: the item workflow acts on `hold_until`, `escalate_after`, `renotify_after` and `michael_ping`, but **not** on `new_info`, `price_change` or `auction_ending` in `wake_on`.
- FACT: the spine always archives after NO, so the UI's "archive?" checkbox was removed.
- INFERENCE: `SpineBackend.components` must equal the worker's `Components`, because `spine.decide` classifies MODIFY successors with the PDP. This matters once A-03 wires 05's PDP.

## Blockers
None.

## Needs Michael decision
None. Live comms stay disabled (MICHAEL_DECISIONS #4).

## Needs coordinator review
- `tools/interop_check.py` row 06 points at `operator_ui/util.py`, which F-01 removed under R10. F-02 vendors the reference byte-identical at `operator_ui/mbos_canonical.py`. Please repoint row 06 there (adapter `lambda m: m.sha256_of`).

## Proposed tasks
- **P-06-1 (lane A):** a `spine.notify_decision(item_id, approval_id)` helper (named in R10), so the UI and CLI share one wake path.
- **P-06-2 (lane A, with B/C):** have `_approval_gate` act on `wake_on` = `new_info` / `price_change` / `auction_ending`, using a message kind that lanes B/C send. Today these presets only fire at `hold_until`.
- **P-06-3 (lane F, after A-03):** build the UI's `SpineBackend` with the worker's real `Components` (05 PDP).

## Files (Round Two, current)
- `operator_ui/` (`backend`, `ux`, `views`, `server`, `__main__`), `tests/` (conftest, test_operator_ui, fixtures/illustrative.json)
- `docs/research/agent-06-operator-ui.md`, `docs/decisions/ADR-06-003-operator-ui-stdlib.md`, `docs/receipts/2026-10-07-*.md`
- `docs/research/contracts/` (byte-identical frozen v1.0.0)
