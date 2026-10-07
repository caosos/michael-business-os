# Receipt: F-14, "Add what you know about this model" (Michael's own mechanic knowledge)

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-14` (P1; claimed in `6e3a1bb`)
- **Intent:** let Michael put his own model-specific knowledge into the system from the card. It shows on cards as his RECOMMENDATION, behind any sourced recall.
- **Effect:** this branch only. The only write is `spine_d.record_operator_note` (append-only, receipted, human provenance first). No sends.

## Provenance
| Input | Ref |
|---|---|
| Call | `mbos.spine_d.record_operator_note(conn, bundle)` @ `f4c6529` (A-21; installed, not merged) |
| Rules | `mbos_economics.valueadd.new_manual_note` (Agent 03 @ `6a20b91`, v0.10.2) is the single source of validation. `docs/state/OPERATOR_NOTES.md` (Agent 04, D-17) |

## What was built
- Card section "Add what you know about this model". It is a **prompt** when the card shows no lane-sourced (FACT/INFERENCE) model knowledge, and "Add another note" otherwise. Services show a note that notes cover flip equipment. Reference backend shows "needs lane D".
- `POST /item/<id>/note` → `App.add_note`: CSRF, then the **step-up PIN** (unset PIN = refused, fail-closed), then `ux.parse_note`, then `SpineBackend.record_operator_note`. The **author is set by the server** (`App.author`) and is **not a form field**; a posted `author` or `entered_by` is ignored. The PIN is what ties `entered_by` to the authenticated operator (all humans share one DB login).
- Refusals are shown **together, each with its reason** (elementary advice, basis FACT, missing make or model, bad kind, non-https link, over 600 characters, database refusals), the form is re-shown with the typed values, and nothing is stored. "FACT" cannot be chosen: the form has no such option, and a forged `basis=FACT` is refused with the loader's own text (a test checks that text equals 03's).
- `/notes`: read-only list of the current head of each note chain (statement, make/model, how he knows, author, provenance link). **Retraction is not offered**: `spine_d` has no wrapper for `mbos.retract_operator_note` (proposed below).

## Verification (FACT)
- Lane D + lane E suite: 18 passed. Reference suite: 119 passed (`tools/run_tests.sh`).
- A saved note has `entered_by=michael`, `basis=RECOMMENDATION`, a human provenance, and an `operator_note` receipt citing it.
- **End to end with the real lane-C engine and EconomicsEnricher:** a note for Acme ZX9 entered first appears on the NEXT Acme ZX9 card as a RECOMMENDATION risk with Michael's provenance link, and the "no sourced model knowledge" prompt stays.
- Missing CSRF, wrong or empty PIN, unset PIN and a foreign Host are all refused with nothing stored. Hostile text is escaped on `/notes` and the card. A static test pins R14: no workflow or runtime module references `record_operator_note`; the only UI callers are `backend.py` and the single entry point in `server.py`.
- Mutation check: removing the PIN check fails the human-channel test; file restored.
- A pinned test flipped with E-12 (R20): a freeze-refused approved request is now `cancelled_by_freeze` (spine @ `f4c6529`, governance @ `408bcad`).

## Proposed (not started)
- **P-06-14 (lane A):** a `spine_d.retract_operator_note` wrapper (the SQL function exists), so the UI can offer "retract" and "edit" (supersedes).
