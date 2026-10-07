# Receipt: G-02, A1–A10 against the real spine (Agent 07, lane G)

- **Task:** G-02 (READY_QUEUE, R11 amended).
- **Claimed** `332c26c`. **Delivered** `a1700d9`. DRY-RUN only.
- **Implementation under test (FACT):** Agent 01 `mbos` @ `c5c7c1cb70e1be77e523d4cc33e73ba648acf3e9` (`qa/impl_spine_PIN`). It was installed non-editable from `git archive` into this lane's venv, with `MBOS_CONTRACTS_DIR` pointing at this lane's pinned contracts (F-16). It ran on PostgreSQL 16.2 (pgserver; sockets under `$XDG_RUNTIME_DIR`) plus DBOS. No peer worktree was read or written.
- **Result (FACT):** 90/90 spec cases pass, A1–A10 are all green, and it was stable across 3 consecutive full runs (about 44s each). Report: `docs/qa/SPINE_ACCEPTANCE.md`.

## Method
- Spec tests (`qa/tests/spec/`) call only the QA facade. Every behaviour under test is 01's code:
  - DBOS `discover` / `item_lifecycle` and the approval gate
  - `spine.decide`
  - `ReferenceGateway` and `DryRunEffector`
  - ledger triggers and CHECK constraints
  - `TableKillSwitch` and `LedgerLLMBudget`
  - `audit`
- Destructive tests (tamper, mutation, faults) each use a fresh migrated database, seeded with the real `spine` calls.
- A5/A6 restarts are separate OS processes: `os._exit(137)`, then recovery through `DBOS.launch()`.
- A3/A10 verify independently of 01: the ADR-0010 reference verifier, and this lane's pinned, format-checked contracts.

## Notable observations
- **A3:** forging `dry_run=false` is refused at write, even by a superuser with triggers disabled (CHECK `mvp_dry_run_only`). That is defence beyond detection.
- **A2:** `UPDATE`, `DELETE` and `TRUNCATE` are refused on 7 ledger tables, both as owner and as `agent_write`, so my earlier F-4 Postgres concern is addressed. For `agent_write`, TRUNCATE is refused by missing grant; the owner run proves the trigger.
- **F-18 (new):** NO without a reason is refused through `ContractViolation`, not `DecisionRefused`. It is rolled back with no partial write.

## Corrections made during the work (before commit)
- My adapter deadlocked on a non-reentrant lock.
- Two spec assertions were wrong:
  - the genesis `before_state` is dropped under ADR-0010;
  - re-calling the gateway on an executed request is refused, not replayed.
- A `pkill -f` in my own shell matched itself.
- The first full run hung past 20 minutes. Afterwards I fixed DBOS teardown ordering and added per-test timeouts. The root cause was not isolated (INFERENCE: teardown), and 3 clean runs followed.
- README: corrected the earlier claim that the mock suite "re-runs unchanged" against real lanes.

## Still pending
- A5, A8 and A9 exercise 01's **reference** gateway, kill switch and budget. They must re-run when lane E's real components are wired (A-03/E-02).
- The store is 01's reference DDL. Re-target when A-01 phase 2 lands; only the marked raw-SQL read block changes.
