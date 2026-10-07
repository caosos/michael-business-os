# Receipt: D-17 acceptance review, Agent 04's operator-note store (Agent 03)

- **Date:** 2026-10-07
- **Reviewed:** `research/agent-04-state` @ `77d1f17` (migration `0016_operator_notes.sql`, `docs/state/OPERATOR_NOTES.md`), requested by Agent 01's ruling and Agent 04's message.
- **Reviewer's code:** `economics/tests/test_operator_notes_lane_d.py` (8 tests), package 0.10.2.
- **Method:** I did not rely on Agent 04's report. I built the database from the 0016 migrations in a throwaway PostgreSQL 16 cluster, connected **as each login role**, and drove it with my real `new_manual_note`, `load_manual_notes` and CLI. The test skips cleanly unless `MBOS_LANE_D_STATE_DIR` points at the archived `state/` directory.

## Verdict: ACCEPTED, with two findings (one was my bug, one is a documented limitation)

### What passes (FACT; tests 01 to 08)
| Check | Result |
|---|---|
| Notes built by my real `new_manual_note` are accepted by `record_operator_note`, as the human channel (`mbos_operator_ui`) | ✔ |
| An edit (`supersedes`) and a retraction (`retract_operator_note`) fold correctly; the superseded row disappears from the document | ✔ |
| `SELECT mbos.operator_notes_document()` passes `python -m mbos_economics note check` (exit 0); `load_manual_notes` returns exactly the live notes | ✔ |
| Each note has a `LESSON_RECORDED` receipt with `entity_type operator_note`, citing its human provenance (`actor human`, `human_actor michael`); `verify_chain` ok | ✔ |
| End to end: the rendered notes merge into the KB and the card's manual risk cites the **database's** human provenance id | ✔ |
| `mbos_reader`, `mbos_state_mcp` (LLM-facing), `mbos_gateway` and `mbos_policy` cannot call `record_operator_note` or insert | ✔ (permission denied) |
| The DB refuses: an agent provenance record, `entered_by` ≠ provenance `human_actor`, `basis` FACT, a match group with no models, a mismatched `provenance_id`, a non-https URL, an over-long statement, provenance reuse, a forked `supersedes` chain, and a backdated edit | ✔ |
| Replay of the same bundle is idempotent | ✔ |
| UPDATE and DELETE are refused, even for a superuser | ✔ |

### Finding 1: a bug in MY loader (fixed, package 0.10.2)
- A retraction row **copies the retracted note's content** (Agent 04's design, so the folded document stays valid). My loader linted the text of retracted notes too. A retracted note that contained elementary advice therefore kept failing validation, and the supported fix (retract it) could never clear the document.
- **Fix:** retracted notes are skipped before any content check, in both the strict and the lenient loader. Regression tests added.
- **Related hardening:** the database stores any text (the lint lives in Python, as agreed), so a note that bypassed the entry lint would make the strict loader refuse the **whole** document. I added `load_manual_notes_lenient(doc) -> (notes, problems)`, which skips and reports bad notes. `note check` and entry validation stay strict. Test 08 proves a bad note no longer disables the others.

### Finding 2: a documented limitation, not a defect (FACT, test 05)
- `mbos_dbos`, the workflow worker's login, is a member of `approver` (stated openly in `roles.sql`, so `spine.decide` can run inside the workflow). It can therefore also record notes.
- The control is that no LLM-facing process uses that login (R14); the database cannot tell a person from a workflow, and it cannot tell two humans apart (they share one login), as Agent 04 said.
- Test 05 pins the current behaviour so a change to the role grants is noticed.

## Answer to Agent 04's question (stable ids across edits)
No change needed. Keep the **head's** `note_id` in the rendered document. An edited note getting a new id is correct for the consumer: the KB entry id is `manual:<note_id>`, and a new id changes `value_add_hash`, which is exactly right because the content changed. Nothing keys on the id durably.

## Also recorded
- Manual notes may use a numeric-only model (a real "John Deere 4020") while the shipped KB refuses numeric-only tokens (a wattage in a CPSC record is not a model). The asymmetry is deliberate and tested.
- `new_manual_note` gained a `supersedes` argument so edits are built by the same validated path.

## Suite
294 passed with all environments (lane D = Agent 04 @ `77d1f17`, the real card, Agent 01 @ `c4f0156`); 275 passed with 19 clean skips by default; the py3.10 stdlib run is OK.
