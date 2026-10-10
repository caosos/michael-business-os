# Pickup receipt: ARYA-20261010-2129-a61-integrity-provenance

Docs-only coordination by automatic pickup (dry-run; no code, restart, spend, bid, contact).

## Done
- Read the instruction (A-61 acceptance correction of 83098fc: evidence provenance dropped, no integrity check on read/propose, listing identity not source-scoped) and `docs/status/READY_QUEUE.md`.
- All three fixes need code changes, which pickup may not make. Added READY_QUEUE row **A-64** (P1, READY, 01 engineering session) holding all three fixes, the required regression tests, the value-free import/schema instruction deliverable, and the separation of capability-tested vs actual-case import vs real-candidate application.
- A-64 is marked independent of A-63 (no dependency created). The actual private-case import is recorded as waiting on A-64. The A-61 row is unchanged.

## Not done (needs the engineering session)
- The code correction, the regression run and the updated import/schema instructions are NOT done and UNPROVEN. Whether the session has started A-64 is unproven.
- Tests: none run (docs-only). Numbers: 0 tests, 1 queue row added.

## Remaining blockers
- None for the owner. The parent must keep the private case out of this repo; nothing is learned/applied until secure owner-local write, readback and application proof exist.
