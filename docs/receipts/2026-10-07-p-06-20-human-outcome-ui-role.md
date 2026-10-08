# Receipt: P-06-20 human outcome entry under the real UI role (lane 06)
- **Action:** re-pinned lane D at `819b5c7` (migration 0018; the lane D fixtures `git archive` `origin/research/agent-04-state`, so no vendored copy changed) and flipped the P-06-18 finding in `tests/lane_d/test_p0618_ui_role_outcome_notes.py`. DRY-RUN; no grants or credentials changed by lane 06.
- **Provenance:** lane D migration `0018_human_outcome_ui.sql` and receipt `2026-10-07-p06-19-human-outcome-ui.md` (commit `0dbddaa`); results from the test run.
- **Result (the FINDING is removed):**
  - The real HTTP route `POST /areq/<id>/outcome` on an engine logged in as `mbos_operator_ui` records Michael's `flip_sold` outcome (item -> OUTCOME_RECORDED). With the capital funded by the same role, the closing outcome moves `earned_working_capital` and `realized_profit` by the net (+50 on revenue 250, cost 200).
  - An agent actor calling `mbos.record_outcome` under that role is refused ("may record only a human outcome"); no outcome row, capital unchanged.
  - Notes and forbidden-write tests unchanged and passing.
- **Operational note:** a deployment may now set `MBOS_APPROVER_DATABASE_URL` and still record outcomes.
