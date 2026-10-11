# Receipt — F-142 exact-clean-commit staging verification (Agent 01, independent)
Verified 2026-10-11T20:12:08Z. Task: F-142 (same row). Inbox: 2026-10-11-f142-exact-clean-commit-browser-proof. Provenance: FACT unless marked.

- Tested commit: `85246899debf5c9b8af418dc5560f3b01273d5ee` (lane 06 status; contains source `84475a8`). Detached clean worktree; `git status --porcelain` = 0 before and after.
- Evidence JSON (`docs/receipts/f142-clean-staging-verification/search-now-evidence.json`): 6 captures, all `code_sha=8524689…`, `operator_ui_tests_tools_dirty=false`, captured 2026-10-11T20:11Z; supersedes the 18:14Z dirty-tree evidence (code_sha 5b2fadc).
- Tests (lane 06 interpreter, clean tree): F-60 + F-56 = **8 passed, 0 failed**. Full lane suite excluding `test_capital_f17.py`: 451 passed, 1 failed (`test_resale_f39`); that test passed 4/4 in isolation at 8524689 and at 5b2fadc, so FACT: not reproducible, INFER: load flake from running the full suite beside my other jobs.
- Real Chrome, loopback ephemeral port, stub store, COPY of real GSA cache: desktop 1648x1000 click, mobile 390x844 click, desktop Enter. Typing Min 5 / Max 25 changed results 11 -> 0 in all three. Geometry flags all true: button below both sliders, below all filter controls, inside the filter card.
- I read the screenshots (not only the script's flags): Search Now is the last control in the filter card after Location, Min/Max sliders, Categories, Category/keywords, Broad, Keywords, More filters (desktop and mobile). Crops: `crop-desktop.png`, `crop-mobile.png`.
- Verdict: **F-142 STAGING_ACCEPTED at 8524689.** NOT LIVE_VERIFIED. No reload requested or performed; :8766 untouched.
- Residual / UNKNOWN: "More filters" is collapsed, so its contents were not exercised for ordering (the details sit above the button by DOM position). Condition lives inside it.
- Pitfall found: lane 06's venv resolves `mbos` via an untracked `.tools/` dir in its own worktree; a fresh checkout fails `test_market_f56` (RemoteDisconnected on POST /market/save) until `.tools` is linked. Same failure at 5b2fadc, so not a regression.
- NEED (live): owner authorization for ONE UI-only :8766 reload at 8524689 via docs/handoff/LIVE_RELOAD_PACKET_8766.md; then artifact hash, /health, cache sha256, fresh screenshot.
