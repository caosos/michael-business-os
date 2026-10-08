# Receipt: G-08, independent check of A-15 `propose_followup` and `tools/release_gate.py` (Agent 07, lane G)

- **Task:** G-08 (P1). DRY-RUN only. Queue at `823aa39`. Tests: `qa/tests/followup/` (34 tests; 25 pass + 9 strict xfail on lane D+E; 20 pass + 13 xfail + 1 skip on the reference spine). Findings F-42…F-49 are in `qa/mbos_qa/__main__.py`.
- **Method:** the gate was run UNMODIFIED in a sandbox clone (`/tmp/a07gate/repo`, never committed), one fault at a time; the stale-install checks were run by calling the gate's own `pins_check()`.

## Part 1: A-15 `propose_followup` (lane D + E)
| Attack | Result |
|---|---|
| Item not ACTED (researching, maybe, pass, awaiting approval, failed, unknown id) | Refused (DecisionRefused), nothing written |
| PDP denies / nobody may propose | Denied, item stays ACTED, no gate. **But no request and no receipt: F-43** |
| Negative cost | Rejected by the PDP (`NEGATIVE_COST`), recorded with receipts |
| PANIC L1 / L2 / L3 | A proposal is accepted (inert, as a first action is too). A YES under the freeze never executes, and the approval does not fire after the freeze lifts. Test restated to that guarantee after probing |
| Sequential double submit | One request |
| **Concurrent double submit (8 threads)** | **Two live requests, 3 of 3 runs; both YES accepted; one executes, one stays `approved`, never executed: F-45** |
| **Crash between request creation and gate start** | **Orphan: YES accepted, nothing executes, no recovery: F-42** |
| YES without step-up; reversibility downgraded by the caller | Refused / still needs step-up |
| Malformed `proposed_action` (`{}`, None, list, missing keys) | Nothing written, but a raw KeyError/AttributeError: F-44 |

## Part 2: `tools/release_gate.py`: does it go red?
| Planted fault | Gate |
|---|---|
| Failing test | **RED** (pytest) |
| Installed `.py` modified / deleted / package uninstalled | **RED** (pins) |
| Live-mode policy (`system_mode: live`, fake `origin` ref) | **RED** (pytest + lane D/E run) |
| Chain hash formula changed in lane D (fake `origin` ref) | **RED** (pytest + `chain 0 ok=False`) |
| **Frozen contract weakened (required field dropped)** | **GREEN: F-46** |
| **Every test skipped (`234 skipped`, rc 0); a deleted failing test** | **GREEN: F-47** |
| **Extra stale `.py`, or replaced installed `schemas/*.json`** | **GREEN: F-48** |
| Vacuity: the gate's own e2e executes no action (`effector 0`) | live-effector check is empty there: F-49 |

**Verdict: the gate goes red on the faults that break code or tests. It cannot go red on four classes (F-46…F-49).** All owners are Agent 01 (gate), plus 04 on F-45 and 05 on F-43.

## Open findings
F-42 (01, P1), F-45 (01+04, P1), F-43 (01+05, P2), F-44 (01, P3), F-46 (01, P1), F-47 (01, P1), F-48 (01, P2), F-49 (01, P2).
