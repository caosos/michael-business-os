# Receipt + report: D-13, review of Agent 01's lane-D backend

- Timestamp: 2026-10-07T18:13:37Z
- Agent: 04
- **Reviewed (read-only, via `git show` / `git archive`):** `research/agent-01-coordinator @ 8c3e4fd`
  - `src/mbos/spine_d.py`
  - `src/mbos/reference/governance_lane_d.py`
  - `src/mbos/adapters/state04.py`
  - `tests/helpers/lane_d.py`, `tests/helpers/common.py`, `tests/helpers/runner.py`
  - `tests/integration/test_spine_on_lane_d.py`
- **Agent 01's branch and worktree were not touched.**
  - Their tree was extracted with `git archive` into Agent 04's scratchpad and run there with a separate Python 3.12 venv.
  - Patches mentioned below were applied **only to that scratch copy**, to prove the diagnosis.
- **Schema under test:** lane D's pushed head, built by 01's own `lane_d.build`.

## Why the lane-D e2e times out (FACT, reproduced)
1. **Root cause.** `tests/helpers/common.py::pending_request` (line 65) runs `SELECT body FROM mbos.action_requests …`. `body` exists only in 01's reference DDL; lane D has columns plus `v_action_request_documents.doc`, so it raises `UndefinedColumn`. The `receipts` helper at line 83 (`SELECT body FROM mbos.receipts`) has the same problem.
2. **Why it hangs instead of failing.** `runner.py` reaches `os._exit` only on success. After an exception, DBOS's non-daemon threads keep the subprocess alive until pytest's 180 s timeout.

**Proof:**
- unpatched: TIMEOUT after 200 s, with both items left in AWAITING_APPROVAL after the decisions
- with the two scratch-only changes below: **rc=0 in 2.2 s**, and every value the test asserts is met:
  - trailer AWAITING_APPROVAL → ACTED; smart_home_install → ARCHIVED; mower ARCHIVED
  - chain OK (56 receipts); ADR-0010 reference `verify_chain` `(True, '56 receipts verified')`
  - effector_calls 1, live 0, executed 1, contract_errors []

**Suggested fixes (01's files):**
- `pending_request`:

  ```sql
  SELECT a.doc FROM mbos.v_action_request_documents a JOIN mbos.action_requests r USING (action_request_id)
  WHERE r.item_id = :i AND r.status IN ('pending_approval','held') ORDER BY r.created_at DESC LIMIT 1
  ```

  Do the same for the receipts helper, using `v_receipt_documents.doc`.
- `runner.py` `__main__`: wrap the dispatch in `try/except BaseException: traceback.print_exc(); os._exit(1)`.
- **The same e2e also passes when the spine connects as the real login `mbos_dbos`:** schema `dbos` owned by it, its own system DB, rc=0, identical RESULT. So 01's role assumptions hold for this path. Today the e2e runs as the pgserver superuser, which exercises no role checks. RECOMMEND switching the test to `mbos_dbos`.

## Findings in spine_d.py
| # | Severity | Finding | Status |
|---|---|---|---|
| F1 | blocker (test) | `body` column in helpers (above) | fix in 01's helpers |
| F2 | major (test infra) | runner hangs on exceptions (above) | fix in 01's runner |
| F3 | **bug, MODIFY path** | `decide(MODIFY)` writes provenance with `approval_id`, and the successor request cites it, *before* the approval row exists. Lane D's FK `provenance_approval_fk` was immediate, so it failed with `ForeignKeyViolation`. It is not covered by the e2e. | **fixed on lane D**: migration `0012` makes the FK DEFERRABLE INITIALLY DEFERRED (it must hold at COMMIT). Regression test runs as `mbos_dbos` and fails without 0012. |
| F4 | minor | `set_kill_switch` idempotency key includes `new_id('rcpt')`, so it is never replay-safe. If it ever runs inside a DBOS step, a replay double-writes. | use a caller-supplied request id |
| F5 | ok | Version-keyed item idempotency (`{item}:v{n}:{to}`, plus a patch hash for patches) is replay-safe, because `_version` locks the row and the key is unique per version | none |
| F6 | ok | Expiry as `POLICY_DECIDED` (pending\|held → expired) matches the lane-D guidance until ADR-0009's `ACTION_EXPIRED`. Edges and roles are valid. | none |
| F7 | advisory (R4/A-03) | `begin_act` writes ACTION_EXECUTING in one transaction, while the effector call is recorded later in another (`record_effector_call`). For 05's gateway, use `effector_claim` in the same transaction as ACTION_EXECUTING and `effector_finish` afterwards (0007, 07 F-6). | A-03 |
| F8 | advisory | `_propose` sets `untrusted_inputs_present=True`. Any PDP tier > 0 is then rejected by the CHECK (fail-safe by design). Expect a CheckViolation, not a silent tier. | note |
| F9 | perf | `pending_decisions` filters on `v_action_request_documents.doc->>'status'`, which builds a JSON document for every request. Filter on `mbos.action_requests.status` (indexed) and join the view only for the selected rows. | suggestion |
| F10 | ok | `ACTION_EXECUTED` / `ACTION_FAILED` carry approval_id, effect and a dry_run effector_response. `cancelled_by_freeze` from executing is allowed (0007). Document-view reads are correct. | none |

## Results (FACT)
- Lane D: migration `0012` and `tests/test_d13_review.py` added. `pytest`: 184 passed, twice.
- All scratch artifacts (the archive copy, venv, pgserver clusters) stay in Agent 04's scratchpad. The clusters were stopped by `cleanup()`.
