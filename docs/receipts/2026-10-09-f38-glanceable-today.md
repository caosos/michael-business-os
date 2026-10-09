# F-38 receipt: glanceable Today (DRY-RUN)

- **Task:** F-38 (P1), owner UX requirement 2026-10-09 (ack `2026-10-09-aria-owner-deal-sniffer-readable-ui`). Lane 06, branch `research/agent-06-communications`.
- **What changed:** new `operator_ui/glance_view.py`; `/` now shows five compact cards (DONE, WORKING, BLOCKED, OPPORTUNITIES, NEXT) above the existing Today header. The old queue is kept in a collapsed "Full queue". No write path was added.
- **Provenance (FACT, from the code):**
  - DONE lists only items with an ACTION_EXECUTED / OUTCOME_RECORDED receipt, with its seq. Label CONFIRMED needs an outcome with `realized.net_profit` plus an OUTCOME_RECORDED receipt on a non-test item. A dry-run execution is labelled SIMULATED. Items on `.invalid` / `example.` hosts are SIMULATED. Everything else is UNVERIFIED, or SPECULATIVE when no expected profit is stored.
  - Opportunity figures come from the stored Item. Anything missing shows UNKNOWN. A stored YES without an expected profit is shown as MAYBE, with a note. Net and $/hour are the scorecard's expected values and are labelled "weighted by chance".
  - Approve / Hold / Pass post to the existing `/areq/<id>/decide` as YES / HOLD / NO, with CSRF and the payload hash. The PIN box appears when `requires_step_up` says so. Pass requires a reason. "More details" links to `/item/<id>`. No new actions.
  - Red is used only for FROZEN and a missing owner login. Amber is used for items parked waiting on Michael. Top 3 opportunities and top 3 DONE items are shown; the rest are in `<details>`.
- **Tests:** `tests/test_glance_f38.py` (7 tests, labelled TEST data; 2 over real HTTP on the spine: Pass click archives the item, Approve is refused without the PIN, then ACTED shows the receipt seq and "dry-run: nothing real happened", and CONFIRMED never appears). The module list pin in `tests/test_operator_ui.py` now includes `glance_view.py`.
- **Result:** reference backend 266 passed / 0 failed. Lane D + E 104 passed / 2 failed (`tests/lane_d/test_inputs_f32.py` quote and scope tests, `KeyError: 'value'`). The same 2 fail with my change stashed, so they are pre-existing; they test stored-input shape, not Today.
- **Screenshots (TEST DATA preview of the renderer):** `docs/receipts/f38-screens/desktop.png`, `mobile.png`.
- **Not done / UNKNOWN:** "location and source link" show only what the Item stores. The service quote falls back to UNKNOWN unless `job.quoted_revenue` is stored.
