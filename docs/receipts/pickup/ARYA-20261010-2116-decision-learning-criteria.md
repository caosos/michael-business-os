# Pickup receipt: ARYA-20261010-2116-decision-learning-criteria

## What I did
- Added canonical section **13c "Owner decision learning criteria"** to `docs/product/DEAL_SNIFFER_START_HERE.md` (after 13b-1): decision-record fields, honest outcomes, owner inspect/correct/reset, single-listing pass is not a category dislike, learning never overrides hard filters or gates, no transaction authority, no private amounts.
- Amended the **A-61** row in `docs/status/READY_QUEUE.md`: its inspection result must report adoption of 13c and the smallest existing-model fit/dependency. A-59/A-60 untouched; no new row, worker or datastore.
- Pointed A-61 at existing candidates (contract `Outcome`, `OUTCOME_RECORDED`/`LESSON_RECORDED` receipts) only as things to inspect; fit not yet determined.

## Tests
None run (docs-only; 0 code changes). The learning capability is NOT implemented.

## Remaining blockers
- A-61 inspection still waits on A-60 acceptance. No bid, contact, spend, restart or credentials involved. No private amounts written.
