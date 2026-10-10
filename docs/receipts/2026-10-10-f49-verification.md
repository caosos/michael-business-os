# Receipt: F-49 verification (code complete, staging verified, live NOT yet updated), 2026-10-10

Stages kept separate:
1. **Code complete (lane 06):** F-49 `820854c`, status `b1a3d16` on `research/agent-06-communications`; receipt `docs/receipts/2026-10-10-f49-live-only-and-gazetteer.md` on that branch.
2. **Staging verified by Agent 01** on :8767 (same database, artifact exported from `b1a3d16` into `var/lanes/agent-06.new`), 2026-10-10 ~03:50-04:05Z:
   - 17 non-demo routes walked (`/ /market /queue /mission /digest /summary /holds /outcomes /ledger /numbers /wanted /notes /assets /resale /intake /gsa /owner-listing`): HTTP 200 each, **0** hits for `TRAIN-`, `example.invalid`, `55 inch`, `LED TV`, `Honda Recon`, `riding mower`, `drywall`.
   - `/market` search "trailer", radius 100: base `72032` and `Conway, AR` both give 6 lots with distances (10.4 and 97.9 mi); base `35.09,-92.44` works; `Dallas, TX` is located (3 lots, 3 hidden by radius) but those TX lots show "distance UNKNOWN (place not located)"; `Nowhereville` says "accepted but not located ... radius is not applied".
   - Not found on the page: a visible "approximate centroid / limited coverage" caveat (searched for "approx", "coverage", "gazetteer"). **Remaining defect for lane 06.**
3. **Live :8766 (read-only, 04:02Z):** still the F-48 export. `/mission` 1, `/summary` 1, `/digest` 1, `/ledger` 1 fiction hit each; `/holds`, `/outcomes` 0. So F-49 is **not live**. A UI-only reload (same procedure as 02:04Z) is required; **no authorization to do that has been given for F-49** (the F-48 reload authorization was used once).

Tests (lane 06 head `b1a3d16`, run serially, 2026-10-10 ~03:50-04:01Z):
- Reference suite: **314 passed, 1 failed**. The failure is `tests/test_resale_f39.py::test_item_moves_intake_to_sold_with_receipt_and_simulated_is_never_earned`, a socket TimeoutError in the full run; it **passes alone (4 of 4)**. It also failed in the F-48 full run. Classified: order/load-dependent timeout, not an F-49 regression.
- Lane D+E: **104 passed, 3 failed**. Two are the known pre-existing F-32 tests (`test_quote_on_the_drywall_lead...`, `test_scope_override_on_an_unknown_category...`). The third, `test_wanted_f25.py::test_double_submit_loser_sees_already_recorded` (assert 200 == 303 on the first `/numbers/capital` withdraw), failed deterministically 3 of 3 here, **and fails identically on the F-48 head `5b42655`**, where the same suite passed 105/2 at ~02:00Z. So it is not caused by F-49; cause not yet established (state or time dependent). Not hidden: it needs its own task.
- Housekeeping found: many leaked `pgserver` postgres processes from old test runs (some days old) under agent-01 and agent-06 venvs. Not touched.

Exact owner gate for live acceptance: one UI-only reload of `mbos-dev-ui` (about 11 s, only that tmux session, copy `var/lanes/agent-06.new` over `var/lanes/agent-06` with the timestamped backup, same start command as `tools/run_dev_stack.sh`, database and worker untouched, rollback = restore the backup), artifact `research/agent-06-communications` @ `b1a3d16`.
