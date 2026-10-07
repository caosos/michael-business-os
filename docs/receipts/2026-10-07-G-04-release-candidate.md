# Receipt: G-04, wave-two release-candidate run (Agent 07, lane G)

- **Task:** G-04 (P0, release). **Claimed** `76545b5`. **Delivered** `6d43d2b`. DRY-RUN only.
- **Verdict (FACT): NOT READY.** 88 passed, 9 failed, 6 strict-xfail known gaps, 3 not applicable; 106 cases. The failing and xfail sets were identical across two clean runs. Report: `docs/qa/RELEASE_CANDIDATE.md`. Findings: `docs/qa/ACCEPTANCE_REPORT.md`.
- **Stack under test:**
  - `mbos` @ `ca6d056` (Agent 01, `state_backend=lane_d`, `gateway_mode=lane_e`)
  - Agent 04 schema @ `a08dd9f`, built as 01's recipe does: roles + pgvector + lane D's own migrator
  - Agent 05 `mbos_governance` @ `101a7e6`, with its WHOLE `policy/` directory
  - PostgreSQL 16 (pgserver) + DBOS
  - All pins are in `qa/impl_lane_pins.json` and `qa/impl_spine_PIN`; everything comes from `git archive`, and nothing is merged or read from a peer worktree.

## Results by acceptance test
- **PASS:** A1, A2 (49/49: UPDATE/DELETE/TRUNCATE as owner and `agent_write` on 7 ledger tables), A3 (verified by lane D's verifier and the ADR-0010 reference alone, including tamper), A4, A6 (YES/NO/MODIFY/HOLD, including HOLD across a process restart), A7, A8, A10, and G1/G2/G4 on the email path.
- **FAIL — F-24 (release-blocking):**
  - A request the gateway DENIES at execution time (freeze engaged before the YES, or an unreadable or corrupt PANIC state) stays `approved` while the item goes FAILED.
  - Once the switch is released or repaired, calling the gateway again EXECUTES the stale approval: the request becomes `executed`, there is one effector row, and the item is still FAILED.
  - The same A9 suite is 8/8 on the reference backend, so the tests are valid.
- **FAIL — F-25 (needs a ruling):** after a hard kill mid-ACT the gateway never duplicates the effector. Both crash points are covered by `test_kill_mid_act_never_duplicates_the_effector`, which passes. But it reconciles to FAILED instead of resuming to ACTED (A5 as written).
- **Strict xfail — F-22:** Agent 05's policy grants `publish.listing.create` to nobody, so the PDP denies the whole flip/publishing path.
- **Strict xfail — F-23:** when the PDP denies a proposal, the item is still moved to AWAITING_APPROVAL with nothing to approve.
- **Not run:** one reference-only test is skipped because it wraps a ReferenceGateway around a live effector. Lane E's own suite covers the equivalent.

## Still not real, even in this stack
- `LedgerLLMBudget` (A8; LiteLLM is not wired)
- The dry-run provider, whose delivery record lives in the process
- The placeholder scorer
- Fixture source adapters
- Real egress cut and credential revocation for L3

## Process notes and corrections
- My first RC run reported 38 failures and 25 errors. It overlapped the window when `/run/user/1001` (a shared 1.5 GB tmpfs) was 100% full, because my hard-killed runs left about 1.1 GB of clusters behind. That run was discarded.
- Cleanup: I stopped only my own 3 postgres processes and deleted only my own `a07-*` directories (tmpfs went from 100% to 3%). The harness now keeps its clusters on disk under a short `/tmp/a07pg-<pid>-*` path, tears them down in a `finally`/fixture and `atexit`, and sweeps orphans of dead runs on the next start. I verified all three paths, including SIGKILL.
- My earlier test assumptions that were specific to the reference backend are now backend-neutral through adapter hooks. No assertion was loosened: A5 was split into the invariant (no duplicate; passes) and "resumes" (as written; fails).
