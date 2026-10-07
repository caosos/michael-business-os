# Receipt: G-07, final re-run of the release candidate and card suites (Agent 07, lane G)

- **Task:** G-07 (P1; the re-run after E-15). **Delivered** `5e66a02`. DRY-RUN only.
- **Release candidate: READY (dry-run scope).** 105 passed, 0 failed, 3 not applicable. The result is identical across two runs; the reference configuration is 104/0; the mock suite is 77/0/1. Report: `docs/qa/RELEASE_CANDIDATE.md` (it states what the verdict does not cover).
- **Card: 232 passed, 11 failed** (down from 148/87 at G-05), every failure mapped. Report: `docs/qa/CARD_ACCEPTANCE.md`.

## Stack (pins in `qa/impl_lane_pins.json`, all via `git archive`; installs verified byte-identical)
- Agent 01 `mbos` `2d4e8dd`
- Agent 04 `c97ba6b` (migrations through 0016), built with lane D's own migrator, roles and pgvector
- Agent 05 `87f0b53` (E-15, policy w1.8), with its whole `policy/` directory
- PostgreSQL 16 + DBOS
- Agent 03's engine `3d6212c` is **not** in this stack; the scorer is 01's placeholder.

## Verified closed (each by a test that failed before and passes now)
| Finding | Evidence |
|---|---|
| F-40 | A YES without the step-up the policy requires is refused at decision time (`test_a_yes_the_policy_will_refuse_is_refused_when_it_is_given`) |
| F-41 | Policy data: no agent holds `money.payment.send`, `price.change` or `commit.external`. The live publishing request is stamped `proposed_by: agent-07-marketing`, and email falls back to the spine identity |
| F-24, F-25, F-22, F-23 | As at G-06, still green on the new heads |
| Card F-26, F-29, F-32…F-38 | The pure and backend card suites pass for them (fuzz 300/300 without a crash; hostile text cannot forge sections; the hash is order-independent and checked) |

## Open (card; none is a safety invariant), with owners
| ID | Owner | What |
|---|---|---|
| F-36 | 01 (+02) | `discover` has no per-record isolation around `normalize_step`: one NUL aborts the batch (the scrub and savepoint in `ingest` never run) |
| F-30 | 01 + 03 | 3 of 42 elementary phrasings still pass ("Look for any damage", "Check the carburetor", "Check the fluids"); no model-specific marker in the contract; a sourced `why` line is not linted |
| F-28 | 01 | `posted_at`/`updated_at` accept 'not a date' and a 2999 date as FACT |
| F-31 | 01 | The headline 'Contact Sent / [now: CONTACT SENT]' has no dry-run marker (the row and the recommendation do) |
| F-27 | 01 | A risk with a malformed `source` yields a card its own `validate_card` rejects |
| F-39 | — | ACCEPTED by R25 (HOLD means 'wait' on a card) |

## Mistakes and corrections during this run (all mine, caught by checks I built)
- **A silent stale install.** After a re-pin, pip kept the OLD `mbos` under the same version string; a first card run therefore showed the old defects. I added `mbos_qa.pincheck` (compares every installed file with the pinned commit and refuses to run on a mismatch) and `python -m mbos_qa install-pins`, and re-ran everything.
  - Root cause: a stale `build/` directory in the extracted tree.
  - Earlier runs: the G-06 `mbos` install was not byte-verified at the time. The behaviours observed at G-06 (R21/F-23 fixed, the E-13 gateway behaviour) show the new code was in use, and everything has since been re-run on verified installs.
- **Wrong database in my ledger-mode helper.** 01's A-18 change routes `spine_d.set_kill_switch` through the SHARED runtime's governance object, so my fresh ledger DBs stayed frozen and an interim RC run reported six spurious failures and "safety BROKEN". Diagnosed from the guard result (`G7:PANIC_L3_FROZEN`), fixed by controlling PANIC through each ledger DB's own governance object. The interim report was never committed.
- **Tests overtaken by design changes.** Two denial tests assumed a `rejected` request; under F-41 no request is created. They now assert what matters (no live request, item not awaiting Michael).
- **Rename-driven edits.** An earlier slice of my own runner file deleted the card block; restored from the last commit.

## Not covered
Operator UI rendering of the card; Agent 03's engine and lane B's real normalizer (the stack uses 01's fixture ones); live providers; LiteLLM; real egress cut.
