# Pickup receipt: ARYA-20261010-1822-f136-scope-handoff

Docs-only, dry-run. No code, restart, fetch, spend or contact.

## Observed F-136 state
- Worker ALREADY RUNNING: `tools/worker.py F-136 --lane 06 --kind implement --risk medium --max-turns 80 --timeout 3500`, PID 3956015, started Sat 2026-10-10 18:20:50Z (13:20:50 local), cwd `agent-01-coordinator` worktree; ~1.5 min old when observed at ~18:22Z.
- It was launched ~1 s BEFORE the 1819 carry-over was appended to the F-61 row (18:20:51Z), and its prompt embeds the F-136 row text read at launch. `tools/worker.py` has no scope-update mechanism for a running worker (prompt fixed at launch; it only tells the worker to re-read the full queue on origin).
- Not killed, restarted or duplicated.

## Done
- `docs/status/READY_QUEUE.md`: appended the four carried obligations (estimated/as-of next-bid wording with live minimum unverified; gallery-surface label coverage proven in the required screenshots; reject non-finite bid/increment; honest unknown opening minimum) to the F-136 row, keeping state-filter scope, F-61 dependency and owner boundaries. F-61 row note marked "CARRIED BY F-136"; F-61 not reopened/duplicated.

## Whether the worker has read the amended scope: NOT PROVEN
Queue adoption is not proof. The worker's embedded row is the pre-amendment text; it only sees the amendment if it re-reads the queue from origin after this push is published (the prompt does tell it to). Handoff limitation: retain the obligations for the serial F-136 acceptance closeout; the acceptance reviewer must check them even if the worker's report omits them.

## Tests
None (docs only). Verified by diff of READY_QUEUE.md (2 rows changed).

## Remaining
- Owner decision: none. If the F-136 worker's final report lacks the four items, a follow-up fix belongs on the same F-136 row (lane 06), not a parallel worker.
