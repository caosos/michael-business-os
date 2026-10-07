# Receipt: C-13, release-gate AT-1 hook (Agent 03)

- **Date:** 2026-10-07
- **Task:** `C-13` (READY_QUEUE @ agent-01 `a910ad9`). Claimed at `6924a55`. Done at `0d417fb` (package 0.8.1).
- **Deliverable:** `docs/research/agent-03-release-gate-at1.md`. It contains:
  - the one command: `python -m mbos_economics audit --dsn "$MBOS_DSN"` (exit 0 clean / 1 drift / 2 usage)
  - a Python snippet for 01's e2e runner
  - the expected outputs
  - the findings vocabulary

## Integration finding (FACT; from reading agent-01 `a910ad9` read-only)
`src/mbos/spine_d.py::record_score` writes `SCORE_RECORDED` receipts with `inputs_hash` but **without `payload_hash`**. Gating 01's exports with C-12's strict ledger check would have flagged every spine-scored item as drift on correct data.
- **The fix:** such receipts match on `inputs_hash` and are reported as `receipt_weak`. That is not drift; `--strict` turns it into a failure.
- **Proposed P-03-06 (lane A):** the spine adds `payload_hash = sha256_of(scorecard)` to the receipt. The gate can then run with `--strict`.
- 01's missing-input fallback card (never produced by the engine) is reported as `not_engine_scorecard` and is not replayed.

## Verification (FACT)
- The real lane-D export, regenerated under 0.8.1 via Agent 04's StateStore @ `7ef19ba` (throwaway PG16, `verify_chain` ok):
  - `audit` gives exit 0: 19 audited, 19 receipts matched, 0 drift, 0 weak.
- The same Items with receipts in the spine's shape (no `payload_hash`): exit 0, `weak_receipt_count` 19. With `--strict`: exit 1.
- `--dsn` is tested with a stand-in driver (SELECT-only assertion). In production it is a psycopg connection with the read role.
- **Suite:** 193 passed, 159 subtests (py3.12 + jsonschema); 193 OK, 8 skipped (py3.10 stdlib).
