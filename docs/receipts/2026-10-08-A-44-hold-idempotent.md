# Receipt: A-44 HOLD wake + idempotent decisions (F-116, F-113, F-118)

DRY-RUN only. No external action, message, spend or credential change.

Provenance: findings F-113, F-116, F-118 in `docs/qa/MISSION_DRYRUN.md` (Agent 07, G-21b, branch `research/agent-07-marketing`); queue row A-44.

Cause (FACT, reproduced in `test_hold_ping_then_yes_reaches_acted_with_receipts`): a second approval gate on the same request (duplicate worker, orphan recovery, retry) starts at `after_seq=0` and replays history. It re-applied the old HOLD (item back to `HELD` after the ping had woken it, so the later YES failed the `APPROVED` trigger), the old NO (`ARCHIVED -> REJECTED`) and the YES (`ACTING -> APPROVED`), each logged as an ERROR traceback.

| Finding | Change | Evidence |
|---|---|---|
| F-116 | `apply_hold` (spine and spine_d) is a no-op unless the request is currently `held` and the item `AWAITING_APPROVAL`/`HELD`; returns `applied`, and the gate sets its hold only when applied | `test_hold_ping_then_yes_reaches_acted_with_receipts` (HOLD -> ping -> twin gate -> YES -> ACTED, 1 effector call, ACTION_EXECUTED receipt); `test_yes_straight_from_hold_reaches_acted` |
| F-113 | `apply_no` is a no-op once the item is already REJECTED/ARCHIVED (rows locked so concurrent gates serialise) | `test_duplicate_gate_applies_a_decision_once_and_logs_no_errors[NO]` (no ERROR log records) |
| F-118 | `begin_act` returns False (nothing done) unless the request is `approved` and the item still awaiting; `_act` then returns `already_applied` and never calls the gateway | same test `[YES]`: one effector call, no ERROR records |
| F-119/F-112 | not done (not cheap: needs a LEARN capability grant / UI wording lane) | UNK |

Note: the lane venv is editable-installed from the coordinator worktree; run tests with `PYTHONPATH=$PWD/src`.

Health (real PG16 via pgserver, `PYTHONPATH=$PWD/src`): full suite 474 passed, 1 failed. The failure is `tests/integration/test_spine_on_lane_d.py::test_full_lifecycle_on_lane_d` (card verdict `PASS` instead of `CONTACT` for the trailer, a timing race with the cleanup NO). It is pre-existing and flaky: the unmodified baseline (HEAD src) fails it 2 of 3 reruns. Not touched here (UNK: owner 01 should make that assertion order-independent).
A-06 acceptance file alone: 10 passed, twice.
