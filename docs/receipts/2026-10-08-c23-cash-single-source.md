# Receipt: C-23 single source for current_cash + WRONG BUY TODAY reason (F-57/F-58)
DRY-RUN. No external action. Tags: FACT / INFER / REC / UNK.

- FACT: engine read `economics.context.current_cash` per item while the card read Michael's profile. Now the engine reads only `operator_context.current_cash` in scoring config 2026.10.3, mirrored from `config/operator_profile.v1.json` `current_cash_context.value` (a test fails on drift). Per-item `current_cash` is refused by input validation.
- FACT: current_cash is null (UNK, Michael has not stated it): cash-pressure factor 1, scorecard reports `current_cash_context.known=false`. No agent guessed a value.
- FACT: new `ranking.wrong_buy_season_factor_max` = 0.5 (REC, provisional). A CAPITAL_INTENSIVE_FLIP with seasonality_factor <= 0.5 gets `ranking.timing_flag = WRONG_BUY_TODAY` and a `WRONG BUY TODAY: ...` line in scorecard `reasons`; the digest reason carries it too. The late-season mower (factor 0.2) shows it; the TV does not.
- INFER: the card (lane 01) composes its own capped `why` list from scorecard reasons; the line is present in the scorecard and digest, card rendering is Agent 01's.
- Versions: package 0.13.1, config 2026.10.3 (2026.10.2 copied to config/history/; engine tolerates its missing key for replay). Goldens, deal_sniffer and class examples, lane-D export fixture regenerated; sensitivity header re-pinned (tables unchanged).
- Tests: `cd economics && PYTHONPATH=src:tests pytest tests -q` -> 334 passed, 0 failed, 21 skipped.
