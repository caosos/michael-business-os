# F-36: G-22 re-audit fixes (F-121..F-125), dry-run

- **Provenance:** READY_QUEUE row F-36 (coordinator branch); findings from `docs/receipts/2026-10-08-G-22-operator-reaudit.md` (agent-07-marketing). Local UI changes only; nothing sent, spent or published.
- **F-121:** `mission_view.today_header` takes live item states: a leg is "ready for your YES" only while its item is open (not HELD, not ACTED/OUTCOME_RECORDED/LEARNED). After execution it says "Record the outcome of <job>"; after HOLD "Nothing to decide: <job> is on hold".
- **F-122:** `/mission` gets the same states; executed legs show DONE / "awaiting the outcome", held legs ON HOLD, and the DEPLOY headline becomes "DONE for now" when no open YES remains.
- **F-123:** card "Net profit if it goes as planned (not weighted by chance)", mission column likewise; digest and summary "Expected profit, weighted by chance". Labels only; no figure was changed or merged (INFER: net vs probability-weighted EV, per G-22).
- **F-124:** Wanted: "No source is hunting for this yet".
- **F-125:** FACT from `mbos_economics.comps_feed`: `condition == parts` comps go to `as_is_comps`, not resale comps. The save banner says so; the card's Needs section says "Your saved price was not used" while every price saved for the item is `parts`.
- **Tests:** `tests/test_f36_ui.py`. `tools/run_tests.sh`: 245 passed (reference), 106 passed (lane D + E), exit 0 · exit 0.
