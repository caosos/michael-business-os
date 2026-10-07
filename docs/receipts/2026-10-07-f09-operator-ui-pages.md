# Receipt: F-09, Operator UI pages (outcome entry, HOLD backlog, source health)

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-09` (claimed in `20df8db`)
- **Intent:** the 72-hour-plan operator pages, on the human channel only (R14).
- **Effect:** this branch only. The one new write path is `spine.record_outcome` (receipted). No sends, no network.

## Provenance
| Input | Ref |
|---|---|
| Task | READY_QUEUE @ `c23bee8` |
| Spine | `mbos` @ `c23bee8` (git archive, installed, not merged): `spine.record_outcome`; A-16 gapless seq; P-06-9 |
| Source-health format | `origin/research/agent-02-opportunity:src/mbos_discovery/health.py` (`HealthBook.to_json()`, `<data-dir>/health.json`), read via `git show`, not imported |
| Outcome contract | `docs/research/contracts/outcome.schema.json` (frozen v1.0.0) |

## What was built
- **Outcome entry** (card section + `POST /areq/<id>/outcome`):
  - The form opens once the item has settled (ACTED / OUTCOME_RECORDED / FAILED / ARCHIVED / REJECTED) and offers the outcome kinds for its lane plus the generic ones.
  - Numbers are parsed (`$` and `,` accepted) and range-checked.
  - `net_profit` is derived, and LEARN `predicted_vs_actual` pairs come from the item's own economics (sell price, labor hours, win probability).
  - It writes via `spine.record_outcome(recorded_by="michael")`: an OUTCOME_RECORDED receipt and ACTED → OUTCOME_RECORDED. CSRF and Host guards apply.
  - `/outcomes` lists recent outcomes.
- **HOLD backlog** (`/holds`), read-only: held requests sorted by wake time, with lane, action, held-at, wake-on and reason. **Overdue holds are flagged** (the worker should have re-presented them).
- **Source health** (`/sources`), read-only: lane B's `health.json` from `MBOS_SOURCE_HEALTH_FILE` (or `App(health_file=…)`).
  - Sorted worst first; an unknown status ranks as the worst.
  - Frozen sources show their freeze reason, and remote error text is escaped.
  - **STALE** is shown when the file is older than 24 h. A missing, unset or malformed file is reported, never guessed.
  - There is no clear-freeze button: clearing stays a human CLI action on lane B.

## Verification (FACT)
- `tests/test_operator_ui_f09.py` (11 tests) runs on the real spine. A flip_sold entry is stored with `realized` (net 950) and predicted/actual pairs, with a human-actor OUTCOME_RECORDED receipt and the item in OUTCOME_RECORDED. Also covered: validation errors, the pre-settled refusal, CSRF/Host, the backlog listing and overdue flag, source ordering, escaping, staleness and missing-file handling.
- Mutation check: removing the lane check on outcome kinds fails 2 tests. The file was restored.
- Full suite: `96 passed`. This includes the seq-gap finding flipped to a regression test after A-16, and an assertion that ACTION_FAILED intents now name the block reason (P-06-9).

## Note for lane A (proposed P-06-10)
`spine.record_outcome` hard-codes its provenance as `tool_name="mbos.cli.outcome"`, so outcomes entered on the web are labelled as CLI. Proposal: a `channel` parameter, so web entries record `operator_ui.web` instead.
