# Receipt: P-06-17 Mission page reads a live plan (DRY-RUN, read-only)

- Agent: 06 Communications. Date: 2026-10-07. Base: `d2f17a5`.
- Provenance: producer `mbos_economics.mission_feed.plan_from_db` (lane 03, P-03-13 @ `bb28734`, proven on PG16 by P-03-15 @ `790df23`); installed mbos-economics 0.13.1 from `origin/research/agent-03-economics` head `882a89f` (re-pin from 0.10.2 / `6a20b91`). It reads `mbos.v_mission_current`, `mbos.capital_position_document()` and `mbos.v_item_documents`.
- Change: `operator_ui/mission_view.py::load_live(backend, now, path)`; `/mission` calls it. On lane D: live plan, validated with `mbos.mission.plan_errors`; the period (only used when no mission is set) is the UTC calendar week. Reference backend, or any producer failure: the `MBOS_MISSION_PLAN_FILE` fallback, and the page states the source and the reason.
- FACT: the task text says "a function in `mbos`"; no such function exists in `mbos` (coordinator). The producer lives in `mbos_economics`, which this lane already depends on, so that is what is called. No other lane's branch was edited.
- FACT: empty DB / no scored live Items -> producer returns DO_NOT_SPEND (or UNKNOWN with no target); nothing is invented (03's tests; shown by the existing F-18 renderer).
- FINDING for lane 03 (proposed task P-06-18): when lane D holds Items whose `scores.scorecard` lacks decision `branches` (as created by this lane's test scorer), `plan_week` raises `KeyError: 'branches'` (`mbos_economics/mission.py:56`) instead of skipping/flagging them. The page then shows the file fallback with "live producer failed: KeyError" rather than a live plan. The lane D test pins this honestly; it flips to the live assertion when 03 fixes it or the DB holds only well-formed scorecards.
- Tests: reference 167 passed; lane D + lane E 43 passed; `exit 0 · exit 0`.
- No sends, spend, publish or credential change.
