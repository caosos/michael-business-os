# Pickup receipt: ARYA-20261010-0706-f58-row-order-proof

Docs-only reconciliation by Agent 01 pickup. No code, tests, browser, restart, reload, spend or contact. No new worker dispatched.

## What changed
`docs/status/READY_QUEUE.md` row **F-58** (existing P0, lane 06) gained two acceptance items:
- **(5) Row-order proof:** on the final committed tree, real browser Save -> reopen -> process restart must show restored custom row order, asserting both the selected row controls (row1-row4) and the rendered DOM row order, including a configured empty row. Populated-card order alone is insufficient. The F-56 log (`docs/receipts/f56-browser/f56-browser.json`, rows `equipment>trailers>>`) is not accepted as order proof; category/condition evidence may be reused for those only.
- **(6) Per-capture provenance:** each capture states its own store and cache. Only the F-57 sidecar/receipt whose serving tool (`serve_market_staging.py`) uses StubStore is corrected; 01's earlier real-cache capture is not relabeled. This refines the stub/real-cache relabel already in F-58 (1) and in `ARYA-20261010-0703` pickup receipt.

## Evidence
Instruction: `origin/liaison/aria-to-agent-01:docs/messages/inbox/ARYA-20261010-0706-f58-row-order-proof.md`; prior receipt `docs/receipts/pickup/ARYA-20261010-0703-final-staging-closeout.md`.

## Tests
None run (docs-only).

## Remaining blockers
- F-58 worker (lane 06, code/browser) must produce the row-order proof; F-58 stays READY, not DONE.
- Live reload still not approved (owner decision after F-58).
