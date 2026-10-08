# Receipt: G-09, re-verification of 01's fixes for F-42…F-49 (Agent 07, lane G)

- **Task:** G-09 (P1). DRY-RUN only. Stack: `mbos` = 01's fix commit (read as `100d2ed` from the shared object store, identical in `src/ tools/ tests/ docs/research` to the pushed `2f7b887`), 05 `716098e`, 04 `c97ba6b`; pins in `qa/impl_lane_pins.json`, installs verified byte-identical.
- The same attack suite (`qa/tests/followup/`, 34 tests) now passes **34/34 on lane D + E** (the F-42…F-45 strict xfails flipped; I removed them rather than loosening anything). Two premises were restated to 01's chosen design and are explained in the test docstrings: F-42 recovery goes through `workflows.recover_orphan_gates()`; F-43 is an `ITEM_STATE_CHANGED` receipt (effect none) naming the capability.

## A-15 follow-up API
| Finding | Verdict | Evidence |
|---|---|---|
| F-42 orphan gate | **FIXED** | Enqueue broken after commit → `recover_orphan_gates()` starts ≤ 1 gate, a second pass starts none, YES executes exactly once (3 of 3 runs) |
| F-45 concurrency | **FIXED** | 8 concurrent calls → 1 request, 1 execution (3 of 3 runs; earlier 0 of 3) |
| F-43 invisible denial | **FIXED** | Receipt on the item names `comms.voice.call` and says it was blocked; item stays ACTED |
| F-44 raw KeyError | **FIXED** | `{}`, None, list, missing keys → DecisionRefused, nothing written |

## Release gate, re-run unmodified, each fault planted alone (`--no-fetch`; fake `origin` refs for 04/05)
| Planted fault | Result |
|---|---|
| none (baseline) | **GREEN**, 259 passed / 1 skipped, 9 checks |
| Frozen contract weakened (F-46) | **RED**: `CHANGED approval.schema.json` |
| Every test skipped (F-47) | **RED**: floor `passed 0 (min 250), skipped 260` (pytest itself says PASS; the floor catches it) |
| Suite shrunk (acceptance dir removed) (F-47) | **RED**: `passed 176 (min 250)` |
| Extra stale `.py` / extra `.json` / replaced `schemas/*.json` / new subpackage dir (F-48) | **RED** each (quick `pins_check()` calls) |
| Live-mode policy (F-49) | **RED**: the new action-path check and the e2e fail, plus pytest |
| Chain hash formula changed in lane D | **RED**: action path `chain 0 ok=False`, e2e, pytest |
| Failing test | RED (G-08) |

F-46, F-47, F-48, F-49: **FIXED**. The action-path check really executes (2 effector calls, 0 live, follow-up, PANIC drill).

## New, residual (F-50, owner 01, P3)
- A failed `git fetch` (rc 128, origin unreachable) is ignored; the gate runs on stale refs and can still PASS.
- Extra non-`.py/.json` files (`.txt`, `.sql`, `.so`, `.pth`) in an installed package are not drift.
- `test_action_path_check_requires_real_executions` greps source text instead of running the check.
- By design, a contract change plus a regenerated `FROZEN.sha256.json` in the same commit passes; the pin guards drift, not an intentional edit (needs review).
