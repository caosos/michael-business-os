# F-144 DealSniffer Marketplace title, radius slider 0-500 that expands, neutral first visit

- Lane 06 · DRY-RUN · 2026-10-11 · owner-resolved (liaison 2026-10-11-owner-unblock-release-alerts-f144). Built on `3960e46`.
- Tested code commit (`code_sha`): `64dfdcc67ae1c2fd4f06da8b0f029e497d63d7c5`; `3d4025a` is the code, `64dfdcc` regenerates the GSA golden (title + slider max only; diff inspected). The commit after it adds only the F-142 tool fix, screenshots, this receipt and status; app code is unchanged.

## Changes
1. Page title `DealSniffer Marketplace` (h1 and page title). Origin/prefs unchanged (per-user data).
2. Slider scale 0-500 (`SLIDER_MAX`). A saved/typed radius over 500 expands the slider max to `ceil(value)` (server render and `static/market_radius.js`); the value is never clamped or changed; the numeric field still validates to 25,000. Field and slider update each other on input.
3. `landing_fix.origin_note`: blank origin shows "Enter a ZIP or city to search by distance." (neutral card); a typed-but-unknown origin keeps the old notice.
4. `tests/test_market_f136.py`: the `if ... else True` assertion is split into two unconditional asserts.
Also: `tests/test_market_f143.py` slider expectations updated to 500; `tools/f143_live_check.py` now checks slider 0/60/120/500 and typed 97.9/750/25000/0; `tools/f142_search_bottom_shots.py` no longer looks up the price sliders F-143 removed (it crashed on `min_r` before this task; pre-existing).

## Tests
- `tests/test_market_f144.py` 7 + f143 + f136 + f47 + f145 golden: pass.
- `tools/run_tests.sh`: reference 483 passed / 2 failed (`test_resale_f39`, known timeout; the golden failure was fixed by regeneration after that run). Lane D+E: 104 passed / 3 failed: `test_inputs_f32` x2 (known F-32) and `test_wanted_f25` concurrent double-submit, which passed 9/9 when run alone (flaky under load; unrelated).
- Real Chrome, 1648x1000 and 390x844: `tools/f143_live_check.py` 36 checks / 0 failed, dirty=false, sha 64dfdcc; `tools/f145_source_shots.py` 22 / 0; `tools/f142_search_bottom_shots.py` all Search-Now-last flags true. There is no `tools/f142_live_check.py`; the F-142 script is the one above.
- Screenshots: `docs/receipts/f144-screenshots/` (slider 0/60/120/500, typed 97.9/750/25000/0, new-user; both viewports). They are full-page and very tall; the per-check evidence is in `f143-evidence.json`. Agent 01 review still needed.

## Not done
No release/reload attempted (Agent 01 does the one combined UI-only reload). No source activation, DB change or new dependency.
