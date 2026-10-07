# Receipt: C-14, LEARN end to end on lane D (Agent 03)

- **Date:** 2026-10-07
- **Task:** `C-14` (READY_QUEUE @ agent-01 `ca6d056`). Claimed at `abedc41`. Done at `ec97bf7`.
- **Scope:** a THROWAWAY PostgreSQL 16 cluster (pgserver wheel) built from a read-only archive of Agent 04's `state/` (@ `7ef19ba`), destroyed after each run.
  - Agent 01's `mbos` package (@ `ca6d056`) was installed `--no-deps` from a read-only archive into a scratch venv.
  - No shared database, other branch or worktree was touched.

## What the test proves (`tests/test_learn_lane_d.py`; FACT)
1. **Two scored trailers** were written through 04's StateStore.
2. **Two outcomes were recorded by Agent 01's real `spine_d.record_outcome`.** The spine linked the scorecard and the provenance on each.
3. **`learn.load_outcomes`** read them back through 04's SELECT-only views (`v_outcome_documents`, `v_item_documents`).
4. **`calibrate` and `propose_learn_bump`** produced a tier-0 `config.scoring.bump` draft:
   - trailer repair probability 0.95 → 0.875
   - trailer labor 4 → 4.25 h
   - `verify_proposal` true
   - provenance derived from both outcomes
5. **The lane-D store REFUSED the draft:** `null value in column "item_id" of relation "action_requests" violates not-null constraint`. This is exactly the gap ADR-0009 item 9 closes. Row counts are unchanged, no `config.scoring.bump` request exists, and no extra `ACTION_PROPOSED` receipt was written.
6. **Nothing applied:** `verify_chain` is ok; the config and priors files are byte-identical; the priors version is unchanged.
7. **Release gate:** `audit(strict=True)` over the same database is clean (2 audited, 2 receipts matched, 0 weak).

## Finding (FACT)
A first attempt was refused for a *different* reason: `action request references unknown provenance ids`. The LEARN provenance record has to be persisted before the proposal is submitted.
- The persisting step (State MCP / spine) must call `record_provenance(out["provenance"])` first.
- The test now does that, which is what exposed the real contract refusal.

## Suite
- With the lane-D environment (`MBOS_LANE_D_STATE_DIR` pointing at the archived `state/`): **195 passed**, 159 subtests.
- Without it: 193 passed, 2 skipped (py3.12). The py3.10 stdlib run skips the lane-D tests as well.

## When ADR-0009 item 9 lands
Remove the refusal assertion. The draft should then be accepted as `drafted`, awaiting Michael's YES in the Operator UI. The apply path (archive, write, `CONFIG_VERSION_BUMPED`) is still a State-lane action after approval, and nothing in lane C performs it.
