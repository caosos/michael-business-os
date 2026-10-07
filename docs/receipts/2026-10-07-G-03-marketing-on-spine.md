# Receipt: G-03, G1–G4 against the real approval path (Agent 07, lane G)

- **Task:** G-03 (READY after G-02).
- **Claimed** `da66cec`. **Delivered** `46ac715`. **Status: BLOCKED (partial):** G1 is green, while G2/G4 wait on spine changes F-19/F-20 (lane 01). DRY-RUN only.
- **Implementation under test:** Agent 01 `mbos` @ `c5c7c1c`, on PostgreSQL 16 + DBOS, with **this lane's real `MarketingPlanner`** wired into the runtime `Components` (R9). Nothing is mocked.

## Results (FACT; docs/qa/SPINE_ACCEPTANCE.md)
- **G1: PASS (4 cases).**
  - A publishing draft becomes a tier-0, `pending_approval`, `dry_run` request, and nothing executes before approval.
  - NO: nothing is published.
  - YES: published exactly once (one effector call, `effect=publish`, `dry_run=true`).
  - Every `ACTION_EXECUTED` in the ledger traces to Michael's YES on the identical payload hash.
- **G4: strict XFAIL (F-19).** The approved payload has no `content_hash` (verified with `--runxfail`). The spine freezes only {capability, summary, item_id, recommendation_id, target, dry_run}, so draft text is not what Michael approves.
- **G2: strict XFAIL (F-20).** `record_outcome()` raised `TypeError: unexpected keyword argument 'attribution'`.
- **G3: not applicable** in wave one. No review-request path exists.

## Why not DONE
The acceptance condition is "G1–G4 green on the real spine". Making G2/G4 green requires changes in lane 01's code (proposed as P-07-6/P-07-7), and I did not edit another lane's branch. The strict xfails turn into failures, forcing removal of the marker, as soon as those gaps close.
